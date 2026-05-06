---
title: Attribute Lookup and Instance/Class Namespaces
slug: attribute-lookup
source: python-programming-basics-long-fo
confidence: high
tags: [python, oop, descriptors, namespaces, lookup]
---

# Attribute Lookup and Instance/Class Namespaces

## Overview

In Python, attributes are resolved by a well-defined lookup algorithm over multiple namespaces with descriptor hooks. Understanding instance and class namespaces, method binding, descriptor precedence, and special hooks (`__getattribute__`, `__getattr__`, `__setattr__`, `__delattr__`) is essential for correct object-oriented design, debugging, and framework development.

Core facts:
- An instance typically stores per-object state in `obj.__dict__` (unless restricted by `__slots__`).
- A class stores attributes in `cls.__dict__` (exposed as a read-only `mappingproxy`).
- Attribute lookup on instances prioritizes data descriptors, then the instance dictionary, then class attributes and non-data descriptors, finally `__getattr__`.
- Functions defined on a class are non-data descriptors; accessed via an instance they produce a bound method.
- Class vs instance attributes differ in lifetime and sharing; mutating a shared mutable class attribute affects all instances.

## Namespaces: Where attributes live

- Instance namespace
  - Default storage: `obj.__dict__` (a per-instance mutable dict).
  - Contains per-instance attributes assigned after construction (e.g., in `__init__`).
  - Absent if the class defines `__slots__` without `"__dict__"`; then storage is via slot descriptors.

- Class namespace
  - Storage: `cls.__dict__` (a `mappingproxy` exposing class definitions).
  - Holds class attributes, methods (functions), descriptors (`property`, custom), and special methods.
  - Inheritance: attribute lookup consults the Method Resolution Order (MRO): `obj.__class__.__mro__` for instances; for classes, `cls.__mro__`.

- Metaclass namespace (advanced)
  - A class object is itself an instance of its metaclass. Class attribute lookup can involve the metaclass and its MRO (rarely needed in ordinary code).

## Class vs instance attributes

- Class attribute
  - Defined on the class body; shared across all instances unless shadowed.
  - Example:
    ```python
    class Dog:
        species = "Canis familiaris"  # class attribute

        def __init__(self, name):
            self.name = name          # instance attribute
    ```
- Instance attribute
  - Bound to a specific object; usually set in `__init__` or later.

- Shadowing and assignment semantics
  - Reading: if an instance lacks a given attribute, lookup falls back to the class (and bases).
  - Writing via instance: `obj.attr = value` creates/updates an instance attribute (does not mutate the class attribute) unless a data descriptor intercepts the assignment.
  - Mutable class attribute pitfall:
    ```python
    class Bad:
        items = []  # shared across all instances

    a, b = Bad(), Bad()
    a.items.append("x")
    assert b.items == ["x"]  # shared
    ```
    Prefer per-instance mutable state:
    ```python
    class Good:
        def __init__(self):
            self.items = []  # independent per-instance
    ```

## The attribute lookup algorithm (instances)

Given `obj.name`, the default `object.__getattribute__` performs:

1. Check for a data descriptor named `name` on `type(obj)` or its bases (a descriptor defining `__set__` or `__delete__`):
   - If found, return `descriptor.__get__(obj, type(obj))`.
2. Else, check the instance dictionary:
   - If `name in obj.__dict__`, return `obj.__dict__[name]`.
3. Else, look in `type(obj)` and its MRO for a class attribute or a non-data descriptor:
   - If a non-data descriptor (defines `__get__` only), return `descriptor.__get__(obj, type(obj))`.
   - Otherwise, return the class attribute value.
4. Else, if `obj.__getattr__` is defined, call `obj.__getattr__(name)` as a fallback.
5. Otherwise, raise `AttributeError`.

Notes:
- Data descriptors take precedence over the instance dictionary.
- Non-data descriptors are overridden by an instance attribute of the same name.
- The class and its bases are searched in MRO order: `type(obj).__mro__`.

## Attribute assignment and deletion (instances)

- Assignment `obj.name = value`:
  - If a data descriptor `name` exists on the class/bases (i.e., defines `__set__`), it is called: `descriptor.__set__(obj, value)`.
  - Else, if `__setattr__` is overridden, it runs and should delegate to `super().__setattr__`.
  - Else, `value` is stored in `obj.__dict__` (unless `__slots__` restricts storage).

- Deletion `del obj.name`:
  - If a data descriptor defines `__delete__`, invoke it.
  - Else, if `__delattr__` is overridden, it runs and should delegate to `super().__delattr__`.
  - Else, remove from `obj.__dict__` or raise `AttributeError`.

- `__slots__`
  - Declaring `__slots__ = (...)` creates per-slot data descriptors on the class, removes the per-instance `__dict__` by default, and restricts allowable attributes to defined slots (plus optional `"__weakref__"` and `"__dict__"` if included).
  - Slots reduce memory and prevent arbitrary attributes; they complicate inheritance and pickling; use when warranted.

## Descriptors, properties, and methods

- Descriptor protocol
  - An object on the class defining any of:
    - `__get__(self, obj, objtype=None)`
    - `__set__(self, obj, value)`
    - `__delete__(self, obj)`
  - Data descriptor: defines `__set__` or `__delete__` (wins over instance dict).
  - Non-data descriptor: defines only `__get__` (loses to instance dict).

- `property` is a descriptor
  - Read-only property: still a data descriptor; assignment to the attribute attempts `__set__` and raises if no setter is defined.
  - Example:
    ```python
    class Temperature:
        def __init__(self, c):
            self._c = c

        @property
        def celsius(self):
            return self._c

        @celsius.setter
        def celsius(self, value):
            if value < -273.15:
                raise ValueError("below absolute zero")
            self._c = value
    ```

