# Specification

## Syntax

### 1. Define Multimethod (Main Syntax)

```python
@dispatch
def function_name(arg1: Type1, arg2: Type2, ...) -> ReturnType:
    """Default implementation"""
    ...
```

### 2. Register an Implementation (Main Syntax)

```python
@function_name.register(Type1, Type2, ...)
def function_name_impl(arg1: Type1, arg2: Type2, ...) -> ReturnType:
    """Implementation for (Type1, Type2, ...)"""
    ...
```

### 3. Register an Implementation (Metaprogramming)

```python
# Direct assignment
function_name[Type1, Type2] = implementation_callable

# Or with a function definition
def custom_impl(arg1: Type1, arg2: Type2) -> ReturnType:
    ...

function_name[Type1, Type2] = custom_impl
```

### 4. Access an Implementation

```python
impl = function_name[Type1, Type2]  # Returns registered callable or raises KeyError
```

## Semantics

### Dispatch Algorithm

When `function_name(arg1, arg2, ...)` is called:

1. **Collect runtime types**: `(type(arg1), type(arg2), ...)`

2. **Exact match**: If `(Type1, Type2, ...)` exists in registry, call that implementation

3. **Find all applicable signatures**: All registered signatures where each runtime type is a subclass of the registered type

4. **Select most specialized**:
   - A signature A is **more specialized** than B if all its type parameters are subclasses of B's corresponding parameters
   - If neither A nor B is more specialized than the other → **ambiguity error**
   - If A beats B but not vice versa → A wins
   - Exact match beats inheritance match

5. **Fallback**:
   - If no registered signature matches → call the default implementation
     (the function decorated with `@dispatch`), whatever the argument types
   - If there is no default (a bare `Multimethod()`) → raise `TypeError`

### Registration Methods

| Method | Syntax | Returns |
|--------|--------|---------|
| `.register(*types)` | `@func.register(int, str)` | Decorator |
| `__setitem__` | `func[int, str] = impl` | `None` |
| `__getitem__` | `impl = func[int, str]` | Registered callable or raises `KeyError` |

### Type Matching Rules

- **Exact types**: `int` matches `int` only
- **Subclass types**: `Animal` matches `Dog` if `Dog` is subclass of `Animal`
- **Single type shorthand**: `func[int]` is equivalent to `func[(int,)]`

## Examples

### Basic Usage

```python
@dispatch
def add(a: int, b: int) -> int:
    return a + b

@add.register(int, float)
def add_int_float(a: int, b: float) -> float:
    return float(a) + b

print(add(1, 2))     # 3 (int, int) -> default
print(add(1, 2.0))  # 3.0 (int, float) -> registered implementation
```

### Metaprogramming

```python
@dispatch
def process(data: str) -> str:
    return data.upper()

def json_handler(data: dict) -> str:
    import json
    return json.dumps(data)

# Register via assignment
process[dict] = json_handler

# Access an implementation
handler = process[dict]
print(handler({"key": "value"}))  # {"key": "value"}
```

### Inheritance Dispatch

```python
class Animal:
    pass

class Dog(Animal):
    pass

class Cat(Animal):
    pass

@dispatch
def make_sound(animal: Animal) -> str:
    return "..."

@make_sound.register(Dog)
def _(dog: Dog) -> str:
    return "Woof!"

@make_sound.register(Cat)
def _(cat: Cat) -> str:
    return "Meow!"

print(make_sound(Dog()))  # Woof!
print(make_sound(Cat()))  # Meow!
```

### Ambiguity Detection

```python
class Animal:
    pass

class Dog(Animal):
    pass

@dispatch
def f(a: Animal, b: Animal) -> str:
    return "Animal, Animal"

@f.register(Dog, Animal)
def _(d: Dog, a: Animal) -> str:
    return "Dog, Animal"

@f.register(Animal, Dog)
def _(a: Animal, d: Dog) -> str:
    return "Animal, Dog"

# ERROR: Ambiguous - neither is more specialized than the other
f(Dog(), Dog())
# TypeError: Ambiguous dispatch for types (Dog, Dog): matches multiple signatures
```

## Error Cases

```python
@dispatch
def foo(a: int) -> int:
    return a

# KeyError - no implementation registered for exactly these types
foo[float]  # KeyError: "No implementation registered for (<class 'float'>,)"

# TypeError - no matching implementation and no default to fall back to
bar = Multimethod()

@bar.register(int)
def _(a: int) -> int:
    return a * 2

bar("str")  # TypeError: "No matching implementation for types (<class 'str'>,)"
```

## Design Decisions

1. **Return type annotations**: Not used in dispatch matching
2. **Variadic arguments**: Not supported
3. **Keyword arguments**: Not used in dispatch (treated as fallback)
4. **Callable references**: Registration requires explicit callable object, not name matching
