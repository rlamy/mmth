from __future__ import annotations

import functools
import inspect
import itertools
import weakref
from abc import get_cache_token
from collections.abc import Mapping
from types import MappingProxyType, MethodType, UnionType
from typing import (
    Any,
    Callable,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

# Not the implementation's own type: implementations are all named `_`, so
# type checkers would treat a subclass's `_` as overriding its base's.
_Registered = Any
_TypeSpec = type | UnionType


def _union_members(t: Any) -> tuple[Any, ...]:
    """`t`'s members if it's a union (`int | str`, `Union[int, str]`),
    else just `(t,)`."""
    if get_origin(t) in (Union, UnionType):
        return get_args(t)
    return (t,)


def _is_type_spec(t: Any) -> bool:
    """True for a type, or a union of types."""
    return all(isinstance(m, type) for m in _union_members(t))


def _is_function(obj: Any) -> bool:
    """True for anything registrable as an implementation: a non-type
    callable, or a `classmethod`/`staticmethod` object."""
    if isinstance(obj, (classmethod, staticmethod)):
        return True
    return callable(obj) and not _is_type_spec(obj)


def _parse_decorator_args(
    caller: str, args: tuple[Any, ...], func: Any = None
) -> tuple[tuple[Any, ...], Any]:
    """Split decorator arguments into `(types, func)`, with `func` None when
    they're just types (`@f.register(*types)`)."""
    if func is None and args and _is_function(args[-1]):
        args, func = args[:-1], args[-1]
    for t in args:
        if not _is_type_spec(t):
            raise TypeError(f"{caller} expected types, got {t!r}")
    return args, func


def _expand_unions(types: tuple[Any, ...]) -> list[tuple[type, ...]]:
    """Every signature a (possibly union-containing) signature stands for."""
    return list(itertools.product(*(_union_members(t) for t in types)))


class Multimethod:
    # Slots keep calls fast despite update_wrapper's instance attributes
    # (see docs/performance.md).
    __slots__ = (
        "_registry",
        "_default",
        "_default_signatures",
        "_skip",
        "_parent",
        "_binds_class",
        "_abc_token",
        "_cache",
        "_children",
        "__dict__",
        "__weakref__",
    )

    def __init__(
        self,
        func: Callable[..., Any] | None = None,
        *types: _TypeSpec,
        _skip: int = 0,
        _parent: Multimethod | None = None,
        _binds_class: bool = False,
    ) -> None:
        # The underscored arguments are internal, set by `dispatchmethod`
        # and `.inherit()`.
        self._registry: dict[tuple[type, ...], Any] = {}
        self._default: Any = None
        self._default_signatures: list[tuple[type, ...]] = []
        self._skip = _skip
        self._parent = _parent
        self._binds_class = _binds_class
        # Set once an ABC is registered, since `SomeABC.register(cls)` can
        # change `issubclass` results after they were cached.
        self._abc_token: object | None = None
        self._cache: dict[type | tuple[type, ...], Callable[..., Any]] = {}
        self._children: list[weakref.ReferenceType[Multimethod]] = []
        if func is None:
            return
        _parse_decorator_args("Multimethod()", types)
        functools.update_wrapper(self, func)
        self.__isabstractmethod__ = getattr(func, "__isabstractmethod__", False)
        self._default = func
        self._default_signatures = _expand_unions(
            types or self._param_types(func, strict=False)
        )
        for sig in self._default_signatures:
            if sig:
                self._store(sig, func)

    def _unwrap(self, func: Any) -> tuple[Callable[..., Any], int]:
        """The plain function behind `func`, and how many of its leading
        parameters (`self`/`cls`) aren't dispatched on."""
        if isinstance(func, staticmethod):
            return func.__func__, 0
        if isinstance(func, classmethod):
            return func.__func__, 1
        return func, self._skip

    def _param_types(self, func: Any, *, strict: bool) -> tuple[Any, ...]:
        """Infer a registry key from `func`'s annotations, past `self`/`cls`.
        A missing or unresolvable annotation counts as `object`, or raises
        `TypeError` if `strict`."""
        func, skip = self._unwrap(func)
        try:
            params = list(inspect.signature(func).parameters.values())
        except (ValueError, TypeError):
            params = []
        try:
            hints = get_type_hints(func)
        except NameError:  # a forward reference that doesn't resolve yet
            hints = {}
        types = []
        for p in params[skip:]:
            annotation = hints.get(p.name, p.annotation)
            # `Parameter.empty` (no annotation) is itself a class
            if annotation is not p.empty and _is_type_spec(annotation):
                types.append(annotation)
            elif strict:
                raise TypeError(
                    f"register() found no type annotation on parameter "
                    f"{p.name!r} of {func.__qualname__}; annotate it or pass "
                    f"the types explicitly"
                )
            else:
                types.append(object)
        if strict and not types:
            raise TypeError(
                f"register() found no parameters to dispatch on in "
                f"{func.__qualname__}; pass the types explicitly"
            )
        return tuple(types)

    def _default_signatures_in_chain(self) -> list[tuple[type, ...]]:
        mm: Multimethod | None = self
        while mm is not None:
            if mm._default is not None:
                return mm._default_signatures
            mm = mm._parent
        return []

    def _store(self, sig: tuple[type, ...], func: Any) -> None:
        self._registry[sig] = func
        if self._abc_token is None and any(
            hasattr(t, "__abstractmethods__") for t in sig
        ):
            self._watch_abc_cache()
        self._invalidate_cache()

    def _register(self, caller: str, types: tuple[Any, ...], func: Any) -> None:
        sigs = _expand_unions(types or self._param_types(func, strict=True))
        defaults = [
            d for d in self._default_signatures_in_chain() if len(d) == len(sigs[0])
        ]
        for sig in sigs:
            if defaults and not any(
                all(issubclass(t, dt) for t, dt in zip(sig, d)) for d in defaults
            ):
                expected = " or ".join(str(d) for d in defaults)
                raise TypeError(
                    f"{caller} expected subclasses of the default "
                    f"implementation's types {expected}, got {sig}"
                )
        for sig in sigs:
            self._store(sig, func)

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
        """Register an implementation, for the given types or, if none are
        given, its parameters' annotations (all of which must be types).

        Use either bare, `@f.register`, or with explicit types,
        `@f.register(T1, T2)`, which take precedence over annotations; or
        functools-style, `f.register(T, func)`. A union type (`int | str`)
        registers the implementation for each member. With a default
        implementation, the types must be subclasses of its annotations.
        Also accepts a `classmethod` or `staticmethod`, for a method.
        """
        types, func = _parse_decorator_args("register()", types, func)
        if func is not None:
            return self.register(*types)(func)

        def decorator(func: Any) -> _Registered:
            if not _is_function(func):
                raise TypeError(f"register() expected a function, got {func!r}")
            self._register("register()", types, func)
            return func

        return decorator

    def _watch_abc_cache(self) -> None:
        self._abc_token = get_cache_token()
        for ref in self._children:
            child = ref()
            if child is not None:
                child._watch_abc_cache()

    def _invalidate_cache(self) -> None:
        self._cache.clear()
        alive = []
        for ref in self._children:
            child = ref()
            if child is not None:
                child._invalidate_cache()
                alive.append(ref)
        self._children = alive

    def inherit(self) -> Multimethod:
        """A multimethod for a subclass, inheriting this one's implementations.
        Its own registrations are always tried first, whatever their types,
        like a method override (see docs/methods.md):

            class Sub(Base):
                visit = Base.visit.inherit()

                @visit.register(SomeType)
                def _(self, x):
                    ...
                    return super().visit(x)
        """
        child = Multimethod(
            _skip=self._skip, _parent=self, _binds_class=self._binds_class
        )
        if self._abc_token is not None:
            child._watch_abc_cache()
        self._children.append(weakref.ref(child))
        return child

    def __getitem__(self, types: type | tuple[type, ...]) -> Callable[..., Any]:
        if not isinstance(types, tuple):
            types = (types,)
        if types in self._registry:
            return self._registry[types]
        raise KeyError(f"No implementation registered for {types}")

    def __setitem__(
        self, types: _TypeSpec | tuple[_TypeSpec, ...], func: Any
    ) -> None:
        if not isinstance(types, tuple):
            types = (types,)
        types, _ = _parse_decorator_args("__setitem__()", types)
        self._register("__setitem__()", types, func)

    @property
    def registry(self) -> Mapping[Any, Any]:
        """A read-only view of the registered implementations, keyed by
        signature - a bare type for a single argument, as in
        `functools.singledispatch`, else a tuple of types."""
        return MappingProxyType(
            {sig[0] if len(sig) == 1 else sig: f for sig, f in self._registry.items()}
        )

    def dispatch(self, *types: type) -> Any:
        """The implementation that a call with arguments of these types would
        run (without calling it), as `functools.singledispatch`'s."""
        return self._lookup(types)

    def _is_more_specialized(
        self, sig_a: tuple[type, ...], sig_b: tuple[type, ...]
    ) -> bool:
        """Returns True if sig_a is strictly more specialized than sig_b."""
        more_specific = False
        for type_a, type_b in zip(sig_a, sig_b):
            if issubclass(type_a, type_b):
                if not issubclass(type_b, type_a):
                    more_specific = True
            else:
                return False
        return more_specific

    def _find_most_specialized(
        self, types: tuple[type, ...]
    ) -> Callable[..., Any] | None:
        """Find the most specialized matching signature, or raise on ambiguity."""
        candidates = [
            (sig, func) for sig, func in self._registry.items()
            if self._match_signature(sig, types)
        ]

        if not candidates:
            return None

        # Not a running "best so far": a later candidate can dominate two
        # earlier, mutually incomparable ones.
        maximal = [
            (sig, func)
            for sig, func in candidates
            if not any(
                other_sig != sig and self._is_more_specialized(other_sig, sig)
                for other_sig, _ in candidates
            )
        ]

        if len(maximal) > 1:
            raise TypeError(
                f"Ambiguous dispatch for types {types}: "
                f"matches multiple signatures"
            )

        return maximal[0][1]

    def _resolve(self, key: type | tuple[type, ...]) -> Callable[..., Any]:
        """The implementation to call for `key` (a bare type for one argument,
        else a tuple of types), adapted by `_callable` and cached."""
        if self._abc_token is not None and self._abc_token != get_cache_token():
            self._abc_token = get_cache_token()
            self._cache.clear()
        try:
            return self._cache[key]
        except KeyError:
            pass
        arg_types = key if isinstance(key, tuple) else (key,)
        func = self._callable(self._lookup(arg_types))
        self._cache[key] = func
        return func

    def _callable(self, func: Any) -> Any:
        """`func` as called with this multimethod's arguments, including a
        leading `self`/`cls` for a method: a `staticmethod` drops it, and a
        `classmethod` gets the instance's class in its place (or the class
        itself, already, for a `classmethod` dispatchmethod)."""
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

    def _lookup(self, arg_types: tuple[type, ...]) -> Any:
        """The registered implementation for `arg_types`, uncached."""
        if arg_types in self._registry:
            return self._registry[arg_types]

        func = self._find_most_specialized(arg_types)
        if func is not None:
            return func

        if self._parent is not None:
            return self._parent._lookup(arg_types)

        if self._default is not None:
            return self._default

        raise TypeError(f"No matching implementation for types {arg_types}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # Fast path for one dispatched argument (see docs/performance.md).
        # `__class__`, not `type()`, so proxies like `Mock(spec=cls)`
        # dispatch as that class.
        key: type | tuple[type, ...]
        if len(args) - self._skip == 1:
            key = args[self._skip].__class__
        else:
            key = tuple(arg.__class__ for arg in args[self._skip:])
        return self._resolve(key)(*args, **kwargs)

    def __get__(self, instance: object | None, owner: type | None = None) -> Any:
        if self._binds_class:
            return MethodType(self, owner if owner is not None else type(instance))
        if instance is None or self._skip == 0:
            return self
        return MethodType(self, instance)

    def _match_signature(self, sig: tuple[type, ...], types: tuple[type, ...]) -> bool:
        if len(sig) != len(types):
            return False
        for sig_type, arg_type in zip(sig, types):
            if not isinstance(sig_type, type):
                return False
            if not issubclass(arg_type, sig_type):
                return False
        return True


class _PendingInherit:
    """Returned by `inherit()`: collects registrations until `__set_name__`
    can find the base multimethod, then replaces itself with its child."""

    def __init__(self) -> None:
        self._registrations: list[tuple[tuple[Any, ...], Any]] = []

    def register(self, *types: Any, func: Any = None) -> Any:
        # Same forms as `Multimethod.register`; annotations are only read
        # once `__set_name__` has the real multimethod (and its `_skip`).
        types, func = _parse_decorator_args("register()", types, func)
        if func is not None:
            self._registrations.append((types, func))
            return func

        def decorator(func: Any) -> Any:
            self._registrations.append((types, func))
            return func

        return decorator

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
    """Like `Base.visit.inherit()`, but finds the base multimethod by looking
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


# Types first, as for `Multimethod.register`; mypy flags the overlap (a
# type is callable) even though that order resolves it correctly.
@overload
def dispatch(  # type: ignore[overload-overlap]
    *types: _TypeSpec,
) -> Callable[[Callable[..., Any]], Multimethod]: ...
@overload
def dispatch(func: Callable[..., Any], /) -> Multimethod: ...
def dispatch(*types: Any) -> Any:
    """Turn a function into a multimethod, with it as the default
    implementation, called whenever no registered signature matches.

    Use either bare, `@dispatch`, or with explicit types, `@dispatch(T1, T2)`,
    which take precedence over annotations, same as `.register()`. Unlike
    `.register()`, a parameter without a type annotation counts as `object`.
    """
    types, func = _parse_decorator_args("dispatch()", types)

    def decorator(func: Callable[..., Any]) -> Multimethod:
        if not callable(func) or _is_type_spec(func):
            raise TypeError(f"dispatch() expected a function, got {func!r}")
        return Multimethod(func, *types)

    return decorator(func) if func is not None else decorator


@overload
def dispatchmethod(  # type: ignore[overload-overlap]
    *types: _TypeSpec,
) -> Callable[[Any], Multimethod]: ...
@overload
def dispatchmethod(func: Any, /) -> Multimethod: ...
def dispatchmethod(*types: Any) -> Any:

    """Like `dispatch`, but decorates a method instead of a function, in the
    same two forms (`@dispatchmethod` or `@dispatchmethod(T1, T2)`).

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
    types, func = _parse_decorator_args("dispatchmethod()", types)

    def decorator(func: Any) -> Multimethod:
        if not _is_function(func):
            raise TypeError(f"dispatchmethod() expected a function, got {func!r}")
        if isinstance(func, staticmethod):
            return Multimethod(func, *types)
        return Multimethod(
            func, *types, _skip=1, _binds_class=isinstance(func, classmethod)
        )

    return decorator(func) if func is not None else decorator
