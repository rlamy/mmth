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
print(add(1, 2.0))  # 3.0 (int, float) -> registered implementation
```

## Documentation

Full documentation - specification, method dispatch, performance notes, API
reference and development guide - is at https://mmth.readthedocs.io. The
sources live in [`docs/`](docs/).
