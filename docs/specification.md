# Specification

## Syntax

### 1. Define Multimethod (Main Syntax)

```python
@dispatch
def function_name(arg1: Type1, arg2: Type2, ...) -> ReturnType:
    """Default implementation"""
    ...

# Or with explicit types, which take precedence over the annotations
@dispatch(Type1, Type2, ...)
def function_name(arg1, arg2, ...) -> ReturnType:
    ...
```

The decorated function is the **default implementation**, called whenever no
registered signature matches. It is also registered under its signature: the
explicit types if given, else its parameters' annotations, where a parameter
without a type annotation counts as `object`. The multimethod takes on the
default's `__name__`, `__doc__`, `__wrapped__`, etc., as with
`functools.wraps`.

### 2. Register an Implementation (Main Syntax)

```python
@function_name.register(Type1, Type2, ...)
def function_name_impl(arg1, arg2, ...) -> ReturnType:
    """Implementation for (Type1, Type2, ...)"""
    ...

# Or bare, taking the types from the annotations
@function_name.register
def function_name_impl(arg1: Type1, arg2: Type2, ...) -> ReturnType:
    ...
```

As with `@dispatch`, explicit types take precedence over annotations. Unlike
`@dispatch`, every parameter must then have a type annotation, since there is
no sensible default: a missing one raises `TypeError`. String annotations
(e.g. under `from __future__ import annotations`) are evaluated, as
`functools.singledispatch` does; one that can't be resolved yet (a forward
reference) raises `TypeError` too - pass the types explicitly in that case.

Also as with `functools.singledispatch`:

- A **union** (`int | str`, `Union[int, str]`, `Optional[int]`), as an
  explicit type or an annotation, registers the implementation for each
  member.
- `function_name.register(Type, impl)` or `.register(Type, func=impl)`
  registers `impl` directly, rather than returning a decorator.

**Registered types must be subclasses of the default's**: a signature of the
same length as the default's must be a subclass of it at every position (of
at least one member, for a union), or `register()` raises `TypeError`. The
default claims to handle its annotated types, so an implementation for
anything broader or unrelated would contradict it.

### 3. Register an Implementation (Metaprogramming)

```python
# Direct assignment
function_name[Type1, Type2] = implementation_callable

# Or with a function definition
def custom_impl(arg1: Type1, arg2: Type2) -> ReturnType:
    ...

function_name[Type1, Type2] = custom_impl
```

### 4. Access an Implementation

```python
impl = function_name[Type1, Type2]  # Returns registered callable or raises KeyError
```

## Semantics

### Dispatch Algorithm

When `function_name(arg1, arg2, ...)` is called:

1. **Collect runtime types**: `(arg1.__class__, arg2.__class__, ...)` -
   `__class__` rather than `type()`, as `functools.singledispatch` does, so
   that proxies (e.g. `Mock(spec=SomeClass)`) dispatch as the class they
   stand in for

2. **Exact match**: If `(Type1, Type2, ...)` exists in registry, call that implementation

3. **Find all applicable signatures**: All registered signatures where each runtime type is a subclass of the registered type

4. **Select most specialized**:
   - A signature A is **more specialized** than B if all its type parameters are subclasses of B's corresponding parameters
   - If neither A nor B is more specialized than the other → **ambiguity error**
   - If A beats B but not vice versa → A wins
   - Exact match beats inheritance match

5. **Fallback**:
   - If no registered signature matches → call the default implementation
     (the function decorated with `@dispatch`), whatever the argument types
   - If there is no default (a bare `Multimethod()`) → raise `TypeError`

### Registration Methods

| Method | Syntax | Returns |
|--------|--------|---------|
| `.register(*types)` | `@func.register(int, str)` | Decorator |
| `.register` | `@func.register` | The function (types from annotations) |
| `.register(type, impl)` | `func.register(int, impl)` | `impl` |
| `__setitem__` | `func[int, str] = impl` | `None` |
| `__getitem__` | `impl = func[int, str]` | Registered callable or raises `KeyError` |

### Type Matching Rules

- **Exact types**: `int` matches `int` only
- **Subclass types**: `Animal` matches `Dog` if `Dog` is subclass of `Animal`
- **Single type shorthand**: `func[int]` is equivalent to `func[(int,)]`
- **ABCs**: matching uses `issubclass`, so abstract base classes match their
  virtual subclasses (via `ABC.register()` or `__subclasshook__`), including
  ones registered after the multimethod was first called

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

