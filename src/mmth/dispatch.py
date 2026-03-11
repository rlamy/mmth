class Dispatcher:
    def __init__(self, func=None):
        self._registry = {}
        self._default = None
        self._has_user_variants = False
        if func is not None:
            self._default = func
            import inspect
            try:
                sig = inspect.signature(func)
                types = []
                for param in sig.parameters.values():
                    if param.annotation is not inspect.Parameter.empty:
                        types.append(param.annotation)
                    else:
                        types.append(object)
                if types:
                    self._registry[tuple(types)] = func
            except (ValueError, TypeError):
                pass

    def register(self, *types):
        if not types:
            raise TypeError("register() requires at least one type argument")
        self._has_user_variants = True

        def decorator(func):
            self._registry[types] = func
            return func

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

    def __call__(self, *args, **kwargs):
        arg_types = tuple(type(arg) for arg in args)

        # 1. Exact match in registry
        if arg_types in self._registry:
            return self._registry[arg_types](*args, **kwargs)

        # 2. Find most specialized via inheritance
        func = self._find_most_specialized(arg_types)
        if func is not None:
            return func(*args, **kwargs)

        # 3. Fall back to default (always callable regardless of types)
        if self._default is not None:
            return self._default(*args, **kwargs)

        # 4. No matching implementation
        if self._has_user_variants:
            raise TypeError(f"No matching variant for types {arg_types}")

        raise TypeError(f"No matching implementation for types {arg_types}")

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
                dispatcher._registry[types] = func
                dispatcher._has_user_variants = True
            return dispatcher
        raise TypeError("dispatch expects a callable function")

    if types and callable(types[0]) and not isinstance(types[0], type):
        return decorator(types[0])
    return decorator
