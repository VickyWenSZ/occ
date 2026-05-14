"""
OCC Forge — mechanical lint (Karpathy LLM-wiki pattern, adapted to OCC).

Implements check codes from `_refs/nvk-llm-wiki/.../linting.md`:
  - C1   Structure          (Critical) — required files exist, frontmatter parses
  - C2   Frontmatter        (Critical/Warning) — required fields present, valid
  - C3   Index Consistency  (Warning) — index rows match files on disk
  - C4   Link Integrity     (Warning) — markdown links resolve, See Also bidirectional
  - C4b  Source Provenance  (Warning) — sources frontmatter resolves, no orphan raw
  - C5   Tag Hygiene        (Warning) — near-duplicate tags collapse to canonical form
  - C11  Canonical Placement (Critical) — file in directory matching its frontmatter

OCC adaptations vs Karpathy:
  - Master index is `wiki/index.md` (not `_index.md`); concepts has `_index.md`
  - Only `wiki/concepts/` (no topics/, references/, theses/)
  - Only `raw/articles/` (no papers/, repos/, notes/, data/)
  - `wiki/schema.md` plays the role of Karpathy's `config.md`

Each issue is a dict: {code, severity, message, path, fixed}.
Severity: critical | warning | suggestion | info.
Pass `fix=True` to apply auto-fixes for the issues that support it.
"""
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    raise RuntimeError("pyyaml not installed. Run: pip install pyyaml")


# ── Public entry point ────────────────────────────────────────────────────────

def run_structural_checks(wiki_dir: Path, pack_dir: Path, fix: bool = False) -> tuple[list[dict], dict]:
    """Run all mechanical checks. Returns (issues, summary)."""
    issues: list[dict] = []

    concepts_dir = wiki_dir / "concepts"
    raw_articles_dir = pack_dir / "raw" / "articles"

    pages = _scan_md_with_frontmatter(concepts_dir, pack_dir) if concepts_dir.exists() else []
    raws = _scan_md_with_frontmatter(raw_articles_dir, pack_dir) if raw_articles_dir.exists() else []

    _check_c1_structure(wiki_dir, pack_dir, pages, issues, fix)
    _check_c2_frontmatter(pages, raws, issues, fix)
    _check_c3_index(wiki_dir, pack_dir, pages, raws, issues, fix)
    _check_c4_links(wiki_dir, pages, issues, fix)
    _check_c4b_source_provenance(pack_dir, pages, raws, issues, fix)
    _check_c5_tag_hygiene(pages, issues, fix)
    _check_c11_placement(pages, raws, issues, fix)
    _check_m1_manifest_exists(pack_dir, issues, fix)
    _check_m2_manifest_summary(pack_dir, issues, fix)
    _check_s1_prompt_injection(pages, issues, fix)
    _check_s2_destructive_shell(pages, issues, fix)
    _check_s3_suspicious_urls(pages, issues, fix)
    _check_s5_control_chars(pages, issues, fix)
    _check_q1_page_length(pages, issues, fix)
    _check_q2_placeholders(pages, issues, fix)
    _check_q3_template_leakage(pages, issues, fix)
    _check_q4_index_summary_drift(wiki_dir, pages, issues, fix)

    summary = {
        "total":      len(issues),
        "critical":   sum(1 for i in issues if i["severity"] == "critical"),
        "warning":    sum(1 for i in issues if i["severity"] == "warning"),
        "suggestion": sum(1 for i in issues if i["severity"] == "suggestion"),
        "info":       sum(1 for i in issues if i["severity"] == "info"),
        "fixed":      sum(1 for i in issues if i.get("fixed")),
    }
    return issues, summary


def format_report(issues: list[dict], summary: dict, pack_name: str, fix_applied: bool) -> str:
    """Format issues as a human-readable markdown report. No internal codes."""
    from datetime import date

    lines = [
        f"## Structural Checks — {pack_name} — {date.today().isoformat()}",
        "",
        f"- Issues found: **{summary['total']}** "
        f"({summary['critical']} critical, {summary['warning']} warning, "
        f"{summary['suggestion']} suggestion, {summary['info']} info)",
    ]
    if fix_applied:
        lines.append(f"- Auto-fixed: **{summary['fixed']}**")
    lines.append("")

    for sev_label, sev_key in [
        ("Critical", "critical"),
        ("Warnings", "warning"),
        ("Suggestions", "suggestion"),
        ("Info", "info"),
    ]:
        bucket = [i for i in issues if i["severity"] == sev_key]
        if not bucket:
            continue
        lines.append(f"### {sev_label}")
        lines.append("")
        for i in bucket:
            tag = "✅ auto-fixed — " if i.get("fixed") else ""
            path = f" — `{i['path']}`" if i.get("path") else ""
            lines.append(f"- {tag}{i['message']}{path}")
        lines.append("")

    if summary["total"] == 0:
        lines.append("_All structural checks passed._")
        lines.append("")

    return "\n".join(lines)


# ── C1: Structure ─────────────────────────────────────────────────────────────

