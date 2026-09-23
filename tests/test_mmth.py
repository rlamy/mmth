import pytest

from mmth import dispatch
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


def test_no_match_raises_type_error():
    d = Multimethod()
    d.register(int)(lambda a: a * 2)
    assert d(5) == 10
    with pytest.raises(TypeError):
        d("not an int")


def test_getitem_getter():
    @dispatch
    def add(a: int, b: int) -> int:
        return a + b

    @add.register(int, float)
    def add_int_float(a: int, b: float) -> float:
        return float(a) + b

    impl = add[int, float]
    assert impl(1, 2.0) == 3.0


def test_setitem_setter():
    @dispatch
    def process(data: str) -> str:
        return data.upper()

    def custom_handler(data: dict) -> str:
        return str(data)

    process[dict] = custom_handler

    assert process("hello") == "HELLO"
    assert process({"key": "value"}) == "{'key': 'value'}"


def test_getitem_after_setitem():
    @dispatch
    def process(data: str) -> str:
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

    with pytest.raises(TypeError) as exc_info:
        f(Dog(), Dog())
    assert "Ambiguous dispatch" in str(exc_info.value)


def test_default_fallback_no_registrations():
    @dispatch
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3
    assert add("a", "b") == "ab"


def test_default_fallback_with_registrations():
    @dispatch
    def add(a: int, b: int) -> int:
        return a + b

    @add.register(int, float)
    def add_int_float(a: int, b: float) -> float:
        return float(a) + b

    assert add(1, 2) == 3
    assert add(1, 2.0) == 3.0


def test_no_implementation_at_all():
    d = Multimethod()
    d.register(int)(lambda a: a * 2)

    with pytest.raises(TypeError) as exc_info:
        d("str")
    assert "No matching implementation" in str(exc_info.value)


def test_single_type_shorthand():
    @dispatch
    def double(x: int) -> int:
        return x * 2

    @double.register(float)
    def double_float(x: float) -> float:
        return x * 2.0

    impl = double[int]
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

    impl = add[int, int]
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
    def add(a: int, b: int) -> int:
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


def test_cache_invalidated_across_override_chain():
    # a mutation to the *parent* multimethod must invalidate an
    # override()-chained child's cache too, since the child can fall
    # through to the parent's registry
    parent = Multimethod()
    parent.register(object)(lambda x: "parent-default")
    child = parent.override()

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
