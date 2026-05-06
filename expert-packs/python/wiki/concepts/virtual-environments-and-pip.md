---
title: Virtual Environments and pip
slug: virtual-environments-and-pip
source: python-programming-basics-long-fo
confidence: high
tags: [python, venv, pip, dependencies, packaging]
---

# Virtual Environments and pip

## Overview

Virtual environments (venv) provide isolated Python installations with their own site-packages, preventing one project’s dependencies from affecting another. pip is the standard Python package installer used to add, remove, inspect, and freeze third-party dependencies, typically inside a virtual environment. For modern development, always use Python 3 and prefer per-project virtual environments.

Key relationships:
- A venv isolates interpreter + installed packages for a project.
- pip installs into the currently selected interpreter’s environment; use python -m pip to bind pip to the exact interpreter/venv you intend.
- Applications benefit from pinned/locked dependencies for reproducibility; libraries should avoid over-constraining downstream users.

## Creating and activating a virtual environment

Create an isolated environment in the project root (common convention: .venv directory):

```bash
python -m venv .venv
```

Activate:
- macOS/Linux (bash/zsh):
  ```bash
  source .venv/bin/activate
  ```
- Windows PowerShell:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```

Deactivate:
```bash
deactivate
```

Interpreter selection and verification:
- The Python command varies by platform/install: python, python3, or py (Windows launcher).
  - Windows examples:
    - Default: `py`
    - Specific version: `py -3.12`
- Confirm the active interpreter path (helps detect editor/terminal mismatches):
  ```bash
  python -c "import sys; print(sys.executable)"
  ```
- Keep .venv out of version control (e.g., via .gitignore).

## Using pip safely and correctly

Bind pip to the active interpreter/venv to avoid ambiguity:
```bash
python -m pip install PACKAGE
```

Common operations:
```bash
python -m pip install requests
python -m pip install --upgrade requests
python -m pip uninstall requests
python -m pip list
python -m pip show requests
python -m pip install --upgrade pip
```

Freeze currently installed versions to a requirements file (useful for application deployments):
```bash
python -m pip freeze > requirements.txt
```

Install from a requirements file:
```bash
python -m pip install -r requirements.txt
```

Editable installs for package development (reflect source changes without reinstall):
```bash
python -m pip install -e .
```

Notes:
- Prefer python -m pip over bare pip to ensure you target the intended environment.
- pip modifies only the currently selected environment (system/global or active venv).

## Dependency pinning and files

- requirements.txt
  - Plain-text list of packages (optionally pinned with ==).
  - Typical for application deployments and simple workflows.
  - Example:
    ```
    requests==2.32.3
    pytest==8.3.2
    ```
  - Install: `python -m pip install -r requirements.txt`

- Pinning policy
  - Applications: prefer exact pins or lock files for reproducibility.
  - Libraries: avoid exact pins; specify compatible ranges to prevent conflicts for downstream users (e.g., requests>=2.32,<3).

- Constraints files (advanced pip usage)
  - Constrain versions without directly causing installation:
    ```bash
    python -m pip install -r requirements.txt -c constraints.txt
    ```
  - Useful for organization-wide version ceilings/floors.

- pyproject.toml (project metadata)
  - Modern packaging and tooling central configuration; can declare runtime dependencies and optional development extras.
  - Applications may still use requirements files or lock files to ensure deterministic deploys.
  - Example dependency declaration (library-style):
    ```toml
    [project]
    requires-python = ">=3.11"
    dependencies = ["requests>=2.32,<3"]
    ```

## Typical per-project workflow

1. Create and activate venv:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
2. Upgrade pip, install dependencies:
   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
   or for development extras:
   ```bash
   python -m pip install -e ".[dev]"
   ```
3. Verify interpreter and installed packages:
   ```bash
   python -c "import sys; print(sys.executable)"
   python -m pip list
   ```
4. Freeze for deployment (applications):
   ```bash
   python -m pip freeze > requirements.txt
   ```
5. Deactivate when done:
   ```bash
   deactivate
   ```

## IDE/editor integration

- Point your IDE to the project venv’s interpreter; mismatches cause “works in terminal but not in editor” (and vice versa).
- Validate with:
  ```bash
  python -c "import sys; print(sys.executable)"
  ```
- Common symptom of mismatch: ModuleNotFoundError for installed packages due to using the wrong interpreter.

## Troubleshooting

- ModuleNotFoundError after install:
  - Cause: active Python differs from the one pip installed into.
  - Fix: use python -m pip consistently; re-check `sys.executable`; ensure venv is activated.
- pip succeeded but import fails:
  - Cause: pip and python refer to different envs.
  - Fix: `python -m pip show pkg`, `python -m pip list`; verify interpreter path; reactivate venv.
- Conflicting dependency versions:
  - Adjust requirements/constraints; for libraries, relax overly strict pins; for applications, update pins consistently and test.
- Tests import source unintentionally (not installed package):
  - Adopt src/ layout and install the package in the venv (`python -m pip install -e .`) to test the installed artifact.

## Security and reproducibility notes

- Avoid global installs; per-project venvs limit blast radius and version conflicts.
- Applications: pin exact versions (or use a lock workflow) and record Python version; build and test in clean environments (CI) to catch undeclared dependencies.
- Always set up environments via declared files (requirements.txt and/or pyproject.toml metadata).
- Prefer reproducible installs from frozen/locked sets for deployment scenarios.

## Command reference (cheat sheet)

```bash
# Create and activate environment
python -m venv .venv
source .venv/bin/activate            # macOS/Linux
.venv\Scripts\Activate.ps1           # Windows PowerShell

# Interpreter/pip binding and upgrade
python -c "import sys; print(sys.executable)"
python -m pip install --upgrade pip

# Install/uninstall/show/list
python -m pip install PACKAGE
python -m pip uninstall PACKAGE
python -m pip show PACKAGE
python -m pip list

# Requirements workflows
python -m pip freeze > requirements.txt
python -m pip install -r requirements.txt

# Editable install for local package development
python -m pip install -e .

# Deactivate
deactivate
```

## Key Points

- Use a virtual environment per project to isolate dependencies; store it in .venv and exclude it from VCS.
- Always run pip via python -m pip to target the active interpreter/venv and avoid cross-environment mistakes.
- Applications should pin/lock dependencies for reproducibility; libraries should specify compatible version ranges to avoid over-constraining users.
- Verify the active interpreter (sys.executable) and align your IDE/editor to the same venv to prevent ModuleNotFoundError due to environment mismatch.
- Manage installs with requirements.txt for simple flows; declare runtime deps in pyproject.toml for packaging; use constraints files to enforce version ceilings/floors when needed.