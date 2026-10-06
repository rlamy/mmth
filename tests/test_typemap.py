import copy
from abc import ABC

import pytest

from mmth import AmbiguousMatchError, ChainTypeMap, NoMatchError, TypeMap


class Animal:
    pass


class Dog(Animal):
    pass


class Pet:
    pass


class PetDog(Dog, Pet):
    pass


def test_mapping_is_exact_and_own_keys_only():
    parent = TypeMap({(object,): "object"})
    tm = ChainTypeMap(parent, {(Animal,): "animal"})
    assert tm[(Animal,)] == "animal"
    with pytest.raises(KeyError):
        tm[(Dog,)]
    with pytest.raises(KeyError):
        tm[(object,)]
    assert (Dog,) not in tm
    assert tm.get((Dog,)) is None
    assert list(tm) == [(Animal,)]
    assert len(tm) == 1
    assert dict(tm) == {(Animal,): "animal"}


def test_lookup_finds_exact_then_most_specific():
    tm = TypeMap({(Animal,): "animal", (Dog,): "dog"})
    assert tm.lookup(Animal) == tm.lookup((Animal,)) == "animal"
    assert tm.lookup(PetDog) == "dog"
    with pytest.raises(NoMatchError, match="No key matches"):
        tm.lookup(int)


def test_arity_is_given_or_inferred_from_the_table():
    for table in [None, {}]:
        with pytest.raises(TypeError, match="needs an arity"):
            TypeMap(table)
    assert TypeMap(arity=2).arity == 2
    assert TypeMap({(Animal, Animal): "animal, animal"}).arity == 2
    with pytest.raises(ValueError, match="has 1 types"):
        TypeMap({(Animal,): "animal"}, arity=2)
    with pytest.raises(ValueError, match="has 1 types"):
        TypeMap({(Animal, Animal): "animal, animal", (Animal,): "animal"})


def test_keys_all_have_the_arity_of_the_parent():
    parent = TypeMap(arity=2)
    with pytest.raises(NoMatchError):
        parent.lookup((Dog, Dog))
    child = ChainTypeMap(parent, {(Animal, Animal): "animal, animal"})
    assert child.arity == copy.copy(child).arity == 2
    with pytest.raises(ValueError, match="has 1 types"):
        ChainTypeMap(parent, {(Animal,): "animal"})
    with pytest.raises(ValueError, match="has 1 types"):
        child[(Animal,)] = "animal"
    assert child.lookup((Dog, Dog)) == "animal, animal"
    for key in [Dog, (Dog, Dog, Dog)]:
        with pytest.raises(TypeError, match="Expected 2 types") as exc_info:
            child.lookup(key)
        assert exc_info.type is TypeError


def test_lookup_raises_on_ambiguity():
    tm = TypeMap({(Dog,): "dog", (Pet,): "pet"})
    with pytest.raises(AmbiguousMatchError, match="Ambiguous lookup"):
        tm.lookup(PetDog)


def test_lookup_falls_back_on_ancestors():
    root = TypeMap({(object,): "root object", (Animal,): "animal"})
    child = ChainTypeMap(root)
    grandchild = ChainTypeMap(child, {(object,): "grandchild object"})
    assert child.lookup(Dog) == grandchild.lookup(Dog) == "animal"
    assert child.lookup(int) == "root object"
    assert grandchild.lookup(int) == "grandchild object"


def test_lookup_merges_parent_keys_with_own():
    parent = TypeMap({(Animal,): "parent animal", (Dog,): "parent dog"})
    child = ChainTypeMap(parent, {(object,): "child object", (Animal,): "child animal"})
    assert child.lookup(Animal) == "child animal"
    assert child.lookup(PetDog) == "parent dog"
    assert child.lookup(int) == "child object"
    child[(Pet,)] = "child pet"
    with pytest.raises(AmbiguousMatchError):
        child.lookup(PetDog)


def test_lookup_caches_until_the_type_map_changes():
    checks = []

    class Counting(type):
        def __subclasscheck__(cls, subclass):
            checks.append(subclass)
            return super().__subclasscheck__(subclass)

    class Base(metaclass=Counting):
        pass

    class Leaf(Base):
        pass

    tm = TypeMap({(Base,): "base"})
    assert tm.lookup(Leaf) == "base"
    assert checks
    checks.clear()
    assert tm.lookup(Leaf) == "base"
    assert not checks
    tm[(object,)] = "object"
    assert tm.lookup(Leaf) == "base"
    assert checks


def test_delitem_removes_only_exact_own_keys():
    parent = TypeMap({(Animal,): "animal"})
    tm = ChainTypeMap(parent, {(Dog,): "dog"})
    with pytest.raises(KeyError):
        del tm[(PetDog,)]
    with pytest.raises(KeyError):
        del tm[(Animal,)]
    assert tm.lookup(Dog) == "dog"
    del tm[(Dog,)]
    assert tm.lookup(Dog) == "animal"
    assert list(parent) == [(Animal,)]


def test_parent_changes_invalidate_children():
    parent = TypeMap({(object,): "object"})
    child = ChainTypeMap(parent)
    grandchild = ChainTypeMap(child)
    assert grandchild.lookup(Dog) == "object"
    parent[(Animal,)] = "animal"
    assert grandchild.lookup(Dog) == "animal"
    del parent[(Animal,)]
    assert grandchild.lookup(Dog) == "object"


def test_abc_registration_invalidates_cache():
    class Walker(ABC):
        pass

    parent = TypeMap({(object,): "object", (Walker,): "walker"})
    child = ChainTypeMap(parent)
    assert parent.lookup(Dog) == child.lookup(Dog) == "object"
    Walker.register(Dog)
    assert parent.lookup(Dog) == child.lookup(Dog) == "walker"


def test_children_watch_abcs_once_their_parent_does():
    class Walker(ABC):
        pass

    parent = TypeMap({(object,): "object"})
    grandchild = ChainTypeMap(ChainTypeMap(parent))
    assert grandchild.lookup(Dog) == "object"
    parent[(Walker,)] = "walker"
    assert grandchild.lookup(Dog) == "object"
    Walker.register(Dog)
    assert grandchild.lookup(Dog) == "walker"


def test_copy_is_independent_but_keeps_parent():
    parent = TypeMap({(object,): "object"})
    tm = ChainTypeMap(parent, {(Animal,): "animal"})
    child = ChainTypeMap(tm)
    assert child.lookup(Dog) == "animal"

    clone = copy.copy(tm)
    clone[(Dog,)] = "dog"
    del clone[(Animal,)]
    assert dict(tm) == {(Animal,): "animal"}
    assert dict(clone) == {(Dog,): "dog"}
    assert tm.lookup(Dog) == "animal"
    assert child.lookup(Dog) == "animal"
    assert clone.lookup(PetDog) == "dog"
    assert clone.lookup(Animal) == "object"

    parent[(Animal,)] = "parent animal"
    assert clone.lookup(Animal) == "parent animal"


def test_copy_keeps_watching_abcs():
    class Walker(ABC):
        pass

    tm = TypeMap({(object,): "object", (Walker,): "walker"})
    clone = copy.copy(tm)
    assert clone.lookup(Dog) == "object"
    Walker.register(Dog)
    assert clone.lookup(Dog) == "walker"
