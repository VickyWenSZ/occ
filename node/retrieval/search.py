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


def keyword_search(wiki_dir: Path, query: str, max_chars: int = 8000) -> str:
    """Keyword search across wiki markdown files. Returns relevant excerpts.

    Scales dynamically: more max_chars → more files and longer excerpts.
    """
    if not wiki_dir.exists():
        return ""

    terms = [
        t for t in re.findall(r'\w+', query.lower())
        if len(t) > 2 and t not in _STOP_WORDS
    ]
    if not terms:
        return ""

    scored: list[tuple[int, Path, str]] = []
    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name.startswith("_"):
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

    # Dynamic scaling: more budget → more files, longer excerpts
    max_files = min(len(scored), max(5, max_chars // 2000))
    excerpt_size = max_chars // max(max_files, 1)

    collected = []
    for _, path, text in scored[:max_files]:
        excerpt = text[:excerpt_size]
        collected.append(f"[{path.stem}]\n{excerpt}")

    return "\n\n".join(collected)
