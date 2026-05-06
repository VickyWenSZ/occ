---
title: Python Object Model
slug: python-object-model
source: python-programming-basics-long-fo
confidence: high
tags: [objects, descriptors, metaclasses, attribute-lookup, dunder-methods]
---

# Python Object Model

## Overview
Python’s object model defines how values, attributes, methods, operators, iteration, classes, and modules behave at runtime. Core principles:
- Everything is an object: numbers, strings, functions, classes, modules, exceptions, iterators, coroutines.
- Names bind to objects; objects have identity, type, and value.
- Dynamic typing: types belong to objects, not names. Type checks occur at runtime; annotations do not enforce types without extra code.
- Behavior is mediated by protocols and special (dunder) methods looked up on types.
- Attribute access follows a precise order involving instance dicts, class dicts, MRO, and descriptors.
- CPython-specific details (reference counting, GIL, bytecode) are implementation details, not language guarantees.

## Names, Objects, Identity, and Mutability
- Binding:
  - Assignment binds a name to an object (no “variable boxes” with fixed types).
  - Multiple names can refer to the same object (aliasing).
- Identity vs equality:
  - Identity: a is b; value-equality: a == b.
  - Use is for None and singletons; use == for value comparison.
- Mutability:
  - Mutable: list, dict, set; Immutable: int, float, bool, str, tuple, bytes.
  - Shallow copy copies the outer container only; deep copy recursively copies nested objects.
- Hashability:
  - Hashable objects can be dict keys/set elements; must keep hash stable with equality.
  - Tuples are hashable only if all elements are hashable.

```python
a = [1, 2]; b = a; b.append(3)
assert a is b and a == [1, 2, 3]
```

## Types, Classes, and Instances
- Every object has a type: type(obj).
- Classes are objects; their type is usually type (the default metaclass).
- Instances are created by calling the class: inst = C(...).
- Class attributes live on the class; instance attributes live on the instance.
- Name mangling for __private in classes: self.__x becomes _ClassName__x (prevents accidental override, not security).

```python
class User: pass
u = User()
type(User) is type  # True
```

## Attribute Lookup and the Data Model
Python resolves obj.attr roughly in this order (simplified):
1) Data descriptor on the class (defines __set__ or __delete__) via class or its MRO.
2) Instance dictionary (if present).
3) Non-data descriptor or other attribute on the class (via MRO).
4) Fallback to __getattr__ if defined.
If not found, raise AttributeError.

Key hooks:
- __getattribute__(self, name): invoked for all attribute access; use carefully, delegate to super().
- __getattr__(self, name): invoked only if normal lookup fails.
- __setattr__(self, name, value), __delattr__(self, name): intercept assignment/deletion; avoid recursion with super() or object.__setattr__.

```python
class Missing:
    def __getattr__(self, name):  # only on miss
        return f"{name!r} missing"
```

## Descriptors and Properties
A descriptor customizes attribute access via methods on the attribute object placed on the class:
- __get__(self, obj, objtype=None)
- __set__(self, obj, value)
- __delete__(self, obj)
- __set_name__(self, owner, name): learn assigned name at class creation.

Types:
- Data descriptors define __set__ or __delete__; they take precedence over instance attributes.
- Non-data descriptors define only __get__; instance attributes can override them.

Built-ins using descriptors:
- Functions defined in class bodies are non-data descriptors; accessing via instance returns a bound method.
- property returns a data descriptor implementing computed/validated attributes.

```python
class Positive:
    def __set_name__(self, owner, name):
        self.private = "_" + name
    def __get__(self, obj, objtype=None):
        return getattr(obj, self.private)
    def __set__(self, obj, value):
        if value <= 0: raise ValueError
        setattr(obj, self.private, value)
```

## Methods, Binding, and Callables
- Function attributes:
  - Functions have __name__, __doc__, __annotations__, __defaults__, and are objects assignable to variables.
- Method binding:
  - Accessing C.f on instance c produces a bound method with __self__=c, __func__=C.f; call inserts self automatically.
