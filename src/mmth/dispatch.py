import inspect
from types import MethodType


class Dispatcher:
    def __init__(self, func=None, as_method=False):
        self._registry = {}
        self._default = None
        self._has_user_variants = False
        self._as_method = as_method
        self._arity = None
        if func is not None:
            self._default = func
            try:
                params = list(inspect.signature(func).parameters.values())
                self._arity = len(params)
            except (ValueError, TypeError):
                params = []
            types = tuple(
                p.annotation if p.annotation is not inspect.Parameter.empty else object
                for p in params
            )
            if types:
                self._registry[types] = func

    def _normalize(self, types):
        """Turn `types` into a full-arity registry key.

        A key shorter than the decorated default's arity is left-padded
        with `object`, so a method's own class doesn't need to be spelled
        out on every registration - only on the ones that actually narrow
        it (e.g. to override a case for one particular subclass).
        """
        if not isinstance(types, tuple):
            types = (types,)
        if self._arity is not None and len(types) < self._arity:
            types = (object,) * (self._arity - len(types)) + types
        return types

    def register(self, *types):
        if not types:
            raise TypeError("register() requires at least one type argument")
        types = self._normalize(types)
        self._has_user_variants = True

        def decorator(func):
            self._registry[types] = func
            return func

        return decorator

    def __getitem__(self, types):
        types = self._normalize(types)
        if types in self._registry:
            return self._registry[types]
        raise KeyError(f"No specialization registered for {types}")

    def __setitem__(self, types, func):
        types = self._normalize(types)
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

        # 3. Fall back to default (always callable regardless of types)
        if self._default is not None:
            return self._default

        # 4. No matching implementation
        if self._has_user_variants:
            raise TypeError(f"No matching variant for types {arg_types}")

        raise TypeError(f"No matching implementation for types {arg_types}")

    def __call__(self, *args, **kwargs):
        arg_types = tuple(type(arg) for arg in args)
        return self._resolve(arg_types)(*args, **kwargs)

    def __get__(self, instance, owner=None):
        if instance is None or not self._as_method:
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


def dispatch(*types):
    def decorator(func):
        if callable(func) and not isinstance(func, type):
            dispatcher = Dispatcher(func)
            if types and not callable(types[0]):
                key = dispatcher._normalize(types)
                dispatcher._registry[key] = func
                dispatcher._has_user_variants = True
            return dispatcher
        raise TypeError("dispatch expects a callable function")

    if types and callable(types[0]) and not isinstance(types[0], type):
        return decorator(types[0])
    return decorator


def dispatchmethod(func):
    """Like `dispatch`, but decorates a method instead of a function.

    `self` is bound automatically via the descriptor protocol, and
    participates in dispatch like any other argument - but `.register(*types)`
    only needs to list the types that actually narrow a case: any type left
    unspecified (typically `self`, since most implementations apply
    regardless of the concrete subclass) defaults to `object`, i.e. "matches
    any type here". This makes a plain `.register(SomeType)` mean "for any
    `self`, when the next argument is `SomeType`" - exactly like the examples
    below - while a subclass can still narrow a specific case further by
    registering directly on the base dispatcher with its own class spelled
    out, e.g. `@Base.visit.register(Sub, SomeType)`.

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
    return Dispatcher(func, as_method=True)
