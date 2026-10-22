# Differences from `functools.singledispatch`

With a single dispatched argument, `dispatch` and `dispatchmethod` behave
like `functools.singledispatch` and `functools.singledispatchmethod`, except
as listed here (see also [Migrate from functools](../how-to/functools.md)):

- **Ties raise instead of following the MRO**: given `class C(A, B)` with
  implementations for both `A` and `B`, functools picks `A` (first in
  `C.__mro__`), while mmth raises `AmbiguousMatchError`, listing both. The
  same applies to a real base class against an unrelated ABC that `C`
  implicitly satisfies. (Where functools does raise on ambiguity between
  ABCs, it raises `RuntimeError`; mmth raises `AmbiguousMatchError`.)
- **`Any` means `object`**: functools treats it as a class that nothing is
  an instance of, so an implementation registered for `Any` never runs.
- **Looking a `dispatchmethod` up on the class**: `Class.method(obj, arg)`
  dispatches on `arg`, skipping `obj` as it would `self`, while functools
  dispatches on `obj` before Python 3.15 (from 3.15, it matches mmth). So
  a `classmethod`/`staticmethod` implementation of an ordinary
  `dispatchmethod` can only be called through an instance; a
  `dispatchmethod` that is itself a `classmethod`/`staticmethod` works
  through either, as in functools.
- **`register(Type, SomeClass)` reads the class as a type**, as it does
  any other type, so with one dispatched argument it raises `TypeError`,
  suggesting `func=SomeClass`; functools registers the class as the
  implementation.
- **`dispatch` on a method**: functools binds the function to the instance
  and dispatches on `self`. A `dispatch` multimethod isn't bound, so as a
  class attribute it works as a static function; one whose default takes
  `self` raises `TypeError` when the class is created, pointing to
  `dispatchmethod` (wrapped in a `RuntimeError` on Python 3.11 and PyPy
  3.11, as for `inherit()`; see
  [Methods and Inheritance](dispatch.md#methods-and-inheritance)).
- **Dispatched arguments by keyword**: `f(x=1)` dispatches on `x`, named
  as in the default; functools raises `TypeError`, as it requires the
  dispatched argument to be positional.
- **Replacing an implementation warns**: registering a different one for
  a signature already registered warns with `RedefinitionWarning`, where
  functools replaces it silently.
- **`classmethod`/`staticmethod` implementations are stored adapted**:
  `registry` and `func[types]` hold a plain function that takes the
  multimethod's own arguments, not the `classmethod`/`staticmethod` object
  functools keeps.

