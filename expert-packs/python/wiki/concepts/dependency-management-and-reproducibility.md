---
title: Dependency Management and Reproducibility
slug: dependency-management-and-reproducibility
source: python-programming-basics-long-fo
confidence: high
tags: [python, packaging, dependencies, reproducibility, virtual-environments]
---

# Dependency Management and Reproducibility

## Scope and definitions
Dependency management in Python covers declaring, resolving, installing, locking, and verifying third-party packages and their versions for a project. Reproducibility means a project can be installed, tested, built, and run consistently across machines and over time. This page formalizes best practices using modern Python 3, `pyproject.toml`, virtual environments, and contemporary tooling.

Core distinctions:
- Application vs library:
  - Applications prioritize reproducibility; pin exact versions or use lock files.
  - Libraries prioritize compatibility; specify compatible version ranges to avoid over-constraining downstream users.
- Environment vs metadata:
  - A virtual environment provides isolation but not reproducibility by itself. Reproducibility requires declared Python and dependency versions plus a stable build/install process.
- Build vs install:
  - Build backends create source distributions (sdist) and wheels; installers like pip consume distributions to install packages into environments.

## Environment isolation: virtual environments and interpreter selection
Virtual environments isolate per-project packages from the system and other projects.

- Create and activate:
  - Create: `python -m venv .venv`
  - Activate (macOS/Linux): `source .venv/bin/activate`
  - Activate (Windows PowerShell): `.venv\Scripts\Activate.ps1`
- Install inside the active environment using the same interpreter:
  - Prefer `python -m pip install ...` to ensure pip matches the interpreter in use.
- Verify environment:
  - `python -c "import sys; print(sys.executable)"` to confirm the interpreter path.
- Editor/IDE integration:
  - Ensure the editor uses the same environment as the terminal. Many “works in terminal, fails in editor” issues are interpreter-mismatch bugs.

Convention: place the venv at project root (`.venv/`) and git-ignore it.

## Declaring dependencies
Modern Python consolidates project metadata in `pyproject.toml`. Requirements files remain useful for pinned application deployments and installer workflows.

- `pyproject.toml` (preferred for package metadata):
  - Core fields under `[project]`: `name`, `version` or `dynamic`, `requires-python`, `dependencies`, optional metadata.
  - Runtime dependencies: `[project].dependencies = [...]`.
  - Optional dependencies (“extras”): `[project.optional-dependencies]` (e.g., `dev`, `docs`, `postgres` groups) and installable with `".[extra]"`.
  - CLI entry points: `[project.scripts]` to expose console commands.
  - Build backend: `[build-system]` with `requires` and `build-backend` (e.g., hatchling, setuptools, flit, poetry-core, pdm-backend).
- `requirements.txt` (pip input file):
  - Plain list of packages/versions for installation. Common for application pinning and CI.
  - Generate snapshot of current env: `python -m pip freeze > requirements.txt` (note: includes all installed packages).
- Constraints files:
  - Provide upper/lower bounds without requesting installation. Use with `-c constraints.txt` to limit versions while installing from a separate `-r requirements.txt`.

Separate runtime vs development dependencies:
- Runtime dependencies go in `[project].dependencies`.
- Development-only tooling (pytest, linters, type checkers, build tools) should be in extras (e.g., `[project.optional-dependencies].dev`) or tool-specific config, not in runtime deps.

## Version constraints and pinning strategies
Version specifiers determine resolver flexibility and reproducibility:

- Forms:
  - Unpinned: `requests`
  - Lower bound: `requests>=2.32`
  - Compatible range: `requests>=2.32,<3`
  - Exact pin: `requests==2.32.3`
- Guidance:
  - Applications: pin exact versions or use lock files for reproducible deployments.
  - Libraries: specify compatible ranges (e.g., `>=x,<y`) to avoid blocking downstream resolution.
- Python version:
  - Declare supported Python versions in metadata: `[project] requires-python = ">=3.11"`.
- Note on SemVer:
  - Many projects follow semantic versioning patterns, but policies vary. Avoid assuming strict SemVer from all dependencies; respect each project’s documented policy.

## Resolution, conflicts, and lock files
- Dependency resolution selects versions satisfying all constraints. Conflicts (e.g., `package-a` requires `requests<2.30` while `package-b` requires `requests>=2.32`) should fail fast.
- Lock files record an exact, reproducible solution including transitive dependencies:
  - Tool-specific formats include `poetry.lock`, `pdm.lock`, `uv.lock`, or a generated pinned `requirements.txt`.
  - Use lock files for applications and deployments. Libraries generally should not impose lock files on downstream users.
- Constraints vs locks:
  - Constraints restrict allowable versions during resolution.
  - Locks preserve a resolved set; installing from a lock replicates that set.

## Build, packaging, and reproducible artifacts
- Distributions:
  - sdist (source distribution): contains source and metadata.
  - wheel (built distribution): install-friendly, often platform-independent for pure Python (`py3-none-any`), platform-specific for C-extensions.
- Build with the standard frontend:
  - `python -m pip install build`
  - `python -m build` produces files under `dist/`.
- Editable installs:
  - `python -m pip install -e .` for development; reflects source changes without reinstall.
