"""
Single source of truth for every OCC service path.

Layout (under `OCC_HOME`, defaults to `~/.occ`):

    ~/.occ/
    ├── keys/
    │   ├── private.key         # X25519 priv (E2E peer crypto)
    │   ├── public.key          # X25519 pub
    │   ├── signing.key         # Ed25519 priv (TOFU node identity)
    │   ├── signing.pub         # Ed25519 pub
    │   ├── node_id             # persistent node identifier
    │   └── publisher/          # pack publishing key (separate trust scope)
    │       ├── signing.key
    │       └── signing.pub
    ├── secrets/
    │   ├── env                 # OPENAI_API_KEY for Forge top-tier calls
    │   └── reindex_token       # broker /admin/reindex header value
    ├── state/
    │   ├── chats.db            # SQLite — replaces .occ_chats.json
    │   ├── deliberation.log    # multi-call deliberation transcript
    │   ├── workspace/          # write_file / run_code working dir
    │   └── upload/             # chat attachment store
    └── config.json             # OpenRouter key, model, local_mode, disabled_packs

Everything callers need is reachable from the typed getters below — never
hard-code `Path.home() / ".occ"` from anywhere else in the codebase.

Env override `OCC_HOME=/path/to/dir` repoints the whole tree (used by
tests and by power users who want OCC state on a different volume).
"""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_HOME = Path.home() / ".occ"
_OCC_HOME_ENV = "OCC_HOME"


def occ_home() -> Path:
    """Resolve the OCC service root, honouring the OCC_HOME env override."""
    raw = os.environ.get(_OCC_HOME_ENV, "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_HOME


def _restrict(path: Path, mode: int) -> None:
    """Best-effort chmod — POSIX honours, Windows ignores. Wrapped so a
    weird filesystem (read-only mount, network drive) can't break startup."""
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def _mkdir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _restrict(path, mode)
    return path


# ─── Top-level dirs ────────────────────────────────────────────────────────

def keys_dir() -> Path:
    """Directory holding the node's encryption + signing keypairs and node_id."""
    return _mkdir(occ_home() / "keys", 0o700)


def publisher_keys_dir() -> Path:
    """Directory holding the publisher Ed25519 keypair used to sign packs."""
    return _mkdir(keys_dir() / "publisher", 0o700)


def secrets_dir() -> Path:
    """Directory for credentials Forge / Hub read at runtime."""
    return _mkdir(occ_home() / "secrets", 0o700)


def state_dir() -> Path:
    """Directory for per-instance state (chats DB, log, workspace, upload)."""
    return _mkdir(occ_home() / "state", 0o755)


def workspace_dir() -> Path:
    """Working dir for write_file / run_code / list_files tools."""
    return _mkdir(state_dir() / "workspace", 0o755)


def upload_dir() -> Path:
    """Drop-target for files attached to a chat message."""
    return _mkdir(state_dir() / "upload", 0o755)


# ─── Individual files ──────────────────────────────────────────────────────

def x25519_private_key() -> Path:
    return keys_dir() / "private.key"


def x25519_public_key() -> Path:
    return keys_dir() / "public.key"


def ed25519_signing_key() -> Path:
    return keys_dir() / "signing.key"


def ed25519_signing_pub() -> Path:
    return keys_dir() / "signing.pub"


def node_id_file() -> Path:
    return keys_dir() / "node_id"


def publisher_signing_key() -> Path:
    return publisher_keys_dir() / "signing.key"


def publisher_signing_pub() -> Path:
    return publisher_keys_dir() / "signing.pub"


def env_file() -> Path:
    """`KEY=VALUE` lines (one per line). OPENAI_API_KEY lives here for Forge."""
    return secrets_dir() / "env"


def reindex_token_file() -> Path:
    return secrets_dir() / "reindex_token"


def chats_db() -> Path:
    return state_dir() / "chats.db"


def deliberation_log() -> Path:
    return state_dir() / "deliberation.log"


def config_file() -> Path:
    return occ_home() / "config.json"


def migration_stamp() -> Path:
    """Sentinel that tells the auto-migrator the legacy paths have already
    been moved. Once present, the migrator is a no-op."""
    return occ_home() / ".migrated"


# ─── Env-file loader ───────────────────────────────────────────────────────

def load_env_file() -> dict[str, str]:
    """Parse `secrets/env` as a `KEY=VALUE` map. Empty/missing file → {}.
    Lines starting with `#` and blank lines are skipped. Values aren't
    quote-stripped: write the file with the bare value (no surrounding `"`)."""
    p = env_file()
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            # Strip a single layer of surrounding quotes if the user wrote
            # KEY="value with spaces". Don't unescape; the value goes
            # straight into os.environ.
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            if k:
                out[k] = v
    except Exception:
        return {}
    return out


def apply_env_file_to_os_environ() -> None:
    """Read secrets/env and export every entry into os.environ for the rest
    of the process. Existing os.environ values WIN — explicit env always
    beats the file, so tests and CI can override freely."""
    for k, v in load_env_file().items():
        os.environ.setdefault(k, v)
