import itertools

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from mmth import Multimethod


@st.composite
def _multi_inheritance_dag(draw, max_size=10, max_parents=3):
    """A class hierarchy as a DAG rather than a tree: each node i > 0 gets
    1..max_parents *direct* parents drawn from the earlier nodes (so
    `max_parents=1` degenerates to a plain single-inheritance tree). The
    classes are built for real as we go (not just as an abstract graph),
    because getting them to actually construct relies on Python's own,
    already-computed MROs:

    - Python rejects a bases list where one base is already an ancestor of
      another (no valid MRO from that alone), so direct parents are first
      filtered down to an antichain (mutually unrelated nodes) - diamonds
      are still very much possible deeper in the hierarchy, e.g. two nodes
      that each have a single, different parent, both ultimately
      descending from the same node further up; only a single class's own
      *direct* bases are constrained this way.
    - That alone isn't sufficient, though: two classes sharing some of the
      same (unrelated) ancestors, but listing them in opposite orders, can
      each be individually fine while a later class combining both as
      bases has no consistent MRO. A *fixed* rule (e.g. always sort by
      node index) doesn't reliably avoid this either - a single-inheritance
      chain doesn't get sorted, its internal MRO order is just a fixed
      consequence of the chain, and that can silently disagree with a
      fixed sort order chosen elsewhere:

          class N1(N0): pass
          class N2(N0): pass          # unrelated; fixed rule: N2 before N1
          class N3(N1): pass
          class N4(N3, N2): pass      # bases correctly sorted (N3, N2)...
          N4.__mro__  # ...N3, N1, N2...  <- N1 before N2 regardless!

      Instead, every antichain is ordered by each candidate's position in
      a running "checkpoint" class's *real* `__mro__` - literally a class
      that inherits from every node built so far, kept up to date by
      re-deriving it (`type(new_node, checkpoint)`) after each new node.
      Since that position comes from an MRO Python already accepted, it
      reflects every constraint established so far, not just a
      once-and-for-all guess - which cuts how often a class is still
      unconstructible by roughly 40x in practice (measured by comparing
      against the fixed-order version of this same generator). It doesn't
      reach zero, though: a new node's *own* multi-parent merge can
      introduce an emergent ordering for some pair that the checkpoint
      didn't know about yet (the same phenomenon as above, recursively,
      between the new node and the checkpoint itself) - when re-deriving
      the checkpoint fails for that reason, the previous (still valid)
      checkpoint is simply kept rather than updated, and the rare residual
      case where a *node itself* (not just the checkpoint) fails to
      construct is discarded via `assume(False)`.
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
    """Extend a `_multi_inheritance_dag()` result with a random subset of
    nodes to register - always including the root, so every node has at
    least one registered ancestor. Kept separate from the DAG generator
    itself: which nodes get registered is the test's own concern, not a
    property of the class hierarchy.
    """
    classes, ancestors = dag
    return st.sets(st.integers(min_value=0, max_value=len(classes) - 1)).map(
        lambda registered: (classes, ancestors, registered | {0})
    )


def _maximal_registered_ancestors(node, registered, ancestors):
    """Independent oracle, using the ancestor sets tracked alongside the DAG
    itself (see `_multi_inheritance_dag`) rather than `issubclass`.
    """
    matching = [r for r in registered if r in ancestors[node]]
    return [
        r for r in matching if not any(r2 != r and r in ancestors[r2] for r2 in matching)
    ]


@given(_multi_inheritance_dag().flatmap(_with_registered_subset), st.booleans())
def test_dispatch_handles_multiple_inheritance(data, reverse_registration_order):
    classes, ancestors, registered = data
    mm = Multimethod()

    # registration order shouldn't matter - this is exactly the axis a past
    # bug in _find_most_specialized got wrong (see the ambiguity test below)
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
    """`arity` independent `_multi_inheritance_dag()` draws, one per
    argument position, plus a random subset of signature tuples (one node
    index per position) to register - always including the all-roots
    signature, so every query has at least one registered match. `arity`
    starts at 2 (not 1) since single-argument dispatch is already covered,
    more thoroughly, by `test_dispatch_handles_multiple_inheritance` above.
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
    """True if `sig_a` is strictly more specialized than `sig_b` - the same
    rule as `Multimethod._is_more_specialized`, computed from the tracked
    ancestor sets instead of `issubclass`.
    """
    more_specific = False
    for a, b, ancestors in zip(sig_a, sig_b, ancestors_lists):
        if b in ancestors[a]:
            if a not in ancestors[b]:
                more_specific = True
        else:
            return False
    return more_specific


def _maximal_registered_signatures(query, registered, ancestors_lists):
    """Independent oracle, generalizing `_maximal_registered_ancestors` to
    multiple argument positions.
    """
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
