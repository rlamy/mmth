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

- Use Google-style or NumPy-style docstrings
- Include docstrings for public APIs
- Keep brief and descriptive

```python
def register(self, *types):
    """Register a specialized implementation for the given types.
    
    Args:
        *types: Type signature to match against.
    
    Returns:
        A decorator that registers the function.
    """
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
    raise KeyError(f"No specialization registered for {types}")

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
    
    raise TypeError(f"No matching variant for {arg_types}")
```

---

## Testing Guidelines

- All new functionality must have tests
- Tests should be in `tests/test_*.py`
- **Do not use test classes** - use standalone functions
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
    
    with pytest.raises(TypeError) as exc_info:
        f(Dog(), Dog())
    
    assert "Ambiguous dispatch" in str(exc_info.value)
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
│   └── multimethod.py    # Core implementation (dispatch, Multimethod, dispatchmethod)
├── tests/
│   ├── test_mmth.py      # dispatch/Multimethod test suite
│   └── test_method.py    # dispatchmethod test suite
├── pyproject.toml        # Project config
├── uv.lock               # Locked dependency versions (uv)
├── .python-version       # Default interpreter pin (uv)
├── tox.ini               # Test/lint envs (used locally and in CI)
├── README.md             # Documentation
└── AGENTS.md              # This file
```

---

## Key Patterns

### Multiple Dispatch

```python
@dispatch
def add(a: int, b: int) -> int:
    """Default implementation."""
    return a + b

@add.register(int, float)
def add_int_float(a: int, b: float) -> float:
    """Specialized for int + float."""
    return float(a) + b

# Access specialization
impl = add[int, float]

# Metaprogramming
add[str, str] = lambda a, b: f"{a}{b}"
```

### Dispatch Algorithm

1. Exact match in registry
2. Inheritance-based match (most specific wins)
3. Default fallback
4. Error if no match and variants exist

### Method Dispatch

`dispatchmethod` is `dispatch` for use on a method: `self` is bound
automatically via the descriptor protocol and excluded from dispatch, so
`.register(*types)` only needs the types of the remaining arguments. A
subclass narrows one case for itself via `override()` (chains to a
separate multimethod, tried first, so the subclass always wins regardless
of relative type specificity - unlike standard multiple dispatch) rather
than `.register()` on the shared table; `override()` finds the base
multimethod itself via `__set_name__` (same lookup `super()` would do), or
use `Base.visit.override()` directly when that auto-lookup isn't what you
want. See README.md's "Method Dispatch" and "Overriding One Case in a
Subclass" sections for the full examples, including using `dispatchmethod`
to replace the Visitor pattern (dispatching straight on a node's type
instead of an `accept()`/`visit_ElementType()` callback pair).

```python
class Evaluator:
    @dispatchmethod
    def visit(self, node: Expr):
        raise TypeError(f"no visit for {type(node).__name__}")

    @visit.register(Num)
    def _(self, node):
        return node.value
```
