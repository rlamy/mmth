import itertools

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from mmth import Multimethod


@st.composite
def _multi_inheritance_dag(draw, max_size=10, max_parents=3):
    """Generate a class hierarchy as a DAG.

    Each class after the first gets 1..max_parents unrelated direct parents
    among the earlier ones (so `max_parents=1` gives a tree). Returns the
    classes and each one's ancestor indices, used as an oracle independent
    of `issubclass`.

    Parents are ordered by their position in the MRO of a "checkpoint"
    class inheriting from every class so far, since a fixed order often
    yields bases with no consistent MRO; the rare remaining failures are
    discarded.
    """
    n = draw(st.integers(min_value=1, max_value=max_size))

    classes = [type("Node0", (object,), {})]
    checkpoint = classes[0]
    ancestors: list[frozenset] = [frozenset({0})]

    for i in range(1, n):
        position = {cls: idx for idx, cls in enumerate(checkpoint.__mro__)}

        k = draw(st.integers(min_value=1, max_value=min(max_parents, i)))
        candidates = draw(
            st.lists(
                st.integers(min_value=0, max_value=i - 1),
                min_size=1,
                max_size=k,
                unique=True,
            )
        )
        parents: list[int] = []
        for c in candidates:
            if all(c not in ancestors[p] and p not in ancestors[c] for p in parents):
                parents.append(c)
        # order by position in the checkpoint's real MRO; nodes it hasn't
        # caught up to yet (see above) fall back to construction order
        parents.sort(key=lambda idx: position.get(classes[idx], -idx))

        bases = tuple(classes[p] for p in parents)
        try:
            new_cls = type(f"Node{i}", bases, {})
        except TypeError:
            assume(False)  # see docstring: rare, and not worth chasing further
        classes.append(new_cls)
        ancestors.append(frozenset({i}).union(*(ancestors[p] for p in parents)))

        try:
            checkpoint = type(f"Checkpoint{i}", (new_cls, checkpoint), {})
        except TypeError:
            pass  # keep the previous checkpoint; it's still valid, just stale

    return classes, ancestors


def _with_registered_subset(dag):
    """Add nodes to register to a `_multi_inheritance_dag()` result.

    A random subset, always including the root.
    """
    classes, ancestors = dag
    return st.sets(st.integers(min_value=0, max_value=len(classes) - 1)).map(
        lambda registered: (classes, ancestors, registered | {0})
    )


def _maximal_registered_ancestors(node, registered, ancestors):
    """Return the registered ancestors of `node` that nothing else beats.

    Computed from the ancestor sets rather than `issubclass`.
    """
    matching = [r for r in registered if r in ancestors[node]]
    return [
        r for r in matching if not any(r2 != r and r in ancestors[r2] for r2 in matching)
    ]


@given(_multi_inheritance_dag().flatmap(_with_registered_subset), st.booleans())
def test_dispatch_handles_multiple_inheritance(data, reverse_registration_order):
    classes, ancestors, registered = data
    mm = Multimethod()

    # registration order mustn't affect the result
    for i in sorted(registered, reverse=reverse_registration_order):
        mm.register(classes[i])(lambda obj, i=i: i)

    for node in range(len(classes)):
        maximal = _maximal_registered_ancestors(node, registered, ancestors)
        instance = classes[node]()

        if len(maximal) == 1:
            assert mm(instance) == maximal[0]
        else:
            assert len(maximal) > 1
            with pytest.raises(TypeError, match="Ambiguous dispatch"):
                mm(instance)


@st.composite
def _multi_arg_dags(draw, min_arity=2, max_arity=3, max_size=6, max_parents=3):
    """Generate one `_multi_inheritance_dag()` per argument position.

    Plus a random subset of signatures to register, always including the
    all-roots one.
    """
    arity = draw(st.integers(min_value=min_arity, max_value=max_arity))
    dags = [
        draw(_multi_inheritance_dag(max_size=max_size, max_parents=max_parents))
        for _ in range(arity)
    ]
    class_lists = [classes for classes, _ancestors in dags]
    ancestors_lists = [ancestors for _classes, ancestors in dags]

    sizes = [len(cl) for cl in class_lists]
    registered = draw(
        st.sets(st.tuples(*(st.integers(min_value=0, max_value=s - 1) for s in sizes)))
    )
    registered.add(tuple(0 for _ in range(arity)))

    return class_lists, ancestors_lists, registered


def _dominates(sig_a, sig_b, ancestors_lists):
    """`Multimethod._is_more_specialized`, from the ancestor sets."""
    more_specific = False
    for a, b, ancestors in zip(sig_a, sig_b, ancestors_lists):
        if b in ancestors[a]:
            if a not in ancestors[b]:
                more_specific = True
        else:
            return False
    return more_specific


def _maximal_registered_signatures(query, registered, ancestors_lists):
    """Return `_maximal_registered_ancestors`, for several arguments."""
    matching = [
        sig
        for sig in registered
        if all(sig[p] in ancestors_lists[p][query[p]] for p in range(len(query)))
    ]
    return [
        sig
        for sig in matching
        if not any(
            other != sig and _dominates(other, sig, ancestors_lists) for other in matching
        )
    ]


@given(_multi_arg_dags(), st.booleans())
def test_multi_arg_dispatch_handles_ambiguity(data, reverse_registration_order):
    class_lists, ancestors_lists, registered = data
    arity = len(class_lists)
    mm = Multimethod()

    for sig in sorted(registered, reverse=reverse_registration_order):
        types = tuple(class_lists[p][sig[p]] for p in range(arity))
        mm.register(*types)(lambda *args, sig=sig: sig)

    sizes = [len(cl) for cl in class_lists]
    for query in itertools.product(*(range(s) for s in sizes)):
        maximal = _maximal_registered_signatures(query, registered, ancestors_lists)
        instances = [class_lists[p][query[p]]() for p in range(arity)]

        if len(maximal) == 1:
            assert mm(*instances) == maximal[0]
        else:
            assert len(maximal) > 1
            with pytest.raises(TypeError, match="Ambiguous dispatch"):
                mm(*instances)
