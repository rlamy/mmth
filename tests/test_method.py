import pickle

import pytest

from mmth import AmbiguousMatchError, Multimethod, dispatchmethod, inherit


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


def test_dispatchmethod_method_registered_twice_is_one_implementation():
    def shared(node):
        return "shared"

    class Handler:
        @dispatchmethod
        def visit(self, node: object):
            return "default"

    method = staticmethod(shared)
    Handler.visit.register(int, method)
    Handler.visit.register(str, method)
    assert Handler.visit[int | str] is Handler.visit[int]
    assert Handler().visit("s") == "shared"


def test_dispatchmethod_adapted_methods_wrap_the_function():
    def static(node):
        return "static"

    def method(cls, node):
        return f"class {cls.__name__}"

    class Handler:
        @dispatchmethod
        def visit(self, node: object):
            return "default"

    Handler.visit.register(int, staticmethod(static))
    Handler.visit.register(str, classmethod(method))
    assert Handler.visit[int].__wrapped__ is static
    assert Handler.visit[int].__qualname__ == static.__qualname__
    assert Handler.visit[str].__wrapped__ is method
    assert Handler().visit(1) == "static"
    assert Handler().visit("s") == "class Handler"


def test_dispatchmethod_takes_an_arity():
    class Handler:
        @dispatchmethod(arity=1)
        def visit(self, *nodes):
            return "default"

        @visit.register(Num)
        def _(self, node, *rest):
            return node.value + len(rest)

        @dispatchmethod(arity=1)
        @staticmethod
        def describe(*nodes):
            return "default"

    assert Handler().visit(Num(5), Num(6)) == 6
    assert Handler().visit(Node()) == "default"
    assert Handler.describe(Num(1)) == "default"


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


def test_dispatchmethod_inherit_dispatches_on_the_merged_registrations():
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
            return "picky-node"

    assert PickyHandler().visit(Num(1)) == "handler-num"
    assert PickyHandler().visit(Node()) == "picky-node"
    assert Handler().visit(Node()) == "default"


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


def test_inherit_function_checks_the_number_of_types_with_its_base():
    # called directly, as in test_inherit_function_raises_without_a_matching_base
    class Base:
        @dispatchmethod
        def visit(self, node):
            return "default"

    class Sub(Base):
        pass

    pending = inherit()
    pending.register(Num, Node)
    with pytest.raises(TypeError, match=r"for visit\(Num, Node\): .* pass func=Node"):
        pending.__set_name__(Sub, "visit")


def test_inherit_function_takes_item_assignment():
    class Base:
        @dispatchmethod
        def visit(self, node):
            return "default"

    class Sub(Base):
        visit = inherit()
        visit[Num] = lambda self, node: "num"

    assert Sub().visit(Num(1)) == "num"
    assert Sub().visit(Node()) == "default"
    assert Base().visit(Num(1)) == "default"


def test_inherit_function_register_rejects_non_function_at_once():
    with pytest.raises(TypeError, match=r"register\(\) expected a function"):
        inherit().register(int)(42)


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
    assert list(Evaluator.visit._registry) == [(object,), (Num,)]


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


def test_dispatchmethod_takes_only_a_function():
    with pytest.raises(TypeError, match=r"dispatchmethod\(\) expected a function"):
        dispatchmethod(42)
    with pytest.raises(TypeError, match=r"dispatchmethod\(\) expected a function"):
        dispatchmethod(Node)


def test_dispatchmethod_called_bare_is_dispatchmethod():
    class Handler:
        @dispatchmethod()
        def visit(self, node, extra=None):
            return "default"

        @visit.register(Num)
        def _(self, node, extra=None):
            return node.value

    assert Handler().visit(Num(3)) == 3
    assert Handler().visit(Node()) == "default"


def test_inherit_register_accepts_types_outside_the_base_default():
    class Handler:
        @dispatchmethod
        def visit(self, node: Node):
            return "default"

    class LenientHandler(Handler):
        visit = Handler.visit.inherit()

    LenientHandler.visit.register(int)(lambda self, node: "int")
    assert LenientHandler().visit(1) == "int"
    assert Handler().visit(1) == "default"


