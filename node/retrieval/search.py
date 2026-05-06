import re
from pathlib import Path

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
        # Skip header and separator rows
        if parts[0].lower() in ("file", "---", "") or parts[0].startswith("---"):
            continue
        entries.append({
            "file": parts[0],
            "title": parts[1] if len(parts) > 1 else "",
            "summary": parts[2] if len(parts) > 2 else "",
        })
    return entries


def keyword_search(wiki_dir: Path, query: str, max_chars: int = 8000) -> str:
    """Karpathy LLM Wiki retrieval:
    1. Read index.md to find relevant pages by matching query against title+summary.
    2. Read those pages in full (up to max_chars budget).
    3. Fallback to direct file search only if index is absent or yields nothing.
    """
    if not wiki_dir.exists():
        return ""

    terms = [
        t for t in re.findall(r'\w+', query.lower())
        if len(t) > 2 and t not in _STOP_WORDS
    ]
    if not terms:
        return ""

    # ── Step 1: score pages via index.md ──────────────────────────────────────
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

            # ── Step 2: read selected pages in full ───────────────────────────
            max_pages = max(3, max_chars // 3000)
            collected = []
            total_chars = 0
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

    # ── Fallback: direct keyword search across files (no index) ───────────────
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
