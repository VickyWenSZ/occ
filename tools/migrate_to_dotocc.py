"""
One-shot migration to the unified ~/.occ/ layout.

Moves every legacy service file/directory into its canonical home so that
fresh users get a clean install and existing users keep their state.

Idempotent: a sentinel `~/.occ/.migrated` stamp short-circuits subsequent
runs. Re-running by deleting the stamp is safe — every move is a "move
if source exists AND target doesn't", never a destructive overwrite.

Sources mapped to targets:

    ~/.occ_keys/                  -> ~/.occ/keys/
    ~/.occ_publisher/             -> ~/.occ/keys/publisher/
    ~/.occ_reindex_token          -> ~/.occ/secrets/reindex_token
    ~/.occ/config.json            (already correct location, untouched)
    <repo>/.env                   -> ~/.occ/secrets/env
    <repo>/.occ_chats.json        -> ~/.occ/state/chats.db   (SQLite)
    <repo>/deliberation_log.md    -> ~/.occ/state/deliberation.log
    <repo>/workspace/             -> ~/.occ/state/workspace/
    <repo>/upload/                -> ~/.occ/state/upload/
    <repo>/.occ_config.json       -> deleted (duplicate of ~/.occ/config.json)

Called automatically from the GUI server's init path; can also be run
standalone: `python tools/migrate_to_dotocc.py [--force]`.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from node import paths, chat_store  # noqa: E402


def _move_file(src: Path, dst: Path, log: list[str]) -> None:
    """Move a single file. If dst already exists, leave the source alone and
    log it — the target wins by virtue of being in the right place already."""
    if not src.exists() or not src.is_file():
        return
    if dst.exists():
        log.append(f"  skip (target exists): {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    log.append(f"  moved: {src} -> {dst}")


def _move_dir_contents(src_dir: Path, dst_dir: Path, log: list[str]) -> None:
    """Move every file inside src_dir into dst_dir. Empty src_dir is
    removed afterwards; non-empty (because targets already existed) is
    left alone."""
    if not src_dir.exists() or not src_dir.is_dir():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in list(src_dir.iterdir()):
        target = dst_dir / item.name
        if target.exists():
            log.append(f"  skip (target exists): {item} -> {target}")
            continue
        shutil.move(str(item), str(target))
        log.append(f"  moved: {item} -> {target}")
    try:
        # rmdir only succeeds when empty; that's the signal that
        # everything migrated. Failure is fine — something stayed behind
        # legitimately.
        src_dir.rmdir()
        log.append(f"  rmdir: {src_dir}")
    except OSError:
        pass


def migrate(force: bool = False) -> dict:
    """Run the migration. Returns a dict with counts + a per-step log."""
    stamp = paths.migration_stamp()
    if stamp.exists() and not force:
        return {"ok": True, "skipped": True, "log": [f"already migrated ({stamp})"]}

    log: list[str] = []
    home = Path.home()

    # ── ~/.occ_keys/* -> ~/.occ/keys/* ──────────────────────────────────────
    _move_dir_contents(home / ".occ_keys", paths.keys_dir(), log)

    # ── ~/.occ_publisher/* -> ~/.occ/keys/publisher/* ───────────────────────
    _move_dir_contents(home / ".occ_publisher", paths.publisher_keys_dir(), log)

    # ── ~/.occ_reindex_token -> ~/.occ/secrets/reindex_token ────────────────
    _move_file(home / ".occ_reindex_token", paths.reindex_token_file(), log)

    # ── <repo>/.env -> ~/.occ/secrets/env ───────────────────────────────────
    _move_file(REPO_ROOT / ".env", paths.env_file(), log)

    # ── <repo>/deliberation_log.md -> ~/.occ/state/deliberation.log ─────────
    _move_file(REPO_ROOT / "deliberation_log.md", paths.deliberation_log(), log)

    # ── <repo>/workspace/* -> ~/.occ/state/workspace/* ──────────────────────
    legacy_ws = REPO_ROOT / "workspace"
    if legacy_ws.exists() and legacy_ws.is_dir():
        _move_dir_contents(legacy_ws, paths.workspace_dir(), log)
        # Drop the .gitkeep we might have created if everything else moved
        try:
            (legacy_ws / ".gitkeep").unlink(missing_ok=True)
            legacy_ws.rmdir()
            log.append(f"  rmdir: {legacy_ws}")
        except OSError:
            pass

    # ── <repo>/upload/* -> ~/.occ/state/upload/* ────────────────────────────
    legacy_up = REPO_ROOT / "upload"
    if legacy_up.exists() and legacy_up.is_dir():
        _move_dir_contents(legacy_up, paths.upload_dir(), log)
        try:
            (legacy_up / ".gitkeep").unlink(missing_ok=True)
            legacy_up.rmdir()
            log.append(f"  rmdir: {legacy_up}")
        except OSError:
            pass

    # ── <repo>/.occ_chats.json -> ~/.occ/state/chats.db (SQLite import) ─────
    legacy_chats = REPO_ROOT / ".occ_chats.json"
    if legacy_chats.exists():
        result = chat_store.import_from_json(legacy_chats)
        log.append(
            f"  imported chats: {result.get('chats_imported', 0)} chats, "
            f"{result.get('messages_imported', 0)} messages"
        )
        # Rename rather than delete — gives a one-line escape hatch if the
        # user inspects the old data.
        backup = legacy_chats.with_suffix(".json.migrated")
        try:
            legacy_chats.rename(backup)
            log.append(f"  renamed: {legacy_chats} -> {backup}")
        except OSError:
            pass

    # ── <repo>/.occ_config.json: duplicate of ~/.occ/config.json, drop ─────
    legacy_cfg = REPO_ROOT / ".occ_config.json"
    if legacy_cfg.exists():
        try:
            legacy_cfg.unlink()
            log.append(f"  removed: {legacy_cfg} (duplicate of {paths.config_file()})")
        except OSError as e:
            log.append(f"  ! could not remove {legacy_cfg}: {e}")

    # ── Stamp ──────────────────────────────────────────────────────────────
    stamp.write_text(
        "OCC service paths migrated to ~/.occ/. Delete this file and re-run\n"
        "tools/migrate_to_dotocc.py --force to re-attempt the migration.\n",
        encoding="utf-8",
    )
    log.append(f"  stamped: {stamp}")
    return {"ok": True, "skipped": False, "log": log}


def main():
    force = "--force" in sys.argv[1:]
    result = migrate(force=force)
    if result.get("skipped"):
        print(result["log"][0])
        print("(re-run with --force to redo)")
        return
    for line in result["log"]:
        print(line)
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
