---
title: Dunder Methods and Language Protocols
slug: dunder-methods-and-protocols
source: python-programming-basics-long-fo
confidence: high
tags: ["python", "data model", "dunder methods", "protocols", "descriptors"]
---

# Dunder Methods and Language Protocols

Dunder (double-underscore) methods are special methods that implement Python’s language protocols: they connect syntax (len(x), a + b, for x in y, with x, await x, x[y]) and built-ins to object behavior. They are looked up primarily on the type (class), not the instance, and they compose with attribute access rules, descriptors, inheritance, and metaclasses to form Python’s data model. Do not invent your own dunder names; use only those defined by the language protocols.

## Data model and special method lookup

- Special methods underlie Python syntax:
  - len(obj) → obj.__len__()
  - obj[key] → obj.__getitem__(key)
  - for x in obj → iteration protocol (__iter__ / __next__)
  - a + b → __add__ (and reflected/in-place variants)
  - with obj → context manager protocol (__enter__, __exit__)
  - await obj → awaitable protocol
- Lookup is primarily on the type:
  - Assigning a dunder method on a single instance usually does not affect syntax; define on the class.
- Attribute lookup order (simplified):
  - Data descriptor on the class (defines __set__ or __delete__) → instance dict → non-data descriptor/class attribute → __getattr__ fallback; __getattribute__ intercepts all attribute access.
- Functions in classes are non-data descriptors:
  - Access via instance returns a bound method (inserts self) through the descriptor’s __get__.

## Construction, initialization, and representation

- __new__(cls, …) creates the instance; __init__(self, …) initializes it. Use __new__ for immutable subclasses or allocation control; most classes only need __init__.
- __repr__(self) → developer-oriented, unambiguous representation (ideally evaluatable form).
- __str__(self) → user-oriented string; falls back to __repr__ if not defined.

Example:
```python
class Point:
    def __new__(cls, x, y):
        return super().__new__(cls)
    def __init__(self, x, y):
        self.x, self.y = x, y
    def __repr__(self):
        return f"Point({self.x!r}, {self.y!r})"
    def __str__(self):
        return f"{self.x},{self.y}"
```

## Comparison, ordering, hashing, truth

- Equality and ordering:
  - Implement __eq__ (and optionally ordering via __lt__/__le__/__gt__/__ge__). Return NotImplemented for unsupported operand types to allow fallbacks/reflection.
  - functools.total_ordering can fill in ordering methods given __eq__ and one ordering operator.
- Hashing:
  - If two objects compare equal, their hashes must be equal. Do not hash mutable state that can change while in dict/set.
- Truthiness:
  - __bool__(self) controls truth value; if absent, bool(x) falls back to __len__()>0. Common falsy: False, None, 0, 0.0, "", [], {}, set(), ().
- Best practices:
  - For simple data objects, prefer dataclasses to auto-generate __init__, __repr__, __eq__, and optionally ordering/hash.

Example:
```python
from functools import total_ordering

@total_ordering
class Version:
    def __init__(self, major, minor):
        self.major, self.minor = major, minor
    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor) == (other.major, other.minor)
    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor) < (other.major, other.minor)
    def __hash__(self):
        return hash((self.major, self.minor))
```

## Containers and iteration

- Container/sequence protocol (commonly implemented together):
  - __len__(self) → non-negative int length.
  - __contains__(self, item) → membership test for in/not in.
  - __iter__(self) → iterator; for x in obj consumes the iterator.
  - __getitem__(self, key) → item/slice access (used by x[y]).
- Iterator protocol:
  - An iterator defines __iter__(self) → self and __next__(self) → next value or raises StopIteration when exhausted.
- Typical container scaffold:
```python
class Bag:
    def __init__(self, items):
        self._items = list(items)
    def __len__(self):
        return len(self._items)
    def __contains__(self, item):
        return item in self._items
    def __iter__(self):
        return iter(self._items)
```

## Numeric and operator overloading

- Binary operators: __add__, __sub__, __mul__, … with reflected versions __radd__, … and in-place versions __iadd__, …
- Return NotImplemented for unsupported operand types; Python will try reflected methods or raise TypeError.
- Overload operators only when meaning is natural and unsurprising; keep invariants clear.

Example:
```python
class Vector:
    def __init__(self, x, y):
        self.x, self.y = x, y
    def __add__(self, other):
        if not isinstance(other, Vector):
            return NotImplemented
        return Vector(self.x + other.x, self.y + other.y)
    def __repr__(self):
        return f"Vector({self.x!r}, {self.y!r})"
```

## Callables

- __call__(self, …) makes instances behave like functions; useful for stateful callables and strategies.

Example:
```python
class Multiplier:
    def __init__(self, factor): self.factor = factor
    def __call__(self, value):  return value * self.factor

double = Multiplier(2)
double(5)  # 10
```

## Context managers

- with obj: calls obj.__enter__() → value bound by as; then obj.__exit__(exc_type, exc, tb) on block exit.
- __exit__ returning True suppresses the exception; use suppression sparingly and deliberately.

Example:
```python
class Managed:
    def __enter__(self): print("enter"); return self
    def __exit__(self, exc_type, exc, tb): print("exit"); return False

with Managed() as m:
    pass
```

