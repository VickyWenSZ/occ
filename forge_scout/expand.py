"""
LLM-driven helpers for Scout:

- `classify_domain(topic)`   → returns one of the registered domains.
- `expand_queries(topic)`    → list of sub-queries from different angles.
- `rank_results(topic, ...)` → relevance score (0..1) per candidate.

Each helper accepts a `model_spec`:

    {"provider": "openrouter", "model": "openai/gpt-5", "api_key": "..."}
    {"provider": "ollama",     "model": "qwen3.5:9b"}

Top-tier (OpenRouter) is recommended; local Ollama is free fallback. The
GUI always defaults to top-tier per the user's "recommended" requirement.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .types import SourceResult

OR_API_URL = "https://openrouter.ai/api/v1/chat/completions"

DOMAINS = ("history", "science", "tech", "literature", "philosophy",
           "medicine", "art", "law", "social_science", "other")

SCOPE_RULES: dict[str, str] = {
    "overview": (
        "Foundational overview suitable for a top-level or intermediate node in a "
        "knowledge tree. Cover: main schools/branches/sub-fields, key figures, central "
        "concepts, historical context, major works. AVOID: deep technical specialties, "
        "obscure scholarly debates, modern adjacent reinterpretations, namesakes from "
        "unrelated fields."
    ),
    "deep_dive": (
        "Specialised, focused material on this exact entity. Cover: detailed sub-topics, "
        "primary sources, scholarly debates around it, technical aspects. AVOID: "
        "introductory surveys, broad overviews that mostly cover other related entities."
    ),
    "critique": (
        "Debates, criticisms, controversies, modern reassessments specific to this topic. "
        "AVOID: hagiographic intro material, unrelated polemics."
    ),
    "comparison": (
        "Comparative material — this topic vs adjacent traditions, alternatives, or "
        "successors. AVOID: standalone treatments of either side without comparison."
    ),
    "practical": (
        "Practical / applied / how-to material — modern uses, exercises, real-world "
        "application of this topic. AVOID: pure historical / theoretical / philological "
        "scholarship."
    ),
    "custom": (
        "Follow the user's brief literally. Generate ONLY queries the brief explicitly "
        "requests or clearly implies. Do not extrapolate."
    ),
}


def _scope_block(scope: str) -> str:
    return SCOPE_RULES.get(scope, SCOPE_RULES["overview"])


def _brief_block(brief: str) -> str:
    brief = (brief or "").strip()
    if not brief:
        return ""
    return (
        "\nUSER BRIEF (binding — treat every constraint here as mandatory):\n"
        f"\"\"\"\n{brief}\n\"\"\"\n"
    )


def classify_domain(topic: str, model_spec: dict) -> str:
    """Cheap, single-token-ish classification. Defaults to 'other' on failure."""
    system = (
        "You classify research topics into ONE of these domains: "
        + ", ".join(DOMAINS)
        + ". Output the domain word only — no punctuation, no quotes, no explanation."
    )
    user = f"Topic: {topic}\nDomain:"
    raw = _chat(system, user, model_spec, max_tokens=600, json_mode=False)
    word = (raw or "").strip().lower().split()[0] if raw else "other"
    word = re.sub(r"[^a-z_]", "", word)
    return word if word in DOMAINS else "other"


def expand_queries(topic: str, model_spec: dict, n: int = 7,
                   domain: str | None = None,
                   scope: str = "overview",
                   brief: str = "") -> list[str]:
    """
    Generate `n` search queries strictly within the user's intent (scope + brief).

    Key constraints baked into the prompt:
    - No drift to adjacent fields ("philosophy of action" out of "Stoicism").
    - No namesake/homonym branching ("Quantum Zeno effect" out of "Stoicism").
    - Disambiguate words with multiple unrelated meanings.
    """
    dom_hint = f"\nDetected domain: {domain}." if domain else ""

    system = (
        "You design search queries to gather research material for a knowledge pack. "
        "The user has specified a TOPIC + an INTENT (scope and optionally a brief). "
        "Your queries must stay STRICTLY within that intent.\n\n"
        "Hard rules:\n"
        "1. Never drift to adjacent or namesake fields. If the topic is 'Stoicism' "
        "(the ancient school) do NOT generate queries about 'Zeno's paradox' "
        "(Zeno of Elea, a different person), the 'Quantum Zeno effect' (physics), "
        "or generic 'philosophy of action'. Stay on the topic itself.\n"
        "2. If a word in the topic has multiple unrelated meanings, ALWAYS qualify it "
        "in every query (e.g. 'Stoic philosophy Zeno of Citium' not bare 'Zeno').\n"
        "3. Respect the brief literally when present — it is binding.\n"
        "4. Use short, search-engine-friendly phrases (4-8 words each).\n"
        "5. Make queries genuinely complementary (different facets of the same scope), "
        "not paraphrases of each other.\n\n"
        "Output JSON only."
    )

    user = (
        f"TOPIC: {topic}{dom_hint}\n\n"
        f"SCOPE ({scope}):\n{_scope_block(scope)}\n"
        f"{_brief_block(brief)}\n"
        f"Generate exactly {n} distinct queries that collectively cover this scope "
        f"WITHOUT drifting outside it. Return JSON:\n"
        f'{{"queries": ["query 1", "query 2", ...]}}'
    )
    raw = _chat(system, user, model_spec, max_tokens=2000, json_mode=True)
    data = _parse_json(raw)
    queries = data.get("queries") if isinstance(data, dict) else None
    if not queries or not isinstance(queries, list):
        return [topic]
    return [str(q).strip() for q in queries if str(q).strip()][:n] or [topic]


def suggest_pack_params(topic: str,
                        scope: str,
                        language: str,
                        model_spec: dict) -> dict:
    """
    Given just a topic + scope chip + target language, propose a complete
    Scout configuration: a precise brief, the right source set, and the
    search depth knobs. Returns a dict the frontend applies to the form.

    The output schema:
        {
          "pack_name":        str (slug, 1-3 hyphenated words),
          "brief":            str (in `language`, with COVER and EXCLUDE),
          "sources":          [list of source ids to enable],
          "per_source_limit": int,
          "top_k":            int,
          "explanation":      str (short rationale, in `language`)
        }
    """
    scope_text = _scope_block(scope) if scope in SCOPE_RULES else _scope_block("overview")

    # Compact catalog the LLM uses to pick sources.
    catalog = (
        "- wikipedia      : multilingual encyclopedia. Default choice for any topic.\n"
        "- sep            : Stanford Encyclopedia of Philosophy. Gold standard for "
        "any philosophy / intellectual-history / ethics topic.\n"
        "- wikisource     : primary historical texts and source documents.\n"
        "- archive_org    : scanned books (HEAVY — only enable for historical / "
        "literature / philosophy where primary books matter).\n"
        "- openalex       : 250M+ academic papers (metadata + abstract only).\n"
        "- pubmed         : biomedical literature (NCBI E-utilities). Enable for "
        "medicine / biology / cognitive neuroscience.\n"
        "- arxiv          : preprints in physics / CS / math / quantitative bio.\n"
        "- crossref       : DOI metadata for journal articles + book chapters.\n"
        "- mathworld      : Wolfram MathWorld encyclopedia (MATH ONLY).\n"
        "- gutendex       : Project Gutenberg public-domain books (HEAVY — only for "
        "literature / classics).\n"
        "- github         : repo READMEs (TECH topics — programming, frameworks, libraries).\n"
        "- stackexchange  : StackOverflow Q&A (PRACTICAL CODE / how-to).\n"
        "- hackernews     : HN top stories + comments (modern tech discussion).\n"
    )

    system = (
        # ── Who you are and the system you're inside ─────────────────────────
        "You are a CONFIGURATOR for a knowledge-pack search agent called OCC "
        "Forge Scout. You're not writing for a human reader — you're producing "
        "machine-readable instructions that will be FED INTO OTHER LLM PROMPTS "
        "downstream. Specifically, your `brief` field will be injected verbatim "
        "into:\n"
        "  1. The query-expansion LLM (decides which search queries to fire).\n"
        "  2. The candidate-ranking LLM (scores each fetched source for relevance).\n"
        "  3. The concept-extraction LLM (reads each source and decides which "
        "     concepts deserve their own wiki page in the pack).\n\n"
        # ── What `brief` IS vs IS NOT ────────────────────────────────────────
        "Your `brief` is an IMPERATIVE INSTRUCTION SET, NOT a description, "
        "summary, or definition of the topic. The user is NOT the reader — "
        "another LLM is. Treat it like a prompt you're writing TO that downstream "
        "LLM, telling it what to keep and what to drop.\n\n"
        "WRONG (reads like a textbook entry — DO NOT do this):\n"
        "  'Cognitivism in psychology — provide a concise, foundational overview "
        "  of the mid-20th-century movement in psychology...'\n\n"
        "RIGHT (reads like an instruction set — DO this):\n"
        "  'COVER: the cognitive revolution in psychology (1950s-60s); key "
        "  figures (Neisser, Bruner, Miller, Chomsky, Simon, Newell); "
        "  computational theory of mind; information-processing models; symbolic "
        "  architectures (ACT-R, SOAR); critiques from connectionism and "
        "  embodied cognition. EXCLUDE: cognitivism in metaethics (Moore, "
        "  Parfit, moral realism debate — different field); CBT as clinical "
        "  practice; educational pedagogy applications; generic cognitive-"
        "  science overviews that do not specifically address the cognitivism "
        "  movement.'\n\n"
        # ── Required structure ───────────────────────────────────────────────
        "REQUIRED STRUCTURE for the brief:\n"
        "1. Open with the explicit phrase 'COVER:' followed by a list of what "
        "   the downstream LLM SHOULD include — entities, sub-topics, key "
        "   figures, mechanisms, time periods, sources to look for. The depth "
        "   of this list depends on the SCOPE (broader for overview, narrower "
        "   and deeper for deep_dive, etc.).\n"
        "2. Then the explicit phrase 'EXCLUDE:' followed by what the downstream "
        "   LLM MUST DROP — adjacent fields, namesakes, related-but-distinct "
        "   schools, tangential content. Be specific (name the thing to "
        "   exclude, not just 'unrelated material').\n"
        "3. If the topic has multiple plausible meanings (e.g. 'Cognitivism' "
        "   = psychology vs metaethics; 'Stoicism' = ancient school vs modern "
        "   self-help; 'Saturn' = planet vs Roman god; 'Zeno' = Stoic vs "
        "   Eleatic vs Quantum effect), PICK ONE reading based on the scope's "
        "   natural focus and EXCLUDE the others BY NAME.\n"
        "4. 3-6 sentences total. No preamble like 'This brief instructs...' — "
        "   just COVER and EXCLUDE.\n"
        "5. Write in the requested target language. The structural keywords "
        "   COVER and EXCLUDE can stay in English even when the rest is "
        "   translated — they're machine markers.\n\n"
        # ── The other fields (unchanged guidance) ────────────────────────────
        "Output JSON only. The other fields work as follows:\n"
        "Your `pack_name` is a slug used as the on-disk folder name for this pack.\n"
        "RULES: 1-3 words, lowercase ASCII letters and digits only, hyphens between "
        "words, no spaces, no underscores, no diacritics. Max 30 characters. "
        "Should evoke the topic + (optionally) the scope. Examples: "
        "'stoicism-overview', 'cognitivism-psychology', 'rust-async-deep-dive', "
        "'crispr-overview'.\n\n"
        "Your `sources` array should reflect the topic domain:\n"
        "- philosophy / ethics / history of ideas → wikipedia, sep, wikisource, "
        "openalex, crossref. Add archive_org if classical / pre-1923. Skip github / "
        "stackexchange / mathworld / pubmed.\n"
        "- programming / software → wikipedia, github, stackexchange, hackernews, "
        "arxiv (for CS topics), openalex. Skip sep / pubmed / mathworld / "
        "wikisource / gutendex.\n"
        "- medicine / biology → wikipedia, pubmed, openalex, crossref. Skip sep / "
        "github / mathworld.\n"
        "- math → wikipedia, mathworld, arxiv, openalex, crossref. Skip pubmed / "
        "github (unless about computational topics).\n"
        "- history / classics / literature → wikipedia, wikisource, archive_org, "
        "gutendex, sep (when philosophical), openalex.\n"
        "- science (physics/chemistry/etc) → wikipedia, arxiv, openalex, crossref. "
        "Skip sep / github / pubmed / mathworld unless directly relevant.\n\n"
        "Your `per_source_limit` and `top_k`:\n"
        "- overview: per_source_limit=4, top_k=20 (focused)\n"
        "- deep_dive: per_source_limit=8, top_k=50 (broad and thorough)\n"
        "- critique: per_source_limit=6, top_k=30\n"
        "- comparison: per_source_limit=6, top_k=40\n"
        "- practical: per_source_limit=6, top_k=30\n"
        "- custom: per_source_limit=6, top_k=40\n\n"
        "Output JSON only."
    )
    user = (
        f"TOPIC: {topic}\n"
        f"SCOPE: {scope}\n"
        f"(The scope description below tells you what KIND of material to include "
        f"in the COVER list — NOT how the brief itself should read.)\n"
        f"{scope_text}\n"
        f"BRIEF LANGUAGE (write the brief and explanation in this language): {language}\n\n"
        f"AVAILABLE SOURCES:\n{catalog}\n"
        f"Reminder: the `brief` is INSTRUCTIONS for downstream LLMs that will filter "
        f"concepts, NOT a description of the topic. Use imperative COVER: and "
        f"EXCLUDE: sections, not prose. The reader is a machine, not a human.\n\n"
        f'Return JSON:\n'
        f'{{"pack_name": "<slug, 1-3 hyphenated words, lowercase ASCII>", '
        f'"brief": "<3-6 sentences in {language}, MUST start with COVER: and contain EXCLUDE:>", '
        f'"sources": ["wikipedia", ...], '
        f'"per_source_limit": <int 4-10>, '
        f'"top_k": <int 20-60>, '
        f'"explanation": "<1-2 sentences in {language}, rationale for the picks>"}}'
    )

    raw = _chat(system, user, model_spec, max_tokens=2000, json_mode=True)
    data = _parse_json(raw)
    if not isinstance(data, dict):
        return {}

    # Validate, clean, and bound the numerics so the form can't be corrupted.
    valid_sources = {
        "wikipedia", "sep", "wikisource", "archive_org", "openalex", "pubmed",
        "arxiv", "crossref", "mathworld", "gutendex", "github", "stackexchange",
        "hackernews",
    }
    raw_sources = data.get("sources") or []
    sources = [s for s in raw_sources if isinstance(s, str) and s in valid_sources]

    try:
        psl = int(data.get("per_source_limit") or 6)
    except Exception:
        psl = 6
    try:
        topk = int(data.get("top_k") or 40)
    except Exception:
        topk = 40

    # Slugify the LLM's pack_name proposal aggressively — never trust it raw.
    raw_pack_name = str(data.get("pack_name") or "").strip().lower()
    pack_name = re.sub(r"[^a-z0-9-]+", "-", raw_pack_name)
    pack_name = re.sub(r"-+", "-", pack_name).strip("-")[:30]

    return {
        "pack_name":        pack_name,
        "brief":            str(data.get("brief") or "").strip(),
        "sources":          sources,
        "per_source_limit": max(2, min(psl, 10)),
        "top_k":            max(10, min(topk, 100)),
        "explanation":      str(data.get("explanation") or "").strip(),
    }


def rank_results(topic: str,
                 results: list[SourceResult],
                 model_spec: dict,
                 top_k: int = 30,
                 scope: str = "overview",
                 brief: str = "",
                 threshold: float = 0.3
                 ) -> tuple[list[SourceResult], list[SourceResult]]:
    """
    Score every candidate against the user's intent (topic + scope + brief).
    Always runs the LLM ranker — no early-exit on small candidate sets.
    Returns (kept, dropped) where:
        kept    = candidates with score ≥ threshold, sorted desc, capped at top_k
        dropped = candidates that fell below threshold (for logging in the GUI)
    """
    if not results:
        return [], []

    # Build a compact rateable batch
    lines = []
    for i, r in enumerate(results):
        lines.append(
            f"[{i}] ({r.source}/{r.kind}, lang={r.lang or '?'}) "
            f"{r.title} — {r.snippet[:160]}"
        )
    listed = "\n".join(lines)

    system = (
        "You rate sources by how DIRECTLY relevant they are to a specific knowledge "
        "pack request defined by a TOPIC and an INTENT (scope + optional brief).\n\n"
        "Scoring guide:\n"
        "  0.90-1.00 — directly on the topic AND fits the scope/brief.\n"
        "  0.60-0.89 — on the topic but partial fit with the scope.\n"
        "  0.30-0.59 — adjacent / partially related.\n"
        "  0.00-0.29 — off-topic. THIS BUCKET INCLUDES keyword-collision results: "
        "sources whose title shares a word with the topic but discuss a completely "
        "different entity, person, or field. Examples to DOWNRANK aggressively:\n"
        "    · Topic 'Stoicism' (Zeno of Citium) ↔ result about 'Quantum Zeno effect' "
        "(physics, named after Zeno of Elea). SCORE 0.05.\n"
        "    · Topic 'Julius Caesar' (Roman) ↔ result about a 'Caesar' cipher or "
        "the Las Vegas casino. SCORE 0.05.\n"
        "    · Topic 'transformer' (ML) ↔ result about electrical transformers. SCORE 0.05.\n"
        "If the title or snippet doesn't substantially address the user's specific "
        "topic, score it low even if it's a high-authority source. Be strict.\n\n"
        "Output JSON only."
    )
    user = (
        f"TOPIC: {topic}\n"
        f"SCOPE ({scope}): {_scope_block(scope)}\n"
        f"{_brief_block(brief)}\n"
        f"CANDIDATES:\n{listed}\n\n"
        f"Return a JSON object {{\"scores\": [{{\"i\": <int>, \"s\": <0..1>}}, ...]}}. "
        f"Include every candidate exactly once. Use the full 0..1 range — do NOT "
        f"bunch everything near 0.5 to play it safe."
    )

    raw = _chat(system, user, model_spec, max_tokens=4000, json_mode=True)
    data = _parse_json(raw)
    scores: dict[int, float] = {}
    if isinstance(data, dict) and isinstance(data.get("scores"), list):
        for entry in data["scores"]:
            try:
                i = int(entry.get("i"))
                s = float(entry.get("s"))
                if 0 <= i < len(results):
                    scores[i] = max(0.0, min(1.0, s))
            except Exception:
                continue

    # Apply scores. If a candidate didn't get scored at all, give it a low default
    # so it doesn't bypass the threshold by accident.
    for i, r in enumerate(results):
        r.score = scores.get(i, 0.2)

    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
    kept    = [r for r in sorted_results if r.score >= threshold][:top_k]
    dropped = [r for r in sorted_results if r.score <  threshold]
    return kept, dropped


# ── Provider plumbing ─────────────────────────────────────────────────────────

def _chat(system: str, user: str, spec: dict, max_tokens: int = 2000,
          json_mode: bool = False) -> str:
    provider = (spec.get("provider") or "openrouter").lower()
    if provider == "openrouter":
        return _chat_openrouter(system, user, spec, max_tokens, json_mode)
    if provider == "ollama":
        return _chat_ollama(system, user, spec, max_tokens, json_mode)
    raise ValueError(f"Unknown LLM provider: {provider}")


def _chat_openrouter(system: str, user: str, spec: dict, max_tokens: int,
                     json_mode: bool) -> str:
    """
    Single OpenRouter chat call for Scout's lightweight routing tasks
    (query expansion, domain classification, ranking, parameter suggestion).

    NOTE — reasoning explicitly minimised: every Scout call is a config/routing
    decision that doesn't benefit from chain-of-thought. GPT-5 family models
    default to heavy reasoning that can hang for several minutes on what should
    be a 2-second JSON shape. We set `reasoning.effort = "minimal"` to short-
    circuit that. Also caps the HTTP timeout at 60s so a stuck upstream fails
    fast instead of hanging the UI silently.
    """
    key = spec.get("api_key", "")
    if not key:
        raise RuntimeError("OpenRouter API key not configured for Scout.")
    body: dict[str, Any] = {
        "model": spec.get("model") or "openai/gpt-5-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": max_tokens,
        # Provider-agnostic field (OpenRouter unified). Both gpt-5 and Claude
        # honour it; non-reasoning models simply ignore it.
        "reasoning": {"effort": "minimal"},
        # OpenAI native flat field — duplicated for older proxy paths that
        # don't unwrap the nested form.
        "reasoning_effort": "minimal",
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as c:
            r = c.post(OR_API_URL,
                       headers={
                           "Authorization": f"Bearer {key}",
                           "Content-Type":  "application/json",
                           "HTTP-Referer":  "https://opencognitivecommons.org",
                           "X-Title":       "OCC Forge Scout",
                       },
                       json=body)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"OpenRouter timed out after 60s: {exc}") from exc
    if not r.is_success:
        raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:400]}")
    msg = r.json()["choices"][0]["message"]
    return msg.get("content") or msg.get("reasoning_content") or ""


def _chat_ollama(system: str, user: str, spec: dict, max_tokens: int,
                 json_mode: bool) -> str:
    """Local model via Ollama. Forces think=False for snappiness."""
    import ollama  # delayed import: only required when user picks 'local'
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    options = {"num_predict": max_tokens}
    kwargs: dict[str, Any] = {
        "model":      spec.get("model"),
        "messages":   messages,
        "options":    options,
        "think":      False,
        "keep_alive": -1,
    }
    if json_mode:
        kwargs["format"] = "json"
    resp = ollama.chat(**kwargs)
    return (resp.get("message") or {}).get("content", "") or ""


def _parse_json(raw: str) -> Any:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Salvage: the model sometimes wraps JSON in fences or chatter
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}
