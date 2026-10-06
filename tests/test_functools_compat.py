"""Single dispatch behaves like `functools.singledispatch`/`singledispatchmethod`.

Each test builds the same thing with both, via `_both()`, and checks they
agree. The intentional differences are tested (and documented) separately:
see `test_*_differs_from_functools` below and docs/specification.md.
"""

import abc
import functools
import inspect
from typing import Any, Optional, Union
from unittest import mock

import pytest
from hypothesis import given

from mmth import AmbiguousMatchError, dispatch, dispatchmethod, inherit

from strategies import multi_inheritance_dag, with_registered_subset


def _both(build):
    """`build(decorator)` with functools.singledispatch, then with dispatch."""
    return build(functools.singledispatch), build(dispatch)


def _both_methods(build):
    return build(functools.singledispatchmethod), build(dispatchmethod)


class Animal:
    pass


class Dog(Animal):
    pass


@given(multi_inheritance_dag(max_parents=1).flatmap(with_registered_subset))
def test_matches_functools_on_single_inheritance_trees(data):
    # with single inheritance there are no ties to break, so mmth's
    # ambiguity rule never kicks in and both must pick the same thing
    classes, _ancestors, registered = data

    def build(decorator):
        @decorator
        def f(x):
            return "default"

        for i in registered:
            f.register(classes[i])(lambda x, i=i: i)
        return f

    reference, f = _both(build)
    for cls in classes:
        assert f(cls()) == reference(cls())


def test_optional_parameters_are_passed_on():
    def build(decorator):
        @decorator
        def fun(arg, verbose=False):
            return f"default {verbose}"

        @fun.register
        def _(arg: int, verbose=False):
            return f"int {verbose}"

        return fun

    reference, fun = _both(build)
    for args, kwargs in [((1,), {}), ((1, True), {}), (("s",), {"verbose": True})]:
        assert fun(*args, **kwargs) == reference(*args, **kwargs)


def test_register_union_type():
    def build(decorator):
        @decorator
        def f(x):
            return "default"

        f.register(int | str)(lambda x: "int|str")
        f.register(Union[bytes, float])(lambda x: "bytes|float")

        @f.register
        def _(x: list | Optional[dict]):
            return "list|dict|None"

        return f

    reference, f = _both(build)
    for arg in (1, "s", b"b", 1.0, [], {}, None, ()):
        assert f(arg) == reference(arg)


def test_register_string_annotation():
    def build(decorator):
        @decorator
        def f(x):
            return "default"

        @f.register
        def _(x: "int"):
            return "int"

        return f

    reference, f = _both(build)
    assert f(1) == reference(1) == "int"


def test_register_functional_form():
    def build(decorator):
        @decorator
        def f(x):
            return "default"

        assert f.register(int, len) is len
        assert f.register(str, func=str.upper) is str.upper
        return f

    reference, f = _both(build)
    assert f([]) == reference([]) == "default"
    assert f("s") == reference("s") == "S"


def test_dispatches_on_dunder_class():
    # proxies like Mock(spec=...) report the class they stand in for
    def build(decorator):
        @decorator
        def f(x):
            return "default"

        f.register(Dog)(lambda x: "dog")
        return f

    reference, f = _both(build)
    assert f(mock.Mock(spec=Dog)) == reference(mock.Mock(spec=Dog)) == "dog"


def test_abc_registered_after_first_call():
    class Greetable(abc.ABC):
        pass

    class Person:
        pass

    def build(decorator):
        @decorator
        def f(x):
            return "stranger"

        f.register(Greetable)(lambda x: "friend")
        return f

    reference, f = _both(build)
    assert f(Person()) == reference(Person()) == "stranger"  # now cached
    Greetable.register(Person)
    assert f(Person()) == reference(Person()) == "friend"


def test_abc_registered_after_first_call_through_inherit():
    class Greetable(abc.ABC):
        pass

    class Person:
        pass

    class Base:
        @dispatchmethod
        def greet(self, x):
            return "stranger"

        @greet.register(Greetable)
        def _(self, x):
            return "friend"

    class Sub(Base):
        greet = inherit()

    assert Sub().greet(Person()) == "stranger"  # now cached, in Sub's cache
    Greetable.register(Person)
    assert Sub().greet(Person()) == "friend"


