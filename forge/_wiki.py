"""
Wiki file operations for OCC Forge.
Writes pages, index.md, log.md, schema.md.
"""
import re
from pathlib import Path
from datetime import date

try:
    import yaml
except ImportError:
    raise RuntimeError("pyyaml not installed. Run: pip install pyyaml")


def write_page(wiki_dir: Path, slug: str, content: str) -> Path:
    """
    Write a wiki page after cleaning the LLM output.
    Raises ValueError if the cleaned content does not begin with a valid
    YAML frontmatter block (`---\\n…\\n---`). Callers should catch this and
    skip the page rather than persist a malformed file.
    """
    cleaned = _normalize_llm_page_output(content)
    concepts_dir = wiki_dir / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    filename = _slug_to_filename(slug)
    path = concepts_dir / filename
    path.write_text(_dedup_sources(cleaned), encoding="utf-8")
    return path


_CODE_FENCE_OPEN_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n")
_CODE_FENCE_CLOSE_RE = re.compile(r"\n```\s*$")
_FRONTMATTER_START_RE = re.compile(r"(?m)^---\s*\n")
_UNQUOTED_SCALAR_RE = re.compile(r"^(\s*)(title|summary):\s*(.+?)\s*$")

# Patterns that indicate the LLM copied the prompt template verbatim instead
# of replacing the placeholder. Triggered for `title`, `summary` and `tags`.
# Cause discovered 2026-05-14: a prompt template that said
#   summary: "REPLACE WITH ONE SENTENCE — must be a single quoted string …"
# was copied verbatim by ~60% of pages.
_TEMPLATE_LEAKAGE_PATTERNS = [
    re.compile(r"REPLACE\s+WITH", re.IGNORECASE),
    re.compile(r"<<\s*WRITE", re.IGNORECASE),
    re.compile(r"<<\s*TAG\d*\s*>>", re.IGNORECASE),
    re.compile(r"<<\s*SUMMARY", re.IGNORECASE),
    re.compile(r"<<\s*TITLE", re.IGNORECASE),
    re.compile(r"must\s+be\s+a\s+single\s+quoted\s+string", re.IGNORECASE),
    re.compile(r"3-?5\s+relevant\s+lowercase\s+keywords?", re.IGNORECASE),
    re.compile(r"^\s*replace\s+with", re.IGNORECASE),
    re.compile(r"never\s+a\s+yaml\s+list", re.IGNORECASE),
    re.compile(r"^[A-Z<\[].{0,5}(WRITE|REPLACE|FILL)\b", re.IGNORECASE),
]

# Stale `### See Also` sub-subsection (three hashes, wrong heading level)
# carrying the cross-link placeholder. The LLM occasionally emits this in
# the body, beside the proper `## See Also` section, leaving the placeholder
# behind for the cross-link pass to miss.
_STALE_SEE_ALSO_BLOCK_RE = re.compile(
    r"\n###\s+See\s+Also\s*\n+_To be linked after compilation\._\s*\n*",
    re.IGNORECASE,
)


def _detect_placeholder_leakage(parsed_fm: dict) -> str | None:
    """Return a human description of placeholder leakage, or None if clean.

    Checks summary/title for any template-leakage pattern and tags for
    instructional strings that look like the unfilled prompt template.
    """
    for field in ("summary", "title"):
        value = parsed_fm.get(field)
        if value is None:
            continue
        s = str(value)
        for pat in _TEMPLATE_LEAKAGE_PATTERNS:
            if pat.search(s):
                return f"{field} leaks template placeholder: {s[:80]!r}"

    tags = parsed_fm.get("tags") or []
    if isinstance(tags, list):
        for t in tags:
            ts = str(t).strip()
            for pat in _TEMPLATE_LEAKAGE_PATTERNS:
                if pat.search(ts):
                    return f"tags leak template placeholder: {ts!r}"
            # Tags should be short keywords. An instructional string is
            # typically multi-word and long. Be permissive: allow up to
            # ~4 words per tag (e.g. `parallel-distributed-processing` is
            # one token; `large language model` is three words).
            if " " in ts and len(ts.split()) > 4:
                return f"tag looks instructional (too many words): {ts!r}"
            if len(ts) > 60:
                return f"tag too long (likely instructional): {ts[:60]!r}…"
    return None


