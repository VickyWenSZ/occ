"""
Persistent node identifier.

NODE_ID has to survive process restarts because the broker now binds
node_id ↔ Ed25519 signing key in its TOFU table (`node_identity.db`). If
NODE_ID regenerated on every launch (the original behaviour) every restart
would consume a fresh row and the table would grow without bound. Worse,
the user's reputation/stability stats keyed on node_id would never
accumulate — every reconnect would look like a brand-new peer.

The id is written once to `~/.occ_keys/node_id` and re-read on subsequent
runs. The directory is the same one that holds the encryption + signing
keys (perms restricted to the user in crypto.py).
"""
import socket
import uuid
from pathlib import Path

_NODE_ID_FILE = Path.home() / ".occ_keys" / "node_id"


def _load_or_generate_node_id() -> str:
    if _NODE_ID_FILE.exists():
        try:
            existing = _NODE_ID_FILE.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except Exception:
            pass
    fresh = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"
    try:
        _NODE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _NODE_ID_FILE.write_text(fresh, encoding="utf-8")
    except Exception:
        # Best-effort: a write failure means we'll regenerate next run,
        # but the current process still has a working id.
        pass
    return fresh


NODE_ID = _load_or_generate_node_id()