def test_wraps_the_default_implementation():
    def build(decorator):
        @decorator
        def f(x: int, y: str = "") -> str:
            """Docstring."""
            return "default"

        return f

    reference, f = _both(build)
    for attr in ("__name__", "__qualname__", "__doc__", "__module__"):
        assert getattr(f, attr) == getattr(reference, attr)
    assert f.__wrapped__ is not reference.__wrapped__
    assert inspect.signature(f) == inspect.signature(reference)


def test_dispatch_method_and_registry():
    def build(decorator):
        @decorator
        def f(x):
            return "default"

        f.register(Animal)(lambda x: "animal")
        return f

    reference, f = _both(build)
    assert f.dispatch(Dog)(Dog()) == reference.dispatch(Dog)(Dog()) == "animal"
    assert f.dispatch(int)(1) == reference.dispatch(int)(1) == "default"
    assert set(f.registry) == set(reference.registry) == {object, Animal}
    with pytest.raises(TypeError):
        f.registry[int] = len  # read-only, as functools'


def test_abstract_dispatchmethod():
    def build(decorator):
        class Base(abc.ABC):
            @decorator
            @abc.abstractmethod
            def m(self, x): ...

        return Base

    for base in _both_methods(build):
        with pytest.raises(TypeError, match="abstract"):
            base()


def test_dispatchmethod_classmethod_and_staticmethod_implementations():
    def build(decorator):
        class K:
            @decorator
            def m(self, x):
                return "default"

            @m.register(int)
            @classmethod
            def _(cls, x):
                return f"classmethod {cls.__name__}"

            @m.register
            @staticmethod
            def _(x: str):
                return "staticmethod"

        class Sub(K):
            pass

        return Sub

    reference, cls = _both_methods(build)
    for arg in (1, "s", 1.0):
        assert cls().m(arg) == reference().m(arg)


def test_dispatchmethod_wrapping_classmethod():
    def build(decorator):
        class K:
            @decorator
            @classmethod
            def m(cls, x):
                return f"default {cls.__name__}"

            @m.register
            @classmethod
            def _(cls, x: int):
                return f"int {cls.__name__}"

        class Sub(K):
            pass

        return Sub

    reference, cls = _both_methods(build)
    for arg in (1, "s"):
        assert cls.m(arg) == reference.m(arg)
        assert cls().m(arg) == reference().m(arg)


def test_dispatchmethod_wrapping_staticmethod():
    def build(decorator):
        class K:
            @decorator
            @staticmethod
            def m(x):
                return "default"

            @m.register(int)
            @staticmethod
            def _(x):
                return "int"

        return K

    reference, cls = _both_methods(build)
    for arg in (1, "s"):
        assert cls.m(arg) == reference.m(arg)
        assert cls().m(arg) == reference().m(arg)


def test_multiple_inheritance_differs_from_functools():
    # functools breaks the tie by MRO order; mmth refuses to guess
    class A:
        pass

    class B:
        pass

    class C(A, B):
        pass

    def build(decorator):
        @decorator
        def f(x):
            return "default"

        f.register(A)(lambda x: "A")
        f.register(B)(lambda x: "B")
        return f

    reference, f = _both(build)
    assert reference(C()) == "A"
    with pytest.raises(AmbiguousMatchError, match="Ambiguous lookup"):
        f(C())


def test_default_annotations_are_ignored():
    def build(decorator):
        @decorator
        def f(x: Dog):
            return "default"

        f.register(Animal)(lambda x: "animal")
        return f

    reference, f = _both(build)
    assert f(Dog()) == reference(Dog()) == "animal"
    assert f(1) == reference(1) == "default"
    assert set(f.registry) == set(reference.registry) == {object, Animal}


def test_dispatchmethod_class_access_differs_from_functools():
    # looked up on the class, functools dispatches on the first argument
    # given, i.e. the instance; mmth skips it, as it would `self`
    def build(decorator):
        class K:
            @decorator
            def m(self, x):
                return "default"

            @m.register(int)
            def _(self, x):
                return "int"

        return K

    reference, cls = _both_methods(build)
    assert reference.m(reference(), 1) == "default"
    assert cls.m(cls(), 1) == "int"


def test_any_differs_from_functools():
    # functools treats Any as a class nothing is an instance of
    def build(decorator):
        @decorator
        def f(x):
            return "default"

        f.register(Any)(lambda x: "any")
        return f

    reference, f = _both(build)
    assert reference(1) == "default"
    assert f(1) == "any"
