"""
code_inspect — large skill for the "code-related question" category.

Covers 8 distinct user intents through internal recognition:
    debug    — diagnose an error and propose a concrete fix
    explain  — walk through the code block by block
    review   — find issues (bugs / security / performance / maintainability)
    test     — propose a complete test suite
    port     — translate to another language
    compare  — side-by-side analysis of two snippets
    search   — locate something inside the user's code
    extend   — design + implementation snippet for a new feature on top

What this skill does NOT do:
    - generate code FROM SCRATCH (no input code)        → use `code_generate`
    - rewrite existing code into a better version       → use `code_refactor`

Pipeline (3 internal LLM calls + 1 retrieval before the final answer):
    1. Intent recognition          (~200 ms — short prompt, num_predict=8)
    2. Context detection           (~400 ms — JSON output, num_predict=200)
    3. Keyword translation         (inside pack_retrieve, ~400 ms)
    4. pack_retrieve grounded ctx  (broker + page fetch, ~500-1500 ms)
    5. Composition                 (no LLM — assembled deterministically)
Total: ~2-3 s pre-response, then engine streams the final answer to the user.
"""
from __future__ import annotations

import json
import re

import ollama

from node.deliberation.skills import Skill
from node.retrieval.pack_retrieve import pack_retrieve


# ── Mapping detected language → installed pack name ──────────────────────────
# Pack must exist on the broker. When language is detected but no pack maps,
# the skill degrades gracefully (no retrieval grounding, model uses training).
_LANG_TO_PACK: dict[str, str] = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "javascript",   # share the JS pack
    "node": "javascript",
    "nodejs": "javascript",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "docker": "docker",
    "dockerfile": "docker",
    "mcp": "mcp",
}


# ── The 8 intents — each with a final-instruction the model uses to write ─────
# its user-facing answer (ordered so the LLM sees them as a clear menu).
_INTENTS: dict[str, str] = {
    "debug": (
        "Diagnose the error precisely (root cause, not just symptom). Then "
        "give the user a step-by-step fix with concrete shell commands or "
        "code edits. If the user is missing a dependency, name the install "
        "command for the platform implied by the error."
    ),
    "explain": (
        "Walk the user through the code block by block. Name the patterns and "
        "idioms used. Explain WHY the author wrote it this way, not just what "
        "each line does syntactically. End with one or two sentences on the "
        "code's overall purpose and trade-offs."
    ),
    "review": (
        "List concrete issues found, grouped by category (Correctness, "
        "Security, Performance, Maintainability). For each issue: severity "
        "(high/medium/low), 1-2 line description, and a suggested fix. "
        "Avoid vague 'consider improving X' — be specific. End with one line "
        "summary of what's good about the code too."
    ),
    "test": (
        "Propose a complete test suite using the conventional framework for "
        "this language (pytest for Python, Jest/Vitest for JS, testing for "
        "Go, etc.). Cover: happy path, edge cases, error cases. Output the "
        "full test file, runnable as-is."
    ),
    "port": (
        "Translate the code to the target language requested. Preserve "
        "semantics. Where the source's idiom doesn't translate directly, "
        "show the target-language idiom and add a comment explaining the "
        "difference. Output the full translated file."
    ),
    "compare": (
        "Compare the two code excerpts side by side. Identify what's the "
        "same, what's different at the algorithmic level, and which approach "
        "is better in which context (performance, readability, idiomaticity). "
        "End with a concrete recommendation."
    ),
    "search": (
        "Identify where in the provided code the requested element lives. "
        "Quote line numbers when visible. If multiple occurrences exist, list "
        "each with its surrounding context. If absent, say so explicitly and "
        "suggest where it would conventionally be added."
    ),
    "extend": (
        "Propose a design for the requested extension first (1-2 paragraphs), "
        "then provide a concrete implementation snippet that fits the "
        "existing code style. Note any new dependencies or breaking changes "
        "the extension would introduce."
    ),
}


# ── Per-intent retrieval keyword bias ────────────────────────────────────────
# Adds intent-specific terms to the BM25 keyword query so the pack returns
# the most useful pages (install/error pages for debug, testing pages for
# test, etc.) instead of generic overview pages.
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "debug":   ["error", "fix", "troubleshoot", "install"],
    "explain": ["overview", "concept", "how"],
    "review":  ["best practice", "antipattern", "pitfall", "convention"],
    "test":    ["testing", "framework", "fixture"],
    "port":    ["equivalent", "comparison", "idiom"],
    "compare": ["comparison", "difference", "trade-off"],
    "search":  ["reference", "api"],
    "extend":  ["pattern", "example", "extension"],
}


# Detect a code block in the user's query (markdown fence OR a plausible
# language opener at the start of a line). Lets the skill warn early when
# the user asks "explain this" but didn't actually paste code.
_CODE_HINT_PATTERN = re.compile(
    r"```|^\s*(def |class |function |import |from |const |let |var |"
    r"#include |package |fn |use |func |interface |type |struct |enum )",
    re.MULTILINE,
)


def _log(msg: str) -> None:
    """Write to the GUI log bus when available."""
    try:
        from node.apps.gui import log_bus
        log_bus.write(msg)
    except Exception:
        pass


