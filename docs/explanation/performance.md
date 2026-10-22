# Performance

## Resolution caching

Resolving a call's implementation (matching runtime types against the
registry, merged with those along `inherit()`'s parent chain)
only depends on the argument types, so each `Multimethod`'s `TypeMap`
memoizes a successful resolution by argument types; any change to the
registry (`register()`, `__setitem__()`, deleting from the `TypeMap`)
clears the cache, cascading to every `inherit()`-chained descendant
(whose lookups include its keys). Failed resolutions (ambiguous / no match)
aren't cached. This makes repeat calls with the same concrete types - the
common case - essentially free after the first one, regardless of registry
size or `inherit()` chain depth; see
[Development](../development.md#running-benchmarks) to measure it.

Registering an ABC is the one case where the cache can go stale without a
`register()` call: `SomeABC.register(cls)` changes what `issubclass`
answers. So a multimethod with an ABC in its registry (or its `inherit()`
parent's) records `abc.get_cache_token()` and clears its cache whenever the
token has changed since.

The cache holds the argument classes it has seen by strong reference, so a
class a multimethod has been called with stays alive until that
multimethod's registry (or its `inherit()` parent's) next changes, or the
multimethod itself goes. Holding them weakly would avoid that, but a weak
reference costs a call on every lookup: about 10% of a cached call. That
matters only for programs that create classes dynamically and dispatch on
them.

## Fast paths

Once resolution itself is cached, building the cache key becomes the
dominant remaining cost: a generator expression to compute `arg_types` from
`*args` (needed in general, since a signature can have any arity) costs far
more than the single `__class__` lookup the overwhelmingly common one-dispatched-
argument case actually needs - true of essentially every `dispatchmethod`
call (`self` is skipped) and most `dispatch` functions. `__call__`
fast-paths that case, halving the cost of a call on CPython (and more on
PyPy). It also builds a two-type key directly, which costs about 40% less
than the generator expression for a two-argument call; three or more
arguments take the general path.

`dispatch(*types)` shares the call's cache, but reading `types` as type
annotations (unions, `Optional`, `Annotated`, ...) costs several times a
cached call. Given only plain classes, as when an implementation falls back
on a more general one with `f.dispatch(Base)(...)`, it skips that and goes
straight to the cache, costing about two calls.

## Instance layout

`Multimethod` and `TypeMap` keep every attribute a call touches in
`__slots__`.
`functools.update_wrapper` accesses the instance's `__dict__` (to copy the
default's own `__dict__`), and on CPython 3.11, 3.12 and 3.14 that moves an
ordinary instance's attributes out of the fast inline layout that attribute
lookups specialize for, costing 20-30% of a plain `dispatch` call. CPython
3.13 keeps them inline anyway, so there slots don't help, and cost 3-5%: a
method lookup on an instance whose `__dict__` slot is in use doesn't
specialize. Slots make no difference on PyPy.
