"""
pack_retrieve — skill-facing retrieval helper.

Sibling (NOT replacement) of engine._retrieve_from_server. The big retrieval
pipeline used in `deliberate` mode does decompose → tree-walk-with-LLM →
translate-per-pack → round-robin. That is necessary when the user asks an
open-ended question and the system has to figure out where to look.

Skills don't have that problem: the skill itself knows the scope (a pack
path like "python" or "harry-potter") and supplies a clean query. So the
retrieval they need is much smaller — basically a wrapper around the
broker's /search and /packs/.../wiki/... endpoints.

Two optional powers exposed:
    deep_walk=True   — BM25-driven drill-down within the scope subtree to
                       focus on the most relevant sub-pack. Useful when the
                       scope is broad (e.g. scope="harry-potter" and the
                       query is about a specific character — drill-down
                       finds harry-potter/characters/villains/voldemort).
                       Deterministic, no LLM call. Adds 1-2 broker calls.
    max_chars        — total budget for the assembled context.

Phase 2 (later, requires broker change): an `entity=` parameter that calls
a /lookup_entity endpoint to discover which pack a named entity lives in.
That requires deploying a new endpoint to the broker; until then, skills
that don't know the scope can't use this helper and must rely on the
existing deliberate path.
"""
from __future__ import annotations

import httpx

from node.retrieval.pack_cache import SERVER_URL


