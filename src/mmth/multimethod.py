"""Multimethods: functions dispatched on the types of their arguments."""

import functools
import inspect
import itertools
import operator
import sys
from collections.abc import Mapping
from types import MappingProxyType, MethodType, NoneType, SimpleNamespace, UnionType
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

from mmth.typemap import (
    AmbiguousMatchError,
    ChainTypeMap,
    NoMatchError,
    TypeMap,
    _count,
    _format_types,
    _type_name,
)

# Not the implementation's own type: implementations are all named `_`, so
# type checkers would treat a subclass's `_` as overriding its base's.
_Registered = Any
# `_SpecialForm` is how mypy types `Optional[X]`, `Union[...]`, `Any` etc.
_TypeSpec = type | UnionType | TypeVar | _SpecialForm | None
# How many registered signatures a `NoMatchError` lists.
_MAX_LISTED = 5

# Annotations are evaluated lazily since Python 3.14, so reading a signature
# can raise `NameError`; leave the ones that don't resolve yet as
# `ForwardRef`s.
_SIGNATURE_OPTIONS: dict[str, Any] = {}
if sys.version_info >= (3, 14):
    from annotationlib import Format

    _SIGNATURE_OPTIONS["annotation_format"] = Format.FORWARDREF


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


# What evaluating an annotation that doesn't resolve (yet) raises.
_UNRESOLVED = (NameError, AttributeError, SyntaxError)


def _resolve(func: Any, name: str, annotation: Any) -> Any:
    """Evaluate the annotation of `func`'s parameter `name`.

    As `get_type_hints(func)` does, forward references in it included, but
    for this annotation alone, so that others that don't resolve don't
    matter. Raise `TypeError` if it doesn't resolve.
    """
    holder = SimpleNamespace(__annotations__={name: annotation})
    try:
        return get_type_hints(holder, globalns=getattr(func, "__globals__", None))[name]
    except _UNRESOLVED as e:
        # Shown when it's all a forward reference, not just part of it.
        source = getattr(annotation, "__forward_arg__", annotation)
        shown = f" {source!r}" if isinstance(source, str) else ""
        advice = "define it before registering, or pass the types explicitly"
        # Registering in a class body, on that class.
        scope = getattr(func, "__qualname__", "").split(".")[-2:-1]
        if scope and getattr(e, "name", None) == scope[0]:
            advice = (
                f"{scope[0]} is still being defined, so register this after the "
                f"class body instead"
            )
        raise TypeError(
            f"register() can't resolve the annotation{shown} of parameter "
            f"{name!r} of {_describe(func)} ({e}); {advice}"
        ) from None


def _describe(func: Any) -> str:
    """Return how error messages show `func`: its qualname and location.

    Implementations are usually all named `_`, so only the location tells
    them apart.
    """
    func = inspect.unwrap(func)
    if isinstance(func, functools.partial):
        return f"functools.partial({_describe(func.func)})"
    name = getattr(func, "__qualname__", None)
    # PyPy's builtins have code, without a location.
    code: Any = getattr(func, "__code__", None)
    filename = getattr(code, "co_filename", None)
    if name is None or filename is None:
        return repr(func)
    return f"{name} at {filename}:{code.co_firstlineno}"


def _not_a_type_hint(t: Any) -> str:
    """Return a hint at what to dispatch on instead of `t`, if any."""
    origin = get_origin(t)
    # Before checking for a class, as `Union` is one since Python 3.14.
    if origin in (Union, UnionType, Annotated):
        members = get_args(t)[:1] if origin is Annotated else get_args(t)
        return next(filter(None, map(_not_a_type_hint, members)), "")
    if isinstance(origin, type):
        return (
            f" (isinstance can't check a parameterized generic's parameters; "
            f"use {_type_name(origin)})"
        )
    if isinstance(t, str):
        return " (only annotations are evaluated; pass the class itself)"
    return ""


def _is_implementation(obj: Any) -> bool:
    """Return whether `obj` can be registered as an implementation."""
    return callable(obj) or isinstance(obj, (classmethod, staticmethod))


def _is_function(obj: Any) -> bool:
    """Return whether `obj` is an implementation rather than a type.

    That is, one that isn't a type or other annotation (e.g. `list[int]`,
    which is callable too).
    """
    return (
        _is_implementation(obj)
        and not isinstance(obj, type)
        and get_origin(obj) is None
    )


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
            raise TypeError(f"{caller} expected types, got {t!r}{_not_a_type_hint(t)}")
    return args, func


