---
title: Testing Strategy and pytest
slug: testing-and-test-automation
source: python-programming-basics-long-fo
confidence: high
tags: [testing, pytest, unit-tests, fixtures, coverage]
---

# Testing Strategy and pytest

## Objectives and strategy
A testing strategy controls risk, not just coverage percentage. Combine layers:
- Unit tests: small, isolated behavior (pure functions, small objects).
- Integration tests: component interactions (DB/HTTP/files).
- Contract tests: external interface expectations.
- Regression tests: locked-in reproductions of past bugs.
- End-to-end/smoke: critical workflows and deployment sanity.
- Property-based tests: broad input spaces for invariants.

Design for testability:
- Make dependencies explicit (constructor/function parameters) instead of hidden globals; pass in sessions, base URLs, tokens, paths, clocks, random sources.
- Separate parsing/validation from I/O and orchestration.
- Keep import-time side effects minimal; do work in functions.

## pytest overview
pytest is a third-party test framework with:
- Discovery: files named test_*.py or *_test.py; test functions/methods named test_*.
- Simple asserts with introspection.
- Fixtures for reusable setup/teardown with dependency injection.
- Parametrization to expand a test across data sets.
- Built-ins for monkeypatching and temporary paths.
- Rich ecosystem and plugins.

Run:
```bash
pytest              # or: python -m pytest
pytest -q           # quiet
pytest path::test_name -k substring  # select
```

Basic example:
```python
def normalize_name(name: str) -> str:
    return name.strip().title()

def test_normalize_name() -> None:
    assert normalize_name(" ada ") == "Ada"
```

## Test structure and discovery
- Layout:
  - Package-style projects: src/ layout preferred to avoid importing the source tree by accident:
    project/
      pyproject.toml
      src/my_package/...
      tests/test_core.py
- Imports in tests should mirror user usage: from my_package.module import fn
- Shared fixtures/helpers live in tests/conftest.py (auto-discovered by pytest).

## Assertions and error testing
- Use plain assert; pytest shows expressions and values on failure.
- Do not use assert for production validation (can be stripped with -O); raise specific exceptions instead.
- Exception testing:
```python
import pytest

def parse_positive(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise ValueError("must be positive")
    return value

def test_parse_positive_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        parse_positive("0")
```

## Fixtures
- Define setup logic as fixtures; inject by parameter name:
```python
import pytest

@pytest.fixture
def sample_user() -> dict[str, object]:
    return {"name": "Ada", "active": True}

def test_user_is_active(sample_user: dict[str, object]) -> None:
    assert sample_user["active"] is True
```
- Keep fixtures focused and composable; avoid obscuring test intent with deep fixture nesting.
- Place widely used fixtures in tests/conftest.py.
- Use appropriate scope (function/module/session) when performance warrants; default is function.

Common built-ins:
- tmp_path: per-test temporary directory (pathlib.Path).
- monkeypatch: override env vars/attributes safely.

## Parametrization
- Expand a single test across many cases:
```python
import pytest

@pytest.mark.parametrize(
    ("text", "expected"),
    [("1", 1), ("42", 42), ("0005", 5)],
)
def test_int_parse(text: str, expected: int) -> None:
    assert int(text) == expected
```

## Monkeypatching and test doubles
- Replace environment variables, attributes, and callables:
```python
def get_mode() -> str:
    import os
    return os.environ.get("APP_MODE", "prod")

def test_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "test")
    assert get_mode() == "test"
```
- unittest.mock for behavior verification:
```python
from unittest.mock import Mock

sender = Mock()
sender.send.return_value = None
sender.send("a@example.com", "hello")
sender.send.assert_called_once_with("a@example.com", "hello")
```
- Prefer dependency injection over patching where feasible to reduce brittleness.

## Temporary paths and files
- Use tmp_path to work with files without side effects:
```python
def test_writes_file(tmp_path) -> None:
    path = tmp_path / "out.txt"
    path.write_text("hello", encoding="utf-8")
    assert path.read_text(encoding="utf-8") == "hello"
```

## Markers and selection
- Mark categories (e.g., slow) and configure in pyproject:
```toml
[tool.pytest.ini_options]
markers = ["slow: marks tests as slow"]
testpaths = ["tests"]
addopts = "-ra"
```
- Run subsets:
```bash
pytest -m "not slow"
pytest -k "substring"
```

## Property-based testing (Hypothesis)
- Explore input spaces and invariants:
```python
from hypothesis import given
from hypothesis import strategies as st

@given(st.lists(st.integers()))
def test_sorted_preserves_length(values: list[int]) -> None:
    assert len(sorted(values)) == len(values)
```
- Great for parsers, serializers, and algorithmic properties.

## Coverage
- Measure what your tests execute; branch coverage often more meaningful than line coverage.
```bash
coverage run -m pytest
coverage report
coverage html
```
- Configure:
```toml
[tool.coverage.run]
branch = true
source = ["my_package"]

[tool.coverage.report]
show_missing = true
fail_under = 85
```
- High coverage ≠ correctness; ensure strong assertions and edge cases.

## Flaky tests and stability
Common causes:
- Time dependence, sleeps, random without seed.
- Network and external service reliance.
- Shared global state or test-order dependence.
- Concurrency races, filesystem assumptions.

Mitigations:
- Isolate state; use fixtures and tmp_path.
- Replace real network with fakes/mocks; set timeouts.
- Seed randomness or inject RNGs.
- Mark slow/external tests; exclude from fast path; fix flakes rather than rerun-until-green.

## Testing CLIs and configuration
- Separate parsing from execution to test logic independently:
```python
import argparse

def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("name")
    return p.parse_args(argv)

def run(name: str) -> None:
    print(f"Hello, {name}")

def main(argv=None) -> int:
    args = parse_args(argv)
    run(args.name)
    return 0
```
- Test main with explicit argv; use SystemExit for exit codes in scripts.

## Multi-environment automation (tox/nox)
- tox (INI-driven) for version matrices:
```ini
[tox]
envlist = py311, py312, py313

[testenv]
deps = pytest
commands = pytest
```
- Nox (Python-driven) for flexible sessions:
```python
import nox

@nox.session(python=["3.11","3.12","3.13"])
def tests(session: nox.Session) -> None:
    session.install(".[dev]")
    session.run("pytest")
```

## CI integration
- Run in clean environments; install from declared metadata; verify packaging for libraries.
- Example GitHub Actions job (conceptual):
```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix: { python-version: ["3.11","3.12","3.13"] }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: ${{ matrix.python-version }} }
      - run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy src
      - run: pytest
```
- Cache wheels/packages and parallelize to keep feedback fast.

## Common pitfalls
- Asserts used for runtime validation (stripped with -O): raise exceptions instead.
- Tests import the local package accidentally (flat layout): prefer src/ or editable installs.
- Over-mocking internals: test behavior and public API; keep mocks at boundaries.
- Hidden global state: pass dependencies explicitly.
- Network/time randomness in unit tests: inject fakes and seeds; set timeouts.

## Key Points
- Use pytest’s fixtures, parametrization, and assertion introspection to write concise, robust, isolated tests.
- Design code for testability by injecting dependencies and minimizing import-time side effects.
- Layer tests (unit, integration, property-based, end-to-end) and measure with coverage; prefer branch coverage thresholds with meaningful assertions.
- Control flakiness by isolating state, avoiding real network/time in unit tests, and fixing nondeterminism promptly.
- Automate across environments (tox/nox) and CI; test installed artifacts for libraries and pin or lock dependencies for applications.