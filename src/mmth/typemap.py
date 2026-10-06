"""A mapping keyed by tuples of types, looked up by subclass."""

import weakref
from abc import get_cache_token
from collections.abc import Iterator, MutableMapping
from typing import Any, Callable, Self

_Signature = tuple[type, ...]
_MISSING: Any = object()


class NoMatchError(TypeError):
    """Raised by `TypeMap.lookup()` when no key matches."""


class AmbiguousMatchError(TypeError):
    """Raised by `TypeMap.lookup()` when no matching key is the most specific."""


class TypeMap(MutableMapping[_Signature, Any]):
    """A mapping keyed by tuples of types, with lookups that match subclasses.

    As a mapping, it only holds its own keys, matched exactly. `lookup()`
    looks up the value of the most specific key that a tuple of types
    matches position by position, each a subclass of the key's type; an
    exact key is always the most specific. It caches its results.

    All keys have the same length, its `arity`, set by the first key stored.
    """

    # Slots, since `lookup()` is performance-critical (see
    # docs/performance.md).
    __slots__ = (
        "_table",
        "_cache",
        "_abc_token",
        "_dependents",
        "_arity",
        "_adapt",
        "__weakref__",
    )

    # Formatted with `types`; a subclass can reword them for its own domain.
    _no_match_message = "No key matches types {types}"
    _ambiguous_message = "Ambiguous lookup for types {types}: matches several keys"
    _arity_message = "Expected {arity} types, got {types}"

    def __init__(self, *, adapt: Callable[[Any], Any] | None = None) -> None:
        """Create an empty type map.

        `lookup()` passes whatever it finds through `adapt`, if given. Since
        `lookup()` caches by the types looked up, not by the key they
        matched, `adapt` runs once per distinct looked-up types: `list` and
        `tuple` both matching `(Sequence,)` get separately adapted values.
        """
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
        self._arity: int | None = None
        self._adapt = adapt

    def _check_arity(self, sig: _Signature) -> None:
        if self._arity is None:
            self._arity = len(sig)
        elif len(sig) != self._arity:
            raise ValueError(
                f"Key {sig} has {len(sig)} types, but this type map's keys "
                f"have {self._arity}"
            )

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
        return all(
            isinstance(sig_type, type) and issubclass(arg_type, sig_type)
            for sig_type, arg_type in zip(sig, types)
        )

    def _lookup_table(self) -> dict[_Signature, Any]:
        """Return the keys and values `lookup()` looks among."""
        return self._table

    def _find_most_specialized(
        self, table: dict[_Signature, Any], types: _Signature
    ) -> Any:
        """Return the most specific matching key's value, or raise on ambiguity."""
        candidates = [
            (sig, value)
            for sig, value in table.items()
            if self._match_signature(sig, types)
        ]
        if not candidates:
            return _MISSING

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
            raise AmbiguousMatchError(self._ambiguous_message.format(types=types))
        return maximal[0][1]

    def _miss(self, types: _Signature) -> Any:
        arity = self.arity
        if arity is not None and len(types) != arity:
            raise TypeError(self._arity_message.format(arity=arity, types=types))
        table = self._lookup_table()
        try:
            value = table[types]
        except KeyError:
            value = self._find_most_specialized(table, types)
        if value is _MISSING:
            raise NoMatchError(self._no_match_message.format(types=types))
        return value if self._adapt is None else self._adapt(value)

    def __getitem__(self, sig: _Signature) -> Any:
        """Return the value stored under exactly the key `sig`."""
        return self._table[sig]

    def __setitem__(self, sig: _Signature, value: Any) -> None:
        """Store `value` under exactly the key `sig`.

        Raise `ValueError` if `sig`'s length isn't this type map's `arity`.
        """
        self._check_arity(sig)
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

    def _empty_copy(self) -> Self:
        return type(self)(adapt=self._adapt)

    def __copy__(self) -> Self:
        """Return a type map with the same keys and adapt.

        The copy is independent: changing either one leaves the other as is.
        """
        new = self._empty_copy()
        new._table = self._table.copy()
        new._arity = self._arity
        if self._abc_token is not None:
            new._abc_token = get_cache_token()
        return new

    @property
    def arity(self) -> int | None:
        """Return the length of every key, or None until one is stored."""
        return self._arity

    def lookup(self, key: type | _Signature) -> Any:
        """Return the value for the most specific key the types `key` match.

        `key` is a tuple of types, or a bare type for a one-element tuple.
        Raise `TypeError` if `key` doesn't have `arity` types, `NoMatchError`
        if no key matches, and `AmbiguousMatchError` if no single matching key
        is more specific than all the others. The result is cached, per `key`, until this type map
        changes.
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
    when the parent changes. It shares its parent's `arity`.
    """

    __slots__ = ("_parent",)

    def __init__(
        self,
        parent: TypeMap,
        *,
        adapt: Callable[[Any], Any] | None = None,
    ) -> None:
        """Create an empty type map chained to `parent`."""
        super().__init__(adapt=adapt)
        self._parent = parent
        parent._dependents[id(self)] = self
        if parent._abc_token is not None:
            self._abc_token = get_cache_token()

    def _check_arity(self, sig: _Signature) -> None:
        self._parent._check_arity(sig)

    def _invalidate_cache(self) -> None:
        # The parent may have just started watching ABCs.
        if self._abc_token is None and self._parent._abc_token is not None:
            self._abc_token = get_cache_token()
        super()._invalidate_cache()

    def _lookup_table(self) -> dict[_Signature, Any]:
        return self._parent._lookup_table() | self._table

    def _empty_copy(self) -> Self:
        return type(self)(self._parent, adapt=self._adapt)

    @property
    def arity(self) -> int | None:
        """Return the length of every key, shared with the parent."""
        return self._parent.arity
