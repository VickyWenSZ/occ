---
title: Packaging and pyproject.toml
slug: packaging-and-pyproject-toml
source: python-programming-basics-long-fo
confidence: high
tags: [replace with 3-5 relevant lowercase keywords]
---

# Packaging and pyproject.toml

## Overview

Packaging is the process of turning a Python project into an installable, importable distribution with declared metadata, dependencies, and build configuration. Modern Python centers packaging, builds, and tool configuration around a single TOML file: pyproject.toml. The Python Packaging User Guide describes pyproject.toml as a configuration file used by packaging tools and other development tools (linters, type checkers, formatters). It hosts:
- Build-system configuration ([build-system])
- Project metadata and dependencies ([project], extras, scripts)
- Tool-specific configuration ([tool.<name>])

Use Python 3 for new work. Modern packaging practices assume Python 3.x and the growing ecosystem of standardized metadata and wheels. For installation and isolation, use virtual environments and invoke pip via python -m pip to ensure the correct interpreter.

## Project layout and packaging scope

- Script-only projects (internal automation) can start simple, but distributable applications and libraries should adopt a package layout and pyproject.toml.
- Preferred layout for packages: src/ layout. It prevents accidental imports from the working directory and ensures tests exercise the installed package rather than the source tree.
  - Flat layout is acceptable for small projects but can mask packaging mistakes because the project root is often on sys.path.
- Minimal package structure:
  - src/<package_name>/__init__.py and modules
  - tests/ with import paths mirroring user usage
  - pyproject.toml for metadata, builds, and tool configs
  - README.md, LICENSE, and optional docs/

Example src/ layout:
```
my-project/
  pyproject.toml
  README.md
  src/
    my_package/
      __init__.py
      core.py
  tests/
    test_core.py
```

## pyproject.toml essentials

### [build-system]
Declares the build backend and build requirements used to produce source distributions (sdist) and wheels:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```
Common backends: setuptools, hatchling, flit, poetry-core, pdm-backend. The backend choice affects configuration semantics but must produce standards-compliant distributions.

### [project] metadata
Specifies canonical package metadata and runtime dependencies. Prefer static fields where feasible; use dynamic only when the build backend injects values.
```toml
[project]
name = "example-package"
version = "0.1.0"
description = "An example Python package"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"

authors = [{ name = "Example Author", email = "author@example.com" }]

dependencies = [
  "requests>=2.32,<3",
]
```
Key fields:
- name, version: distribution identity. Keep a single source of truth (either static in pyproject.toml or a backend-managed dynamic version).
- requires-python: supported interpreter range; crucial for installers and resolvers.
- dependencies: runtime requirements (library-style: compatible ranges; application-style: pin in lock/pinned files for deployment).

### Optional dependencies (extras)
Declare opt-in feature groups (e.g., dev, docs, database drivers):
```toml
[project.optional-dependencies]
dev = ["pytest", "ruff", "mypy", "coverage", "build"]
docs = ["mkdocs"]
postgres = ["psycopg[binary]"]
```
Install with extras:
```
python -m pip install ".[dev]"
```

### CLI entry points
Expose console scripts via project.scripts:
```toml
[project.scripts]
my-tool = "my_package.cli:main"
```
The referenced callable should be import-safe (avoid heavy I/O at import time) and typically return an int exit code; wrap with raise SystemExit(main()) when invoked directly.

### Tool configuration
Many tools read configuration from pyproject.toml under [tool.<name>]:
```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.11"
strict = true

