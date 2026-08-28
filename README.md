# mmth

A simple multiple-dispatch library for Python, inspired by Julia's multiple dispatch.

## Installation

```bash
pip install mmth
```

## Specification

### Syntax

#### 1. Define Dispatcher (Main Syntax)

```python
@dispatch
def function_name(arg1: Type1, arg2: Type2, ...) -> ReturnType:
    """Default implementation"""
    ...
```

#### 2. Register Specialization (Main Syntax)

```python
@function_name.register(Type1, Type2, ...)
def function_name_impl(arg1: Type1, arg2: Type2, ...) -> ReturnType:
    """Specialized implementation"""
    ...
```

#### 3. Register Specialization (Metaprogramming)

```python
# Direct assignment
function_name[Type1, Type2] = implementation_callable

# Or with a function definition
def custom_impl(arg1: Type1, arg2: Type2) -> ReturnType:
    ...

function_name[Type1, Type2] = custom_impl
```

#### 4. Access Specialization

```python
impl = function_name[Type1, Type2]  # Returns registered callable or raises KeyError
```

---

### Semantics

#### Dispatch Algorithm

When `function_name(arg1, arg2, ...)` is called:

1. **Collect runtime types**: `(type(arg1), type(arg2), ...)`

2. **Exact match**: If `(Type1, Type2, ...)` exists in registry, call that implementation

3. **Find all applicable signatures**: All registered signatures where each runtime type is a subclass of the registered type

4. **Select most specialized**:
   - A signature A is **more specialized** than B if all its type parameters are subclasses of B's corresponding parameters
   - If neither A nor B is more specialized than the other → **ambiguity error**
   - If A beats B but not vice versa → A wins
   - Exact match beats inheritance match

5. **Fallback**:
   - If variants exist but none match → raise `TypeError`
   - If no variants exist → call default implementation
   - If no default exists → raise `TypeError`

#### Registration Methods

| Method | Syntax | Returns |
|--------|--------|---------|
| `.register(*types)` | `@func.register(int, str)` | Decorator |
| `__setitem__` | `func[int, str] = impl` | `None` |
| `__getitem__` | `impl = func[int, str]` | Registered callable or raises `KeyError` |

#### Type Matching Rules

- **Exact types**: `int` matches `int` only
- **Subclass types**: `Animal` matches `Dog` if `Dog` is subclass of `Animal`
- **Single type shorthand**: `func[int]` is equivalent to `func[(int,)]`

---

### Examples

#### Basic Usage

```python
@dispatch
def add(a: int, b: int) -> int:
    return a + b

@add.register(int, float)
def add_int_float(a: int, b: float) -> float:
    return float(a) + b

print(add(1, 2))     # 3 (int, int) -> default
print(add(1, 2.0))  # 3.0 (int, float) -> specialized
```

#### Metaprogramming

```python
@dispatch
def process(data: str) -> str:
    return data.upper()

def json_handler(data: dict) -> str:
    import json
    return json.dumps(data)

# Register via assignment
process[dict] = json_handler

# Access specialization
handler = process[dict]
print(handler({"key": "value"}))  # {"key": "value"}
```

#### Inheritance Dispatch

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

#### Ambiguity Detection

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

---

### Error Cases

```python
@dispatch
def foo(a: int) -> int:
    return a

# KeyError - specialization not registered
foo[float]  # KeyError: "No specialization registered for (<class 'float'>,)"

# TypeError - no matching variant and variants exist
@foo.register(int)
def _(a: int) -> int:
    return a * 2

foo("str")  # TypeError: "No matching variant for types (<class 'str'>,)"
```

---

### Design Decisions

1. **Return type annotations**: Not used in dispatch matching
2. **Variadic arguments**: Not supported
3. **Keyword arguments**: Not used in dispatch (treated as fallback)
4. **Callable references**: Registration requires explicit callable object, not name matching

---

## Development

Dev environments are managed with [uv](https://docs.astral.sh/uv/) for
reproducibility: `uv.lock` pins the exact version of every dependency, and
`.python-version` pins the interpreter used by default.

```bash
uv sync --extra dev   # creates .venv, installs locked deps
uv run pytest
```

`uv sync` reads `uv.lock`, so everyone (and CI) gets identical dependency
versions. Re-run `uv lock` and commit the updated `uv.lock` whenever
`pyproject.toml`'s dependencies change.

### Running CI checks locally

CI runs the test suite on Python 3.11-3.14 and PyPy 3.11, plus a lint job,
via [tox](https://tox.wiki) (using the [tox-uv](https://github.com/tox-dev/tox-uv)
plugin, so tox itself uses uv to create envs and can fetch missing
interpreters). To run the exact same checks locally:

```bash
uv run tox            # test envs for every interpreter tox/uv can find or fetch, + lint
uv run tox -e py312   # test a single interpreter
uv run tox -e lint    # lint only
```

To test against a specific interpreter that isn't already on your machine,
have uv fetch it first, e.g. `uv python install 3.14` or
`uv python install pypy3.11`.
