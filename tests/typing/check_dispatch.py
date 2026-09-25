"""Static typing of `dispatch` multimethods, checked by mypy and pyright.

Each expected error carries an ignore comment for both, which they're
configured to report if unused (see tox.ini, `typing` env).
"""

from typing import Callable, assert_type

from mmth import dispatch


class Animal: ...


class Dog(Animal): ...


class Cat(Animal): ...


@dispatch
def meet(a: Animal, b: Animal) -> str:
    return "generic"


@meet.register
def _(a: Dog, b: Dog) -> str:
    return "dogs"


@meet.register(Dog, Cat)
def _(a: Dog, b: Animal) -> str:
    return "dog, cat"


@meet.register(Cat, Dog)
def _(a, b):  # type: ignore[no-untyped-def]  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
    return "cat, dog"


@meet.register(Dog | Cat, Cat)
def _(a: Animal, b: Cat) -> str:
    return "union"


def cats(a: Cat, b: Cat) -> str:
    return "cats"


meet.register(Cat, Cat, func=cats)


def test_calls_are_typed_by_the_default() -> None:
    assert_type(meet(Dog(), Cat()), str)
    meet(1, Dog())  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    meet(Dog())  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


def test_implementations_return_the_defaults_type() -> None:
    @meet.register  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
    def _(a: Cat, b: Cat) -> int:
        return 1

    @meet.register(Dog, Dog)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    def _(a: Dog, b: Dog) -> int:
        return 1


def test_implementations_accept_their_registered_types() -> None:
    @meet.register(Dog, Animal)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    def _(a: Dog, b: Dog) -> str:
        return ""


def test_registered_types_are_ones_the_default_accepts() -> None:
    @meet.register(int, Dog)  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportUntypedFunctionDecorator]
    def _(a: int, b: Dog) -> str:
        return ""


@dispatch
def describe(x: Animal) -> str:
    return "animal"


def test_single_dispatch_functools_style() -> None:
    describe.register(Dog, lambda d: "dog")
    describe.register(Dog, cats)  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType]
    assert_type(describe.dispatch(Dog), Callable[..., str])
    assert_type(describe[Dog], Callable[..., str])