[tool.coverage.run]
branch = true
source = ["my_package"]
```
Not all tools support pyproject.toml for all options; consult each tool’s documentation.

## Building distributions

- Source distribution (sdist): archives source and metadata, built typically as .tar.gz.
- Wheel: built distribution for fast installation; pure-Python wheels look like -py3-none-any.whl; platform wheels embed ABI/platform tags.

Build with the standard build frontend:
```
python -m pip install build
python -m build
```
Artifacts appear in dist/. Always verify by installing the built wheel in a clean environment:
```
python -m pip install dist/*.whl
python -c "import my_package; print(my_package.__name__)"
```

Editable installs are useful during development:
```
python -m pip install -e .
```

## Dependency specification and strategy

### Version specifiers and policy
- Unpinned (e.g., requests): maximally flexible, least reproducible.
- Lower bound (requests>=2.32): avoid unsupported old versions.
- Compatible ranges (requests>=2.32,<3): library-friendly; leave headroom.
- Exact pins (requests==2.32.3): application deployment reproducibility.

Guideline:
- Libraries: use compatible ranges in [project].dependencies to avoid constraining downstream resolution.
- Applications: use lock files or pinned requirements for deployment reproducibility.

### Requirements and constraints files
- requirements.txt: pip-native installation list (conventionally via -r). Good for applications/deployments.
- Constraints file (-c constraints.txt): restricts allowable versions without requesting installation, useful for enterprise controls or deployment standardization.
- Lock files: tool-specific (e.g., Poetry, PDM, uv). Appropriate for applications; generally not published by libraries.

### Direct vs transitive usage
If your code imports a package, declare it directly in dependencies. Do not rely on a transitive dependency of another package; it can change without notice.

## Applications vs libraries

- Applications prioritize reproducibility:
  - Pin or lock dependencies
  - Validate configuration and environment on startup
  - CI must build and install from a clean state
- Libraries prioritize compatibility:
  - Declare supported Python versions (requires-python)
  - Use compatible dependency ranges
  - Provide stable public API and deprecation policy
  - Test across supported Python versions and lower/upper dependency bounds when practical

## Verification and CI

- Always test with the installed artifact (wheel), not just the source tree.
- CI should:
  - Create a clean virtual environment
  - Install with python -m pip install -e ".[dev]" (dev workflow) or install built wheel (release checks)
  - Run linting, formatting checks, and type checking if adopted
  - Run tests across supported Python versions (matrix)
  - Optionally build distributions to catch packaging errors early

Example CI steps (conceptual):
```
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy src
pytest
python -m build
python -m pip install dist/*.whl
```

## Virtual environments and installation hygiene

- Create isolated environments with venv:
  - python -m venv .venv; activate; ensure editor uses the same interpreter
- Prefer python -m pip ... to guarantee operations run against the intended interpreter
- Do not commit virtual environments; add .venv/ to .gitignore

## Publishing and distribution targets

- Public distribution: build sdist and wheels, then upload via trusted publishing or twine to PyPI (consult current PyPI docs).
- Internal distribution: use private indexes or artifact repositories for organizational control, caching, and access policies.
- Containers: package applications with OS-level dependencies; separate build and runtime stages for slim images.

## Documentation and metadata quality

- Provide README, LICENSE, supported Python versions, how to install, quickstart usage, and contribution/testing instructions.
- Keep changelog with user-visible changes and version history.
- Avoid import-time side effects in top-level modules to keep installation, import, testing, and CLI startup predictable.

## Minimal, composable examples

Minimal pyproject.toml for a library:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "example-project"
version = "0.1.0"
description = "Example professional Python project"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [{ name = "Example Team", email = "team@example.com" }]
dependencies = ["requests>=2.32,<3"]

[project.optional-dependencies]
dev = ["pytest", "coverage", "ruff", "mypy", "build"]

[project.scripts]
example-tool = "example_project.cli:main"

[tool.ruff]
line-length = 88
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.coverage.run]
branch = true
source = ["example_project"]

[tool.mypy]
python_version = "3.11"
strict = true
```

Build and verify:
```
python -m pip install build
python -m build
python -m pip install dist/*.whl
python -c "import example_project; print(example_project.__name__)"
```

Development install:
```
python -m pip install -e ".[dev]"
pytest
```

## Common pitfalls and remedies

- Works locally, fails elsewhere: undeclared dependencies, wrong interpreter, missing wheel files. Remedy: clean env, install built wheel, ensure direct dependency declarations.
- Importing source during tests: flat layout hides packaging errors. Remedy: src/ layout or ensure tests import the installed package.
- Over-constraining library dependencies: leads to resolver conflicts for users. Remedy: use compatible ranges and document supported versions.
- Tool configuration drift: inconsistent local vs CI behavior. Remedy: store configs in repo (pyproject.toml where supported), pin tool versions, use pre-commit.
- Build includes wrong/missing files: misconfigured backend discovery. Remedy: inspect wheel contents, adjust backend package discovery, retest in clean env.

## Security and supply chain basics for packaging

- Prefer lock/pins for applications; review dependency changes regularly.
- Use constraints for organizational control where appropriate.
- Avoid running untrusted code at build or import time; keep imports lightweight.
- Consider vulnerability and secret scanning in CI.
- Install from trusted indexes; avoid typosquatting and dependency confusion.

## Key Points

- pyproject.toml centralizes build-system config, project metadata, dependencies, scripts, and many tool settings; it is the modern anchor of Python packaging.
- Use src/ layout, build wheels with a backend (e.g., hatchling), and verify by installing artifacts in clean environments; prefer python -m pip.
- Libraries specify compatible dependency ranges and supported Python versions; applications pin/lock for reproducibility and deployment stability.
- Optional dependencies (extras) group feature-specific or development dependencies; scripts expose CLI entry points via [project.scripts].
- CI should validate packaging: configure envs, lint/format/type-check, run tests across versions, build distributions, and install built wheels to catch errors early.