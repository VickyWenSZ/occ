---
title: Descriptor Protocol
slug: descriptor-protocol
source: python-programming-basics-long-fo
confidence: high
tags: [python, descriptors, object-model, attribute-lookup, property]
---

# Descriptor Protocol

## Overview
In Python, a descriptor is any object that defines one or more of the methods __get__, __set__, or __delete__ to participate in attribute access on another object. Descriptors underpin properties, methods, static methods, class methods, and super(); they are central to Python’s attribute access semantics.

A descriptor must be found on the owner’s class (or its bases) to engage the protocol; placing a descriptor instance on an object’s instance dictionary does not trigger descriptor behavior.

Core methods:
- __get__(self, obj, objtype=None) -> value
- __set__(self, obj, value) -> None
- __delete__(self, obj) -> None

Classification:
- Data descriptor: defines __set__ or __delete__ (often also __get__). Takes precedence over instance attributes.
- Non-data descriptor: defines only __get__. Yields to instance attributes of the same name.

Related hook:
- __set_name__(self, owner, name) -> None: Called at class creation, informs a descriptor of the attribute name it was assigned to. Useful for computing per-instance storage keys.

Reference: Python’s Descriptor Guide (descriptors power property, methods, staticmethod, classmethod, and super()).

## Attribute lookup and precedence
For attribute access obj.name, the effective precedence is:
1. Data descriptor on type(obj) (or its MRO): if found, use its __get__.
2. Instance dictionary: if name in obj.__dict__, return that value.
3. Non-data descriptor or plain attribute on type(obj): if a descriptor, call __get__; else return attribute.
4. Fallback to obj.__getattr__(name) if defined; otherwise raise AttributeError.

Implications:
- Data descriptors (e.g., property with a setter) override instance attributes.
- Non-data descriptors (e.g., plain functions in a class, or cached_property-like descriptors) can be shadowed by an instance attribute with the same name.
- Assignment obj.name = v is routed through object.__setattr__ which consults data descriptors: if a matching data descriptor is present on the class, its __set__ is invoked; otherwise the value is stored in obj.__dict__ (unless __setattr__ is overridden).

For class attribute access C.name:
- Lookup happens on the class, possibly invoking descriptors defined on the metaclass (type(C)); __get__ receives obj as None (typical convention is to return the descriptor itself or a class-bound value).

## Data descriptors
Data descriptors define __set__ or __delete__ and typically implement __get__ as well. Because they take precedence over instance attributes, they are ideal for validation and enforced computed attributes.

Pattern using per-instance storage via a “private” name derived in __set_name__:
```python
class Positive:
    def __set_name__(self, owner, name):
        self.private_name = f"_{name}"

    def __get__(self, obj, objtype=None):
        if obj is None:  # accessed via class
            return self
        return getattr(obj, self.private_name)

    def __set__(self, obj, value):
        if value <= 0:
            raise ValueError("value must be positive")
        setattr(obj, self.private_name, value)

class Product:
    price = Positive()
    def __init__(self, price):
        self.price = price
```
Notes:
- __set_name__ (PEP 487) avoids hard-coding attribute names.
- Storing per-instance state in the instance dictionary (via the “private” name) prevents cross-instance leakage.

Properties are data descriptors
- property objects implement descriptor methods; a property without a setter still behaves as a (read-only) data descriptor and overrides instance attributes.
- @prop.setter defines write validation logic; without it, property.__set__ raises AttributeError.

## Non-data descriptors
Non-data descriptors only define __get__. They can be cached or shadowed by instance attributes.

Example (compute-once caching pattern; see functools.cached_property for a library version):
```python
class cached:
    def __init__(self, func):
        self.func = func
    def __set_name__(self, owner, name):
        self.name = name
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        value = self.func(obj)
        obj.__dict__[self.name] = value  # shadow descriptor thereafter
        return value
```

Behavior:
- First access computes and stores the value in obj.__dict__[name].
- Subsequent accesses return the instance-stored value, since instance attributes outrank non-data descriptors.

## Functions, methods, and built-ins as descriptors
- A function defined in a class is a non-data descriptor: accessing it via an instance produces a bound method (inserting self), roughly equivalent to C.f(obj). Access via the class returns the original function object.
- classmethod and staticmethod are descriptors:
  - classmethod returns a descriptor that binds the function to the class (inserting cls).
  - staticmethod returns the underlying function without binding.
- property is a (read-only or read-write) data descriptor.
- super() relies on descriptor binding to produce methods bound to superclasses.

Example (bound method):
```python
class Greeter:
    def greet(self):
        return "hello"

g = Greeter()
Greeter.greet      # function (descriptor object)
g.greet            # bound method (self == g)
g.greet()          # "hello"
```

