import inspect
from types import MethodType


class Dispatcher:
    def __init__(self, func=None, skip=0, parent=None):
        self._registry = {}
        self._default = None
        self._has_user_variants = False
        self._skip = skip
        self._parent = parent
        if func is not None:
            self._default = func
            types = self._param_types(func)
            if types:
                self._registry[types] = func

    def _param_types(self, func):
        """Infer a registry key from `func`'s annotations, past `self._skip`."""
        try:
            params = list(inspect.signature(func).parameters.values())
        except (ValueError, TypeError):
            return ()
        return tuple(
            p.annotation if p.annotation is not inspect.Parameter.empty else object
            for p in params[self._skip:]
        )

    def register(self, *types):
        if not types:
            raise TypeError("register() requires at least one type argument")
        self._has_user_variants = True

        def decorator(func):
            self._registry[types] = func
            return func

        return decorator

    def override(self, *types):
        """A dispatcher chained to this one, for a subclass to narrow a case
        while inheriting everything else - unlike `.register()`, which adds
        a peer entry compared against every other registration by
        specificity, an overriding subclass's own dispatcher is always
        tried first, in full, before falling through to this one. This
        mirrors plain method overriding rather than standard multiple
        dispatch: the subclass wins regardless of how its registered types
        compare to the base class's.

        With no arguments, returns the chained dispatcher directly, meant
        to be assigned as the subclass's own attribute and then built up
        with `.register(*types)`:

            class Sub(Base):
                visit = Base.visit.override()

                @visit.register(SomeType)
                def _(self, x): ...

        With `*types`, acts as a decorator instead, for the common case of
        narrowing a single case: the decorated method is installed as its
        own chained override automatically, once Python calls
        `__set_name__` on it at class-creation time - so it's a real method
        of the subclass, and `super()` works normally:

            class Sub(Base):
                @Base.visit.override(SomeType)
                def visit(self, x):
                    ...
                    return super().visit(x)
        """
        if not types:
            return Dispatcher(skip=self._skip, parent=self)

        def decorator(func):
            return _PendingOverride(self, types, func)

        return decorator

    def __getitem__(self, types):
        if not isinstance(types, tuple):
            types = (types,)
        if types in self._registry:
            return self._registry[types]
        raise KeyError(f"No specialization registered for {types}")

    def __setitem__(self, types, func):
        if not isinstance(types, tuple):
            types = (types,)
        self._registry[types] = func
        self._has_user_variants = True
        return None

    def _is_more_specialized(self, sig_a, sig_b):
        """Returns True if sig_a is strictly more specialized than sig_b."""
        more_specific = False
        for type_a, type_b in zip(sig_a, sig_b):
            if issubclass(type_a, type_b):
                if not issubclass(type_b, type_a):
                    more_specific = True
            else:
                return False
        return more_specific

    def _find_most_specialized(self, types):
        """Find the most specialized matching signature, or raise on ambiguity."""
        candidates = [
            (sig, func) for sig, func in self._registry.items()
            if self._match_signature(sig, types)
        ]

        if not candidates:
            return None

        winner_sig, winner_func = candidates[0]

        for sig, func in candidates[1:]:
            if self._is_more_specialized(sig, winner_sig):
                winner_sig, winner_func = sig, func
            elif not self._is_more_specialized(winner_sig, sig):
                raise TypeError(
                    f"Ambiguous dispatch for types {types}: "
                    f"matches multiple signatures"
                )

        return winner_func

    def _resolve(self, arg_types):
        """Find the implementation to call for the given argument types."""
        # 1. Exact match in registry
        if arg_types in self._registry:
            return self._registry[arg_types]

        # 2. Find most specialized via inheritance
        func = self._find_most_specialized(arg_types)
        if func is not None:
            return func

        # 3. Fall through to a parent dispatcher, if chained via `override()`
        if self._parent is not None:
            return self._parent._resolve(arg_types)

        # 4. Fall back to default (always callable regardless of types)
        if self._default is not None:
            return self._default

        # 5. No matching implementation
        if self._has_user_variants:
            raise TypeError(f"No matching variant for types {arg_types}")

        raise TypeError(f"No matching implementation for types {arg_types}")

    def __call__(self, *args, **kwargs):
        arg_types = tuple(type(arg) for arg in args[self._skip:])
        return self._resolve(arg_types)(*args, **kwargs)

    def __get__(self, instance, owner=None):
        if instance is None or self._skip == 0:
            return self
        return MethodType(self, instance)

    def _match_signature(self, sig, types):
        if len(sig) != len(types):
            return False
        for sig_type, arg_type in zip(sig, types):
            if not isinstance(sig_type, type):
                return False
            if not issubclass(arg_type, sig_type):
                return False
        return True


class _PendingOverride:
    """Placeholder returned by `Dispatcher.override(*types)` as a decorator;
    replaces itself with a real, chained `Dispatcher` on the owning class
    once Python calls `__set_name__` on it at class-creation time."""

    def __init__(self, parent, types, func):
        self._parent = parent
        self._types = types
        self._func = func

    def __set_name__(self, owner, name):
        dispatcher = self._parent.override()
        dispatcher.register(*self._types)(self._func)
        setattr(owner, name, dispatcher)


def dispatch(*types):
    def decorator(func):
        if callable(func) and not isinstance(func, type):
            dispatcher = Dispatcher(func)
            if types and not callable(types[0]):
                dispatcher._registry[types] = func
                dispatcher._has_user_variants = True
            return dispatcher
        raise TypeError("dispatch expects a callable function")

    if types and callable(types[0]) and not isinstance(types[0], type):
        return decorator(types[0])
    return decorator


def dispatchmethod(func):
    """Like `dispatch`, but decorates a method instead of a function.

    `self` is bound automatically via the descriptor protocol and excluded
    from dispatch, so `.register(*types)` only lists the types of the
    remaining arguments.

    A subclass can narrow a single case for itself, without touching the
    base class, via `.override(...)` - see `Dispatcher.override` for the
    two ways to use it.

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
        raise TypeError("dispatchmethod expects a callable function")
    return Dispatcher(func, skip=1)
