"""
Two-stage query router for OCC.

Why this design (and not "let the model figure it out"):
    Frontier LLMs (Claude, GPT-5) handle tool selection inside generation
    with no separate classifier — they're big enough to read the full tool
    list and decide on the fly. Qwen 9B can't reliably do that with 14
    tools/skills. So we scaffold the decision into small, focused LLM calls.

Stage 1 — `_classify_intent`
    4-way label, each with EXACTLY ONE meaning (no overlap):
        chitchat   — purely social / meta. No tools, no retrieval.
        tools      — one concrete action: search web, fetch URL, read or
                     write a file in workspace, run code.
        knowledge  — informational question that benefits from the curated
                     knowledge packs (history, science, how-to, etc.).
        skill      — composite multi-step task that maps to an orchestrated
                     skill (deep research, fact-checking, multi-file Q&A).

Stage 2 — `_classify_skill` (only if Stage 1 returned 'skill')
    Picks ONE skill from the registry whose purpose matches the user's intent.

Public API:
    classify(model, query, skill_registry=None) -> str
        Returns one of: 'chitchat' | 'tools' | 'deliberate' | 'skill:<name>'
        ('knowledge' is renamed 'deliberate' on the wire for backwards
        compatibility with the engine's existing path.)
"""
import json
import re
import ollama


# ── Stage 1 prompt ────────────────────────────────────────────────────────────

_STAGE1_SYSTEM = (
    "Route the query. Reply with ONE label only.\n\n"
    "chitchat   — social, meta, greetings. No external action.\n"
    "tools      — single concrete action: web search, URL fetch, read/write file, run code, list files.\n"
    "knowledge  — informational question to answer from curated packs.\n"
    "skill      — multi-step composite task: deep research, fact-check, multi-file Q&A, code analysis/generation/refactor.\n\n"
    "If unsure: knowledge."
)

_STAGE1_EXAMPLES = (
    "Examples:\n"
    "hi → chitchat\n"
    "thanks → chitchat\n"
    "who are you → chitchat\n"
    "what can you do → chitchat\n"
    "search the web for X → tools\n"
    "fetch this URL → tools\n"
    "run this code → tools\n"
    "write file foo.txt → tools\n"
    "list workspace files → tools\n"
    "what packs do you have on the broker → tools\n"
    "show me what's under marketing → tools\n"
    "download pack marketing/storybrand → tools\n"
    "browse the catalog → tools\n"
    "what is TCP/IP → knowledge\n"
    "who was Caesar → knowledge\n"
    "explain HTTPS → knowledge\n"
    "how does OAuth work → knowledge\n"
    "do deep research on X → skill\n"
    "fact-check this claim → skill\n"
    "summarize all my uploaded files → skill\n"
    "debug this Python error <code> → skill\n"
    "refactor this function <code> → skill\n"
    "write me a Flask endpoint → skill\n"
    "explain what this code does <code> → skill\n"
    "write me a poem about the sky → skill\n"
    "write a poem in the style of <author> → skill\n"
    "write a short story about Y → skill\n"
    "compose a monologue for character Z → skill\n"
    "write the homepage copy using <framework> → skill\n\n"
    "Disambiguation:\n"
    "- topic question → knowledge (NOT skill, unless multi-step)\n"
    "- code attached → skill (NOT knowledge — code analysis is a skill)\n"
    "- current/latest events → tools (web search), NOT knowledge\n"
    "- short clarification → chitchat, NOT knowledge\n"
)


# ── Fast-path chitchat (avoid an LLM call on trivial greetings) ──────────────

_CHAT_LITERALS = {
    # English
    "hi", "hello", "hey", "yo", "thanks", "thank you", "ty", "ok", "okay",
    "bye", "goodbye", "good morning", "good evening", "good night",
    # Italian
    "ciao", "salve", "grazie", "buongiorno", "buonasera", "buonanotte", "ok", "va bene",
    # French / Spanish / German basics
    "bonjour", "merci", "hola", "gracias", "hallo", "danke",
}