# ── The skill class ──────────────────────────────────────────────────────────

class CodeInspectSkill(Skill):
    name = "code_inspect"
    description = (
        "Analyze code that the user has provided. Use this skill for any "
        "question ABOUT existing code: debugging an error, explaining what "
        "the code does, requesting a code review, asking for tests, "
        "translating to another language, comparing two snippets, finding "
        "something in the code, or designing a feature on top of it. "
        "Does NOT generate new code from scratch (that's code_generate) "
        "and does NOT rewrite/refactor existing code (that's code_refactor). "
        "Works in any natural language: the skill internally translates "
        "queries to the pack's language for grounded retrieval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The user's full request, including any pasted code, "
                    "error messages, or stacktraces. Pass the message verbatim."
                ),
            },
        },
        "required": ["query"],
    }
    tier_min = 1

    def run(self, args: dict, ctx=None):
        query = (args or {}).get("query", "").strip()
        if not query:
            yield ("result", "code_inspect: missing 'query' argument.")
            return

        if ctx is None or not getattr(ctx, "model", None):
            yield ("result",
                "code_inspect: an LLM model is required for intent and context "
                "detection. The engine should always pass ctx.model — this is "
                "a bug if you see it."
            )
            return
        model = ctx.model

        has_code = bool(_CODE_HINT_PATTERN.search(query))

        # ── Step 1: intent recognition ──────────────────────────────────────
        yield ("status", "Recognizing what you're asking about your code...")
        intent = _recognize_intent(query, model)
        _log(f"[code_inspect] intent = {intent}")

        # If the intent strictly needs code but the user didn't paste any,
        # don't waste cycles on retrieval — surface the gap immediately.
        intents_requiring_code = {"debug", "explain", "review", "test", "port", "compare", "search", "extend"}
        if intent in intents_requiring_code and not has_code:
            yield ("result", _no_code_response(intent, query))
            return

        # ── Step 2: context detection (language, framework, key symbols) ────
        yield ("status", f"Detected intent: {intent}. Identifying language and framework...")
        context = _detect_context(query, model)
        language = (context.get("language") or "").lower().strip()
        framework = (context.get("framework") or "").strip()
        key_symbols = [s for s in context.get("key_symbols", []) if isinstance(s, str)][:5]
        _log(f"[code_inspect] language={language!r} framework={framework!r} symbols={key_symbols}")

        # ── Step 3: pack retrieval (only if the language maps to a pack) ────
        pack_scope = _LANG_TO_PACK.get(language)
        retrieval_text = ""
        if pack_scope:
            yield ("status", f"Looking up '{pack_scope}' pack documentation...")
            keywords = _build_keywords(intent, context, query)
            _log(f"[code_inspect] retrieval keywords: {keywords!r} scope={pack_scope}")
            try:
                retrieval_text = pack_retrieve(
                    query=keywords,
                    scope=pack_scope,
                    model=model,           # enables LLM keyword translation
                    deep_walk=False,       # scope is already specific
                    max_chars=3000,
                )
                _log(f"[code_inspect] retrieved {len(retrieval_text)} chars")
            except Exception as e:
                _log(f"[code_inspect] pack_retrieve failed: {e}")
                retrieval_text = ""
        else:
            yield ("status",
                f"No pack installed for '{language or 'unknown language'}'; "
                "answering from the model's general knowledge."
            )

        # ── Step 4: assemble the model-facing context block ─────────────────
        yield ("status", "Composing analytical response...")
        yield ("result", _compose_response(
            intent=intent,
            language=language,
            framework=framework,
            key_symbols=key_symbols,
            retrieval_text=retrieval_text,
            user_query=query,
        ))


SKILL = CodeInspectSkill()


# ── Internal helpers (private; pure functions where possible) ─────────────────

def _recognize_intent(query: str, model: str) -> str:
    """LLM call: classify the user's request into one of the 8 code intents.
    Returns the intent label. Defaults to 'explain' on any failure or if the
    model returns a label we don't recognize."""
    intents_block = "\n".join(
        f"  {name}    — {desc.split('.')[0]}."
        for name, desc in _INTENTS.items()
    )
    system = (
        "You classify a user's code-related request into ONE label. "
        "Reply with only the label, no explanation, no quotes.\n\n"
        "Labels:\n"
        + intents_block
        + "\n\nDefault to 'explain' when the request is ambiguous."
    )
    examples = (
        "Examples (any language):\n"
        '"why does this throw TypeError?" → debug\n'
        '"perché questo codice non funziona?" → debug\n'
        '"ho un ModuleNotFoundError, aiutami" → debug\n'
        '"what does this regex do?" → explain\n'
        '"spiegami questa funzione" → explain\n'
        '"explique-moi ce code" → explain\n'
        '"is there anything wrong with this code?" → review\n'
        '"trovami i problemi nel codice" → review\n'
        '"do a code review" → review\n'
        '"write tests for this function" → test\n'
        '"scrivimi i test" → test\n'
        '"port this from JavaScript to Python" → port\n'
        '"traduci da Python a Go" → port\n'
        '"which approach is better, A or B?" → compare\n'
        '"qual è la differenza tra questi due?" → compare\n'
        '"where is the auth check in this code?" → search\n'
        '"trovami dove sta la funzione X" → search\n'
        '"add caching to this function" → extend\n'
        '"aggiungi una feature per X" → extend\n'
    )
    try:
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system + "\n\n" + examples},
                {"role": "user", "content": query[:2000]},
            ],
            think=False,
            keep_alive=-1,
            options={"temperature": 0.0, "num_predict": 8},
            stream=False,
        )
        out = (resp.message.content or "").strip().lower()
        first = out.split()[0].strip(".,;:!?\"'`") if out else ""
        return first if first in _INTENTS else "explain"
    except Exception:
        return "explain"


