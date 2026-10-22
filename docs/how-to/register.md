# Define and Extend a Multimethod

This guide covers creating a multimethod and adding implementations to it.
The exact rules are in [Dispatch rules](../reference/dispatch.md).

## Define a multimethod with a default

Decorate the default implementation with `dispatch`. It runs whenever no
more specific implementation matches:

```python
from mmth import dispatch

class Animal: ...
class Dog(Animal): ...
class Cat(Animal): ...

@dispatch
def make_sound(animal: Animal) -> str:
    return "..."
```

The default's required positional parameters are the ones dispatched on;
their number is the multimethod's **arity**. Their annotations don't
restrict dispatch: the default is registered for `object` at each of them,
and calls are type-checked against them (see
[Static typing](../reference/typing.md)). Other arguments, like optional
parameters, are passed on to the implementation without being dispatched
on.

## Dispatch on another number of arguments

Pass `arity`, not counting `self` for a method:

```python
@dispatch(arity=1)
def describe(x: object, *details: str) -> str:
    return " ".join([str(x), *details])

larger = dispatch(max, arity=2)
```

It's required when the default takes `*args`, or has no signature to read,
as for some builtins.

## Define a multimethod without a default

When no implementation makes sense for arbitrary arguments, declare the
multimethod with a stub:

```python
class Shape: ...

@dispatch(stub=True)
def area(shape: Shape, /, *, units: str = "m") -> float:
    """Return the area of `shape`."""
    ...
```

The stub gives the multimethod its name, docstring, signature and arity,
but is never registered or called, so a call that matches no
implementation raises `NoMatchError`.

## Register implementations

Decorate the implementation with `register`, taking the types from its
annotations, or passing them explicitly:

```python
@make_sound.register
def _(dog: Dog) -> str:
    return "Woof!"

@make_sound.register(Cat)
def _(cat) -> str:
    return "Meow!"

make_sound(Dog())     # Woof!
make_sound(Cat())     # Meow!
make_sound(Animal())  # ...
```

The multimethod keeps a reference to each implementation, so they don't
need distinct names. Pass the types explicitly when an implementation
isn't annotated, or when an annotation is a forward reference that can't
be resolved yet; explicit types take precedence over annotations.

With several dispatched arguments, give one type per argument:

```python
@dispatch
def add(a: object, b: object) -> object:
    return a + b

@add.register(int, float)
def _(a: int, b: float) -> float:
    return float(a) + b

add(1, 2)    # 3, from the default
add(1, 2.0)  # 3.0
```

To register one implementation for several types, use a union, as an
explicit type or an annotation: `@make_sound.register(Dog | Cat)`.

To register an existing callable without decorating it, pass it after the
types, or assign it:

```python
def meow(cat: Cat) -> str:
    return "Meow!"

make_sound.register(Cat, meow)
make_sound[Cat] = meow  # same
```

A class can be an implementation too, but since a class is also a type,
pass it as `func=`, with the types explicitly:
`make_sound.register(Cat, func=SomeClass)`.

## Call a more general implementation

To extend a more general implementation rather than replace it, look it up
with `dispatch()` and call it:

```python
class Puppy(Dog): ...

@make_sound.register
def _(puppy: Puppy) -> str:
    return make_sound.dispatch(Dog)(puppy) + " (squeaky)"

make_sound(Puppy())  # Woof! (squeaky)
```

## Pass dispatched arguments by keyword

Callers can pass dispatched arguments by keyword, named as in the default:
`add(b=2.0, a=1)` is `add(1, 2.0)`. The implementation receives them
positionally, whatever its own parameter names are.

## Replace an implementation

Registering a different implementation for a signature that's already
registered, the default included, replaces it and warns with
`RedefinitionWarning`. Where that's intended, silence the warning:

```python
import warnings

from mmth import RedefinitionWarning

with warnings.catch_warnings():
    warnings.simplefilter("ignore", RedefinitionWarning)

    @make_sound.register
    def _(dog: Dog) -> str:
        return "Yap!"
```

To silence it everywhere, or turn it into an error in a test suite, see
[`RedefinitionWarning`](../reference/api.md#mmth.RedefinitionWarning).

## Inspect a multimethod

```python
make_sound.dispatch(Puppy)  # the implementation a call with a Puppy runs
make_sound[Dog]             # the one registered for exactly Dog, else KeyError
make_sound.registry         # every registered signature and its implementation
```
