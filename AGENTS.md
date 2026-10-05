# AGENTS.md

Guidelines for agents working in this repository.

---

## Project Overview

**mmth** is a simple multiple-dispatch library for Python, inspired by Julia's multiple dispatch. It allows defining functions with different implementations based on argument types.

- **Python**: >= 3.11
- **License**: MIT
- **Repository**: https://github.com/yourusername/mmth

---

## Commands

### Development Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/) and pinned in
`uv.lock` for reproducibility; `.python-version` pins the default
interpreter (3.12).

```bash
# Create .venv and install locked dev dependencies
uv sync --extra dev

# Run a command inside the environment
uv run pytest
```

After changing dependencies in `pyproject.toml`, run `uv lock` and commit
the updated `uv.lock`.

### Testing

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_mmth.py

# Run a single test function
pytest tests/test_mmth.py::test_basic_dispatch

# Run with verbose output
pytest -v

# Run with coverage (if installed)
pytest --cov=mmth --cov-report=term-missing
```

### Benchmarks

`tests/test_benchmarks.py` (via [pytest-benchmark](https://pytest-benchmark.readthedocs.io/))
measures performance, not correctness, so it's excluded from the default
`pytest`/`tox` run (`addopts = "-m 'not benchmark'"` in `pyproject.toml`):

```bash
pytest -m benchmark    # run only the benchmarks
tox -e benchmark       # same, in an isolated tox env
```

### Linting

```bash
# Run ruff linter
ruff check src/ tests/

# Auto-fix linting issues
ruff check --fix src/ tests/

# Format code
ruff format src/ tests/
```

### Type Checking

```bash
# Run mypy (if installed)
mypy src/

# Run pyright (if installed)
pyright src/
```

### CI (GitHub Actions)

CI (`.github/workflows/ci.yml`) runs tests on Python 3.11, 3.12, 3.13, 3.14,
and PyPy 3.11, plus a separate `ruff check` lint job. Each job installs uv,
has uv fetch the matrix interpreter (`uv python install ...`), and runs
tests through `tox` (`tox.ini`, using the `tox-uv` plugin) so the same
commands reproduce locally:

```bash
uv run tox            # test envs for every interpreter tox/uv can find or fetch, + lint
uv run tox -e py313    # test a single interpreter
uv run tox -e lint     # lint only
uv run tox -e benchmark  # performance benchmarks (not part of the default envlist)
```

---

## Code Style

### General

- **Line length**: 88 characters (follows ruff default)
- **Python version**: 3.11+
- **Encoding**: UTF-8

### Imports

- Use absolute imports: `from mmth import dispatch`
- Group imports in order: stdlib, third-party, local
- Do not use wildcard imports (`from mmth import *`)
- Do not use `from __future__ import annotations` in mmth's own code; use
  `typing.Self` for the enclosing class, or else quote forward references
  (`-> "Multimethod"`). mmth still supports it in user code.
- Sort imports with `ruff` (automatic)

```python
# Correct
import inspect
from typing import Any, Callable

from mmth import dispatch
from mmth.multimethod import Multimethod
```

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Modules | lowercase | `multimethod.py` |
| Classes | PascalCase | `class Multimethod` |
| Functions | snake_case | `def dispatch()` |
| Methods | snake_case | `def register()` |
| Private | leading underscore | `_registry` |
| Constants | UPPER_SNAKE | `MAX_SIZE` |

### Type Annotations

- Use type annotations for function signatures
- Use `Any` sparingly
- Prefer explicit types over type comments

```python
# Good
def add(a: int, b: int) -> int:
    return a + b

def process(data: dict[str, Any]) -> list[str]:
    ...

# Avoid
def add(a, b):  # No types
    return a + b