def _check_c1_structure(wiki_dir: Path, pack_dir: Path, pages: list[dict],
                        issues: list[dict], fix: bool):
    # Required files at wiki root
    for fname, severity in [("index.md", "critical"), ("schema.md", "warning")]:
        path = wiki_dir / fname
        if not path.exists():
            issues.append({
                "code": "1", "severity": severity,
                "message": f"Missing `wiki/{fname}`",
                "path": str(path.relative_to(pack_dir)),
                "fixed": False,
            })

    # Concepts _index.md (auto-fixable: regenerate from disk)
    concepts_idx = wiki_dir / "concepts" / "_index.md"
    if (wiki_dir / "concepts").exists() and not concepts_idx.exists():
        fixed = False
        if fix:
            try:
                import forge._wiki as wiki
                wiki._update_concepts_index(wiki_dir, [
                    {"slug": p["frontmatter"].get("slug", p["path"].stem),
                     "title": p["frontmatter"].get("title", p["path"].stem),
                     "summary": p["frontmatter"].get("summary", "")}
                    for p in pages
                ])
                fixed = concepts_idx.exists()
            except Exception:
                fixed = False
        issues.append({
            "code": "1", "severity": "warning",
            "message": "Missing `wiki/concepts/_index.md`",
            "path": str(concepts_idx.relative_to(pack_dir)),
            "fixed": fixed,
        })

    # Raw indexes (only required if raw exists)
    raw_dir = pack_dir / "raw"
    if raw_dir.exists():
        if not (raw_dir / "_index.md").exists():
            fixed = False
            if fix:
                try:
                    import forge._wiki as wiki
                    wiki._update_raw_index(pack_dir)
                    fixed = (raw_dir / "_index.md").exists()
                except Exception:
                    fixed = False
            issues.append({
                "code": "1", "severity": "warning",
                "message": "Missing `raw/_index.md`",
                "path": "raw/_index.md", "fixed": fixed,
            })
        articles_idx = raw_dir / "articles" / "_index.md"
        if (raw_dir / "articles").exists() and not articles_idx.exists():
            fixed = False
            if fix:
                try:
                    import forge._wiki as wiki
                    wiki._update_raw_index(pack_dir)
                    fixed = articles_idx.exists()
                except Exception:
                    fixed = False
            issues.append({
                "code": "1", "severity": "warning",
                "message": "Missing `raw/articles/_index.md`",
                "path": "raw/articles/_index.md", "fixed": fixed,
            })

    # Each page must have valid frontmatter
    for p in pages:
        if p["frontmatter"] is None:
            issues.append({
                "code": "1", "severity": "critical",
                "message": "Page has no valid YAML frontmatter (missing `---` block)",
                "path": str(p["path"].relative_to(pack_dir)), "fixed": False,
            })


# ── C2: Frontmatter ───────────────────────────────────────────────────────────

_PAGE_REQUIRED_CRITICAL = ["title", "category", "sources"]
_PAGE_REQUIRED_WARNING  = ["summary", "tags", "created", "updated"]
_RAW_REQUIRED_CRITICAL  = ["title", "source", "type"]
_RAW_REQUIRED_WARNING   = ["ingested", "tags"]


def _check_c2_frontmatter(pages: list[dict], raws: list[dict], issues: list[dict], fix: bool):
    for p in pages:
        fm = p["frontmatter"]
        if fm is None:
            continue  # already flagged by C1
        rel = p["rel_path"]

        for field in _PAGE_REQUIRED_CRITICAL:
            v = fm.get(field)
            empty = (v is None) or (isinstance(v, (str, list)) and len(v) == 0)
            if empty:
                fixed = False
                if fix and field == "title":
                    fixed = _autofix_title_from_heading(p)
                issues.append({
                    "code": "2", "severity": "critical",
                    "message": f"Frontmatter `{field}` missing or empty",
                    "path": rel, "fixed": fixed,
                })

        for field in _PAGE_REQUIRED_WARNING:
            v = fm.get(field)
            empty = (v is None) or (isinstance(v, (str, list)) and len(v) == 0)
            if empty:
                fixed = False
                if fix and field == "summary":
                    fixed = _autofix_summary_from_first_paragraph(p)
                issues.append({
                    "code": "2", "severity": "warning",
                    "message": f"Frontmatter `{field}` missing or empty",
                    "path": rel, "fixed": fixed,
                })

        cat = fm.get("category")
        if cat and cat != "concept":
            issues.append({
                "code": "2", "severity": "warning",
                "message": f"Frontmatter `category: {cat}` — OCC packs only use `concept`",
                "path": rel, "fixed": False,
            })

        conf = fm.get("confidence")
        if conf and conf not in ("high", "medium", "low"):
            issues.append({
                "code": "2", "severity": "warning",
                "message": f"Frontmatter `confidence: {conf}` — must be high|medium|low",
                "path": rel, "fixed": False,
            })

    for r in raws:
        fm = r["frontmatter"]
        if fm is None:
            issues.append({
                "code": "2", "severity": "critical",
                "message": "Raw source has no valid YAML frontmatter",
                "path": r["rel_path"], "fixed": False,
            })
            continue
        for field in _RAW_REQUIRED_CRITICAL:
            v = fm.get(field)
            if v is None or (isinstance(v, str) and not v.strip()):
                issues.append({
                    "code": "2", "severity": "critical",
                    "message": f"Raw frontmatter `{field}` missing or empty",
                    "path": r["rel_path"], "fixed": False,
                })
        for field in _RAW_REQUIRED_WARNING:
            if fm.get(field) is None:
                issues.append({
                    "code": "2", "severity": "warning",
                    "message": f"Raw frontmatter `{field}` missing",
                    "path": r["rel_path"], "fixed": False,
                })
        rtype = fm.get("type")
        if rtype and rtype != "articles":
            issues.append({
                "code": "2", "severity": "warning",
                "message": f"Raw frontmatter `type: {rtype}` — OCC packs only use `articles`",
                "path": r["rel_path"], "fixed": False,
            })


# ── C3: Index Consistency ─────────────────────────────────────────────────────

