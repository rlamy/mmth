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
def add(a: int, b: int) -> int:
    return a + b

@add.register(int, float)
def add_int_float(a: int, b: float) -> float:
    return float(a) + b

print(add(1, 2))     # 3 (int, int) -> default
print(add(1, 2.0))  # 3.0 (int, float) -> specialized
```

## Where next

- [Specification](specification.md): syntax, dispatch semantics, examples and error cases
- [Methods](methods.md): `dispatchmethod` and overriding cases in subclasses
- [Performance](performance.md): resolution caching and benchmarks
- [API reference](reference.md)
- [Development](development.md): dev setup, CI checks, building these docs
