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

# What `register()` gives back for a registered implementation: deliberately
# not its own precise type (as typeshed's `functools.singledispatch` stubs
# do too), since implementations are conventionally all named `_`, and a
# precise type makes a type checker compare a subclass's `_` against its base
# class's (e.g. with `inherit()`) as if one overrode the other. `Any` rather
# than `Callable`, since a `classmethod`/`staticmethod` isn't callable itself.
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
    """Split `(*types, func)` - `func` given directly (bare `@f.register`,
    or functools-style `f.register(cls, func)`) or as a keyword - from
    `(*types,)` alone (`@f.register(*types)`, for a decorator)."""
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
    # Slots for everything a call touches, so those lookups stay fast even
    # though `functools.update_wrapper` adds arbitrary attributes (__name__,
    # __doc__, ..., plus the function's own __dict__) to the instance -
    # which otherwise stops instances sharing their dict's keys, and costs
    # ~25% on every call.
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
        # `_skip` (leading arguments excluded from dispatch, i.e. `self`),
        # `_parent` (the `inherit()` chain) and `_binds_class` (a
        # `classmethod` dispatchmethod, bound to the class even when looked
        # up on an instance) are internal wiring: set them via
        # `dispatchmethod` and `.inherit()`, which also registers the child
        # for cache invalidation.
        self._registry: dict[tuple[type, ...], Any] = {}
        self._default: Any = None
        self._default_signatures: list[tuple[type, ...]] = []
        self._skip = _skip
        self._parent = _parent
        self._binds_class = _binds_class
        # Set once any registered type is an ABC: `issubclass` against an
        # ABC can change after the fact (`SomeABC.register(cls)`), which
        # bumps `abc.get_cache_token()` - same trick as functools'.
        self._abc_token: object | None = None
        # Resolving a signature against `_registry` (and, on a miss, the
        # whole `_parent` chain) only depends on `arg_types` and the
        # registry contents, so a successful resolution can be memoized by
        # `arg_types` - this is what actually matters for real call sites,
        # which call with the same concrete types over and over. Failed
        # resolutions (ambiguous / no match) aren't cached, since raising
        # is already the slow, cold path. `_children` lets a mutation here
        # invalidate every inherit()-chained descendant's cache too, since
        # those can fall through to this multimethod's registry. Cache keys
        # are a bare type for the common one-argument case (see `_resolve`)
        # rather than always a one-element tuple, to avoid its allocation
        # and (slightly more expensive) hashing on every call.
        self._cache: dict[type | tuple[type, ...], Callable[..., Any]] = {}
        self._children: list[weakref.ReferenceType[Multimethod]] = []
        if func is None:
            return
        _parse_decorator_args("Multimethod()", types)
        # __name__, __doc__, __wrapped__, ... as functools.singledispatch
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

        String annotations (e.g. under `from __future__ import annotations`)
        are evaluated, as functools does. A parameter without a usable
        annotation (missing, or a string naming something not defined yet)
        counts as `object`, or, if `strict`, raises `TypeError`, as does a
        function with no parameters to dispatch on.
        """
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
        # Registering a type the default's annotation doesn't cover would
        # otherwise be silently more specific than, or unrelated to, what
        # the default claims to handle.
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
        """A multimethod chained to this one, for a subclass to replace one
        implementation while inheriting everything else - unlike
        `.register()`, which adds a peer entry compared against every other
        registration by specificity, an overriding subclass's own
        multimethod is always tried first, in full, before falling through
        to this one. This mirrors plain method overriding rather than
        standard multiple dispatch: the subclass wins regardless of how its
        registered types compare to the base class's.

        Assign the result as the subclass's own attribute, then build it up
        with `.register(*types)` same as `dispatchmethod` itself; a
        registered function defined inside the subclass's body can still
        call `super()` normally, since it's an ordinary method either way:

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

        # A candidate is a contender unless some *other* candidate dominates
        # it - checking against every other candidate, not just a running
        # "best so far", matters: two mutually-incomparable candidates
        # encountered early don't make the call ambiguous if a later,
        # more specific candidate dominates both of them.
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
        """Find the implementation to call for the given argument type(s),
        memoized in `self._cache` (see `__init__`), adapted to be called
        with the multimethod's own arguments (see `_callable`). `key` is a
        bare type for the common single-argument case, or a tuple of types
        for multi-argument dispatch."""
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
        # 1. Exact match in registry
        if arg_types in self._registry:
            return self._registry[arg_types]

        # 2. Find most specialized via inheritance
        func = self._find_most_specialized(arg_types)
        if func is not None:
            return func

        # 3. Fall through to a parent multimethod, if chained via `inherit()`
        if self._parent is not None:
            return self._parent._lookup(arg_types)

        # 4. Fall back to default (always callable regardless of types)
        if self._default is not None:
            return self._default

        # 5. No matching implementation
        raise TypeError(f"No matching implementation for types {arg_types}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # The overwhelmingly common case - one dispatched argument, e.g.
        # every `dispatchmethod` call (self is skipped) and most plain
        # `dispatch` functions - is fast-pathed to avoid both the generator
        # expression below (building and driving a generator per call is
        # far more expensive than one attribute lookup) and wrapping that
        # single type in a one-element tuple, which `_resolve` would
        # otherwise need to allocate and hash on every call. `__class__`
        # rather than `type()`, as functools does, so that proxies (e.g.
        # `Mock(spec=cls)`) dispatch as the class they stand in for.
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
    """Placeholder returned by `inherit()`; collects `.register(*types)`
    calls, then replaces itself with a real `Multimethod` - chained to
    whichever base class defines the same attribute name - once Python
    calls `__set_name__` on it at class-creation time."""

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
    """A subclass's own multimethod, inheriting every implementation of the
    base class's, with the base multimethod found automatically instead of
    spelled out: assign the result to the *same* attribute name the base
    class uses, and Python's own class-creation machinery (`__set_name__`)
    fills in the rest once the class body finishes, by looking up that name
    on the base classes - exactly the lookup `super()` would do. Register
    implementations with `.register(*types)` exactly like `dispatchmethod`
    itself; they take precedence over the inherited ones:

        class Sub(Base):
            visit = inherit()

            @visit.register(SomeType)
            def _(self, x):
                ...
                return super().visit(x)

    Equivalent to `Base.visit.inherit()` (see `Multimethod.inherit`), for
    the common case where the base multimethod is simply inherited - use the
    explicit form instead if the name differs from the base's, or the base
    to chain to isn't the one plain attribute lookup would find.
    """
    # Declared as returning Multimethod (not _PendingInherit, its actual
    # runtime type here) so that type checkers accept both the assignment
    # to an attribute overriding a Multimethod-typed base one, and the
    # .register(*types) calls that follow - by the time anything other
    # than __set_name__ touches the attribute, it really has become one.
    # (The same kind of deliberate mismatch as dataclasses.field()'s.)
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
