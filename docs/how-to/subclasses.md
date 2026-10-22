# Override Implementations in a Subclass

A subclass can override some implementations of a base class's
`dispatchmethod` without touching the base class itself, or its other
subclasses. This guide continues the `Evaluator` example from
[Dispatch on method arguments](methods.md#replace-the-visitor-pattern).

## Override with `inherit()`

Assign `inherit()` as the subclass's own attribute, under the name the base
class uses, then register on it as on any `dispatchmethod`:

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

Inside the implementation, `super().visit(...)` calls the base class's
multimethod, as for any overridden method. `StrictEvaluator` keeps the
base's implementations for every other type, such as `Add`.

A registration for the same types as the base's replaces it, without a
`RedefinitionWarning`. Otherwise, the most specific implementation wins,
whichever class registered it: registering a broader type than the base
did doesn't override the base's more specific registration, and can make
a call ambiguous (see [Resolve ambiguities](ambiguities.md)).

## Name the base multimethod explicitly

If the attribute name differs from the base's, or the multimethod to
extend isn't the one attribute lookup on the bases would find, call
`inherit()` on it instead:

```python
class LoggingEvaluator(Evaluator):
    evaluate = Evaluator.visit.inherit()

    @evaluate.register(Add)
    def _(self, node):
        print("adding")
        return self.evaluate(node.left) + self.evaluate(node.right)
```

## Find errors in registrations

A bare `inherit()` only finds its base multimethod when the class statement
ends, so mistakes in its registrations, like a missing annotation, are
raised there rather than at the `register()` line. On Python 3.11 and
PyPy 3.11 they arrive wrapped in a `RuntimeError`: look at its
`__cause__`. `Base.visit.inherit()` registers at once, so its errors
aren't delayed or wrapped. See
[Dispatch rules](../reference/dispatch.md#methods-and-inheritance).