```

### Docstrings

- Public docstrings must follow [PEP 257](https://peps.python.org/pep-0257/),
  and private ones should. `ruff check` enforces its format on every
  docstring (`D` rules, `pep257` convention); tests are exempt from needing
  docstrings, not from their format.
- Include docstrings for public APIs: modules, classes, `__init__`, public
  and dunder methods, functions
- One-line summary in the imperative ("Return ...", not "Returns ..."),
  ending with a period; then a blank line before any further description,
  and closing quotes on their own line
- Google style (`Args:`, `Returns:`) for sections, which mkdocstrings
  renders; keep brief and descriptive

```python
def register(self, *types):
    """Register an implementation for the given types.

    Args:
        *types: Type signature to match against.

    Returns:
        A decorator that registers the function.
    """
    ...
```

### Comments

These apply to comments and to private docstrings (public docstrings are
the API reference, rendered by mkdocstrings):

- Keep them short: a line or two, rarely more.
- Explain *why*, never *how*: don't narrate what the code already says.
- Write for any reader of the code: no history (past bugs, earlier
  designs, benchmark numbers) that only the commit history explains.
- Don't repeat what's already in `docs/` or a commit message; point to the
  doc instead if needed (e.g. "see docs/performance.md").
- In tests, don't restate the assertions or the test name.

```python
# Good - a reason the reader would otherwise miss
# `__class__`, not `type()`, so proxies like `Mock(spec=cls)` dispatch as
# that class.

# Avoid - narrates the code
# 1. Exact match in registry
if arg_types in self._registry:
    ...
```

### Error Handling

- Use specific exceptions (`TypeError`, `KeyError`, `ValueError`)
- Provide clear error messages
- Avoid catching generic `Exception` unless necessary

```python
# Good
if not types:
    raise TypeError("register() requires at least one type argument")

if types not in self._registry:
    raise KeyError(f"No implementation registered for {types}")

# Avoid
if not types:
    raise Exception("error")  # Too generic
```

### Code Organization

- Private methods (starting with `_`) should be defined before public methods
- Group related functionality together
- Keep classes focused (single responsibility)
- Maximum ~170 lines per file (current convention)

### Conditionals and Flow

- Use early returns to avoid deep nesting
- Prefer clear boolean expressions over complex conditionals

```python
# Good - early return
def __call__(self, *args, **kwargs):
    if arg_types in self._registry:
        return self._registry[arg_types](*args, **kwargs)
    
    func = self._find_most_specialized(arg_types)
    if func is not None:
        return func(*args, **kwargs)
    
    raise TypeError(f"No matching implementation for types {arg_types}")
```

---

## Testing Guidelines

- All new functionality must have tests
- Test behaviour, not declarations: don't write tests that just restate the
  code (e.g. `issubclass(NoMatchError, TypeError)` for an exception class)
- Tests should be in `tests/test_*.py`
- **Do not use test classes** - use standalone functions
- Never import from a test file (`test_*.py`); helpers or Hypothesis
  strategies used by more than one test module go in a separate file, e.g.
  `tests/strategies.py`
- Test names should be descriptive: `test_feature_name`
- Use assertions with clear failure messages

```python
def test_ambiguity_detection():
    """Multiple equally specialized signatures should raise TypeError."""
    @dispatch
    def f(a: Animal, b: Animal) -> str:
        return "Animal, Animal"
    
    @f.register(Dog, Animal)
    def _(d: Dog, a: Animal) -> str:
        return "Dog, Animal"
    
    @f.register(Animal, Dog)
    def _(a: Animal, d: Dog) -> str:
        return "Animal, Dog"
    
    with pytest.raises(AmbiguousMatchError) as exc_info:
        f(Dog(), Dog())
    
    assert "Ambiguous lookup" in str(exc_info.value)
```

---

## Commit Messages

- Use imperative mood: "Add feature" not "Added feature"
- First line: ~50 characters
- Body: wrapped at 72 characters
- Reference issues when applicable

```
Add __getitem__ for accessing specializations

