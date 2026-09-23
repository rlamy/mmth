# Performance: Resolution Caching

Resolving a call's implementation (matching runtime types against the
registry, and - on a miss - falling through `inherit()`'s parent chain)
only depends on the argument types, so each `Multimethod` memoizes a
successful resolution by argument types; a `register()`/`__setitem__()`
call clears the cache, cascading to every `inherit()`-chained descendant
(which can fall through to it). Failed resolutions (ambiguous / no match)
aren't cached. This makes repeat calls with the same concrete types - the
common case - essentially free after the first one, regardless of registry
size or `inherit()` chain depth; see `tests/test_benchmarks.py`.

Registering an ABC is the one case where the cache can go stale without a
`register()` call: `SomeABC.register(cls)` changes what `issubclass`
answers. As in `functools.singledispatch`, a multimethod with an ABC in its
registry (or its `inherit()` parent's) records `abc.get_cache_token()` and
clears its cache whenever the token has changed since.

Once resolution itself was cached, building the cache key became the
dominant remaining cost: a generator expression to compute `arg_types` from
`*args` (needed in general, since a signature can have any arity) costs far
more than the single `__class__` lookup the overwhelmingly common one-dispatched-
argument case actually needs - true of essentially every `dispatchmethod`
call (`self` is skipped) and most `dispatch` functions. `__call__`
fast-paths that case, which closes almost the entire remaining gap to
`functools.singledispatch` (itself fixed at exactly one dispatch argument,
so it never pays this cost at all).

`Multimethod` keeps every attribute a call touches in `__slots__`. Copying
the default's `__name__`, `__doc__`, etc. onto the instance (as
`functools.update_wrapper` does) otherwise stops instances sharing their
dict's keys, which slows every attribute lookup a call makes - measured at
~25% of a plain `dispatch` call.

## Benchmarks

`tests/test_benchmarks.py` measures dispatch performance (via
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/)) rather than
correctness, so it's excluded from the default test run (`addopts` in
`pyproject.toml`) and from `tox`'s default envlist. Run it explicitly:

```bash
uv run pytest -m benchmark          # via the dev venv directly
uv run tox -e benchmark             # via tox, in an isolated env
```
