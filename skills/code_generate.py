"""
code_generate — produce NEW code from a natural-language requirement.

Distinct from `code_inspect` (analyzes existing code) and `code_refactor`
(rewrites existing code). This skill is for "scrivimi una funzione che…",
"genera uno script bash per…", "give me a Flask endpoint that…".

Honest limits with Qwen 9B and (currently) no code-specific packs:
    - Excellent for small-to-medium scripts and standalone functions
    - Solid for common stack idioms (Flask/FastAPI/Express/CLI tools)
    - Weaker on multi-file architecture, exotic languages, very recent APIs
    - With no pack to ground on, stays grounded on the model's training —
      so we add language-specific best-practice hints to the prompt to
      reduce sloppy output (no `eval` in Python, `set -euo pipefail` in
      bash, error returns in Go, etc.)

Pipeline (1-2 internal LLM calls before the final answer):
    1. Requirement extraction      (~300 ms — small JSON output)
    2. Completeness check          (no LLM — pure logic)
    3. (future) pack pattern lookup — extension point, currently no-op
    4. Compose generation prompt   (no LLM — assembled deterministically)
"""
from __future__ import annotations

import json
import re

import ollama

from node.deliberation.skills import Skill
from node.retrieval.pack_retrieve import pack_retrieve


# ── Best-practice hints injected per language ────────────────────────────────
# These keep Qwen 9B from emitting amateur code patterns when it's working
# from raw training without grounding from a pack. Kept short so they don't
# eat too much context.
_LANG_BEST_PRACTICES: dict[str, str] = {
    "python": (
        "Use type hints for public functions. Prefer f-strings over % "
        "formatting. Use pathlib.Path over os.path strings. Use context "
        "managers (with) for files. Never use eval/exec on user input. "
        "Add a brief docstring. If the script has a main entry, use "
        "`if __name__ == \"__main__\":`."
    ),
    "javascript": (
        "Use const/let, never var. Prefer async/await over callbacks. Use "
        "strict equality (===). Handle promise rejections. JSDoc comments "
        "for non-trivial functions. Use modern ES (modules over require)."
    ),
    "typescript": (
        "Define explicit types for function signatures. Avoid `any` — use "
        "`unknown` and narrow. Prefer `interface` for object shapes that "
        "extend, `type` for unions/intersections. Strict null checks."
    ),
    "go": (
        "Idiomatic error returns (`if err != nil` checks at every step). "
        "Use `fmt.Errorf` with %w to wrap errors. Defer cleanup. Small "
        "interfaces. No init-time side effects beyond logging."
    ),
    "rust": (
        "Use Result<T, E> with `?` for propagation. Avoid `unwrap()` in "
        "library code (only in tests/main). Borrow (&str) over owned "
        "(String) where possible. Use `clippy`-friendly patterns."
    ),
    "bash": (
        "Start with `#!/usr/bin/env bash` and `set -euo pipefail`. Quote "
        "all variable expansions (\"$var\"). Use `[[ ]]` for tests, not "
        "`[ ]`. Trap signals for cleanup. Prefer `mktemp` for temp files."
    ),
    "java": (
        "Use try-with-resources for AutoCloseable. Prefer `var` for local "
        "type inference (Java 11+). Use streams where they improve clarity. "
        "Throw specific exceptions, not generic Exception."
    ),
    "csharp": (
        "Use `using` declarations for IDisposable. Prefer pattern matching "
        "in switch. Use `nameof()` for member references. Async all the way "
        "for IO."
    ),
    "cpp": (
        "Use RAII (smart pointers, no raw new/delete). Pass by const& for "
        "non-owning references. Use auto for iterator types. Prefer "
        "`std::span` over raw pointer + length."
    ),
    "ruby": (
        "Use `frozen_string_literal: true` magic comment. Prefer blocks "
        "with `do...end` for multi-line, `{ }` for one-liners. Use safe "
        "navigation `&.` for nil-safe chains."
    ),
    "sql": (
        "Use lowercase keywords (or all-caps consistently). Always alias "
        "tables in joins. Prefer explicit JOINs over implicit. Avoid "
        "SELECT * in production queries."
    ),
}


# ── Mapping detected language → installed pack name ──────────────────────────
# Same as code_inspect — when packs for code exist, generation can ground
# on real examples from the pack. For now, this is a no-op for most langs.
_LANG_TO_PACK: dict[str, str] = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "docker": "docker",
    "dockerfile": "docker",
    "mcp": "mcp",
}


def _log(msg: str) -> None:
    try:
        from node.apps.gui import log_bus
        log_bus.write(msg)
    except Exception:
        pass


# ── The skill class ──────────────────────────────────────────────────────────

