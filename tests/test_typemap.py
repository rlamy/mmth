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
    parent = TypeMap()
    parent[(object,)] = "object"
    tm = ChainTypeMap(parent)
    tm[(Animal,)] = "animal"
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
    tm = TypeMap()
    tm[(Animal,)] = "animal"
    tm[(Dog,)] = "dog"
    tm[(Animal, Animal)] = "animal, animal"
    assert tm.lookup(Animal) == tm.lookup((Animal,)) == "animal"
    assert tm.lookup(PetDog) == "dog"
    assert tm.lookup((Dog, PetDog)) == "animal, animal"
    with pytest.raises(NoMatchError, match="No key matches"):
        tm.lookup(int)


def test_lookup_raises_on_ambiguity():
    tm = TypeMap()
    tm[(Dog,)] = "dog"
    tm[(Pet,)] = "pet"
    with pytest.raises(AmbiguousMatchError, match="Ambiguous lookup"):
        tm.lookup(PetDog)


def test_lookup_falls_back_on_parent_then_nearest_default():
    root = TypeMap(default="root default")
    root[(Animal,)] = "animal"
    child = ChainTypeMap(root)
    grandchild = ChainTypeMap(child, default="grandchild default")
    assert child.lookup(Dog) == grandchild.lookup(Dog) == "animal"
    assert child.lookup(int) == "root default"
    assert grandchild.lookup(int) == "grandchild default"
    assert TypeMap(default=None).lookup(int) is None


def test_lookup_merges_parent_keys_with_own():
    parent = TypeMap()
    parent[(Animal,)] = "parent animal"
    parent[(Dog,)] = "parent dog"
    child = ChainTypeMap(parent)
    child[(object,)] = "child object"
    child[(Animal,)] = "child animal"
    assert child.lookup(Animal) == "child animal"
    assert child.lookup(PetDog) == "parent dog"
    assert child.lookup(int) == "child object"
    child[(Pet,)] = "child pet"
    with pytest.raises(AmbiguousMatchError):
        child.lookup(PetDog)


def test_lookup_adapts_once_per_looked_up_types():
    made = []
    tm = TypeMap(adapt=lambda value: made.append(value) or [value])
    tm[(Animal,)] = "animal"
    dog, again, pet_dog = tm.lookup(Dog), tm.lookup(Dog), tm.lookup(PetDog)
    assert dog is again
    assert dog is not pet_dog
    assert made == ["animal", "animal"]


def test_lookup_adapts_values_including_the_default():
    tm = TypeMap(default="default", adapt=str.upper)
    tm[(Animal,)] = "animal"
    assert tm.lookup(Dog) == "ANIMAL"
    assert tm.lookup(int) == "DEFAULT"
    assert tm[(Animal,)] == "animal"


def test_lookup_caches_until_the_type_map_changes():
    calls = []

    def adapt(value):
        calls.append(value)
        return value

    tm = TypeMap(adapt=adapt)
    tm[(Animal,)] = "animal"
    assert tm.lookup(Dog) == tm.lookup(Dog) == "animal"
    assert calls == ["animal"]
    tm[(Dog,)] = "dog"
    assert tm.lookup(Dog) == "dog"
    assert calls == ["animal", "dog"]


def test_delitem_removes_only_exact_own_keys():
    parent = TypeMap()
    parent[(Animal,)] = "animal"
    tm = ChainTypeMap(parent)
    tm[(Dog,)] = "dog"
    with pytest.raises(KeyError):
        del tm[(PetDog,)]
    with pytest.raises(KeyError):
        del tm[(Animal,)]
    assert tm.lookup(Dog) == "dog"
    del tm[(Dog,)]
    assert tm.lookup(Dog) == "animal"
    assert list(parent) == [(Animal,)]


def test_parent_changes_invalidate_children():
    parent = TypeMap()
    parent[(object,)] = "object"
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

    parent = TypeMap()
    parent[(object,)] = "object"
    parent[(Walker,)] = "walker"
    child = ChainTypeMap(parent)
    assert parent.lookup(Dog) == child.lookup(Dog) == "object"
    Walker.register(Dog)
    assert parent.lookup(Dog) == child.lookup(Dog) == "walker"


def test_children_watch_abcs_once_their_parent_does():
    class Walker(ABC):
        pass

    parent = TypeMap()
    parent[(object,)] = "object"
    grandchild = ChainTypeMap(ChainTypeMap(parent))
    assert grandchild.lookup(Dog) == "object"
    parent[(Walker,)] = "walker"
    assert grandchild.lookup(Dog) == "object"
    Walker.register(Dog)
    assert grandchild.lookup(Dog) == "walker"


def test_copy_is_independent_but_keeps_parent_default_and_adapt():
    parent = TypeMap()
    parent[(object,)] = "object"
    tm = ChainTypeMap(parent, default="default", adapt=str.upper)
    tm[(Animal,)] = "animal"
    child = ChainTypeMap(tm)
    assert child.lookup(Dog) == "animal"

    clone = copy.copy(tm)
    clone[(Dog,)] = "dog"
    del clone[(Animal,)]
    assert dict(tm) == {(Animal,): "animal"}
    assert dict(clone) == {(Dog,): "dog"}
    assert tm.lookup(Dog) == "ANIMAL"
    assert child.lookup(Dog) == "animal"
    assert clone.lookup(PetDog) == "DOG"
    assert clone.lookup(Animal) == "OBJECT"

    parent[(Animal,)] = "parent animal"
    assert clone.lookup(Animal) == "PARENT ANIMAL"


def test_copy_keeps_watching_abcs():
    class Walker(ABC):
        pass

    tm = TypeMap(default="default")
    tm[(Walker,)] = "walker"
    clone = copy.copy(tm)
    assert clone.lookup(Dog) == "default"
    Walker.register(Dog)
    assert clone.lookup(Dog) == "walker"