def _check_c3_index(wiki_dir: Path, pack_dir: Path, pages: list[dict],
                    raws: list[dict], issues: list[dict], fix: bool):
    index_path = wiki_dir / "index.md"
    if index_path.exists():
        rows = _parse_index_rows(index_path.read_text(encoding="utf-8"))
        page_filenames = {p["path"].name for p in pages}
        index_filenames = {Path(r).name for r in rows}
        missing = page_filenames - index_filenames  # pages not in index
        dead = index_filenames - page_filenames     # rows pointing nowhere
        if missing or dead:
            fixed = False
            if fix:
                try:
                    import forge._wiki as wiki
                    fresh_pages = [{
                        "slug":    p["frontmatter"].get("slug", p["path"].stem) if p["frontmatter"] else p["path"].stem,
                        "title":   p["frontmatter"].get("title", p["path"].stem) if p["frontmatter"] else p["path"].stem,
                        "summary": p["frontmatter"].get("summary", "") if p["frontmatter"] else "",
                    } for p in pages]
                    wiki.update_index(wiki_dir, fresh_pages)
                    fixed = True
                except Exception:
                    fixed = False
            if missing:
                issues.append({
                    "code": "3", "severity": "warning",
                    "message": f"`wiki/index.md` missing {len(missing)} page(s): {', '.join(sorted(missing)[:5])}{'...' if len(missing) > 5 else ''}",
                    "path": "wiki/index.md", "fixed": fixed,
                })
            if dead:
                issues.append({
                    "code": "3", "severity": "warning",
                    "message": f"`wiki/index.md` has {len(dead)} dead row(s): {', '.join(sorted(dead)[:5])}{'...' if len(dead) > 5 else ''}",
                    "path": "wiki/index.md", "fixed": fixed,
                })

    concepts_idx = wiki_dir / "concepts" / "_index.md"
    if concepts_idx.exists():
        rows = _parse_index_rows(concepts_idx.read_text(encoding="utf-8"))
        page_filenames = {p["path"].name for p in pages}
        index_filenames = {Path(r).name for r in rows}
        diff = (page_filenames ^ index_filenames)
        if diff:
            fixed = False
            if fix:
                try:
                    import forge._wiki as wiki
                    fresh = [{
                        "slug":    p["frontmatter"].get("slug", p["path"].stem) if p["frontmatter"] else p["path"].stem,
                        "title":   p["frontmatter"].get("title", p["path"].stem) if p["frontmatter"] else p["path"].stem,
                        "summary": p["frontmatter"].get("summary", "") if p["frontmatter"] else "",
                    } for p in pages]
                    wiki._update_concepts_index(wiki_dir, fresh)
                    fixed = True
                except Exception:
                    fixed = False
            issues.append({
                "code": "3", "severity": "warning",
                "message": f"`wiki/concepts/_index.md` out of sync with files ({len(diff)} mismatch)",
                "path": "wiki/concepts/_index.md", "fixed": fixed,
            })

    raw_articles_idx = pack_dir / "raw" / "articles" / "_index.md"
    if raw_articles_idx.exists() and raws:
        rows = _parse_index_rows(raw_articles_idx.read_text(encoding="utf-8"))
        raw_filenames = {r["path"].name for r in raws}
        index_filenames = {Path(r).name for r in rows}
        diff = (raw_filenames ^ index_filenames)
        if diff:
            fixed = False
            if fix:
                try:
                    import forge._wiki as wiki
                    wiki._update_raw_index(pack_dir)
                    fixed = True
                except Exception:
                    fixed = False
            issues.append({
                "code": "3", "severity": "warning",
                "message": f"`raw/articles/_index.md` out of sync with files ({len(diff)} mismatch)",
                "path": "raw/articles/_index.md", "fixed": fixed,
            })


# ── C4: Link Integrity ────────────────────────────────────────────────────────

_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_WIKILINK = re.compile(r"\[\[([a-z0-9\-]+)(?:\|[^\]]+)?\]\]")
_SECTION_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _check_c4_links(wiki_dir: Path, pages: list[dict], issues: list[dict], fix: bool):
    page_slugs = set()
    page_filenames = set()
    for p in pages:
        page_filenames.add(p["path"].name)
        if p["frontmatter"]:
            slug = p["frontmatter"].get("slug")
            if slug:
                page_slugs.add(slug)

    # See Also bidirectionality map: backlinks[target_slug] = set(source_slugs)
    backlinks: dict[str, set[str]] = {}
    forward: dict[str, set[str]] = {}

    for p in pages:
        text = p["text"]
        rel = p["rel_path"]
        page_dir = p["path"].parent

        # Markdown link resolution (skip http(s) and mailto)
        for label, target in _MD_LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = (page_dir / target).resolve()
            if not target_path.exists():
                issues.append({
                    "code": "4", "severity": "warning",
                    "message": f"Broken link `[{label}]({target})`",
                    "path": rel, "fixed": False,
                })

        # See Also bidirectionality (extract section)
        see_also = _extract_section(text, "See Also")
        if see_also:
            this_slug = (p["frontmatter"] or {}).get("slug", p["path"].stem)
            forward.setdefault(this_slug, set())
            for tslug in _WIKILINK.findall(see_also):
                forward[this_slug].add(tslug)
                backlinks.setdefault(tslug, set()).add(this_slug)

    # Now check: every forward edge (A → B) needs a back edge (B → A)
    for src, targets in forward.items():
        for tgt in targets:
            if tgt not in page_slugs:
                # Target slug doesn't exist as a page — separate issue
                issues.append({
                    "code": "4", "severity": "warning",
                    "message": f"`See Also` link to non-existent page `{tgt}`",
                    "path": f"wiki/concepts/{src}.md", "fixed": False,
                })
                continue
            back = forward.get(tgt, set())
            if src not in back:
                fixed = False
                if fix:
                    fixed = _autofix_add_backlink(wiki_dir, tgt, src, pages)
                issues.append({
                    "code": "4", "severity": "warning",
                    "message": f"`See Also` link `{src} → {tgt}` is not bidirectional (missing back-link in `{tgt}.md`)",
                    "path": f"wiki/concepts/{tgt}.md", "fixed": fixed,
                })


# ── C4b: Source Provenance ────────────────────────────────────────────────────

