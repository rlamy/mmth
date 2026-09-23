from __future__ import annotations

import inspect
import weakref
from types import MethodType
from typing import Any, Callable


class Multimethod:
    def __init__(
        self,
        func: Callable[..., Any] | None = None,
        *,
        _skip: int = 0,
        _parent: Multimethod | None = None,
    ) -> None:
        # `_skip` (leading arguments excluded from dispatch, i.e. `self`) and
        # `_parent` (the `inherit()` chain) are internal wiring: set them
        # via `dispatchmethod` and `.inherit()`, which also registers the
        # child for cache invalidation.
        self._registry: dict[tuple[type, ...], Callable[..., Any]] = {}
        self._default: Callable[..., Any] | None = None
        self._skip = _skip
        self._parent = _parent
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
        if func is not None:
            self._default = func
            types = self._param_types(func)
            if types:
                self._registry[types] = func

    def _param_types(self, func: Callable[..., Any]) -> tuple[type, ...]:
        """Infer a registry key from `func`'s annotations, past `self._skip`."""
        try:
            params = list(inspect.signature(func).parameters.values())
        except (ValueError, TypeError):
            return ()
        return tuple(
            p.annotation if p.annotation is not inspect.Parameter.empty else object
            for p in params[self._skip:]
        )

    def register(
        self, *types: type
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if not types:
            raise TypeError("register() requires at least one type argument")

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._registry[types] = func
            self._invalidate_cache()
            return func

        return decorator

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
        child = Multimethod(_skip=self._skip, _parent=self)
        self._children.append(weakref.ref(child))
        return child

    def __getitem__(self, types: type | tuple[type, ...]) -> Callable[..., Any]:
        if not isinstance(types, tuple):
            types = (types,)
        if types in self._registry:
            return self._registry[types]
        raise KeyError(f"No implementation registered for {types}")

    def __setitem__(
        self, types: type | tuple[type, ...], func: Callable[..., Any]
    ) -> None:
        if not isinstance(types, tuple):
            types = (types,)
        self._registry[types] = func
        self._invalidate_cache()

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
        memoized in `self._cache` (see `__init__`). `key` is a bare type
        for the common single-argument case, or a tuple of types for
        multi-argument dispatch."""
        try:
            return self._cache[key]
        except KeyError:
            pass
        arg_types = key if isinstance(key, tuple) else (key,)
        func = self._resolve_uncached(arg_types)
        self._cache[key] = func
        return func

    def _resolve_uncached(self, arg_types: tuple[type, ...]) -> Callable[..., Any]:
        # 1. Exact match in registry
        if arg_types in self._registry:
            return self._registry[arg_types]

        # 2. Find most specialized via inheritance
        func = self._find_most_specialized(arg_types)
        if func is not None:
            return func

        # 3. Fall through to a parent multimethod, if chained via `inherit()`
        if self._parent is not None:
            key: type | tuple[type, ...] = (
                arg_types[0] if len(arg_types) == 1 else arg_types
            )
            return self._parent._resolve(key)

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
        # far more expensive than one attribute-free `type()` call) and
        # wrapping that single type in a one-element tuple, which `_resolve`
        # would otherwise need to allocate and hash on every call.
        key: type | tuple[type, ...]
        if len(args) - self._skip == 1:
            key = type(args[self._skip])
        else:
            key = tuple(type(arg) for arg in args[self._skip:])
        return self._resolve(key)(*args, **kwargs)

    def __get__(self, instance: object | None, owner: type | None = None) -> Any:
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
        self._registrations: list[tuple[tuple[type, ...], Callable[..., Any]]] = []

    def register(
        self, *types: type
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if not types:
            raise TypeError("register() requires at least one type argument")

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
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
            dispatcher.register(*types)(func)
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


def dispatch(*types: Any) -> Any:
    def decorator(func: Callable[..., Any]) -> Multimethod:
        if callable(func) and not isinstance(func, type):
            dispatcher = Multimethod(func)
            if types and not callable(types[0]):
                dispatcher._registry[types] = func
            return dispatcher
        raise TypeError("dispatch expects a callable function")

    if types and callable(types[0]) and not isinstance(types[0], type):
        return decorator(types[0])
    return decorator


def dispatchmethod(func: Callable[..., Any]) -> Multimethod:
    """Like `dispatch`, but decorates a method instead of a function.

    `self` is bound automatically via the descriptor protocol and excluded
    from dispatch, so `.register(*types)` only lists the types of the
    remaining arguments.

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
    if not callable(func) or isinstance(func, type):
        raise TypeError(f"dispatchmethod() expected a function, got {func!r}")
    return Multimethod(func, _skip=1)
