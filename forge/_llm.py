"""
OpenAI Responses API calls for OCC Forge.
IMPORTANT: Always use /v1/responses, never /v1/chat/completions.
See forge/OPENAI_RESPONSES_API_GUIDE.md for critical rules.
"""
import os
import json
import httpx

OPENAI_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_EXTRACT_MODEL = "gpt-5-mini"
DEFAULT_WRITE_MODEL = "gpt-5"
_TIMEOUT = None


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY environment variable not set.")
    return key


def _extract_text(data: dict) -> str:
    """Extract text from Responses API output[]. Loops to find type='message', never assumes output[0]."""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") in ("output_text", "text") and block.get("text"):
                    return block["text"]
    return data.get("output_text", "")


def _call(
    model: str,
    system: str,
    user: str,
    json_mode: bool = False,
    max_output_tokens: int = 4096,
) -> str:
    body: dict = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_output_tokens": max_output_tokens,
    }
    if json_mode:
        # CRITICAL: prompt must contain the word "json" when using json_object format.
        # Both system and user prompts above contain "JSON" — requirement satisfied.
        body["text"] = {"format": {"type": "json_object"}}

    key = _api_key()
    resp = httpx.post(
        OPENAI_API_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=_TIMEOUT,
    )
    if not resp.is_success:
        raise RuntimeError(f"OpenAI {resp.status_code}: {resp.text[:600]}")
    return _extract_text(resp.json())


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
        f"- Update the `source:` frontmatter field to list both sources.\n"
        f"- Keep the same slug and title. Update tags if needed.\n"
        f"- Output the complete updated page, starting with the frontmatter block.\n"
    )
    return _call(model, system, user, json_mode=False, max_output_tokens=32000)


def write_wiki_page(
    concept: dict,
    source_text: str,
    source_name: str,
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
        f"source: {source_name}\n"
        f"confidence: high\n"
        f"tags: [replace with 3-5 relevant lowercase keywords]\n"
        f"---\n\n"
        f"# {concept['title']}\n\n"
        f"Write a dense technical explanation. Include all relevant details from the source. "
        f"Use ## subheaders, bullet lists, and code blocks where relevant. "
        f"End with a '## Key Points' section containing 3-5 bullet takeaways."
    )
    return _call(model, system, user, json_mode=False, max_output_tokens=32000)
