"""
OCC Ingestion Pipeline — Karpathy LLM Wiki pattern.

Takes a raw source file, uses the local LLM to extract structured wiki pages,
writes them to the expert pack's wiki/ directory.

Usage:
    python -m occ.ingestion.ingest <pack_dir> <raw_file>
"""
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ollama
from node.deliberation.engine import _extract_token

# ── Prompts ────────────────────────────────────────────────────────────────────

_EXTRACT_CONCEPTS_PROMPT = """/no_think

You are an expert knowledge compiler. Given a technical source document, your job
is to identify the distinct concepts that deserve their own wiki page.

Source document:
---
{source_text}
---

List the concepts to extract as wiki pages. Each concept should be a focused,
specific topic (not too broad, not too narrow).

Reply ONLY with a JSON array of objects, no other text:
[
  {{"slug": "concept-slug", "title": "Concept Title", "summary": "one sentence"}},
  ...
]
"""

_WRITE_PAGE_PROMPT = """/no_think

You are an expert knowledge compiler writing a wiki page for a knowledge base.

Source document:
---
{source_text}
---

Write a comprehensive wiki page for this concept: "{title}"

The page must follow this EXACT format:

=== WIKI PAGE START ===
---
title: {title}
slug: {slug}
source: {source_name}
confidence: high
tags: [tag1, tag2]
---

# {title}

[Write a clear, precise explanation of this concept. Include all key technical
details from the source. Use headers, bullet points, and code blocks where useful.
Be specific — someone reading this should know exactly how to implement or use this.]

## Key Points
- [bullet point 1]
- [bullet point 2]

=== WIKI PAGE END ===
"""

# ── Core functions ─────────────────────────────────────────────────────────────

def extract_concepts(source_text: str, model: str) -> list[dict]:
    """Ask the LLM to identify what wiki pages to create from a source."""
    prompt = _EXTRACT_CONCEPTS_PROMPT.format(source_text=source_text[:6000])
    tokens = []
    for chunk in ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1, "num_predict": 800},
        stream=True,
    ):
        t = _extract_token(chunk)
        if t:
            tokens.append(t)

    raw = "".join(tokens).strip()
    # Extract JSON array from response
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        return []
    try:
        import json
        return json.loads(match.group())
    except Exception:
        return []


def write_wiki_page(concept: dict, source_text: str, source_name: str, model: str) -> str:
    """Ask the LLM to write a full wiki page for a concept."""
    prompt = _WRITE_PAGE_PROMPT.format(
        source_text=source_text[:6000],
        title=concept["title"],
        slug=concept["slug"],
        source_name=source_name,
    )
    tokens = []
    for chunk in ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.2, "num_predict": 1200},
        stream=True,
    ):
        t = _extract_token(chunk)
        if t:
            tokens.append(t)
    return "".join(tokens).strip()


def parse_wiki_page(raw_output: str) -> str | None:
    """Extract the wiki page content between the markers."""
    match = re.search(
        r'=== WIKI PAGE START ===(.*?)=== WIKI PAGE END ===',
        raw_output,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    # Fallback: if LLM didn't use markers, return the whole output
    if raw_output.startswith("---"):
        return raw_output
    return None


def update_index(wiki_dir: Path, pages: list[dict]):
    """Regenerate _index.md from all wiki pages."""
    index_path = wiki_dir / "_index.md"
    lines = ["# Wiki Index\n", f"Last updated: 2026-05-01\n\n## Pages\n\n",
             "| File | Title | Summary |\n", "|------|-------|---------|\n"]
    for p in pages:
        lines.append(f"| {p['slug']}.md | {p['title']} | {p.get('summary', '')} |\n")
    index_path.write_text("".join(lines), encoding="utf-8")


def append_log(wiki_dir: Path, message: str):
    log_path = wiki_dir / "log.md"
    entry = f"\n## [2026-05-01] ingest | {message}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


# ── Main ───────────────────────────────────────────────────────────────────────

def ingest(pack_dir: Path, raw_file: Path, model: str):
    wiki_dir = pack_dir / "wiki" / "concepts"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    source_text = raw_file.read_text(encoding="utf-8")
    source_name = raw_file.stem

    print(f"\n[OCC Ingestion] Source: {raw_file.name}")
    print(f"[OCC Ingestion] Model:  {model}")
    print(f"[OCC Ingestion] Pack:   {pack_dir}\n")

    # Step 1: Extract concept list
    print("Step 1/3 — Identifying concepts...")
    concepts = extract_concepts(source_text, model)
    if not concepts:
        print("  ! No concepts extracted. Check model output.")
        return
    print(f"  ✓ Found {len(concepts)} concepts: {[c['title'] for c in concepts]}\n")

    # Step 2: Write a wiki page for each concept
    print("Step 2/3 — Writing wiki pages...")
    written = []
    for concept in concepts:
        slug = re.sub(r'[^a-z0-9-]', '-', concept["slug"].lower())
        print(f"  → {concept['title']}...", end=" ", flush=True)

        raw_page = write_wiki_page(concept, source_text, source_name, model)
        page_content = parse_wiki_page(raw_page)

        if page_content:
            page_path = wiki_dir / f"{slug}.md"
            page_path.write_text(page_content, encoding="utf-8")
            written.append({"slug": slug, "title": concept["title"],
                             "summary": concept.get("summary", "")})
            print("✓")
        else:
            print("✗ (parse failed)")

    # Step 3: Update index and log
    print("\nStep 3/3 — Updating index and log...")
    update_index(pack_dir / "wiki", written)
    append_log(pack_dir / "wiki", f"Ingested {raw_file.name} → {len(written)} pages")
    print(f"\n[OCC Ingestion] Done. {len(written)} pages written to {wiki_dir}\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m occ.ingestion.ingest <pack_dir> <raw_file> [model]")
        sys.exit(1)

    pack = Path(sys.argv[1])
    raw = Path(sys.argv[2])
    mdl = sys.argv[3] if len(sys.argv) > 3 else "qwen3.5:9b"
    ingest(pack, raw, mdl)
