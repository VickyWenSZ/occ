---
title: Security Best Practices for Python
slug: security-practices
source: python-programming-basics-long-fo
confidence: high
tags: [python, security, dependencies, subprocess, secrets]
---

# Security Best Practices for Python

## Executive summary
Secure Python development requires disciplined avoidance of dynamic code execution on untrusted inputs, careful filesystem and subprocess handling, safe serialization, secret hygiene, robust network client defaults, supply-chain risk management, and automated scanning and testing. Modern, reproducible environments with pinned or constrained dependencies (for applications), explicit configuration validation, and safe coding templates reduce risk substantially.

## Threat modeling baseline
Before coding, enumerate risks and trust boundaries:
- Untrusted inputs: CLI args, environment variables, files, HTTP payloads, database content, plugin names, configuration.
- Filesystem: what can be read/written; where path joins occur; symlink and race considerations.
- Subprocesses: whether commands or shell features use untrusted strings.
- Secrets: where keys/tokens live; how they enter processes; where they might leak (logs, tracebacks).
- Networking: timeouts, TLS verification, auth, rate limits, retries.
- Dependencies: provenance, typosquatting, transitive vulnerabilities, build-time execution.
- Privileges and logs: process permissions; which logs persist and who can read them.

## Never execute untrusted code or data
- Avoid dynamic code execution:
  - Never eval/exec/compile untrusted text.
    ```python
    # Dangerous
    eval(user_input)
    exec(user_input)
    ```
  - Prefer structured parsers. For Python literals only, ast.literal_eval is safer than eval; for interoperable data, use JSON.
    ```python
    import ast, json
    safe_list = ast.literal_eval("[1, 2, 3]")
    data = json.loads('{"name": "Ada"}')
    ```
- Avoid unsafe deserialization:
  - Never unpickle untrusted bytes; pickle can execute arbitrary code.
    ```python
    import pickle
    # Unsafe: pickle.loads(untrusted_bytes)
    ```
  - Use JSON for untrusted interchange and validate shape/limits post-parse.

## Filesystem and path traversal safety
- Do not naively join user input to sensitive directories.
  ```python
  from pathlib import Path
  base = Path("uploads").resolve()
  candidate = (base / user_input).resolve()
  if candidate != base and base not in candidate.parents:
      raise ValueError("invalid path")
  ```
- Additional concerns for serious systems: symlinks, TOCTOU races, file creation modes/umask, platform differences.
- Always specify encodings for text I/O to avoid mis-decoding and data mangling:
  ```python
  Path("file.txt").write_text("café", encoding="utf-8")
  text = Path("file.txt").read_text(encoding="utf-8")
  ```
- Prefer context managers for I/O to ensure reliable cleanup.
- Use atomic write patterns to avoid partial files:
  ```python
  from pathlib import Path
  import tempfile, os

  def atomic_write_text(path: Path, text: str) -> None:
      path = Path(path)
      with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                       dir=path.parent, delete=False) as tmp:
          tmp.write(text)
          tmp_name = tmp.name
      os.replace(tmp_name, path)
  ```

## Subprocess safety
- Never interpolate untrusted strings into shell commands.
  ```python
  import subprocess

  # Dangerous: shell injection
  # subprocess.run(f"grep {user_input} file.txt", shell=True)

  # Safer: pass argv list, no shell
  subprocess.run(["grep", user_input, "file.txt"], check=True)
  ```
- If shell features are unavoidable, validate/whitelist inputs rigorously; still prefer avoiding the shell.
- Use check=True to surface failures; set explicit timeouts where appropriate; control environment if needed.

## Secrets management and configuration
- Do not hard-code secrets or commit real secrets (including .env files). Load from environment/secret managers:
  ```python
  import os
  API_KEY = os.environ["API_KEY"]  # Raises if missing (fail fast)
  ```
- Do not log secrets or include them in exceptions.
- Validate configuration at startup and fail fast with clear errors:
  ```python
  from dataclasses import dataclass
  @dataclass(frozen=True)
  class Settings:
      host: str
      port: int

  def load_settings(env: dict[str, str]) -> Settings:
      host = env.get("HOST", "localhost")
      port = int(env.get("PORT", "8000"))
      if not 1 <= port <= 65535:
          raise ValueError("invalid port")
      return Settings(host, port)
  ```

