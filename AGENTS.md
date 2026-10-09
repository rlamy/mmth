# AGENTS.md

Guidelines for agents working in this repository. User-facing behaviour is
documented in `docs/` (MkDocs); this file covers only what isn't there:
conventions, internals, and what to keep in sync.

**mmth** is a multiple-dispatch library for Python (>= 3.11, MIT),
inspired by Julia: https://github.com/rlamy/mmth

---

## Commands

Setup, CI and the docs build are described in `docs/development.md`
(uv, `uv.lock`, tox with `tox-uv`). Quick reference:

```bash
uv sync --extra dev            # locked dev environment (add --extra docs for mkdocs)
uv run pytest                  # tests (benchmarks excluded by default)
uv run pytest tests/test_mmth.py::test_basic_dispatch
uv run pytest -m benchmark     # benchmarks only, see docs/performance.md
ruff check src/ tests/         # lint, including docstring format
ruff format src/ tests/
mypy src/ && pyright src/
mypy --strict tests/typing && pyright -p tests/typing

uv run tox                     # everything CI runs: every interpreter + lint, typing, docs
uv run tox -e py313            # one interpreter (py311-py314, pypy311)
uv run tox -e lint             # or: typing, docs, benchmark
```

After changing dependencies in `pyproject.toml`, run `uv lock` and commit
`uv.lock`.

---

## Code Style

`ruff check` enforces the line length (88), import sorting, PEP 8 naming
and the docstring format (`pyproject.toml`). Beyond that:

### Imports and annotations

- Absolute imports only, no wildcard imports.
- Do not use `from __future__ import annotations` in mmth's own code; use
  `typing.Self` for the enclosing class, or else quote forward references
  (`-> "Multimethod"`). mmth still supports it in user code.
- Annotate function signatures; use `Any` sparingly.

### Docstrings

