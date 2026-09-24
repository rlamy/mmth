"""Hypothesis strategies shared by several test modules."""

from hypothesis import assume
from hypothesis import strategies as st


@st.composite
def multi_inheritance_dag(draw, max_size=10, max_parents=3):
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


def with_registered_subset(dag):
    """Add nodes to register to a `multi_inheritance_dag()` result.

    A random subset, always including the root.
    """
    classes, ancestors = dag
    return st.sets(st.integers(min_value=0, max_value=len(classes) - 1)).map(
        lambda registered: (classes, ancestors, registered | {0})
    )
