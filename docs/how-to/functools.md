# Migrate from `functools.singledispatch`

With a single dispatched argument, mmth behaves like `functools` except for
the [differences](../reference/functools.md) listed in the reference. This
guide goes through the changes they can call for.

## Replace the decorators

Use `dispatch` for `functools.singledispatch`, and `dispatchmethod` for
`functools.singledispatchmethod`:

```python
from mmth import dispatch

@dispatch
def show(arg: object) -> str:
    return repr(arg)

@show.register
def _(arg: int) -> str:
    return f"int {arg}"
```

`register()` takes the same forms (bare, with a type, or with a type and
an implementation), and `show.dispatch(cls)` and `show.registry` work as
before.

## Check what changes

- **Ties between base classes**: where functools picks the first of
  several matching bases in the MRO, mmth raises `AmbiguousMatchError`.
  Register the subclass itself to resolve each one, and add a test calling
  `detect_ambiguities()` (see [Resolve ambiguities](ambiguities.md)).
- **Implementations for `Any`**: functools never runs them, but mmth reads
  `Any` as `object`, so they replace the default, with a
  `RedefinitionWarning`. Remove them.
- **A class as an implementation**: `register(Type, SomeClass)` raises
  `TypeError`; pass it as `register(Type, func=SomeClass)`.
- **`singledispatch` on a method**: functools dispatches on `self`, while
  mmth raises `TypeError` when the class is created. Use `dispatchmethod`
  to dispatch on the next argument instead, or a module-level `dispatch`
  function called with the instance to dispatch on its type.
- **Replaced implementations**: registering another implementation for a
  type that already has one now warns with `RedefinitionWarning`. Remove
  the duplicate, or [silence the warning](register.md#replace-an-implementation)
  where replacing is intended.
- **`registry` entries for class and static methods**: they hold a plain
  function taking the multimethod's arguments, rather than the
  `classmethod` or `staticmethod` object.

## Go further

A multimethod can then dispatch on several arguments: see
[Define and extend a multimethod](register.md).