Enables func[Type] syntax to retrieve registered implementations.
Fixes #10.
```

---

## File Structure

```
mmth/
├── .github/workflows/
│   └── ci.yml            # GitHub Actions CI
├── src/mmth/
│   ├── __init__.py       # Public API exports
│   ├── multimethod.py    # Core implementation (dispatch, Multimethod, dispatchmethod)
│   └── typemap.py        # TypeMap/ChainTypeMap: signature table, lookup, cache
├── tests/
│   ├── test_mmth.py      # dispatch/Multimethod test suite
│   ├── test_method.py    # dispatchmethod test suite
│   ├── test_typemap.py   # TypeMap test suite
│   ├── test_abc.py       # dispatch with real/virtual/structural ABC subclasses
│   ├── strategies.py     # Hypothesis strategies shared by test modules
│   ├── test_hypothesis.py # property-based specialization tests
│   ├── test_functools_compat.py # single dispatch vs functools.singledispatch
│   └── test_benchmarks.py # pytest-benchmark performance benchmarks (excluded by default)
├── pyproject.toml        # Project config
├── uv.lock               # Locked dependency versions (uv)
├── .python-version       # Default interpreter pin (uv)
├── tox.ini               # Test/lint envs (used locally and in CI)
├── docs/                 # MkDocs sources (spec, methods, performance, API reference, development)
├── mkdocs.yml            # MkDocs Material + mkdocstrings config
├── .readthedocs.yaml     # Read the Docs build config
├── README.md             # Landing page; links to the hosted docs
└── AGENTS.md              # This file
```

---

## Key Patterns

### Multiple Dispatch

```python
@dispatch
def add(a: object, b: object) -> object:
    """Default implementation."""
    return a + b

@add.register(int, float)
def add_int_float(a: int, b: float) -> float:
    """Specialized for int + float."""
    return float(a) + b

@add.register  # types from annotations (all required, unlike @dispatch)
def add_float_int(a: float, b: int) -> float:
    return a + float(b)

# Access an implementation
impl = add[int, float]

# Metaprogramming
add[str, str] = lambda a, b: f"{a}{b}"
```

### Dispatch Algorithm

1. Exact match in registry
2. Inheritance-based match (most specific wins)
3. Default fallback
4. Error if no match and no default (bare `Multimethod()`)

Each `Multimethod` keeps its implementations in a `TypeMap` (a mutable
mapping by exact signature) whose `lookup()` does the lookup above and
memoizes a successful resolution by argument types, invalidated on any
change (cascading to `inherit()` descendants, whose `ChainTypeMap`
looks among `parent | child`) - see docs/performance.md.

The default is registered for `object` at every parameter, ignoring its
annotations, as in `functools.singledispatch`. With one dispatched argument, behaviour matches
`functools.singledispatch`/`singledispatchmethod` except where
docs/specification.md ("Differences from `functools.singledispatch`") says
otherwise; `tests/test_functools_compat.py` checks this against functools
itself, so keep it in sync with any new single-dispatch behaviour.

### Method Dispatch

`dispatchmethod` is `dispatch` for use on a method: `self` is bound
automatically via the descriptor protocol and excluded from dispatch, so
`.register(*types)` only needs the types of the remaining arguments. A
subclass replaces one implementation for itself via `inherit()` (a
separate multimethod dispatching on `base | subclass` registrations,
so the most specific signature still wins across both) rather than
`.register()` on the shared table; `inherit()`
finds the base multimethod itself via `__set_name__` (same lookup
`super()` would do), or use `Base.visit.inherit()` directly when that
auto-lookup isn't what you want. See docs/methods.md ("Method Dispatch"
and "Overriding One Implementation in a Subclass") for the full examples,
including using `dispatchmethod` to replace the Visitor pattern
(dispatching straight on a node's type instead of an
`accept()`/`visit_ElementType()` callback pair).

```python
class Evaluator:
    @dispatchmethod
    def visit(self, node: Expr):
        raise TypeError(f"no visit for {type(node).__name__}")

    @visit.register(Num)
    def _(self, node):
        return node.value
```