def _looks_like_pure_chitchat(q: str) -> bool:
    s = q.strip().lower().rstrip("!.?,;:")
    if not s:
        return True
    if s in _CHAT_LITERALS:
        return True
    if len(s) <= 3 and re.match(r"^[\w\s]+$", s):
        return True
    return False


# ── Stage 1: 4-way intent ─────────────────────────────────────────────────────

def _classify_intent(model: str, query: str, has_skills: bool) -> str:
    """Return one of: 'chitchat' | 'tools' | 'knowledge' | 'skill'.
    When `has_skills` is False, 'skill' is removed from the prompt so we never
    suggest routing to a non-existent stage 2."""
    system = _STAGE1_SYSTEM
    examples = _STAGE1_EXAMPLES
    if not has_skills:
        # Strip the skill option from prompt + examples
        system = system.replace(
            "  skill      — composite multi-step task that needs orchestration: "
            "deep research across multiple web sources, fact-checking a specific "
            "claim against evidence, answering questions across multiple uploaded "
            "documents, or anything similarly multi-step.\n\n",
            ""
        ).replace(
            "If unsure between 'knowledge' and 'skill', "
            "pick 'skill' when the request is clearly multi-source or composite, "
            "otherwise 'knowledge'. If unsure between 'tools' and 'skill', pick "
            "'tools' when the request names ONE action, 'skill' when it implies "
            "several steps.",
            "If unsure, pick 'knowledge'."
        )
        examples = "\n".join(
            line for line in examples.splitlines() if "→ skill" not in line
        )

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system + "\n\n" + examples},
            {"role": "user", "content": query},
        ],
        think=False,
        keep_alive=-1,
        options={"temperature": 0.0, "num_predict": 8},
        stream=False,
    )
    raw = (response.message.content or "").strip().lower()
    first = raw.split()[0].strip(".,;:!?\"'`") if raw else ""

    if first == "chitchat":
        return "chitchat"
    if first == "tools":
        return "tools"
    if first == "skill" and has_skills:
        return "skill"
    # Default: knowledge (safest fallback — won't break, packs may not return
    # anything but at least we don't lose the message).
    return "knowledge"


# ── Stage 2: pick which skill ─────────────────────────────────────────────────

def _classify_skill(model: str, query: str, skill_registry) -> str | None:
    """Given that Stage 1 said 'skill', pick the most relevant one."""
    skills = skill_registry.all()
    if not skills:
        return None

    skill_lines = []
    for s in skills:
        skill_lines.append(f"  skill_{s.name} — {s.description.strip()}")

    system = (
        "You route the user's request to one of the orchestrated skills below. "
        "Reply with EXACTLY ONE skill name (the part starting with 'skill_'), "
        "no explanation.\n\n"
        "ORCHESTRATED SKILLS:\n"
        + "\n".join(skill_lines)
        + "\n\nPick the skill whose purpose best matches the user's intent."
    )

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ],
        think=False,
        keep_alive=-1,
        options={"temperature": 0.0, "num_predict": 16},
        stream=False,
    )
    raw = (response.message.content or "").strip().lower()
    first = raw.split()[0].strip(".,;:!?\"'`") if raw else ""
    if not first.startswith("skill_"):
        return None
    name = first[len("skill_"):]
    valid = {s.name for s in skills}
    return name if name in valid else None


# ── Multi-intent pre-pass ────────────────────────────────────────────────────

