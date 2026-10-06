import itertools
import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mmth import AmbiguousMatchError, Multimethod

from strategies import multi_inheritance_dag, with_registered_subset


def _maximal_registered_ancestors(node, registered, ancestors):
    """Return the registered ancestors of `node` that nothing else beats.

    Computed from the ancestor sets rather than `issubclass`.
    """
    matching = [r for r in registered if r in ancestors[node]]
    return [
        r
        for r in matching
        if not any(r2 != r and r in ancestors[r2] for r2 in matching)
    ]


@given(multi_inheritance_dag().flatmap(with_registered_subset), st.booleans())
def test_dispatch_handles_multiple_inheritance(data, reverse_registration_order):
    classes, ancestors, registered = data
    mm = Multimethod(arity=1)

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
            with pytest.raises(AmbiguousMatchError, match="is ambiguous between") as e:
                mm(instance)
            assert sorted(impl(None) for _, impl in e.value.candidates) == sorted(
                maximal
            )


@st.composite
def _multi_arg_dags(draw, min_arity=2, max_arity=3, max_size=6, max_parents=3):
    """Generate one `multi_inheritance_dag()` per argument position.

    Plus a random subset of signatures to register, always including the
    all-roots one.
    """
    arity = draw(st.integers(min_value=min_arity, max_value=max_arity))
    dags = [
        draw(multi_inheritance_dag(max_size=max_size, max_parents=max_parents))
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
    """`TypeMap._is_more_specialized`, from the ancestor sets."""
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
            other != sig and _dominates(other, sig, ancestors_lists)
            for other in matching
        )
    ]


@given(_multi_arg_dags(), st.booleans())
def test_multi_arg_dispatch_handles_ambiguity(data, reverse_registration_order):
    class_lists, ancestors_lists, registered = data
    arity = len(class_lists)
    mm = Multimethod(arity=arity)

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
            with pytest.raises(AmbiguousMatchError, match="is ambiguous between") as e:
                mm(*instances)
            assert sorted(impl() for _, impl in e.value.candidates) == sorted(maximal)
            # The suggested fix resolves the ambiguity.
            fix = re.search(
                r"^Register \w+\((.*)\) to resolve it\.$", str(e.value), re.M
            )
            by_name = [{cls.__name__: cls for cls in cl} for cl in class_lists]
            fix_types = [by_name[p][n] for p, n in enumerate(fix[1].split(", "))]
            child = mm.inherit()
            child.register(*fix_types)(lambda *args: "fix")
            assert child(*instances) == "fix"
