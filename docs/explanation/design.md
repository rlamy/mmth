# Design of Dispatch

The rules themselves are in [Dispatch rules](../reference/dispatch.md).
This page discusses why they are what they are.

## Multiple dispatch

A method call in Python picks its implementation from the class of one
object, the receiver. Multiple dispatch, as in Julia, picks it from the
classes of all the dispatched arguments together. An operation on two
values, like `add(a, b)` or `collide(ship, asteroid)`, then belongs to
neither class: it's a function with one implementation per combination of
argument types, and either side can be extended without modifying the
other.

## Specificity

With a single argument, the matching implementations are for ancestors of
the argument's class, which its MRO puts in order, so it's tempting to take
the first.
With several arguments, there's no such order: `(Dog, Animal)` and
`(Animal, Dog)` both match `(Dog, Dog)`, and neither is more specific than
the other. Specificity is only a partial order, so a call can have several
best matches.

mmth raises `AmbiguousMatchError` then, rather than guessing, and applies
the same rule with one argument as with several. So, unlike
`functools.singledispatch`, it doesn't use the MRO to break ties between
unrelated base classes: the order of a class's bases is set by its
definition, for reasons unrelated to the multimethod, and a later change
to it would silently change which implementation runs. The error lists the
candidates and the signature to register, which makes the choice explicit
(see [Resolve ambiguities](../how-to/ambiguities.md)).

## The default

The default is registered for `object` at every dispatched parameter,
whatever its annotations, as in `functools.singledispatch`: it's what runs
when nothing more specific does, so it must accept anything. Its
annotations still matter to type checkers, which check calls against the
default's signature (see [Static typing](../reference/typing.md)).

Where there's no sensible fallback, a stub declares the same name,
signature and type without registering anything, so unmatched calls raise
`NoMatchError` rather than run a placeholder.

## Runtime types

Dispatch reads `arg.__class__` rather than `type(arg)`: they only differ
for proxies, which set `__class__` to the class they stand in for, like
`Mock(spec=SomeClass)`, and should dispatch as that class.

Matching uses `issubclass`, so ABCs work as registered types, with their
virtual and structural subclasses. That makes the result of a lookup
depend on more than the registry, which the cache has to account for (see
[Performance](performance.md)).

Only annotations that stand for classes can be dispatched on.
A parameterized generic like `list[int]` would need checking each element
of the argument, and `Literal[...]` its value, so they raise `TypeError`
rather than be silently treated as `list` or ignored.

## Detecting ambiguities

`detect_ambiguities()` finds ambiguities without a call: for each pair of
signatures where neither is more specialized than the other, it tries the
most general types that match both. At each position, that's the more
specialized of their two types, or for unrelated classes, their common
subclasses, found through `__subclasses__()`.

So it only knows about classes that exist when it's called. It doesn't
know about virtual or structural subclasses of an ABC either:
`__subclasses__()` doesn't list them, and nothing else can enumerate
classes that would satisfy `__subclasshook__`.

## What isn't dispatched on

- **Return annotations**: they describe what an implementation returns,
  not which arguments it accepts.
- **Variadic arguments**: every signature has the multimethod's arity, and
  positional arguments past it are passed on to the implementation, so a
  default can take `*args`, given an explicit `arity`.
- **Keyword arguments**: those named after the default's dispatched
  parameters are dispatched on, and passed on positionally, so that a call
  means the same either way; others are only passed on.
- **Names**: implementations are registered as callable objects, never
  found by naming convention, so they can all be named `_`.

## Inheritance between multimethods

A subclass's `inherit()` multimethod chains to the base's rather than
copying or modifying it: the base class and its other subclasses keep
their own behaviour, while registrations on the base still reach the
subclass. Within the chain, the base's registrations and the subclass's
compete by specificity, as if registered on one multimethod, so a
subclass can't make a call less specific than the base already made it.
