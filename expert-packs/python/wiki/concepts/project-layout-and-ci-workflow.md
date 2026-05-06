---
title: Project Layout, Tooling and CI Workflows
slug: project-layout-and-ci-workflow
source: python-programming-basics-long-fo
confidence: high
tags: [packaging, pyproject.toml, testing, ci, tooling]
---

# Project Layout, Tooling and CI Workflows

## Executive overview
Professional Python projects are more than `.py` files: they are versioned, installable, testable, reproducible, and maintainable units. Core practices include a predictable project layout (preferably `src/`), isolated environments, declared dependencies in `pyproject.toml`, automated quality gates (formatter, linter, type checker, tests), multi-environment testing, and CI that validates the build and packaging in clean environments. Distinguish applications (often pinned, lock-file-managed) from libraries (compatibility ranges, multi-version support). Consolidate configuration in `pyproject.toml` where tools support it.

## Project categories and goals
- Script project
  - Minimal structure for small internal automation.
  - Can start with `requirements.txt` and grow into package layout if needed.
- Application (web/CLI/worker/service)
  - Priorities: reproducible environments, pinned or locked dependencies, configuration and logging, deployment docs, tests.
- Library/package
  - Priorities: stable public API, compatible dependency ranges, supported Python version matrix, packaging correctness, documentation, tests across versions.
- Research/notebook project
  - Add environment definition, data provenance, deterministic seeds, scripts for reproducibility; avoid committing large data.

## Layouts and repository structure
Preferred `src/` layout helps avoid importing local source instead of the installed package during tests.

Flat layout (acceptable for small projects):
```
my-project/
    my_package/
        __init__.py
        core.py
    tests/
        test_core.py
    pyproject.toml
```

`src/` layout (recommended for distributable packages and libraries):
```
my-project/
    src/
        my_package/
            __init__.py
            core.py
    tests/
        test_core.py
    pyproject.toml
```

Common directories and files:
- tests/: test modules (e.g., test_core.py, conftest.py)
- docs/: user and API documentation (e.g., index.md)
- .gitignore, LICENSE, README.md
- .pre-commit-config.yaml
- .github/workflows/ci.yml (or other CI provider config)
- Additional config files as needed (pytest.ini/pyproject sections, mypy.ini/tool.mypy, .coveragerc/pyproject sections, ruff config, tox.ini, noxfile.py)

## pyproject.toml essentials
`pyproject.toml` centralizes build metadata and tool configurations.

Minimal package:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "example-package"
version = "0.1.0"
description = "Example package"
readme = "README.md"
requires-python = ">=3.11"
dependencies = ["requests>=2.32,<3"]

[project.optional-dependencies]
dev = ["pytest", "coverage", "ruff", "mypy", "build"]

[project.scripts]
example-tool = "example_package.cli:main"

[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.coverage.run]
branch = true
source = ["example_package"]

[tool.coverage.report]
show_missing = true
fail_under = 85

