"""Multimethods: functions dispatched on the types of their arguments."""

import functools
import inspect
import itertools
from collections.abc import Mapping
from types import MappingProxyType, MethodType, NoneType, UnionType
from typing import (
    Annotated,
    Any,
    Callable,
    Self,
    TypeVar,
    Union,
    _SpecialForm,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from mmth.typemap import TypeMap

# Not the implementation's own type: implementations are all named `_`, so
# type checkers would treat a subclass's `_` as overriding its base's.
_Registered = Any
# `_SpecialForm` is how mypy types `Optional[X]`, `Union[...]`, `Any` etc.
_TypeSpec = type | UnionType | TypeVar | _SpecialForm | None


def _classes(t: Any) -> tuple[type, ...] | None:
    """Return the classes that type annotation `t` stands for.

    Return None if it can't be dispatched on, like a parameterized generic,
    whose parameters `isinstance` can't check.
    """
    if t is None:
        return (NoneType,)
    if t is Any:
        return (object,)
    if isinstance(t, TypeVar):
        if t.__bound__ is not None:
            return _classes(t.__bound__)
        if t.__constraints__:
            return _classes(Union[t.__constraints__])
        return (object,)
    origin = get_origin(t)
    if origin is Annotated:
        return _classes(get_args(t)[0])
    if origin in (Union, UnionType):
        members = [_classes(m) for m in get_args(t)]
        if any(m is None for m in members):
            return None
        return tuple(dict.fromkeys(c for m in members if m for c in m))
    if isinstance(t, type) and origin is None:
        return (t,)
    return None


def _is_function(obj: Any) -> bool:
    """Return whether `obj` can be registered as an implementation.

    That is, a callable that isn't a type or other annotation (e.g.
    `list[int]`, which is callable too), or a `classmethod`/`staticmethod`.
    """
    if isinstance(obj, (classmethod, staticmethod)):
        return True
    return callable(obj) and not isinstance(obj, type) and get_origin(obj) is None


def _parse_decorator_args(
    caller: str, args: tuple[Any, ...], func: Any = None
) -> tuple[tuple[Any, ...], Any]:
    """Split decorator arguments into `(types, func)`.

    `func` is None when they're just types (`@f.register(*types)`).
    """
    if func is None and args and _is_function(args[-1]):
        args, func = args[:-1], args[-1]
    for t in args:
        if _classes(t) is None:
            raise TypeError(f"{caller} expected types, got {t!r}")
    return args, func


def _expand(types: tuple[Any, ...]) -> list[tuple[type, ...]]:
    """Return the signatures of classes that type annotations `types` mean."""
    return list(itertools.product(*(_classes(t) or () for t in types)))


class Multimethod:
    """A function whose implementation is chosen by its arguments' types.

    Usually created with `dispatch` or `dispatchmethod`. Implementations are
    added with `register()` or `f[types] = impl`, and looked up with
    `f[types]`, `dispatch()` or `registry`; `inherit()` chains a subclass's
    own multimethod to this one.
    """

    # Slots keep calls fast even though update_wrapper accesses `__dict__`
    # (see docs/performance.md).
    __slots__ = (
        "_registry",
        "_skip",
        "_binds_class",
        "__dict__",
        "__weakref__",
    )

    def __init__(
        self,
        func: Callable[..., Any] | None = None,
        *,
        _skip: int = 0,
        _parent: Self | None = None,
        _binds_class: bool = False,
    ) -> None:
        """Create a multimethod with `func` as its default implementation.

        `func` is registered for `object` at every parameter, whatever its
        annotations. Without `func`, a call matching no registration raises
        `NoMatchError`.
        The underscored arguments are internal, set by `dispatchmethod` and
        `inherit()`.
        """
        self._skip = _skip
        self._binds_class = _binds_class
        parent = _parent._registry if _parent is not None else None
        if func is None:
            self._registry: TypeMap = TypeMap(parent, adapt=self._callable)
            return
        functools.update_wrapper(self, func)
        self.__isabstractmethod__ = getattr(func, "__isabstractmethod__", False)
        self._registry = TypeMap(parent, default=func, adapt=self._callable)
        arity = len(self._params(func))
        if arity:
            self._registry[(object,) * arity] = func

    def _unwrap(self, func: Any) -> tuple[Callable[..., Any], int]:
        """Return `func`'s plain function, and how many leading params to skip."""
        if isinstance(func, staticmethod):
            return func.__func__, 0
        if isinstance(func, classmethod):
            return func.__func__, 1
        return func, self._skip

    def _params(self, func: Any) -> list[inspect.Parameter]:
        """Return `func`'s parameters past `self`/`cls`, if it has a signature."""
        func, skip = self._unwrap(func)
        try:
            return list(inspect.signature(func).parameters.values())[skip:]
        except (ValueError, TypeError):
            return []

    def _param_types(self, func: Any) -> tuple[Any, ...]:
        """Infer a registry key from `func`'s annotations, past `self`/`cls`.

        Raise `TypeError` for a missing annotation, or one that can't be
        dispatched on.
        """
        params = self._params(func)
        func, _ = self._unwrap(func)
        try:
            hints = get_type_hints(func)
        except NameError:  # a forward reference that doesn't resolve yet
            hints = {}
        types = []
        for p in params:
            annotation = hints.get(p.name, p.annotation)
            # `Parameter.empty` (no annotation) is itself a class
            if annotation is not p.empty and _classes(annotation) is not None:
                types.append(annotation)
            elif annotation is p.empty:
                raise TypeError(
                    f"register() found no type annotation on parameter "
                    f"{p.name!r} of {func.__qualname__}; annotate it or pass "
                    f"the types explicitly"
                )
            else:
                raise TypeError(
                    f"register() can't dispatch on parameter {p.name!r} of "
                    f"{func.__qualname__}, annotated {annotation!r}; pass the "
                    f"types explicitly"
                )
        if not types:
            raise TypeError(
                f"register() found no parameters to dispatch on in "
                f"{func.__qualname__}; pass the types explicitly"
            )
        return tuple(types)

    def _register(self, types: tuple[Any, ...], func: Any) -> None:
        for sig in _expand(types or self._param_types(func)):
            self._registry[sig] = func

    # The types-first order matters: a type is itself callable, so
    # `register(int)` would otherwise match the bare-decorator overload.
    @overload
    def register(self, *types: _TypeSpec) -> Callable[[Any], _Registered]: ...
    @overload
    def register(self, func: Any, /) -> _Registered: ...
    @overload
    def register(self, cls: _TypeSpec, func: Any, /) -> _Registered: ...
    @overload
    def register(self, *types: _TypeSpec, func: Any) -> _Registered: ...
    def register(self, *types: Any, func: Any = None) -> Any:
        """Register an implementation for the given types, or its annotations.

        Without types, every parameter must be annotated with a type. Use
        either bare, `@f.register`, or with explicit types,
        `@f.register(T1, T2)`, which take precedence over annotations; or
        functools-style, `f.register(T, func)`. A union type (`int | str`)
        registers the implementation for each member. Also accepts a `classmethod` or `staticmethod`, for a method.
        """
        types, func = _parse_decorator_args("register()", types, func)

        def decorator(func: Any) -> _Registered:
            if not _is_function(func):
                raise TypeError(f"register() expected a function, got {func!r}")
            self._register(types, func)
            return func

        return decorator(func) if func is not None else decorator

    def inherit(self) -> Self:
        """Return a multimethod for a subclass, inheriting this one's.

        Its own registrations are always tried first, whatever their types,
        like a method override (see docs/methods.md):

            class Sub(Base):
                visit = Base.visit.inherit()

                @visit.register(SomeType)
                def _(self, x):
                    ...
                    return super().visit(x)
        """
        return type(self)(
            _skip=self._skip, _parent=self, _binds_class=self._binds_class
        )

    def _as_types(
        self, caller: str, types: _TypeSpec | tuple[_TypeSpec, ...]
    ) -> tuple[Any, ...]:
        """Normalize a `__getitem__`/`__setitem__` type-or-tuple argument."""
        if not isinstance(types, tuple):
            types = (types,)
        types, _ = _parse_decorator_args(caller, types)
        return types

    def __getitem__(
        self, types: _TypeSpec | tuple[_TypeSpec, ...]
    ) -> Callable[..., Any]:
        """Return the implementation registered for exactly `types`.

        A single type stands for a one-element tuple. For a union, the same
        implementation must be registered for every member. Raise `KeyError`
        if there's no such implementation.
        """
        types = self._as_types("__getitem__()", types)
        impls = [self._registry.get(sig) for sig in _expand(types)]
        if impls[0] is not None and all(impl is impls[0] for impl in impls):
            return impls[0]
        raise KeyError(f"No implementation registered for {types}")

    def __setitem__(
        self, types: _TypeSpec | tuple[_TypeSpec, ...], func: Any
    ) -> None:
        """Register `func` for `types`, a single type or a tuple of them."""
        types = self._as_types("__setitem__()", types)
        self._register(types, func)

    @property
    def registry(self) -> Mapping[Any, Any]:
        """Read-only mapping of the registered implementations, by signature.

        Keyed by a bare type for a single argument, as in
        `functools.singledispatch`, else by a tuple of types.
        """
        return MappingProxyType(
            {sig[0] if len(sig) == 1 else sig: f for sig, f in self._registry.items()}
        )

    def dispatch(self, *types: _TypeSpec) -> Any:
        """Return the implementation a call with arguments of `types` would run."""
        types, _ = _parse_decorator_args("dispatch()", types)
        sigs = _expand(types)
        if len(sigs) != 1:
            raise TypeError(f"dispatch() expected one class per argument, got {types}")
        arg_types = sigs[0]
        key: type | tuple[type, ...] = arg_types[0] if len(arg_types) == 1 else arg_types
        return self._registry.lookup(key)

    def _callable(self, func: Any) -> Any:
        """Adapt `func` to be called with this multimethod's own arguments.

        For a method, those start with `self`/`cls`: a `staticmethod` drops
        it, and a `classmethod` gets the instance's class in its place (or
        the class itself, already, for a `classmethod` dispatchmethod).
        """
        if isinstance(func, staticmethod):
            static = func.__func__
            if not self._skip:
                return static
            return lambda _self, *args, **kwargs: static(*args, **kwargs)
        if isinstance(func, classmethod) and self._skip:
            method = func.__func__
            if self._binds_class:
                return method
            return lambda obj, *args, **kwargs: method(type(obj), *args, **kwargs)
        return func

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the implementation chosen by the arguments' types."""
        # Fast path for one dispatched argument (see docs/performance.md).
        # `__class__`, not `type()`, so proxies like `Mock(spec=cls)`
        # dispatch as that class.
        key: type | tuple[type, ...]
        if len(args) - self._skip == 1:
            key = args[self._skip].__class__
        else:
            key = tuple(arg.__class__ for arg in args[self._skip:])
        return self._registry.lookup(key)(*args, **kwargs)

    def __get__(self, instance: object | None, owner: type | None = None) -> Any:
        """Bind to `instance` as a method, or to `owner` for a classmethod."""
        if self._binds_class:
            return MethodType(self, owner if owner is not None else type(instance))
        if instance is None or self._skip == 0:
            return self
        return MethodType(self, instance)



class _PendingInherit:
    """Placeholder returned by `inherit()`, until its class is created.

    It collects registrations until `__set_name__` can find the base
    multimethod, then replaces itself with its child.
    """

    def __init__(self) -> None:
        self._registrations: list[tuple[tuple[Any, ...], Any]] = []

    def register(self, *types: Any, func: Any = None) -> Any:
        # Same forms as `Multimethod.register`; annotations are only read
        # once `__set_name__` has the real multimethod (and its `_skip`).
        types, func = _parse_decorator_args("register()", types, func)

        def decorator(func: Any) -> Any:
            self._registrations.append((types, func))
            return func

        return decorator(func) if func is not None else decorator

    def __set_name__(self, owner: type, name: str) -> None:
        parent = None
        for base in owner.__mro__[1:]:
            if name in vars(base):
                parent = vars(base)[name]
                break
        if not isinstance(parent, Multimethod):
            raise TypeError(
                f"inherit() found no base class of {owner.__name__} "
                f"defining a Multimethod named {name!r}"
            )
        dispatcher = parent.inherit()
        for types, func in self._registrations:
            dispatcher.register(*types, func=func)
        setattr(owner, name, dispatcher)


def inherit() -> Multimethod:
    """Return a subclass's multimethod, inheriting its base class's.

    Like `Base.visit.inherit()`, but finds the base multimethod by looking
    up the same attribute name on the base classes, as `super()` would:

        class Sub(Base):
            visit = inherit()

            @visit.register(SomeType)
            def _(self, x):
                ...
                return super().visit(x)

    Use `Base.visit.inherit()` directly when that lookup isn't what you want.
    """
    # Typed as the Multimethod it becomes at class creation, so type checkers
    # accept the attribute and its `.register()` calls (cf. dataclasses.field).
    return _PendingInherit()  # type: ignore[return-value]


def dispatch(func: Callable[..., Any]) -> Multimethod:
    """Turn a function into a multimethod, with it as the default.

    The default implementation is called whenever no registered signature
    matches, and is registered for `object` at every parameter: as with
    `functools.singledispatch`, its annotations are ignored.
    """
    if not _is_function(func):
        raise TypeError(f"dispatch() expected a function, got {func!r}")
    return Multimethod(func)


def dispatchmethod(func: Any) -> Multimethod:
    """Turn a method into a multimethod, as `dispatch` does a function.

    `self` is bound automatically via the descriptor protocol and excluded
    from dispatch, so `.register(*types)` only lists the types of the
    remaining arguments. As with `functools.singledispatchmethod`, either
    the method itself or any registered implementation can also be a
    `classmethod` or `staticmethod` (applied *below* the decorator).

    A subclass can replace a single implementation for itself, without
    touching the base class, via `inherit()` (see `inherit` and
    `Multimethod.inherit`).

    ```python
    class Evaluator:
        @dispatchmethod
        def visit(self, node: Node):
            raise TypeError(f"no visit for {type(node).__name__}")

        @visit.register(Num)
        def _(self, node):
            return node.value

        @visit.register(Add)
        def _(self, node):
            return self.visit(node.left) + self.visit(node.right)
    ```
    """
    if not _is_function(func):
        raise TypeError(f"dispatchmethod() expected a function, got {func!r}")
    if isinstance(func, staticmethod):
        return Multimethod(func)
    return Multimethod(func, _skip=1, _binds_class=isinstance(func, classmethod))