def pack_retrieve(
    query: str,
    scope: str | None = None,
    entity: str | None = None,
    model: str | None = None,
    deep_walk: bool = False,
    max_chars: int = 4000,
    top_k: int = 5,
) -> str:
    """Retrieve grounded context from a pack for a skill's needs.

    Args:
        query: search terms in the user's language.
        scope: pack path to constrain the search to (e.g. "python" or
               "history/ancient-rome"). Required UNLESS `entity` is given.
        entity: when set (and scope is not), the broker's /lookup_entity
                is called first to discover which pack contains pages
                mentioning the entity. The top-matching pack becomes the
                effective scope for the search. Use when the skill knows a
                named entity (e.g. "Voldemort") but doesn't know which
                installed pack covers it.
        model: when set, the query is first translated into the pack's
               language via an LLM keyword-extraction call. Required when
               the user's language may differ from the pack's. Pass None
               only when the caller already has clean keywords in the
               pack's expected language (e.g. parsed from a stacktrace).
        deep_walk: when True, walk the scope's subtree picking the child
                   with the highest BM25 score for the query. Refines the
                   scope before the final search. Use when scope is broad
                   and the query points to a specific sub-area.
        max_chars: total cap on returned context text.
        top_k: number of pages to fetch from the final search.

    Returns:
        Assembled context with one section per fetched page. Empty string
        if nothing found, scope/entity both missing, or broker unreachable.
    """
    if not query:
        return ""

    # Resolve scope. Either the caller already gave us one, or we discover
    # it from the entity via the broker's /lookup_entity endpoint.
    if not scope:
        if not entity:
            return ""
        discovered = _lookup_entity_pack(entity)
        if not discovered:
            return ""
        scope = discovered

    # Translate user query into pack language (LLM keyword extraction).
    # Same pattern as engine._translate_query_for_pack but standalone, so
    # we don't depend on the engine module.
    effective_query = query
    if model:
        sample = _fetch_index_sample(scope)
        if sample:
            translated = _translate_query(query, sample, model)
            if translated:
                effective_query = translated

    effective_scope = scope
    if deep_walk:
        drilled = _drill_down(scope, effective_query)
        if drilled:
            effective_scope = drilled

    results = _broker_search(effective_query, effective_scope, k=top_k)
    if not results:
        return ""

    pages: list[str] = []
    total = 0
    remaining_slots = top_k
    for r in results:
        pack_path = r.get("pack_path") or ""
        page_file = r.get("page_file") or ""
        title = r.get("title") or page_file
        if not pack_path or not page_file:
            continue

        body = _fetch_page(pack_path, page_file)
        if not body:
            continue

        # Per-page budget so one huge page doesn't eat all the room
        per_page_budget = max(600, (max_chars - total) // max(1, remaining_slots))
        if len(body) > per_page_budget:
            body = body[:per_page_budget].rstrip() + "\n[...truncated]"

        section = f"=== {title}  ({pack_path}/{page_file}) ===\n{body.strip()}"
        if total and total + len(section) + 2 > max_chars:
            break
        pages.append(section)
        total += len(section) + 2
        remaining_slots = max(1, remaining_slots - 1)

    return "\n\n".join(pages)


# ── Internals (private, no LLM) ───────────────────────────────────────────────

def _broker_search(query: str, scope: str | None, k: int = 5) -> list[dict]:
    """POST /search with optional scope. Returns [] on any failure."""
    payload: dict = {"q": query, "k": k}
    if scope:
        payload["scope"] = scope
    try:
        resp = httpx.post(
            f"{SERVER_URL}/search",
            json=payload,
            timeout=8.0,
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("results", []) or []
    except Exception:
        return []


def _fetch_page(pack_path: str, page_file: str) -> str:
    """GET /packs/{pack_path}/wiki/{page_file}. Returns '' on any failure."""
    try:
        resp = httpx.get(
            f"{SERVER_URL}/packs/{pack_path}/wiki/{page_file}",
            timeout=8.0,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return ""
        return resp.text or ""
    except Exception:
        return ""


def _drill_down(scope: str, query: str) -> str:
    """Pick the child of `scope` whose top BM25 score for `query` is highest.
    Returns the chosen child path, or the original scope if no children or
    all children return zero results.

    This is deterministic — no LLM — so it's fast and cheap. Cost: one
    /tree call + N small /search calls (one per child). For a pack with
    5-10 immediate children, totals ~150-400ms on a warm broker.
    """
    try:
        resp = httpx.get(f"{SERVER_URL}/tree/{scope}", timeout=5.0)
        if resp.status_code != 200:
            return scope
        children = resp.json().get("children", []) or []
    except Exception:
        return scope

    if not children:
        return scope

    # Broker /tree returns children as plain strings (the name of each
    # immediate child), not dicts. Full child path = scope + "/" + name.
    best_score = 0.0
    best_path = scope
    for child_name in children:
        if not isinstance(child_name, str) or not child_name:
            continue
        child_path = f"{scope}/{child_name}"
        peek = _broker_search(query, child_path, k=1)
        if not peek:
            continue
        # FTS5 BM25 scores via SQLite are negative (lower = better) by default;
        # broker may normalize. Take whichever metric is reported, default 0.
        score = float(peek[0].get("score", 0) or 0)
        # If the broker reports negative bm25 (raw FTS5), invert so larger=better
        if score < 0:
            score = -score
        if score > best_score:
            best_score = score
            best_path = child_path

    return best_path


def _lookup_entity_pack(entity: str) -> str:
    """Ask the broker which installed pack contains pages mentioning `entity`.
    Returns the top-matching pack_path, or "" if no broker / no match."""
    try:
        resp = httpx.post(
            f"{SERVER_URL}/lookup_entity",
            json={"term": entity, "limit": 3},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return ""
        results = resp.json().get("results", []) or []
        if not results:
            return ""
        # Top result has the highest match_count for this entity
        return results[0].get("pack_path", "") or ""
    except Exception:
        return ""


def _fetch_index_sample(scope: str, max_chars: int = 800) -> str:
    """Fetch a sample of `scope`'s index.md so the translator LLM can
    detect the pack's language. Walks down up to 2 levels if the scope
    itself doesn't have an index.md (e.g. scope is a category, not a leaf).
    Returns "" if nothing found."""
    def _try_index(path: str) -> str:
        try:
            r = httpx.get(f"{SERVER_URL}/packs/{path}/wiki/index.md", timeout=5.0)
            if r.status_code == 200:
                return r.text or ""
        except Exception:
            pass
        return ""

    text = _try_index(scope)
    if text:
        return text[:max_chars]

    # Walk down one level
    try:
        resp = httpx.get(f"{SERVER_URL}/tree/{scope}", timeout=5.0)
        if resp.status_code != 200:
            return ""
        children = resp.json().get("children", []) or []
    except Exception:
        return ""

    for child in children:
        if not isinstance(child, str):
            continue
        text = _try_index(f"{scope}/{child}")
        if text:
            return text[:max_chars]

    # As a last resort, just return the children names (gives the LLM at
    # least a hint of which language the pack is in if the names are
    # English/Italian/whatever).
    return " ".join(c for c in children if isinstance(c, str))[:max_chars]


def _translate_query(query: str, index_sample: str, model: str) -> str:
    """LLM keyword-extraction call. Given a user query (any language) and a
    sample of the pack's index, produce 5-10 keywords in the pack's
    language that BM25 can match against page titles/summaries. Returns
    the original query on any failure (degraded but functional)."""
    if not index_sample.strip():
        return query

    import ollama

    system = (
        "You build a keyword query for a BM25 full-text search. "
        "Detect the language of the knowledge base from the index sample, "
        "then output 5-10 keywords in THAT language that best cover the "
        "user's question. Include synonyms, domain-specific terms, and "
        "proper names that are likely to appear in page titles or summaries. "
        "Reply with the keywords only, space-separated. No punctuation, no "
        "explanations, no quotes, no operators."
    )
    user = (
        f"Index sample (first {len(index_sample)} chars):\n{index_sample}\n\n"
        f"User question: {query}\n"
        "Keywords:"
    )
    try:
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            think=False,
            keep_alive=-1,
            options={"temperature": 0.0, "num_predict": 64, "num_ctx": 1024},
            stream=False,
        )
        out = (resp.message.content or "").strip()
        out = out.strip('"').strip("'").strip("`")
        # Reject obviously pathological output (e.g. a sentence-long answer)
        if not out or len(out) > len(query) * 8 + 200:
            return query
        return out
    except Exception:
        return query