- Functions and bound methods
  - Functions defined in a class are non-data descriptors. Access via instance binds `self`:
    ```python
    class Greeter:
        def greet(self):
            return "hello"

    obj = Greeter()
    assert obj.greet() == "hello"          # bound method: Greeter.greet(obj)
    assert Greeter.greet is Greeter.__dict__["greet"]
    ```
  - Per-instance method override via attribute assignment shadows the non-data descriptor:
    ```python
    import types

    def alt(self): return "hi"
    obj.greet = types.MethodType(alt, obj)  # bind explicitly
    assert obj.greet() == "hi"
    ```
    Assigning a plain function without binding will not auto-insert `self`.

- Custom descriptors
  - Reusable validation or computed fields:
    ```python
    class Positive:
        def __set_name__(self, owner, name):
            self._name = "_" + name
        def __get__(self, obj, objtype=None):
            return getattr(obj, self._name)
        def __set__(self, obj, value):
            if value <= 0: raise ValueError("must be positive")
            setattr(obj, self._name, value)

    class Product:
        price = Positive()
        def __init__(self, price): self.price = price
    ```

## Special hooks that intercept attribute operations

- `__getattribute__(self, name)`
  - Called for every attribute access on instances.
  - Must delegate to `super().__getattribute__(name)` (or `object.__getattribute__`) to avoid infinite recursion.
  - Use sparingly for logging, proxies, or virtualization layers.

- `__getattr__(self, name)`
  - Called only if normal lookup fails (fallback).
  - Useful for dynamic or lazy attributes, and compatibility shims.

- `__setattr__(self, name, value)`
  - Intercepts all assignments. Delegate to `super().__setattr__(name, value)` (or `object.__setattr__`).

- `__delattr__(self, name)`
  - Intercepts deletions. Delegate appropriately.

## Attribute lookup on classes

- `cls.attr` uses the same conceptual mechanism with `type(cls)` (the metaclass) as the "owner" and consults `cls.__mro__` for class-level attributes.
- Descriptors accessed via class receive `obj=None` in `__get__(obj, objtype)`. Many descriptors (e.g., `property`) return themselves when accessed on the class.

## MRO and inheritance effects

- Lookup across bases follows the MRO:
  ```python
  class A: ...
  class B(A): ...
  class C(B): ...
  assert C.__mro__ == (C, B, A, object)
  ```
- Descriptors and class attributes in the first occurrence along MRO win at their respective precedence stage (data descriptor before instance, non-data/class after instance).

## Naming conventions and name mangling

- Single leading underscore `_attr`: “internal” by convention.
- Double leading underscore in class scope triggers name mangling to avoid accidental overrides in subclasses:
  ```python
  class Example:
      def __init__(self): self.__hidden = 1
  assert "_Example__hidden" in Example.__dict__ or in obj.__dict__
  ```
- Mangling is not security; it is a compile-time renaming to reduce collisions.

## Introspection and utilities

- Inspect instance and class dictionaries:
  ```python
  vars(obj)           # instance dict (if available)
  Example.__dict__    # mappingproxy for class dict
  ```
- Test for attribute presence carefully:
  - `hasattr(obj, "name")` returns False if lookup raises `AttributeError` anywhere in the chain (including inside descriptors).
  - `getattr(obj, "name", default)` queries with fallback.

## Common pitfalls and patterns

- Mutable class attributes shared across instances; prefer per-instance state.
- Read-only `property` prevents instance-level shadowing because it is a data descriptor whose `__set__` raises.
- Overriding methods per-instance requires explicit binding (`types.MethodType`), or you get a plain function without `self`.
- Overusing `__getattribute__`/`__setattr__` leads to fragile code; prefer descriptors or properties for focused behavior.
- With `__slots__`, unknown attribute assignment raises `AttributeError`; include `"__dict__"` in slots to allow dynamic attributes if needed.

## Examples

Shadowing non-data descriptor (method) with per-instance override:
```python
import types

class C:
    def f(self): return "class"

c = C()
assert c.f() == "class"

def alt(self): return "instance"
c.f = types.MethodType(alt, c)
assert c.f() == "instance"   # shadows non-data descriptor
```

Data descriptor precedence over instance dictionary:
```python
class D:
    @property
    def x(self): return 10

d = D()
d.__dict__["x"] = 99
assert d.x == 10              # property (data descriptor) wins
```

Assignment to read-only property raises:
```python
class E:
    @property
    def name(self): return "ro"

e = E()
try:
    e.name = "x"
except AttributeError:
    pass
```

Basic lookup tracing via explicit checks:
```python
def has_instance_attr(obj, name): return hasattr(obj, "__dict__") and name in obj.__dict__
def has_class_attr(obj, name): return any(name in cls.__dict__ for cls in type(obj).__mro__)
```

## Key Points

- Instance attribute lookup order: data descriptor on class → instance `__dict__` → class/non-data descriptor via MRO → `__getattr__` → `AttributeError`.
- Assignment via instance stores in the instance dictionary unless intercepted by a data descriptor (`__set__`) or `__setattr__`; deletion similarly.
- Functions on a class are non-data descriptors; via instance they bind `self`. Properties are data descriptors and prevent instance shadowing.
- Class attributes are shared; mutating a shared mutable object affects all instances. Use per-instance state for mutables.
- `__slots__` replaces `__dict__` storage with slot descriptors, constraining attributes and altering assignment behavior.