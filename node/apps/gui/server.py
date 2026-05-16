"""
OCC Node GUI — FastAPI server.
Run: python node/apps/gui/server.py
Then open: http://localhost:7891
"""
import asyncio
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATIC = Path(__file__).parent / "static"
sys.path.insert(0, str(ROOT))

from node import chat_store, paths
from node.apps.cli.config import Config, save_openrouter_config
from node.apps.gui import log_bus
from node.deliberation.classifier import classify, detect_multi_intent
from node.deliberation.engine import DeliberationEngine
from node.deliberation.tools import set_workspace, set_upload, set_packs_root
from node.expert_runtime.pack import load_all_packs, load_pack, MultiPackRetriever

app = FastAPI()
STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ── CSRF / cross-origin guard ─────────────────────────────────────────────────
# The Node GUI binds to 127.0.0.1 (see __main__ at bottom) and has no auth.
# A malicious page open in the user's browser could still POST to
# http://localhost:7891 via fetch(). Block any state-changing request whose
# Origin header doesn't match a known local origin. GET/HEAD pass through so
# normal page loads still work; same-origin GUI requests carry Origin
# http://localhost:7891 / http://127.0.0.1:7891.
_ALLOWED_ORIGINS = frozenset({
    "http://localhost:7891",
    "http://127.0.0.1:7891",
})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@app.middleware("http")
async def _csrf_origin_guard(request, call_next):
    if request.method not in _SAFE_METHODS:
        origin = request.headers.get("origin", "")
        # No Origin → request didn't come from a browser script that knows
        # cross-origin rules (curl, internal calls, same-origin form). Allow.
        # With Origin set, require it to match a known local origin.
        if origin and origin not in _ALLOWED_ORIGINS:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "cross-origin request blocked"}, status_code=403)
    return await call_next(request)

# ── Global state ──────────────────────────────────────────────────────────────

_cfg: Config | None = None
_engine: DeliberationEngine | None = None
_retriever: MultiPackRetriever | None = None
_model: str = ""
_ready = False
_init_status = "starting"

# ── Chat storage ──────────────────────────────────────────────────────────────
# Thin shims that delegate to node.chat_store (SQLite). Kept here so the
# rest of server.py keeps its old call sites unchanged; refactoring those
# would have ballooned the diff with no behaviour change.


def _get_chat(chat_id: str) -> dict | None:
    return chat_store.get_chat(chat_id)


def _add_message_to_chat(
    chat_id: str,
    role: str,
    content: str,
    routing: str = "",
    attachments: list | None = None,
    tools: list | None = None,
    peer_answers: dict | None = None,
):
    chat_store.add_message(
        chat_id, role, content,
        routing=routing,
        attachments=attachments,
        tools=tools,
        peer_answers=peer_answers,
    )


# ── Startup init ──────────────────────────────────────────────────────────────

def _init():
    global _cfg, _engine, _retriever, _model, _ready, _init_status

    _init_status = "migrating service paths"
    # Move legacy scattered paths (~/.occ_keys, ~/.occ_publisher, repo-side
    # .env / chats / workspace / upload) into the unified ~/.occ/ tree.
    # Idempotent — a stamp file makes subsequent boots a no-op.
    try:
        from tools.migrate_to_dotocc import migrate as _migrate
        result = _migrate()
        if not result.get("skipped") and result.get("log"):
            for line in result["log"]:
                log_bus.write(f"[migrate] {line.strip()}")
    except Exception as e:
        log_bus.write(f"[migrate] WARN — migration step failed: {e}")

    _init_status = "loading config"
    log_bus.write("[GUI] Loading config...")
    # Surface ~/.occ/secrets/env into the process environment so anything
    # that reads OPENAI_API_KEY / GITHUB_TOKEN / ... via os.environ picks
    # them up. Existing env vars win — CI and tests still override freely.
    paths.apply_env_file_to_os_environ()
    _cfg = Config()
    _model = _cfg.model

    _init_status = "checking Ollama"
    from node.hardware import (
        is_ollama_installed, is_ollama_running, start_ollama,
        is_model_installed, pull_model_stream, OLLAMA_DOWNLOAD_URL,
    )

    if not is_ollama_installed():
        _init_status = "ollama_missing"
        log_bus.write(f"[GUI] Ollama not found. Download: {OLLAMA_DOWNLOAD_URL}")
        return

    if not is_ollama_running():
        log_bus.write("[GUI] Starting Ollama...")
        ok = start_ollama()
        if not ok:
            _init_status = "ollama_start_failed"
            log_bus.write("[GUI] Could not start Ollama. Run 'ollama serve' manually.")
            return

    if not is_model_installed(_model):
        log_bus.write(f"[GUI] Model {_model} not found — downloading...")
        _init_status = f"downloading {_model}"
        try:
            for status, completed, total in pull_model_stream(_model):
                if total and total > 0:
                    pct = int(completed / total * 100)
                    _init_status = f"downloading {_model} — {pct}%"
                elif status:
                    _init_status = f"downloading {_model} — {status}"
        except Exception as e:
            _init_status = "model_download_failed"
            log_bus.write(f"[GUI] Download failed: {e}")
            return
        log_bus.write(f"[GUI] Model {_model} ready.")

    _init_status = "loading packs"
    log_bus.write("[GUI] Loading expert packs...")
    workspace = paths.workspace_dir()
    set_workspace(workspace)
    upload = paths.upload_dir()
    set_upload(upload)
    set_packs_root(_cfg.packs_root)

    if _cfg.pack_name:
        pack_path = _cfg.packs_root / _cfg.pack_name
        _retriever = MultiPackRetriever([load_pack(pack_path)])
    else:
        _retriever = load_all_packs(_cfg.packs_root)

    n_packs = len(_retriever.packs) if _retriever else 0
    log_bus.write(f"[GUI] Loaded {n_packs} pack(s): {_retriever.name if _retriever else 'none'}")

    _init_status = "starting broker agent"
    _start_broker_agent_background()

    _init_status = "loading model"
    log_bus.write(f"[GUI] Warming up model: {_model}...")
    _warmup_model()

    _engine = DeliberationEngine(
        model=_model,
        expert_pack=_retriever,
        num_ctx_answer=_cfg.num_ctx_answer,
        num_ctx_synth=_cfg.num_ctx_synth,
        retrieval_chars=_cfg.retrieval_chars,
        domains=_retriever.domains if _retriever else [],
        workspace=workspace,
        openrouter_key=_cfg.openrouter_api_key,
        openrouter_model=_cfg.openrouter_model,
        local_mode=_cfg.local_mode,
        skills_dir=ROOT / "skills",
        packs_root=_cfg.packs_root,
    )

    _ready = True
    _init_status = "ready"
    or_label = f" · OpenRouter: {_cfg.openrouter_model}" if _cfg.openrouter_api_key else ""
    log_bus.write(f"[GUI] Node ready. Model: {_model}{or_label}")


def _warmup_model():
    import ollama
    try:
        list(ollama.chat(
            model=_model,
            messages=[{"role": "user", "content": "hi"}],
            think=False,
            keep_alive=-1,
            options={"num_predict": 1},
            stream=True,
        ))
        log_bus.write(f"[GUI] Model loaded into memory.")
    except Exception as e:
        log_bus.write(f"[GUI] Warmup warning: {e}")


def _start_broker_agent_background():
    from node.server import broker_agent

    def _thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(broker_agent.run())

    threading.Thread(target=_thread, daemon=True).start()


@app.on_event("startup")
async def _startup():
    """Set the log bus loop to uvicorn's loop, then kick off background init."""
    log_bus.set_loop(asyncio.get_event_loop())
    threading.Thread(target=_init, daemon=True).start()

# ── Routes — static ───────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


# ── Routes — status & config ──────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    from node.hardware import OLLAMA_DOWNLOAD_URL
    error_states = {"ollama_missing", "ollama_start_failed", "model_download_failed"}
    return {
        "ready": _ready,
        "status": _init_status,
        "model": _model,
        "error": _init_status if _init_status in error_states else None,
        "ollama_download_url": OLLAMA_DOWNLOAD_URL,
    }


@app.get("/api/gpu_stats")
async def get_gpu_stats():
    from node.hardware import gpu_utilization_pct
    loop = asyncio.get_event_loop()
    pct = await loop.run_in_executor(None, gpu_utilization_pct)
    return {"gpu_pct": pct}


@app.get("/api/config")
async def get_config():
    if not _cfg:
        raise HTTPException(503, "Not ready")
    from node.retrieval import local_index
    from node.apps.cli.config import load_disabled_packs
    return {
        "model": _model,
        "hardware_profile": _cfg.hardware_profile,
        "detected_vram_gb": _cfg.detected_vram_gb,
        "num_ctx_answer": _cfg.num_ctx_answer,
        "openrouter_configured": bool(_engine.or_key if _engine else _cfg.openrouter_api_key),
        "openrouter_key_saved": bool(_cfg.openrouter_api_key),
        "openrouter_model": _cfg.openrouter_model,
        "packs": [{"name": p.name, "domains": p.domains} for p in (_retriever.packs if _retriever else [])],
        # Full pack_paths on disk (recursive, includes nested layouts) and the
        # subset currently disabled by the user. Used by the Knowledge Source
        # panel to render enable/disable chip toggles.
        "pack_paths": local_index.list_pack_paths(_cfg.packs_root),
        "disabled_packs": load_disabled_packs(),
        "local_mode": _cfg.local_mode,
    }


class OpenRouterBody(BaseModel):
    api_key: str | None = None
    model: str


@app.post("/api/config/openrouter")
async def set_openrouter(body: OpenRouterBody):
    global _cfg
    # api_key=None means "keep existing key, only update model"
    if body.api_key is None:
        existing_key = _cfg.openrouter_api_key if _cfg else ""
        save_openrouter_config(existing_key, body.model)
        effective_key = existing_key
    else:
        save_openrouter_config(body.api_key, body.model)
        effective_key = body.api_key
    _cfg = Config()
    if _engine:
        _engine.or_key = effective_key
        _engine.or_model = body.model
    return {"ok": True}


class LocalModeBody(BaseModel):
    enabled: bool


@app.post("/api/config/local_mode")
async def set_local_mode(body: LocalModeBody):
    global _cfg
    from node.apps.cli.config import save_local_mode
    save_local_mode(body.enabled)
    _cfg = Config()
    if _engine:
        _engine._local_mode = body.enabled
    # Toggling local mode ON kicks a background reindex so the FTS5 index
    # reconciles with the filesystem — anything the user removed by hand
    # from expert-packs/ since the last reindex stops appearing in search.
    # Background: doesn't block the toggle response, doesn't crash if it fails.
    if body.enabled and _cfg is not None:
        try:
            from node.retrieval import local_index
            local_index.start_background_reindex(_cfg.packs_root)
            log_bus.write("[local-mode] toggled ON — background reindex started")
        except Exception as e:
            log_bus.write(f"[local-mode] background reindex failed to start: {e}")
    return {"ok": True, "local_mode": body.enabled}


@app.post("/api/local/reindex")
async def local_reindex():
    """Full rebuild of the local FTS5 index over the current packs_root.

    Forge and Lint already trigger an incremental reindex of the pack they
    touched. This endpoint exists for the rarer case where the user added or
    moved pack folders by hand and wants the local search to pick them up
    without a node restart. Returns the count of packs and pages indexed.
    """
    if not _cfg:
        raise HTTPException(503, "Not ready")
    from node.retrieval import local_index
    try:
        result = local_index.reindex_all(_cfg.packs_root)
    except Exception as e:
        raise HTTPException(500, f"Reindex failed: {e}")
    log_bus.write(f"[local-index] reindex complete: {result}")
    return {"ok": True, **result}


class DisabledPacksBody(BaseModel):
    disabled: list[str]


