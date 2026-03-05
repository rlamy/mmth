# mmth

A simple multiple-dispatch library for Python.

## Installation

```bash
pip install mmth
```

## Usage

```python
from mmth import dispatch

@dispatch
def greet(name: str) -> str:
    return f"Hello, {name}!"

# Register a variant
@greet.register(int)
def _(n: int) -> str:
    return f"Hello, number {n}!"

print(greet("World"))  # Hello, World!
print(greet(42))       # Hello, number 42!
```

### Multiple Arguments

```python
@dispatch
def add(a: int, b: int) -> int:
    return a + b

@add.register(str, str)
def _(a: str, b: str) -> str:
    return a + b

print(add(1, 2))      # 3
print(add("a", "b"))  # ab
```

### Inheritance Support

```python
class Animal:
    pass

class Dog(Animal):
    pass

@dispatch
def make_sound(animal: Animal) -> str:
    return "..."

@make_sound.register(Dog)
def _(dog: Dog) -> str:
    return "Woof!"

dog = Dog()
print(make_sound(dog))  # Woof!
```

## Development

```bash
pip install -e ".[dev]"
pytest
```
