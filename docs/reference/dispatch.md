# Dispatch Rules

For examples, see the [how-to guides](../how-to/register.md); for the
reasons behind these rules, see [Design](../explanation/design.md).

## Defining a Multimethod

```python
@dispatch
def function_name(arg1, arg2, ...) -> ReturnType:
    """Default implementation"""
    ...
```

The decorated function is the **default implementation**, registered for
`object` at every required positional parameter, so it's called whenever no
more specific signature matches. Its annotations are ignored. Their number
is the multimethod's **arity**: a call dispatches on its first `arity`
positional arguments, and passes any others, like optional parameters, on
to the implementation without dispatching on them.

A call can also pass dispatched arguments by keyword, by the default's
parameter names: after `def f(x, y)`, `f(y=1, x=2)` is `f(2, 1)`. The
implementation gets them positionally, whatever its own parameter names.
That excludes positional-only parameters, and a multimethod created with
no function at all (`Multimethod(arity=n)`) takes them positionally only.
Other keyword arguments are never dispatched on, only passed on to the
implementation.

The multimethod takes on the default's `__name__`, `__doc__`, `__wrapped__`,
etc., as with `functools.wraps`.

`dispatch` and `dispatchmethod` take keyword-only options:

- `arity`, an integer of at least 0, to dispatch on another number of
  arguments, as `@dispatch(arity=2)` or `dispatch(max, arity=2)` (not
  counting `self` for a method). It's required for a default that takes
  `*args`, or that has no signature to read (whether builtins like `max`
  do depends on the Python implementation): rather than guess, they raise
  `TypeError`. Without options, `@dispatch()` is just `@dispatch`.
- `stub=True`: the function is never registered or called. It gives the
  multimethod its name, docstring, signature, arity and parameter names,
  as a default would, and its type (see [Static typing](typing.md)), but
  its `registry` starts empty, so a call matching no implementation raises
  `NoMatchError`.

## Registering an Implementation

```python
@function_name.register(Type1, Type2, ...)
def function_name_impl(arg1, arg2, ...) -> ReturnType:
    ...

# Or bare, taking the types from the annotations
@function_name.register
def function_name_impl(arg1: Type1, arg2: Type2, ...) -> ReturnType:
    ...
```

| Method | Syntax | Returns |
|--------|--------|---------|
| `.register(*types)` | `@func.register(int, str)` | Decorator |
| `.register` | `@func.register` | The function (types from annotations) |
| `.register(*types, impl)` | `func.register(int, impl)` | `impl` |
| `.register(*types, func=impl)` | `func.register(int, func=impl)` | `impl` |
| `__setitem__` | `func[int, str] = impl` | `None` |

- Explicit types take precedence over annotations. Without them, every
  dispatched parameter must have a type annotation: a missing one raises
  `TypeError`. Registering by annotations reads those of the
  implementation's first `arity` positional parameters.
- String annotations (e.g. under `from __future__ import annotations`) are
  evaluated; one on a dispatched parameter that can't be resolved yet (a
  forward reference) raises `TypeError` too. Unresolved annotations
  elsewhere, on the return or other parameters, are ignored. Return
  annotations are never used for dispatch.
- A **union** (`int | str`, `Union[int, str]`, `Optional[int]`), as an
  explicit type or an annotation, registers the implementation for each
  member.
- An implementation can be any callable, a class included; but since a
  class is also a type, pass it as `func=SomeClass` (or decorate it), and
  pass the types explicitly, as its annotations aren't its parameters'.
- `register(*types)` checks at once that there are as many types as the
  multimethod's arity, rather than when the decorator it returns is
  applied, if ever. Registering another number of types raises
  `TypeError`, as does registering, for explicit types, an implementation
  with too few positional parameters to take them (past `self`/`cls`, and
  without `*args`).

