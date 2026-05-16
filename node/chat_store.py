"""
SQLite-backed chat store. Replaces the monolithic `.occ_chats.json` file.

Why SQLite: the JSON file got fully read+rewritten on every message,
turning a routine ~10 KB append into hundreds of MB of churn once the
file passed a few MB. With SQLite each add_message is one INSERT.

Schema kept deliberately lean — we still serialize the rich fields
(attachments, tools, peer_answers) as JSON because the GUI consumes them
opaquely and a strict relational model would only add migration friction
without runtime benefit.

Public API mirrors the previous in-file helpers in server.py so the
caller code stays untouched:

    list_chats() -> list[{"id","title","created_at"}]
    create_chat(chat_id, title, created_at) -> dict
    get_chat(chat_id) -> dict | None       # includes "messages": [...]
    delete_chat(chat_id) -> None
    delete_all_chats() -> None
    rename_chat(chat_id, new_title) -> str | None
    add_message(chat_id, role, content, ...) -> None
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from node import paths

# Single global connection guarded by a lock. SQLite handles concurrent
# readers fine, but writes from multiple threads need serialisation. Using
# one connection + a Python lock is the simplest correct pattern for the
# moderate write rate here (one INSERT per chat message).
_LOCK = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """Lazily open the chats DB and create the schema on first call."""
    global _conn
    if _conn is not None:
        return _conn
    db_path = paths.chats_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    # WAL gives us non-blocking reads-during-writes and durability. Same
    # journal mode the broker uses for pack_search.db.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL DEFAULT 'New Chat',
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id            TEXT PRIMARY KEY,
            chat_id       TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            seq           INTEGER NOT NULL,
            role          TEXT NOT NULL,
            content       TEXT NOT NULL,
            timestamp     TEXT NOT NULL,
            routing       TEXT,
            attachments   TEXT,
            tools         TEXT,
            peer_answers  TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_chat_seq ON messages(chat_id, seq)"
    )
    _conn = conn
    return _conn


def _row_to_message(row: sqlite3.Row) -> dict:
    """Reassemble the rich message dict the GUI expects. Optional fields
    are only included when non-empty so the front-end doesn't have to
    distinguish 'missing' from 'empty array'."""
    msg: dict = {
        "id":        row["id"],
        "role":      row["role"],
        "content":   row["content"],
        "timestamp": row["timestamp"],
    }
    if row["routing"]:
        msg["routing"] = row["routing"]
    if row["attachments"]:
        try:
            msg["attachments"] = json.loads(row["attachments"])
        except Exception:
            pass
    if row["tools"]:
        try:
            msg["tools"] = json.loads(row["tools"])
        except Exception:
            pass
    if row["peer_answers"]:
        try:
            msg["peer_answers"] = json.loads(row["peer_answers"])
        except Exception:
            pass
    return msg


# ─── Public API ────────────────────────────────────────────────────────────

def list_chats() -> list[dict]:
    """Most-recent-first listing for the sidebar. Returns the lean view
    (no messages) — the GUI calls get_chat(id) when the user opens one."""
    with _LOCK:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, title, created_at FROM chats ORDER BY created_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]


def create_chat(chat_id: str | None = None, title: str = "New Chat",
                created_at: str | None = None) -> dict:
    """Insert a new chat, return the shape the existing endpoint returns."""
    cid = chat_id or str(uuid.uuid4())[:12]
    ts = created_at or datetime.now().isoformat()
    with _LOCK:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO chats (id, title, created_at) VALUES (?, ?, ?)",
            (cid, title, ts),
        )
    return {"id": cid, "title": title, "created_at": ts}


def get_chat(chat_id: str) -> dict | None:
    """Full chat including its messages in insertion order."""
    with _LOCK:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, title, created_at FROM chats WHERE id = ?",
            (chat_id,),
        )
        head = cur.fetchone()
        if head is None:
            return None
        cur = conn.execute(
            "SELECT id, role, content, timestamp, routing, attachments, tools, peer_answers "
            "FROM messages WHERE chat_id = ? ORDER BY seq ASC",
            (chat_id,),
        )
        messages = [_row_to_message(r) for r in cur.fetchall()]
    return {
        "id":         head["id"],
        "title":      head["title"],
        "created_at": head["created_at"],
        "messages":   messages,
    }


def delete_chat(chat_id: str) -> None:
    with _LOCK:
        conn = _get_conn()
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))


def delete_all_chats() -> None:
    with _LOCK:
        conn = _get_conn()
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM chats")


def rename_chat(chat_id: str, new_title: str) -> str | None:
    """Return the saved title or None when the chat doesn't exist."""
    title = (new_title or "").strip() or "New Chat"
    with _LOCK:
        conn = _get_conn()
        cur = conn.execute(
            "UPDATE chats SET title = ? WHERE id = ?", (title, chat_id),
        )
        if cur.rowcount == 0:
            return None
    return title