def _register_with(
    add: Callable[[tuple[Any, ...] | None, Any], None],
    types: tuple[Any, ...],
    func: Any,
    check: Callable[[tuple[Any, ...]], None],
) -> Any:
    """Handle `register()`'s arguments, registering through `add(types, func)`.

    `add` gets None for types to take from the annotations. Return `func`,
    or without it a decorator that registers the function, once
    `check(types)` has accepted any types: the decorator may never be applied.
    """
    types, func = _parse_decorator_args("register()", types, func)
    if func is None and types:
        check(types)

    def decorator(func: Any) -> Any:
        if not _is_implementation(func):
            raise TypeError(f"register() expected a function, got {func!r}")
        add(types or None, func)
        return func

    return decorator(func) if func is not None else decorator


def _as_types(caller: str, types: _TypeSpec | tuple[_TypeSpec, ...]) -> tuple[Any, ...]:
    """Normalize a `__getitem__`/`__setitem__` type-or-tuple argument."""
    if not isinstance(types, tuple):
        types = (types,)
    types, _ = _parse_decorator_args(caller, types)
    return types


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
        "_arity",
        "_skip",
        "_binds_class",
        "_adapted",
        "__dict__",
        "__weakref__",
    )

    def __init__(
        self,
        func: Any = None,
        *,
        arity: int | None = None,
        _skip: int = 0,
        _binds_class: bool = False,
        _registry: TypeMap | None = None,
    ) -> None:
        """Create a multimethod with `func` as its default implementation.

        A call dispatches on its first `arity` positional arguments (past
        `self`/`cls`), by default as many as `func` has required positional
        parameters; any others are passed on, not dispatched on. `func` is
        registered for `object` at each of them, whatever its annotations.
        Pass `arity` for a multimethod without a default, or a default that
        takes `*args`, where it's required, or to override `func`'s. A call
        matching no registration raises `NoMatchError`. The underscored
        arguments are internal, set by `dispatchmethod` and `inherit()`.
        Raise `TypeError` for an `arity` that isn't an integer, and
        `ValueError` for a negative one.
        """
        if arity is not None:
            try:
                arity = operator.index(arity)
            except TypeError:
                raise TypeError(f"arity must be an integer, got {arity!r}") from None
            if arity < 0:
                raise ValueError(f"arity must be at least 0, got {arity}")
        self._skip = _skip
        self._binds_class = _binds_class
        self._adapted: dict[Any, Any] = {}
        if func is None:
            if _registry is None:
                if arity is None:
                    raise TypeError(
                        "Multimethod() needs a default function or an arity"
                    )
                _registry = TypeMap(arity=arity)
            self._registry: TypeMap = _registry
            self._arity = _registry.arity
            return
        functools.update_wrapper(self, func)
        self.__isabstractmethod__ = getattr(func, "__isabstractmethod__", False)
        if arity is None:
            arity = self._infer_arity(func)
        self._registry = TypeMap({(object,) * arity: self._callable(func)})
        self._arity = arity

    def _infer_arity(self, func: Any) -> int:
        """Return how many required positional parameters `func` has."""
        _, params = self._params(func)
        if params is None:
            raise TypeError(
                f"can't read the signature of {_describe(func)} to infer its "
                f"arity; pass arity explicitly"
            )
        if any(p.kind is p.VAR_POSITIONAL for p in params):
            raise TypeError(
                f"can't infer the arity of {_describe(func)}, which takes *args; "
                f"pass arity explicitly"
            )
        return sum(p.default is p.empty for p in params)

    def _unwrap(self, func: Any) -> tuple[Callable[..., Any], int]:
        """Return `func`'s plain function, and how many leading params to skip."""
        if isinstance(func, staticmethod):
            return func.__func__, 0
        if isinstance(func, classmethod):
            return func.__func__, 1
        return func, self._skip

    def _params(
        self, func: Any
    ) -> tuple[Callable[..., Any], list[inspect.Parameter] | None]:
        """Return `func`'s plain function, and its positional params past `self`/`cls`.

        Only positional arguments are dispatched on, so keyword-only
        parameters and `**kwargs` are left out. The params are None if
        `func` has no signature to read.
        """
        func, skip = self._unwrap(func)
        try:
            signature = inspect.signature(func, **_SIGNATURE_OPTIONS)
            params = list(signature.parameters.values())[skip:]
        except (ValueError, TypeError):
            return func, None
        positional = [
            p for p in params if p.kind not in (p.KEYWORD_ONLY, p.VAR_KEYWORD)
        ]
        return func, positional

    def _param_types(self, func: Any) -> tuple[Any, ...]:
        """Infer a registry key from `func`'s annotations, past `self`/`cls`.

        Read those of its first `arity` positional parameters, `*args` aside.
        Raise `TypeError` if it has fewer, or for a missing annotation, or one
        that can't be dispatched on.
        """
        # A class's annotations are its attributes', not its parameters'.
        if isinstance(func, type):
            raise TypeError(
                f"register() can't take the types to register class "
                f"{_type_name(func)} for from annotations; pass them explicitly"
            )
        func, params = self._params(func)
        params = [p for p in params or () if p.kind is not p.VAR_POSITIONAL]
        if len(params) < self._arity:
            raise TypeError(
                f"register() found too few parameters to dispatch on in "
                f"{_describe(func)}: needs {self._arity}; pass the types "
                f"explicitly"
            )
        try:
            hints = get_type_hints(func)
        # Some annotation doesn't resolve yet, maybe one not dispatched on, or
        # `func` isn't a function, like a `functools.partial`: evaluate the
        # signature's annotations one by one instead.
        except (TypeError, *_UNRESOLVED):
            hints = {}
        types = []
        for p in params[: self._arity]:
            annotation = hints.get(p.name, p.annotation)
            # Checked first, since `Parameter.empty` is itself a class.
            if annotation is p.empty:
                raise TypeError(
                    f"register() found no type annotation on parameter "
                    f"{p.name!r} of {_describe(func)}; annotate it or pass "
                    f"the types explicitly"
                )
            if p.name not in hints:
                annotation = _resolve(func, p.name, annotation)
            if _classes(annotation) is None:
                raise TypeError(
                    f"register() can't dispatch on parameter {p.name!r} of "
                    f"{_describe(func)}, annotated {annotation!r}"
                    f"{_not_a_type_hint(annotation)}; pass the types explicitly"
                )
            types.append(annotation)
        return tuple(types)

    def _check_count(self, types: tuple[Any, ...], func: Any = None) -> None:
        """Raise `TypeError` unless there are `arity` types to register `func` for."""
        if len(types) == self._arity:
            return
        registering = f"register {_describe(func)}" if func is not None else "register"
        message = (
            f"can't {registering} for {self._format_call(types, short=True)}: "
            f"{self._name()} dispatches on {_count(self._arity, 'argument')}, "
            f"not {len(types)}"
        )
        # As `functools.singledispatch` would read `register(int, SomeClass)`.
        last = types[-1] if types else None
        if (
            func is None
            and len(types) == self._arity + 1 > 1
            and isinstance(last, type)
        ):
            message += (
                f"; to register {_type_name(last)} itself as the "
                f"implementation, pass func={_type_name(last)}"
            )
        raise TypeError(message)

    def _register(self, types: tuple[Any, ...] | None, func: Any) -> None:
        """Register `func` for `types`, or for its annotations if None."""
        if types is not None:
            self._check_count(types, func)
        impl = self._callable(func)
        if types is None:
            types = self._param_types(func)
        for sig in _expand(types):
            self._registry[sig] = impl

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

        Without types, the implementation's first `arity` positional
        parameters (past `self`/`cls`) must be annotated with types. Use
        either bare, `@f.register`, or with explicit types,
        `@f.register(T1, T2)`, which take precedence over annotations; or
        functools-style, `f.register(T, func)`. A union type (`int | str`)
        registers the implementation for each member. Also accepts a
        `classmethod` or `staticmethod`, for a method. Raise `TypeError` at
        once for another number of types than `arity`.
        """
        return _register_with(self._register, types, func, self._check_count)

    def inherit(self) -> Self:
        """Return a multimethod for a subclass, inheriting this one's.

        It dispatches on `base | sub` registrations: its own replace those
        for the same types, and the most specific of all the others wins
        (see docs/methods.md):

            class Sub(Base):
                visit = Base.visit.inherit()

                @visit.register(SomeType)
                def _(self, x):
                    ...
                    return super().visit(x)
        """
        child = type(self)(
            _skip=self._skip,
            _binds_class=self._binds_class,
            _registry=ChainTypeMap(self._registry),
        )
        # As `update_wrapper` would, but leaving its qualname to
        # `__set_name__`, and not abstract: like a method, it overrides.
        vars(child).update(
            (key, value)
            for key, value in vars(self).items()
            if key not in ("__qualname__", "__isabstractmethod__")
        )
        return child

    def __getitem__(
        self, types: _TypeSpec | tuple[_TypeSpec, ...]
    ) -> Callable[..., Any]:
        """Return the implementation registered for exactly `types`.

        A single type stands for a one-element tuple. For a union, the same
        implementation must be registered for every member. Registered on
        an `inherit()` base counts, unless replaced. Raise `KeyError` if
        there's no such implementation.
        """
        types = _as_types("__getitem__()", types)
        table = self._registry._lookup_table()
        impls = [table.get(sig) for sig in _expand(types)]
        if impls[0] is not None and all(impl is impls[0] for impl in impls):
            return impls[0]
        if len(types) != self._arity:
            raise KeyError(
                f"No implementation registered for {self._format_call(types)}: "
                f"{self._name()} dispatches on {_count(self._arity, 'argument')}"
            )
        if None in impls:
            raise KeyError(
                f"No implementation registered for exactly {self._format_call(types)}"
            )
        raise KeyError(
            f"No one implementation registered for every member of "
            f"{self._format_call(types)}"
        )

    def __setitem__(self, types: _TypeSpec | tuple[_TypeSpec, ...], func: Any) -> None:
        """Register `func` for `types`, a single type or a tuple of them."""
        types = _as_types("__setitem__()", types)
        self._register(types, func)

    @property
    def registry(self) -> Mapping[Any, Any]:
        """Read-only mapping of the registered implementations, by signature.

        Keyed by a bare type for a single argument, as in
        `functools.singledispatch`, else by a tuple of types. Those of an
        `inherit()` base are included, unless replaced, as calls see them.
        """
        table = self._registry._lookup_table()
        return MappingProxyType(
            {sig[0] if len(sig) == 1 else sig: f for sig, f in table.items()}
        )

    def dispatch(self, *types: _TypeSpec) -> Any:
        """Return the implementation a call with arguments of `types` would run."""
        types, _ = _parse_decorator_args("dispatch()", types)
        if len(types) != self._arity:
            raise TypeError(
                f"dispatch() expected {_count(self._arity, 'type')}, got "
                f"{len(types)}: {_format_types(types)}"
            )
        sigs = _expand(types)
        if len(sigs) != 1:
            raise TypeError(
                f"dispatch() expected one class per argument, got "
                f"{_format_types(types)}"
            )
        try:
            return self._registry.lookup(sigs[0])
        except TypeError as e:
            error = self._lookup_error(e)
            if error is None:
                raise
            raise error from None

    def _callable(self, func: Any) -> Any:
        """Adapt `func` to be called with this multimethod's own arguments.

        The registry stores the result, so calls need no adapting. Only a
        `staticmethod` or `classmethod` needs it (see `_adapt_method`).
        """
        if not isinstance(func, (staticmethod, classmethod)):
            return func
        # Memoized so that registering the same method again stores the same
        # callable, which `__getitem__` needs to look up a union.
        if func not in self._adapted:
            self._adapted[func] = self._adapt_method(func)
        return self._adapted[func]

    def _adapt_method(self, func: Any) -> Any:
        """Adapt a `staticmethod` or `classmethod` to this multimethod's arguments.

        For a method, those start with `self`/`cls`: a `staticmethod` drops
        it, and a `classmethod` gets the instance's class in its place (or
        the class itself, already, for a `classmethod` dispatchmethod).
        """
        method = func.__func__
        if isinstance(func, staticmethod):
            if not self._skip:
                return method

            def adapted(obj: Any, *args: Any, **kwargs: Any) -> Any:
                return method(*args, **kwargs)

        else:
            if not self._skip:
                return func
            if self._binds_class:
                return method

            def adapted(obj: Any, *args: Any, **kwargs: Any) -> Any:
                return method(type(obj), *args, **kwargs)

        # So that errors and `registry` show the method itself.
        return functools.update_wrapper(adapted, method)

    def _name(self) -> str:
        """Return how error messages name this multimethod."""
        name = getattr(self, "__name__", type(self).__name__)
        return getattr(self, "__qualname__", name)

    def _format_call(self, types: tuple[Any, ...], short: bool = False) -> str:
        """Return how error messages show a call with arguments of `types`.

        With `short`, name this multimethod without its qualname's prefix.
        """
        name = self._name().rpartition(".")[2] if short else self._name()
        return f"{name}({', '.join(_type_name(t) for t in types)})"

    def _no_match_error(self, types: tuple[type, ...]) -> str:
        """Describe a call matching no registered signature."""
        message = f"{self._format_call(types)} matches no implementation"
        sigs = list(self._registry._lookup_table())
        if not sigs:
            return f"{message}: none are registered"
        listed = ", ".join(self._format_call(sig) for sig in sigs[:_MAX_LISTED])
        if len(sigs) > _MAX_LISTED:
            listed += f", and {len(sigs) - _MAX_LISTED} more"
        return f"{message}; registered: {listed}"

    def _ambiguity_error(
        self, types: tuple[type, ...], candidates: tuple[tuple[Any, Any], ...]
    ) -> str:
        """Describe a call matching several signatures, none the most specific.

        Suggest registering, at each position, the most specific of the
        candidates' types, if any, else the argument's own: more specific
        than every candidate, it resolves the ambiguity.
        """
        lines = [f"{self._format_call(types)} is ambiguous between:"]
        lines += [
            f"  {self._format_call(sig, short=True)}: {_describe(impl)}"
            for sig, impl in candidates
        ]
        fix = []
        for i, t in enumerate(types):
            column = [sig[i] for sig, _ in candidates]
            fix.append(
                next((c for c in column if all(issubclass(c, o) for o in column)), t)
            )
        fix_call = self._format_call(tuple(fix), short=True)
        lines.append(f"Register {fix_call} to resolve it.")
        return "\n".join(lines)

    def _too_few_args_error(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        """Describe a call with too few positional arguments to dispatch on."""
        after = ""
        if self._skip:
            after = " after cls" if self._binds_class else " after self"
        message = (
            f"{self._name()}() takes {_count(self._arity, 'positional argument')}"
            f" to dispatch on{after}, got {max(len(args) - self._skip, 0)}"
        )
        default = getattr(self, "__wrapped__", None)
        if default is None:
            return message
        _, params = self._params(default)
        names = [p.name for p in params or () if p.kind is not p.VAR_POSITIONAL]
        by_keyword = [repr(name) for name in names[: self._arity] if name in kwargs]
        if by_keyword:
            message += (
                f"; pass {', '.join(by_keyword)} positionally, as only positional "
                f"arguments are dispatched on"
            )
        return message

    def _lookup_error(self, error: TypeError) -> TypeError | None:
        """Return the error to raise for a failed lookup, or None to re-raise.

        `TypeMap.lookup()` reports it in terms of keys, so restate it in
        terms of this multimethod.
        """
        if isinstance(error, NoMatchError):
            return NoMatchError(self._no_match_error(error.types), error.types)
        if isinstance(error, AmbiguousMatchError):
            return AmbiguousMatchError(
                self._ambiguity_error(error.types, error.candidates),
                error.types,
                error.candidates,
            )
        return None

    def _call_error(
        self, error: TypeError, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> TypeError | None:
        """Return the error to raise for a call's failed lookup, or None to re-raise."""
        if len(args) - self._skip < self._arity:
            return TypeError(self._too_few_args_error(args, kwargs))
        return self._lookup_error(error)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the implementation chosen by the arguments' types."""
        # Fast path for one dispatched argument (see docs/performance.md).
        # `__class__`, not `type()`, so proxies like `Mock(spec=cls)`
        # dispatch as that class.
        key: type | tuple[type, ...]
        skip = self._skip
        if self._arity == 1:
            try:
                key = args[skip].__class__
            except IndexError:
                key = ()  # too few arguments: let lookup() raise
        else:
            key = tuple(arg.__class__ for arg in args[skip : skip + self._arity])
        # Two statements, so that a traceback shows which one failed.
        try:
            impl = self._registry.lookup(key)
        except TypeError as e:
            error = self._call_error(e, args, kwargs)
            if error is None:
                raise
            raise error from None
        return impl(*args, **kwargs)

    def __set_name__(self, owner: type, name: str) -> None:
        """Take the attribute's name, unless named after a default already.

        So that a subclass's `inherit()`ed multimethod is named in errors.
        """
        if "__qualname__" not in vars(self):
            self.__module__ = owner.__module__
            self.__name__ = name
            self.__qualname__ = f"{owner.__qualname__}.{name}"

    def __reduce__(self) -> str:
        """Pickle by reference, as a function is: by module and qualname.

        Raise `TypeError` for one without a name, unless set as a class
        attribute.
        """
        if "__qualname__" not in vars(self):
            raise TypeError(f"cannot pickle {self._name()}: it has no qualname")
        return self.__qualname__

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
        self._registrations: list[tuple[tuple[Any, ...] | None, Any]] = []
        self._decorator_types: list[tuple[Any, ...]] = []

    def register(self, *types: Any, func: Any = None) -> Any:
        # Annotations, and how many types there are, are only checked once
        # `__set_name__` has the real multimethod (and its `_skip`).
        return _register_with(
            lambda types, func: self._registrations.append((types, func)),
            types,
            func,
            self._decorator_types.append,
        )

    def __setitem__(self, types: _TypeSpec | tuple[_TypeSpec, ...], func: Any) -> None:
        self._registrations.append((_as_types("__setitem__()", types), func))

    def __set_name__(self, owner: type, name: str) -> None:
        base = next((b for b in owner.__mro__[1:] if name in vars(b)), None)
        if base is None:
            raise TypeError(
                f"inherit() found no base class of {owner.__name__} "
                f"defining a Multimethod named {name!r}"
            )
        parent = vars(base)[name]
        if not isinstance(parent, Multimethod):
            raise TypeError(
                f"inherit() found {base.__name__}.{name}, but it's a "
                f"{type(parent).__name__}, not a Multimethod"
            )
        dispatcher = parent.inherit()
        # Named first, for errors from the registrations.
        dispatcher.__set_name__(owner, name)
        for decorator_types in self._decorator_types:
            dispatcher._check_count(decorator_types)
        for types, func in self._registrations:
            dispatcher._register(types, func)
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