def _normalize_llm_page_output(content: str) -> str:
    """
    Strip code-fence wrappers and any preamble before the YAML frontmatter
    block, verify the frontmatter parses as YAML, reject placeholder
    template leakage, strip stale `### See Also` blocks, and repair
    common LLM YAML mistakes. Raise ValueError if no recoverable
    frontmatter block can be produced — caller retries.

    Handles known LLM failure modes:
      - Whole response wrapped in ```markdown / ```md / ```yaml / ``` fences
      - Explanatory preamble (e.g. "Here is the wiki page:\\n\\n---\\n…")
      - Leading BOM, leading whitespace
      - Trailing closing ``` fence
      - Unquoted `title:`/`summary:` lines containing a colon (auto-repaired)
      - `summary` or `tags` copying the prompt template verbatim (rejected → retry)
      - Stale `### See Also` (wrong heading level) with `_To be linked after compilation._`
    """
    if not isinstance(content, str):
        raise ValueError("write_page: content is not a string")

    text = content.lstrip("﻿").lstrip()
    if not text:
        raise ValueError("write_page: empty content")

    open_m = _CODE_FENCE_OPEN_RE.match(text)
    if open_m:
        text = text[open_m.end():]
        text = _CODE_FENCE_CLOSE_RE.sub("", text).rstrip() + "\n"

    fm_match = _FRONTMATTER_START_RE.search(text)
    if not fm_match:
        raise ValueError("write_page: no `---` frontmatter opener found")
    if fm_match.start() != 0:
        text = text[fm_match.start():]

    after_open = text[len(fm_match.group(0)):]
    close_m = _FRONTMATTER_START_RE.search(after_open)
    if not close_m:
        raise ValueError("write_page: no closing `---` for frontmatter block")

    yaml_block = after_open[: close_m.start()]
    rest = after_open[close_m.start():]

    parsed: dict | None = None
    try:
        parsed = yaml.safe_load(yaml_block)
        if not isinstance(parsed, dict):
            raise yaml.YAMLError("frontmatter is not a YAML mapping")
    except yaml.YAMLError:
        repaired = _repair_unquoted_scalars(yaml_block)
        try:
            parsed = yaml.safe_load(repaired)
            if not isinstance(parsed, dict):
                raise yaml.YAMLError("repaired frontmatter is not a YAML mapping")
        except yaml.YAMLError as e:
            raise ValueError(f"write_page: YAML frontmatter cannot be parsed even after repair: {e}")
        yaml_block = repaired

    # Reject placeholder leakage — caller retries
    leakage = _detect_placeholder_leakage(parsed)
    if leakage:
        raise ValueError(f"write_page: {leakage}")

    # Strip stale `### See Also` sub-subsections carrying the cross-link
    # placeholder (the proper `## See Also` lives elsewhere and the cross-link
    # pass only touches `## ` headings)
    rest_cleaned = _STALE_SEE_ALSO_BLOCK_RE.sub("\n\n", rest)

    text = "---\n" + yaml_block + rest_cleaned
    if not text.endswith("\n"):
        text += "\n"
    return text


def _repair_unquoted_scalars(yaml_block: str) -> str:
    """
    Quote `title:` and `summary:` lines that are unquoted and contain a
    YAML-breaking character (`:` or `#`). Conservative: only touches those
    two keys, leaves already-quoted or list values alone.
    """
    out_lines = []
    for line in yaml_block.splitlines():
        m = _UNQUOTED_SCALAR_RE.match(line)
        if not m:
            out_lines.append(line)
            continue
        indent, key, val = m.groups()
        # Leave already-quoted or list-typed values alone
        if val.startswith(('"', "'", "[")):
            out_lines.append(line)
            continue
        if ":" not in val and "#" not in val:
            out_lines.append(line)
            continue
        safe = val.replace("\\", "\\\\").replace('"', '\\"')
        out_lines.append(f'{indent}{key}: "{safe}"')
    return "\n".join(out_lines) + ("\n" if yaml_block.endswith("\n") else "")


