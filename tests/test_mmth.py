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
    d = Multimethod()
    d.register(int)(lambda a: a * 2)
    assert d(5) == 10
    with pytest.raises(NoMatchError, match="No key matches"):
        d("not an int")


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
    assert "No implementation registered" in str(exc_info.value)


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
    assert "Ambiguous lookup" in str(exc_info.value)


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
    def foo(a: int) -> int:
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
    parent = Multimethod()
    parent.register(object)(lambda x: "parent-default")
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

    assert f.registry == {(object, object): f.__wrapped__}
    with pytest.raises(KeyError):
        f[str, object]
    assert f(1, 2) == "default"
    assert f(1) == "default"  # still the fallback for another arity


def test_dispatch_takes_only_a_function():
    with pytest.raises(TypeError, match=r"dispatch\(\) expected a function, got 42"):
        dispatch(42)
    with pytest.raises(TypeError, match=r"dispatch\(\) expected a function"):
        dispatch(int)
    with pytest.raises(TypeError):
        dispatch()  # type: ignore[call-arg]


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


def test_register_rejects_unresolvable_string_annotation():
    @dispatch
    def f(a: object) -> str:
        return "default"

    def g(a: "Undefined") -> str:  # noqa: F821
        return "g"

    with pytest.raises(TypeError, match="can't dispatch on parameter 'a'"):
        f.register(g)


def test_register_requires_parameters_to_dispatch_on():
    @dispatch
    def f(a: object) -> str:
        return "default"

    with pytest.raises(TypeError, match="no parameters to dispatch on"):
        f.register(lambda: "g")


def test_register_rejects_non_types():
    @dispatch
    def f(a: object) -> str:
        return "default"

    with pytest.raises(TypeError, match=r"register\(\) expected types, got 42"):
        f.register(42)


def test_register_accepts_types_outside_the_default_annotation():
    class Animal:
        pass

    @dispatch
    def f(a: Animal, b: int) -> str:
        return "default"

    f.register(object, int)(lambda a, b: "object, int")
    f[Animal, str] = lambda a, b: "animal, str"
    f.register(int)(lambda a: "one argument")
    assert f(1, 2) == "object, int"
    assert f(Animal(), "s") == "animal, str"
    assert f(Animal(), 1.0) == "default"
    assert f(1) == "one argument"


def test_setitem_accepts_any_object():
    @dispatch
    def f(a: object) -> str:
        return "default"

    marker = object()
    f[int] = marker
    assert f[int] is marker


def test_any_means_object():
    @dispatch
    def f(a: Any) -> str:
        return "default"

    assert f[object] is f.__wrapped__
    f.register(int)(lambda a: "int")  # a subclass of the default's Any

    @f.register
    def g(a: Any, b: int) -> str:
        return "any, int"

    assert f(1) == "int"
    assert f("s", 1) == "any, int"


def test_none_means_nonetype():
    @dispatch
    def f(a: object) -> str:
        return "default"

    f.register(None)(lambda a: "none")

    @f.register
    def g(a: None, b: None) -> str:
        return "none, none"

    assert f(None) == "none"
    assert f(None, None) == "none, none"
    assert f[None] is f[type(None)]


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
    with pytest.raises(TypeError, match="can't dispatch on parameter 'a'"):
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
