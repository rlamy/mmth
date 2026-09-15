import pytest

from mmth import Dispatcher, dispatchmethod


class Node:
    pass


class Num(Node):
    def __init__(self, value):
        self.value = value


class Add(Node):
    def __init__(self, left, right):
        self.left = left
        self.right = right


def test_dispatchmethod_replaces_visitor_pattern():
    class Evaluator:
        @dispatchmethod
        def visit(self, node: Node):
            raise TypeError(f"no visit implementation for {type(node).__name__}")

        @visit.register(Num)
        def _(self, node):
            return node.value

        @visit.register(Add)
        def _(self, node):
            return self.visit(node.left) + self.visit(node.right)

    tree = Add(Num(1), Add(Num(2), Num(3)))
    assert Evaluator().visit(tree) == 6


def test_dispatchmethod_state_is_per_instance():
    class Greeting(Node):
        pass

    class Greeter:
        def __init__(self, name):
            self.name = name

        @dispatchmethod
        def visit(self, node: Node):
            return "?"

        @visit.register(Greeting)
        def _(self, node):
            return f"Hello, {self.name}!"

    assert Greeter("Ada").visit(Greeting()) == "Hello, Ada!"
    assert Greeter("Grace").visit(Greeting()) == "Hello, Grace!"


def test_dispatchmethod_generic_fallback_raises():
    class Unknown(Node):
        pass

    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            raise TypeError(f"no visit implementation for {type(node).__name__}")

    with pytest.raises(TypeError, match="no visit implementation for Unknown"):
        Handler().visit(Unknown())


def test_dispatchmethod_class_access_returns_dispatcher():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

    assert isinstance(Handler.visit, Dispatcher)


def test_dispatchmethod_setitem_and_getitem():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

    def handle_num(self, node):
        return node.value

    Handler.visit[Num] = handle_num
    assert Handler.visit[Num] is handle_num
    assert Handler().visit(Num(5)) == 5


def test_dispatchmethod_rejects_non_callable():
    with pytest.raises(TypeError):
        dispatchmethod(42)


def test_dispatchmethod_subclass_can_override_one_case():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return node.value

    class PickyHandler(Handler):
        pass

    @Handler.visit.register(PickyHandler, Num)
    def _(self, node):
        if node.value < 0:
            raise ValueError("negative numbers not supported")
        return Handler.visit[Num](self, node)

    assert Handler().visit(Num(5)) == 5
    assert PickyHandler().visit(Num(5)) == 5
    with pytest.raises(ValueError, match="negative numbers"):
        PickyHandler().visit(Num(-1))

    # unrelated node types and unrelated subclasses are unaffected
    assert Handler().visit(Add(Num(1), Num(2))) == "default"
    assert PickyHandler().visit(Add(Num(1), Num(2))) == "default"