- Verify packaging correctness:
  - Build a wheel, install it in a clean env, then import: `python -m pip install dist/*.whl; python -c "import my_package"`.
- Layout:
  - Prefer `src/` layout for packages to avoid accidental imports from the working directory and to test the installed artifact path resolution.

## Tooling landscape (installers, managers, backends)
- Installers and environments:
  - `pip`: standard installer; use with `venv`.
  - `venv`: stdlib virtual environment creator.
  - `pipx`: isolate global CLI tools (not project deps).
- Project/dependency managers (integrated workflows):
  - `uv`: very fast modern package/project manager; supports envs, install, resolve, locking, and more. Check current docs for evolving features.
  - Poetry, PDM, Hatch: provide metadata management, locking, build, publish workflows.
  - Setuptools: long-standing build backend; supports modern `pyproject.toml`.
- Selection guidance:
  - Use one coherent workflow per project. Avoid mixing conflicting managers (e.g., Poetry and ad-hoc `requirements.txt` without clear policy).

## Security aspects of dependencies
Third-party packages introduce supply-chain risks: vulnerabilities, malicious releases, typosquatting, license issues, abandoned projects, and transitive exposure.

Practices:
- Prefer reputable packages; avoid untrusted indexes.
- Pin/lock application dependencies and update regularly.
- Review dependency diffs; limit transitive bloat.
- Vulnerability scanning where appropriate (e.g., pip-audit, Safety, OSV).
- Hash checking for high-security deployments:
  - In requirements: `package==1.2.3 \` followed by `--hash=sha256:...`
  - Enforces content integrity; operational overhead required to maintain hashes.
- Avoid importing transitive dependencies not declared directly by your project.

## CI/CD verification for reproducibility
- CI should run in clean environments and install from declared metadata.
- Typical CI checks:
  - Install (with pinned or locked requirements for applications).
  - Lint and format checks (e.g., Ruff).
  - Type checks (mypy or Pyright).
  - Tests (pytest) and coverage.
  - Build package and test importing the built wheel.
  - Multi-version matrix for libraries (`py311`, `py312`, `py313`, `py314`) and relevant OSes if needed.
- Pre-commit hooks:
  - Fast local checks (format, lint, basic file checks, secret scanning).
  - CI remains authoritative; hooks can be bypassed and should not replace CI.

## Containers and runtime reproducibility
- Containers standardize OS-layer dependencies and runtime environment.
- Basics:
  - Use slim base images; pin base image tags; avoid root where possible.
  - Separate build and runtime dependencies; use multi-stage builds.
  - Do not bake secrets into images; expose health checks and log to stdout/stderr.
- Example production steps:
  - Build wheels in builder stage; install wheels into a slim runtime image.
  - Validate at startup: configuration parsing, timeouts, connection health if relevant.

## Data and experiment reproducibility (data work)
Beyond packages, data projects should capture:
- Dataset identifiers/versions and acquisition time.
- Data source URLs or provenance.
- Schema versions and transformations.
- Random seeds and environment details.
- Scripts and configs to regenerate key outputs.
Package-level reproducibility alone is insufficient for end-to-end data reproducibility.

## Troubleshooting and anti-patterns
Common failure modes and fixes:
- “It works on my machine”:
  - Causes: undeclared deps, wrong venv, global packages, different Python version, missing env vars, local files.
  - Fixes: clean envs, declare/pin deps, CI validation, documented setup.
- `ModuleNotFoundError` after install:
  - Likely `pip`/`python` mismatch. Use `python -m pip ...` and confirm `sys.executable`.
- Importing transitive deps:
  - Declare direct dependency if you import it; do not rely on another package’s dependencies.
- Dependency resolver conflicts:
  - Inspect constraints; relax library pins, update ranges; avoid mixing managers.
- Packaging errors hidden by flat layout:
  - Use `src/` layout; test installed wheel in CI.

## Minimal examples

Pinned application requirements:
```text
# requirements.txt
requests==2.32.3
urllib3==2.2.3
certifi==2024.8.30
```

Constraints file (limits versions without direct install):
```text
# constraints.txt
requests==2.32.3
urllib3==2.2.3
```

Install with constraints:
```bash
python -m pip install -r requirements.txt -c constraints.txt
```

Library-style `pyproject.toml` (ranges, extras, backend):
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "example-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "requests>=2.32,<3",
]

[project.optional-dependencies]
dev = [
  "pytest",
  "coverage",
  "ruff",
  "mypy",
  "build",
]
```

Virtual environment and installer hygiene:
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Build and verify distribution:
```bash
python -m pip install build
python -m build
python -m pip install dist/*.whl
python -c "import example_project; print('ok')"
```

## Key Points
- Use virtual environments for isolation; reproducibility additionally requires declared Python version, pinned or locked dependencies, and a stable build/install process.
- Applications should pin or lock exact versions; libraries should specify compatible ranges and avoid over-constraining downstream users.
- Prefer `pyproject.toml` for project metadata and dependency declaration; use requirements/constraints for installer workflows and deployment pinning.
- Validate packaging by building wheels and testing installs in clean environments; prefer `src/` layout to avoid path shadowing.
- Manage supply-chain risk: scan dependencies, minimize bloat, and consider hash checking for high-security deployments.