_MULTI_INTENT_SYSTEM = (
    "Inspect a user query for MULTIPLE DISTINCT requests in one message — "
    "things the assistant must DO separately, that would each need a different "
    "kind of response.\n\n"
    "Multi-intent examples (split):\n"
    "  - 'Explain closures in Python and write an example counter using one' "
    "→ 2 (explain + code)\n"
    "  - 'Tell me about Caesar and write a Python script simulating a battle' "
    "→ 2 (history + code)\n"
    "  - 'Who was Pascoli, write a poem in his style, then compare with Leopardi' "
    "→ 3 (bio + creative + comparison)\n\n"
    "NOT multi-intent (single request, do NOT split):\n"
    "  - 'Explain how OAuth works' → single\n"
    "  - 'Tell me about Caesar and his rise to power' → single (one topic)\n"
    "  - 'Compare Caesar and Napoleon' → single (one comparison task)\n"
    "  - 'Debug this error and explain why it happened' → single (one task)\n"
    "  - 'Write a Flask endpoint that does X and Y' → single (one coding task)\n\n"
    "Reply ONLY with a single JSON object, no prose, no fences:\n"
    "  {\"single\": true}  — for a single request\n"
    "  {\"intents\": [{\"label\": \"...\", \"q\": \"...\"}, ...]}  — for multi "
    "(MAX 3 items; labels are 1-3 words in the user's language, used as section "
    "headers in the UI; each q is SELF-CONTAINED — rewrite pronouns and back-"
    "references so each sub-query stands on its own).\n\n"
    "When unsure, prefer single. Only split when the parts would clearly need "
    "DIFFERENT handling (e.g. one is a question, the other is a creative or "
    "coding task)."
)


def detect_multi_intent(model: str, query: str, max_intents: int = 3) -> list[dict] | None:
    """Detect whether the query bundles 2+ distinct requests in one message.

    Returns:
        None if the query is a single request (the common case).
        A list of {"q": str, "label": str} dicts (length 2..max_intents) when
        the query should be split, each sub-query self-contained and labeled
        for the UI section header.

    Cost: one LLM micro-call (~200-500ms on tier 1-3 hardware). Skipped for
    pure chitchat to avoid waste on greetings.
    """
    if _looks_like_pure_chitchat(query):
        return None
    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": _MULTI_INTENT_SYSTEM},
                {"role": "user", "content": query[:2000]},
            ],
            think=False,
            keep_alive=-1,
            options={"temperature": 0.0, "num_predict": 300, "num_ctx": 2048},
            stream=False,
        )
        raw = (response.message.content or "").strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
    except Exception:
        return None

    if data.get("single") is True:
        return None
    intents = data.get("intents")
    if not isinstance(intents, list) or len(intents) < 2:
        return None

    out: list[dict] = []
    seen_q: set[str] = set()
    for item in intents[:max_intents]:
        if not isinstance(item, dict):
            continue
        q = (item.get("q") or "").strip()
        label = (item.get("label") or "").strip()
        if not q or not label:
            continue
        key = q.lower()
        if key in seen_q:
            continue
        seen_q.add(key)
        out.append({"q": q, "label": label})
    return out if len(out) >= 2 else None


# ── Public API ────────────────────────────────────────────────────────────────

def classify(model: str, query: str, skill_registry=None) -> str:
    """Route a query. Returns one of:
        'chitchat'         — pure social / meta
        'tools'            — single concrete action (atomic tools available)
        'deliberate'       — knowledge retrieval pipeline
        'skill:<name>'     — orchestrated skill (e.g. 'skill:web_research')

    'knowledge' is renamed 'deliberate' on output to keep server.py and the
    engine path naming stable across this refactor.
    """
    if _looks_like_pure_chitchat(query):
        return "chitchat"

    has_skills = bool(skill_registry and len(skill_registry))
    intent = _classify_intent(model, query, has_skills)

    if intent == "chitchat":
        return "chitchat"
    if intent == "tools":
        return "tools"
    if intent == "skill":
        name = _classify_skill(model, query, skill_registry)
        if name:
            return f"skill:{name}"
        # Stage 2 couldn't pick a valid skill → fall back to knowledge retrieval
        return "deliberate"
    # 'knowledge' on the wire goes by 'deliberate' for engine compat
    return "deliberate"
