"""A mapping keyed by tuples of types, looked up by subclass."""

import weakref
from abc import get_cache_token
from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any, Self

_Signature = tuple[type, ...]


def _type_name(t: Any) -> str:
    """Return how error messages show type `t`: `None`, else its qualname.

    Leave out the enclosing functions of a class defined in one, as Python
    does in its own messages.
    """
    if t is type(None):
        return "None"
    return getattr(t, "__qualname__", repr(t)).rpartition("<locals>.")[2]


def _format_types(types: tuple[Any, ...]) -> str:
    """Return how error messages show a tuple of types, e.g. `(int, str)`."""
    names = [_type_name(t) for t in types]
    return f"({names[0]},)" if len(names) == 1 else f"({', '.join(names)})"


def _count(n: int, noun: str) -> str:
    """Return e.g. `1 type` or `2 types`."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


class NoMatchError(TypeError):
    """Raised by `TypeMap.lookup()` when no key matches.

    Attributes:
        types: The tuple of types looked up.
    """

    def __init__(self, message: str, types: _Signature = ()) -> None:
        """Create the error, for a lookup of `types`."""
        super().__init__(message)
        self.types = types

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle the attributes along with the message."""
        return type(self), (str(self), self.types), self.__dict__


class AmbiguousMatchError(TypeError):
    """Raised by `TypeMap.lookup()` when no matching key is the most specific.

    Attributes:
        types: The tuple of types looked up.
        candidates: The matching `(key, value)` pairs, none more specific
            than the others.
    """

    def __init__(
        self,
        message: str,
        types: _Signature = (),
        candidates: tuple[tuple[_Signature, Any], ...] = (),
    ) -> None:
        """Create the error, for a lookup of `types` matching `candidates`."""
        super().__init__(message)
        self.types = types
        self.candidates = candidates

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle the attributes along with the message."""
        return type(self), (str(self), self.types, self.candidates), self.__dict__


class TypeMap(MutableMapping[_Signature, Any]):
    """A mapping keyed by tuples of types, with lookups that match subclasses.

    As a mapping, it only holds its own keys, matched exactly. `lookup()`
    looks up the value of the most specific key that a tuple of types
    matches position by position, each a subclass of the key's type; an
    exact key is always the most specific. It caches its results.

    All keys have the same length, its `arity`.
    """

    # Slots, since `lookup()` is performance-critical (see
    # docs/performance.md).
    __slots__ = (
        "_table",
        "_cache",
        "_abc_token",
        "_dependents",
        "_arity",
        "__weakref__",
    )

    def __init__(
        self,
        table: Mapping[_Signature, Any] | None = None,
        *,
        arity: int | None = None,
    ) -> None:
        """Create a type map holding the keys and values of `table`.

        Its `arity` is inferred from `table`'s keys; pass `arity` instead only
        to start empty. Raise `TypeError` if there's neither, and `ValueError`
        if the keys don't all have the same length (`arity`, if given).
        """
        if arity is None:
            if not table:
                raise TypeError("TypeMap() needs an arity, or a table to infer it from")
            arity = len(next(iter(table)))
        self._arity = arity
        self._table: dict[_Signature, Any] = {}
        self._cache: dict[type | _Signature, Any] = {}
        # Set once an ABC is registered, since `SomeABC.register(cls)` can
        # change `issubclass` results after they were cached.
        self._abc_token: object | None = None
        # Type maps whose lookups depend on this one's keys, by `id()` since
        # mappings are unhashable.
        self._dependents: weakref.WeakValueDictionary[int, TypeMap] = (
            weakref.WeakValueDictionary()
        )
        if table:
            self.update(table)

    def _invalidate_cache(self) -> None:
        self._cache.clear()
        for dependent in self._dependents.values():
            dependent._invalidate_cache()

    @staticmethod
    def _is_more_specialized(sig_a: _Signature, sig_b: _Signature) -> bool:
        """Return whether `sig_a` is strictly more specialized than `sig_b`."""
        return sig_a != sig_b and all(map(issubclass, sig_a, sig_b))

    @staticmethod
    def _match_signature(sig: _Signature, types: _Signature) -> bool:
        return all(map(issubclass, types, sig))

    def _lookup_table(self) -> dict[_Signature, Any]:
        """Return the keys and values `lookup()` looks among."""
        return self._table

    def _find_most_specialized(
        self, table: dict[_Signature, Any], types: _Signature
    ) -> Any:
        """Return the most specific matching key's value.

        Raise `NoMatchError` if no key matches, or `AmbiguousMatchError`.
        """
        candidates = [
            (sig, value)
            for sig, value in table.items()
            if self._match_signature(sig, types)
        ]
        if not candidates:
            raise NoMatchError(f"No key matches {_format_types(types)}", types)

        # Not a running "best so far": a later candidate can dominate two
        # earlier, mutually incomparable ones.
        maximal = [
            (sig, value)
            for sig, value in candidates
            if not any(
                self._is_more_specialized(other_sig, sig) for other_sig, _ in candidates
            )
        ]
        if len(maximal) > 1:
            keys = ", ".join(_format_types(sig) for sig, _ in maximal)
            raise AmbiguousMatchError(
                f"Ambiguous lookup for {_format_types(types)}: matches {keys}, "
                f"none more specific than the others",
                types,
                tuple(maximal),
            )
        return maximal[0][1]

    def _miss(self, types: _Signature) -> Any:
        if len(types) != self._arity:
            raise TypeError(
                f"Expected {_count(self._arity, 'type')}, got {len(types)}: "
                f"{_format_types(types)}"
            )
        table = self._lookup_table()
        if types in table:
            return table[types]
        return self._find_most_specialized(table, types)

    def __getitem__(self, sig: _Signature) -> Any:
        """Return the value stored under exactly the key `sig`."""
        return self._table[sig]

    def __setitem__(self, sig: _Signature, value: Any) -> None:
        """Store `value` under exactly the key `sig`.

        Raise `TypeError` if `sig` holds anything but classes, and
        `ValueError` if its length isn't this type map's `arity`.
        """
        if not all(isinstance(t, type) for t in sig):
            raise TypeError(f"Key {sig!r} holds something other than classes")
        if len(sig) != self._arity:
            raise ValueError(
                f"Key {_format_types(sig)} has {_count(len(sig), 'type')}, but "
                f"this type map's keys have {self._arity}"
            )
        self._table[sig] = value
        if self._abc_token is None and any(
            hasattr(t, "__abstractmethods__") for t in sig
        ):
            self._abc_token = get_cache_token()
        self._invalidate_cache()

    def __delitem__(self, sig: _Signature) -> None:
        """Remove exactly the key `sig`, raising `KeyError` if it isn't stored here."""
        del self._table[sig]
        self._invalidate_cache()

    def __iter__(self) -> Iterator[_Signature]:
        """Iterate over the keys stored here, not the parent's."""
        return iter(self._table)

    def __len__(self) -> int:
        """Return the number of keys stored here."""
        return len(self._table)

    def _copy_with(self, table: Mapping[_Signature, Any]) -> Self:
        """Return a type map like this one, but holding `table`."""
        return type(self)(table, arity=self._arity)

    def __copy__(self) -> Self:
        """Return a type map with the same keys.

        The copy is independent: changing either one leaves the other as is.
        """
        return self._copy_with(self._table)

    @property
    def arity(self) -> int:
        """Return the length of every key."""
        return self._arity

    def lookup(self, key: type | _Signature) -> Any:
        """Return the value for the most specific key the types `key` match.

        `key` is a tuple of types, or a bare type for a one-element tuple.
        Raise `TypeError` if `key` doesn't have `arity` types, `NoMatchError`
        if no key matches, and `AmbiguousMatchError` if no single matching key
        is more specific than all the others. The result is cached, per
        `key`, until this type map changes.
        """
        if self._abc_token is not None and self._abc_token != get_cache_token():
            self._abc_token = get_cache_token()
            self._cache.clear()
        try:
            return self._cache[key]
        except KeyError:
            pass
        value = self._miss(key if isinstance(key, tuple) else (key,))
        self._cache[key] = value
        return value