def _check_c4b_source_provenance(pack_dir: Path, pages: list[dict], raws: list[dict],
                                 issues: list[dict], fix: bool):
    raw_files_relative = {r["rel_path"] for r in raws}
    used_raws: set[str] = set()

    for p in pages:
        if not p["frontmatter"]:
            continue
        rel = p["rel_path"]
        sources = p["frontmatter"].get("sources") or []
        if not isinstance(sources, list):
            issues.append({
                "code": "4b", "severity": "warning",
                "message": f"Frontmatter `sources` is not a list",
                "path": rel, "fixed": False,
            })
            continue
        for s in sources:
            s_str = str(s).strip()
            # Source can be a path like "raw/articles/file.md" — check existence
            candidate = pack_dir / s_str
            if candidate.exists():
                # Track usage by relative path
                try:
                    used_raws.add(str(candidate.resolve().relative_to(pack_dir.resolve())).replace("\\", "/"))
                except ValueError:
                    used_raws.add(s_str)
            else:
                # Could be just a name (legacy) — see if matches any raw by stem
                stems = {Path(r["rel_path"]).stem.lower() for r in raws}
                if s_str.lower() not in stems:
                    issues.append({
                        "code": "4b", "severity": "warning",
                        "message": f"Frontmatter `sources` entry does not resolve: `{s_str}`",
                        "path": rel, "fixed": False,
                    })

    # Orphan raw sources: present on disk but cited by no page
    for r in raws:
        if r["rel_path"].replace("\\", "/") not in used_raws:
            issues.append({
                "code": "4b", "severity": "suggestion",
                "message": f"Raw source not cited by any wiki page (orphan)",
                "path": r["rel_path"], "fixed": False,
            })


# ── C5: Tag Hygiene ───────────────────────────────────────────────────────────

# Common acronym → canonical expansion table (extend as needed).
# When both acronym and expansion appear in the wiki, canonical = expansion.
_TAG_ACRONYMS = {
    "ml":     "machine-learning",
    "ai":     "artificial-intelligence",
    "nlp":    "natural-language-processing",
    "cv":     "computer-vision",
    "rl":     "reinforcement-learning",
    "dl":     "deep-learning",
    "llm":    "large-language-model",
    "rdbms":  "relational-database",
    "iot":    "internet-of-things",
    "ux":     "user-experience",
    "ui":     "user-interface",
    "k8s":    "kubernetes",
}