@overload
def dispatch(func: Callable[..., Any], *, arity: int | None = None) -> Multimethod: ...
@overload
def dispatch(
    *, arity: int | None = None
) -> Callable[[Callable[..., Any]], Multimethod]: ...
def dispatch(func: Any = None, *, arity: int | None = None) -> Any:
    """Turn a function into a multimethod, with it as the default.

    The default implementation is registered for `object` at every required
    positional parameter, so it's called whenever no more specific signature
    matches: as with `functools.singledispatch`, its annotations are ignored.
    Calls dispatch on that many positional arguments, and pass any others on.

    Pass `arity` to dispatch on another number of arguments, either directly,
    `dispatch(func, arity=n)`, or as `@dispatch(arity=n)`. It's required if
    the default takes `*args` or has no signature to read, rather than guess.
    `@dispatch()` is the same as `@dispatch`.
    """
    if func is None:
        return lambda func: dispatch(func, arity=arity)
    if not _is_function(func):
        raise TypeError(f"dispatch() expected a function, got {func!r}")
    return Multimethod(func, arity=arity)


@overload
def dispatchmethod(func: Any, *, arity: int | None = None) -> Multimethod: ...
@overload
def dispatchmethod(*, arity: int | None = None) -> Callable[[Any], Multimethod]: ...
def dispatchmethod(func: Any = None, *, arity: int | None = None) -> Any:
    """Turn a method into a multimethod, as `dispatch` does a function.

    `self` is bound automatically via the descriptor protocol and excluded
    from dispatch, so `.register(*types)` only lists the types of the
    remaining arguments, and `arity` doesn't count it either (pass it as with
    `dispatch`). As with `functools.singledispatchmethod`, either the method
    itself or any registered implementation can also be a `classmethod` or
    `staticmethod` (applied *below* the decorator).

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
    if func is None:
        return lambda func: dispatchmethod(func, arity=arity)
    if not _is_function(func):
        raise TypeError(f"dispatchmethod() expected a function, got {func!r}")
    if isinstance(func, staticmethod):
        return Multimethod(func, arity=arity)
    return Multimethod(
        func, arity=arity, _skip=1, _binds_class=isinstance(func, classmethod)
    )
