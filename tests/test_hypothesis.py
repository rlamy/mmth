import itertools

from hypothesis import given
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
