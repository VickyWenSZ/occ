"""
OpenRouter Chat Completions API calls for OCC Forge.
Uses OPENROUTER_API_KEY — same key as Node (no separate OpenAI key needed).
Models: openai/gpt-5, openai/gpt-5-mini, anthropic/claude-sonnet-4-6, etc.
"""
import os
import json
import httpx
from datetime import date

OR_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_EXTRACT_MODEL = "openai/gpt-5-mini"
DEFAULT_WRITE_MODEL   = "openai/gpt-5"
_TIMEOUT = None


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set. Add your OpenRouter key in Settings.")
    return key


def _normalize_model(model: str) -> str:
    """Add openai/ prefix to bare GPT model names for OpenRouter compatibility."""
    if "/" not in model:
        return f"openai/{model}"
    return model


def _call(
    model: str,
    system: str,
    user: str,
    json_mode: bool = False,
    max_output_tokens: int = 4096,
) -> str:
    model = _normalize_model(model)
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": max_output_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    resp = httpx.post(
        OR_API_URL,
        headers={
            "Authorization":  f"Bearer {_api_key()}",
            "Content-Type":   "application/json",
            "HTTP-Referer":   "https://opencognitivecommons.org",
            "X-Title":        "OCC Forge",
        },
        json=body,
        timeout=_TIMEOUT,
    )
    if not resp.is_success:
        raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:600]}")
    return resp.json()["choices"][0]["message"]["content"]


def extract_concepts(source_text: str, model: str = DEFAULT_EXTRACT_MODEL) -> list[dict]:
    """
    Identify wiki concepts from a source document.
    Returns list of {slug, title, summary}.
    Uses gpt-5-mini (cheap, structured task).
    """
    system = (
        "You are a knowledge compiler. Analyze technical documents and identify distinct concepts "
        "that deserve their own wiki page. Output valid JSON only."
    )
    user = (
        f"Analyze this document and return a JSON object with a 'concepts' key.\n\n"
        f"Document:\n---\n{source_text}\n---\n\n"
        f"Each concept in the array must have:\n"
        f"  - slug: lowercase-hyphenated identifier (e.g. 'docker-volumes')\n"
        f"  - title: human-readable title\n"
        f"  - summary: one sentence describing the concept\n\n"
        f"Aim for 5-15 focused, non-overlapping concepts. Return valid JSON."
    )
    raw = _call(model, system, user, json_mode=True, max_output_tokens=32000)
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        for v in data.values():
            if isinstance(v, list):
                return v
    except Exception:
        pass
    return []


def update_wiki_page(
    concept: dict,
    existing_content: str,
    new_source_text: str,
    source_name: str,
    raw_path: str = "",
    model: str = DEFAULT_WRITE_MODEL,
) -> str:
    """
    Enrich an existing wiki page with knowledge from a new source.
    Merges, extends, and flags contradictions. Never loses existing content.
    """
    system = (
        "You are an expert knowledge compiler maintaining a living wiki. "
        "Your job is to enrich existing wiki pages with new information from additional sources. "
        "Never remove existing content. Add what is new, correct what is wrong, flag contradictions. "
        "Output the complete updated page in markdown."
    )
    user = (
        f"Enrich this existing wiki page with new information from an additional source.\n\n"
        f"EXISTING PAGE:\n---\n{existing_content}\n---\n\n"
        f"NEW SOURCE ('{source_name}'):\n---\n{new_source_text}\n---\n\n"
        f"Instructions:\n"
        f"- Keep all existing content. Add new facts, details, and sections from the new source.\n"
        f"- If the new source contradicts existing content, add a `> ⚠️ Conflict: ...` blockquote.\n"
        f"- Keep all existing content. Add new facts, details, and sections from the new source.\n"
        f"- Append `  - {raw_path or source_name}` to the `sources:` YAML list in frontmatter.\n"
        f"- Update the `updated:` frontmatter field to today: {date.today().isoformat()}.\n"
        f"- Update `summary:` if the new source meaningfully expands the concept.\n"
        f"- Keep the same slug, title, category, and created date. Update tags if needed.\n"
        f"- Output the complete updated page, starting with the frontmatter block.\n"
    )
    return _call(model, system, user, json_mode=False, max_output_tokens=32000)


def lint_wiki(
    pack_name: str,
    index_content: str,
    pages_content: str,
    model: str = DEFAULT_WRITE_MODEL,
) -> str:
    """
    Perform a quality review (lint) of an expert pack wiki.
    Returns a structured markdown report.
    """
    system = (
        "You are a knowledge quality reviewer for an LLM wiki. "
        "Analyze the provided wiki pages and produce a precise, actionable quality report. "
        "Be specific: quote exact claims when flagging issues. Output markdown."
    )
    user = (
        f"Wiki pack: {pack_name}\n\n"
        f"INDEX.MD:\n---\n{index_content}\n---\n\n"
        f"PAGES:\n---\n{pages_content}\n---\n\n"
        f"Produce a quality review report with these exact sections:\n\n"
        f"## Summary\n"
        f"Overall assessment in 1-2 sentences.\n\n"
        f"## Contradictions\n"
        f"Conflicting claims between pages. Quote the specific conflicting statements and name the pages.\n\n"
        f"## Orphaned Pages\n"
        f"Pages present in the concepts directory but not referenced in index.md.\n\n"
        f"## Missing Cross-References\n"
        f"Concepts that are related but not linked to each other.\n\n"
        f"## Coverage Gaps\n"
        f"Important concepts that appear in sources but have no dedicated page.\n\n"
        f"## Staleness Warnings\n"
        f"Claims that may be outdated (version numbers, deprecated features, date-sensitive info).\n\n"
        f"For any section with no issues, write exactly: _None found._"
    )
    return _call(model, system, user, json_mode=False, max_output_tokens=8192)


def write_wiki_page(
    concept: dict,
    source_text: str,
    source_name: str,
    raw_path: str = "",
    model: str = DEFAULT_WRITE_MODEL,
) -> str:
    """
    Write a full wiki page for a concept.
    Returns markdown string with YAML frontmatter.
    Uses gpt-5 (quality-critical — this is what OCC nodes answer from).
    """
    system = (
        "You are an expert knowledge compiler. Write dense, factual wiki pages "
        "optimized for LLM consumption. Be precise, complete, and technical. Use markdown."
    )
    user = (
        f"Write a comprehensive wiki page for the concept: \"{concept['title']}\"\n\n"
        f"Source document:\n---\n{source_text}\n---\n\n"
        f"Start the page with this exact frontmatter block, then write the content:\n\n"
        f"---\n"
        f"title: {concept['title']}\n"
        f"slug: {concept['slug']}\n"
        f"category: concept\n"
        f"sources:\n"
        f"  - {raw_path or source_name}\n"
        f"confidence: high\n"
        f"created: {date.today().isoformat()}\n"
        f"updated: {date.today().isoformat()}\n"
        f"summary: [replace with one sentence describing this concept]\n"
        f"tags: [replace with 3-5 relevant lowercase keywords]\n"
        f"---\n\n"
        f"# {concept['title']}\n\n"
        f"Write a dense technical explanation. Include all relevant details from the source. "
        f"Use ## subheaders, bullet lists, and code blocks where relevant. "
        f"End with a '## Key Points' section containing 3-5 bullet takeaways."
    )
    return _call(model, system, user, json_mode=False, max_output_tokens=32000)