@app.get("/api/local/pack-state")
async def get_pack_state():
    """Return the full list of pack_paths on disk plus the disabled subset.
    The UI uses this to render which chips are 'loaded' vs 'unloaded'.
    Independent of the engine; reflects only what's persisted in config and
    what exists on disk right now."""
    if not _cfg:
        raise HTTPException(503, "Not ready")
    from node.retrieval import local_index
    from node.apps.cli.config import load_disabled_packs
    all_packs = local_index.list_pack_paths(_cfg.packs_root)
    return {
        "packs": all_packs,
        "disabled": load_disabled_packs(),
    }


@app.post("/api/local/pack-state")
async def set_pack_state(body: DisabledPacksBody):
    """Persist a new disabled-pack set. The engine reads this list fresh on
    every local-mode query, so toggle-off takes effect immediately — no
    rebuild required. Newly-enabled packs (present in the old disabled list
    but not in the new) trigger an incremental `reindex_pack` so packs pulled
    via `download_pack` become searchable on first activation."""
    if not _cfg:
        raise HTTPException(503, "Not ready")
    from node.apps.cli.config import load_disabled_packs, save_disabled_packs
    from node.retrieval import local_index

    old_disabled = set(load_disabled_packs())
    new_disabled = set(body.disabled)
    newly_enabled = old_disabled - new_disabled

    save_disabled_packs(list(new_disabled))

    indexed: list[dict] = []
    for pack_path in sorted(newly_enabled):
        try:
            result = local_index.reindex_pack(_cfg.packs_root, pack_path)
            indexed.append({"pack": pack_path, **result})
            log_bus.write(
                f"[pack-state] reindexed '{pack_path}' "
                f"({result.get('pages_indexed', 0)} pages)"
            )
        except Exception as e:
            log_bus.write(f"[pack-state] reindex_pack({pack_path}) failed: {e}")

    return {
        "ok": True,
        "disabled": sorted(new_disabled),
        "indexed": indexed,
    }


class OpenRouterActiveBody(BaseModel):
    active: bool


@app.post("/api/config/openrouter/active")
async def set_openrouter_active(body: OpenRouterActiveBody):
    """Toggle OpenRouter on/off in the engine without touching the saved key on disk."""
    global _cfg
    if not _cfg:
        raise HTTPException(503, "Not ready")
    if body.active:
        _cfg = Config()
        if _engine:
            _engine.or_key = _cfg.openrouter_api_key
            _engine.or_model = _cfg.openrouter_model
        return {"ok": True, "active": bool(_cfg.openrouter_api_key), "model": _cfg.openrouter_model}
    else:
        if _engine:
            _engine.or_key = ""
        return {"ok": True, "active": False}


# ── Routes — Update ───────────────────────────────────────────────────────────

