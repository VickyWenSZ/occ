"""
Persistent node identifier.

NODE_ID has to survive process restarts because the broker now binds
node_id ↔ Ed25519 signing key in its TOFU table. If NODE_ID regenerated
on every launch (the original behaviour) every restart would consume a
fresh row, the table would grow without bound, and any reputation/
stability stats keyed on node_id would never accumulate.

Stored under the shared service tree at `~/.occ/keys/node_id` (see
`node.paths` for the resolved location).
"""
import socket
import uuid

from node import paths


def _load_or_generate_node_id() -> str:
    f = paths.node_id_file()
    if f.exists():
        try:
            existing = f.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except Exception:
            pass
    fresh = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"
    try:
        f.write_text(fresh, encoding="utf-8")
    except Exception:
        # Best-effort: a write failure means we'll regenerate next run,
        # but the current process still has a working id.
        pass
    return fresh


NODE_ID = _load_or_generate_node_id()