class ChainTypeMap(TypeMap):
    """A type map whose `lookup()` also matches the keys of a parent type map.

    As a mapping, it only holds its own keys; `lookup()` looks among the keys
    `parent | self`, as by `dict.__or__`, so its own keys replace equal ones,
    and the most specific of all the others wins. Its cache is invalidated
    when the parent changes. It has its parent's `arity`.
    """

    __slots__ = ("_parent",)

    def __init__(
        self, parent: TypeMap, table: Mapping[_Signature, Any] | None = None
    ) -> None:
        """Create a type map chained to `parent`, holding `table`, if given.

        It has `parent`'s arity, so `table` can be left out to start empty.
        """
        # Set first, as storing `table` invalidates the cache, which reads it.
        self._parent = parent
        super().__init__(table, arity=parent.arity)
        parent._dependents[id(self)] = self
        if parent._abc_token is not None:
            self._abc_token = get_cache_token()

    def _invalidate_cache(self) -> None:
        # The parent may have just started watching ABCs.
        if self._abc_token is None and self._parent._abc_token is not None:
            self._abc_token = get_cache_token()
        super()._invalidate_cache()

    def _lookup_table(self) -> dict[_Signature, Any]:
        return self._parent._lookup_table() | self._table

    def _copy_with(self, table: Mapping[_Signature, Any]) -> Self:
        return type(self)(self._parent, table)
