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
