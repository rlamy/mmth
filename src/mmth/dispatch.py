class Dispatcher:
    def __init__(self, func=None):
        self._registry = {}
        self._default = None
        self._has_variants = False
        if func is not None:
            self._default = func

    def register(self, *types):
        if not types:
            raise TypeError("register() requires at least one type argument")
        self._has_variants = True

        def decorator(func):
            self._registry[types] = func
            return func

        return decorator

    def __call__(self, *args, **kwargs):
        types = tuple(type(arg) for arg in args)

        if types in self._registry:
            return self._registry[types](*args, **kwargs)

        for sig, func in self._registry.items():
            if self._match_signature(sig, types):
                return func(*args, **kwargs)

        if self._has_variants:
            raise TypeError(f"No matching variant for types {types}")

        if self._default is not None:
            return self._default(*args, **kwargs)

        raise TypeError(f"No matching implementation for types {types}")

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
                dispatcher._has_variants = True
            return dispatcher
        raise TypeError("dispatch expects a callable function")

    if types and callable(types[0]) and not isinstance(types[0], type):
        return decorator(types[0])
    return decorator
