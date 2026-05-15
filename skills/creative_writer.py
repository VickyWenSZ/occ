"""
creative_writer — entity-aware grounding for creative writing requests.

Design ratio (Vicky, 2026-05-15):
    The skill does NOT add creative instructions, forms, templates, or
    stylistic guidance. The LLM already knows how to write creatively from
    its training. The skill's ONLY job is to detect whether the request
    names specific identifiable entities that the model can't reliably
    invent (named authors, works, characters, styles, places, cultural
    objects) and, if so, fetch relevant context from the packs.

Flow:
    1. Micro-call LLM: "does this request name specific entities? yes/no
       + list". One JSON line, no chain of thought.
    2. If no entities → return empty string. The engine, with the matching
       empty-result guard in `_run_skill`, will not append any wrapper —
       the LLM receives the user's query verbatim and answers freely.
    3. If entities → for each one, call `pack_retrieve(entity=...)`. The
       broker's /lookup_entity finds the right pack; pack_retrieve handles
       cross-language keyword translation. Return one context block per
       entity that produced retrieval. Empty string if none produced
       anything.
"""
from __future__ import annotations

import json
import re

import ollama

from node.deliberation.skills import Skill
from node.retrieval.pack_retrieve import pack_retrieve


def _log(msg: str) -> None:
    try:
        from node.apps.gui import log_bus
        log_bus.write(msg)
    except Exception:
        pass


_MAX_ENTITIES = 5
_PER_ENTITY_MAX_CHARS = 2500
_PER_ENTITY_TOP_K = 3


_DETECT_SYSTEM = (
    "You inspect a creative-writing request and identify any SPECIFIC entities "
    "that an external knowledge base might cover. Qualifying entities have a "
    "named, identifiable identity an encyclopedia could have a page on:\n"
    "  - Named authors, artists, philosophers, musicians, directors\n"
    "  - Named works (books, films, songs, paintings, plays)\n"
    "  - Named characters, mythological/historical figures\n"
    "  - Named styles, movements, schools, genres (cubism, hermeticism, noir, haiku)\n"
    "  - Specific historical events, places, or culturally-connoted objects\n\n"
    "DO NOT include generic concepts (love, sky, time, sadness, water, freedom, "
    "death, joy, nature, war). DO NOT include common nouns. ONLY entities with "
    "a specific identifiable identity.\n\n"
    "Reply with ONLY a single JSON object, no prose, no code fences:\n"
    '  {\"entities\": [\"name1\", \"name2\", ...]}\n'
    "If no qualifying entities are present, reply with: {\"entities\": []}"
)


def _detect_entities(query: str, model: str) -> list[str]:
    """Single LLM micro-call. Returns the list of identifiable entities, possibly empty."""
    try:
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": _DETECT_SYSTEM},
                {"role": "user", "content": query[:2000]},
            ],
            think=False,
            keep_alive=-1,
            options={"temperature": 0.0, "num_predict": 200, "num_ctx": 2048},
            stream=False,
        )
        raw = (resp.message.content or "").strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(0))
        ents = data.get("entities", [])
        if not isinstance(ents, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for e in ents[:_MAX_ENTITIES]:
            if not isinstance(e, str):
                continue
            clean = e.strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(clean)
        return out
    except Exception as e:
        _log(f"[creative_writer] entity detection failed: {e}")
        return []


class CreativeWriterSkill(Skill):
    name = "creative_writer"
    description = (
        "Handle creative writing requests (poems, stories, lyrics, monologues, "
        "essays, character profiles, dialogues, scripts, any artistic prose). "
        "Retrieves grounding context ONLY when the request names specific "
        "identifiable entities like authors, works, characters, styles, or "
        "places — and otherwise leaves the creative output entirely to the "
        "model. Use this when the user asks for any kind of creative or "
        "artistic writing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The user's full creative writing request, verbatim.",
            },
        },
        "required": ["query"],
    }
    tier_min = 1

    def run(self, args: dict, ctx=None):
        query = (args or {}).get("query", "").strip()
        if not query:
            yield ("result", "")
            return
        if ctx is None or not getattr(ctx, "model", None):
            # No model means no entity detection — degrade to no-grounding.
            yield ("result", "")
            return
        model = ctx.model

        yield ("status", "Checking for entities to ground...")
        entities = _detect_entities(query, model)
        _log(f"[creative_writer] entities: {entities!r}")

        if not entities:
            # No grounding needed — engine will answer the query directly.
            yield ("result", "")
            return

        blocks: list[str] = []
        for i, ent in enumerate(entities, 1):
            yield ("status", f"Looking up {i}/{len(entities)}: {ent}...")
            try:
                ctx_text = pack_retrieve(
                    query=ent,
                    entity=ent,
                    model=model,
                    deep_walk=False,
                    max_chars=_PER_ENTITY_MAX_CHARS,
                    top_k=_PER_ENTITY_TOP_K,
                )
            except Exception as e:
                _log(f"[creative_writer] pack_retrieve failed for {ent!r}: {e}")
                ctx_text = ""

            if ctx_text.strip():
                blocks.append(f"=== {ent} ===\n{ctx_text.strip()}")
            else:
                _log(f"[creative_writer] no pack context for {ent!r}")

        if not blocks:
            # Entities detected but nothing installed — same as no entities.
            yield ("result", "")
            return

        yield ("result", "\n\n".join(blocks))


SKILL = CreativeWriterSkill()
