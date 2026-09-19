# Performance: Resolution Caching

Resolving a call's implementation (matching runtime types against the
registry, and - on a miss - falling through `override()`'s parent chain)
only depends on the argument types, so each `Multimethod` memoizes a
successful resolution by argument types; a `register()`/`__setitem__()`
call clears the cache, cascading to every `override()`-chained descendant
(which can fall through to it). Failed resolutions (ambiguous / no match)
aren't cached. This makes repeat calls with the same concrete types - the
common case - essentially free after the first one, regardless of registry
size or `override()` chain depth; see `tests/test_benchmarks.py`.

Once resolution itself was cached, building the cache key became the
dominant remaining cost: a generator expression to compute `arg_types` from
`*args` (needed in general, since a signature can have any arity) costs far
more than the single `type()` call the overwhelmingly common one-dispatched-
argument case actually needs - true of essentially every `dispatchmethod`
call (`self` is skipped) and most `dispatch` functions. `__call__`
fast-paths that case, which closes almost the entire remaining gap to
`functools.singledispatch` (itself fixed at exactly one dispatch argument,
so it never pays this cost at all).

## Benchmarks

`tests/test_benchmarks.py` measures dispatch performance (via
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/)) rather than
correctness, so it's excluded from the default test run (`addopts` in
`pyproject.toml`) and from `tox`'s default envlist. Run it explicitly:

```bash
uv run pytest -m benchmark          # via the dev venv directly
uv run tox -e benchmark             # via tox, in an isolated env
```
