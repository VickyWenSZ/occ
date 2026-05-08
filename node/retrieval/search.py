import json
import math
import re
from pathlib import Path

import ollama

_EMBED_MODEL = "nomic-embed-text"
_PAGE_SIMILARITY_THRESHOLD = 0.30   # min score to include a page within a pack
_PACK_SIMILARITY_THRESHOLD = 0.35   # min score to consider a pack relevant at all

_STOP_WORDS = {
    # Italian
    "che", "come", "cosa", "chi", "quando", "dove", "perché", "perche",
    "quale", "quali", "quanto", "quanti", "quanta", "quante",
    "sono", "sei", "siamo", "siete", "hanno", "hai", "avere", "essere",
    "non", "con", "per", "del", "della", "dei", "delle", "dal", "dalla",
    "nel", "nella", "nei", "nelle", "sul", "sulla", "sui", "sulle",
    "gli", "una", "uno", "gli", "tra", "fra", "poi", "già", "anche",
    "però", "ciao", "buon", "buona", "caro", "cara", "bene", "male",
    "tutto", "tutta", "tutti", "tutte", "questo", "questa", "questi",
    "quello", "quella", "quelli", "quelle", "molto", "poco", "bello",
    # English
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "her", "was", "one", "our", "out", "day", "get", "has", "him",
    "his", "how", "its", "may", "new", "now", "old", "see", "two",
    "use", "way", "who", "did", "let", "put", "say", "she", "too",
    "any", "hey", "bye", "yes", "yep", "nope", "what", "when",
    "where", "which", "with", "this", "that", "from", "have", "been",
    "will", "they", "them", "than", "then", "just", "into", "over",
    "also", "some", "more", "very", "well", "good", "hello", "thanks",
}

# In-process cache: same query won't be embedded twice in one request
_embed_cache: dict[str, list[float]] = {}


# ── Index parsing ─────────────────────────────────────────────────────────────

def _parse_index(index_path: Path) -> list[dict]:
    """Parse index.md table → list of {file, title, summary}."""
    entries = []
    if not index_path.exists():
        return entries
    try:
        text = index_path.read_text(encoding="utf-8")
    except Exception:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 2:
            continue
        if parts[0].lower() in ("file", "---", "") or parts[0].startswith("---"):
            continue
        entries.append({
            "file": parts[0],
            "title": parts[1] if len(parts) > 1 else "",
            "summary": parts[2] if len(parts) > 2 else "",
        })
    return entries


# ── Embedding primitives ──────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed(text: str) -> list[float] | None:
    """Embed text via nomic-embed-text. Returns None if unavailable."""
    if text in _embed_cache:
        return _embed_cache[text]
    try:
        resp = ollama.embed(model=_EMBED_MODEL, input=text)
        vec = resp.embeddings[0]
        _embed_cache[text] = vec
        return vec
    except Exception:
        return None


# ── Embeddings file ───────────────────────────────────────────────────────────

def _embeddings_path(wiki_dir: Path) -> Path:
    return wiki_dir / "embeddings.json"