def add_message(
    chat_id: str,
    role: str,
    content: str,
    routing: str = "",
    attachments: list | None = None,
    tools: list | None = None,
    peer_answers: dict | None = None,
) -> None:
    """Append a message to chat_id. Auto-promotes the chat title to the
    first user message's content (preserves the prior JSON behaviour)."""
    msg_id = str(uuid.uuid4())[:8]
    ts = datetime.now().isoformat()
    attachments_s = json.dumps(attachments) if attachments else None
    tools_s = json.dumps(tools) if tools else None
    peer_s = json.dumps(peer_answers) if peer_answers else None
    with _LOCK:
        conn = _get_conn()
        # Verify the chat exists — silently no-op if not (matches old loop
        # behaviour which simply found no matching c["id"]).
        cur = conn.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,))
        if cur.fetchone() is None:
            return
        # Next seq within this chat
        cur = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE chat_id = ?",
            (chat_id,),
        )
        seq = cur.fetchone()[0]
        conn.execute(
            "INSERT INTO messages "
            "(id, chat_id, seq, role, content, timestamp, routing, attachments, tools, peer_answers) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (msg_id, chat_id, seq, role, content, ts,
             routing or None, attachments_s, tools_s, peer_s),
        )
        # First user message defines the chat title.
        if role == "user" and seq == 0:
            title = (content or "")[:60].strip() or "New Chat"
            conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))


# ─── Migration helper ─────────────────────────────────────────────────────

def import_from_json(json_path: Path) -> dict:
    """One-shot import of the old `.occ_chats.json` schema. Idempotent on
    the per-chat level: chats that already exist in SQLite are skipped, so
    re-running after a partial import doesn't duplicate messages."""
    if not json_path.exists():
        return {"chats_imported": 0, "messages_imported": 0}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {"chats_imported": 0, "messages_imported": 0, "error": "malformed json"}
    if not isinstance(data, list):
        return {"chats_imported": 0, "messages_imported": 0, "error": "not a list"}

    chats_imported = 0
    messages_imported = 0
    with _LOCK:
        conn = _get_conn()
        for chat in data:
            if not isinstance(chat, dict):
                continue
            cid = chat.get("id")
            if not cid:
                continue
            cur = conn.execute("SELECT 1 FROM chats WHERE id = ?", (cid,))
            if cur.fetchone() is not None:
                continue
            conn.execute(
                "INSERT INTO chats (id, title, created_at) VALUES (?, ?, ?)",
                (cid, chat.get("title", "New Chat"),
                 chat.get("created_at", datetime.now().isoformat())),
            )
            chats_imported += 1
            messages = chat.get("messages", []) or []
            for seq, m in enumerate(messages):
                if not isinstance(m, dict):
                    continue
                conn.execute(
                    "INSERT INTO messages "
                    "(id, chat_id, seq, role, content, timestamp, routing, attachments, tools, peer_answers) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        m.get("id") or str(uuid.uuid4())[:8],
                        cid, seq,
                        m.get("role", "user"),
                        m.get("content", ""),
                        m.get("timestamp", datetime.now().isoformat()),
                        m.get("routing") or None,
                        json.dumps(m["attachments"]) if m.get("attachments") else None,
                        json.dumps(m["tools"]) if m.get("tools") else None,
                        json.dumps(m["peer_answers"]) if m.get("peer_answers") else None,
                    ),
                )
                messages_imported += 1
    return {"chats_imported": chats_imported, "messages_imported": messages_imported}
