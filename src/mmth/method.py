import inspect
from types import MethodType

from mmth.dispatch import Dispatcher


class DispatchMethod:
    """Descriptor version of `Dispatcher` for use as an instance method.

    `self` is bound automatically via the descriptor protocol and excluded
    from dispatch, so `.register(*types)` only lists the types of the
    remaining arguments. This is mmth's replacement for the visitor
    pattern: a stateful object with one method per node type, and no
    `accept()` boilerplate needed on the visited classes.
    """

    def __init__(self, func):
        self._dispatcher = Dispatcher()
        self._dispatcher._default = func
        types = self._param_types(func)
        if types:
            self._dispatcher._registry[types] = func

    @staticmethod
    def _param_types(func):
        params = list(inspect.signature(func).parameters.values())[1:]
        return tuple(
            p.annotation if p.annotation is not inspect.Parameter.empty else object
            for p in params
        )

    def register(self, *types):
        return self._dispatcher.register(*types)

    def __getitem__(self, types):
        return self._dispatcher[types]

    def __setitem__(self, types, func):
        self._dispatcher[types] = func

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return MethodType(self, instance)

    def __call__(self, instance, *args, **kwargs):
        arg_types = tuple(type(arg) for arg in args)
        func = self._dispatcher._resolve(arg_types)
        return func(instance, *args, **kwargs)


def dispatchmethod(func):
    """Like `dispatch`, but decorates a method instead of a function.

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
    return DispatchMethod(func)