def _dedup_sources(content: str) -> str:
    """
    Remove duplicate entries from the YAML `sources:` list in frontmatter and
    from `## Sources` bullet lines in the body. The LLM occasionally appends
    the same raw_path twice when a page is enriched from a source it already
    contains (e.g. multi-concept ingest of the same Wikipedia article).
    Order-preserving dedup; bullets are deduped by their full text.
    """
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---\n", 4)
    if end == -1:
        return content
    fm_block = content[4:end]
    body = content[end + 5:]

    # Dedup YAML `sources:` list (order-preserving) without parsing the whole
    # frontmatter — keeps unrelated quoting/whitespace intact.
    fm_block = re.sub(
        r"(^sources:\s*\n)((?:[ \t]+-[^\n]*\n)+)",
        lambda m: m.group(1) + _dedup_yaml_list_block(m.group(2)),
        fm_block,
        flags=re.MULTILINE,
    )

    # Dedup `## Sources` bullets (exact-line match, order-preserving)
    body = re.sub(
        r"(^##\s+Sources\s*\n)((?:.*\n)*?)(?=^##\s+|\Z)",
        lambda m: m.group(1) + _dedup_bullet_block(m.group(2)),
        body,
        flags=re.MULTILINE,
    )

    return f"---\n{fm_block}\n---\n{body}"


def _dedup_yaml_list_block(block: str) -> str:
    seen: set[str] = set()
    out_lines: list[str] = []
    for line in block.splitlines(keepends=True):
        key = line.strip()
        if key in seen:
            continue
        seen.add(key)
        out_lines.append(line)
    return "".join(out_lines)


def _dedup_bullet_block(block: str) -> str:
    seen: set[str] = set()
    out_lines: list[str] = []
    for line in block.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("- "):
            if stripped in seen:
                continue
            seen.add(stripped)
        out_lines.append(line)
    return "".join(out_lines)