## Implementation and usage patterns
- Validation fields: Centralize validation and normalization (e.g., Positive above).
- Lazy attributes: Compute on first access and cache (non-data descriptor pattern; see functools.cached_property).
- Framework internals: ORMs and declarative DSLs use descriptors to define fields, relationships, and computed attributes with cross-cutting behavior.
- Cross-class reuse: One descriptor instance placed on many classes can coordinate uniform attribute behavior (be mindful of storing per-instance data; avoid storing mutable per-instance state on the descriptor object itself unless using a per-instance map such as the instance dict or a WeakKeyDictionary).

## Access via class vs instance
- A well-behaved descriptor typically returns self (the descriptor) when obj is None (i.e., attribute access through the class). This preserves discoverability and allows decorator chaining and introspection.
- For __get__ invocations through the instance, return the bound/computed value.

## Interactions with other attribute hooks
- __getattribute__(self, name) intercepts all attribute access. Use only when necessary; call super().__getattribute__(name) to participate in normal descriptor mechanics.
- __getattr__(self, name) is only invoked as a fallback after normal lookup (including descriptors) fails.
- __setattr__/__delattr__ can intercept assignment/deletion; prefer calling super().__setattr__ to avoid recursion. Data descriptor __set__/__delete__ take precedence for matching attributes on the class.

## Pitfalls and best practices
- Shared state bug: Storing per-instance values on the descriptor object itself shares that state across all instances. Instead, write to the instance (e.g., obj.__dict__[private_name]) or use a per-instance storage map.
- Shadowing non-data descriptors: Instance attributes can shadow non-data descriptors. Plan naming to avoid accidental shadowing, or prefer data descriptors when shadowing must be prevented.
- Infinite recursion in __setattr__: Always delegate to super().__setattr__ (or object.__setattr__) rather than writing attributes via self.attr inside __setattr__.
- Prefer properties for single-class, localized behavior; prefer custom descriptors when the same attribute behavior is reused across many classes or when building frameworks.
- Keep descriptor __get__ side effects minimal; expensive work should be explicit or clearly cached.

## Examples

Minimal non-data descriptor:
```python
class NonData:
    def __get__(self, obj, objtype=None):
        return "value"
class C:
    x = NonData()

c = C()
print(c.x)     # "value"
c.__dict__['x'] = "shadow"
print(c.x)     # "shadow" (instance attribute wins over non-data)
```

Minimal data descriptor (overrides instance):
```python
class Data:
    def __get__(self, obj, objtype=None):
        return "value"
    def __set__(self, obj, v):
        raise AttributeError("read-only")

class C:
    x = Data()

c = C()
c.__dict__['x'] = "try-to-shadow"
print(c.x)     # "value" (data descriptor wins)
# c.x = 10     # AttributeError: read-only
```

property as data descriptor with validation:
```python
class Temperature:
    def __init__(self, celsius):
        self.celsius = celsius

    @property
    def celsius(self):
        return self._celsius

    @celsius.setter
    def celsius(self, value):
        if value < -273.15:
            raise ValueError("below absolute zero")
        self._celsius = value
```

Function (method) binding via descriptor:
```python
class A:
    def f(self): return "ok"

a = A()
assert A.f is A.__dict__['f']          # function object
assert a.f() == "ok"                   # bound method call
```

Using __set_name__ to derive private storage:
```python
class Field:
    def __set_name__(self, owner, name):
        self.private = '_' + name
    def __get__(self, obj, objtype=None):
        if obj is None: return self
        return getattr(obj, self.private, None)
    def __set__(self, obj, value):
        setattr(obj, self.private, value)
```

## When to choose descriptors vs alternatives
- Use a property when the behavior is specific to one class and simple (computed attribute, validation).
- Use a custom descriptor when the same attribute behavior must be reused across many classes or when creating declarative APIs (fields, validators, lazy loaders).
- Consider __getattr__/__getattribute__ for dynamic, name-driven behavior not tied to specific attributes (careful to preserve normal descriptor semantics).
- Prefer composition and simple interfaces where possible; descriptors are powerful but can obscure control flow if overused.

## Key Points
- Descriptors customize attribute access by implementing __get__, __set__, and/or __delete__; they must be attributes on the class (or its bases) to participate in lookup.
- Lookup order: data descriptor > instance dict > non-data descriptor/class attribute > __getattr__; assignment consults data descriptor __set__ before storing in the instance.
- Functions in classes are non-data descriptors (produce bound methods); property, classmethod, and staticmethod are standard library descriptors.
- __set_name__ provides the owning class and attribute name at class-creation time, enabling robust per-instance storage conventions.
- Use properties for localized behavior; use custom descriptors for reusable validation/lazy patterns or framework-style declarative fields; avoid shared mutable state on the descriptor object.