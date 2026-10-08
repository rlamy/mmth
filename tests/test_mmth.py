import functools
import pickle
import re
import sys
from collections.abc import Iterable, Sized
from typing import (
    Annotated,
    Any,
    Callable,
    List,
    Literal,
    Optional,
    TypeVar,
    Union,
)

import pytest

from mmth import AmbiguousMatchError, NoMatchError, dispatch
from mmth.multimethod import Multimethod


def test_basic_dispatch():
    @dispatch
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    assert greet("World") == "Hello, World!"


def test_register_variant():
    @dispatch
    def add(a: int, b: int) -> str:
        return f"int + int: {a + b}"

    @add.register(int, int)
    def _(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3


def test_inheritance_dispatch():
    class Animal:
        pass

    class Dog(Animal):
        pass

    @dispatch
    def make_sound(animal: Animal) -> str:
        return "Some sound"

    @make_sound.register(Dog)
    def _(dog: Dog) -> str:
        return "Woof!"

    dog = Dog()
    assert make_sound(dog) == "Woof!"


def test_no_match_raises_no_match_error():
    d = Multimethod(arity=1)
    d.register(int)(lambda a: a * 2)
    assert d(5) == 10
    with pytest.raises(NoMatchError) as exc_info:
        d("not an int")
    assert str(exc_info.value) == (
        "Multimethod(str) matches no implementation; registered: Multimethod(int)"
    )
    assert exc_info.value.types == (str,)
    assert exc_info.value.__suppress_context__


def test_no_match_error_lists_some_registered_signatures():
    f = Multimethod(arity=2)
    with pytest.raises(NoMatchError, match="none are registered$"):
        f(1, "a")
    for cls in [int, float, bytes, list, dict, set]:
        f[cls, cls] = lambda a, b: "same"
    with pytest.raises(NoMatchError) as exc_info:
        f(1, "a")
    assert str(exc_info.value) == (
        "Multimethod(int, str) matches no implementation; registered: "
        "Multimethod(int, int), Multimethod(float, float), "
        "Multimethod(bytes, bytes), Multimethod(list, list), "
        "Multimethod(dict, dict), and 1 more"
    )


def test_getitem_getter():
    @dispatch
    def add(a, b):
        return a + b

    @add.register(int, float)
    def add_int_float(a: int, b: float) -> float:
        return float(a) + b

    impl = add[int, float]
    assert impl(1, 2.0) == 3.0


def test_setitem_setter():
    @dispatch
    def process(data):
        return data.upper()

    def custom_handler(data: dict) -> str:
        return str(data)

    process[dict] = custom_handler

    assert process("hello") == "HELLO"
    assert process({"key": "value"}) == "{'key': 'value'}"


def test_getitem_after_setitem():
    @dispatch
    def process(data):
        return data.upper()

    def custom_handler(data: dict) -> str:
        return str(data)

    process[dict] = custom_handler
    handler = process[dict]
    assert handler({"key": "value"}) == "{'key': 'value'}"


def test_keyerror_on_missing_implementation():
    @dispatch
    def add(a: int, b: int) -> int:
        return a + b

    with pytest.raises(KeyError) as exc_info:
        add[float, float]
    assert exc_info.value.args == (
        f"No implementation registered for exactly {add.__qualname__}(float, float)",
    )
    with pytest.raises(KeyError, match=r"for .*add\(float\): .*add dispatches on 2 "):
        add[float]
    add[int, int] = lambda a, b: "int, int"
    add[int, str] = lambda a, b: "int, str"
    with pytest.raises(KeyError, match=r"every member of .*add\(int, int \| str\)"):
        add[int, int | str]


def test_ambiguity_detection():
    class Animal:
        pass

    class Dog(Animal):
        pass

    @dispatch
    def f(a: Animal, b: Animal) -> str:
        return "Animal, Animal"

    @f.register(Dog, Animal)
    def _(d: Dog, a: Animal) -> str:
        return "Dog, Animal"

    @f.register(Animal, Dog)
    def _(a: Animal, d: Dog) -> str:
        return "Animal, Dog"

    with pytest.raises(AmbiguousMatchError) as exc_info:
        f(Dog(), Dog())
    assert "is ambiguous between" in str(exc_info.value)


def _located(func) -> str:
    return f"{func.__qualname__} at {__file__}:{func.__code__.co_firstlineno}"


def test_ambiguity_error_locates_candidates_and_suggests_a_fix():
    class A:
        pass

    class B(A):
        pass

    class Left:
        pass

    class Right:
        pass

    class Both(Left, Right):
        pass

    @dispatch
    def f(a, b, c) -> str:
        return "default"

    @f.register(B, A, Left)
    def first(a, b, c) -> str:
        return "B, A, Left"

    @f.register(A, B, Right)
    def second(a, b, c) -> str:
        return "A, B, Right"

    with pytest.raises(AmbiguousMatchError) as exc_info:
        f(B(), B(), Both())
    assert str(exc_info.value) == "\n".join(
        [
            f"{f.__qualname__}(B, B, Both) is ambiguous between:",
            f"  f(B, A, Left): {_located(first)}",
            f"  f(A, B, Right): {_located(second)}",
            "Register f(B, B, Both) to resolve it.",
        ]
    )
    assert exc_info.value.types == (B, B, Both)
    assert [impl for _, impl in exc_info.value.candidates] == [first, second]
    assert exc_info.value.__suppress_context__


def test_ambiguity_error_shows_builtins():
    @dispatch
    def f(a) -> str:
        return "default"

    f.register(Sized, len)
    f.register(Iterable, iter)
    with pytest.raises(AmbiguousMatchError) as exc_info:
        f([])
    assert str(exc_info.value).splitlines()[1:3] == [
        f"  f(Sized): {len!r}",
        f"  f(Iterable): {iter!r}",
    ]


def test_default_fallback_no_registrations():
    @dispatch
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3
    assert add("a", "b") == "ab"


def test_default_fallback_with_registrations():
    @dispatch
    def add(a, b):
        return a + b

    @add.register(int, float)
    def add_int_float(a: int, b: float) -> float:
        return float(a) + b

    assert add(1, 2) == 3
    assert add(1, 2.0) == 3.0


def test_single_type_shorthand():
    @dispatch
    def double(x: int | float) -> int | float:
        return x * 2

    @double.register(float)
    def double_float(x: float) -> float:
        return x * 2.0

    impl = double[object]
    assert impl(5) == 10

    impl_float = double[float]
    assert impl_float(3.0) == 6.0


def test_most_specialized_wins():
    class Animal:
        pass

    class Dog(Animal):
        pass

    @dispatch
    def f(a: Animal) -> str:
        return "Animal"

    @f.register(Animal)
    def f_animal(a: Animal) -> str:
        return "Animal"

    @f.register(Dog)
    def f_dog(a: Dog) -> str:
        return "Dog"

    dog = Dog()
    assert f(dog) == "Dog"
    assert f(Animal()) == "Animal"


def test_exact_match_beats_inheritance():
    class Animal:
        pass

    class Dog(Animal):
        pass

    @dispatch
    def f(a: Animal) -> str:
        return "Animal"

    @f.register(Dog)
    def f_dog(a: Dog) -> str:
        return "Dog"

    dog = Dog()
    assert f(dog) == "Dog"


def test_getitem_returns_default():
    @dispatch
    def add(a: int, b: int) -> int:
        return a + b

    impl = add[object, object]
    assert impl(1, 2) == 3


def test_setitem_returns_none():
    @dispatch
    def foo(a: int, b: int) -> int:
        return a

    class SetTracker:
        pass

    tracker = SetTracker()
    foo[int, int] = tracker
    assert foo._registry[(int, int)] is tracker


def test_default_fallback_with_unmatched_types():
    @dispatch
    def add(a, b):
        return a + b

    @add.register(int, float)
    def add_int_float(a: int, b: float) -> float:
        return float(a) + b

    assert add("a", "b") == "ab"


def test_cache_invalidated_by_later_registration():
    # a later, more specific registration must win even for a type that was
    # already dispatched (and so memoized) before that registration existed
    class Animal:
        pass

    class Dog(Animal):
        pass

    @dispatch
    def speak(a: Animal) -> str:
        return "..."

    dog = Dog()
    assert speak(dog) == "..."  # caches the Animal fallback for (Dog,)

    @speak.register(Dog)
    def _(a: Dog) -> str:
        return "Woof!"

    assert speak(dog) == "Woof!"


def test_cache_invalidated_across_inherit_chain():
    parent = Multimethod(lambda x: "parent-default")
    child = parent.inherit()

    class Node:
        pass

    node = Node()
    assert child(node) == "parent-default"  # caches the parent fallthrough

    parent.register(Node)(lambda x: "parent-node")

    assert child(node) == "parent-node"


def test_repeated_calls_use_the_cache_consistently():
    class Animal:
        pass

    class Dog(Animal):
        pass

    @dispatch
    def speak(a: Animal) -> str:
        return "..."

    @speak.register(Dog)
    def _(a: Dog) -> str:
        return "Woof!"

    dog = Dog()
    for _ in range(5):
        assert speak(dog) == "Woof!"


def test_dispatch_default_matches_object_whatever_its_annotations():
    @dispatch
    def f(a: str, b=None) -> str:
        return "default"

    assert f.registry == {object: f.__wrapped__}
    with pytest.raises(KeyError):
        f[str]
    assert f(1) == f(1, 2) == "default"


def test_calls_dispatch_on_the_required_positional_params():
    @dispatch
    def f(a, b, c=None) -> str:
        return f"default {c}"

    @f.register
    def _(a: int, b: int, c: str = "unset") -> str:
        return f"int, int {c}"

    assert f.registry == {(object, object): f.__wrapped__, (int, int): _}
    assert f(1, 2) == "int, int unset"
    assert f(1, 2, "c") == "int, int c"
    assert f("a", 2, c="c") == "default c"
    with pytest.raises(
        TypeError, match=r"f\(\) takes 2 arguments to dispatch on, got 1: missing 'b'$"
    ) as exc_info:
        f(1)
    assert exc_info.type is TypeError


def test_dispatch_takes_an_arity():
    @dispatch(arity=2)
    def f(*args) -> str:
        return "default"

    f.register(int, int)(lambda a, b, *rest: f"int, int {len(rest)}")
    assert f(1, 2, 3) == "int, int 1"
    assert f("a", "b") == "default"

    def g(a, b=None) -> str:
        return "default"

    assert dispatch(g, arity=2).registry == {(object, object): g}


def test_arity_must_be_a_natural_number():
    def f(*args) -> str:
        return "default"

    for arity in ["2", 1.5]:
        with pytest.raises(
            TypeError, match=f"^arity must be an integer, got {arity!r}$"
        ):
            dispatch(f, arity=arity)
    with pytest.raises(ValueError, match="^arity must be at least 0, got -1$"):
        dispatch(arity=-1)(f)
    with pytest.raises(ValueError, match="^arity must be at least 0, got -1$"):
        Multimethod(arity=-1)


def test_dispatch_default_arity_ignores_keyword_only_params():
    @dispatch
    def f(a, *, key=None, **kwargs) -> str:
        return f"default {key}"

    assert f.registry == {object: f.__wrapped__}
    assert f(1, key="k", extra=0) == "default k"


def test_multimethod_needs_a_default_or_an_arity():
    with pytest.raises(TypeError, match="needs a default function or an arity"):
        Multimethod()
    bare = Multimethod(arity=2)
    with pytest.raises(NoMatchError):
        bare(1, 2)

    def varargs(*args):
        return len(args)

    with pytest.raises(TypeError) as exc_info:
        dispatch(varargs)
    assert str(exc_info.value) == (
        f"can't infer the arity of {_located(varargs)}, which takes *args; pass "
        f"arity explicitly"
    )
    assert Multimethod(varargs, arity=2)(1, 2, 3) == 3

    def opaque(*args):
        return len(args)

    # Builtins like `max` have no signature on CPython, but do on PyPy.
    opaque.__signature__ = "unreadable"
    with pytest.raises(TypeError, match="can't read the signature"):
        dispatch(opaque)
    assert Multimethod(opaque, arity=2)(1, 2) == 2

    @dispatch
    def nullary() -> str:
        return "default"

    assert nullary() == "default"


def test_register_rejects_another_arity_than_the_default():
    @dispatch
    def f(a, b) -> str:
        return "default"

    def _(a) -> str:
        return "int"

    with pytest.raises(TypeError) as exc_info:
        f.register(int, _)
    assert str(exc_info.value) == (
        f"can't register {_located(_)} for f(int): {f.__qualname__} dispatches "
        f"on 2 arguments, not 1"
    )
    with pytest.raises(TypeError) as exc_info:
        f.register(int)
    assert str(exc_info.value) == (
        f"can't register for f(int): {f.__qualname__} dispatches on 2 arguments, not 1"
    )
    with pytest.raises(TypeError, match=r"for f\(\): .* not 0$"):
        f[()] = lambda a, b: "nothing"
    with pytest.raises(TypeError, match=r"for f\(int, int, int\): .* not 3$"):
        f[int, int, int] = lambda a, b, c: "int, int, int"
    assert list(f.registry) == [(object, object)]
    with pytest.raises(
        TypeError, match=r"f\(\) takes 2 arguments to dispatch on, got 1: missing 'b'$"
    ) as exc_info:
        f(1)
    assert exc_info.type is TypeError


def test_register_suggests_func_for_a_trailing_class():
    class Box:
        def __init__(self, x):
            self.x = x

    @dispatch
    def f(a) -> str:
        return "default"

    with pytest.raises(TypeError) as exc_info:
        f.register(int, Box)
    assert str(exc_info.value) == (
        f"can't register for f(int, Box): {f.__qualname__} dispatches on 1 "
        f"argument, not 2; to register Box itself as the implementation, pass "
        f"func=Box"
    )
    assert list(f.registry) == [object]


def test_register_takes_a_class_as_implementation():
    class Box:
        def __init__(self, x: int):
            self.x = x

    @dispatch
    def f(a) -> str:
        return "default"

    assert f.register(int, func=Box) is Box

    @f.register(str)
    class Label:
        def __init__(self, text):
            self.text = text

    assert isinstance(f(1), Box)
    assert isinstance(f("a"), Label)
    assert f[int] is Box
    with pytest.raises(TypeError, match="class Box for from annotations; pass "):
        f.register(func=Box)


def test_dispatch_rejects_a_method_taking_self():
    # called directly, since some interpreters wrap __set_name__ errors
    # raised by a class statement in a RuntimeError
    @dispatch
    def meth(self, x) -> str:
        return "default"

    class A:
        pass

    with pytest.raises(
        TypeError,
        match=r"meth at .* takes self, .*; use dispatchmethod for .*A\.meth$",
    ):
        meth.__set_name__(A, "meth")

    class B:
        @dispatch
        def helper(x) -> str:  # noqa: N805
            return "default"

        @helper.register(int)
        def _(x) -> str:  # noqa: N805
            return "int"

    assert B.helper(1) == B().helper(1) == "int"


def test_dispatch_takes_only_a_function():
    with pytest.raises(TypeError, match=r"dispatch\(\) expected a function, got 42"):
        dispatch(42)
    with pytest.raises(TypeError, match=r"dispatch\(\) expected a function"):
        dispatch(int)


def test_dispatch_called_bare_is_dispatch():
    @dispatch()
    def f(a, b=None) -> str:
        return "default"

    f.register(int)(lambda a, b=None: "int")
    assert f(1) == "int"
    assert f("a", 2) == "default"


def test_register_bare_uses_annotations():
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register
    def f_int(a: int) -> str:
        return "int"

    assert f[int] is f_int
    assert f(1) == "int"
    assert f("s") == "default"


def test_register_with_empty_parentheses_uses_annotations():
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register()
    def f_int(a: int) -> str:
        return "int"

    assert f[int] is f_int


def test_register_explicit_types_take_precedence_over_annotations():
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register(int)
    def f_int(a: str) -> str:
        return "int"

    assert f[int] is f_int
    with pytest.raises(KeyError):
        f[str]


def test_register_requires_annotation_on_every_parameter():
    @dispatch
    def f(a: object, b: object) -> str:
        return "default"

    def g(a: int, b) -> str:
        return "g"

    with pytest.raises(TypeError, match="no type annotation on parameter 'b'"):
        f.register(g)


def test_register_ignores_keyword_only_annotations():
    @dispatch
    def f(a: object, *, key: object = None) -> str:
        return "default"

    @f.register
    def f_int(a: int, *, key: str = "", **kwargs: int) -> str:
        return f"int {key}"

    assert f.registry == {object: f.__wrapped__, int: f_int}
    assert f(1, key="k") == "int k"


def test_register_evaluates_string_annotations():
    # what every annotation is under `from __future__ import annotations`;
    # evaluated as functools does
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register
    def g(a: "int") -> str:
        return "g"

    assert f[int] is g
    assert f(1) == "g"


def test_register_reads_a_partials_annotations():
    @dispatch
    def f(a: object) -> str:
        return "default"

    def g(a: int, suffix: str) -> str:
        return f"int{suffix}"

    f.register(functools.partial(g, suffix="!"))
    assert f(1) == "int!"


def test_register_rejects_unresolvable_string_annotation():
    @dispatch
    def f(a: object) -> str:
        return "default"

    def g(a: "Undefined") -> str:  # noqa: F821
        return "g"

    with pytest.raises(TypeError) as exc_info:
        f.register(g)
    assert str(exc_info.value) == (
        f"register() can't resolve the annotation 'Undefined' of parameter 'a' "
        f"of {_located(g)} (name 'Undefined' is not defined); define it before "
        f"registering, or pass the types explicitly"
    )

    def h(a: "functools.nope") -> str:
        return "h"

    with pytest.raises(TypeError, match=r"'functools\.nope' .*has no attribute 'nope'"):
        f.register(h)


def test_register_resolves_forward_references_in_unions():
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register
    def _(a: Optional["int"], b: "Undefined" = None) -> str:  # noqa: F821
        return "optional int"

    assert f(None) == "optional int"

    def g(a: Optional["Undefined"]) -> str:  # noqa: F821
        return "g"

    with pytest.raises(TypeError) as exc_info:
        f.register(g)
    assert str(exc_info.value) == (
        f"register() can't resolve the annotation of parameter 'a' of "
        f"{_located(g)} (name 'Undefined' is not defined); define it before "
        f"registering, or pass the types explicitly"
    )


def test_register_resolves_string_annotations_one_by_one():
    # As under `from __future__ import annotations`.
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register
    def _(a: "int", b: "Later" = None) -> "Later":  # noqa: F821
        return "int"

    assert f(1) == "int"


def test_register_requires_parameters_to_dispatch_on():
    @dispatch
    def f(a: object) -> str:
        return "default"

    with pytest.raises(TypeError, match="too few parameters to dispatch on"):
        f.register(lambda: "g")

    def h(*args: int) -> str:
        return "h"

    with pytest.raises(TypeError, match="too few parameters to dispatch on"):
        f.register(h)

    def g() -> str:
        return "partial"

    with pytest.raises(TypeError) as exc_info:
        f.register(functools.partial(g))
    assert f"in functools.partial({_located(g)}): needs 1" in str(exc_info.value)


def test_register_errors_locate_the_implementation():
    @dispatch
    def f(a: object) -> str:
        return "default"

    def _(a) -> str:
        return "_"

    location = f"{_.__qualname__} at {__file__}:{_.__code__.co_firstlineno};"
    with pytest.raises(TypeError, match=re.escape(location)):
        f.register(_)


def test_register_rejects_non_types():
    @dispatch
    def f(a: object) -> str:
        return "default"

    with pytest.raises(TypeError, match=r"register\(\) expected types, got 42$"):
        f.register(42)
    with pytest.raises(TypeError, match=r"got 'int' \(.*pass the class itself\)$"):
        f.register("int")


def test_register_accepts_types_outside_the_default_annotation():
    class Animal:
        pass

    @dispatch
    def f(a: Animal, b: int) -> str:
        return "default"

    f.register(object, int)(lambda a, b: "object, int")
    f[Animal, str] = lambda a, b: "animal, str"
    assert f(1, 2) == "object, int"
    assert f(Animal(), "s") == "animal, str"
    assert f(Animal(), 1.0) == "default"


def test_setitem_accepts_any_object():
    @dispatch
    def f(a: object) -> str:
        return "default"

    marker = object()
    f[int] = marker
    assert f[int] is marker


def test_any_means_object():
    @dispatch
    def f(a: Any, b: Any) -> str:
        return "default"

    assert f[object, object] is f.__wrapped__
    f.register(int, int)(lambda a, b: "int, int")  # subclasses of the default's Any

    @f.register
    def g(a: Any, b: int) -> str:
        return "any, int"

    assert f(1, 1) == "int, int"
    assert f("s", 1) == "any, int"
    assert f("s", "s") == "default"


def test_none_means_nonetype():
    @dispatch
    def f(a: object, b: object) -> str:
        return "default"

    f.register(None, object)(lambda a, b: "none, object")

    @f.register
    def g(a: None, b: None) -> str:
        return "none, none"

    assert f(None, 1) == "none, object"
    assert f(None, None) == "none, none"
    assert f[None, None] is f[type(None), type(None)]


def test_optional_and_union_members():
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register
    def g(a: Optional[int]) -> str:
        return "int or none"

    f.register(Union[str, bytes, None])(lambda a: "str, bytes or none")

    assert f(1) == "int or none"
    assert f(None) == "str, bytes or none"
    assert f(b"b") == "str, bytes or none"
    assert f[Union[str, bytes]] is f[bytes]
    with pytest.raises(KeyError):
        f[Optional[int]]  # int and None now have different implementations


def test_annotated_means_its_type():
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register
    def g(a: Annotated[int, "metadata"]) -> str:
        return "int"

    assert f[int] is g
    assert f(1) == "int"


def test_typevar_means_its_bound_or_constraints():
    Unbound = TypeVar("Unbound")
    Bound = TypeVar("Bound", bound=int)
    Constrained = TypeVar("Constrained", str, bytes)

    @dispatch
    def f(a: Unbound) -> str:
        return "default"

    f.register(Bound)(lambda a: "int")

    @f.register
    def g(a: Constrained) -> str:
        return "str or bytes"

    assert f[object] is f.__wrapped__
    assert f(True) == "int"
    assert f("s") == f(b"b") == "str or bytes"


def test_parameterized_generics_are_rejected():
    @dispatch
    def f(a: object) -> str:
        return "default"

    def g(a: list[int]) -> str:
        return "list"

    for annotation in (list[int], List[int], List, Callable[[], int], Literal[1]):
        with pytest.raises(TypeError, match="expected types"):
            f.register(annotation)(g)
    with pytest.raises(TypeError, match=r"got list\[int\] \(.*; use list\)$"):
        f.register(list[int])
    for annotation in (Optional[list[int]], Annotated[list[int], "meta"]):
        with pytest.raises(TypeError, match=r"; use list\)$"):
            f.register(annotation)
    with pytest.raises(TypeError, match=r"expected types, got [^(]*$"):
        f.register(Literal[1] | None)
    with pytest.raises(TypeError, match=r"; use list\); pass the types explicitly$"):
        f.register(g)


def test_dispatch_default_ignores_parameterized_generics():
    @dispatch
    def f(a: list[int]) -> str:
        return "default"

    assert f[object] is f.__wrapped__


def test_dispatch_method_accepts_annotations():
    @dispatch
    def f(a: object) -> str:
        return "default"

    f.register(int)(lambda a: "int")
    assert f.dispatch(None) is f.__wrapped__
    assert f.dispatch(Annotated[bool, "m"])(True) == "int"
    with pytest.raises(TypeError, match="one class per argument"):
        f.dispatch(Optional[int])


def test_dispatch_method_errors_match_a_calls():
    class A:
        pass

    class B:
        pass

    class AB(A, B):
        pass

    f = Multimethod(arity=1)
    f.register(A)(lambda a: "A")
    f.register(B)(lambda a: "B")
    with pytest.raises(
        TypeError, match=r"^dispatch\(\) expected 1 type, got 2: \(A, B\)$"
    ):
        f.dispatch(A, B)
    with pytest.raises(TypeError, match=r"got 2: \(A \| B \| None, int\)$"):
        f.dispatch(Optional[A | B], int)
    for cls, error in [(AB, AmbiguousMatchError), (int, NoMatchError)]:
        with pytest.raises(error) as from_dispatch:
            f.dispatch(cls)
        with pytest.raises(error) as from_call:
            f(cls())
        assert str(from_dispatch.value) == str(from_call.value)


def test_implementation_errors_point_at_its_call():
    @dispatch
    def f(a: object) -> str:
        return "default"

    @f.register(int)
    def _(a, b) -> str:
        return "int"

    with pytest.raises(TypeError, match="missing 1 required positional") as exc_info:
        f(1)
    (entry,) = [e for e in exc_info.traceback if e.name == "__call__"]
    assert "lookup" not in str(entry.statement)


def test_call_takes_dispatched_arguments_by_the_default_names():
    @dispatch
    def f(a, b, c=None) -> str:
        return f"default {c}"

    @f.register(int, str)
    def _(x, y, c=None) -> str:
        return f"int, str {x} {y} {c}"

    assert f(b="s", a=1) == f(1, "s") == "int, str 1 s None"
    assert f(1, b="s", c=3) == "int, str 1 s 3"
    assert f(a="s", b=1) == "default None"


def test_implementation_errors_by_keyword_dont_chain_to_dispatch_errors():
    @dispatch
    def f(a, b) -> str:
        raise ValueError("default")

    with pytest.raises(ValueError) as exc_info:
        f(1, b=2)
    assert exc_info.value.__context__ is None


def test_call_missing_dispatched_arguments_names_them():
    @dispatch
    def f(a, b, c=None) -> str:
        return "default"

    with pytest.raises(TypeError) as exc_info:
        f(1, c=3)
    assert str(exc_info.value) == (
        f"{f.__qualname__}() takes 2 arguments to dispatch on, got 1: missing 'b'"
    )
    with pytest.raises(TypeError, match=r"got 0: missing 'a', 'b'$"):
        f(b=2)


def test_call_cant_take_positional_only_dispatched_arguments_by_keyword():
    @dispatch
    def f(a, /, b, **kwargs) -> str:
        return f"default {kwargs}"

    assert f(1, b=2) == "default {}"
    with pytest.raises(TypeError, match=r"takes 2 arguments to dispatch on, got 0$"):
        f(a=1, b=2)


def test_call_without_a_default_takes_dispatched_arguments_positionally():
    f = Multimethod(arity=1)
    f.register(int)(lambda a: "int")

    assert f(1) == "int"
    with pytest.raises(TypeError, match=r"takes 1 argument to dispatch on, got 0$"):
        f(a=1)


def test_lookup_passes_on_errors_of_its_own():
    error = TypeError("can't check subclasses")

    class Failing(type):
        def __subclasscheck__(cls, subclass):
            raise error

    class Base(metaclass=Failing):
        pass

    @dispatch
    def f(a: object) -> str:
        return "default"

    f.register(Base)(lambda a: "base")
    with pytest.raises(TypeError) as exc_info:
        f(1)
    assert exc_info.value is error


def test_arity_zero_dispatches_on_nothing():
    @dispatch
    def f() -> str:
        return "default"

    assert f() == "default"
    with pytest.raises(TypeError, match="dispatches on 0 arguments, not 1$"):
        f.register(int)
    f[()] = lambda: "replaced"
    assert f() == "replaced"


@pytest.mark.skipif(sys.version_info < (3, 14), reason="lazy annotations")
def test_unresolved_annotations_off_dispatch_are_ignored():
    @dispatch
    def f(a, b: Later = None) -> Later:  # noqa: F821
        return "default"

    @f.register
    def _(a: int, b: Later = None) -> Later:  # noqa: F821
        return "int"

    assert f(1) == "int"


@pytest.mark.skipif(sys.version_info < (3, 14), reason="lazy annotations")
def test_register_rejects_unresolved_lazy_annotation():
    @dispatch
    def f(a: object) -> str:
        return "default"

    def g(a: Later) -> str:  # noqa: F821
        return "g"

    def h(a: Optional[Later]) -> str:  # noqa: F821
        return "h"

    for func in [g, h]:
        with pytest.raises(TypeError, match="name 'Later' is not defined"):
            f.register(func)

    class Later:
        pass

    f.register(g)
    assert f(Later()) == "g"
    f.register(h)
    assert f(None) == "h"


@dispatch
def module_level(a) -> str:
    return "default"


@module_level.register(int)
def _(a) -> str:
    return "int"


def test_multimethod_pickles_by_reference():
    assert pickle.loads(pickle.dumps(module_level)) is module_level
    with pytest.raises(TypeError, match="cannot pickle Multimethod: it has no "):
        pickle.dumps(Multimethod(arity=1))