class CodeGenerateSkill(Skill):
    name = "code_generate"
    description = (
        "Generate NEW code from a natural-language requirement. Use this "
        "when the user wants you to write code from scratch: a function, "
        "a script, a small program, a CLI tool, an API endpoint, a test "
        "file, etc. Does NOT analyze existing code (use code_inspect for "
        "that) and does NOT rewrite existing code (use code_refactor). "
        "Works in any natural language for the user-facing description."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The user's full request describing what code they want "
                    "generated. Pass the message verbatim including any "
                    "constraints, library preferences, or example inputs."
                ),
            },
        },
        "required": ["query"],
    }
    tier_min = 1

    def run(self, args: dict, ctx=None):
        query = (args or {}).get("query", "").strip()
        if not query:
            yield ("result", "code_generate: missing 'query' argument.")
            return
        if ctx is None or not getattr(ctx, "model", None):
            yield ("result",
                "code_generate: an LLM model is required (engine should "
                "always pass ctx.model — bug if you see this)."
            )
            return
        model = ctx.model

        # ── Step 1: requirement extraction ──────────────────────────────────
        yield ("status", "Understanding what code you want generated...")
        req = _extract_requirement(query, model)
        language = (req.get("language") or "").lower().strip()
        artifact = (req.get("artifact") or "").lower().strip() or "snippet"
        frameworks = [s for s in req.get("frameworks", []) if isinstance(s, str)][:5]
        complexity = (req.get("complexity") or "").lower().strip() or "medium"
        _log(f"[code_generate] req: lang={language!r} artifact={artifact!r} "
             f"frameworks={frameworks} complexity={complexity!r}")

        # ── Step 2: completeness check ──────────────────────────────────────
        # If we couldn't even pin down a language, ask for it. Without the
        # language we can't pick best-practice hints, can't choose syntax,
        # and the output would be a guess.
        if not language:
            yield ("result", _missing_language_response(query))
            return

        # ── Step 3: pack retrieval (extension point — currently a no-op for
        # most languages because code-specific packs don't yet exist) ───────
        retrieval_text = ""
        pack_scope = _LANG_TO_PACK.get(language)
        if pack_scope:
            yield ("status", f"Looking for similar examples in '{pack_scope}' pack...")
            keywords = _build_pattern_keywords(req, query)
            _log(f"[code_generate] pattern lookup keywords: {keywords!r}")
            try:
                retrieval_text = pack_retrieve(
                    query=keywords,
                    scope=pack_scope,
                    model=model,
                    deep_walk=False,
                    max_chars=2000,  # smaller cap — patterns are reference, not full answer
                )
                _log(f"[code_generate] retrieved {len(retrieval_text)} chars of patterns")
            except Exception as e:
                _log(f"[code_generate] pack_retrieve failed: {e}")
                retrieval_text = ""

        # ── Step 4: compose generation prompt ───────────────────────────────
        complexity_label = {
            "small": "small (~10-30 lines)",
            "medium": "medium (~30-100 lines)",
            "large": "large (multi-component)",
        }.get(complexity, complexity)
        yield ("status",
            f"Composing generation prompt ({language}, {artifact}, "
            f"{complexity_label})..."
        )
        yield ("result", _compose_generation_prompt(
            language=language,
            artifact=artifact,
            frameworks=frameworks,
            complexity=complexity,
            retrieval_text=retrieval_text,
            user_query=query,
        ))


SKILL = CodeGenerateSkill()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_requirement(query: str, model: str) -> dict:
    """LLM call: extract a structured requirement spec from the user's
    natural-language ask. Returns a dict with:
        language    — target language (lowercase, empty if not stated/inferable)
        artifact    — function | script | class | module | endpoint | test | snippet | cli | api | other
        frameworks  — 0-5 named libraries/frameworks the user wants used
        complexity  — small | medium | large

    Empty/partial dict on failure — the caller uses defaults."""
    system = (
        "You extract a code-generation requirement from a user's request. "
        "Reply with ONLY a single JSON object, no prose, no code fences. "
        "Schema:\n"
        '  {"language": "<lowercase target language or empty>", '
        '"artifact": "<function|script|class|module|endpoint|test|cli|api|snippet|other>", '
        '"frameworks": ["<lib1>", "<lib2>"], '
        '"complexity": "<small|medium|large>"}\n\n'
        "Rules:\n"
        "- language: ONLY if the user explicitly states it OR the request "
        "strongly implies it (e.g. 'CLI tool with click' implies python). "
        "If genuinely unclear, set to empty string.\n"
        "- artifact: pick the closest match. Default 'snippet' if unsure.\n"
        "- frameworks: only those the user named or that are obviously implied.\n"
        "- complexity: small (<30 lines, single concept), medium (30-100 "
        "lines, a few moving pieces), large (multi-file or architectural).\n"
    )
    try:
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": query[:2500]},
            ],
            think=False,
            keep_alive=-1,
            options={"temperature": 0.0, "num_predict": 200, "num_ctx": 2048},
            stream=False,
        )
        out = (resp.message.content or "").strip()
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if not m:
            return {}
        return json.loads(m.group(0))
    except Exception:
        return {}