- Public docstrings must follow [PEP 257](https://peps.python.org/pep-0257/),
  and private ones should; ruff checks the format of all of them (tests
  are exempt from needing one, not from the format).
- Document public APIs: modules, classes, `__init__`, public and dunder
  methods, functions. They're the API reference, rendered by mkdocstrings.
- One-line summary in the imperative ("Return ...", not "Returns ...").
- Google style (`Args:`, `Returns:`) for sections; keep them brief.

```python
def register(self, *types):
    """Register an implementation for the given types.

    Args:
        *types: Type signature to match against.

    Returns:
        A decorator that registers the function.
    """
```

### Comments

These apply to comments and to private docstrings:

- Keep them short: a line or two, rarely more.
- Explain *why*, never *how*: don't narrate what the code already says.
- Write for any reader of the code: no history (past bugs, earlier
  designs, benchmark numbers) that only the commit history explains.
- Don't repeat what's already in `docs/` or a commit message; point to the
  doc instead if needed (e.g. "see docs/performance.md").
- In tests, don't restate the assertions or the test name.

```python
# Good - a reason the reader would otherwise miss
# Not a running "best so far": a later candidate can dominate two
# earlier, mutually incomparable ones.

# Avoid - narrates the code
# Return the exact match if there is one
if types in table:
    return table[types]
```

### Errors

- Raise specific built-in exceptions (`TypeError`, `ValueError`,
  `KeyError`) with a message that says what was wrong and what was
  received; don't catch generic `Exception`.
- Failed lookups raise `NoMatchError` / `AmbiguousMatchError` (both
  `TypeError` subclasses) carrying `types` (and `candidates`). `TypeMap`
  words them in terms of keys; `Multimethod._lookup_error()` restates them
  in terms of the call. Keep that split when adding lookup errors.

```python
raise TypeError(f"register() expected a function, got {func!r}")
```

### Code organization

- Define private methods (`_name`) before public ones.
- Use early returns rather than deep nesting.

---

## Testing Guidelines

- All new functionality must have tests, in `tests/test_*.py`.
- Test behaviour, not declarations: don't write tests that just restate the
  code (e.g. `issubclass(NoMatchError, TypeError)` for an exception class).
- **Do not use test classes** - use standalone functions with descriptive
  names.
- Never import from a test file (`test_*.py`); helpers or Hypothesis
  strategies used by more than one test module go in a separate file, e.g.
  `tests/strategies.py`.

```python
def test_ambiguity_detection():
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

    with pytest.raises(AmbiguousMatchError) as exc_info:
        f(Dog(), Dog())
    assert "is ambiguous between" in str(exc_info.value)
```

---

## Commit Messages

- Imperative mood: "Add feature", not "Added feature".
- First line ~50 characters; body wrapped at 72.
- Reference issues when there is one.

```
Allow passing dispatched arguments by keyword
```

---

## File Structure

```
mmth/
├── .github/workflows/ci.yml  # CI: runs tox (tests per interpreter, lint, typing, docs)
├── src/mmth/
│   ├── __init__.py       # Public API exports
│   ├── multimethod.py    # dispatch, dispatchmethod, inherit, Multimethod
│   └── typemap.py        # TypeMap/ChainTypeMap (table, lookup, cache), lookup errors
├── tests/
│   ├── test_mmth.py      # dispatch/Multimethod
│   ├── test_method.py    # dispatchmethod, inherit
│   ├── test_typemap.py   # TypeMap/ChainTypeMap
│   ├── test_abc.py       # real/virtual/structural ABC subclasses
│   ├── test_hypothesis.py # property-based specialization tests
│   ├── strategies.py     # Hypothesis strategies shared by test modules
│   ├── test_functools_compat.py # single dispatch vs functools.singledispatch
│   ├── test_benchmarks.py # pytest-benchmark (excluded by default)
│   └── typing/           # type-checked only (mypy, pyright): how user code is typed
├── docs/                 # MkDocs: specification, methods, typing, performance, reference, development
├── pyproject.toml, uv.lock, .python-version, tox.ini
├── mkdocs.yml, .readthedocs.yaml
└── README.md             # Landing page; links to the hosted docs
```

---

## Internals and What to Keep in Sync

User-facing semantics are in `docs/specification.md` (syntax, dispatch
algorithm, errors), `docs/methods.md` (`dispatchmethod`, `inherit()`) and
`docs/typing.md`. Implementation notes:

- **Table and lookup:** each `Multimethod` keeps its implementations in a
  `TypeMap` (a mutable mapping by exact signature) whose `lookup()` finds
  the exact or most specific match and memoizes it by argument types,
  invalidated on any change. That cascades to `inherit()` descendants,
  whose `ChainTypeMap` looks among `parent | child`. See
  docs/performance.md.
- **Default and arity:** the default is registered for `object` at every
  required positional parameter, ignoring its annotations, as in
  `functools.singledispatch`; it's an ordinary table entry. That count is
  the arity: calls dispatch on their first `arity` positional arguments
  and pass any others on (`*args` defaults need an explicit
  `@dispatch(arity=n)`).
- **Methods:** `dispatchmethod` binds `self` via the descriptor protocol
  and excludes it from dispatch. `inherit()` finds the base multimethod
  via `__set_name__`.
- **functools compatibility:** with one dispatched argument, behaviour
  matches `functools.singledispatch`/`singledispatchmethod` except where
  docs/specification.md ("Differences from `functools.singledispatch`")
  says otherwise. `tests/test_functools_compat.py` checks this against
  functools itself; keep it in sync with any new single-dispatch behaviour.
- **Static typing:** `Multimethod[P, R]` is generic over the default's
  signature, so calls are checked against it, and implementations must
  return `R`. `dispatchmethod` is typed as `_Method` (type checkers only)
  to bind `self`. With explicit types, `register(T1, T2)` returns
  `_Register` (also type checkers only), which checks that both the
  implementation and the default accept those types. `tests/typing/` covers
  this; keep it and docs/typing.md in sync with any change to the public
  signatures.
