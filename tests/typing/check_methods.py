"""Static typing of `dispatchmethod` multimethods, checked by mypy and pyright.

Each expected error carries an ignore comment for each checker reporting
it, which they're configured to report if unused (see tox.ini, `typing`
env). Known gaps, in `*Unchecked*` classes, carry none for a checker that
misses them, so catching them fails until it's added.
"""

from typing import Callable, assert_type

from mmth import dispatchmethod, inherit


class Node: ...


class Num(Node): ...


class Add(Node): ...


class Evaluator:
    @dispatchmethod
    def visit(self, node: Node) -> int:
        raise TypeError(type(node).__name__)

    @visit.register
    def _(self, node: Num) -> int:
        return 1

    @visit.register(Add)
    def _(self, node: Add) -> int:
        return 2

    @visit.register(Add)  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
    def _(self, node: Num) -> int:
        return 3

    @visit.register(Add)  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
    def _(self, node: Add) -> str:
        return ""

    @visit.register(int)  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportUntypedFunctionDecorator]
    def _(self, node: int) -> int:
        return 4

    @visit.register(Num)
    @staticmethod
    def _(node: Num) -> int:
        return 5

    @visit.register(Num)
    @classmethod
    def _(cls, node: Num) -> int:
        return 6


class MissingSelfUncheckedByMypy:
    @dispatchmethod
    def visit(self, node: Node) -> int:
        return 0

    @visit.register(Num)
    def _(node: Num) -> int:  # noqa: N805  # pyright: ignore[reportGeneralTypeIssues]
        return 1


def test_methods_bind_self() -> None:
    evaluator = Evaluator()
    bound: Callable[[Node], int] = evaluator.visit
    assert_type(bound(Num()), int)
    assert_type(evaluator.visit(Num()), int)
    assert_type(Evaluator.visit(evaluator, Num()), int)
    evaluator.visit(1)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]


class Factory:
    @dispatchmethod
    @classmethod
    def make(cls, node: Node) -> str:
        return "node"

    @dispatchmethod
    @staticmethod
    def check(node: Node) -> bool:
        return True


def test_classmethods_and_staticmethods() -> None:
    assert_type(Factory.make(Num()), str)
    assert_type(Factory().make(Num()), str)
    assert_type(Factory.check(Num()), bool)
    assert_type(Factory().check(Num()), bool)


class Explicit(Evaluator):
    visit = Evaluator.visit.inherit()

    @visit.register(Num)
    def _(self, node: Num) -> int:
        return 7

    @visit.register(Num)  # type: ignore[arg-type]  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
    def _(self, node: Num) -> bytes:
        return b""


class Implicit(Evaluator):
    visit = inherit()

    @visit.register(Num)
    def _(self, node: Num) -> int:
        return 8


def test_inherit() -> None:
    assert_type(Explicit().visit(Num()), int)
    Implicit().visit(Num())