Registering a different implementation for a signature the multimethod
already has, the default included, replaces it and warns with
`mmth.RedefinitionWarning`, attributed to the line that registered it.
Registering the same implementation again doesn't warn, nor does an
`inherit()` multimethod replacing its parent's. Where replacing is
intended, silence it with the `warnings` filters (see
[`RedefinitionWarning`](api.md#mmth.RedefinitionWarning)).

## Type Matching

- **Exact types**: `int` matches `int` only.
- **Subclass types**: `Animal` matches `Dog` if `Dog` is a subclass of
  `Animal`.
- **Single type shorthand**: `func[int]` is equivalent to `func[(int,)]`.
- **One arity**: every signature has the multimethod's arity, as many types
  as the default has required positional parameters (or
  `Multimethod(arity=n)`, required with no function). A call with fewer
  dispatched arguments, positional or by keyword, raises `TypeError` (not
  `NoMatchError`).
- **ABCs**: matching uses `issubclass`, so abstract base classes match their
  virtual subclasses (via `ABC.register()` or `__subclasshook__`), including
  ones registered after the multimethod was first called.

### Annotations That Aren't Classes

Wherever a type is expected (explicit types, annotations, `func[...]`), these
standard annotations stand for classes:

| Annotation | Dispatches as |
|------------|---------------|
| `Any` | `object` |
| `None` | `NoneType` |
| `Optional[X]`, `Union[X, Y]`, `X \| Y` | each member, as a union (see above) |
| `Annotated[X, ...]` | `X` |
| A `TypeVar` | its bound, else its constraints as a union, else `object` |

Anything else, notably a parameterized generic like `list[int]` or
`Literal[...]`, raises `TypeError` as an explicit type or a registered
implementation's annotation. For `func[...]` with a union, the same
implementation must be registered for every member.

## Dispatch Algorithm

When `function_name(arg1, arg2, ...)` is called:

1. **Collect runtime types**: `(arg1.__class__, arg2.__class__, ...)` -
   `__class__` rather than `type()`, so that proxies (e.g.
   `Mock(spec=SomeClass)`) dispatch as the class they stand in for.
2. **Exact match**: if `(Type1, Type2, ...)` is registered, call that
   implementation.
3. **Find all applicable signatures**: all registered signatures where each
   runtime type is a subclass of the registered type.
4. **Select the most specialized**: a signature A is **more specialized**
   than B if each of its types is a subclass of B's corresponding type.
   The applicable signature more specialized than all the others wins; if
   there's none, raise `AmbiguousMatchError`.
5. **No match**: if no registered signature matches, raise `NoMatchError`.
   The default's `(object, ...)` matches any call, so this only happens
   without one, as for a stub or `Multimethod(arity=n)`.

## Methods and Inheritance

- **`dispatchmethod`** binds `self` via the descriptor protocol and
  excludes it from dispatch. Its `.register()` takes the same forms as a
  function's, with types for the arguments after `self`.
- **Class and static methods**: a registered implementation can be a
  `classmethod` or `staticmethod` (applied below `.register()`), as can
  the `dispatchmethod` itself (applied below `@dispatchmethod`). Looked up
  on the class, an ordinary `dispatchmethod` takes the instance as its
  first argument, `Class.method(obj, arg)`, and dispatches on the others;
  so a `classmethod`/`staticmethod` implementation of it can only be
  called through an instance. `registry` and `func[types]` hold such
  implementations as plain functions taking the multimethod's own
  arguments.
- **`dispatch` on a method**: a `dispatch` multimethod isn't bound, so as a
  class attribute it works as a static function; one whose default takes
  `self` raises `TypeError` when the class is created, pointing to
  `dispatchmethod` (wrapped as for `inherit()`, below).
- **`Base.method.inherit()`** returns a multimethod for a subclass, which
  dispatches on the registrations `base | subclass`: a registration for
  the same types replaces the base's, and otherwise the most specific one
  wins, whichever class registered it. Its `registry` and `func[types]`
  show those merged registrations. Changes to the base's registrations
  apply to it too.
- **`inherit()`**, assigned as a class attribute, is `Base.method.inherit()`
  for the multimethod of the same name that the class's bases define, as
  `super()` would find it. It finds it when Python calls `__set_name__` on
  it, at the end of the class statement, and only registers then, since
  only the base multimethod tells the arity. So its errors, including no
  base class defining that name, are raised there. On Python 3.11 and PyPy
  3.11 they arrive wrapped in a `RuntimeError` with the original exception
  as its `__cause__`, as those interpreters do for `__set_name__` failures.
  `Base.method.inherit()` registers at once, so its errors aren't wrapped.

## Introspection

| Expression | Result |
|------------|--------|
| `func.dispatch(Type1, Type2, ...)` | The implementation a call with arguments of those types would run, without calling it |
| `func[Type1, Type2]` | The implementation registered for exactly these types, else `KeyError` |
| `func.registry` | A read-only mapping of every registered signature to its implementation, keyed by a bare type for a single argument, else a tuple |
| `func.detect_ambiguities()` | The `AmbiguousMatchError` a call would raise, for each ambiguity among the classes that exist now, without calling anything |

`detect_ambiguities()` doesn't know about virtual or structural subclasses
of an ABC. `TypeMap.detect_ambiguities()` does the same for a type map's
keys.

A multimethod pickles by reference, as a function does: by its module and
qualified name, so one defined at module level or as a class attribute
unpickles as itself.

## Type Maps

A multimethod's implementations live in a `mmth.TypeMap`, a mutable
mapping of exactly the signatures registered on it (so `del typemap[sig]`
unregisters `sig`), whose `lookup(types)` returns, cached, what a call
with arguments of `types` would run: exact match, else most specialized
(`lookup(types, default)` returns `default` instead of raising
`NoMatchError`, as `dict.get()` does).

It's built from an initial table, e.g. `TypeMap({(int,): f})`, whose keys
set its `arity`, the length all its keys share (`TypeMap(arity=n)` starts
one empty). An `inherit()` multimethod keeps them in a
`mmth.ChainTypeMap`, whose `lookup()` looks among the signatures
`parent | child`, sharing the parent's arity.

## Errors

| Error | Raised when |
|-------|-------------|
| `NoMatchError` (a `TypeError`) | A call, `dispatch()` or `TypeMap.lookup()` matches no registered signature |
| `AmbiguousMatchError` (a `TypeError`) | Several signatures match and none is more specialized than all the others |
| `KeyError` | `func[types]` or `del typemap[types]` names a signature that isn't registered |
| `TypeError` | A registration is invalid (see above), or a call passes fewer dispatched arguments than the arity |
| `RedefinitionWarning` (a warning) | A different implementation replaces a registered one |

Both lookup errors carry the `types` looked up; `AmbiguousMatchError` also
carries the `candidates`. Their messages name the call and the registered
signatures:

```python
@dispatch(stub=True)
def bar(a: object) -> int: ...

@bar.register(int)
def _(a: int) -> int:
    return a * 2

bar[float]  # KeyError: 'No implementation registered for exactly bar(float)'
bar("str")  # NoMatchError: bar(str) matches no implementation; registered: bar(int)
```
