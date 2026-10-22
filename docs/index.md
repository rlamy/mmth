# mmth

A simple multiple-dispatch library for Python, inspired by Julia's multiple dispatch.

## Installation

```bash
pip install mmth
```

## Quick start

```python
from mmth import dispatch

@dispatch
def add(a: object, b: object) -> object:
    return a + b

@add.register(int, float)
def add_int_float(a: int, b: float) -> float:
    return float(a) + b

print(add(1, 2))     # 3 (int, int) -> default
print(add(1, 2.0))  # 3.0 (int, float) -> registered implementation
```

## Documentation

- **How-to guides**, for common tasks:
  [define and extend a multimethod](how-to/register.md),
  [resolve ambiguities](how-to/ambiguities.md),
  [dispatch on method arguments](how-to/methods.md),
  [override implementations in a subclass](how-to/subclasses.md),
  [migrate from `functools.singledispatch`](how-to/functools.md).
- **Reference**, for exactly what mmth does:
  [dispatch rules](reference/dispatch.md),
  [differences from `functools`](reference/functools.md),
  [static typing](reference/typing.md),
  [API](reference/api.md).
- **Explanation**, for why it does it that way:
  [design of dispatch](explanation/design.md),
  [performance](explanation/performance.md).
- [Development](development.md): dev setup, CI checks, benchmarks, building
  these docs.
