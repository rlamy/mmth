# Static Typing

mmth is typed (it ships a `py.typed` marker), so type checkers such as mypy
and pyright check code that uses it: calls to a multimethod, and the
implementations registered on it.

## Calls

A multimethod is typed by its default implementation's signature: its type
is `Multimethod[P, R]`, for the default's parameters `P` and return type `R`.
Registered types must be subclasses of the default's, so any call that
dispatches is one the default's signature accepts:

```python
from mmth import dispatch

class Animal: ...
class Dog(Animal): ...
class Cat(Animal): ...

@dispatch
def meet(a: Animal, b: Animal) -> str:
    return "sniff"

@meet.register
def _(a: Dog, b: Cat) -> str:
    return "chase"

reveal_type(meet(Dog(), Cat()))  # str
meet(Dog(), 1)                   # error: "int" is not "Animal"
meet(Dog())                      # error: missing argument "b"
```

As for any function, a parameter without an annotation accepts anything,
and a missing return annotation is either `Any` or inferred from the
default's body, depending on the type checker.

## Implementations

An implementation is only called with arguments of the types it's
registered for, so it can narrow the default's parameters, but it has to
return what the default does. Type checkers check each registration as
follows:

| Registration | Checked statically |
|---|---|
| `@f.register` (types from annotations) | The return type |
| `@f.register(T1, T2)` | The return type; that the implementation accepts `T1, T2`; that the default does too |
| `f.register(T, impl)` | The return type; that `impl` accepts `T` |
| `f.register(*types, func=impl)`, `f[types] = impl` | The return type |

```python
@meet.register(Dog, Dog)
def _(a: Dog, b: Dog) -> int:      # error: returns "int", not "str"
    return 0

@meet.register(Dog, Animal)
def _(a: Dog, b: Dog) -> str:      # error: doesn't accept "Animal" as b
    return "wag"

@meet.register(int, Dog)           # error: the default doesn't accept "int"
def _(a: int, b: Dog) -> str:
    return "?"
```

That last error can read oddly (pyright reports that the result of
`register()` "is not callable", mypy that it expected `*Never`), but it
points at the right line.

With explicit types, the implementation is checked against up to three
classes; with more, or with a union (mypy doesn't treat `Dog | Cat` as a
class), only its return type is. Annotations are always checked when the
implementation is registered, at runtime: `register()` raises `TypeError`
if they aren't subclasses of the default's, so importing the module is
enough to catch that.

Registering returns the implementation typed as `Any`: implementations are
usually all named `_`, which type checkers would otherwise check against
each other, as redefinitions or, in a subclass, as method overrides.

## Methods

A `dispatchmethod` binds `self` like a method, so the type of
`obj.method` is the default's signature without `self`. Under
`@classmethod` it binds the class instead, and under `@staticmethod` it
doesn't bind:

```python
from mmth import dispatchmethod

class Node: ...
class Num(Node): ...

class Evaluator:
    @dispatchmethod
    def visit(self, node: Node) -> int:
        raise TypeError(type(node).__name__)

    @visit.register(Num)
    def _(self, node: Num) -> int:
        return 1

    @dispatchmethod
    @classmethod
    def parse(cls, text: str) -> Node:
        return Num()

reveal_type(Evaluator().visit)       # (node: Node) -> int
reveal_type(Evaluator.parse("1"))    # Node
```

In a subclass, `Base.visit.inherit()` keeps the base multimethod's type,
so its registrations are checked as above. A bare `inherit()` doesn't know
which base multimethod it will inherit from, so it accepts any
implementation and its calls are untyped (pyright still infers them from
the base class).

## Limitations

- **A different number of arguments from the default**: mmth lets
  implementations take more or fewer arguments than the default, but type
  checkers only accept calls matching the default's signature. To dispatch
  on different numbers of arguments, give the default `*args`, which also
  keeps its return type checked:

  ```python
  from typing import Any

  @dispatch
  def area(*args: Any) -> float:
      raise TypeError("no area for these")

  @area.register
  def _(side: float) -> float:
      return side * side

  @area.register
  def _(width: float, height: float) -> float:
      return width * height
  ```

- **Keyword arguments**: they're passed on to the implementation, but its
  parameter names aren't checked against the default's.
- **Other type checkers**: mypy and pyright are tested. ty mostly agrees,
  but isn't part of mmth's checks yet.
