"""A mapping keyed by tuples of types, looked up by subclass."""

import weakref
from abc import get_cache_token
from collections.abc import Iterator, MutableMapping
from typing import Any, Callable, Self

_Signature = tuple[type, ...]
_MISSING: Any = object()


class NoMatchError(TypeError):
    """Raised by `TypeMap.lookup()` when no key matches and there's no default."""


class AmbiguousMatchError(TypeError):
    """Raised by `TypeMap.lookup()` when no matching key is the most specific."""


class TypeMap(MutableMapping[_Signature, Any]):
    """A mapping keyed by tuples of types, with lookups that match subclasses.

    As a mapping, it only holds its own keys, matched exactly. `lookup()`
    looks up the value of the most specific key that a tuple of types
    matches position by position, each a subclass of the key's type, else
    the default; an exact key is always the most specific. With a parent
    type map, it looks among the keys `parent | self`. It caches its results.
    """

    # Slots, since `lookup()` is performance-critical (see
    # docs/performance.md).
    __slots__ = (
        "_table",
        "_cache",
        "_abc_token",
        "_parent",
        "_children",
        "_default",
        "_adapt",
        "__weakref__",
    )

    # Formatted with `types`; a subclass can reword them for its own domain.
    _no_match_message = "No key matches types {types}"
    _ambiguous_message = "Ambiguous lookup for types {types}: matches several keys"

    def __init__(
        self,
        parent: "TypeMap | None" = None,
        *,
        default: Any = _MISSING,
        adapt: Callable[[Any], Any] | None = None,
    ) -> None:
        """Create an empty type map, inheriting `parent`'s keys in `lookup()`.

        `lookup()` looks among the keys `parent | self`, and returns `default`
        when no key matches (or the nearest ancestor's default, if not given),
        and passes whatever it finds through `adapt`, if given. Since
        `lookup()` caches by the types looked up, not by the key they matched,
        `adapt` runs once per distinct looked-up types: `list` and `tuple`
        both matching `(Sequence,)` get separately adapted values.
        """
        self._table: dict[_Signature, Any] = {}
        self._cache: dict[type | _Signature, Any] = {}
        # Set once an ABC is registered, since `SomeABC.register(cls)` can
        # change `issubclass` results after they were cached.
        self._abc_token: object | None = None
        self._parent = parent
        self._children: list[weakref.ReferenceType[TypeMap]] = []
        if default is _MISSING and parent is not None:
            default = parent._default
        self._default = default
        self._adapt = adapt
        if parent is not None:
            parent._children.append(weakref.ref(self))
            if parent._abc_token is not None:
                self._watch_abc_cache()

    def _live_children(self) -> list["TypeMap"]:
        """Return this type map's live children, pruning dead references."""
        alive_refs = []
        children = []
        for ref in self._children:
            child = ref()
            if child is not None:
                alive_refs.append(ref)
                children.append(child)
        self._children = alive_refs
        return children

    def _watch_abc_cache(self) -> None:
        self._abc_token = get_cache_token()
        for child in self._live_children():
            child._watch_abc_cache()

    def _invalidate_cache(self) -> None:
        self._cache.clear()
        for child in self._live_children():
            child._invalidate_cache()

    @staticmethod
    def _is_more_specialized(sig_a: _Signature, sig_b: _Signature) -> bool:
        """Return whether `sig_a` is strictly more specialized than `sig_b`."""
        return sig_a != sig_b and all(map(issubclass, sig_a, sig_b))

    @staticmethod
    def _match_signature(sig: _Signature, types: _Signature) -> bool:
        return len(sig) == len(types) and all(
            isinstance(sig_type, type) and issubclass(arg_type, sig_type)
            for sig_type, arg_type in zip(sig, types)
        )

    def _merged_table(self) -> dict[_Signature, Any]:
        """Return `parent | self`, recursively, as a dict."""
        if self._parent is None:
            return self._table
        return self._parent._merged_table() | self._table

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
        table = self._merged_table()
        try:
            value = table[types]
        except KeyError:
            value = self._find_most_specialized(table, types)
        if value is _MISSING:
            value = self._default
        if value is _MISSING:
            raise NoMatchError(self._no_match_message.format(types=types))
        return value if self._adapt is None else self._adapt(value)

    def __getitem__(self, sig: _Signature) -> Any:
        """Return the value stored under exactly the key `sig`."""
        return self._table[sig]

    def __setitem__(self, sig: _Signature, value: Any) -> None:
        """Store `value` under exactly the key `sig`."""
        self._table[sig] = value
        if self._abc_token is None and any(
            hasattr(t, "__abstractmethods__") for t in sig
        ):
            self._watch_abc_cache()
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

    def __copy__(self) -> Self:
        """Return a type map with the same keys, parent, default and adapt.

        The copy is independent: changing either one leaves the other as is,
        and it doesn't share this one's children.
        """
        new = type(self)(self._parent, default=self._default, adapt=self._adapt)
        new._table = self._table.copy()
        if self._abc_token is not None:
            new._watch_abc_cache()
        return new

    def lookup(self, key: type | _Signature) -> Any:
        """Return the value for the most specific key the types `key` match.

        `key` is a tuple of types, or a bare type for a one-element tuple.
        Raise `NoMatchError` if no key matches and there's no default, and
        `AmbiguousMatchError` if no single matching key is more specific than
        all the others. The result is cached, per `key`, until this type map or one
        of its ancestors changes.
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
