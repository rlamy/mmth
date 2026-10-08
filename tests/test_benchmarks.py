"""Performance benchmarks, excluded by default: run `pytest -m benchmark`."""

import functools

import pytest

from mmth import dispatch, dispatchmethod

pytestmark = pytest.mark.benchmark


class Animal:
    pass


class Dog(Animal):
    pass


def test_baseline_plain_function_call(benchmark):
    def add(a, b):
        return a + b

    benchmark(add, 1, 2)


def test_baseline_singledispatch(benchmark):
    @functools.singledispatch
    def handle(x):
        return "default"

    @handle.register(Dog)
    def _(x):
        return "dog"

    benchmark(handle, Dog())


def test_mmth_dispatch_exact_match(benchmark):
    @dispatch
    def handle(x: object) -> str:
        return "default"

    @handle.register(Dog)
    def _(x: Dog) -> str:
        return "dog"

    benchmark(handle, Dog())


def test_mmth_dispatch_one_level_of_inheritance(benchmark):
    @dispatch
    def handle(x: object) -> str:
        return "default"

    @handle.register(Animal)
    def _(x: Animal) -> str:
        return "animal"

    # Dog matches via inheritance, not an exact registry key
    benchmark(handle, Dog())


@pytest.mark.parametrize("arity", [2, 3])
def test_mmth_dispatch_several_arguments(benchmark, arity):
    @dispatch(arity=arity)
    def handle(*args) -> str:
        return "default"

    handle.register(*[Dog] * arity, lambda *args: "dogs")

    benchmark(handle, *[Dog()] * arity)


@pytest.mark.parametrize("registry_size", [1, 10, 100])
def test_mmth_dispatch_scaling_when_nothing_matches(benchmark, registry_size):
    """Every registered type is unrelated to the call's."""

    @dispatch
    def handle(x: object) -> str:
        return "default"

    for i in range(registry_size):
        cls = type(f"Sibling{i}", (Animal,), {})

        @handle.register(cls)
        def _(x, cls=cls) -> str:
            return cls.__name__

    benchmark(handle, Dog())


@pytest.mark.parametrize("chain_length", [1, 10, 100])
def test_mmth_dispatch_scaling_when_everything_matches(benchmark, chain_length):
    """Register every ancestor of the call type, but not the type itself.

    The worst case for `_find_most_specialized`.
    """

    @dispatch
    def handle(x: object) -> str:
        return "default"

    cls = Animal
    for i in range(chain_length):
        cls = type(f"Level{i}", (cls,), {})

        @handle.register(cls)
        def _(x, cls=cls) -> str:
            return cls.__name__

    query_cls = type("Query", (cls,), {})  # deliberately never registered
    benchmark(handle, query_cls())


@pytest.mark.parametrize("chain_depth", [1, 10, 100])
def test_dispatchmethod_inherit_chain_depth(benchmark, chain_depth):
    """A call that falls through every `.inherit()` level to the base."""

    class Base:
        @dispatchmethod
        def visit(self, x: object) -> str:
            return "base"

    cls = Base
    for i in range(chain_depth):
        cls = type(f"Level{i}", (cls,), {"visit": cls.visit.inherit()})

    benchmark(cls().visit, object())
