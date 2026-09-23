import pytest

from mmth import Multimethod, dispatchmethod, inherit


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


def test_dispatchmethod_class_access_returns_multimethod():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

    assert isinstance(Handler.visit, Multimethod)


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


def test_dispatchmethod_inherit_replaces_one_implementation():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return node.value

    class PickyHandler(Handler):
        visit = Handler.visit.inherit()

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


def test_dispatchmethod_inherit_can_replace_several_implementations():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return node.value

    class PickyHandler(Handler):
        visit = Handler.visit.inherit()

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


def test_dispatchmethod_inherit_wins_regardless_of_relative_specificity():
    # PickyHandler registers a broader type (Node) than Handler (Num), and
    # still wins for Num
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return "handler-num"

    class PickyHandler(Handler):
        visit = Handler.visit.inherit()

        @visit.register(Node)
        def _(self, node):
            return "picky-any"

    assert Handler().visit(Num(1)) == "handler-num"
    assert PickyHandler().visit(Num(1)) == "picky-any"


def test_inherit_function_finds_base_multimethod_automatically():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return node.value

    class PickyHandler(Handler):
        visit = inherit()

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
    assert isinstance(PickyHandler.visit, Multimethod)


def test_inherit_function_collects_multiple_registrations():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

    class PickyHandler(Handler):
        visit = inherit()

        @visit.register(Num)
        def _(self, node):
            return "picky-num"

        @visit.register(Add)
        def _(self, node):
            return "picky-add"

    assert PickyHandler().visit(Num(1)) == "picky-num"
    assert PickyHandler().visit(Add(Num(1), Num(2))) == "picky-add"
    assert PickyHandler().visit(Node()) == "default"


def test_inherit_function_raises_without_a_matching_base():
    # called directly, since some CPython versions wrap __set_name__
    # errors raised by a class statement in a RuntimeError
    pending = inherit()

    class Orphan:
        pass

    with pytest.raises(TypeError, match="no base class of Orphan"):
        pending.__set_name__(Orphan, "visit")


def test_dispatchmethod_register_bare_uses_annotations_past_self():
    class Evaluator:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

        @visit.register
        def _(self, node: Num):
            return node.value

    assert Evaluator().visit(Num(3)) == 3
    assert Evaluator().visit(Add(Num(1), Num(2))) == "default"
    assert list(Evaluator.visit._registry) == [(Node,), (Num,)]


def test_inherit_register_bare_uses_annotations():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

    class PickyHandler(Handler):
        visit = inherit()

        @visit.register
        def _(self, node: Num):
            return "picky-num"

    class ExplicitHandler(Handler):
        visit = Handler.visit.inherit()

        @visit.register
        def _(self, node: Num):
            return "explicit-num"

    assert PickyHandler().visit(Num(1)) == "picky-num"
    assert ExplicitHandler().visit(Num(1)) == "explicit-num"
    assert PickyHandler().visit(Node()) == "default"


def test_dispatchmethod_with_explicit_types():
    class Evaluator:
        @dispatchmethod(Node)
        def visit(self, node):
            return "default"

        @visit.register(Num)
        def _(self, node):
            return node.value

    assert Evaluator.visit[Node] is Evaluator.visit.__wrapped__
    assert Evaluator().visit(Num(3)) == 3
    assert Evaluator().visit(Node()) == "default"


def test_dispatchmethod_with_empty_parentheses_uses_annotations():
    class Evaluator:
        @dispatchmethod()
        def visit(self, node: Node):
            return "default"

    assert Evaluator.visit[Node] is Evaluator.visit.__wrapped__


def test_dispatchmethod_rejects_non_types():
    with pytest.raises(TypeError, match=r"dispatchmethod\(\) expected types"):
        dispatchmethod(42)


def test_inherit_register_requires_subclasses_of_the_base_default():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

    class PickyHandler(Handler):
        visit = Handler.visit.inherit()

    with pytest.raises(TypeError, match="expected subclasses of the default"):
        PickyHandler.visit.register(int)(lambda self, node: "int")