def fill_see_also(wiki_dir: Path, slug: str, links: list[dict]) -> bool:
    """
    Replace the `## See Also` section of a page with `links`.
    Each link: {slug, title, note}.

    Always consumes the placeholder `_To be linked after compilation._` so it
    cannot linger after the cross-link pass. When `links` is empty (or every
    candidate was self-referential), the section is rewritten with a sentinel
    line ("_No related pages in this pack._") rather than left as the
    placeholder, which avoids the page being re-picked-up forever by the
    straggler pass.

    Returns True iff the page was rewritten on disk.
    """
    path = wiki_dir / "concepts" / _slug_to_filename(slug)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")

    bullets = []
    for l in (links or []):
        target_slug = l.get("slug", "")
        if not target_slug or target_slug == slug:
            continue
        target_title = l.get("title", target_slug)
        note = l.get("note", "").strip()
        bullets.append(
            f"- [[{target_slug}|{target_title}]]"
            + (f" — {note}" if note else "")
        )

    if bullets:
        new_body = "\n".join(bullets) + "\n"
    else:
        new_body = "_No related pages in this pack._\n"
    new_section = "## See Also\n\n" + new_body

    pattern = re.compile(r"^##\s+See Also\s*$.*?(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    if pattern.search(text):
        new_text = pattern.sub(new_section + "\n", text, count=1)
    else:
        # No See Also section yet — insert before Sources, or before Key Points, or at end
        for anchor in ("## Sources", "## Key Points"):
            if anchor in text:
                new_text = text.replace(anchor, new_section + "\n" + anchor, 1)
                break
        else:
            new_text = text.rstrip() + "\n\n" + new_section
    path.write_text(new_text, encoding="utf-8")
    return True


def scan_existing_pages(wiki_dir: Path) -> list[dict]:
    """Read frontmatter from all existing concept pages."""
    concepts_dir = wiki_dir / "concepts"
    if not concepts_dir.exists():
        return []
    pages = []
    for md_file in sorted(concepts_dir.glob("*.md")):
        if md_file.name.startswith("_"):
            continue  # _index.md and any other folder-meta file
        text = md_file.read_text(encoding="utf-8", errors="replace")
        fm = _parse_frontmatter(text)
        pages.append({
            "slug": _coerce_str(fm.get("slug"), md_file.stem),
            "title": _coerce_str(fm.get("title"), md_file.stem),
            "summary": _coerce_str(fm.get("summary"), ""),
        })
    return pages


def _coerce_str(value, fallback: str) -> str:
    """LLMs occasionally emit summary/title as a YAML list of bullets. Flatten."""
    if value is None:
        return fallback
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "; ".join(str(x).strip() for x in value if x is not None)
    return str(value)


def update_index(wiki_dir: Path, pages: list[dict]):
    """Rebuild index.md from all pages (existing + newly written)."""
    today = date.today().isoformat()
    seen = set()
    deduped = []
    for p in pages:
        if p["slug"] not in seen:
            seen.add(p["slug"])
            deduped.append(p)
    deduped.sort(key=lambda x: x.get("slug", ""))

    lines = [
        f"# Wiki Index\n\n",
        f"Last updated: {today}  \n",
        f"Total pages: {len(deduped)}\n\n",
        "## Pages\n\n",
        "| File | Title | Summary |\n",
        "|------|-------|---------|\n",
    ]
    for p in deduped:
        fname = _slug_to_filename(p["slug"])
        title = p.get("title", "")
        summary = p.get("summary", "").replace("|", "/")
        lines.append(f"| concepts/{fname} | {title} | {summary} |\n")

    (wiki_dir / "index.md").write_text("".join(lines), encoding="utf-8")
    _update_concepts_index(wiki_dir, deduped)


def _update_concepts_index(wiki_dir: Path, pages: list[dict]):
    """Write _index.md inside concepts/ (one _index.md per directory, Karpathy pattern)."""
    today = date.today().isoformat()
    concepts_dir = wiki_dir / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Concepts Index\n\n",
        f"> Compiled wiki articles for this expert pack.\n\n",
        f"Last updated: {today}\n\n",
        "## Contents\n\n",
        "| File | Title | Summary |\n",
        "|------|-------|--------|\n",
    ]
    for p in pages:
        fname = _slug_to_filename(p["slug"])
        title = p.get("title", "").replace("|", "/")
        summary = p.get("summary", "").replace("|", "/")
        lines.append(f"| [{fname}]({fname}) | {title} | {summary} |\n")
    (concepts_dir / "_index.md").write_text("".join(lines), encoding="utf-8")


def append_log(wiki_dir: Path, source_name: str, n_pages: int, source_url: str = ""):
    today = date.today().isoformat()
    log_path = wiki_dir / "log.md"
    entry = (
        f"\n## [{today}] ingest | {source_name}\n\n"
        f"- Pages written: {n_pages}\n"
        f"- Source: {source_url}\n"
    )
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


def append_images_to_raw(
    pack_dir: Path,
    raw_path: str,
    images: list[dict],
    source_slug: str,
) -> None:
    """
    Append a `## Images` section to a raw source file with one bullet per
    relevant image. Each image dict: {filename, caption}.

    Writes a relative link from the raw file's location to wiki/assets/<slug>/<file>.
    Raw lives in `pack_dir/raw/articles/`, assets live in `pack_dir/wiki/assets/`,
    so the relative path is `../../wiki/assets/<slug>/<filename>`.
    """
    if not images:
        return
    raw_file = pack_dir / raw_path
    if not raw_file.exists():
        return

    lines = ["", "## Images", ""]
    for img in images:
        caption = (img.get("caption") or "").strip().replace("\n", " ")
        rel = f"../../wiki/assets/{source_slug}/{img['filename']}"
        lines.append(f"- ![{caption}]({rel}) — {caption}" if caption else f"- ![]({rel})")
    lines.append("")

    with open(raw_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_raw_source(pack_dir: Path, source_name: str, source_url: str, text: str) -> str:
    """
    Write the original source text immutably to raw/articles/.
    Returns the relative path from pack_dir (e.g. 'raw/articles/2026-05-09-prehistory.md').
    Never overwrites an existing file — appends -2, -3, etc. if needed.
    """
    today = date.today().isoformat()
    raw_dir = pack_dir / "raw" / "articles"
    raw_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r'[^a-z0-9-]', '-', source_name.lower()).strip('-')
    base = f"{today}-{slug}"
    filename = f"{base}.md"
    counter = 2
    while (raw_dir / filename).exists():
        filename = f"{base}-{counter}.md"
        counter += 1

    content = (
        f"---\n"
        f"title: \"{source_name}\"\n"
        f"source: \"{source_url}\"\n"
        f"type: articles\n"
        f"ingested: {today}\n"
        f"tags: []\n"
        f"summary: \"\"\n"
        f"---\n\n"
        f"{text}\n"
    )
    (raw_dir / filename).write_text(content, encoding="utf-8")
    _update_raw_index(pack_dir)
    return f"raw/articles/{filename}"


