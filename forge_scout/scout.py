"""
Top-level orchestration for Forge Scout.

Three modes are exposed as generators yielding dicts of the form:

    {"type": "log",      "text": "..."}        — human-readable progress line
    {"type": "result",   "result": {...}}      — one SourceResult.to_dict()
    {"type": "domain",   "domain": "history"}  — detected domain
    {"type": "expanded", "queries": [...]}     — expansion queries
    {"type": "done",     "total": N}           — terminal marker

The dict shape is what the FastAPI server forwards over SSE.

The orchestrator never writes to the pack directory itself — it returns
selected SourceResults (after the GUI picks them) and a small helper
`fetch_for_forge()` materialises them into a temp folder Forge can ingest.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Iterable, Iterator

from .sources import REGISTRY, sources_for_domain, wikidata
from .sources import wikipedia
from .types import SourceResult
from .expand import classify_domain, expand_queries, rank_results


# ── Wikipedia-first ───────────────────────────────────────────────────────────

def wikipedia_first(topic: str,
                    langs: Iterable[str] = ("en",),
                    depth: int = 1,
                    max_pages: int = 30,
                    include_internal_links: bool = False,
                    use_wikidata: bool = True) -> Iterator[dict]:
    """
    Walk Wikipedia outward from the topic. Zero LLM cost.

    Strategy:
      1. If `use_wikidata`, look up the topic → resolve sitelinks in every
         target language → use the *correct* page name per language.
      2. For each language, walk to `depth` hops, capped at `max_pages` total.
      3. Yield each visited page as a result.
    """
    langs = list(dict.fromkeys(l.strip().lower() for l in langs if l.strip())) or ["en"]
    yield _log(f"Wikipedia-first mode — langs={','.join(langs)}, depth={depth}, "
               f"max={max_pages}, walk={'inline+see-also' if include_internal_links else 'see-also only'}")

    # 1. Resolve titles per language via Wikidata if asked
    seeds: dict[str, str] = {}
    if use_wikidata:
        yield _log("Disambiguating via Wikidata...")
        cands = wikidata.search(topic, langs=langs, limit=5)
        if cands:
            qid = cands[0].qid
            yield _log(f"  ✓ Picked {qid} — {cands[0].label}: {cands[0].description}")
            sl = wikidata.sitelinks(qid)
            for lang in langs:
                if sl.get(lang):
                    seeds[lang] = sl[lang]
                    yield _log(f"  ↳ {lang}: {sl[lang]}")
        else:
            yield _log("  · no Wikidata match — falling back to direct title")
    # Fallback for any missing language: use the raw topic
    for lang in langs:
        seeds.setdefault(lang, topic)

    # 2. Walk
    per_lang_cap = max(3, max_pages // max(len(langs), 1))
    all_results: list[SourceResult] = []
    for lang in langs:
        yield _log(f"\nWalking {lang}.wikipedia.org from '{seeds[lang]}'...")
        try:
            results = wikipedia.walk(
                seeds[lang], lang,
                depth=depth, max_pages=per_lang_cap,
                include_internal_links=include_internal_links,
            )
        except Exception as e:
            yield _log(f"  ✗ {lang}: walk failed — {e}")
            continue
        yield _log(f"  found {len(results)} page(s)")
        for r in results:
            all_results.append(r)
            yield {"type": "result", "result": r.to_dict()}

    yield {"type": "done", "total": len(all_results)}


# ── Multi-source curated ──────────────────────────────────────────────────────

def multi_source(topic: str,
                 model_spec: dict,
                 langs: Iterable[str] = ("en",),
                 scope: str = "overview",
                 brief: str = "",
                 enabled_sources: list[str] | None = None,
                 per_source_limit: int = 6,
                 expand_n: int = 6,
                 auto_rank_top_k: int = 40,
                 auto_detect_domain: bool = True,
                 with_query_expansion: bool = True,
                 relevance_threshold: float = 0.3) -> Iterator[dict]:
    """
    Fan-out across all relevant sources, dedup, rank.

    `enabled_sources=None` → auto-pick based on detected domain.
    `with_query_expansion=False` → use the raw topic as the single query.
    `scope` + `brief` define the user's INTENT — both are pushed into
    query expansion and the ranker, so the pipeline stays on-topic.
    `relevance_threshold` (0..1) — candidates below this score are dropped.
    """
    langs = list(dict.fromkeys(l.strip().lower() for l in langs if l.strip())) or ["en"]
    intent_label = scope + (f" + brief({len(brief)} chars)" if brief else "")
    yield _log(f"Multi-source mode — langs={','.join(langs)}, intent={intent_label}")

    # 1. Domain detection
    domain = "other"
    if auto_detect_domain:
        yield _log("Classifying topic domain...")
        try:
            domain = classify_domain(topic, model_spec)
        except Exception as e:
            yield _log(f"  ⚠ classification failed: {e} — using 'other'")
        yield {"type": "domain", "domain": domain}
        yield _log(f"  → {domain}")

    # 2. Source selection
    if enabled_sources is None:
        enabled_sources = sources_for_domain(domain) or list(REGISTRY.keys())
    enabled_sources = [s for s in enabled_sources if s in REGISTRY]
    yield _log(f"Sources to query: {', '.join(enabled_sources)}")

    # 3. Query expansion (scope + brief-aware)
    queries: list[str] = [topic]
    if with_query_expansion:
        yield _log("Expanding queries via LLM (scope-aware)...")
        try:
            queries = expand_queries(topic, model_spec, n=expand_n,
                                     domain=domain, scope=scope, brief=brief)
        except Exception as e:
            yield _log(f"  ⚠ expansion failed: {e} — using single raw query")
            queries = [topic]
        yield {"type": "expanded", "queries": queries}
        for q in queries:
            yield _log(f"  · {q}")

    # 4. Parallel fan-out across (source × query) pairs
    yield _log("\nFanning out across sources...")
    bucket: dict[str, SourceResult] = {}

    async def run_one(src_id: str, q: str):
        mod = REGISTRY[src_id]["module"]
        # All source `search()` are sync — run in thread.
        loop = asyncio.get_event_loop()
        try:
            results = await loop.run_in_executor(
                None, lambda: mod.search(q, per_source_limit, langs)
            )
        except Exception:
            results = []
        return src_id, q, results

    async def fanout() -> None:
        tasks = []
        for src_id in enabled_sources:
            for q in queries:
                tasks.append(run_one(src_id, q))
        for coro in asyncio.as_completed(tasks):
            src_id, q, results = await coro
            yielded_in_round = 0
            for r in results:
                key = r.dedup_key
                if key not in bucket:
                    bucket[key] = r
                    yielded_in_round += 1
            _queue.append({"type": "log",
                           "text": f"  · {src_id} ← \"{q[:50]}\" — {len(results)} ({yielded_in_round} new)"})

    _queue: list[dict] = []
    # Run async loop synchronously (this generator runs in a worker thread)
    asyncio.run(fanout())
    for msg in _queue:
        yield msg

    # 5. Ranking — ALWAYS runs the LLM rank (no early-exit). Uses scope + brief
    # as binding context so off-topic keyword collisions get downranked.
    all_results = list(bucket.values())
    yield _log(f"\nCollected {len(all_results)} unique candidate(s).")
    if not all_results:
        yield {"type": "done", "total": 0}
        return
    yield _log(f"Ranking by relevance (scope-aware, threshold={relevance_threshold:.2f})...")
    try:
        ranked, dropped = rank_results(
            topic, all_results, model_spec,
            top_k=auto_rank_top_k,
            scope=scope, brief=brief,
            threshold=relevance_threshold,
        )
    except Exception as e:
        yield _log(f"  ⚠ ranking failed: {e} — falling back to authority heuristic")
        ranked = sorted(all_results, key=lambda r: r.score, reverse=True)[:auto_rank_top_k]
        dropped = []

    if dropped:
        yield _log(f"  ✂ Dropped {len(dropped)} off-topic candidate(s):")
        for r in dropped[:8]:
            yield _log(f"     · [{r.source}] {r.title[:70]} (score {r.score:.2f})")
        if len(dropped) > 8:
            yield _log(f"     · ... and {len(dropped) - 8} more")

    for r in ranked:
        yield {"type": "result", "result": r.to_dict()}

    yield {"type": "done", "total": len(ranked)}


# ── Materialisation helper ────────────────────────────────────────────────────

def fetch_into_pack(selected: list[SourceResult],
                    pack_dir: Path,
                    full_text_keys: set[str] | None = None,
                    scope: str = "",
                    brief: str = "",
                    on_progress=None) -> dict:
    """
    Materialise selected SourceResults straight into `<pack_dir>/raw/articles/`
    using Forge's own raw-source schema (frontmatter + body). The pack folder
    is created if it doesn't exist; raws are appended alongside any existing
    ones (Forge's `write_raw_source` never overwrites).

    Also persists the user's intent (scope + brief) into `manifest.yaml` so
    Forge can read it at compile time and apply scope-aware concept extraction.

    `on_progress`: optional callable(str) — invoked with a human-readable log
    line BEFORE each fetch attempt and AFTER its outcome. Lets the GUI stream
    per-source progress so the user isn't left staring at a frozen pane for
    minutes when one fetch takes its full 30s timeout.
    """
    from forge import _wiki as _forge_wiki
    from forge import _manifest as _forge_manifest
    import time as _time
    import threading as _threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pack_existed = pack_dir.exists()
    pack_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = pack_dir / "raw" / "articles"
    raw_dir.mkdir(parents=True, exist_ok=True)

    full_text_keys = full_text_keys or set()
    raw_paths: list[str] = []

    def _log(msg: str):
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    total = len(selected)

    # Polite per-source concurrency cap — keeps us from hammering a single
    # upstream with 8 parallel requests. Trusts each source module's own
    # httpx timeout (10-30s) for hang detection — we no longer wrap fetches
    # in nested threads with manual timeouts, which previously created
    # zombie threads + serialised the worker pool.
    _SOURCE_CONCURRENCY = {
        "sep":        3,
        "mathworld":  3,
        "wikipedia":  6,
        "wikisource": 6,
        "archive_org": 4,
    }
    _semaphores: dict[str, _threading.Semaphore] = {
        k: _threading.Semaphore(v) for k, v in _SOURCE_CONCURRENCY.items()
    }

    def _fetch_one(r: SourceResult) -> tuple:
        """Worker: returns (result, md, name, elapsed_s, error_or_None).
        Hard guarantees: ALWAYS returns. Any exception inside the fetch is
        converted to an error string so the future completes."""
        t0 = _time.time()
        try:
            module = REGISTRY[r.source]["module"]
        except KeyError:
            return r, None, None, 0.0, f"unknown source '{r.source}'"
        wants_full = (r.dedup_key in full_text_keys) and hasattr(module, "fetch_full_text")
        sem = _semaphores.get(r.source)
        try:
            if sem is not None:
                with sem:
                    md, name = (module.fetch_full_text(r) if wants_full
                                else module.fetch(r))
            else:
                md, name = (module.fetch_full_text(r) if wants_full
                            else module.fetch(r))
        except Exception as exc:
            return r, None, None, _time.time() - t0, str(exc)[:160]
        return r, md, name, _time.time() - t0, None

    # Heartbeat thread — prints elapsed/done counter every 5s.
    t_all = _time.time()
    _stop_heartbeat = _threading.Event()
    _hb_state = {"completed": 0, "total": total}
    def _heartbeat():
        # Best-effort: never raise out of this thread.
        while not _stop_heartbeat.wait(5.0):
            try:
                elapsed = _time.time() - t_all
                done = _hb_state["completed"]
                _log(f"  ⏳ {done}/{total} done, {elapsed:.0f}s elapsed...")
            except Exception:
                pass
    _hb_thread = _threading.Thread(target=_heartbeat, daemon=True)

    _log(f"📡 Fetching {total} source(s) (concurrency caps: sep≤3, wiki≤6, "
         f"wikisource≤6, mathworld≤3, archive_org≤4)...")
    _hb_thread.start()
    completed = 0
    failed = 0

    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            future_to_r = {ex.submit(_fetch_one, r): r for r in selected}
            for fut in as_completed(future_to_r):
                r = future_to_r[fut]
                title_short = (r.title or "(no title)")[:60]
                try:
                    _, md, name, dt, err = fut.result()
                except Exception as exc:
                    err = f"thread crashed: {exc}"
                    md = name = None
                    dt = 0.0
                completed += 1
                _hb_state["completed"] = completed
                prefix = f"  [{completed}/{total}]"
                if err:
                    failed += 1
                    _log(f"{prefix} ✗ {r.source} ← {title_short} — {err[:120]} ({dt:.1f}s)")
                    continue
                if not md or not md.strip():
                    failed += 1
                    _log(f"{prefix} ✗ {r.source} ← {title_short} — empty body ({dt:.1f}s)")
                    continue
                try:
                    rel_path = _forge_wiki.write_raw_source(pack_dir, name, r.url or "", md)
                    raw_paths.append(rel_path)
                    _log(f"{prefix} ✓ {r.source} ← {title_short} — {len(md):,} chars ({dt:.1f}s)")
                except Exception as exc:
                    failed += 1
                    _log(f"{prefix} ✗ {r.source} ← {title_short} — write: {str(exc)[:120]}")
    finally:
        _stop_heartbeat.set()

    _log(f"📦 Fetched {len(raw_paths)} / {total} source(s) "
         f"in {_time.time() - t_all:.1f}s ({failed} failed)")

    # Persist scope + brief in the manifest so Forge can read them later.
    # We always touch the manifest (even with empty scope/brief) so subsequent
    # Forge runs are guaranteed to find at least an empty file, not a missing one.
    try:
        pack_name = pack_dir.name
        mf = _forge_manifest.load_or_create(pack_dir, pack_name)
        if scope.strip():
            mf["scope"] = scope.strip()
        if brief.strip():
            mf["brief"] = brief.strip()
        _forge_manifest.save(pack_dir, mf)
    except Exception:
        # Manifest write failure shouldn't break the fetch — Forge will fall
        # back to scope-less extraction if the manifest doesn't include it.
        pass

    return {
        "pack_dir":         pack_dir,
        "pack_existed":     pack_existed,
        "raw_paths":        raw_paths,
        "passthrough_urls": [],
    }


# Backwards-compatible shim — kept in case anything imports the old name.
def fetch_for_forge(selected, out_dir=None):  # pragma: no cover
    raise NotImplementedError(
        "fetch_for_forge() was replaced by fetch_into_pack(selected, pack_dir). "
        "Update the caller to pass a pack directory."
    )


# ── Internals ─────────────────────────────────────────────────────────────────

def _log(text: str) -> dict:
    return {"type": "log", "text": text}