- Callable protocol: __call__ turns any object into a callable.

```python
class Mult:
    def __init__(self, k): self.k = k
    def __call__(self, x): return x * self.k
double = Mult(2); assert double(5) == 10
```

## Special Methods and Protocols
Special methods (dunder methods) implement Python protocols and are usually looked up on the type:
- Representation: __repr__, __str__
- Comparison: __eq__, __lt__, __le__, __gt__, __ge__; return NotImplemented for unsupported types
- Hashing: __hash__ consistent with __eq__
- Container: __len__, __iter__, __contains__, __getitem__, __setitem__, __delitem__
- Iterator: __iter__ returns iterator; iterators implement __next__ and raise StopIteration
- Numeric: __add__, __sub__, __mul__, etc., with reflected versions (e.g., __radd__)
- Context manager: __enter__, __exit__; async: __aenter__, __aexit__
- Async/await: __await__, __anext__, __aiter__
- Call: __call__

Guidelines:
- Use len(x), iter(x), next(it), context managers, and operators instead of calling dunders directly.
- Overload operators only when behavior is natural and unsurprising.

```python
class Bag:
    def __init__(self, items): self._items = list(items)
    def __len__(self): return len(self._items)
    def __iter__(self): return iter(self._items)
    def __contains__(self, x): return x in self._items
```

## Iterables, Iterators, Generators
- Iterable: produces iterators (has __iter__).
- Iterator: stateful, returns values via __next__ until StopIteration.
- Generator functions (yield) synthesize iterators; generator expressions are lazy.
- yield from delegates to a sub-iterator.

```python
def count_up_to(n):
    i = 1
    while i <= n:
        yield i; i += 1
```

## Classes, Class Creation, and Metaclasses
- Class creation executes the class body, then calls the metaclass to create the class object.
- Default metaclass is type; custom metaclasses subclass type to control class creation:
  - __prepare__(mcls, name, bases) -> mapping for class body execution.
  - __new__/__init__ on the metaclass to modify the class dict, enforce constraints, register subclasses.
- __init_subclass__ on a base class runs whenever a subclass is created; often simpler than a metaclass.
- Class decorators can post-process a class.
- __new__ (on the class) creates instances; __init__ initializes them. For immutable built-ins (e.g., int, str, tuple) do work in __new__.

```python
class Meta(type):
    def __new__(m, name, bases, ns):
        ns["created_by_meta"] = True
        return super().__new__(m, name, bases, ns)

class C(metaclass=Meta): pass
assert C.created_by_meta is True
```

## Inheritance, MRO, and super()
- Single and multiple inheritance supported; attribute lookup follows Method Resolution Order (MRO), inspect with C.__mro__.
- Cooperative multiple inheritance requires all overriding methods to call super() so the chain composes.
- super() resolves to the next class in the MRO, not necessarily the lexical parent.

```python
class A: 
    def f(self): print("A"); 
class B(A): 
    def f(self): print("B"); super().f()
class C(A): 
    def f(self): print("C"); super().f()
class D(B, C): pass
D().f()  # B -> C -> A
```

## __slots__, Instance Layout, Weak References
- __slots__ replaces per-instance __dict__ with fixed attribute slots:
  - Reduces memory for many small instances.
  - Prevents arbitrary new attributes.
  - Complicates inheritance/pickling; include "__weakref__" if weak refs are needed.
- Objects usually store attributes in obj.__dict__; classes’ dict is a mappingproxy (read-only view).

```python
class Point:
    __slots__ = ("x", "y", "__weakref__")
    def __init__(self, x, y): self.x, self.y = x, y
```

## Modules, Imports, and sys.modules
- A module is an object created by import; its top-level code executes once per process.
- Imported modules are cached in sys.modules; re-importing uses the cache.
- Avoid heavy side-effects at import time; prefer lazy execution within functions.
- __name__ == "__main__" identifies the entry-point module when a file is executed as a script.

## Functions, Closures, and Late Binding
- Functions are first-class objects; can carry attributes.
- Closures capture variables by reference, not by value. Common trap in loops; fix by binding default arguments.