def _update_raw_index(pack_dir: Path):
    """Rebuild raw/_index.md and raw/articles/_index.md from files on disk."""
    today = date.today().isoformat()
    raw_dir = pack_dir / "raw"
    articles_dir = raw_dir / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    articles = []
    for md_file in sorted(articles_dir.glob("*.md")):
        if md_file.name == "_index.md":
            continue
        fm = _parse_frontmatter(md_file.read_text(encoding="utf-8", errors="replace"))
        articles.append({
            "file": md_file.name,
            "title": fm.get("title", md_file.stem),
            "ingested": fm.get("ingested", ""),
        })

    art_lines = [
        "# Articles Index\n\n",
        f"Last updated: {today}\n\n",
        "## Contents\n\n",
        "| File | Title | Ingested |\n",
        "|------|-------|----------|\n",
    ]
    for a in articles:
        art_lines.append(f"| [{a['file']}]({a['file']}) | {a['title']} | {a['ingested']} |\n")
    (articles_dir / "_index.md").write_text("".join(art_lines), encoding="utf-8")

    raw_lines = [
        "# Raw Sources Index\n\n",
        f"Last updated: {today}  \n",
        f"Total sources: {len(articles)}\n\n",
        "## Contents\n\n",
        "| File | Title | Ingested |\n",
        "|------|-------|----------|\n",
    ]
    for a in articles:
        raw_lines.append(
            f"| [articles/{a['file']}](articles/{a['file']}) | {a['title']} | {a['ingested']} |\n"
        )
    (raw_dir / "_index.md").write_text("".join(raw_lines), encoding="utf-8")


def ensure_schema(wiki_dir: Path, pack_name: str):
    """Create schema.md if it doesn't exist yet."""
    path = wiki_dir / "schema.md"
    if path.exists():
        return
    content = f"""# Schema — {pack_name} pack

## Page structure
- Location: `wiki/concepts/<slug>.md`
- Slug: lowercase, hyphen-separated (e.g. `docker-compose`)

## Frontmatter fields
- `title`: human-readable concept name
- `slug`: matches filename without .md extension
- `source`: name of the raw source document
- `confidence`: high / medium / low
- `tags`: list of relevant keywords

## Writing conventions
- Dense and factual — optimized for LLM consumption, not human reading
- Use `##` subheaders for logical sections
- Use code blocks for commands, configs, examples
- End every page with a `## Key Points` section (3-5 bullets)
- Flag contradictions between sources with `> ⚠️ Conflict: ...` blockquotes

## Source tracking
All ingestion events are recorded in `log.md`.
Each page's `source:` frontmatter field traces it back to the original document.
"""
    path.write_text(content, encoding="utf-8")


def _slug_to_filename(slug: str) -> str:
    return re.sub(r'[^a-z0-9-]', '-', slug.lower()).strip('-') + ".md"


def _parse_frontmatter(text: str) -> dict:
    match = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
    if not match:
        return {}
    try:
        return yaml.safe_load(match.group(1)) or {}
    except Exception:
        return {}