def _detect_context(query: str, model: str) -> dict:
    """LLM call: extract structured code context from the query.
    Returns a dict with keys language, framework, key_symbols.
    Empty dict on failure — skill degrades gracefully without retrieval."""
    system = (
        "You extract code context from a user's request. Reply with ONLY a "
        "single JSON object, no prose, no code fences. Schema:\n"
        '  {"language": "<lowercase language name>", '
        '"framework": "<main framework or empty string>", '
        '"key_symbols": ["<sym1>", "<sym2>"]}\n\n'
        "language values: python, javascript, typescript, go, rust, docker, "
        "mcp, java, csharp, cpp, ruby, php, sql, bash, yaml, html, css, kotlin, "
        "swift. Use the empty string if you cannot tell.\n"
        "framework: django, fastapi, flask, react, vue, svelte, express, gin, "
        "tokio, etc. Empty string if none/unclear.\n"
        "key_symbols: 0-5 important identifiers — function names, class names, "
        "library names, error names — that the user mentioned or that appear "
        "in pasted code. These will be used as retrieval keywords.\n\n"
        "If a code block is present, base detection on it. Otherwise infer "
        "from explicit mentions in the question."
    )
    try:
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": query[:3000]},
            ],
            think=False,
            keep_alive=-1,
            options={"temperature": 0.0, "num_predict": 200, "num_ctx": 2048},
            stream=False,
        )
        out = (resp.message.content or "").strip()
        # The model may wrap the JSON in code fences or prose despite instructions
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if not m:
            return {}
        return json.loads(m.group(0))
    except Exception:
        return {}


def _build_keywords(intent: str, context: dict, original_query: str) -> str:
    """Compose a keyword query for pack_retrieve. Combines: detected key
    symbols + framework name + intent-bias terms. The translation step inside
    pack_retrieve will then convert these into the pack's language if
    necessary."""
    parts: list[str] = []
    parts.extend(context.get("key_symbols", [])[:5])
    framework = context.get("framework") or ""
    if framework:
        parts.append(framework)
    parts.extend(_INTENT_KEYWORDS.get(intent, []))
    if not parts:
        # Fallback: take the first ~80 chars of the user query and let the
        # translator pull keywords from it.
        return original_query[:80]
    return " ".join(parts)


def _no_code_response(intent: str, query: str) -> str:
    """Used when the user's intent strictly needs source code but they
    didn't include any. Returns a conversational redirect that asks for the
    code, in a tone that matches the language they wrote in (Qwen handles
    the language naturally when given a clear prompt)."""
    return (
        f"[code_inspect — intent: {intent}, but no source code was provided]\n\n"
        f"[User's request]\n{query.strip()}\n\n"
        "[Final instruction]\n"
        "Reply briefly in the user's language: explain that this request "
        f"({intent}) needs the actual source code to work on. Ask the user "
        "to paste the code into the chat (markdown ``` fences) or to upload "
        "a file via the + button. Don't try to guess or invent code to "
        "analyze — just ask politely."
    )


def _compose_response(
    intent: str,
    language: str,
    framework: str,
    key_symbols: list[str],
    retrieval_text: str,
    user_query: str,
) -> str:
    """Assemble the text the engine feeds back to Qwen for the final answer.

    Structure (the model reads this as one big context block):
      1. Recognition header — what the skill understood
      2. The user's original verbatim request (so Qwen sees the code too)
      3. Grounded retrieval from the pack, if any
      4. Final instruction tailored to the recognized intent
    """
    header_bits = [f"intent: {intent}", f"language: {language or 'unknown'}"]
    if framework:
        header_bits.append(f"framework: {framework}")
    if key_symbols:
        header_bits.append("symbols: " + ", ".join(key_symbols))
    header = "[code_inspect — " + " | ".join(header_bits) + "]"

    sections = [header]
    sections.append(f"\n[User's original request — preserve all code blocks verbatim when relevant]\n{user_query.strip()}")

    if retrieval_text.strip():
        sections.append(
            f"\n[Grounded context from the {language} pack]\n"
            + retrieval_text.strip()
        )
    else:
        sections.append(
            "\n[No grounded context retrieved from any pack — answer from "
            "your training, but stay conservative on specific claims like "
            "version numbers, exact API signatures, or library availability.]"
        )

    sections.append(f"\n[Final instruction]\n{_INTENTS[intent]}")
    return "\n\n".join(sections)