```python
funcs = []
for i in range(3):
    funcs.append(lambda i=i: i)  # bind now
assert [f() for f in funcs] == [0, 1, 2]
```

## Exceptions as Objects
- Exceptions are class instances; carry message, type, and traceback.
- Raise with raise; catch specific types with try/except.
- Exception chaining preserves cause: raise NewError(...) from exc.
- Python 3.11+: ExceptionGroup and except* support handling multiple concurrent exceptions (version-dependent).

## Typing and Protocols (Static vs Runtime)
- Type hints annotate but do not enforce runtime types.
- Protocols (typing.Protocol) model structural typing for static checkers (duck-typed interfaces).
- ABCs (abc.ABC) provide nominal interfaces and optional runtime checks.
- Special methods and runtime behavior remain dynamic regardless of annotations.

## Memory Management (CPython details)
- CPython uses reference counting plus cyclic garbage collection.
- Reference cycles require GC; finalizers (__del__) complicate collection; prefer context managers for resources.
- The Global Interpreter Lock (GIL) in traditional CPython builds limits parallel execution of Python bytecode in threads; I/O-bound threading and multiprocessing remain useful. GIL specifics are implementation/version dependent.

## Equality, Ordering, and Hash Contracts
- If __eq__ defines value equality, ensure __hash__ is consistent (equal objects must have equal hashes).
- Mutable objects typically should not be hashable.
- total_ordering (functools) can synthesize ordering methods from __eq__ and one comparison.

```python
from functools import total_ordering
@total_ordering
class V:
    def __init__(self, a,b): self.a,self.b = a,b
    def __eq__(self,o): return isinstance(o,V) and (self.a,self.b)==(o.a,o.b)
    def __lt__(self,o): return (self.a,self.b)<(o.a,o.b)
```

## Context Managers and Resource Protocols
- with obj uses __enter__ and __exit__ for setup/cleanup; returning True from __exit__ suppresses exceptions (use sparingly).
- contextlib.contextmanager makes function-based context managers.
- ExitStack manages dynamic groups of context managers.

```python
from contextlib import contextmanager
@contextmanager
def temp_setting(obj, name, value):
    old = getattr(obj, name); setattr(obj, name, value)
    try: yield
    finally: setattr(obj, name, old)
```

## Async Objects and Structured Concurrency (version-dependent)
- Awaitable protocols (__await__), async iterators (__aiter__/__anext__), and async context managers (__aenter__/__aexit__).
- asyncio tasks schedule coroutines; cancellation raises asyncio.CancelledError; handle and re-raise.
- Python 3.11+: asyncio.TaskGroup supports structured concurrency.

## Copying, Aliasing, and Views
- Assignment aliases references.
- Shallow copies duplicate outer container only; nested mutables remain shared.
- Many stdlib views (e.g., dict.keys()) are dynamic views onto underlying objects.

```python
import copy
a = [[1],[2]]; b = copy.copy(a); b[0].append(99); assert a[0]==[1,99]
```

## Practical Patterns and Pitfalls
- Prefer properties over ad-hoc __getattr__/__setattr__ for specific attributes.
- Descriptors for reusable attribute behaviors across classes (e.g., validation).
- Prefer __init_subclass__ or class decorators over metaclasses unless class-creation control is truly required.
- Special-method dispatch is on types; setting a dunder on a single instance will not affect operator syntax.

## Key Points
- Attribute access is governed by descriptors, instance/class dicts, and MRO; data descriptors override instance attributes.
- Functions in classes are descriptors: accessing via an instance produces bound methods; special-method dispatch occurs on types.
- Classes are runtime objects created by metaclasses; __init_subclass__, class decorators, and descriptors often replace metaclasses for common needs.
- Equality/hash must be consistent; operator and protocol behaviors are implemented via well-defined dunder methods.
- CPython-specific behavior (reference counting, GIL, bytecode) is not a language guarantee; write against Python’s data model and protocols, not implementation quirks.