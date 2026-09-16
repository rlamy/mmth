import abc
from collections import abc as collections_abc

import pytest

from mmth import dispatch, dispatchmethod


def test_dispatch_matches_a_real_abc_subclass():
    class Shape(abc.ABC):
        @abc.abstractmethod
        def area(self): ...

    class Square(Shape):
        def __init__(self, side):
            self.side = side

        def area(self):
            return self.side**2

    @dispatch
    def describe(obj: object) -> str:
        return "something"

    @describe.register(Shape)
    def _(obj: Shape) -> str:
        return "a shape"

    assert describe(Square(3)) == "a shape"


def test_dispatch_matches_a_virtual_subclass():
    class Greetable(abc.ABC):
        pass

    class Person:
        pass

    Greetable.register(Person)

    @dispatch
    def greet(obj: object) -> str:
        return "hello, stranger"

    @greet.register(Greetable)
    def _(obj: Greetable) -> str:
        return "hello, friend"

    # Person never inherits from Greetable - no relationship at all in
    # Person's own MRO - yet issubclass (and so dispatch) treats it as one,
    # purely because of the .register() call.
    assert Greetable not in Person.__mro__
    assert issubclass(Person, Greetable)
    assert greet(Person()) == "hello, friend"


def test_dispatch_matches_collections_abc_structural_subclass():
    # collections.abc.Sized uses __subclasshook__ for duck-typing: any
    # class with a __len__ counts as a "subclass", with neither real
    # inheritance nor an explicit .register() call anywhere.
    @dispatch
    def describe(obj: object) -> str:
        return "unsized"

    @describe.register(collections_abc.Sized)
    def _(obj) -> str:
        return "sized"

    assert issubclass(list, collections_abc.Sized)
    assert describe([1, 2, 3]) == "sized"
    assert describe(object()) == "unsized"


def test_dispatch_prefers_the_more_specific_of_two_virtual_bases():
    class Base(abc.ABC):
        pass

    class Derived(Base):
        pass

    class Thing:
        pass

    Derived.register(Thing)

    @dispatch
    def visit(obj: object) -> str:
        return "default"

    @visit.register(Base)
    def _(obj) -> str:
        return "base"

    @visit.register(Derived)
    def _(obj) -> str:
        return "derived"

    # Thing is a virtual subclass of Derived, which is a real subclass of
    # Base - so Thing is (via issubclass) a subclass of both, and Derived
    # should win as the more specific match.
    assert issubclass(Thing, Base)
    assert issubclass(Thing, Derived)
    assert visit(Thing()) == "derived"


def test_multi_arg_dispatch_mixes_a_real_class_and_a_virtual_subclass():
    class Number(abc.ABC):
        pass

    Number.register(int)

    class Loud:
        pass

    @dispatch
    def combine(a: object, b: object) -> str:
        return "default"

    @combine.register(Number, Loud)
    def _(a, b) -> str:
        return "number+loud"

    assert combine(5, Loud()) == "number+loud"
    assert combine("not a number", Loud()) == "default"


def test_dispatch_raises_ambiguous_for_two_unrelated_virtual_bases():
    class Flyer(abc.ABC):
        pass

    class Swimmer(abc.ABC):
        pass

    class Duck:
        pass

    Flyer.register(Duck)
    Swimmer.register(Duck)

    @dispatch
    def move(obj: object) -> str:
        return "default"

    @move.register(Flyer)
    def _(obj) -> str:
        return "flies"

    @move.register(Swimmer)
    def _(obj) -> str:
        return "swims"

    # Duck is a virtual subclass of both Flyer and Swimmer, which are
    # otherwise unrelated - same ambiguity a real multiple-inheritance
    # diamond would produce, just established via .register() instead.
    with pytest.raises(TypeError, match="Ambiguous dispatch"):
        move(Duck())


def test_dispatchmethod_works_with_an_abc_hierarchy():
    class Shape(abc.ABC):
        @abc.abstractmethod
        def area(self): ...

    class Circle(Shape):
        def __init__(self, radius):
            self.radius = radius

        def area(self):
            return 3.14159 * self.radius**2

    class Formatter:
        @dispatchmethod
        def describe(self, shape: Shape) -> str:
            return f"a shape with area {shape.area()}"

        @describe.register(Circle)
        def _(self, shape):
            return f"a circle with area {shape.area()}"

    assert Formatter().describe(Circle(2)) == "a circle with area 12.56636"
