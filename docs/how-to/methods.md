# Dispatch on Method Arguments

## Define a dispatching method

Use `dispatchmethod` instead of `dispatch`: `self` is bound as for any
method and excluded from dispatch, so `register()` only needs the types of
the other arguments. It takes the same forms as for a function (see
[Define and extend a multimethod](register.md)).

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
implementation for a given call is still chosen by the runtime types of
the arguments.

## Replace the Visitor pattern

Instead of an `accept()` method on every visited class calling back into
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

To change some of `visit`'s implementations in a subclass of `Evaluator`,
see [Override implementations in a subclass](subclasses.md).

## Use class and static methods

A registered implementation can be a `classmethod` or `staticmethod`
(applied *below* `.register()`), as can the `dispatchmethod` itself
(applied below `@dispatchmethod`):

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
it. Make the `dispatchmethod` itself a `classmethod` or `staticmethod` to
call it through the class.