def _build_pattern_keywords(req: dict, query: str) -> str:
    """Build a short BM25 keyword query for finding RELEVANT PATTERNS in a
    code pack (e.g. 'csv reading dictionary count' → finds the page on
    csv.DictReader). Used only when a pack exists for the language."""
    parts: list[str] = []
    artifact = (req.get("artifact") or "").lower()
    if artifact and artifact != "snippet":
        parts.append(artifact)
    for fw in req.get("frameworks", [])[:3]:
        if isinstance(fw, str) and fw.strip():
            parts.append(fw.strip())
    parts.append("example")
    parts.append("pattern")
    if not parts:
        return query[:80]
    return " ".join(parts)


def _missing_language_response(query: str) -> str:
    """Surface the missing-language gap immediately instead of guessing.
    Returns text the engine feeds to Qwen for a polite clarification reply."""
    return (
        "[code_generate — could not determine target language]\n\n"
        f"[User's original request]\n{query.strip()}\n\n"
        "[Final instruction]\n"
        "Reply briefly in the user's language: explain that you can generate "
        "the code but need to know which language they want (Python, "
        "JavaScript, Go, Rust, bash, etc.). Mention 2-3 options that would "
        "make sense for the task they described, and ask them to pick one. "
        "Do NOT guess and produce code in a random language."
    )


def _compose_generation_prompt(
    language: str,
    artifact: str,
    frameworks: list[str],
    complexity: str,
    retrieval_text: str,
    user_query: str,
) -> str:
    """Build the context block the engine feeds to Qwen for the final answer.

    Structure:
      1. Recognition header — what the skill understood
      2. The user's original verbatim request (so Qwen has the full ask)
      3. Optional pack patterns (when available)
      4. Language-specific best-practice hints
      5. Final instruction tailored to artifact type
    """
    header_bits = [f"language: {language}", f"artifact: {artifact}"]
    if frameworks:
        header_bits.append("frameworks: " + ", ".join(frameworks))
    if complexity:
        header_bits.append(f"complexity: {complexity}")
    header = "[code_generate — " + " | ".join(header_bits) + "]"

    sections = [header]
    sections.append(f"\n[User's original request]\n{user_query.strip()}")

    if retrieval_text.strip():
        sections.append(
            f"\n[Reference patterns from the {language} pack]\n"
            + retrieval_text.strip()
            + "\n(Use these as inspiration for idioms and structure, not as "
            "code to copy verbatim.)"
        )

    bp = _LANG_BEST_PRACTICES.get(language)
    if bp:
        sections.append(f"\n[Best practices for {language} — apply these]\n{bp}")

    artifact_hint = _ARTIFACT_INSTRUCTION.get(artifact) or _ARTIFACT_INSTRUCTION["snippet"]
    sections.append(
        "\n[Final instruction]\n"
        "Generate the code the user requested. " + artifact_hint
        + " After the code block, write 2-4 lines explaining the design "
        "choices and how to run/test it. Keep the explanation concise — the "
        "code is the main output."
    )
    return "\n\n".join(sections)


# Per-artifact final-instruction nudges. Keeps Qwen from producing the wrong
# shape (e.g. a bare snippet when the user asked for a full script).
_ARTIFACT_INSTRUCTION: dict[str, str] = {
    "function": (
        "Output a single, complete function with type hints/signatures, a "
        "docstring/comment describing its contract, and inline comments only "
        "where the logic is non-obvious."
    ),
    "script": (
        "Output a complete, runnable script — shebang line if applicable, "
        "argument parsing if needed, error handling, and a clean exit. "
        "Should run as-is from the command line."
    ),
    "class": (
        "Output a complete class with constructor, public methods, and "
        "private helpers as needed. Include a brief docstring on the class "
        "and on each public method."
    ),
    "module": (
        "Output a complete module file: imports at the top, public API "
        "exported clearly, internal helpers prefixed with `_`. Include a "
        "module-level docstring."
    ),
    "endpoint": (
        "Output the endpoint handler complete with route definition, request "
        "validation, business logic, and response. Include error responses "
        "for the obvious failure modes."
    ),
    "test": (
        "Output a complete test file using the conventional framework. Cover "
        "happy path, edge cases, and at least one error case. Use clear test "
        "names that describe the behavior being verified."
    ),
    "cli": (
        "Output a complete CLI tool with proper argument parsing (argparse / "
        "click / commander / cobra as idiomatic), --help text, and exit "
        "codes. Single file unless the user specified multi-file."
    ),
    "api": (
        "Output a complete small API: framework setup, the routes the user "
        "described, request/response models, and the obvious error handling. "
        "Single file unless the user asked for more."
    ),
    "snippet": (
        "Output a focused code snippet that solves the user's specific ask. "
        "No boilerplate beyond what's needed."
    ),
    "other": (
        "Output the code in the most natural shape for the request."
    ),
}
