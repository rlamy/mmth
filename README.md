# mmth

A simple multiple-dispatch library for Python, inspired by Julia's multiple dispatch.

## Installation

```bash
pip install mmth
```

## Specification

### Syntax

#### 1. Define Multimethod (Main Syntax)

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

### Method Dispatch

`dispatchmethod` is `dispatch` for use on a method: `self` is bound
automatically via the descriptor protocol and excluded from dispatch, so
`.register(*types)` only needs the types of the remaining arguments.

```python
from mmth import dispatchmethod

class Formatter:
    def __init__(self, indent):
        self.indent = indent

    @dispatchmethod
    def render(self, value: object) -> str:
        return repr(value)

    @render.register(str)
    def _(self, value):
        return " " * self.indent + value

    @render.register(list)
    def _(self, value):
        return "\n".join(self.render(item) for item in value)

Formatter(indent=2).render(["a", "b"])  # "  a\n  b"
```

Each instance keeps its own state (`self.indent` above), while the
implementation for a given call is still chosen by the runtime type of the
arguments, exactly like `dispatch`.

One direct application is replacing the Visitor pattern: instead of an
`accept()` method on every visited class calling back into
`visitor.visit_ElementType(...)`, a `dispatchmethod` dispatches straight on
the argument's type, so the visited classes need no changes at all:

```python
class Expr:
    pass

class Num(Expr):
    def __init__(self, value):
        self.value = value

class Add(Expr):
    def __init__(self, left, right):
        self.left = left
        self.right = right

class Evaluator:
    @dispatchmethod
    def visit(self, node: Expr):
        raise TypeError(f"no visit for {type(node).__name__}")

    @visit.register(Num)
    def _(self, node):
        return node.value

    @visit.register(Add)
    def _(self, node):
        return self.visit(node.left) + self.visit(node.right)

Evaluator().visit(Add(Num(1), Num(2)))  # 3
```

### Overriding One Case in a Subclass

Subclassing a `dispatchmethod` isn't standard multiple dispatch: a subclass
overriding one case should win *regardless* of how its registered type
compares in specificity to what the base class registered - exactly like a
plain method override, which doesn't care what a sibling method does.
Comparing `self`'s type against the other arguments as peers (as `dispatch`
does for genuine multi-argument dispatch) gets this wrong: if a subclass
registers a *broader* type than the base class did, "most specific match
wins" has no clear answer and either picks the wrong one or raises
"ambiguous dispatch". `override()` avoids this entirely, by not comparing
the two at all: assign it as the subclass's own attribute (under the same
name the base class uses), then build it up with `.register(*types)`
exactly like `dispatchmethod` itself. The subclass's own multimethod is
always tried first, in full, before ever falling through to the base one:

```python
from mmth import override

class StrictEvaluator(Evaluator):
    visit = override()

    @visit.register(Num)
    def _(self, node):
        if node.value < 0:
            raise ValueError("negative numbers not allowed")
        return super().visit(node)

Evaluator().visit(Num(-1))         # -1, unaffected
StrictEvaluator().visit(Num(-1))   # ValueError: negative numbers not allowed
```

`override()` finds the base multimethod itself - the same lookup `super()`
would do, walking `StrictEvaluator`'s bases for a `visit` of their own -
once Python calls `__set_name__` on it at class-creation time. `super()`
works normally inside the registered function, because it's still an
ordinary method of `StrictEvaluator`; `override()` only changes which
multimethod `.register()` adds it to. Every other `Evaluator` subclass, and
every other node type on `StrictEvaluator`, keeps using the base
registrations unchanged.

If the attribute name differs from the base's, or the multimethod to chain
to isn't the one plain attribute lookup would find, spell it out instead
with `Base.visit.override()` (see `Multimethod.override`) - `override()` is
just that, with the base found automatically for the common case.

(On Python 3.11, an error raised while resolving `override()` - e.g. no
base class actually defines that name - arrives wrapped in a
`RuntimeError` with the original exception as its `__cause__`, rather than
directly; this is a difference in how CPython itself handles `__set_name__`
failures across versions, not something mmth controls.)

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

### Benchmarks

`tests/test_benchmarks.py` measures dispatch performance (via
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/)) rather than
correctness, so it's excluded from the default test run (`addopts` in
`pyproject.toml`) and from `tox`'s default envlist. Run it explicitly:

```bash
uv run pytest -m benchmark          # via the dev venv directly
uv run tox -e benchmark             # via tox, in an isolated env
```
