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
    tools: list | None = None,
    peer_answers: dict | None = None,
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
            if tools:
                msg["tools"] = tools
            if peer_answers:
                msg["peer_answers"] = peer_answers
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
    return {
        "model": _model,
        "hardware_profile": _cfg.hardware_profile,
        "detected_vram_gb": _cfg.detected_vram_gb,
        "num_ctx_answer": _cfg.num_ctx_answer,
        "openrouter_configured": bool(_cfg.openrouter_api_key),
        "openrouter_model": _cfg.openrouter_model,
        "packs": [{"name": p.name, "domains": p.domains} for p in (_retriever.packs if _retriever else [])],
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
    return {"ok": True, "local_mode": body.enabled}


# ── Routes — Update ───────────────────────────────────────────────────────────

@app.post("/api/update")
async def update_app(background_tasks: BackgroundTasks):
    try:
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

    pip = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "-r",
        str(ROOT / "node" / "requirements.txt"), "-q",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await pip.communicate()

    background_tasks.add_task(_restart_server)
    return {"updated": True, "message": git_out}


def _restart_server():
    import time
    time.sleep(1.5)
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])


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
                result.append({
                    "name": pack_dir.name,
                    "source_count": len(sources),
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
    model: str = "openai/gpt-5"
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

    async def generate():
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()

        def thread():
            success = False
            try:
                for line in _forge_run_core(body):
                    asyncio.run_coroutine_threadsafe(q.put({"text": line}), loop)
                success = True
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(q.put({"text": f"❌ Error: {exc}"}), loop)
            finally:
                if success:
                    asyncio.run_coroutine_threadsafe(
                        q.put({"type": "forge_complete", "pack_name": pack_name_clean}), loop
                    )
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=thread, daemon=True).start()

        while True:
            item = await q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

    rebuild   = body.mode == "rebuild"
    recompile = body.mode == "recompile"

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
    else:
        mf = manifest.load_or_create(pack_dir, pack_name)

    wiki.ensure_schema(wiki_dir, pack_name)
    all_pages = wiki.scan_existing_pages(wiki_dir)
    existing_slugs = {p["slug"] for p in all_pages}

    raw_sources = []
    temp_files_cleanup = []

    pdf_vision_model = extract_model if body.fetch_images else None

    # ── Recompile mode: load existing raw sources, ignore any new input ───────
    if recompile:
        raw_articles = pack_dir / "raw" / "articles"
        if not raw_articles.exists():
            yield "❌ Recompile requires existing raw/articles/ — none found. Use 'Add sources' first."
            return
        loaded = _load_existing_raws_as_sources(raw_articles)
        if not loaded:
            yield "❌ No usable raw sources found in raw/articles/."
            return
        yield f"📚 Loaded {len(loaded)} existing raw source(s) for recompilation."
        raw_sources.extend(loaded)
        # Skip body.files / body.urls / body.text — we are re-using raw only
    else:
        for f in body.files:
            try:
                data = base64.b64decode(f["data_b64"])
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

            yield f"🔍 Extracting concepts ({extract_model})..."
            concepts = None
            for attempt in range(3):
                try:
                    concepts = llm.extract_concepts(
                        text_content, existing_concepts=all_pages, model=extract_model
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
                                page_content = llm.synthesize_wiki_page(
                                    concept, all_payload,
                                    available_images=available_images,
                                    model=write_model,
                                )
                                break
                            except Exception as e:
                                yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."
                    else:
                        yield f"✍️  Enriching: {title}..."
                        page_content = None
                        for attempt in range(3):
                            try:
                                page_content = llm.update_wiki_page(
                                    concept, existing_content, text_content, source_name,
                                    raw_path=raw_path, available_images=available_images,
                                    model=write_model,
                                )
                                break
                            except Exception as e:
                                yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."
                else:
                    yield f"✍️  Writing: {title}..."
                    page_content = None
                    for attempt in range(3):
                        try:
                            page_content = llm.write_wiki_page(
                                concept, text_content, source_name,
                                raw_path=raw_path, available_images=available_images,
                                model=write_model,
                            )
                            break
                        except Exception as e:
                            yield f"  ⏳ Attempt {attempt+1}/3 failed: {e} — retrying..."

                if not page_content:
                    yield f"❌ '{title}' failed after 3 attempts, skipping."
                    continue

                if page_content.strip():
                    wiki.write_page(wiki_dir, slug, page_content)
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

        # Cross-link pass — connect newly-written pages to the rest of the wiki.
        # Re-scan from disk first: `all_pages` holds the concept-extractor's
        # title/summary, but write_wiki_page rewrites both in the final
        # frontmatter. Using the in-memory list would feed the cross-link LLM
        # stale labels (and produce malformed wikilinks).
        if touched_slugs and len(all_pages) > 1:
            yield f"\n🔗 Cross-linking {len(touched_slugs)} touched pages ({extract_model})..."
            disk_pages = wiki.scan_existing_pages(wiki_dir)
            for slug in sorted(touched_slugs):
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
    model: str = "gpt-5"
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

    async def generate():
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()

        def thread():
            try:
                for line in _lint_run_core(
                    pack_name, wiki_dir, pack_dir,
                    model=body.model, fix=body.fix, skip_semantic=body.skip_semantic,
                ):
                    asyncio.run_coroutine_threadsafe(q.put({"text": line}), loop)
                asyncio.run_coroutine_threadsafe(
                    q.put({"type": "lint_complete", "pack_name": pack_name}), loop
                )
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(q.put({"text": f"❌ Error: {exc}"}), loop)
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=thread, daemon=True).start()

        while True:
            item = await q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _lint_run_core(pack_name: str, wiki_dir: Path, pack_dir: Path,
                   model: str, fix: bool = False, skip_semantic: bool = False):
    """
    Two-phase lint:
      1. Mechanical Karpathy checks (C1, C2, C3, C4, C4b, C11) — deterministic, optional auto-fix
      2. Semantic LLM review (Contradictions, Coverage Gaps, Staleness) — optional via skip_semantic
    """
    import forge._lint as lint
    import forge._llm as llm

    # ── Phase 1: mechanical structural checks ─────────────────────────────────
    yield f"🔧 Running structural lint (Karpathy C1, C2, C3, C4, C4b, C11)..."
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

    yield "\n" + lint.format_report(issues, summary, pack_name, fix_applied=fix)

    # ── Phase 2: semantic LLM review ──────────────────────────────────────────
    if skip_semantic:
        yield "✅ Lint complete (semantic phase skipped)."
        return

    if not _cfg.openrouter_api_key:
        yield "⚠️  Semantic phase skipped — OpenRouter API key not configured."
        return

    os.environ["OPENROUTER_API_KEY"] = _cfg.openrouter_api_key

    yield f"\n🤖 Running semantic review ({model})..."
    index_path = wiki_dir / "index.md"
    index_content = index_path.read_text(encoding="utf-8") if index_path.exists() else "(no index.md found)"

    concepts_dir = wiki_dir / "concepts"
    pages_parts = []
    MAX_TOTAL = 80_000
    total_chars = 0
    if concepts_dir.exists():
        page_files = sorted(concepts_dir.glob("*.md"))
        for pf in page_files:
            if pf.name == "_index.md":
                continue
            content = pf.read_text(encoding="utf-8")
            chunk = f"\n### {pf.stem}\n{content}\n"
            if total_chars + len(chunk) > MAX_TOTAL:
                pages_parts.append(f"\n### (truncated — {len(page_files)} total pages, limit reached)")
                break
            pages_parts.append(chunk)
            total_chars += len(chunk)

    pages_content = "".join(pages_parts) or "(no pages found)"

    report = llm.lint_wiki(pack_name, index_content, pages_content, model=model)
    yield "\n" + report
    yield f"\n✅ Lint complete (structural + semantic)."


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
    )
    n = len(_retriever.packs)
    log_bus.write(f"[GUI] Packs reloaded: {n} pack(s)")
    return {"ok": True, "packs": n}


@app.post("/api/forge/open-folder/{pack_name}")
async def forge_open_folder(pack_name: str):
    import platform, subprocess
    pack_dir = ROOT / "expert-packs" / pack_name
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
        tools_used: list[str] = []

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

            yield f"data: {json.dumps({'type': kind, 'value': value})}\n\n"

        answer = "".join(tokens).strip()
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
/unload            unload model from VRAM
/load              reload model into VRAM
/openrouter on     switch to OpenRouter (if configured)
/openrouter off    switch to local model"""


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
    import uvicorn

    # Browser auto-open is handled by the launcher scripts (launch.bat / launch.sh).
    # When run manually via `python server.py`, open the URL yourself.
    print("OCC Node GUI  →  http://localhost:7891")
    uvicorn.run(app, host="0.0.0.0", port=7891, log_level="warning")
