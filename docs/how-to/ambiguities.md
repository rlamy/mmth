# Resolve Ambiguities

A call is ambiguous when several implementations match it and none is more
specific than all the others. mmth then raises `AmbiguousMatchError`
rather than picking one (see [Design](../explanation/design.md#specificity)).

## Register the missing signature

Ambiguities typically come from registering an operation symmetrically:

```python
from mmth import dispatch

class Animal: ...
class Dog(Animal): ...

@dispatch
def f(a: Animal, b: Animal) -> str:
    return "Animal, Animal"

@f.register(Dog, Animal)
def _(d: Dog, a: Animal) -> str:
    return "Dog, Animal"

@f.register(Animal, Dog)
def _(a: Animal, d: Dog) -> str:
    return "Animal, Dog"

f(Dog(), Dog())
# AmbiguousMatchError: f(Dog, Dog) is ambiguous between:
#   f(Dog, Animal): _ at example.py:10
#   f(Animal, Dog): _ at example.py:14
# Register f(Dog, Dog) to resolve it.
```

Neither `(Dog, Animal)` nor `(Animal, Dog)` is more specific than the
other, so `(Dog, Dog)` is ambiguous, and with it any pair of `Dog`
subclasses. Register the signature the error names:

```python
@f.register(Dog, Dog)
def _(a: Dog, b: Dog) -> str:
    return "Dog, Dog"
```

The same happens with a single dispatched argument and multiple
inheritance: given `class C(A, B)` and implementations for both `A` and
`B`, a call with a `C` is ambiguous until `C` is registered.

## Check for ambiguities in a test suite

`detect_ambiguities()` returns the errors that calls would raise, without
calling anything, so a test can check that none are left:

```python
def test_f_has_no_ambiguities():
    assert not f.detect_ambiguities()
```

Each error carries the ambiguous `types` and the matching `candidates`.

It only considers classes that exist when it's called, so run it once the
modules defining them are imported. It doesn't find ambiguities involving
virtual or structural subclasses of an ABC, as there's no way to list them
(see [Design](../explanation/design.md#detecting-ambiguities)).