def load_embeddings(wiki_dir: Path) -> dict | None:
    """Load embeddings.json if it exists and is not stale vs index.md."""
    path = _embeddings_path(wiki_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        index_path = wiki_dir / "index.md"
        if index_path.exists() and data.get("index_mtime", 0) < index_path.stat().st_mtime:
            return None  # stale — index was updated after embeddings were built
        return data if data.get("entries") else None
    except Exception:
        return None


_BUILD_SKIP = "skip"   # sentinel: no index.md, skip silently (not an error)

def build_embeddings(wiki_dir: Path) -> bool | str:
    """Build embeddings.json from index.md entries.
    Returns True on success, False if nomic failed, _BUILD_SKIP if no index.md.
    """
    index_path = wiki_dir / "index.md"
    entries = _parse_index(index_path)
    if not entries:
        return _BUILD_SKIP

    embedded = []
    for entry in entries:
        text = f"{entry['title']}. {entry['summary']}"
        vec = _embed(text)
        if vec is None:
            return False  # nomic unavailable
        embedded.append({
            "file": entry["file"],
            "title": entry["title"],
            "summary": entry["summary"],
            "vector": vec,
        })

    index_mtime = index_path.stat().st_mtime if index_path.exists() else 0.0
    data = {"model": _EMBED_MODEL, "index_mtime": index_mtime, "entries": embedded}
    _embeddings_path(wiki_dir).write_text(json.dumps(data), encoding="utf-8")
    return True


def pack_max_similarity(wiki_dir: Path, query_vec: list[float]) -> float | None:
    """Max cosine similarity between query_vec and any page in this pack.
    Returns None if no embeddings exist (caller should fall back to keyword)."""
    emb = load_embeddings(wiki_dir)
    if not emb or not emb.get("entries"):
        return None
    return max(_cosine(query_vec, e["vector"]) for e in emb["entries"])


# ── Pack-level relevance (used by MultiPackRetriever) ────────────────────────

def _keyword_relevant(wiki_dir: Path, query: str) -> bool:
    """Does this pack contain any meaningful query term?
    Checks pack name, index.md entries; if no index, scans concept files directly."""
    terms = [t for t in re.findall(r'\w+', query.lower()) if len(t) > 2 and t not in _STOP_WORDS]
    if not terms:
        return False
    pack_name = wiki_dir.parent.name.lower()
    if any(t in pack_name or pack_name in t for t in terms):
        return True
    entries = _parse_index(wiki_dir / "index.md")
    if entries:
        for entry in entries:
            searchable = (entry["title"] + " " + entry["summary"]).lower()
            if any(t in searchable for t in terms):
                return True
        return False
    # No index.md — scan concept files directly (old-format packs).
    # Require at least 2 distinct term matches to avoid single-word false positives.
    required = min(2, len(terms))
    best_score = 0
    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name in ("index.md", "_index.md", "log.md", "schema.md"):
            continue
        try:
            text = md_file.read_text(encoding="utf-8").lower()
            score = sum(1 for t in terms if t in text)
            best_score = max(best_score, score)
        except Exception:
            continue
    return best_score >= required


def relevant_pack_dirs(wiki_dirs: list[Path], query: str) -> list[Path]:
    """Return which wiki dirs are semantically relevant to query.

    Priority:
    1. If any pack name appears explicitly in the query terms, return only those packs.
       (e.g. "occ" in query → only the occ pack, not all 0.35+ packs)
    2. Otherwise return the single best-scoring pack via embeddings (above threshold).
    3. Fall back to keyword match if embeddings unavailable.
    """
    # Step 1: explicit pack-name match — highest precision
    terms = [t for t in re.findall(r'\w+', query.lower()) if len(t) > 2 and t not in _STOP_WORDS]
    name_matches = [
        wd for wd in wiki_dirs
        if any(t in wd.parent.name.lower() or wd.parent.name.lower() in t for t in terms)
    ]
    if name_matches:
        return name_matches

    # Step 2: top-1 embedding pack (avoids multi-pack context dilution)
    query_vec = _embed(query)
    if query_vec is not None:
        scored = []
        for wd in wiki_dirs:
            sim = pack_max_similarity(wd, query_vec)
            if sim is not None:
                scored.append((sim, wd))
            elif _keyword_relevant(wd, query):
                scored.append((_PACK_SIMILARITY_THRESHOLD, wd))
        if scored:
            scored.sort(reverse=True)
            best_sim, best_wd = scored[0]
            if best_sim >= _PACK_SIMILARITY_THRESHOLD:
                return [best_wd]

    # Step 3: keyword fallback
    return [wd for wd in wiki_dirs if _keyword_relevant(wd, query)]


# ── Server-mode ref extraction (no content read) ─────────────────────────────

def get_relevant_page_refs(wiki_dir: Path, query: str, max_pages: int = 5) -> list[dict]:
    """
    Return [{pack, file, score}] for pages relevant to query WITHOUT reading content.
    pack is derived from wiki_dir.parent.name.
    Used by engine.py in server mode: engine fetches content remotely after calling this.
    """
    pack = wiki_dir.parent.name
    query_vec = _embed(query)
    emb = load_embeddings(wiki_dir)

    if emb and query_vec is not None:
        scored = [
            (_cosine(query_vec, e["vector"]), e["file"])
            for e in emb["entries"]
        ]
        scored = [(s, f) for s, f in scored if s >= _PAGE_SIMILARITY_THRESHOLD]
        scored.sort(reverse=True)
        return [{"pack": pack, "file": f, "score": round(s, 4)} for s, f in scored[:max_pages]]

    # Keyword fallback — nomic unavailable or no embeddings cached
    terms = [t for t in re.findall(r'\w+', query.lower()) if len(t) > 2 and t not in _STOP_WORDS]
    if not terms:
        return []
    scored_kw: list[tuple[float, str]] = []
    for entry in _parse_index(wiki_dir / "index.md"):
        searchable = (entry["title"] + " " + entry["summary"]).lower()
        score = sum(searchable.count(t) for t in terms)
        if score > 0:
            scored_kw.append((float(score), entry["file"]))
    scored_kw.sort(reverse=True)
    return [{"pack": pack, "file": f, "score": s} for s, f in scored_kw[:max_pages]]


# ── Main retrieval entry point ────────────────────────────────────────────────

def retrieve(wiki_dir: Path, query: str, max_chars: int = 8000) -> str:
    """Karpathy LLM Wiki retrieval — semantic when possible, keyword as fallback.

    Tries embedding-based page selection first (nomic-embed-text).
    Falls back to keyword search if embeddings unavailable or no match found.
    """
    emb = load_embeddings(wiki_dir)
    if emb:
        result = _semantic_search(wiki_dir, query, max_chars, emb)
        if result:
            return result
    return keyword_search(wiki_dir, query, max_chars)


def _semantic_search(wiki_dir: Path, query: str, max_chars: int, embeddings: dict) -> str:
    query_vec = _embed(query)
    if query_vec is None:
        return ""

    scored = [
        (_cosine(query_vec, e["vector"]), e["file"])
        for e in embeddings["entries"]
    ]
    scored = [(s, f) for s, f in scored if s >= _PAGE_SIMILARITY_THRESHOLD]
    if not scored:
        return ""

    scored.sort(reverse=True)
    max_pages = max(3, max_chars // 3000)
    collected, total_chars = [], 0

    for _, rel_path in scored[:max_pages]:
        page_path = wiki_dir / rel_path
        if not page_path.exists():
            continue
        try:
            content = page_path.read_text(encoding="utf-8")
        except Exception:
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        chunk = content[:remaining]
        collected.append(f"[{page_path.stem}]\n{chunk}")
        total_chars += len(chunk)

    return "\n\n".join(collected)


# ── Keyword search (fallback) ─────────────────────────────────────────────────

def keyword_search(wiki_dir: Path, query: str, max_chars: int = 8000) -> str:
    """Karpathy LLM Wiki retrieval via keyword matching on index.md.
    Used as fallback when embeddings are unavailable.
    """
    if not wiki_dir.exists():
        return ""

    terms = [
        t for t in re.findall(r'\w+', query.lower())
        if len(t) > 2 and t not in _STOP_WORDS
    ]
    if not terms:
        return ""

    index_path = wiki_dir / "index.md"
    entries = _parse_index(index_path)

    if entries:
        scored = []
        for entry in entries:
            searchable = (entry["title"] + " " + entry["summary"]).lower()
            score = sum(searchable.count(t) for t in terms)
            if score > 0:
                scored.append((score, entry["file"]))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            max_pages = max(3, max_chars // 3000)
            collected, total_chars = [], 0
            for _, rel_path in scored[:max_pages]:
                page_path = wiki_dir / rel_path
                if not page_path.exists():
                    continue
                try:
                    content = page_path.read_text(encoding="utf-8")
                except Exception:
                    continue
                remaining = max_chars - total_chars
                if remaining <= 0:
                    break
                chunk = content[:remaining]
                collected.append(f"[{page_path.stem}]\n{chunk}")
                total_chars += len(chunk)
            if collected:
                return "\n\n".join(collected)

    return _fallback_search(wiki_dir, terms, max_chars)


def _fallback_search(wiki_dir: Path, terms: list[str], max_chars: int) -> str:
    scored: list[tuple[int, Path, str]] = []
    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name in ("index.md", "log.md", "schema.md"):
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        low = text.lower()
        score = sum(low.count(t) for t in terms)
        if score > 0:
            scored.append((score, md_file, text))

    if not scored:
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    max_files = min(len(scored), max(3, max_chars // 2000))
    excerpt_size = max_chars // max(max_files, 1)
    collected = []
    for _, path, text in scored[:max_files]:
        collected.append(f"[{path.stem}]\n{text[:excerpt_size]}")
    return "\n\n".join(collected)