Anything else, notably a parameterized generic like `list[int]` (dispatch
can't check its parameters) or `Literal[...]`, raises `TypeError` as an
explicit type or a registered implementation's annotation, and counts as
`object` in the default's annotations. For `func[...]` with a union, the same
implementation must be registered for every member.

### Introspection

As with `functools.singledispatch`:

- `func.dispatch(Type1, Type2, ...)` returns the implementation a call with
  arguments of those types would run, without calling it.
- `func.registry` is a read-only mapping of every registered signature to its
  implementation, keyed by a bare type for a single argument, else a tuple.

## Differences from `functools.singledispatch`

With a single dispatched argument, `dispatch` and `dispatchmethod` behave
like `functools.singledispatch` and `functools.singledispatchmethod`, except:

- **Ties raise instead of following the MRO**: given `class C(A, B)` with
  implementations for both `A` and `B`, functools picks `A` (first in
  `C.__mro__`), while mmth raises `TypeError("Ambiguous dispatch ...")`. The
  same applies to a real base class against an unrelated ABC that `C`
  implicitly satisfies. (Where functools does raise on ambiguity between
  ABCs, it raises `RuntimeError`; mmth raises `TypeError`.)
- **The default's annotations count**: functools ignores them and registers
  the default for `object`, so `@singledispatch def f(x: Dog)` followed by
  `f.register(Animal)` or `f.register(object)` works there; mmth raises
  `TypeError`, since only subclasses of `Dog` may be registered (see above).
- **`Any` means `object`**: functools treats it as a class that nothing is
  an instance of, so an implementation registered for `Any` never runs.
- **Looking a `dispatchmethod` up on the class**: `Class.method(obj, arg)`
  dispatches on `arg`, skipping `obj` as it would `self`, while functools
  dispatches on `obj`. So a `classmethod`/`staticmethod` implementation of an
  ordinary `dispatchmethod` can only be called through an instance; a
  `dispatchmethod` that is itself a `classmethod`/`staticmethod` works
  through either, as in functools.

## Examples

### Basic Usage

```python
@dispatch
def add(a: object, b: object) -> object:
    return a + b

@add.register(int, float)
def add_int_float(a: int, b: float) -> float:
    return float(a) + b

print(add(1, 2))     # 3 (int, int) -> default
print(add(1, 2.0))  # 3.0 (int, float) -> registered implementation
```

### Metaprogramming

```python
@dispatch
def process(data: object) -> str:
    return str(data).upper()

def json_handler(data: dict) -> str:
    import json
    return json.dumps(data)

# Register via assignment
process[dict] = json_handler

# Access an implementation
handler = process[dict]
print(handler({"key": "value"}))  # {"key": "value"}
```

### Inheritance Dispatch

```python
class Animal:
    pass

class Dog(Animal):
    pass

class Cat(Animal):
    pass

@dispatch
def make_sound(animal: Animal) -> str:
    return "..."

@make_sound.register(Dog)
def _(dog: Dog) -> str:
    return "Woof!"

@make_sound.register(Cat)
def _(cat: Cat) -> str:
    return "Meow!"

print(make_sound(Dog()))  # Woof!
print(make_sound(Cat()))  # Meow!
```

### Ambiguity Detection

```python
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

# ERROR: Ambiguous - neither is more specialized than the other
f(Dog(), Dog())
# TypeError: Ambiguous dispatch for types (Dog, Dog): matches multiple signatures
```

## Error Cases

```python
@dispatch
def foo(a: int) -> int:
    return a

# KeyError - no implementation registered for exactly these types
foo[float]  # KeyError: "No implementation registered for (<class 'float'>,)"

# TypeError - no matching implementation and no default to fall back to
bar = Multimethod()

@bar.register(int)
def _(a: int) -> int:
    return a * 2

bar("str")  # TypeError: "No matching implementation for types (<class 'str'>,)"
```

## Design Decisions

1. **Return type annotations**: Not used in dispatch matching
2. **Variadic arguments**: Not supported
3. **Keyword arguments**: Not used in dispatch (treated as fallback)
4. **Callable references**: Registration requires explicit callable object, not name matching
