# Method Dispatch

`dispatchmethod` is `dispatch` for use on a method: `self` is bound
automatically via the descriptor protocol and excluded from dispatch, so
`.register(*types)` only needs the types of the remaining arguments. Its
`.register()` takes the same forms as a function's.

```python
from mmth import dispatchmethod

class Formatter:
    def __init__(self, indent):
        self.indent = indent

    @dispatchmethod
    def render(self, value: object) -> str:
        return repr(value)

    @render.register(str)
    def _(self, value):
        return " " * self.indent + value

    @render.register(list)
    def _(self, value):
        return "\n".join(self.render(item) for item in value)

Formatter(indent=2).render(["a", "b"])  # "  a\n  b"
```

Each instance keeps its own state (`self.indent` above), while the
implementation for a given call is still chosen by the runtime type of the
arguments, exactly like `dispatch`.

One direct application is replacing the Visitor pattern: instead of an
`accept()` method on every visited class calling back into
`visitor.visit_ElementType(...)`, a `dispatchmethod` dispatches straight on
the argument's type, so the visited classes need no changes at all:

```python
class Expr:
    pass

class Num(Expr):
    def __init__(self, value):
        self.value = value

class Add(Expr):
    def __init__(self, left, right):
        self.left = left
        self.right = right

class Evaluator:
    @dispatchmethod
    def visit(self, node: Expr):
        raise TypeError(f"no visit for {type(node).__name__}")

    @visit.register(Num)
    def _(self, node):
        return node.value

    @visit.register(Add)
    def _(self, node):
        return self.visit(node.left) + self.visit(node.right)

Evaluator().visit(Add(Num(1), Num(2)))  # 3
```

## Class and Static Methods

As with `functools.singledispatchmethod`, a registered implementation can be
a `classmethod` or `staticmethod` (applied *below* `.register()`), as can
the `dispatchmethod` itself (applied below `@dispatchmethod`):

```python
from mmth import dispatchmethod

class Negator:
    @dispatchmethod
    @classmethod
    def neg(cls, arg: object):
        raise NotImplementedError("Cannot negate a")

    @neg.register
    @classmethod
    def _(cls, arg: int):
        return -arg

    @neg.register
    @classmethod
    def _(cls, arg: bool):
        return not arg

Negator.neg(5)      # -5
Negator().neg(True)  # False
```

A `classmethod`/`staticmethod` *implementation* of an ordinary
`dispatchmethod` can only be called through an instance, though: looked up
on the class, an ordinary `dispatchmethod` takes the instance as its first
argument (`Formatter.render(formatter, value)`) rather than dispatching on
it as `functools.singledispatchmethod` would.

## Overriding One Implementation in a Subclass

A subclass can override some implementations of a base class's
`dispatchmethod` without touching the base class itself, with `inherit()`:
assign it as the subclass's own attribute (under the same name the base
class uses), then build it up with `.register(*types)` exactly like
`dispatchmethod` itself. The subclass's multimethod dispatches on the
registrations `base | subclass`: a registration for the same types
replaces the base's, and otherwise the most specific one wins, whichever
class registered it. So registering a broader
type than the base class did doesn't override the base's more specific
registration (and can make a call ambiguous, as in `dispatch`):

```python
from mmth import inherit

class StrictEvaluator(Evaluator):
    visit = inherit()

    @visit.register(Num)
    def _(self, node):
        if node.value < 0:
            raise ValueError("negative numbers not allowed")
        return super().visit(node)

Evaluator().visit(Num(-1))         # -1, unaffected
StrictEvaluator().visit(Num(-1))   # ValueError: negative numbers not allowed
```

`inherit()` finds the base multimethod itself - the same lookup `super()`
would do, walking `StrictEvaluator`'s bases for a `visit` of their own -
once Python calls `__set_name__` on it at class-creation time. `super()`
works normally inside the registered function, because it's still an
ordinary method of `StrictEvaluator`; `inherit()` only changes which
multimethod `.register()` adds it to. Every other `Evaluator` subclass, and
every other node type on `StrictEvaluator`, keeps using the base
registrations unchanged.

If the attribute name differs from the base's, or the multimethod to chain
to isn't the one plain attribute lookup would find, spell it out instead
with `Base.visit.inherit()` (see `Multimethod.inherit`) - `inherit()` is
just that, with the base found automatically for the common case.

(On Python 3.11, an error raised while resolving `inherit()` - e.g. no
base class actually defines that name - arrives wrapped in a
`RuntimeError` with the original exception as its `__cause__`, rather than
directly; this is a difference in how CPython itself handles `__set_name__`
failures across versions, not something mmth controls.)

