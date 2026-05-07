"""
OCC Node GUI — FastAPI server.
Run: python node/apps/gui/server.py
Then open: http://localhost:7891
"""
import asyncio
import base64
import json
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATIC = Path(__file__).parent / "static"
sys.path.insert(0, str(ROOT))

from node.apps.cli.config import Config, save_openrouter_config
from node.apps.gui import log_bus
from node.deliberation.classifier import classify
from node.deliberation.engine import DeliberationEngine
from node.deliberation.tools import set_workspace
from node.expert_runtime.pack import load_all_packs, load_pack, MultiPackRetriever

app = FastAPI()
STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# ── Global state ──────────────────────────────────────────────────────────────

_cfg: Config | None = None
_engine: DeliberationEngine | None = None
_retriever: MultiPackRetriever | None = None
_model: str = ""
_ready = False
_init_status = "starting"

# ── Chat storage ──────────────────────────────────────────────────────────────

_CHATS_FILE = ROOT / ".occ_chats.json"


def _load_chats() -> list:
    if _CHATS_FILE.exists():
        try:
            return json.loads(_CHATS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_chats(chats: list):
    _CHATS_FILE.write_text(
        json.dumps(chats, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _get_chat(chat_id: str) -> dict | None:
    for c in _load_chats():
        if c["id"] == chat_id:
            return c
    return None


def _add_message_to_chat(
    chat_id: str,
    role: str,
    content: str,
    routing: str = "",
    attachments: list | None = None,
):
    chats = _load_chats()
    for c in chats:
        if c["id"] == chat_id:
            msg: dict = {
                "id": str(uuid.uuid4())[:8],
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
            if routing:
                msg["routing"] = routing
            if attachments:
                msg["attachments"] = attachments
            c["messages"].append(msg)
            if role == "user" and len(c["messages"]) == 1:
                c["title"] = content[:60].strip() or "New Chat"
            _save_chats(chats)
            return


# ── Startup init ──────────────────────────────────────────────────────────────

def _init():
    global _cfg, _engine, _retriever, _model, _ready, _init_status

    _init_status = "loading config"
    log_bus.write("[GUI] Loading config...")
    _cfg = Config()
    _model = _cfg.model

    _init_status = "checking Ollama"
    from node.hardware import is_ollama_running, start_ollama
    if not is_ollama_running():
        log_bus.write("[GUI] Starting Ollama...")
        start_ollama()

    _init_status = "loading packs"
    log_bus.write("[GUI] Loading expert packs...")
    workspace = ROOT / "workspace"
    workspace.mkdir(exist_ok=True)
    set_workspace(workspace)

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

    _init_status = "building embeddings"
    _maybe_build_embeddings()

    _engine = DeliberationEngine(
        model=_model,
        expert_pack=_retriever,
        peers=_cfg.peers,
        num_ctx_answer=_cfg.num_ctx_answer,
        num_ctx_synth=_cfg.num_ctx_synth,
        retrieval_chars=_cfg.retrieval_chars,
        domains=_retriever.domains if _retriever else [],
        workspace=workspace,
        openrouter_key=_cfg.openrouter_api_key,
        openrouter_model=_cfg.openrouter_model,
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


def _maybe_build_embeddings():
    if not _retriever:
        return
    from node.retrieval.search import build_embeddings, load_embeddings
    for pack in _retriever.packs:
        if load_embeddings(pack.wiki_dir) is None:
            log_bus.write(f"[GUI] Building embeddings: {pack.name}...")
            build_embeddings(pack.wiki_dir)


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
    return {"ready": _ready, "status": _init_status, "model": _model}


@app.get("/api/config")
async def get_config():
    if not _cfg:
        raise HTTPException(503, "Not ready")
    return {
        "model": _model,
        "hardware_profile": _cfg.hardware_profile,
        "detected_vram_gb": _cfg.detected_vram_gb,
        "num_ctx_answer": _cfg.num_ctx_answer,
        "openrouter_configured": bool(_cfg.openrouter_api_key),
        "openrouter_model": _cfg.openrouter_model,
        "packs": [{"name": p.name, "domains": p.domains} for p in (_retriever.packs if _retriever else [])],
        "peers": _cfg.peers,
    }


class OpenRouterBody(BaseModel):
    api_key: str
    model: str


@app.post("/api/config/openrouter")
async def set_openrouter(body: OpenRouterBody):
    global _cfg
    save_openrouter_config(body.api_key, body.model)
    _cfg = Config()
    if _engine:
        _engine.or_key = body.api_key
        _engine.or_model = body.model
    return {"ok": True}


# ── Routes — chats ────────────────────────────────────────────────────────────

@app.get("/api/chats")
async def list_chats():
    chats = _load_chats()
    return [
        {"id": c["id"], "title": c.get("title", "New Chat"), "created_at": c.get("created_at", "")}
        for c in reversed(chats)
    ]


@app.post("/api/chats")
async def create_chat():
    chat = {
        "id": str(uuid.uuid4())[:12],
        "title": "New Chat",
        "created_at": datetime.now().isoformat(),
        "messages": [],
    }
    chats = _load_chats()
    chats.append(chat)
    _save_chats(chats)
    return {"id": chat["id"], "title": chat["title"]}


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str):
    chat = _get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str):
    chats = [c for c in _load_chats() if c["id"] != chat_id]
    _save_chats(chats)
    return {"ok": True}


class RenameChatBody(BaseModel):
    title: str


@app.patch("/api/chats/{chat_id}")
async def rename_chat(chat_id: str, body: RenameChatBody):
    chats = _load_chats()
    for c in chats:
        if c["id"] == chat_id:
            c["title"] = body.title.strip() or "New Chat"
            _save_chats(chats)
            return {"ok": True, "title": c["title"]}
    raise HTTPException(404, "Chat not found")


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


@app.post("/api/chats/{chat_id}/query")
async def chat_query(chat_id: str, body: QueryBody):
    if not _ready or not _engine:
        raise HTTPException(503, "Engine not ready")
    if not _get_chat(chat_id):
        raise HTTPException(404, "Chat not found")

    # Resolve attachments: images → base64 list, text files → appended to query
    images_b64: list[str] = []
    text_suffix = ""
    for att in body.attachments:
        mime = att.get("type", "")
        data = att.get("data", "")
        raw = data.split(",", 1)[-1] if "," in data else data
        if mime.startswith("image/"):
            images_b64.append(raw)
        else:
            try:
                content = base64.b64decode(raw).decode("utf-8", errors="replace")
                text_suffix += f"\n\n[File: {att.get('name', 'file')}]\n{content}"
            except Exception:
                pass

    full_query = body.message + text_suffix

    # Save user message (display version, no file content)
    _add_message_to_chat(chat_id, "user", body.message, attachments=body.attachments or None)

    async def generate():
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()

        # Classify mode in thread pool
        mode = body.mode
        if mode == "auto":
            mode = await loop.run_in_executor(None, classify, _model, full_query)

        def stream_thread():
            try:
                for kind, value in _engine.route_stream(
                    full_query, mode, images=images_b64 or None
                ):
                    asyncio.run_coroutine_threadsafe(q.put((kind, value)), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(q.put(("error", str(exc))), loop)
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=stream_thread, daemon=True).start()

        tokens: list[str] = []
        routing_mode = ""
        peer_data: dict | None = None

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

            yield f"data: {json.dumps({'type': kind, 'value': value})}\n\n"

        answer = "".join(tokens).strip()
        if answer:
            _add_message_to_chat(chat_id, "assistant", answer, routing=routing_mode)
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
    from node.server.client import fetch_peer_manifests
    try:
        manifests = await loop.run_in_executor(None, fetch_peer_manifests)
        return [{"id": nid, **info} for nid, info in manifests.items()]
    except Exception:
        return []


# ── Routes — slash commands ────────────────────────────────────────────────────

_HELP_TEXT = """\
/?  /help          show this help
/clear             clear conversation history and reset context
! <query>          force knowledge retrieval (bypass classifier)
/model <name>      switch model  (e.g. /model deepseek-r1:14b)
/pack <name>       load a specific pack  (e.g. /pack docker)
/packs             list all loaded packs and domains
/peers             show nodes registered on the broker
/status            show current config
/unload            unload model from VRAM
/load              reload model into VRAM
/openrouter on     switch to OpenRouter (if configured)
/openrouter off    switch to local model only"""


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
        loop = asyncio.get_event_loop()
        from node.server.client import fetch_peer_manifests
        try:
            manifests = await loop.run_in_executor(None, fetch_peer_manifests)
        except Exception as e:
            return {"output": f"Error fetching peers: {e}"}
        if not manifests:
            return {"output": "No nodes currently registered on the broker."}
        lines = ["Broker: wss://broker.opencognitivecommons.org/ws", ""]
        for nid, info in manifests.items():
            d = ", ".join(info.get("domains", []))
            lines.append(f"{nid}  pack: {info.get('pack', '?')}  domains: {d}")
        return {"output": "\n".join(lines)}

    if cmd.startswith("/model "):
        new_model = cmd[7:].strip()
        if not new_model:
            return {"output": "Usage: /model <name>"}
        _model = new_model
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _warmup_model)
        _engine = DeliberationEngine(
            model=_model, expert_pack=_retriever, peers=_cfg.peers,
            num_ctx_answer=_cfg.num_ctx_answer, num_ctx_synth=_cfg.num_ctx_synth,
            retrieval_chars=_cfg.retrieval_chars,
            domains=_retriever.domains if _retriever else [],
            workspace=ROOT / "workspace",
            openrouter_key=_cfg.openrouter_api_key,
            openrouter_model=_cfg.openrouter_model,
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
            model=_model, expert_pack=_retriever, peers=_cfg.peers,
            num_ctx_answer=_cfg.num_ctx_answer, num_ctx_synth=_cfg.num_ctx_synth,
            retrieval_chars=_cfg.retrieval_chars,
            domains=_retriever.domains,
            workspace=ROOT / "workspace",
            openrouter_key=_cfg.openrouter_api_key,
            openrouter_model=_cfg.openrouter_model,
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
    log_path = ROOT / "deliberation_log.md"
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
    import time
    import webbrowser
    import uvicorn

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open("http://localhost:7891")

    threading.Thread(target=_open_browser, daemon=True).start()
    print("OCC Node GUI  →  http://localhost:7891")
    uvicorn.run(app, host="0.0.0.0", port=7891, log_level="warning")