## Async protocols

- Async context manager: async with uses __aenter__ / __aexit__.
- Async iteration: async for uses __aiter__ / __anext__ (raises StopAsyncIteration to end).
- Awaitable: await obj uses the awaitable protocol (typically via coroutines; details are version-specific; see asyncio docs).

Example:
```python
class AsyncResource:
    async def __aenter__(self): print("open"); return self
    async def __aexit__(self, exc_type, exc, tb): print("close")

class AsyncCounter:
    def __init__(self, n): self.n = n; self.i = 0
    def __aiter__(self): return self
    async def __anext__(self):
        if self.i >= self.n: raise StopAsyncIteration
        self.i += 1
        return self.i
```

## Attribute access and descriptors

- Interception hooks:
  - __getattribute__(self, name): called for all attribute access. Use super().__getattribute__ to avoid infinite recursion.
  - __getattr__(self, name): fallback when normal lookup fails (define dynamic/default attributes).
  - __setattr__(self, name, value): intercept assignment; use super().__setattr__ or object.__setattr__ to assign.
  - __delattr__(self, name): intercept deletion.
- Descriptors: objects defining any of __get__, __set__, __delete__; control attribute access on owner classes.
  - Data descriptors (define __set__ or __delete__) override instance dict.
  - Non-data descriptors (only __get__) can be shadowed by instance attributes.
  - __set_name__(self, owner, name): called at class creation to learn the attribute’s name.
- Properties are descriptors created by @property; functions in classes are non-data descriptors that bind methods.

Example data descriptor with validation:
```python
class Positive:
    def __set_name__(self, owner, name):
        self._name = "_" + name
    def __get__(self, obj, objtype=None):
        if obj is None: return self
        return getattr(obj, self._name)
    def __set__(self, obj, value):
        if value <= 0: raise ValueError("must be positive")
        setattr(obj, self._name, value)

class Product:
    price = Positive()
    def __init__(self, price): self.price = price
```

## Class creation and subclass hooks

- Metaclasses (subclasses of type) can customize class creation:
  - __prepare__(mcls, name, bases) → namespace mapping used to execute the class body.
  - __new__/__init__ on the metaclass finalize the class object (e.g., inject attributes).
- __init_subclass__(cls, **kwargs) runs when a subclass is created; preferred for lightweight registries and consistency checks without a full metaclass.
- Class decorators modify a class object after creation; often simpler than metaclasses for small transformations.

Example __init_subclass__ registry:
```python
class PluginBase:
    registry = {}
    def __init_subclass__(cls, plugin_name=None, **kw):
        super().__init_subclass__(**kw)
        if plugin_name is not None:
            PluginBase.registry[plugin_name] = cls

class CsvPlugin(PluginBase, plugin_name="csv"):
    pass
```

## Module-level dunders

- __name__: equals "__main__" when a module is executed directly (pattern for script entry points).
- __all__: list of public names for from module import * and for documenting intended exports; not a security boundary.

Example:
```python
def main(): ...
if __name__ == "__main__":
    main()
```

## Best practices and pitfalls

- Define special methods on the class; avoid per-instance dunder assignment for protocol behavior.
- Return NotImplemented in binary operators and comparisons for unsupported operand types; do not raise TypeError unless appropriate.
- Keep __repr__ developer-focused and __str__ user-focused; prefer dataclasses for simple records.
- Ensure hashing and equality are consistent; avoid hashing mutable state.
- Implement __len__ to return a non-negative int; __bool__ should be cheap and intuitive.
- Avoid heavy logic or I/O in import-time code; keep __init__.py lightweight.
- Prefer __init_subclass__, class decorators, or descriptors before metaclasses unless the use case truly demands metaclass control.
- Use context managers to guarantee cleanup; avoid __del__ for resource management due to subtle lifecycle semantics.
- Do not invent nonstandard “dunder” names.

## Reference examples

Equality with NotImplemented:
```python
class Point:
    def __init__(self, x, y): self.x, self.y = x, y
    def __eq__(self, other):
        if not isinstance(other, Point):
            return NotImplemented
        return (self.x, self.y) == (other.x, other.y)
```

Context manager with suppression (rarely appropriate):
```python
class SuppressValueError:
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        return exc_type is ValueError  # suppress ValueError only
```

Attribute interception (safe pattern):
```python
class Logged:
    def __setattr__(self, name, value):
        print(f"setting {name}={value!r}")
        super().__setattr__(name, value)
    def __getattribute__(self, name):
        print(f"getting {name}")
        return super().__getattribute__(name)
```

## Key Points

- Dunder methods implement Python’s core protocols (iteration, numeric ops, containers, context managers, async, callability, attribute access) and are looked up on the type.
- Use descriptors (including property) and subclass hooks to customize attribute/class behavior; data descriptors override instance attributes.
- Implement equality/order/hash carefully; return NotImplemented for unsupported types and keep hash consistent with equality.
- Prefer simple, predictable semantics: __repr__ for developers, __str__ for users, and operator overloading only when meaning is natural.
- Avoid inventing custom dunders; rely on standard protocols, dataclasses for data objects, and context managers for safe resource handling.