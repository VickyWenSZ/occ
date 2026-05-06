# Wiki Index

Last updated: 2026-05-06  
Total pages: 15

## Pages

| File | Title | Summary |
|------|-------|---------|
| concepts/asyncio-and-async-programming.md | asyncio and Asynchronous Programming | Explains async/await, coroutines, tasks, the event loop, cancellation, timeouts, async IO patterns, and when async concurrency is appropriate versus other models. |
| concepts/attribute-lookup.md | Attribute Lookup and Instance/Class Namespaces | Details how attribute access works in Python, including the roles of instance __dict__, class __dict__, descriptors, __getattr__/__getattribute__, and lookup order. |
| concepts/concurrency-and-parallelism.md | Concurrency and Parallelism (Threads, Processes, Async) | Compares threading, multiprocessing, and async approaches in Python, covering the GIL implications, thread-safety, process costs, executors, and task coordination patterns. |
| concepts/dataclasses-and-data-modeling.md | Dataclasses and Data Modeling | Introduces dataclasses, field and default_factory usage, frozen and slots options, __post_init__ hooks, and tradeoffs compared with manual classes or validation libraries. |
| concepts/dependency-management-and-reproducibility.md | Dependency Management and Reproducibility | Explains declaring dependencies, version specifiers, lock files, constraints, direct vs transitive dependencies, and policies for reproducible application deployments and library compatibility. |
| concepts/descriptor-protocol.md | Descriptor Protocol | Describes data and non‑data descriptors (__get__, __set__, __delete__, __set_name__), how they implement properties/methods, and when to use them for reusable attribute behavior. |
| concepts/dunder-methods-and-protocols.md | Dunder Methods and Language Protocols | Covers special methods (e.g., __repr__, __eq__, __len__, __enter__/__exit__) and how implementing these protocols makes objects interoperate with Python syntax and built‑ins. |
| concepts/metaclasses-and-class-creation.md | Metaclasses and Class Creation | Explores how classes are created at runtime, the role of metaclasses (type subclasses), __new__/__init__/__prepare__, and alternatives like __init_subclass__ and class decorators. |
| concepts/packaging-and-pyproject-toml.md | Packaging and pyproject.toml | Covers modern packaging fundamentals centered on pyproject.toml, build backends, wheels vs sdists, entry points, versioning strategies, and best practices for libraries vs applications. |
| concepts/performance-and-profiling.md | Performance Engineering and Profiling | Covers how to diagnose and improve performance: measuring with timeit/cProfile, Big‑O reasoning, memory considerations, caching, vectorization, and the tradeoffs of micro‑optimizations. |
| concepts/project-layout-and-ci-workflow.md | Project Layout, Tooling and CI Workflows | Describes professional project structure (src/ layout), pyproject-centric configuration, formatters/linters/pre-commit, CI best practices, and release/build verification steps. |
| concepts/python-object-model.md | Python Object Model | Explains Python's runtime notions of objects, identity, type, value, instance and class dictionaries, and the mental model for how names bind to objects. |
| concepts/security-practices.md | Security Best Practices for Python | Summarizes core security guidance including avoiding eval/pickle on untrusted input, path traversal defenses, secrets management, subprocess safety, and dependency supply‑chain mitigation. |
| concepts/testing-and-test-automation.md | Testing Strategy and pytest | Outlines testing strategy layers, unit vs integration tests, pytest usage (fixtures, parametrization), mocking/monkeypatching, flakiness causes, coverage, and CI test matrices. |
| concepts/virtual-environments-and-pip.md | Virtual Environments and pip | Describes creating and using isolated Python environments with venv, best practices for invoking pip via python -m pip, interpreter selection, and IDE integration pitfalls. |