[tool.mypy]
python_version = "3.11"
strict = true
```

Key tables:
- [build-system]: build backend and build dependencies (e.g., hatchling, setuptools, flit, poetry-core, pdm-backend).
- [project]: name, version (static or dynamic), requires-python, dependencies.
- [project.optional-dependencies]: extras (e.g., dev, postgres).
- [project.scripts]: console entry points.
- [tool.*]: tool-specific configuration (ruff, pytest, mypy, coverage, etc.), when supported.

## Virtual environments and interpreter hygiene
- Create: `python -m venv .venv`
- Activate (Unix): `source .venv/bin/activate`; (Windows PowerShell): `.venv\Scripts\Activate.ps1`
- Always install via the active interpreter: `python -m pip install -e ".[dev]"`
- Verify interpreter: `python -c "import sys; print(sys.executable)"`

Editors/IDEs must use the same interpreter as the terminal; many “works locally” bugs are mismatched interpreter issues.

## Dependency management
Concepts:
- Runtime dependencies: required for execution (in `[project].dependencies`).
- Development dependencies: for contributors (tests, lint, type-check, build) — put into extras like `[project.optional-dependencies].dev`.
- Direct vs transitive: never import a transitive dependency without declaring it directly.

Versioning patterns:
- Unbounded: `requests` (flexible, less reproducible)
- Lower bound: `requests>=2.32` (avoid old versions)
- Compatible range: `requests>=2.32,<3` (common for libraries)
- Exact pin: `requests==2.32.3` (common for applications)

Requirements/constraints/lock:
- requirements.txt: pip-installable list for deployments.
- Constraints file: restricts versions without causing installation (`-c constraints.txt`).
- Lock files: exact resolution for apps (tool-specific: poetry.lock, pdm.lock, uv.lock). Libraries generally avoid shipping lock files.

Tools:
- pip + venv: standard, simple.
- pipx: install global CLI tools in isolated envs.
- uv / Poetry / PDM / Hatch: modern project managers (resolve, lock, build, run). Choose one consistent workflow; avoid mixing.

## Packaging and distribution
Artifacts:
- sdist (source distribution): tarball with source and metadata.
- wheel (built distribution): installable binary format (`py3-none-any` for pure Python; platform-specific for extensions).

Build and verify:
```bash
python -m pip install --upgrade pip build
python -m build
python -m pip install dist/*.whl  # in clean env
python -c "import my_package; print(my_package.__version__)"
```

Editable installs (development):
```bash
python -m pip install -e .
```

Entry points:
```toml
[project.scripts]
my-tool = "my_package.cli:main"
```

Prefer installed-command invocations (entry points) over invoking module files directly in production.

## Formatting and linting
- Formatter: Black or Ruff formatter; choose one and enforce consistently (pre-commit + CI).
  - Ruff formatter: `ruff format .`
- Linter: Ruff (fast, broad rule coverage; can replace Flake8+plugins, isort, pyupgrade).
  - Run: `ruff check .` (use `--fix` for autofix)
  - Sort imports via Ruff’s lint rules.
- Pylint: optional deeper static analysis (noisier; team-tuned).
- Keep rule sets deliberate; avoid enabling noisy rules en masse.

## Static type checking
- mypy or Pyright (choose one primary for CI).
  - mypy example: `mypy src`
  - Pyright config via `pyrightconfig.json` or editor/tool integration.
- Gradual typing strategy:
  - Start with public APIs, pure functions, dataclasses.
  - Prefer `object` over `Any` when possible; narrow early.
  - Track and reduce `# type: ignore`s.
- For typed libraries, include `py.typed` in package data.

## Testing workflow
- pytest (common choice)
  - Discovery: files named `test_*.py`; functions named `test_*`.
  - Fixtures: reuse setup; place shared fixtures in `conftest.py`.
  - Parametrization: `@pytest.mark.parametrize(...)`
  - Markers: categorize tests (e.g., `@pytest.mark.slow`), register in pytest config.
  - Coverage: `coverage run -m pytest && coverage report` (enable branch coverage; fail-under gates).
- Organization:
  - Separate unit vs integration tests.
  - Avoid global-state coupling; inject dependencies for testability.
  - Minimize external I/O in unit tests; isolate network and time.

## Multi-environment test automation
- tox:
  ```ini
  [tox]
  envlist = py311, py312, py313

  [testenv]
  deps = pytest
  commands = pytest
  ```
- Nox (Python-native sessions and matrices):
  ```python
  import nox

  @nox.session(python=["3.11","3.12","3.13"])
  def tests(session):
      session.install(".[dev]")
      session.run("pytest")
  ```
- Use matrices for Python versions, OSes, and optional extras; keep combinations meaningful to control CI time.

## Pre-commit hooks
- Automate fast local checks; prevent style/quality drift.
- Example `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: ["--fix"]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
```
- Install: `pre-commit install`
- Run all: `pre-commit run --all-files`
- Keep pre-commit fast; put heavy checks (full tests, type checking) in CI.

## Continuous integration (CI)
Goals:
- Clean installations from declared metadata (no local state).
- Run lint, format-check, type-check, tests, coverage.
- Build and sanity-check package.
- Multi-version matrix for libraries; focused single-version for apps.

GitHub Actions example:
```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11","3.12","3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Format check
        run: ruff format --check .
      - name: Type check
        run: mypy src
      - name: Tests
        run: pytest
      - name: Build
        run: python -m build
```

Best practices:
- Cache package downloads appropriately.
- Split fast and slow jobs; parallelize.
- Require stable gates (avoid flaky checks).
- Validate wheels by installing them in clean envs.

## Documentation tooling
- README: what, install, minimal usage, supported Python, dev setup, test command, license, links.
- Sphinx: API-heavy libraries (reST/Markdown extensions).
- MkDocs + Material: Markdown-first, guides and docs sites.
- API docs supplement, not replace, conceptual guides and how-tos.

## Release management and publishing
- Changelog (Added/Changed/Deprecated/Removed/Fixed/Security).
- Release checklist:
  - Lint, type-check, tests, coverage pass.
  - Build sdist and wheel.
  - Install built wheel in clean env; import sanity-check.
  - Update changelog.
  - Tag and publish (e.g., `twine upload dist/*` or trusted publishing).
  - Verify installation from index (public or internal).
- Internal indexes (devpi, Artifactory, Nexus, cloud registries) for private packages and policy control.

## Security and supply chain practices
- Dependency scanning: pip-audit, Safety, OSV-Scanner, Dependabot, Snyk (org policy dependent).
- Secret scanning: pre-commit and CI (detect-secrets, gitleaks, GitHub scanning).
- Supply-chain risk controls:
  - Use trusted package sources; avoid unreviewed packages.
  - Pin/lock application dependencies; review diffs.
  - Hash-pinned requirements for high-security deployments.
  - Keep build tools updated; avoid arbitrary `shell=True`.
- Subprocess safety: avoid `shell=True` with untrusted input; pass argv lists.

## Reproducibility
- Declare supported Python versions (`requires-python`).
- Applications: lock files or fully pinned deployment requirements.
- Libraries: compatible ranges; test lower/upper bounds where practical.
- Clean-room builds: documented commands from a fresh checkout should succeed.
- Data projects: also track datasets, schemas, seeds, and environment.

## Containers (optional for deployment)
- Minimal example:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .
CMD ["python", "-m", "my_package"]
```
- Production: non-root user, slim base, separate build/runtime deps, no secrets in image, health checks, signal handling, logging to stdout/stderr, vulnerability scanning, multi-stage builds for compiled deps.

## Application configuration and observability
- Configuration sources: CLI args, env vars, config files, secrets managers; define precedence (CLI > env > file > defaults).
- Validate configuration at startup; fail fast on invalid values.
- Logging:
  - Libraries create named loggers; apps configure handlers/format.
  - Avoid logging secrets; guard expensive debug logging.
- Metrics/tracing: integrate with Prometheus/OpenTelemetry/APM as needed.

## Editor/IDE and automation
- Ensure editor uses project’s `.venv`.
- `.editorconfig` for cross-editor basics.
- Task runners:
  - Makefile/just for cross-language tasks.
  - Nox for Python-native automation (install + run commands in sessions).
- Encode dev/release commands in repo; avoid “tribal knowledge”.

## Troubleshooting quick reference
- ModuleNotFoundError: wrong venv/import name, missing `__init__.py` (traditional), not installed wheel. Fix: `python -m pip install -e .`; verify `sys.executable`.
- pip installs but cannot import: `pip` vs `python` mismatch. Use `python -m pip`.
- Local pass, CI fail: undeclared deps, version mismatch, env vars, case sensitivity, flaky order. Reproduce in clean env.
- Build ok, wheel missing files: package discovery misconfigured; inspect wheel, fix backend config, verify `src/` inclusion.
- Resolver conflicts: incompatible constraints/pins; relax library pins, update packages, avoid mixing project managers, separate app locks from library ranges.

## Example baseline command set
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

ruff format .
ruff check .
mypy src
pytest
coverage run -m pytest && coverage report
python -m build
python -m pip install dist/*.whl
```

## Key Points
- Prefer `src/` layout, `pyproject.toml`, and isolated environments; install with `python -m pip`.
- Separate application (pins/locks) vs library (compatible ranges, multi-version CI) dependency strategies.
- Automate quality gates: formatter (Ruff/Black), linter (Ruff), type checker (mypy/Pyright), tests (pytest + coverage).
- Use pre-commit for fast local checks and CI for clean-environment validation, packaging, and matrices.
- Security and reproducibility require declared Python versions, pinned/locked deps for apps, safe subprocess use, and dependency/secret scanning.