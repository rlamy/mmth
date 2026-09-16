import itertools

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from mmth import Multimethod


@st.composite
def _tree_with_registrations(draw, max_size=12):
    """A random single-inheritance tree (node 0 is the root; node i's parent
    is some earlier node), plus a random subset of nodes to register - the
    root is always included, so every node has at least one registered
    ancestor.
    """
    n = draw(st.integers(min_value=1, max_value=max_size))
    parents = [0] * n
    for i in range(1, n):
        parents[i] = draw(st.integers(min_value=0, max_value=i - 1))
    registered = draw(st.sets(st.integers(min_value=0, max_value=n - 1)))
    registered.add(0)
    return parents, registered


def _build_classes(parents):
    classes = [type("Node0", (object,), {})]
    for i in range(1, len(parents)):
        classes.append(type(f"Node{i}", (classes[parents[i]],), {}))
    return classes


def _closest_registered_ancestor(node, parents, registered):
    """Independent oracle: since it's single inheritance, a node's registered
    ancestors are totally ordered by the tree's own path to the root - the
    "most derived" one is simply the first one found walking up.
    """
    while node not in registered:
        node = parents[node]
    return node


@given(_tree_with_registrations())
def test_dispatch_picks_the_unique_most_derived_match(tree):
    parents, registered = tree
    classes = _build_classes(parents)
    mm = Multimethod()

    for i in sorted(registered):
        mm.register(classes[i])(lambda obj, i=i: i)

    for node in range(len(classes)):
        expected = _closest_registered_ancestor(node, parents, registered)
        assert mm(classes[node]()) == expected


@st.composite
def _multi_arg_chain(draw, max_arity=3, max_tree_size=6, max_steps=8):
    """`arity` independent inheritance trees, plus a chain of signatures (one
    per argument position each) to register.

    Registering arbitrary signature tuples across multiple positions can be
    genuinely ambiguous - e.g. (Dog, Animal) and (Animal, Dog) neither
    dominates the other, so a query of (Dog, Dog) has no unique answer. To
    keep this a test of the "unique most derived match" invariant rather
    than of ambiguity detection, registrations are built as a chain: start
    at the all-roots signature (an ancestor of every possible call), then
    repeatedly narrow *one* position to a direct child of its current
    value. Each step is therefore strictly more specific, in every
    position, than every step before it - so any two registered signatures
    are always comparable, and any subset of them that matches a given call
    has a well-defined unique maximum.
    """
    arity = draw(st.integers(min_value=1, max_value=max_arity))

    trees = []
    for _ in range(arity):
        n = draw(st.integers(min_value=1, max_value=max_tree_size))
        parents = [0] * n
        children: list[list[int]] = [[] for _ in range(n)]
        for i in range(1, n):
            p = draw(st.integers(min_value=0, max_value=i - 1))
            parents[i] = p
            children[p].append(i)
        trees.append((parents, children))

    current = [0] * arity
    chain = [tuple(current)]

    num_steps = draw(st.integers(min_value=0, max_value=max_steps))
    for _ in range(num_steps):
        pos = draw(st.integers(min_value=0, max_value=arity - 1))
        available = trees[pos][1][current[pos]]
        if not available:
            continue
        current[pos] = available[draw(st.integers(min_value=0, max_value=len(available) - 1))]
        chain.append(tuple(current))

    return trees, chain


def _is_ancestor(candidate, query, parents):
    """True if `candidate` is `query`, or an ancestor of it, in this tree."""
    node = query
    while node != candidate and node != 0:
        node = parents[node]
    return node == candidate


def _most_specific_match(chain, query, trees):
    """Independent oracle: `chain` is registered in strictly increasing
    order of specificity (see `_multi_arg_chain`), so the last entry that
    matches `query` in every position is the unique most derived match.
    """
    winner = None
    for sig in chain:
        if all(
            _is_ancestor(sig[i], query[i], trees[i][0]) for i in range(len(query))
        ):
            winner = sig
    return winner


@given(_multi_arg_chain())
def test_multi_arg_dispatch_picks_the_unique_most_derived_match(data):
    trees, chain = data
    arity = len(trees)
    class_lists = [_build_classes(parents) for parents, _children in trees]
    mm = Multimethod()

    for sig in chain:
        types = tuple(class_lists[i][sig[i]] for i in range(arity))
        mm.register(*types)(lambda *args, sig=sig: sig)

    sizes = [len(cl) for cl in class_lists]
    for query in itertools.product(*(range(s) for s in sizes)):
        expected = _most_specific_match(chain, query, trees)
        instances = [class_lists[i][query[i]]() for i in range(arity)]
        assert mm(*instances) == expected