def test_inherited_multimethods_take_their_attribute_name():
    class Base:
        @dispatchmethod
        def visit(self, node: object):
            return "default"

        alias = visit

    class Sub(Base):
        visit = inherit()

    class Explicit(Base):
        visit = Base.visit.inherit()

    prefix = "test_inherited_multimethods_take_their_attribute_name.<locals>."
    assert Base.visit.__qualname__ == f"{prefix}Base.visit"
    assert Sub.visit.__qualname__ == f"{prefix}Sub.visit"
    assert Explicit.visit.__qualname__ == f"{prefix}Explicit.visit"
    assert Sub.visit.__name__ == "visit"


def test_unbound_call_lacks_an_argument_after_self():
    class Handler:
        @dispatchmethod
        def visit(self, node: object):
            return "default"

    with pytest.raises(
        TypeError,
        match=r"Handler\.visit\(\) takes 1 positional "
        r"argument to dispatch on after self, got 0$",
    ):
        Handler.visit(1)


def test_ambiguity_error_shows_where_inherited_candidates_come_from():
    class Base:
        @dispatchmethod
        def visit(self, a: object, b: object):
            return "default"

        @visit.register(int, object)
        def _(self, a, b):
            return "int, object"

    class Sub(Base):
        visit = inherit()

        @visit.register(object, int)
        def _(self, a, b):
            return "object, int"

    with pytest.raises(AmbiguousMatchError) as exc_info:
        Sub().visit(1, 2)
    header, base, sub, fix = str(exc_info.value).splitlines()
    assert header == f"{Sub.visit.__qualname__}(int, int) is ambiguous between:"
    assert base.startswith(f"  visit(int, object): {Base.__qualname__}._ at ")
    assert sub.startswith(f"  visit(object, int): {Sub.__qualname__}._ at ")
    assert fix == "Register visit(int, int) to resolve it."


def test_inherit_registration_errors_name_the_subclass_multimethod():
    class Base:
        @dispatchmethod
        def visit(self, node: object):
            return "default"

    def _(self, a, b):
        return "int, int"

    pending = inherit()
    pending.register(int, int)(_)

    class Sub(Base):
        pass

    with pytest.raises(
        TypeError, match=r"for visit\(int, int\): .*Sub\.visit dispatches"
    ):
        pending.__set_name__(Sub, "visit")


def test_classmethod_call_lacks_an_argument_after_cls():
    class Handler:
        @dispatchmethod
        @classmethod
        def visit(cls, node: object):
            return "default"

    with pytest.raises(
        TypeError, match=r"to dispatch on after cls, got 0; pass 'node'"
    ):
        Handler.visit(node=1)


def test_register_in_a_class_body_on_that_class_says_so():
    with pytest.raises(TypeError) as exc_info:

        class Shape:
            @dispatchmethod
            def overlaps(self, other: object):
                return False

            @overlaps.register
            def _(self, other: "Shape"):
                return True

    assert str(exc_info.value).endswith(
        "(name 'Shape' is not defined); Shape is still being defined, so "
        "register this after the class body instead"
    )


def test_inherited_multimethod_assigned_later_takes_the_base_name():
    class Base:
        @dispatchmethod
        def visit(self, node: object):
            return "default"

    class Sub(Base):
        pass

    Sub.visit = Base.visit.inherit()
    with pytest.raises(TypeError, match=r"^visit\(\) takes 1 positional argument"):
        Sub().visit()


def test_inherit_says_when_the_base_attribute_isnt_a_multimethod():
    class Base:
        def visit(self, node):
            return "plain"

    class Sub(Base):
        pass

    pending = inherit()
    with pytest.raises(TypeError) as exc_info:
        pending.__set_name__(Sub, "visit")
    assert str(exc_info.value) == (
        "inherit() found Base.visit, but it's a function, not a Multimethod"
    )


class Pickled:
    @dispatchmethod
    def visit(self, node):
        return "default"

    @visit.register(Num)
    def _(self, node):
        return "num"

    unnamed = Multimethod(arity=1)


class PickledSub(Pickled):
    visit = inherit()

    @visit.register(Add)
    def _(self, node):
        return "add"


def test_dispatchmethod_pickles_by_reference():
    for multimethod in (Pickled.visit, PickledSub.visit, Pickled.unnamed):
        assert pickle.loads(pickle.dumps(multimethod)) is multimethod
    bound = pickle.loads(pickle.dumps(PickledSub().visit))
    assert bound(Num(1)) == "num"
    assert bound(Add(Num(1), Num(2))) == "add"