@app.post("/api/update")
async def update_app(background_tasks: BackgroundTasks):
    try:
        await asyncio.create_subprocess_exec(
            "git", "remote", "set-url", "origin",
            "https://github.com/VickyWenSZ/occ.git",
            cwd=str(ROOT),
        )
        proc = await asyncio.create_subprocess_exec(
            "git", "pull", "--ff-only",
            cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        return {"updated": False, "message": "Timed out. Check your internet connection."}
    except Exception as e:
        return {"updated": False, "message": f"Error: {e}"}

    if proc.returncode != 0:
        err = stderr.decode().strip()
        return {"updated": False, "message": err or "git pull failed — is this a git repository?"}

    git_out = stdout.decode().strip()
    if "Already up to date" in git_out or "Already up-to-date" in git_out:
        return {"updated": False, "message": "Already up to date."}

    # Pick the right Python for pip install + restart:
    #   - If a venv exists (.venv/), always use it (the canonical OCC interpreter).
    #   - Otherwise fall back to the current process Python and warn the user
    #     that next launch will trigger the venv migration (handled by launch.bat).
    if os.name == "nt":
        venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = ROOT / ".venv" / "bin" / "python"

    target_python = str(venv_python) if venv_python.exists() else sys.executable
    venv_missing_warning = ""

    if venv_python.exists():
        pip = await asyncio.create_subprocess_exec(
            target_python, "-m", "pip", "install", "-r",
            str(ROOT / "node" / "requirements.txt"), "-q",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await pip.communicate()
    else:
        # Skip pip install — system Python likely lacks write perms (the very
        # reason we moved to a venv). The new launch.bat / launch.sh detect
        # the missing venv and run start.bat to migrate on next launch.
        venv_missing_warning = (
            "\n\nNote: this OCC was installed before the venv migration. "
            "Close OCC and reopen it from the Desktop shortcut — the next "
            "launch will set up the new environment and install dependencies."
        )

    background_tasks.add_task(_restart_server, target_python)
    return {"updated": True, "message": git_out + venv_missing_warning}


def _restart_server(target_python: str = ""):
    import time
    time.sleep(1.5)
    py = target_python or sys.executable
    os.execv(py, [py, str(Path(__file__).resolve())])


# ── Forge run registry ────────────────────────────────────────────────────────
#
# Long-running Forge / Scout-Forge / Lint runs live in an in-memory registry so
# that:
#   1. The browser can disconnect (tab switch / refresh) and reconnect later
#      without losing progress visibility — events are buffered.
#   2. A persistent UI banner can show "Forge running on pack X" across tabs.
#   3. The user can cooperatively STOP a run between sources, saving spend.
#
# A run keeps every event in `buffer` and broadcasts new events to all
# currently-attached subscriber queues. Stop is cooperative: the wrapper
# generator checks `stop_event` between yields, so a current LLM call finishes
# but no new ones are made.

import time as _time
import uuid as _uuid

_FORGE_RUNS: dict[str, dict] = {}
_RUNS_LOCK = threading.Lock()
_RUN_RETENTION_AFTER_DONE = 600   # keep finished runs visible for 10 min


def _evict_old_runs():
    now = _time.time()
    with _RUNS_LOCK:
        expired = []
        for rid, st in _FORGE_RUNS.items():
            done_at = st.get("ended_at")
            if done_at and (now - done_at) > _RUN_RETENTION_AFTER_DONE:
                expired.append(rid)
        for rid in expired:
            _FORGE_RUNS.pop(rid, None)


def _emit_run_event(state: dict, event: dict):
    """Append to the run's buffer and broadcast to all subscriber queues."""
    with _RUNS_LOCK:
        state["buffer"].append(event)
        subs = list(state["subscribers"])
    for (loop, q) in subs:
        try:
            asyncio.run_coroutine_threadsafe(q.put(event), loop)
        except Exception:
            pass


def _finalize_run(state: dict, terminal_status: str):
    state["status"] = terminal_status
    state["ended_at"] = _time.time()
    with _RUNS_LOCK:
        subs = list(state["subscribers"])
    for (loop, q) in subs:
        try:
            asyncio.run_coroutine_threadsafe(q.put(None), loop)
        except Exception:
            pass


def _start_managed_run(kind: str, pack_name: str, gen_factory) -> str:
    """
    Register a new run, start its thread, return the run_id.

    `gen_factory()` must return an iterator yielding either:
      - str  → wrapped as {"text": line}
      - dict → emitted as-is (use this for {"type": "forge_complete", ...})
    """
    _evict_old_runs()
    run_id = _uuid.uuid4().hex[:12]
    state = {
        "id":             run_id,
        "kind":           kind,            # "forge" | "lint" | "scout_forge"
        "pack_name":      pack_name,
        "started_at":     _time.time(),
        "ended_at":       None,
        "status":         "running",       # running | completed | failed | stopped
        "buffer":         [],
        "subscribers":    [],              # list of (asyncio.AbstractEventLoop, asyncio.Queue)
        "stop_event":     threading.Event(),
    }
    with _RUNS_LOCK:
        _FORGE_RUNS[run_id] = state

    def thread():
        try:
            for item in gen_factory():
                ev = item if isinstance(item, dict) else {"text": item}
                _emit_run_event(state, ev)
                if state["stop_event"].is_set():
                    _emit_run_event(state, {
                        "text": "🛑 Stop requested — exiting after current step.",
                    })
                    _finalize_run(state, "stopped")
                    return
            _finalize_run(state, "completed")
        except Exception as exc:
            _emit_run_event(state, {"text": f"❌ Error: {exc}"})
            _finalize_run(state, "failed")

    threading.Thread(target=thread, daemon=True).start()
    return run_id


async def _stream_run_sse(run_id: str):
    """SSE generator: replay the run's buffer, then tail live events."""
    state = _FORGE_RUNS.get(run_id)
    if not state:
        yield f"data: {json.dumps({'type':'error','text':'Run not found.'})}\n\n"
        return

    # Announce the run on the wire first so the client always knows the id
    yield f"data: {json.dumps({'type':'run_started','run_id':run_id,'kind':state['kind'],'pack_name':state['pack_name'],'started_at':state['started_at']})}\n\n"

    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()

    with _RUNS_LOCK:
        snapshot = list(state["buffer"])
        running = state["status"] == "running"
        if running:
            state["subscribers"].append((loop, q))

    for ev in snapshot:
        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    if not running:
        yield f"data: {json.dumps({'type':'run_ended','status':state['status']})}\n\n"
        return

    try:
        while True:
            ev = await q.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
    finally:
        with _RUNS_LOCK:
            try:
                state["subscribers"].remove((loop, q))
            except ValueError:
                pass

    yield f"data: {json.dumps({'type':'run_ended','status':state['status']})}\n\n"


@app.get("/api/forge/runs")
async def list_forge_runs():
    """List active and recently-finished runs (used by the persistent banner)."""
    _evict_old_runs()
    now = _time.time()
    with _RUNS_LOCK:
        out = []
        for st in _FORGE_RUNS.values():
            elapsed = (st.get("ended_at") or now) - st["started_at"]
            out.append({
                "id":         st["id"],
                "kind":       st["kind"],
                "pack_name":  st["pack_name"],
                "status":     st["status"],
                "started_at": st["started_at"],
                "ended_at":   st["ended_at"],
                "elapsed_s":  int(elapsed),
                "events":     len(st["buffer"]),
            })
    # Most recent first
    out.sort(key=lambda r: r["started_at"], reverse=True)
    return out


@app.get("/api/forge/runs/{run_id}/status")
async def get_forge_run_status(run_id: str):
    state = _FORGE_RUNS.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found.")
    now = _time.time()
    return {
        "id":         state["id"],
        "kind":       state["kind"],
        "pack_name":  state["pack_name"],
        "status":     state["status"],
        "started_at": state["started_at"],
        "ended_at":   state["ended_at"],
        "elapsed_s":  int((state.get("ended_at") or now) - state["started_at"]),
        "events":     len(state["buffer"]),
    }


@app.get("/api/forge/runs/{run_id}/stream")
async def stream_forge_run(run_id: str):
    """SSE: replay buffered events for this run, then tail live ones."""
    return StreamingResponse(
        _stream_run_sse(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/forge/runs/{run_id}/stop")
async def stop_forge_run(run_id: str):
    state = _FORGE_RUNS.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found.")
    if state["status"] != "running":
        return {"ok": True, "already": state["status"]}
    state["stop_event"].set()
    return {"ok": True, "status": "stopping"}


# ── Routes — Forge ────────────────────────────────────────────────────────────

@app.get("/api/forge/packs")
async def forge_list_packs():
    import yaml
    packs_root = ROOT / "expert-packs"
    result = []
    if packs_root.exists():
        for pack_dir in sorted(packs_root.iterdir()):
            if pack_dir.is_dir() and (pack_dir / "wiki").exists():
                manifest_path = pack_dir / "manifest.yaml"
                sources = []
                if manifest_path.exists():
                    try:
                        with open(manifest_path, encoding="utf-8") as f:
                            mf = yaml.safe_load(f) or {}
                        sources = mf.get("sources", [])
                    except Exception:
                        pass
                raw_articles_dir = pack_dir / "raw" / "articles"
                raw_count = sum(
                    1 for f in raw_articles_dir.glob("*.md")
                    if f.name != "_index.md"
                ) if raw_articles_dir.exists() else 0
                result.append({
                    "name": pack_dir.name,
                    "source_count": len(sources),
                    "raw_count": raw_count,
                    "sources": [
                        {"url": s.get("url", "?"), "fetched": s.get("fetched", "?")}
                        for s in sources
                    ],
                })
    return result


class ForgeRunBody(BaseModel):
    pack_name: str
    mode: str = "add"
    extract_model: str = "openai/gpt-5-mini"
    model: str = "openai/gpt-5-mini"
    files: list[dict] = []
    urls: list[str] = []
    text: str = ""
    fetch_images: bool = False
    fetch_math: bool = False


@app.post("/api/forge/run")
async def forge_run(body: ForgeRunBody):
    if not _cfg:
        raise HTTPException(503, "Not ready")
    if not _cfg.openrouter_api_key:
        raise HTTPException(400, "OpenRouter API key not configured. Add it in Settings → OpenRouter.")

    pack_name_clean = re.sub(r'[^a-z0-9-]', '-', body.pack_name.strip().lower()).strip('-')

    def gen_factory():
        for line in _forge_run_core(body):
            yield line
        # Refresh the local FTS5 index for this pack so retrieval picks up
        # newly written pages without waiting for a node restart.
        try:
            from node.retrieval import local_index
            local_index.reindex_pack(_cfg.packs_root, pack_name_clean)
        except Exception:
            pass
        yield {"type": "forge_complete", "pack_name": pack_name_clean}

    run_id = _start_managed_run("forge", pack_name_clean, gen_factory)
    return StreamingResponse(
        _stream_run_sse(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _render_pack_scope_text(scope_key: str) -> str:
    """
    Resolve a scope chip identifier (overview/deep_dive/critique/...) into the
    descriptive paragraph Scout uses in its query-expansion prompts. Forge
    passes this string to extract_concepts() so the LLM applies the same
    filter at extraction time. Empty input → empty output (= no filter).
    """
    key = (scope_key or "").strip().lower()
    if not key:
        return ""
    try:
        from forge_scout.expand import SCOPE_RULES, _scope_block
        # _scope_block falls back to "overview" rules if key is unknown
        return _scope_block(key) if key in SCOPE_RULES else ""
    except Exception:
        return ""


def _forge_run_core(body: "ForgeRunBody"):
    """Blocking generator — runs in a thread, yields log lines."""
    os.environ["OPENROUTER_API_KEY"] = _cfg.openrouter_api_key

    import forge._llm as llm
    import forge._sources as sources
    import forge._wiki as wiki
    import forge._manifest as manifest

    pack_name = re.sub(r'[^a-z0-9-]', '-', body.pack_name.strip().lower()).strip('-')
    if not pack_name:
        yield "❌ Invalid pack name."
        return

    extract_model = body.extract_model
    write_model = body.model

    pack_dir = ROOT / "expert-packs" / pack_name
    wiki_dir = pack_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    # ── Sources too short produce hallucinated pages: LLM fills the gap from
    # training data instead of the source. We refuse to extract concepts from
    # raws with less than this many body chars. The raw stays on disk as a
    # citable reference; it just doesn't get its own wiki pages.
    MIN_RAW_CHARS_FOR_EXTRACTION = 1500

    rebuild   = body.mode == "rebuild"
    recompile = body.mode == "recompile"
    resume    = body.mode == "resume"

    if rebuild:
        concepts_dir = wiki_dir / "concepts"
        if concepts_dir.exists():
            shutil.rmtree(concepts_dir)
            yield "🗑️ Concepts deleted — starting from scratch."
        log_path = wiki_dir / "log.md"
        if log_path.exists():
            log_path.unlink()
        raw_articles_dir = pack_dir / "raw" / "articles"
        if raw_articles_dir.exists():
            shutil.rmtree(raw_articles_dir)
            yield "🗑️ Raw articles deleted — will re-fetch from sources."
        raw_index = pack_dir / "raw" / "_index.md"
        if raw_index.exists():
            raw_index.unlink()
        mf = manifest.load_or_create(pack_dir, pack_name)
        mf["sources"] = []
    elif recompile:
        # Wipe wiki pages but keep raw/ untouched (raw is immutable)
        concepts_dir = wiki_dir / "concepts"
        if concepts_dir.exists():
            shutil.rmtree(concepts_dir)
            yield "🗑️ Wiki pages cleared — recompiling from existing raw/ (no re-fetch)."
        mf = manifest.load_or_create(pack_dir, pack_name)
    elif resume:
        # Pick up where a previous interrupted run left off:
        # - Keep existing wiki/concepts (89 pages from a 3-hour run mustn't be lost)
        # - Load all raws from disk (same as recompile)
        # - Skip sources already recorded in wiki/log.md (the per-source completion marker)
        # - Let the existing post-process pass cross-link straggler pages with placeholders
        mf = manifest.load_or_create(pack_dir, pack_name)
    else:
        mf = manifest.load_or_create(pack_dir, pack_name)

    wiki.ensure_schema(wiki_dir, pack_name)
    all_pages = wiki.scan_existing_pages(wiki_dir)
    existing_slugs = {p["slug"] for p in all_pages}

    # ── Pack intent (scope + brief) drives scope-aware concept extraction.
    # Scout writes these into the manifest at Fetch time; standalone Forge
    # runs typically have neither, in which case extraction stays unbounded
    # (same behaviour as before this fix).
    pack_scope_text = _render_pack_scope_text(mf.get("scope") or "")
    pack_brief      = str(mf.get("brief") or "")
    if pack_scope_text or pack_brief:
        scope_label = (mf.get("scope") or "").strip() or "(custom)"
        brief_hint  = f", brief({len(pack_brief)} chars)" if pack_brief else ""
        yield f"🎯 Pack scope active: {scope_label}{brief_hint} — Forge will skip off-scope concepts."

    raw_sources = []
    temp_files_cleanup = []

    pdf_vision_model = extract_model if body.fetch_images else None

    # ── Recompile / Resume modes: load existing raw sources, ignore any new input ───
    if recompile or resume:
        raw_articles = pack_dir / "raw" / "articles"
        if not raw_articles.exists():
            mode_label = "Recompile" if recompile else "Resume"
            yield f"❌ {mode_label} requires existing raw/articles/ — none found. Use 'Add sources' first."
            return
        loaded = _load_existing_raws_as_sources(raw_articles)
        if not loaded:
            yield "❌ No usable raw sources found in raw/articles/."
            return
        if resume:
            completed = _completed_source_names_from_log(wiki_dir)
            before = len(loaded)
            loaded = [item for item in loaded if item[1] not in completed]
            skipped = before - len(loaded)
            if skipped:
                yield f"🔁 Resume: {skipped} source(s) already complete (from log.md), {len(loaded)} remaining to process."
            else:
                yield f"🔁 Resume: no completed sources found in log.md — processing all {len(loaded)}."
            if not loaded:
                yield "✅ All sources already complete. Running post-process only (cross-link stragglers + index + summary)."
        else:
            yield f"📚 Loaded {len(loaded)} existing raw source(s) for recompilation."
        raw_sources.extend(loaded)
        # Skip body.files / body.urls / body.text — we are re-using raw only
    else:
        # Hard cap per uploaded file. base64 inflates by 4/3, so 70 MB of
        # base64 ≈ 50 MB raw. Above this we refuse to decode rather than load
        # an arbitrary blob into memory.
        _FORGE_MAX_FILE_B64 = 70 * 1024 * 1024
        for f in body.files:
            try:
                b64_str = f.get("data_b64", "")
                if len(b64_str) > _FORGE_MAX_FILE_B64:
                    yield f"❌ {f.get('name', 'file')} exceeds the 50 MB upload limit — skipping."
                    continue
                data = base64.b64decode(b64_str)
                suffix = Path(f.get("name", "file.txt")).suffix or ".txt"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(data)
                tmp.close()
                temp_files_cleanup.append(tmp.name)
                is_pdf = suffix.lower() == ".pdf"
                note = " (PDF + vision fallback for low-text pages)" if is_pdf and pdf_vision_model else ""
                yield f"📂 Reading file: {f.get('name', 'file')}{note}..."
                text_content, name, url = sources.read_file(
                    Path(tmp.name),
                    vision_model=pdf_vision_model if is_pdf else None,
                )
                stem = Path(f.get("name", name)).stem
                name = re.sub(r'[^a-z0-9-]', '-', stem.lower()).strip('-') or name
                raw_sources.append((text_content, name, url))
            except Exception as e:
                yield f"❌ Error reading {f.get('name', 'file')}: {e}"

        for url in body.urls:
            url = url.strip()
            if not url:
                continue
            yield f"🌐 Fetching: {url}{' (math extraction ON)' if body.fetch_math else ''}..."
            try:
                text_content, name, fetched_url = sources.fetch_url(url, include_math=body.fetch_math)
                raw_sources.append((text_content, name, fetched_url))
            except Exception as e:
                err = str(e)
                if any(c in err for c in ["403", "401", "406"]):
                    yield f"⚠️ {url}\n   → Blocked ({err[:3]}). Try saving the page as a file."
                else:
                    yield f"❌ Error fetching {url}: {e}"

        if body.text and body.text.strip():
            yield "📝 Using text input..."
            raw_sources.append((body.text.strip(), "manual-text", "text://manual"))

    if not raw_sources:
        yield "❌ No sources found. Add files, URLs, or paste text."
        return

    total_written = 0
    touched_slugs: set[str] = set()

    try:
        for source_item in raw_sources:
            # In recompile mode, raw_sources entries carry an extra `raw_path` field
            if len(source_item) == 4:
                text_content, source_name, source_url, raw_path = source_item
                from_existing_raw = True
            else:
                text_content, source_name, source_url = source_item
                from_existing_raw = False

            yield f"\n━━━ Source: {source_name} ({len(text_content):,} chars) ━━━"

            if from_existing_raw:
                yield f"📂 Reusing existing raw → {raw_path}"
            else:
                raw_path = wiki.write_raw_source(pack_dir, source_name, source_url, text_content)
                yield f"💾 Raw source saved → {raw_path}"

            # ── Image pipeline (Phase 1: URL sources only, opt-in) ────────────
            available_images: list[dict] = []
            if body.fetch_images and not from_existing_raw and source_url.startswith(("http://", "https://")):
                assets_dir = wiki_dir / "assets" / source_name
                yield f"🖼️  Scanning {source_url} for images..."
                try:
                    candidates = sources.fetch_images_from_url(source_url, assets_dir)
                except Exception as e:
                    candidates = []
                    yield f"  ⚠️ Image scan failed: {e}"
                if candidates:
                    yield f"  📥 Downloaded {len(candidates)} candidate image(s) ≥5KB — captioning ({extract_model})..."
                    relevant = []
                    for img in candidates:
                        try:
                            verdict = llm.caption_image(img["path"], source_name, model=extract_model)
                        except Exception as e:
                            yield f"    ⚠️ {img['filename']} caption failed: {e}"
                            continue
                        if verdict.get("relevant"):
                            img["caption"] = verdict.get("caption", "")
                            img["page_rel_path"] = f"../assets/{source_name}/{img['filename']}"
                            relevant.append(img)
                            yield f"    ✅ {img['filename']}: {img['caption'][:80]}"
                        else:
                            try:
                                img["path"].unlink()
                            except Exception:
                                pass
                    if relevant:
                        wiki.append_images_to_raw(pack_dir, raw_path, relevant, source_name)
                        yield f"  📋 Kept {len(relevant)}/{len(candidates)} image(s); appended ## Images to raw"
                        available_images = relevant
                    else:
                        yield f"  ↪️ No relevant images after caption filter"
                else:
                    yield f"  ↪️ No image candidates ≥5KB"

            # ── Min-length guard: refuse to extract concepts from raws that
            # are too thin. Forces would-be hallucinations to remain just
            # citable references, not invented wiki pages.
            if len(text_content) < MIN_RAW_CHARS_FOR_EXTRACTION:
                yield (
                    f"⏭  Skipping concept extraction — source body is only "
                    f"{len(text_content)} chars (<{MIN_RAW_CHARS_FOR_EXTRACTION}). "
                    f"The raw stays as a citable reference; no wiki pages generated from it."
                )
                manifest.add_source(mf, source_url, sources.sha256(text_content))
                wiki.append_log(wiki_dir, source_name, 0, source_url)
                continue

            yield f"🔍 Extracting concepts ({extract_model})..."
            concepts = None
            for attempt in range(3):
                try:
                    concepts = llm.extract_concepts(
                        text_content,
                        existing_concepts=all_pages,
                        model=extract_model,
                        pack_scope_text=pack_scope_text,
                        pack_brief=pack_brief,
                    )
                    break
                except Exception as e:
                    yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."
            if not concepts:
                yield "❌ Concept extraction failed after 3 attempts, skipping source."
                continue

            labels = []
            for c in concepts:
                tag = " (→ updates existing)" if c.get("match_existing") else ""
                labels.append(f"{c.get('title', c.get('slug', '?'))}{tag}")
            yield f"💡 Found {len(concepts)} concepts: {', '.join(labels)}"

            written = 0
            for concept in concepts:
                # Resolve to existing slug if LLM matched it, else sanitize the new slug
                match = concept.get("match_existing")
                if match and match in existing_slugs:
                    slug = match
                else:
                    slug = re.sub(r'[^a-z0-9-]', '-', concept.get("slug", "unknown")).strip('-')
                concept["slug"] = slug
                title = concept.get("title", slug)

                existing_path = wiki_dir / "concepts" / wiki._slug_to_filename(slug)
                if existing_path.exists():
                    existing_content = existing_path.read_text(encoding="utf-8")
                    existing_sources = _existing_sources_from_frontmatter(existing_content)
                    # If the page already has sources AND the new raw is not among them,
                    # re-synthesize from scratch using all raws + the new one (avoids drift).
                    all_payload = []
                    if existing_sources and raw_path not in existing_sources:
                        all_payload = _build_sources_payload(pack_dir, existing_sources, raw_path, text_content, source_name)

                    if len(all_payload) >= 2:
                        yield f"🧬 Re-synthesizing: {title} (from {len(all_payload)} sources)..."
                        page_content = None
                        for attempt in range(3):
                            try:
                                raw_out = llm.synthesize_wiki_page(
                                    concept, all_payload,
                                    available_images=available_images,
                                    model=write_model,
                                )
                                page_content = wiki._normalize_llm_page_output(raw_out)
                                break
                            except Exception as e:
                                page_content = None
                                yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."
                    else:
                        yield f"✍️  Enriching: {title}..."
                        page_content = None
                        for attempt in range(3):
                            try:
                                raw_out = llm.update_wiki_page(
                                    concept, existing_content, text_content, source_name,
                                    raw_path=raw_path, available_images=available_images,
                                    model=write_model,
                                )
                                page_content = wiki._normalize_llm_page_output(raw_out)
                                break
                            except Exception as e:
                                page_content = None
                                yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."
                else:
                    yield f"✍️  Writing: {title}..."
                    page_content = None
                    for attempt in range(3):
                        try:
                            raw_out = llm.write_wiki_page(
                                concept, text_content, source_name,
                                raw_path=raw_path, available_images=available_images,
                                model=write_model,
                            )
                            page_content = wiki._normalize_llm_page_output(raw_out)
                            break
                        except Exception as e:
                            page_content = None
                            yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."

                if not page_content:
                    yield f"❌ '{title}' failed after 3 attempts, skipping."
                    continue

                if page_content.strip():
                    try:
                        wiki.write_page(wiki_dir, slug, page_content)
                    except ValueError as e:
                        yield f"  ❌ {title}: malformed LLM output ({e}) — skipping page"
                        continue
                    entry = {"slug": slug, "title": title, "summary": concept.get("summary", "")}
                    if slug not in existing_slugs:
                        all_pages.append(entry)
                        existing_slugs.add(slug)
                    else:
                        for p in all_pages:
                            if p["slug"] == slug:
                                p.update(entry)
                                break
                    touched_slugs.add(slug)
                    written += 1
                    total_written += 1
                    yield f"  ✅ {title} → concepts/{wiki._slug_to_filename(slug)}"
                else:
                    yield f"  ⚠️ {title}: empty response"

            manifest.add_source(mf, source_url, sources.sha256(text_content))
            wiki.append_log(wiki_dir, source_name, written, source_url)
            # Persist manifest immediately so a mid-run crash leaves an
            # accurate "what's done" record on disk. Was previously saved
            # only at the very end of the run — meaning a 3-hour run that
            # hung on the 13th source left an empty manifest.
            manifest.save(pack_dir, mf)

        # Cross-link pass — connect newly-written pages to the rest of the wiki.
        # Re-scan from disk first: `all_pages` holds the concept-extractor's
        # title/summary, but write_wiki_page rewrites both in the final
        # frontmatter. Using the in-memory list would feed the cross-link LLM
        # stale labels (and produce malformed wikilinks).
        # Straggler recovery: also pick up any page still bearing the
        # placeholder `_To be linked after compilation._` — those are leftover
        # from a previous session that was interrupted before its cross-link
        # pass could run. This makes the pipeline self-healing across restarts.
        disk_pages = wiki.scan_existing_pages(wiki_dir)
        slugs_needing_link: set[str] = set(touched_slugs)
        placeholder = "_To be linked after compilation._"
        for p in disk_pages:
            page_path = wiki_dir / "concepts" / wiki._slug_to_filename(p["slug"])
            if not page_path.exists():
                continue
            try:
                if placeholder in page_path.read_text(encoding="utf-8"):
                    slugs_needing_link.add(p["slug"])
            except Exception:
                pass

        if slugs_needing_link and len(disk_pages) > 1:
            stragglers = slugs_needing_link - touched_slugs
            label = f"{len(slugs_needing_link)} pages"
            if stragglers:
                label += f" ({len(touched_slugs)} new + {len(stragglers)} straggler{'s' if len(stragglers) != 1 else ''})"
            yield f"\n🔗 Cross-linking {label} ({extract_model})..."
            for slug in sorted(slugs_needing_link):
                page = next((p for p in disk_pages if p["slug"] == slug), None)
                if not page:
                    continue
                candidates = [p for p in disk_pages if p["slug"] != slug]
                try:
                    links = llm.suggest_cross_links(
                        page.get("title", slug),
                        page.get("summary", ""),
                        candidates,
                        model=extract_model,
                    )
                except Exception as e:
                    yield f"  ⚠️ {page.get('title', slug)}: cross-link skipped ({e})"
                    continue
                ok = wiki.fill_see_also(wiki_dir, slug, links)
                yield f"  🔗 {page.get('title', slug)} → {len(links)} link(s)" if ok else f"  · {page.get('title', slug)} → no links"

        fresh_pages = wiki.scan_existing_pages(wiki_dir)
        wiki.update_index(wiki_dir, fresh_pages)

        # Auto-finalize: run mechanical lint with fix=True until it converges.
        # The cross-link pass adds A→B but not B→A — the lint's autofix layer
        # writes reciprocal back-links and normalizes near-duplicate tags.
        # Looping handles cascading fixes (a new back-link may itself need
        # back-linking). Caps at 4 iterations so a pathological cycle can't
        # loop forever.
        try:
            from forge._lint import run_structural_checks as _lint_run
            yield "\n🔧 Auto-finalize: normalizing cross-references and tags..."
            for pass_num in range(1, 5):
                _issues, _summ = _lint_run(wiki_dir, pack_dir, fix=True)
                fixed = _summ.get("fixed", 0)
                if fixed == 0:
                    break
                yield f"  ↻ pass {pass_num}: auto-fixed {fixed} issue(s)"
            _, final_summ = _lint_run(wiki_dir, pack_dir, fix=False)
            yield (
                f"  ✅ Lint converged: "
                f"{final_summ.get('critical', 0)} critical, "
                f"{final_summ.get('warning', 0)} warning, "
                f"{final_summ.get('suggestion', 0)} suggestion."
            )
        except Exception as e:
            yield f"  ⚠️ Auto-finalize lint skipped: {e}"

        if fresh_pages:
            try:
                yield f"\n📝 Generating pack summary ({extract_model})..."
                mf["summary"] = llm.generate_pack_summary(pack_name, fresh_pages, model=extract_model)
                yield f"  ✅ Pack summary: {mf['summary'][:80]}..."
            except Exception as e:
                yield f"  ⚠️ Pack summary generation failed: {e} — manifest keeps previous summary"

        manifest.save(pack_dir, mf)

        yield f"\n🎉 Done! {total_written} pages written to expert-packs/{pack_name}/wiki/concepts/"
        yield f"📋 Index updated: {len(fresh_pages)} total pages in pack."

    finally:
        for tmp_path in temp_files_cleanup:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _existing_sources_from_frontmatter(page_text: str) -> list[str]:
    """Extract the `sources:` list (paths) from a wiki page's YAML frontmatter."""
    import re as _re
    m = _re.match(r"^---\n(.*?)\n---", page_text, _re.DOTALL)
    if not m:
        return []
    try:
        import yaml as _yaml
        fm = _yaml.safe_load(m.group(1)) or {}
    except Exception:
        return []
    sources = fm.get("sources") or []
    if not isinstance(sources, list):
        return []
    return [str(s).strip() for s in sources if str(s).strip()]


def _build_sources_payload(
    pack_dir: Path,
    existing_source_paths: list[str],
    new_raw_path: str,
    new_text: str,
    new_source_name: str,
) -> list[dict]:
    """
    Build the payload for synthesize_wiki_page: list of {name, text, raw_path}
    covering all existing sources (read from disk) + the new one (passed in).

    Skips existing sources whose file is missing on disk (best-effort).
    """
    import re as _re
    payload: list[dict] = []
    for s_path in existing_source_paths:
        full = pack_dir / s_path
        if not full.exists():
            continue
        text = full.read_text(encoding="utf-8", errors="replace")
        m = _re.match(r"^---\n.*?\n---\n?(.*)$", text, _re.DOTALL)
        body = m.group(1).strip() if m else text
        if not body:
            continue
        # Recover a friendly source_name from the filename (strip date prefix)
        stem = full.stem
        name = _re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem) or stem
        payload.append({"name": name, "text": body, "raw_path": s_path})
    payload.append({"name": new_source_name, "text": new_text, "raw_path": new_raw_path})
    return payload


def _completed_source_names_from_log(wiki_dir: Path) -> set[str]:
    """
    Parse `wiki/log.md` to recover the set of source names that have already
    been processed end-to-end by a previous Forge run. The log is appended by
    `wiki.append_log` only AFTER all concepts from a source are written, so
    presence here is a reliable "this source is done" marker even when the
    run crashed before saving the manifest.

    Entry format produced by append_log:
        ## [YYYY-MM-DD] ingest | <source-name>

    Returns an empty set if log.md does not exist or contains no entries.
    """
    import re as _re
    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        return set()
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()
    pattern = _re.compile(r"^##\s+\[[^\]]+\]\s+ingest\s+\|\s+(.+?)\s*$", _re.MULTILINE)
    return {m.group(1) for m in pattern.finditer(text)}


def _load_existing_raws_as_sources(raw_articles_dir: Path) -> list[tuple]:
    """
    Read every raw/articles/*.md and return a list of
    (text, source_name, source_url, raw_path) tuples for re-compilation.

    The 4-tuple form (vs the 3-tuple used for fresh ingestion) signals to
    `_forge_run_core` that the raw already exists on disk and must NOT be
    rewritten.
    """
    import re as _re
    out: list[tuple] = []
    pack_dir = raw_articles_dir.parent.parent  # raw/articles → pack root
    for f in sorted(raw_articles_dir.glob("*.md")):
        if f.name == "_index.md":
            continue
        full = f.read_text(encoding="utf-8", errors="replace")
        m = _re.match(r"^---\n(.*?)\n---\n?(.*)$", full, _re.DOTALL)
        if not m:
            continue
        try:
            import yaml as _yaml
            fm = _yaml.safe_load(m.group(1)) or {}
        except Exception:
            fm = {}
        body_text = m.group(2).strip()
        if not body_text:
            continue
        title = str(fm.get("title") or f.stem).strip()
        # Strip the date prefix from the slug to recover the source_name
        stem = f.stem
        stem_no_date = _re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
        source_name = stem_no_date or stem
        source_url = str(fm.get("source") or f.resolve().as_uri()).strip()
        rel_raw_path = f"raw/articles/{f.name}"
        out.append((body_text, source_name, source_url, rel_raw_path))
    return out


class ForgeLintBody(BaseModel):
    pack_name: str
    model: str = "gpt-5-mini"
    fix: bool = False
    skip_semantic: bool = False


@app.post("/api/forge/lint")
async def forge_lint(body: ForgeLintBody):
    if not _cfg:
        raise HTTPException(503, "Not ready")
    if not _cfg.openrouter_api_key:
        raise HTTPException(400, "OpenRouter API key not configured. Add it in Settings → OpenRouter.")

    pack_name = re.sub(r'[^a-z0-9-]', '-', body.pack_name.strip().lower()).strip('-')
    if not pack_name:
        raise HTTPException(400, "Invalid pack name.")

    pack_dir = ROOT / "expert-packs" / pack_name
    wiki_dir = pack_dir / "wiki"
    if not wiki_dir.exists():
        raise HTTPException(404, f"Pack '{pack_name}' not found.")

    def gen_factory():
        for line in _lint_run_core(
            pack_name, wiki_dir, pack_dir,
            model=body.model, fix=body.fix, skip_semantic=body.skip_semantic,
        ):
            yield line
        # Lint may rewrite pages, frontmatter, or the index — refresh the
        # local FTS5 entries for this pack so search reflects the new state.
        try:
            from node.retrieval import local_index
            local_index.reindex_pack(_cfg.packs_root, pack_name)
        except Exception:
            pass
        yield {"type": "lint_complete", "pack_name": pack_name}

    run_id = _start_managed_run("lint", pack_name, gen_factory)
    return StreamingResponse(
        _stream_run_sse(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _lint_run_core(pack_name: str, wiki_dir: Path, pack_dir: Path,
                   model: str, fix: bool = False, skip_semantic: bool = False):
    """
    Three-phase lint:
      1. Mechanical pre-screen (C1-C11 + M1-M2 + S1-S5 + Q1-Q4) — deterministic,
         optional auto-fix
      2. LLM-powered fixes (when fix=True) — currently: regenerate manifest.summary
         for packs that lack it. Uses the same model selected by the user.
      3. Semantic LLM audit — receives mechanical findings + populated
         manifest_summary as context. Ends with a clear visual VERDICT banner.
    """
    import forge._lint as lint
    import forge._llm as llm
    import forge._manifest as manifest
    import forge._wiki as wiki
    import yaml as _yaml

    # ── Phase 1: mechanical structural checks ─────────────────────────────────
    yield f"🔧 Running mechanical lint (structure, manifest, safety, quality)..."
    if fix:
        yield "    🛠️  Auto-fix enabled — fixable issues will be repaired in place"

    issues, summary = lint.run_structural_checks(wiki_dir, pack_dir, fix=fix)
    yield (
        f"    Found {summary['total']} issue(s): "
        f"{summary['critical']} critical, {summary['warning']} warning, "
        f"{summary['suggestion']} suggestion, {summary['info']} info"
    )
    if fix and summary["fixed"]:
        yield f"    ✅ Auto-fixed {summary['fixed']} issue(s)"

    # ── Phase 2: LLM-powered fix for M2 (manifest.summary missing) ────────────
    # Done before the structural report so the report shows M2 as fixed.
    if fix and _cfg.openrouter_api_key:
        m2_issues = [i for i in issues if i.get("code") == "M2" and not i.get("fixed")]
        if m2_issues:
            os.environ["OPENROUTER_API_KEY"] = _cfg.openrouter_api_key
            yield f"\n🤖 M2 needs LLM fix — regenerating manifest.summary ({model})..."
            try:
                fresh_pages = wiki.scan_existing_pages(wiki_dir)
                if not fresh_pages:
                    yield "    ⚠️  Pack has no pages — cannot regenerate summary."
                else:
                    new_summary = llm.generate_pack_summary(pack_name, fresh_pages, model=model)
                    if new_summary.strip():
                        mf = manifest.load_or_create(pack_dir, pack_name)
                        mf["summary"] = new_summary
                        manifest.save(pack_dir, mf)
                        for i in m2_issues:
                            i["fixed"] = True
                        summary["fixed"] += len(m2_issues)
                        yield f"    ✅ Wrote manifest.summary ({len(new_summary)} chars): {new_summary[:100]}..."
                    else:
                        yield (
                            "    ⚠️  LLM returned empty content — likely the model hit its "
                            "internal token budget before emitting the answer. "
                            "Try the Lint with a different model (e.g. GPT-5 instead of GPT-5 Mini)."
                        )
            except Exception as ex:
                yield f"    ❌ LLM fix failed: {ex}"

    yield "\n" + lint.format_report(issues, summary, pack_name, fix_applied=fix)

    # ── Phase 3: semantic LLM review ──────────────────────────────────────────
    if skip_semantic:
        yield from _emit_verdict_banner(None, summary)
        yield "✅ Lint complete (semantic phase skipped)."
        return

    if not _cfg.openrouter_api_key:
        yield "⚠️  Semantic phase skipped — OpenRouter API key not configured."
        yield from _emit_verdict_banner(None, summary)
        return

    os.environ["OPENROUTER_API_KEY"] = _cfg.openrouter_api_key

    yield f"\n🤖 Running semantic audit ({model}) — assessing safety, topic coherence, quality..."
    index_path = wiki_dir / "index.md"
    index_content = index_path.read_text(encoding="utf-8") if index_path.exists() else "(no index.md found)"

    # Load manifest.summary (may have just been regenerated in Phase 2).
    manifest_summary = ""
    mf_path = pack_dir / "manifest.yaml"
    if mf_path.exists():
        try:
            mf_data = _yaml.safe_load(mf_path.read_text(encoding="utf-8")) or {}
            manifest_summary = str(mf_data.get("summary", "") or "")
        except Exception:
            pass

    concepts_dir = wiki_dir / "concepts"
    pages_parts = []
    MAX_TOTAL = 80_000
    total_chars = 0
    if concepts_dir.exists():
        # Exclude folder-meta files like _index.md so the count matches what
        # index.md reports (only actual concept pages).
        concept_files = [pf for pf in sorted(concepts_dir.glob("*.md")) if not pf.name.startswith("_")]
        for pf in concept_files:
            content = pf.read_text(encoding="utf-8")
            chunk = f"\n### {pf.stem}\n{content}\n"
            if total_chars + len(chunk) > MAX_TOTAL:
                pages_parts.append(f"\n### (truncated — {len(concept_files)} total pages, limit reached)")
                break
            pages_parts.append(chunk)
            total_chars += len(chunk)

    pages_content = "".join(pages_parts) or "(no pages found)"

    report = llm.lint_wiki(
        pack_name, index_content, pages_content,
        model=model,
        manifest_summary=manifest_summary,
        mechanical_findings=issues,
    )
    yield "\n" + report
    yield from _emit_verdict_banner(report, summary)
    yield f"\n✅ Lint complete (mechanical + semantic)."


def _extract_llm_verdict(report: str) -> tuple[str, str]:
    """Parse the LLM's `## Overall Verdict` section. Returns (icon, label)."""
    m = re.search(r"##\s*Overall Verdict\s*\n+([^\n]+)", report or "")
    if not m:
        return ("⚠️", "Verdict unclear (LLM didn't follow format)")
    line = m.group(1).strip()
    low = line.lower()
    if "✅" in line or "safe to publish" in low:
        return ("✅", "Safe to publish")
    if "❌" in line or "do not publish" in low:
        return ("❌", "Do not publish")
    if "⚠️" in line or "concerns" in low:
        return ("⚠️", "Concerns — review required")
    return ("⚠️", "Verdict unclear")


def _emit_verdict_banner(llm_report: str | None, mech_summary: dict):
    """Emit a visually clear final banner with the lint verdict."""
    if llm_report is None:
        # Mechanical-only verdict, based purely on issue counts
        if mech_summary["critical"] > 0:
            icon, label = "❌", "Critical mechanical issues — do not publish"
        elif mech_summary["warning"] >= 5:
            icon, label = "⚠️", "Many warnings — review required"
        elif mech_summary["total"] == 0:
            icon, label = "✅", "Mechanical checks all clean"
        else:
            icon, label = "✅", "Minor warnings only — likely safe"
    else:
        icon, label = _extract_llm_verdict(llm_report)

    bar = "═" * 60
    yield ""
    yield bar
    yield ""
    yield f"  VERDICT   {icon}  {label.upper()}"
    yield ""
    yield (
        f"  Mechanical: {mech_summary['critical']} critical, "
        f"{mech_summary['warning']} warnings, "
        f"{mech_summary['suggestion']} suggestions"
    )
    if llm_report is not None:
        yield f"  Semantic:   {label}"
    if mech_summary.get("fixed", 0) > 0:
        yield f"  Auto-fixed: {mech_summary['fixed']} issue(s) repaired in place"
    yield ""
    yield bar


@app.post("/api/forge/reload-packs")
async def forge_reload_packs():
    global _retriever, _engine
    if not _cfg:
        raise HTTPException(503, "Not ready")
    _retriever = load_all_packs(_cfg.packs_root)
    workspace = ROOT / "workspace"
    _engine = DeliberationEngine(
        model=_model,
        expert_pack=_retriever,
        num_ctx_answer=_cfg.num_ctx_answer,
        num_ctx_synth=_cfg.num_ctx_synth,
        retrieval_chars=_cfg.retrieval_chars,
        domains=_retriever.domains if _retriever else [],
        workspace=workspace,
        openrouter_key=_cfg.openrouter_api_key,
        openrouter_model=_cfg.openrouter_model,
        local_mode=_cfg.local_mode,
        skills_dir=ROOT / "skills",
        packs_root=_cfg.packs_root,
    )
    n = len(_retriever.packs)
    log_bus.write(f"[GUI] Packs reloaded: {n} pack(s)")
    return {"ok": True, "packs": n}


@app.post("/api/forge/open-folder/{pack_name}")
async def forge_open_folder(pack_name: str):
    import platform, subprocess
    # Same slug rules as forge_run sanitises with — no slashes, no traversal,
    # no shell metas. Anything outside that alphabet is rejected outright.
    pack_name_clean = re.sub(r'[^a-z0-9-]', '-', pack_name.strip().lower()).strip('-')
    if not pack_name_clean or pack_name_clean != pack_name.strip().lower():
        raise HTTPException(400, "Invalid pack name")
    packs_root = (ROOT / "expert-packs").resolve()
    pack_dir = (packs_root / pack_name_clean).resolve()
    if not str(pack_dir).startswith(str(packs_root)):
        raise HTTPException(400, "Invalid pack path")
    if not pack_dir.exists():
        raise HTTPException(404, "Pack not found")
    system = platform.system()
    if system == "Windows":
        os.startfile(str(pack_dir))
    elif system == "Darwin":
        subprocess.Popen(["open", str(pack_dir)])
    else:
        subprocess.Popen(["xdg-open", str(pack_dir)])
    return {"ok": True}


# ── Routes — Forge Scout ──────────────────────────────────────────────────────

class ScoutSearchBody(BaseModel):
    topic: str
    mode: str = "wikipedia_first"           # wikipedia_first | multi_source
    langs: list[str] = ["en"]
    # Intent
    scope: str = "overview"                 # overview | deep_dive | critique | comparison | practical | custom
    brief: str = ""                         # free-text binding constraints
    # Wikipedia-first only
    depth: int = 1
    max_pages: int = 30
    include_internal_links: bool = False
    use_wikidata: bool = True
    # Multi-source only
    sources: list[str] | None = None        # None = auto by detected domain
    expand: bool = True
    auto_detect_domain: bool = True
    per_source_limit: int = 6
    top_k: int = 40
    # LLM picker (multi_source + auto modes)
    llm_provider: str = "openrouter"        # openrouter | ollama
    llm_model: str = "openai/gpt-5-mini"


@app.get("/api/scout/installed_models")
async def scout_installed_models():
    """List local Ollama models so the GUI can populate the 'local model' dropdown."""
    import ollama
    try:
        data = ollama.list()
    except Exception as e:
        return {"models": [], "error": str(e)}
    out: list[dict] = []
    for m in data.get("models", []) or []:
        name = m.get("model") or m.get("name") or ""
        if not name:
            continue
        size_b = m.get("size") or 0
        size_gb = round(size_b / (1024 ** 3), 1) if size_b else None
        out.append({"name": name, "size_gb": size_gb})
    out.sort(key=lambda x: x["name"])
    return {"models": out}


class ScoutSuggestBody(BaseModel):
    topic: str
    scope: str = "overview"
    language: str = "en"
    llm_provider: str = "openrouter"
    llm_model: str = "openai/gpt-5-mini"


@app.post("/api/scout/suggest")
async def scout_suggest(body: ScoutSuggestBody):
    """
    One-shot LLM call: given topic + scope chip + language, return suggested
    brief + source set + depth knobs. The frontend uses this to populate the
    form when the user clicks a scope chip or the dedicated regenerate button.
    """
    if not body.topic.strip():
        raise HTTPException(400, "Topic is required.")
    if not _cfg:
        raise HTTPException(503, "Not ready")

    if body.llm_provider == "openrouter":
        if not _cfg.openrouter_api_key:
            raise HTTPException(400,
                "OpenRouter API key not configured. Switch the LLM picker to "
                "'Local' or add a key in Settings.")
        model_spec = {
            "provider": "openrouter",
            "model":    body.llm_model or "openai/gpt-5-mini",
            "api_key":  _cfg.openrouter_api_key,
        }
    elif body.llm_provider == "ollama":
        model_spec = {"provider": "ollama", "model": body.llm_model or _model}
    else:
        raise HTTPException(400, f"Unknown LLM provider: {body.llm_provider}")

    from forge_scout.expand import suggest_pack_params
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, suggest_pack_params,
            body.topic.strip(), body.scope, body.language, model_spec,
        )
    except Exception as exc:
        raise HTTPException(500, f"Suggest failed: {exc}")
    if not result:
        raise HTTPException(502, "LLM returned no usable JSON.")
    return result


class WikidataBody(BaseModel):
    query: str
    langs: list[str] = ["en", "it"]


@app.post("/api/scout/wikidata")
async def scout_wikidata(body: WikidataBody):
    """Return Wikidata disambiguation candidates for a free-text query."""
    from forge_scout.sources import wikidata as wd
    try:
        cands = wd.search(body.query, langs=body.langs, limit=7)
    except Exception as e:
        raise HTTPException(500, f"Wikidata error: {e}")
    return {"candidates": [c.to_dict() for c in cands]}


@app.post("/api/scout/search")
async def scout_search(body: ScoutSearchBody):
    """
    Run a Scout search. SSE stream — events match `scout.scout` generator
    output: log / domain / expanded / result / done.
    """
    if not _cfg:
        raise HTTPException(503, "Not ready")

    # Resolve model_spec from request + saved config
    model_spec: dict
    if body.llm_provider == "openrouter":
        if not _cfg.openrouter_api_key:
            raise HTTPException(400,
                "OpenRouter API key not configured. Add it in Settings → OpenRouter, "
                "or switch the Scout model picker to 'Local'.")
        model_spec = {
            "provider": "openrouter",
            "model": body.llm_model or "openai/gpt-5",
            "api_key": _cfg.openrouter_api_key,
        }
    elif body.llm_provider == "ollama":
        model_spec = {
            "provider": "ollama",
            "model": body.llm_model or _model,
        }
    else:
        raise HTTPException(400, f"Unknown llm_provider: {body.llm_provider}")

    async def generate():
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()

        def thread():
            from forge_scout import scout as _scout
            try:
                if body.mode == "wikipedia_first":
                    gen = _scout.wikipedia_first(
                        body.topic,
                        langs=body.langs,
                        depth=body.depth,
                        max_pages=body.max_pages,
                        include_internal_links=body.include_internal_links,
                        use_wikidata=body.use_wikidata,
                    )
                elif body.mode == "multi_source":
                    gen = _scout.multi_source(
                        body.topic,
                        model_spec=model_spec,
                        langs=body.langs,
                        scope=body.scope,
                        brief=body.brief,
                        enabled_sources=body.sources,
                        per_source_limit=body.per_source_limit,
                        expand_n=6,
                        auto_rank_top_k=body.top_k,
                        auto_detect_domain=body.auto_detect_domain,
                        with_query_expansion=body.expand,
                    )
                else:
                    asyncio.run_coroutine_threadsafe(
                        q.put({"type": "log",
                               "text": f"Unknown mode: {body.mode}"}), loop)
                    return
                for ev in gen:
                    asyncio.run_coroutine_threadsafe(q.put(ev), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(
                    q.put({"type": "log", "text": f"❌ {exc}"}), loop)
                asyncio.run_coroutine_threadsafe(
                    q.put({"type": "done", "total": 0}), loop)
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=thread, daemon=True).start()

        while True:
            item = await q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# In-memory cache of fetched Scout batches.
# Token → {"folder": str, "payloads": [...], "urls": [...], "fetched_at": ts}
# Auto-evicted after 1 hour to keep memory bounded.
_SCOUT_BATCHES: dict[str, dict] = {}
_SCOUT_BATCH_TTL = 3600


def _scout_evict_old_batches():
    import time
    now = time.time()
    expired = [k for k, v in _SCOUT_BATCHES.items()
               if now - v.get("fetched_at", 0) > _SCOUT_BATCH_TTL]
    for k in expired:
        _SCOUT_BATCHES.pop(k, None)


class ScoutFetchBody(BaseModel):
    """Stage 1 — write selected sources straight into the target pack's raw/articles/."""
    pack_name: str
    selected: list[dict]
    full_text_keys: list[str] = []   # opt-in heavy fetch for arXiv PDFs etc.
    scope: str = ""                  # pack scope chip (overview/deep_dive/...) for manifest
    brief: str = ""                  # user free-text brief for manifest


@app.post("/api/scout/fetch")
async def scout_fetch(body: ScoutFetchBody):
    """
    Materialise selected SourceResults into `expert-packs/<pack_name>/raw/articles/`
    using Forge's own raw-source format. The user can inspect the pack folder
    immediately. Run Forge then runs in "recompile" mode against those raws —
    no double-write, no hidden staging.

    SSE stream — terminal event is
    {"type":"done", token, pack_dir, file_count, url_count, pack_existed}.
    """
    import time, uuid

    if not body.selected:
        raise HTTPException(400, "No sources selected.")

    pack_name = re.sub(r'[^a-z0-9-]', '-', body.pack_name.strip().lower()).strip('-')
    if not pack_name:
        raise HTTPException(400, "Invalid pack name.")

    from forge_scout.scout import fetch_into_pack
    from forge_scout.types import SourceResult

    _scout_evict_old_batches()

    selected: list[SourceResult] = []
    for d in body.selected:
        try:
            selected.append(SourceResult(**d))
        except TypeError:
            continue
    if not selected:
        raise HTTPException(400, "No valid sources in selection.")

    pack_dir = ROOT / "expert-packs" / pack_name

    async def generate():
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()

        def thread():
            try:
                token = uuid.uuid4().hex[:12]
                asyncio.run_coroutine_threadsafe(
                    q.put({"type": "log",
                           "text": f"📦 Writing {len(selected)} source(s) into "
                                   f"expert-packs/{pack_name}/raw/articles/ ..."}),
                    loop)
                # Stream per-source progress back to the browser as it happens,
                # so the user sees what's running and where (if anywhere) the
                # fetch is stuck. Each `on_progress` call enqueues one log line.
                def _on_fetch_progress(msg: str):
                    asyncio.run_coroutine_threadsafe(
                        q.put({"type": "log", "text": msg}), loop)

                result = fetch_into_pack(
                    selected, pack_dir,
                    full_text_keys=set(body.full_text_keys),
                    scope=body.scope,
                    brief=body.brief,
                    on_progress=_on_fetch_progress,
                )
                _SCOUT_BATCHES[token] = {
                    "pack_name":   pack_name,
                    "pack_dir":    str(result["pack_dir"]),
                    "pack_existed": result["pack_existed"],
                    "raw_paths":   result["raw_paths"],
                    "urls":        result["passthrough_urls"],
                    "fetched_at":  time.time(),
                }
                file_count = len(result["raw_paths"])
                url_count  = len(result["passthrough_urls"])
                asyncio.run_coroutine_threadsafe(
                    q.put({"type": "log",
                           "text": f"  → {file_count} raw file(s) written"}),
                    loop)
                if result["pack_existed"]:
                    asyncio.run_coroutine_threadsafe(
                        q.put({"type": "log",
                               "text": f"  ⚠ Pack '{pack_name}' already exists — "
                                       f"raws added alongside existing ones."}),
                        loop)
                asyncio.run_coroutine_threadsafe(
                    q.put({"type": "done",
                           "token": token,
                           "pack_dir": str(result["pack_dir"]),
                           "pack_name": pack_name,
                           "pack_existed": result["pack_existed"],
                           "file_count": file_count,
                           "url_count":  url_count}),
                    loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(
                    q.put({"type": "log", "text": f"❌ {exc}"}), loop)
                asyncio.run_coroutine_threadsafe(
                    q.put({"type": "done", "file_count": 0, "url_count": 0}), loop)
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=thread, daemon=True).start()

        while True:
            item = await q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ScoutForgeBatchBody(BaseModel):
    """Stage 2 — run Forge over the pack populated by /api/scout/fetch."""
    token: str
    extract_model: str = "openai/gpt-5-mini"
    model: str = "openai/gpt-5-mini"
    fetch_images: bool = False
    fetch_math: bool = False


@app.post("/api/scout/forge_batch")
async def scout_forge_batch(body: ScoutForgeBatchBody):
    """
    Compile the wiki from the raws Scout already wrote into the pack.
    Single phase: Forge runs in "recompile" mode against raw/articles/.
    """
    if not _cfg:
        raise HTTPException(503, "Not ready")
    if not _cfg.openrouter_api_key:
        raise HTTPException(400,
            "OpenRouter API key not configured. Forge needs it to compile the pack.")

    batch = _SCOUT_BATCHES.get(body.token)
    if not batch:
        raise HTTPException(404,
            "Batch expired or unknown. Re-fetch the sources and try again.")

    pack_name = batch["pack_name"]
    pack_name_clean = re.sub(r'[^a-z0-9-]', '-', pack_name.lower()).strip('-')

    def gen_factory():
        yield "▶ Compiling wiki from raw/articles/ (recompile mode)..."
        recompile_body = ForgeRunBody(
            pack_name=pack_name,
            mode="recompile",
            extract_model=body.extract_model,
            model=body.model,
            files=[],
            urls=[],
            text="",
            fetch_images=False,
            fetch_math=False,
        )
        for line in _forge_run_core(recompile_body):
            yield line
        try:
            from node.retrieval import local_index
            local_index.reindex_pack(_cfg.packs_root, pack_name_clean)
        except Exception:
            pass
        yield {"type": "forge_complete", "pack_name": pack_name_clean}

    run_id = _start_managed_run("scout_forge", pack_name_clean, gen_factory)
    return StreamingResponse(
        _stream_run_sse(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/scout/open-folder/{token}")
async def scout_open_folder(token: str):
    """Open the pack folder Scout populated, in the OS file manager."""
    batch = _SCOUT_BATCHES.get(token)
    if not batch:
        raise HTTPException(404, "Batch not found.")
    import platform, subprocess
    folder = batch["pack_dir"]
    system = platform.system()
    if system == "Windows":
        os.startfile(folder)
    elif system == "Darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])
    return {"ok": True, "folder": folder}


@app.delete("/api/scout/batch/{token}")
async def scout_discard_batch(token: str):
    """
    Discard a fetched batch:
    - Delete every raw file Scout wrote in this batch (preserves any others).
    - If the pack folder is now empty AND Scout had created it, remove it.
    """
    batch = _SCOUT_BATCHES.pop(token, None)
    if not batch:
        return {"ok": True}

    pack_dir = Path(batch["pack_dir"])
    removed_files = 0
    for rel in batch.get("raw_paths") or []:
        try:
            p = pack_dir / rel
            if p.exists():
                p.unlink()
                removed_files += 1
        except Exception:
            pass

    # If Scout created the pack folder and it's now effectively empty, remove it.
    if not batch.get("pack_existed"):
        try:
            raw_articles = pack_dir / "raw" / "articles"
            if raw_articles.exists() and not any(raw_articles.iterdir()):
                shutil.rmtree(pack_dir, ignore_errors=True)
        except Exception:
            pass

    return {"ok": True, "removed_files": removed_files}


# ── Routes — chats ────────────────────────────────────────────────────────────

@app.get("/api/chats")
async def list_chats():
    # chat_store.list_chats already returns most-recent first.
    return chat_store.list_chats()


@app.post("/api/chats")
async def create_chat():
    chat = chat_store.create_chat()
    return {"id": chat["id"], "title": chat["title"]}


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str):
    chat = chat_store.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str):
    chat_store.delete_chat(chat_id)

    # Disk cleanup: delete the chat's uploaded files from upload/, but ONLY if
    # no other chat still references them (same filename uploaded in two chats
    # = single file on disk; don't break the other chat).
    files_to_check = _CHAT_UPLOADS.pop(chat_id, set())
    still_referenced: set[str] = set()
    for other_files in _CHAT_UPLOADS.values():
        still_referenced.update(other_files)

    upload_root = paths.upload_dir().resolve()
    for filename in files_to_check - still_referenced:
        try:
            target = (upload_root / filename).resolve()
            if str(target).startswith(str(upload_root)) and target.is_file():
                target.unlink()
        except Exception:
            pass

    _CHAT_STOPS.pop(chat_id, None)
    return {"ok": True}


@app.delete("/api/chats")
async def delete_all_chats():
    chat_store.delete_all_chats()
    _CHAT_UPLOADS.clear()
    _CHAT_STOPS.clear()
    upload_root = paths.upload_dir().resolve()
    if upload_root.exists():
        for f in upload_root.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                try:
                    f.unlink()
                except Exception:
                    pass
    if _engine:
        _engine._history.clear()
    return {"ok": True}


class RenameChatBody(BaseModel):
    title: str


@app.patch("/api/chats/{chat_id}")
async def rename_chat(chat_id: str, body: RenameChatBody):
    title = chat_store.rename_chat(chat_id, body.title)
    if title is None:
        raise HTTPException(404, "Chat not found")
    return {"ok": True, "title": title}


@app.post("/api/chats/{chat_id}/activate")
async def activate_chat(chat_id: str):
    """Load this chat's message history into the engine context."""
    chat = _get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    if _engine:
        _engine._history = [
            {"role": m["role"], "content": m["content"]}
            for m in chat["messages"]
            if m["role"] in ("user", "assistant") and m.get("content")
        ]
        _engine._peak_ctx_used = 0
        _engine._last_ctx_used = 0
    return {"ok": True}


# ── Routes — query (SSE streaming) ───────────────────────────────────────────

class QueryBody(BaseModel):
    message: str
    mode: str = "auto"
    attachments: list = []


# Per-chat-id stop events. Set by POST /api/chats/{chat_id}/stop while a stream
# is in flight; the chat_query stream thread checks this between engine events
# and breaks the loop cleanly so the partial answer still gets saved.
_CHAT_STOPS: dict[str, threading.Event] = {}

# Per-chat-id set of binary files uploaded into the upload/ folder during the
# session. Once a chat has any binary upload (PDF/DOCX/XLSX/audio), follow-up
# messages in that chat must stay in "chat" mode (tools available) so the
# model can re-read the files when the user references them. Cleared on chat
# delete.
_CHAT_UPLOADS: dict[str, set[str]] = {}


@app.post("/api/chats/{chat_id}/stop")
async def stop_chat_stream(chat_id: str):
    ev = _CHAT_STOPS.get(chat_id)
    if not ev:
        return {"ok": True, "already_idle": True}
    ev.set()
    return {"ok": True, "status": "stopping"}


@app.post("/api/chats/{chat_id}/query")
async def chat_query(chat_id: str, body: QueryBody):
    if not _ready or not _engine:
        raise HTTPException(503, "Engine not ready")
    if not _get_chat(chat_id):
        raise HTTPException(404, "Chat not found")

    # Resolve attachments:
    #   images        → base64 list (passed to model as multimodal input)
    #   binary docs   → saved to workspace/, hint injected so the model calls the right tool
    #   text files    → inlined into the query as [File: ...]
    images_b64: list[str] = []
    text_suffix = ""
    uploaded_files: list[str] = []
    upload_dir = paths.upload_dir()
    upload_dir_resolved = upload_dir.resolve()
    BINARY_EXTS = {".pdf", ".docx", ".xlsx", ".mp3", ".wav", ".m4a", ".ogg", ".flac"}
    # Hard cap per attachment payload (base64 chars). 50 MB raw ≈ 67 MB b64.
    _MAX_ATTACHMENT_B64 = 70 * 1024 * 1024
    for att in body.attachments:
        mime = att.get("type", "")
        # Strip every path component from the filename — the attachment name
        # arrives from the browser and could be "../../.occ_keys/private.key".
        # Path(...).name keeps only the leaf. We also reject anything that
        # still escapes upload/ after resolution, as a belt-and-braces check.
        raw_name = att.get("name", "file")
        name = Path(raw_name).name.strip() or "file"
        data = att.get("data", "")
        raw = data.split(",", 1)[-1] if "," in data else data
        if len(raw) > _MAX_ATTACHMENT_B64:
            # Don't decode huge blobs into memory. Silently drop oversize
            # attachments rather than failing the whole query.
            continue
        ext = Path(name).suffix.lower()
        if mime.startswith("image/"):
            images_b64.append(raw)
        elif mime.startswith("audio/") or ext in BINARY_EXTS:
            try:
                upload_dir.mkdir(parents=True, exist_ok=True)
                target = (upload_dir / name).resolve()
                if not str(target).startswith(str(upload_dir_resolved)):
                    continue
                target.write_bytes(base64.b64decode(raw))
                uploaded_files.append(name)
            except Exception:
                pass
        else:
            try:
                content = base64.b64decode(raw).decode("utf-8", errors="replace")
                text_suffix += f"\n\n[File: {name}]\n{content}"
            except Exception:
                pass

    # Track uploads at chat level so follow-up messages (without new attachments)
    # still know which files exist in upload/ and can re-read them on demand.
    if uploaded_files:
        _CHAT_UPLOADS.setdefault(chat_id, set()).update(uploaded_files)

    known_files = _CHAT_UPLOADS.get(chat_id, set())
    if known_files:
        text_suffix += (
            "\n\n[Files available in upload folder for this chat: "
            + ", ".join(sorted(known_files))
            + ". Use read_pdf / read_docx / read_xlsx / transcribe_audio to "
            "(re-)read them whenever the user refers to their content. "
            "IMPORTANT: this chat is dedicated to analyzing the attached files. "
            "If the user asks something clearly unrelated (general knowledge, "
            "history, science, current events, unrelated technical topics), do "
            "NOT answer from your own training — instead reply briefly in the "
            "user's language with a polite suggestion to open a new chat for "
            "that question, because the knowledge-retrieval pipeline is "
            "available only in chats without file uploads.]"
        )

    full_query = body.message + text_suffix

    # Save user message (display version, no file content)
    _add_message_to_chat(chat_id, "user", body.message, attachments=body.attachments or None)

    async def generate():
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()

        # Classify mode in thread pool. Override: if this chat has had any
        # binary upload, stay in chat mode so atomic tools (read_pdf,
        # read_xlsx, transcribe_audio, ...) remain reachable for follow-up
        # references.
        # Otherwise the two-stage classifier returns one of:
        #   'chat'           — atomic tools / social / meta
        #   'deliberate'     — knowledge retrieval pipeline
        #   'skill:<name>'   — a specific orchestrated skill (e.g. 'skill:web_research')
        # All three modes are passed through to the engine, which has a
        # dedicated branch for each.
        mode = body.mode
        # Conversation-aware rewrite — resolve pronouns and back-references in
        # the user query BEFORE the classifier sees it. A bare follow-up like
        # "and what did Dennett think? did he agree?" reads as chitchat in
        # isolation but is clearly a knowledge question once "he" is bound to
        # the previous topic. Computed once here, reused by both the classifier
        # AND the engine's deliberate/skill paths (via route_stream's new
        # rewritten_query param) so we never pay for two rewrites.
        rewritten_query = full_query
        if _engine is not None and _engine._history and full_query.strip():
            rewritten_query = await loop.run_in_executor(
                None, _engine._rewrite_query_with_history, full_query
            )
            if rewritten_query != full_query:
                log_bus.write(
                    f"[rewriter] '{full_query[:80]}' -> '{rewritten_query[:80]}'"
                )
        # Hard override: if /ollama bypass is ON, route every message to the
        # raw-Ollama path. Skips classifier, skills, retrieval, tools, system
        # prompt. Toggle off with /ollama.
        multi_intents: list[dict] | None = None
        if _OLLAMA_MODE:
            mode = "ollama"
            log_bus.write("[router] /ollama bypass ON → raw Ollama call")
        elif mode == "auto":
            if known_files:
                mode = "chat"
            else:
                skill_reg = _engine._skill_registry if _engine is not None else None
                # Multi-intent pre-pass: detect 2+ distinct requests in one
                # message. If yes, take the orchestrated path (each sub-query
                # gets classified and answered separately, with section headers
                # between the answers).
                multi_intents = await loop.run_in_executor(
                    None, detect_multi_intent, _model, rewritten_query
                )
                if multi_intents:
                    mode = "multi"
                    log_bus.write(
                        f"[router] multi-intent: {[x['label'] for x in multi_intents]}"
                    )
                else:
                    mode = await loop.run_in_executor(None, classify, _model, rewritten_query, skill_reg)
                    log_bus.write(f"[router] classified as '{mode}'")

        # Register a fresh stop event for this chat — overwrites any stale one.
        stop_event = threading.Event()
        _CHAT_STOPS[chat_id] = stop_event

        def stream_thread():
            try:
                if mode == "multi" and multi_intents:
                    stream_iter = _engine.route_stream_multi(
                        multi_intents, images=images_b64 or None,
                    )
                else:
                    stream_iter = _engine.route_stream(
                        full_query, mode, images=images_b64 or None,
                        rewritten_query=rewritten_query,
                    )
                for kind, value in stream_iter:
                    if stop_event.is_set():
                        asyncio.run_coroutine_threadsafe(
                            q.put(("stopped", True)), loop)
                        break
                    asyncio.run_coroutine_threadsafe(q.put((kind, value)), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(q.put(("error", str(exc))), loop)
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)
                # Clean up only if we're still the registered event for this chat
                if _CHAT_STOPS.get(chat_id) is stop_event:
                    _CHAT_STOPS.pop(chat_id, None)

        threading.Thread(target=stream_thread, daemon=True).start()

        tokens: list[str] = []
        routing_mode = ""
        peer_data: dict | None = None
        tools_used: list[str] = []
        was_stopped = False

        while True:
            item = await q.get()
            if item is None:
                break
            kind, value = item
            if kind == "token":
                tokens.append(value)
            elif kind == "routing":
                routing_mode = value
            elif kind == "peer_answers":
                peer_data = value
            elif kind == "tool_used" and value not in tools_used:
                tools_used.append(value)
            elif kind == "stopped":
                was_stopped = True

            yield f"data: {json.dumps({'type': kind, 'value': value})}\n\n"

        answer = "".join(tokens).strip()
        if was_stopped and answer:
            answer += "\n\n_(stopped by user)_"
        if answer:
            _add_message_to_chat(chat_id, "assistant", answer, routing=routing_mode,
                                  tools=tools_used or None,
                                  peer_answers=peer_data or None)
            _engine.add_to_history(full_query, answer)
            if peer_data:
                _write_deliberation_log(body.message, peer_data, answer)

        ctx_used  = _engine._peak_ctx_used if _engine else 0
        ctx_limit = _engine._ctx_limit     if _engine else 0
        yield f"data: {json.dumps({'type': 'done', 'answer': answer, 'routing': routing_mode, 'ctx_used': ctx_used, 'ctx_limit': ctx_limit})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Routes — logs ─────────────────────────────────────────────────────────────

@app.get("/api/logs/stream")
async def logs_stream():
    async def generate():
        for line in log_bus.history():
            yield f"data: {json.dumps({'text': line})}\n\n"
        q = log_bus.subscribe()
        try:
            while True:
                line = await q.get()
                yield f"data: {json.dumps({'text': line})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            log_bus.unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Routes — misc ─────────────────────────────────────────────────────────────

@app.get("/api/peers")
async def list_peers():
    if not _cfg:
        return []
    loop = asyncio.get_event_loop()
    from node.server.client import fetch_peer_list
    try:
        peers = await loop.run_in_executor(None, fetch_peer_list)
        return [
            {
                "id": p.node_id,
                "tier_name": p.tier_name,
                "vram_used_mb": p.vram_used_mb,
                "public_key": p.public_key,
            }
            for p in peers
        ]
    except Exception:
        return []


# ── Routes — slash commands ────────────────────────────────────────────────────

_HELP_TEXT = """\
/clear             clear conversation history and reset context
! <query>          force network mode — consult peers regardless of local knowledge
/packs             list all loaded packs and domains
/peers             show active peer nodes on the broker
/status            show current config
/local on          use local packs only — for private Forge packs
/local off         use server packs (default)
/ollama            toggle raw-Ollama mode: bypass OCC framework (no classifier, skills, retrieval, tools)
/unload            unload model from VRAM
/load              reload model into VRAM
/openrouter on     switch to OpenRouter (if configured)
/openrouter off    switch to local model"""

# When True, chat_query sets mode='ollama' for every message: the engine
# bypasses classifier, skills, retrieval, and tools, calling Ollama with no
# OCC system prompt. Useful to compare raw model behavior vs OCC framework.
_OLLAMA_MODE = False


class CommandBody(BaseModel):
    command: str


@app.post("/api/command")
async def run_command(body: CommandBody):
    global _engine, _cfg, _model, _retriever

    if not _ready:
        return {"output": "Node not ready yet."}

    cmd = body.command.strip()

    if cmd in ("/?", "/help"):
        return {"output": _HELP_TEXT}

    if cmd == "/clear":
        if _engine:
            _engine._history.clear()
            _engine._peak_ctx_used = 0
            _engine._last_ctx_used = 0
        return {"output": "Conversation cleared."}

    if cmd == "/ollama":
        global _OLLAMA_MODE
        _OLLAMA_MODE = not _OLLAMA_MODE
        if _OLLAMA_MODE:
            return {"output": (
                "Ollama bypass: ON\n\n"
                "OCC framework disconnected — no classifier, no skills, no "
                "retrieval, no tools. The model now responds raw, as if you "
                "were calling Ollama directly with no system prompt.\n\n"
                "Use /ollama again to turn off."
            )}
        return {"output": "Ollama bypass: OFF\n\nOCC framework restored."}

    if cmd == "/status":
        or_info = f"OpenRouter: {_cfg.openrouter_model}" if _cfg.openrouter_api_key else "OpenRouter: off"
        domains = ", ".join(_retriever.domains) if _retriever and _retriever.packs else "none"
        peers_n = len(_cfg.peers) if _cfg else 0
        return {"output": (
            f"model:    {_model}\n"
            f"profile:  {_cfg.hardware_profile}  ·  {_cfg.detected_vram_gb}GB VRAM\n"
            f"ctx:      {_cfg.num_ctx_answer:,} tokens\n"
            f"provider: {or_info}\n"
            f"domains:  {domains}\n"
            f"peers:    {peers_n}"
        )}

    if cmd == "/packs":
        if not _retriever or not _retriever.packs:
            return {"output": "No packs loaded."}
        lines = [f"{p.name}  ·  {', '.join(p.domains)}" for p in _retriever.packs]
        return {"output": "\n".join(lines)}

    if cmd == "/peers":
        import httpx as _httpx
        def _fetch():
            r = _httpx.get("https://broker.opencognitivecommons.org/nodes", timeout=10.0)
            r.raise_for_status()
            return r.json()
        try:
            data = await asyncio.to_thread(_fetch)
        except Exception as e:
            return {"output": f"Error reaching broker: {e}"}
        if not data:
            return {"output": "No nodes currently registered on the broker."}
        lines = ["Broker: wss://broker.opencognitivecommons.org/ws", ""]
        for nid, info in data.items():
            tier = info.get("tier_name", "?")
            vram_mb = info.get("vram_used_mb", 0)
            vram_str = f"{vram_mb / 1024:.1f}GB" if vram_mb else "CPU"
            lines.append(f"{nid}  tier: {tier}  vram: {vram_str}")
        return {"output": "\n".join(lines)}

    if cmd.startswith("/model "):
        new_model = cmd[7:].strip()
        if not new_model:
            return {"output": "Usage: /model <name>"}
        _model = new_model
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _warmup_model)
        _engine = DeliberationEngine(
            model=_model, expert_pack=_retriever,
            num_ctx_answer=_cfg.num_ctx_answer, num_ctx_synth=_cfg.num_ctx_synth,
            retrieval_chars=_cfg.retrieval_chars,
            domains=_retriever.domains if _retriever else [],
            workspace=ROOT / "workspace",
            openrouter_key=_cfg.openrouter_api_key,
            openrouter_model=_cfg.openrouter_model,
            local_mode=_cfg.local_mode,
            skills_dir=ROOT / "skills",
            packs_root=_cfg.packs_root,
        )
        return {"output": f"Switched to {new_model}"}

    if cmd.startswith("/pack "):
        pack_name = cmd[6:].strip()
        pack_path = ROOT / "expert-packs" / pack_name
        if not pack_path.exists():
            return {"output": f"Pack '{pack_name}' not found in expert-packs/"}
        new_ret = MultiPackRetriever([load_pack(pack_path)])
        _retriever = new_ret
        _engine = DeliberationEngine(
            model=_model, expert_pack=_retriever,
            num_ctx_answer=_cfg.num_ctx_answer, num_ctx_synth=_cfg.num_ctx_synth,
            retrieval_chars=_cfg.retrieval_chars,
            domains=_retriever.domains,
            workspace=ROOT / "workspace",
            openrouter_key=_cfg.openrouter_api_key,
            openrouter_model=_cfg.openrouter_model,
            local_mode=_cfg.local_mode,
            skills_dir=ROOT / "skills",
            packs_root=_cfg.packs_root,
        )
        return {"output": f"Loaded pack: {pack_name}  ·  domains: {', '.join(_retriever.domains)}"}

    if cmd == "/unload":
        import ollama
        try:
            ollama.chat(
                model=_model,
                messages=[{"role": "user", "content": ""}],
                keep_alive=0,
                options={"num_predict": 0},
            )
            return {"output": f"Model {_model} unloaded from VRAM."}
        except Exception as e:
            return {"output": f"Unload failed: {e}"}

    if cmd == "/load":
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _warmup_model)
        return {"output": f"Model {_model} loaded into VRAM."}

    if cmd in ("/local on", "/local off"):
        from node.apps.cli.config import save_local_mode
        enabled = cmd == "/local on"
        save_local_mode(enabled)
        _cfg = Config()
        if _engine:
            _engine._local_mode = enabled
        state = "ON — using local packs only" if enabled else "OFF — using server packs (default)"
        return {"output": f"Local mode: {state}"}

    if cmd == "/openrouter off":
        save_openrouter_config("", _cfg.openrouter_model if _cfg else "")
        _cfg = Config()
        if _engine:
            _engine.or_key = ""
        return {"output": "OpenRouter disabled — using local model."}

    if cmd == "/openrouter on":
        _cfg = Config()
        if _cfg.openrouter_api_key:
            if _engine:
                _engine.or_key = _cfg.openrouter_api_key
                _engine.or_model = _cfg.openrouter_model
            return {"output": f"OpenRouter enabled — {_cfg.openrouter_model}"}
        return {"output": "No OpenRouter key configured. Use Settings (sidebar) to add one."}

    return {"output": f"Unknown command: {cmd}\nType /? for help."}


# ── Deliberation log (mirrors cli/main.py) ────────────────────────────────────

def _write_deliberation_log(query: str, peer_data: dict, answer: str):
    log_path = paths.deliberation_log()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    routing_mode = peer_data.get("mode", "delegate")
    parts = [f"\n---\n\n## [{timestamp}] — {routing_mode}\n\n**Query:** {query}\n\n"]
    if routing_mode == "hybrid":
        parts.append(
            f"### Node A — Local [{peer_data.get('local_pack', 'local')}]\n\n"
            f"{peer_data.get('local_answer') or '_(no answer)_'}\n\n"
        )
    if peer_data.get("expert_peer"):
        parts.append(
            f"### Peer Expert ({peer_data['expert_peer']})\n\n"
            f"{peer_data.get('expert_answer') or '_(no answer)_'}\n\n"
        )
    if peer_data.get("contrarian_peer") and peer_data.get("contrarian_answer"):
        label = "Peer Expert 2" if routing_mode in ("delegate", "hybrid") else "Peer Contrarian"
        parts.append(f"### {label} ({peer_data['contrarian_peer']})\n\n{peer_data['contrarian_answer']}\n\n")
    parts.append(f"### Synthesized Answer\n\n{answer}\n")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("".join(parts))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    # Browser auto-open is handled by the launcher scripts (launch.bat / launch.sh).
    # When run manually via `python server.py`, open the URL yourself.
    # Loopback-only: the Node GUI has no authentication and exposes destructive
    # endpoints (/api/update, /api/command, attachment uploads). Binding to
    # 0.0.0.0 would put all of that on the LAN. CSRF protection is layered on
    # top via the Origin-check middleware below.
    print("OCC Node GUI  →  http://localhost:7891")
    uvicorn.run(app, host="127.0.0.1", port=7891, log_level="warning")