@st.composite
def _multi_arg_registrations(draw, min_arity=2, max_arity=3, max_tree_size=5, max_regs=8):
    """Like `_multi_arg_chain`, but registrations form a *tree* rather than a
    straight-line chain: each new signature narrows one position of some
    *existing* registration (not necessarily the most recent one) to one of
    its direct children. Two registrations extending the same base via
    different positions are siblings - each strictly more specific than
    their shared base, but incomparable with each other - deliberately
    producing the "diamond" pattern that makes a query ambiguous.
    """
    arity = draw(st.integers(min_value=min_arity, max_value=max_arity))

    trees = []
    for _ in range(arity):
        n = draw(st.integers(min_value=1, max_value=max_tree_size))
        parents = [0] * n
        children: list[list[int]] = [[] for _ in range(n)]
        for i in range(1, n):
            p = draw(st.integers(min_value=0, max_value=i - 1))
            parents[i] = p
            children[p].append(i)
        trees.append((parents, children))

    registrations = [tuple([0] * arity)]
    num_new = draw(st.integers(min_value=0, max_value=max_regs))
    for _ in range(num_new):
        base = registrations[draw(st.integers(min_value=0, max_value=len(registrations) - 1))]
        pos = draw(st.integers(min_value=0, max_value=arity - 1))
        available = trees[pos][1][base[pos]]
        if not available:
            continue
        child = available[draw(st.integers(min_value=0, max_value=len(available) - 1))]
        new_sig = tuple(child if i == pos else base[i] for i in range(arity))
        if new_sig in registrations:
            continue
        registrations.append(new_sig)

    return trees, registrations


def _dominates(sig_a, sig_b, trees):
    """True if `sig_a` is strictly more specialized than `sig_b` - the same
    rule as `Multimethod._is_more_specialized`, reimplemented independently
    via tree walks instead of `issubclass`.
    """
    more_specific = False
    for i in range(len(sig_a)):
        parents = trees[i][0]
        if _is_ancestor(sig_b[i], sig_a[i], parents):
            if not _is_ancestor(sig_a[i], sig_b[i], parents):
                more_specific = True
        else:
            return False
    return more_specific


def _maximal_matches(registrations, query, trees):
    """Independent oracle: the registered signatures that match `query`
    (are an ancestor of it in every position), filtered down to the ones
    none of the others dominates. Dispatch should succeed, returning the
    single survivor, when there's exactly one; and raise "Ambiguous
    dispatch" when there's more than one.
    """
    matching = [
        sig
        for sig in registrations
        if all(_is_ancestor(sig[i], query[i], trees[i][0]) for i in range(len(query)))
    ]
    return [
        sig
        for sig in matching
        if not any(_dominates(other, sig, trees) for other in matching if other != sig)
    ]


@given(_multi_arg_registrations())
def test_multi_arg_dispatch_raises_ambiguous_exactly_when_expected(data):
    trees, registrations = data
    arity = len(trees)
    class_lists = [_build_classes(parents) for parents, _children in trees]
    mm = Multimethod()

    for sig in registrations:
        types = tuple(class_lists[i][sig[i]] for i in range(arity))
        mm.register(*types)(lambda *args, sig=sig: sig)

    sizes = [len(cl) for cl in class_lists]
    for query in itertools.product(*(range(s) for s in sizes)):
        maximal = _maximal_matches(registrations, query, trees)
        instances = [class_lists[i][query[i]]() for i in range(arity)]

        if len(maximal) == 1:
            assert mm(*instances) == maximal[0]
        else:
            assert len(maximal) > 1
            with pytest.raises(TypeError, match="Ambiguous dispatch"):
                mm(*instances)


@st.composite
def _multi_inheritance_dag(draw, max_size=10, max_parents=3):
    """A single argument's class hierarchy, but a DAG instead of a tree: each
    node i > 0 gets 1..max_parents *direct* parents drawn from the earlier
    nodes, and the classes are built for real as we go (not just as an
    abstract graph), because getting them to actually construct relies on
    Python's own, already-computed MROs:

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
    parent_lists: list[list[int]] = [[]]
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
        parent_lists.append(parents)
        ancestors.append(frozenset({i}).union(*(ancestors[p] for p in parents)))

        try:
            checkpoint = type(f"Checkpoint{i}", (new_cls, checkpoint), {})
        except TypeError:
            pass  # keep the previous checkpoint; it's still valid, just stale

    registered = draw(st.sets(st.integers(min_value=0, max_value=n - 1)))
    registered.add(0)
    return classes, ancestors, registered


def _maximal_registered_ancestors(node, registered, ancestors):
    """Independent oracle, using the ancestor sets tracked alongside the DAG
    itself (see `_multi_inheritance_dag`) rather than `issubclass`.
    """
    matching = [r for r in registered if r in ancestors[node]]
    return [
        r for r in matching if not any(r2 != r and r in ancestors[r2] for r2 in matching)
    ]


@given(_multi_inheritance_dag(), st.booleans())
def test_dispatch_handles_multiple_inheritance(data, reverse_registration_order):
    classes, ancestors, registered = data
    mm = Multimethod()

    # registration order shouldn't matter - this is exactly the axis a past
    # bug in _find_most_specialized got wrong (see the ambiguity test above)
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
