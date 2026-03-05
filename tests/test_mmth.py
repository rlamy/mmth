import pytest
from mmth import dispatch


class TestDispatcher:
    def test_basic_dispatch(self):
        @dispatch
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        assert greet("World") == "Hello, World!"

    def test_register_variant(self):
        @dispatch
        def add(a: int, b: int) -> str:
            return f"int + int: {a + b}"

        @add.register(int, int)
        def _(a: int, b: int) -> int:
            return a + b

        assert add(1, 2) == 3

    def test_inheritance_dispatch(self):
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

    def test_no_match_raises_type_error(self):
        @dispatch
        def foo(a: int) -> int:
            return a

        @foo.register(int)
        def _(a: int) -> int:
            return a * 2

        assert foo(5) == 10

        with pytest.raises(TypeError):
            foo("not an int")