def _check_c5_tag_hygiene(pages: list[dict], issues: list[dict], fix: bool):
    """Find near-duplicate tags across the wiki and propose/apply canonical form."""
    # Collect every tag with its source pages
    tag_to_pages: dict[str, list[dict]] = {}
    for p in pages:
        if not p["frontmatter"]:
            continue
        tags = p["frontmatter"].get("tags") or []
        if not isinstance(tags, list):
            continue
        for t in tags:
            t_norm = str(t).strip().lower()
            if not t_norm:
                continue
            tag_to_pages.setdefault(t_norm, []).append(p)

    if not tag_to_pages:
        return

    all_tags = list(tag_to_pages.keys())

    # Build canonical mapping: each non-canonical → canonical form
    canonical_map: dict[str, str] = {}

    # Pass 1: known acronyms → expansion (only if expansion exists in wiki)
    for short, long_form in _TAG_ACRONYMS.items():
        if short in tag_to_pages and long_form in tag_to_pages:
            canonical_map[short] = long_form

    # Pass 2: pairwise similarity within remaining tags
    seen_pairs: set[tuple[str, str]] = set()
    for i, a in enumerate(all_tags):
        if a in canonical_map:
            continue
        for b in all_tags[i + 1:]:
            if b in canonical_map:
                continue
            pair = tuple(sorted((a, b)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if not _are_near_duplicates(a, b):
                continue
            canonical, other = _pick_canonical_tag(a, b)
            canonical_map[other] = canonical

    if not canonical_map:
        return

    # Group by canonical for compact reporting
    by_canonical: dict[str, list[str]] = {}
    for old, new in canonical_map.items():
        by_canonical.setdefault(new, []).append(old)

    affected_pages = set()
    for old in canonical_map:
        for p in tag_to_pages.get(old, []):
            affected_pages.add(id(p))

    fixed = False
    if fix:
        for p in pages:
            if id(p) not in affected_pages or not p["frontmatter"]:
                continue
            tags = p["frontmatter"].get("tags") or []
            if not isinstance(tags, list):
                continue
            new_tags = []
            seen = set()
            for t in tags:
                t_norm = str(t).strip().lower()
                replaced = canonical_map.get(t_norm, t_norm)
                if replaced not in seen:
                    seen.add(replaced)
                    new_tags.append(replaced)
            new_fm = dict(p["frontmatter"])
            new_fm["tags"] = new_tags
            _rewrite_frontmatter(p, new_fm)
        fixed = True

    for canonical, olds in sorted(by_canonical.items()):
        olds_str = ", ".join(f"`{o}`" for o in sorted(olds))
        n = sum(len(tag_to_pages.get(o, [])) for o in olds)
        issues.append({
            "code": "5", "severity": "warning",
            "message": f"Near-duplicate tags {olds_str} → canonical `{canonical}` ({n} page{'s' if n != 1 else ''} affected)",
            "path": "", "fixed": fixed,
        })


def _pick_canonical_tag(a: str, b: str) -> tuple[str, str]:
    """
    Decide which of two near-duplicate tags wins.
    Returns (canonical, other). Karpathy convention: lowercase, hyphenated, no spaces.
      1. Hyphen/underscore variants → prefer hyphenated
      2. Space-separated → prefer hyphen-separated equivalent
      3. Otherwise → prefer the longer (more specific)
      4. Tie → prefer the alphabetically smaller (deterministic)
    """
    def _normform_score(t: str) -> int:
        # Higher = more canonical
        score = 0
        if "-" in t and "_" not in t and " " not in t:
            score += 2
        if " " not in t:
            score += 1
        return score
    sa, sb = _normform_score(a), _normform_score(b)
    if sa != sb:
        return (a, b) if sa > sb else (b, a)
    if len(a) != len(b):
        return (a, b) if len(a) > len(b) else (b, a)
    return (a, b) if a < b else (b, a)


def _are_near_duplicates(a: str, b: str) -> bool:
    """
    Heuristic: two tags are near-duplicates if any of:
      - one is the singular/plural of the other (model/models)
      - one differs from the other by 1 char (typo)
      - one differs only by hyphen/underscore/space separator (machine-learning/machine_learning/machine learning)
      - one is a prefix of the other (transformer/transformer-architecture)
        BUT only when the shorter is ≥ 4 chars (avoid false positives like ml/multilang)
    Note: acronym handling is done separately by the explicit table.
    """
    if a == b:
        return False
    a_norm = a.replace("_", "-").replace(" ", "-")
    b_norm = b.replace("_", "-").replace(" ", "-")
    if a_norm == b_norm:
        return True
    # Plural / singular
    if a + "s" == b or b + "s" == a or a + "es" == b or b + "es" == a:
        return True
    # 1-char Levenshtein for tags ≥4 chars (typo detection)
    if min(len(a), len(b)) >= 4 and _levenshtein_at_most_one(a, b):
        return True
    # Prefix containment, conservative
    if len(a) >= 4 and len(b) >= 4:
        if a.startswith(b + "-") or b.startswith(a + "-"):
            return True
    return False


def _levenshtein_at_most_one(a: str, b: str) -> bool:
    """True iff Levenshtein(a, b) ≤ 1. Faster than a full DP for the threshold."""
    if abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return True
    # If lengths equal: check single-char substitution
    if len(a) == len(b):
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs == 1
    # Lengths differ by 1: check single-char insertion
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    found_diff = False
    while i < len(short) and j < len(long_):
        if short[i] != long_[j]:
            if found_diff:
                return False
            found_diff = True
            j += 1
        else:
            i += 1
            j += 1
    return True


# ── C11: Canonical Placement ──────────────────────────────────────────────────

def _check_c11_placement(pages: list[dict], raws: list[dict], issues: list[dict], fix: bool):
    for p in pages:
        if not p["frontmatter"]:
            continue
        cat = p["frontmatter"].get("category")
        if cat and cat != "concept":
            issues.append({
                "code": "11", "severity": "critical",
                "message": f"File in `wiki/concepts/` has `category: {cat}` (expected `concept`)",
                "path": p["rel_path"], "fixed": False,
            })

    for r in raws:
        if not r["frontmatter"]:
            continue
        rtype = r["frontmatter"].get("type")
        if rtype and rtype != "articles":
            issues.append({
                "code": "11", "severity": "critical",
                "message": f"File in `raw/articles/` has `type: {rtype}` (expected `articles`)",
                "path": r["rel_path"], "fixed": False,
            })


# ── M1, M2: Manifest ──────────────────────────────────────────────────────────

def _check_m1_manifest_exists(pack_dir: Path, issues: list[dict], fix: bool):
    mf_path = pack_dir / "manifest.yaml"
    if not mf_path.exists():
        issues.append({
            "code": "M1", "severity": "critical",
            "message": "Missing `manifest.yaml` at the pack's root directory. This file is required for the broker to register the pack.",
            "path": "manifest.yaml", "fixed": False,
        })
        return
    try:
        data = yaml.safe_load(mf_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a YAML mapping")
    except Exception as ex:
        issues.append({
            "code": "M1", "severity": "critical",
            "message": f"`manifest.yaml` is not valid YAML: {ex}",
            "path": "manifest.yaml", "fixed": False,
        })


def _check_m2_manifest_summary(pack_dir: Path, issues: list[dict], fix: bool):
    mf_path = pack_dir / "manifest.yaml"
    if not mf_path.exists():
        return  # already flagged by M1
    try:
        data = yaml.safe_load(mf_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return  # already flagged by M1
    summary = data.get("summary", "")
    if not isinstance(summary, str) or not summary.strip():
        issues.append({
            "code": "M2", "severity": "warning",
            "message": "Pack-level summary is missing from `manifest.yaml`. The broker uses it to disambiguate packs during search; without it, search quality is reduced. Enable auto-fix to regenerate.",
            "path": "manifest.yaml", "fixed": False,
        })
        return
    n = len(summary)
    if n < 50:
        issues.append({
            "code": "M2", "severity": "warning",
            "message": f"Pack-level summary is suspiciously short ({n} chars; expected ~200-500). Consider regenerating it with auto-fix.",
            "path": "manifest.yaml", "fixed": False,
        })
    elif n > 2000:
        issues.append({
            "code": "M2", "severity": "warning",
            "message": f"Pack-level summary is suspiciously long ({n} chars; expected ~200-500).",
            "path": "manifest.yaml", "fixed": False,
        })


# ── S1-S5: Safety pre-screen (regex) ──────────────────────────────────────────
#
# These are CONSERVATIVE pre-screens. Flagging is informational — the LLM
# audit phase (in _llm.py:lint_wiki) decides whether flagged content is
# legitimate in the pack's topic (e.g. a security pack discussing rm -rf
# pedagogically) or actually malicious. A flag here is never a verdict.

_S1_PATTERNS = [
    # Direct jailbreak instructions
    re.compile(r"ignore\s+(?:all\s+|the\s+)?previous\s+(?:instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+|the\s+)?(?:above|prior|previous)", re.IGNORECASE),
    re.compile(r"forget\s+(?:everything|all\s+previous|all\s+instructions)", re.IGNORECASE),
    # ChatML / instruction-tuned model markers leaked into content
    re.compile(r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>"),
    re.compile(r"\[INST\]|\[/INST\]"),
    # Role-override attempts
    re.compile(r"you\s+are\s+now\s+(?:a|an|the)\s+(?:DAN|jailbroken|unrestricted)", re.IGNORECASE),
    re.compile(r"system\s*[:>]\s*you\s+(?:are|will|must)", re.IGNORECASE),
]


def _check_s1_prompt_injection(pages: list[dict], issues: list[dict], fix: bool):
    for p in pages:
        body = p.get("body", "") or ""
        for pat in _S1_PATTERNS:
            m = pat.search(body)
            if m:
                snippet = body[max(0, m.start()-30):m.end()+30].replace("\n", " ")
                issues.append({
                    "code": "S1", "severity": "warning",
                    "message": f"Possible prompt-injection pattern: `…{snippet}…`",
                    "path": p["rel_path"], "fixed": False,
                })
                break  # one flag per page is enough


_S2_PATTERNS = [
    re.compile(r"\brm\s+-rf\s+/(?:\s|$|[^a-zA-Z0-9._/-])"),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),  # fork bomb
    re.compile(r"\bdd\s+if=.*\s+of=/dev/(?:sd|hd|nvme|disk)"),
    re.compile(r"\bmkfs\.(?:ext[234]|btrfs|xfs|vfat|ntfs)\b"),
    re.compile(r"\b(?:curl|wget)\b[^\n|]{0,80}\|\s*(?:bash|sh|zsh|fish)\b"),
    re.compile(r"\bchmod\s+-R\s+777\s+/"),
]


def _check_s2_destructive_shell(pages: list[dict], issues: list[dict], fix: bool):
    for p in pages:
        body = p.get("body", "") or ""
        for pat in _S2_PATTERNS:
            m = pat.search(body)
            if m:
                snippet = body[max(0, m.start()-20):m.end()+20].replace("\n", " ")
                issues.append({
                    "code": "S2", "severity": "warning",
                    "message": f"Destructive shell pattern found (may be pedagogical — LLM will judge): `{snippet}`",
                    "path": p["rel_path"], "fixed": False,
                })
                break


_S3_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "rebrand.ly", "shorturl.at", "rb.gy",
}
_S3_RISKY_TLD = re.compile(r"https?://[^\s/]+\.(?:tk|ml|ga|cf|gq)(?:[/?#]|$)", re.IGNORECASE)
_S3_PUNYCODE = re.compile(r"https?://[^\s/]*xn--[^\s/]*", re.IGNORECASE)
_S3_URL_RE = re.compile(r"https?://([^\s/?#]+)", re.IGNORECASE)


def _check_s3_suspicious_urls(pages: list[dict], issues: list[dict], fix: bool):
    for p in pages:
        body = p.get("body", "") or ""
        for host in _S3_URL_RE.findall(body):
            host_l = host.lower()
            if host_l in _S3_SHORTENERS:
                issues.append({
                    "code": "S3", "severity": "warning",
                    "message": f"URL shortener obscures target: `{host}`",
                    "path": p["rel_path"], "fixed": False,
                })
        if _S3_RISKY_TLD.search(body):
            issues.append({
                "code": "S3", "severity": "warning",
                "message": "URL uses a free TLD frequently abused for phishing (.tk/.ml/.ga/.cf/.gq)",
                "path": p["rel_path"], "fixed": False,
            })
        if _S3_PUNYCODE.search(body):
            issues.append({
                "code": "S3", "severity": "warning",
                "message": "URL contains punycode (xn--…) — possible homoglyph attack on legitimate domain",
                "path": p["rel_path"], "fixed": False,
            })


# Zero-width and bidi-override characters used to hide payloads inside text
_S5_FORBIDDEN_CHARS = "​‌‍‎‏‪‫‬‭‮⁦⁧⁨⁩᠎﻿"
_S5_RE = re.compile(f"[{_S5_FORBIDDEN_CHARS}]")


def _check_s5_control_chars(pages: list[dict], issues: list[dict], fix: bool):
    for p in pages:
        body = p.get("body", "") or ""
        m = _S5_RE.search(body)
        if not m:
            continue
        fixed = False
        if fix:
            try:
                cleaned = _S5_RE.sub("", p["text"])
                p["path"].write_text(cleaned, encoding="utf-8")
                fixed = True
            except Exception:
                fixed = False
        issues.append({
            "code": "S5", "severity": "warning",
            "message": "Page contains invisible/bidi-override Unicode (zero-width or RTL control chars)",
            "path": p["rel_path"], "fixed": fixed,
        })


# ── Q1, Q2, Q4: Quality pre-screen (mechanical) ───────────────────────────────

_Q1_MIN_BODY_CHARS = 200


def _check_q1_page_length(pages: list[dict], issues: list[dict], fix: bool):
    for p in pages:
        body = p.get("body", "") or ""
        # strip headers/blank lines for a fairer minimum
        meat = "\n".join(
            l for l in body.splitlines()
            if l.strip() and not l.lstrip().startswith("#")
        )
        if len(meat) < _Q1_MIN_BODY_CHARS:
            issues.append({
                "code": "Q1", "severity": "warning",
                "message": f"Page body is very short ({len(meat)} chars of substantive text)",
                "path": p["rel_path"], "fixed": False,
            })


_Q2_PLACEHOLDERS = [
    re.compile(r"\b(?:TODO|FIXME|XXX|TBD|TKTK)\b"),
    re.compile(r"\[(?:TODO|FIXME|FILL[\s_-]?ME|PLACEHOLDER|INSERT[^\]]*)\]", re.IGNORECASE),
    re.compile(r"lorem\s+ipsum", re.IGNORECASE),
    re.compile(r"_To be linked after compilation\._"),  # leftover cross-link placeholder
]


def _check_q2_placeholders(pages: list[dict], issues: list[dict], fix: bool):
    for p in pages:
        body = p.get("body", "") or ""
        for pat in _Q2_PLACEHOLDERS:
            m = pat.search(body)
            if m:
                issues.append({
                    "code": "Q2", "severity": "warning",
                    "message": f"Unresolved placeholder: `{m.group(0)}`",
                    "path": p["rel_path"], "fixed": False,
                })
                break


# Patterns that indicate the LLM copied the prompt template verbatim into
# user-visible frontmatter fields. Symptom of a prompt-engineering bug;
# discovered 2026-05-14 after a real run produced 100/162 pages with the
# placeholder string surviving as `summary` or `tags`.
_Q3_LEAKAGE_PATTERNS = [
    re.compile(r"REPLACE\s+WITH", re.IGNORECASE),
    re.compile(r"<<\s*WRITE", re.IGNORECASE),
    re.compile(r"<<\s*TAG\d*\s*>>", re.IGNORECASE),
    re.compile(r"<<\s*SUMMARY", re.IGNORECASE),
    re.compile(r"<<\s*TITLE", re.IGNORECASE),
    re.compile(r"must\s+be\s+a\s+single\s+quoted\s+string", re.IGNORECASE),
    re.compile(r"3-?5\s+relevant\s+lowercase\s+keywords?", re.IGNORECASE),
    re.compile(r"^\s*replace\s+with", re.IGNORECASE),
    re.compile(r"never\s+a\s+yaml\s+list", re.IGNORECASE),
]

# Stale `### See Also` (three hashes) sub-subsection containing the cross-link
# placeholder. The proper section is `## See Also` (two hashes); the cross-link
# pass only fills the two-hash variant, leaving the three-hash stray with its
# placeholder intact.
_Q3_STALE_SEE_ALSO_RE = re.compile(
    r"^###\s+See\s+Also\s*$.*?_To be linked after compilation\._",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def _check_q3_template_leakage(pages: list[dict], issues: list[dict], fix: bool):
    """Detect prompt-template text leaking into user-visible frontmatter.

    These cases survive C2 (frontmatter present) and Q2 (placeholder in body)
    because they are syntactically valid YAML strings that just happen to be
    the LLM's verbatim copy of the prompt template. Severity is critical:
    they degrade retrieval quality severely (the broker indexes summaries).
    Not auto-fixable from inside the lint — see `repair_placeholders.py`
    or re-run the page with the post-2026-05-14 prompts.
    """
    for p in pages:
        fm = p.get("frontmatter")
        if not isinstance(fm, dict):
            continue
        rel = p["rel_path"]

        for field in ("summary", "title"):
            v = fm.get(field)
            if v is None:
                continue
            s = str(v)
            for pat in _Q3_LEAKAGE_PATTERNS:
                if pat.search(s):
                    issues.append({
                        "code": "Q3", "severity": "critical",
                        "message": f"Frontmatter `{field}` contains prompt-template text "
                                   f"(LLM did not replace the placeholder): {s[:80]!r}",
                        "path": rel, "fixed": False,
                    })
                    break

        tags = fm.get("tags") or []
        if isinstance(tags, list):
            for t in tags:
                ts = str(t).strip()
                leaked = False
                for pat in _Q3_LEAKAGE_PATTERNS:
                    if pat.search(ts):
                        leaked = True
                        break
                if not leaked and " " in ts and len(ts.split()) > 4:
                    leaked = True
                if leaked:
                    issues.append({
                        "code": "Q3", "severity": "critical",
                        "message": f"Frontmatter `tags` contains a placeholder/instructional "
                                   f"string instead of a keyword: {ts!r}",
                        "path": rel, "fixed": False,
                    })
                    break

        body = p.get("body", "") or ""
        if _Q3_STALE_SEE_ALSO_RE.search(body):
            issues.append({
                "code": "Q3", "severity": "warning",
                "message": "Body contains a stray `### See Also` (three hashes) section "
                           "with the cross-link placeholder. The cross-link pass only fills "
                           "`## See Also` (two hashes); this stray subsection must be removed "
                           "or merged.",
                "path": rel, "fixed": False,
            })


def _check_q4_index_summary_drift(wiki_dir: Path, pages: list[dict], issues: list[dict], fix: bool):
    index_path = wiki_dir / "index.md"
    if not index_path.exists():
        return  # flagged by C1
    rows = _parse_index_rows_with_summary(index_path.read_text(encoding="utf-8"))
    # Map: filename → summary in index
    idx_summary = {Path(f).name: s for f, _, s in rows}
    drift_count = 0
    for p in pages:
        if not p["frontmatter"]:
            continue
        page_summary = (p["frontmatter"].get("summary") or "").strip()
        idx_s = idx_summary.get(p["path"].name, "").strip()
        if not page_summary or not idx_s:
            continue  # one is empty → C2/C3 covers it
        # Drift detection: index summary differs substantially from frontmatter
        if page_summary[:120] != idx_s[:120]:
            drift_count += 1
    if drift_count > 0:
        fixed = False
        if fix and drift_count > 0:
            try:
                import forge._wiki as wiki_mod
                fresh = [{
                    "slug": p["frontmatter"].get("slug", p["path"].stem) if p["frontmatter"] else p["path"].stem,
                    "title": (p["frontmatter"].get("title", p["path"].stem) if p["frontmatter"] else p["path"].stem),
                    "summary": (p["frontmatter"].get("summary", "") if p["frontmatter"] else ""),
                } for p in pages]
                wiki_mod.update_index(wiki_dir, fresh)
                fixed = True
            except Exception:
                fixed = False
        issues.append({
            "code": "Q4", "severity": "warning",
            "message": f"`wiki/index.md` summaries are out of sync with the page frontmatter for {drift_count} page(s). The broker would index outdated descriptions; auto-fix will regenerate the index.",
            "path": "wiki/index.md", "fixed": fixed,
        })


def _parse_index_rows_with_summary(text: str) -> list[tuple[str, str, str]]:
    """Parse index.md table rows. Returns list of (file, title, summary)."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        if parts[0].lower() == "file" or parts[0].startswith("-"):
            continue
        out.append((parts[0], parts[1], parts[2]))
    return out


# ── Helpers ───────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def _scan_md_with_frontmatter(directory: Path, pack_dir: Path) -> list[dict]:
    """
    Return list of {path, rel_path, text, frontmatter (dict|None), body}.
    `rel_path` is relative to `pack_dir` (e.g. "raw/articles/foo.md" or
    "wiki/concepts/foo.md"), matching the convention used by frontmatter
    `sources:` entries so provenance checks compare equal strings.
    """
    out = []
    if not directory.exists():
        return out
    for f in sorted(directory.glob("*.md")):
        if f.name in ("_index.md", "index.md", "schema.md", "log.md"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        m = _FRONTMATTER_RE.match(text)
        if m:
            try:
                fm = yaml.safe_load(m.group(1)) or {}
                if not isinstance(fm, dict):
                    fm = None
            except Exception:
                fm = None
            body = m.group(2)
        else:
            fm = None
            body = text
        if isinstance(fm, dict):
            for k in ("title", "summary", "slug"):
                v = fm.get(k)
                if v is not None and not isinstance(v, str):
                    fm[k] = "; ".join(str(x).strip() for x in v if x is not None) if isinstance(v, list) else str(v)
        try:
            rel = str(f.resolve().relative_to(pack_dir.resolve())).replace("\\", "/")
        except ValueError:
            rel = f.name
        out.append({"path": f, "rel_path": rel, "text": text, "frontmatter": fm, "body": body})
    return out


def _parse_index_rows(text: str) -> list[str]:
    """Extract filenames from an index markdown table. Returns list of paths/names."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---") or line.startswith("|------"):
            continue
        # Skip header row (contains 'File' or similar uppercase)
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if first.lower() in ("file", "name", ""):
            continue
        # First cell may be "[name.md](name.md)" or "concepts/name.md"
        m = re.match(r"\[([^\]]+)\]\([^)]+\)", first)
        name = m.group(1) if m else first
        if name.endswith(".md"):
            rows.append(name)
    return rows


def _extract_section(text: str, header: str) -> str:
    """Extract the body of `## <header>` up to the next `## ` header or end of file."""
    pattern = re.compile(
        rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1) if m else ""


def _autofix_title_from_heading(page: dict) -> bool:
    """If frontmatter title is missing, infer from first `# heading` in body."""
    body = page.get("body", "")
    m = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    if not m:
        return False
    title = m.group(1).strip()
    fm = page["frontmatter"] or {}
    fm["title"] = title
    return _rewrite_frontmatter(page, fm)


def _autofix_summary_from_first_paragraph(page: dict) -> bool:
    """If frontmatter summary is missing, infer from first body paragraph (skip headers/blockquote)."""
    body = page.get("body", "")
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para or para.startswith("#") or para.startswith(">"):
            continue
        # Take up to ~280 chars, trim at sentence
        if len(para) > 280:
            para = para[:280].rsplit(". ", 1)[0] + "."
        fm = page["frontmatter"] or {}
        fm["summary"] = para
        return _rewrite_frontmatter(page, fm)
    return False


def _autofix_add_backlink(wiki_dir: Path, target_slug: str, source_slug: str, pages: list[dict]) -> bool:
    """Add a See Also bullet linking back to `source_slug` inside the page with `target_slug`."""
    target_page = next(
        (p for p in pages if p["frontmatter"] and p["frontmatter"].get("slug") == target_slug),
        None,
    )
    if not target_page:
        return False
    source_page = next(
        (p for p in pages if p["frontmatter"] and p["frontmatter"].get("slug") == source_slug),
        None,
    )
    source_title = (source_page["frontmatter"] or {}).get("title", source_slug) if source_page else source_slug
    bullet = (
        f"- [[{source_slug}|{source_title}]] "
        f"([{source_title}]({source_slug}.md)) — auto-added back-link"
    )

    text = target_page["text"]
    pattern = re.compile(r"^##\s+See Also\s*$(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    m = pattern.search(text)
    if not m:
        # No See Also section — insert one before Sources or Key Points
        new_section = f"## See Also\n\n{bullet}\n"
        for anchor in ("## Sources", "## Key Points"):
            if anchor in text:
                new_text = text.replace(anchor, f"{new_section}\n{anchor}", 1)
                break
        else:
            new_text = text.rstrip() + f"\n\n{new_section}"
    else:
        existing = m.group(1)
        if source_slug in existing:
            return True  # Already linked — counts as success
        new_text = pattern.sub(
            lambda mm: f"## See Also{mm.group(1).rstrip()}\n{bullet}\n\n",
            text, count=1,
        )

    target_page["path"].write_text(new_text, encoding="utf-8")
    target_page["text"] = new_text
    return True


def _rewrite_frontmatter(page: dict, new_fm: dict) -> bool:
    """Rewrite the frontmatter block of a page on disk, preserving the body."""
    body = page.get("body", "")
    new_fm_yaml = yaml.safe_dump(new_fm, sort_keys=False, allow_unicode=True).strip()
    new_text = f"---\n{new_fm_yaml}\n---\n\n{body.lstrip()}"
    page["path"].write_text(new_text, encoding="utf-8")
    page["text"] = new_text
    page["frontmatter"] = new_fm
    return True