## Networking and HTTP client hardening
- Always set timeouts; handle status codes and parse errors explicitly:
  ```python
  import requests
  resp = requests.get("https://api.example.com/data", timeout=10)
  resp.raise_for_status()
  data = resp.json()
  ```
- Reuse sessions for connection pooling and consistent headers; implement bounded retries with backoff and jitter for transient failures; respect rate limits where applicable.
- Validate incoming/outgoing JSON schemas and constrain sizes/depth to mitigate resource exhaustion.

## Dependency and supply-chain security
- Risks: typosquatting, compromised maintainers, malicious releases, vulnerable transitives, abandoned packages.
- Practices:
  - Use reputable packages; avoid untrusted sources.
  - For applications: pin or lock exact versions (or use constraints) for reproducibility.
  - For libraries: specify compatible version ranges to avoid over-constraining downstream users.
  - Review dependency diffs; update regularly.
  - Use vulnerability scanners (e.g., pip-audit, Safety, OSV-Scanner) and ecosystem services (e.g., Dependabot).
  - Consider hash-pinned installs for high-assurance deployments.
- Keep build-system pinned and avoid executing arbitrary code at import time (top-level side effects).

## Logging, errors, and observability
- Use logging instead of print; libraries should not globally configure logging.
  ```python
  import logging
  logger = logging.getLogger(__name__)
  logger.info("started")  # Avoid f-strings for expensive formatting at disabled levels
  ```
- Do not log secrets or excessive PII.
- Preserve exception context with raise ... from exc; add notes for better diagnostics when safe.
- Avoid broad except blocks that hide real errors; catch specific exceptions.
- Structured logs improve machine processing; ensure sensitive fields are excluded.

## Data validation and parsing
- Validate all untrusted inputs (types, ranges, formats). Fail fast with explicit exceptions.
  ```python
  def parse_age(text: str) -> int:
      try:
          age = int(text)
      except ValueError as exc:
          raise ValueError(f"Invalid age: {text!r}") from exc
      if age < 0:
          raise ValueError("age must be non-negative")
      return age
  ```
- Remember type hints are not runtime checks; add explicit validation as needed.

## Safe templates and f-strings
- F-strings are evaluated at compile time from source code expressions you write; they are not user-expression templates. Do not splice untrusted expressions into evaluable contexts.

## Environment isolation and reproducibility
- Use virtual environments per project; install via python -m pip to target the intended interpreter.
- For applications: lock or pin versions; for libraries: declare compatible ranges and test across supported Python versions.
- Use src/ layout for distributable packages to avoid import path confusion during tests.
- CI should install from declared metadata in a clean environment and run tests, linters, type checkers, and build verifications.

## Testing and automation for security
- Add pre-commit hooks for fast quality gates (format, lint, basic file checks, secret detection).
- CI should run tests, linting, type checking, coverage, build verification, and vulnerability scans in clean environments.
- Separate unit from integration/e2e tests; mock external services judiciously; avoid flaky tests.

## Serialization choices
- JSON for interoperable, untrusted data; validate and bound sizes/depth.
- CSV via csv module (with newline="" and explicit encoding); never manual split for real CSV.
- Datetimes: use timezone-aware UTC and ISO 8601 for serialization.
- Avoid pickle for untrusted inputs; restrict to trusted internal persistence if used.

## Additional safe patterns
- Context managers for resource safety (files, locks, transactions).
- Use pathlib for path correctness and clarity.
- Use with subprocess and files to ensure cleanup even on exceptions.
- Prefer properties or dataclasses for controlled attribute access and validation.

## Code templates (safe defaults)
- Path traversal guard (as above).
- Subprocess without shell (as above).
- Atomic file write (as above).
- Configuration parsing with validation (as above).

## Key Points
- Never execute or deserialize untrusted code/data with eval/exec/pickle; prefer JSON and explicit validation.
- Treat all user-influenced paths and subprocess inputs as hostile; use pathlib.resolve checks and argv lists (no shell).
- Keep secrets out of source and logs; load from environment/secret managers and validate configuration at startup.
- Manage supply-chain risk: isolate environments, pin/lock (apps) vs compatible ranges (libs), scan dependencies, and avoid untrusted sources.
- Network clients must set timeouts, check statuses, and validate payloads; logging and error handling should preserve context without leaking sensitive data.