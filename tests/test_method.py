import pytest

from mmth import Dispatcher, dispatchmethod, override


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


def test_dispatchmethod_override_narrows_one_case():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return node.value

    class PickyHandler(Handler):
        visit = Handler.visit.override()

        @visit.register(Num)
        def _(self, node):
            if node.value < 0:
                raise ValueError("negative numbers not supported")
            return super().visit(node)

    assert Handler().visit(Num(5)) == 5
    assert PickyHandler().visit(Num(5)) == 5
    with pytest.raises(ValueError, match="negative numbers"):
        PickyHandler().visit(Num(-1))

    # unrelated node types and unrelated subclasses are unaffected
    assert Handler().visit(Add(Num(1), Num(2))) == "default"
    assert PickyHandler().visit(Add(Num(1), Num(2))) == "default"


def test_dispatchmethod_override_can_narrow_more_than_one_case():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return node.value

    class PickyHandler(Handler):
        visit = Handler.visit.override()

        @visit.register(Num)
        def _(self, node):
            return node.value * 10

        @visit.register(Add)
        def _(self, node):
            return "picky-add"

    assert Handler().visit(Num(5)) == 5
    assert PickyHandler().visit(Num(5)) == 50
    assert PickyHandler().visit(Add(Num(1), Num(2))) == "picky-add"
    # PickyHandler didn't register anything for other node types, so it
    # still falls through to Handler's own default
    assert PickyHandler().visit(Node()) == "default"


def test_dispatchmethod_override_wins_regardless_of_relative_specificity():
    # Handler registers the *narrower* type (Num); PickyHandler's override
    # registers the *broader* one (Node). A plain multimethod comparing
    # (PickyHandler, Node) against (Handler, Num) as peers would be
    # ambiguous (neither type pair dominates the other) - but subclassing a
    # dispatched method isn't standard multiple dispatch: PickyHandler's own
    # table is tried first, in full, before ever falling back to Handler's.
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return "handler-num"

    class PickyHandler(Handler):
        visit = Handler.visit.override()

        @visit.register(Node)
        def _(self, node):
            return "picky-any"

    assert Handler().visit(Num(1)) == "handler-num"
    assert PickyHandler().visit(Num(1)) == "picky-any"


def test_override_function_finds_base_dispatcher_automatically():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return node.value

    class PickyHandler(Handler):
        visit = override()

        @visit.register(Num)
        def _(self, node):
            if node.value < 0:
                raise ValueError("negative numbers not supported")
            return super().visit(node)

    assert Handler().visit(Num(5)) == 5
    assert PickyHandler().visit(Num(5)) == 5
    with pytest.raises(ValueError, match="negative numbers"):
        PickyHandler().visit(Num(-1))
    assert PickyHandler().visit(Add(Num(1), Num(2))) == "default"
    assert isinstance(PickyHandler.visit, Dispatcher)


def test_override_function_collects_multiple_registrations():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

    class PickyHandler(Handler):
        visit = override()

        @visit.register(Num)
        def _(self, node):
            return "picky-num"

        @visit.register(Add)
        def _(self, node):
            return "picky-add"

    assert PickyHandler().visit(Num(1)) == "picky-num"
    assert PickyHandler().visit(Add(Num(1), Num(2))) == "picky-add"
    assert PickyHandler().visit(Node()) == "default"


def test_override_function_raises_without_a_matching_base():
    # exercise __set_name__ directly rather than via a real class statement:
    # CPython wraps __set_name__ exceptions in a RuntimeError on some
    # versions (and not others), which isn't what this test cares about.
    pending = override()

    class Orphan:
        pass

    with pytest.raises(TypeError, match="no base class of Orphan"):
        pending.__set_name__(Orphan, "visit")
