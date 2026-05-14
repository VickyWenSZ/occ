"""
code_refactor — rewrite existing code into a better version.

Distinct from `code_inspect` (analyzes, produces text) and `code_generate`
(produces new code from scratch). This skill takes existing code AND a goal
("improve", "modernize", "optimize", etc.) and produces REWRITTEN code.

Honest limits with Qwen 9B and (currently) no code-specific packs:
    - Solid for single-file, single-function, or single-class refactors
    - Good for "modernize this Python 2 → 3" or "add type hints" style tasks
    - Weaker on cross-file architectural refactors
    - Risk: refactor can subtly change semantics. The skill instructs the
      model to flag any behavior changes explicitly.

Pipeline (1 internal LLM call before the final answer):
    1. Detect code presence       (no LLM — regex on the query)
    2. Goal + language detection  (~400 ms — single combined JSON call)
    3. (future) pack pattern lookup — extension point, currently no-op
       for most languages because code-specific packs don't yet exist
    4. Compose rewrite prompt     (no LLM — assembled deterministically)
"""
from __future__ import annotations

import json
import re

import ollama

from node.deliberation.skills import Skill
from node.retrieval.pack_retrieve import pack_retrieve


# ── 9 canonical refactor goals — each with the final-instruction Qwen reads ──
_GOALS: dict[str, str] = {
    "improve": (
        "Rewrite the code with a balanced improvement: readability first, "
        "then safety (error handling, edge cases), then minor performance "
        "wins where they don't sacrifice clarity. Don't aggressively "
        "restructure unless the original is clearly poor."
    ),
    "modernize": (
        "Rewrite using modern, idiomatic features of the language (e.g. "
        "Python 3.10+ pattern matching, dataclasses, walrus where it helps; "
        "JS ES2022+ optional chaining, top-level await; etc.). Drop legacy "
        "patterns the codebase doesn't need anymore. Note any minimum "
        "language-version bumps required."
    ),
    "optimize": (
        "Rewrite focusing on performance: better algorithms, fewer "
        "allocations, vectorized operations where applicable, caching where "
        "it pays off. Quantify the expected gain in the explanation. Do NOT "
        "sacrifice correctness for micro-optimization."
    ),
    "simplify": (
        "Rewrite shorter and clearer. Remove dead code, collapse redundant "
        "branches, extract well-named helpers if a function does too much. "
        "Don't golf — clarity over brevity when they conflict."
    ),
    "robustify": (
        "Add proper error handling, input validation, and edge-case coverage. "
        "Replace silent failures with explicit handling. Add type checks at "
        "boundaries (function signatures, deserialization). Don't over-do "
        "defensive programming on internal code."
    ),
    "split": (
        "Restructure: extract functions for distinct responsibilities, "
        "split a large class into smaller cohesive ones, or pull pure logic "
        "out of side-effecting code. Output the result as multiple clearly-"
        "labeled blocks. Note any new module/file boundaries."
    ),
    "type-add": (
        "Add type annotations / type hints throughout, without changing "
        "behavior. For Python: PEP 484 hints + Optional/Union/dataclasses. "
        "For JS: convert to TypeScript or add JSDoc types. For Go/Rust/etc.: "
        "tighten existing types, no `any`/dynamic where avoidable."
    ),
    "secure": (
        "Rewrite removing security vulnerabilities: no eval/exec on user "
        "input, parametrized SQL, escaped HTML output, secrets out of "
        "code, validated paths (no path traversal), bounded resources. "
        "List each fix in the explanation with severity (high/medium/low)."
    ),
    "testable": (
        "Refactor for testability: pure functions where possible, dependency "
        "injection over hardcoded globals, separate side effects from logic. "
        "After the refactored code, sketch the test surface (what would now "
        "be easy to test) without writing the full tests."
    ),
}


_LANG_BEST_PRACTICES: dict[str, str] = {
    "python": (
        "Use type hints. Prefer pathlib over os.path strings. Use context "
        "managers for files. Use dataclasses for plain data carriers. "
        "Never eval/exec on user input. Add concise docstrings."
    ),
    "javascript": (
        "Use const/let, never var. Prefer async/await over callbacks. Strict "
        "equality (===). Modern modules over CommonJS require. JSDoc for "
        "exported functions."
    ),
    "typescript": (
        "Define explicit types for function signatures. Avoid `any` — use "
        "`unknown` and narrow. Strict null checks. Prefer `interface` for "
        "extensible object shapes."
    ),
    "go": (
        "Idiomatic error returns with `if err != nil`. Wrap with fmt.Errorf "
        "and %w. Defer cleanup. Small focused interfaces. Avoid init-time "
        "side effects."
    ),
    "rust": (
        "Use Result<T, E> with `?`. Avoid unwrap() in library code. Borrow "
        "(&str) over owned (String) where possible. Use clippy-friendly "
        "patterns. Match exhaustively."
    ),
    "bash": (
        "Start with `set -euo pipefail`. Quote all variable expansions. Use "
        "`[[ ]]` for tests. Trap signals for cleanup. Use mktemp for temp "
        "files."
    ),
    "java": (
        "try-with-resources for AutoCloseable. Use `var` for type inference "
        "where it improves clarity (Java 11+). Streams where they help. "
        "Throw specific exceptions."
    ),
    "csharp": (
        "Use `using` declarations for IDisposable. Pattern matching in switch. "
        "`nameof()` for member references. Async all the way for IO."
    ),
    "cpp": (
        "RAII with smart pointers — no raw new/delete. Pass by const& for "
        "non-owning references. Use auto for iterators. std::span over "
        "raw pointer + length."
    ),
    "ruby": (
        "Frozen string literals. Blocks: do...end multi-line, { } one-liners. "
        "Safe navigation `&.` for nil-safe chains. Symbol keys in hashes."
    ),
    "sql": (
        "Consistent keyword case. Always alias tables in joins. Explicit "
        "JOINs over implicit. Avoid SELECT * in production."
    ),
}


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


_CODE_HINT_PATTERN = re.compile(
    r"```|^\s*(def |class |function |import |from |const |let |var |"
    r"#include |package |fn |use |func |interface |type |struct |enum )",
    re.MULTILINE,
)


def _log(msg: str) -> None:
    try:
        from node.apps.gui import log_bus
        log_bus.write(msg)
    except Exception:
        pass


# ── The skill class ──────────────────────────────────────────────────────────

class CodeRefactorSkill(Skill):
    name = "code_refactor"
    description = (
        "Rewrite existing code into a better version. Use this when the user "
        "supplies code AND wants it transformed: improved, modernized, "
        "optimized, simplified, made more robust, split into pieces, given "
        "type annotations, made secure, or made more testable. Does NOT "
        "analyze code without rewriting (that's code_inspect) and does NOT "
        "generate new code from scratch (that's code_generate). The output "
        "will be the rewritten code plus a short explanation of what changed "
        "and why."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The user's full request, including the code to refactor "
                    "(in markdown ``` fences) and a description of how they "
                    "want it improved. Pass the message verbatim."
                ),
            },
        },
        "required": ["query"],
    }
    tier_min = 1

    def run(self, args: dict, ctx=None):
        query = (args or {}).get("query", "").strip()
        if not query:
            yield ("result", "code_refactor: missing 'query' argument.")
            return
        if ctx is None or not getattr(ctx, "model", None):
            yield ("result",
                "code_refactor: an LLM model is required (engine should "
                "always pass ctx.model — bug if you see this)."
            )
            return
        model = ctx.model

        # ── Step 1: must have code to refactor ──────────────────────────────
        if not _CODE_HINT_PATTERN.search(query):
            yield ("result", _no_code_response(query))
            return

        # ── Step 2: detect goal + language in a single call ─────────────────
        yield ("status", "Identifying refactor goal and language...")
        info = _detect_goal_and_language(query, model)
        goal = (info.get("goal") or "").lower().strip()
        language = (info.get("language") or "").lower().strip()
        framework = (info.get("framework") or "").strip()
        if goal not in _GOALS:
            goal = "improve"  # safe default
        _log(f"[code_refactor] goal={goal!r} language={language!r} framework={framework!r}")

        # ── Step 3: pack pattern lookup (extension point) ───────────────────
        retrieval_text = ""
        pack_scope = _LANG_TO_PACK.get(language)
        if pack_scope:
            yield ("status", f"Looking up '{pack_scope}' pack for {goal} patterns...")
            keywords = _build_keywords(goal, framework)
            _log(f"[code_refactor] retrieval keywords: {keywords!r}")
            try:
                retrieval_text = pack_retrieve(
                    query=keywords,
                    scope=pack_scope,
                    model=model,
                    deep_walk=False,
                    max_chars=2000,
                )
                _log(f"[code_refactor] retrieved {len(retrieval_text)} chars")
            except Exception as e:
                _log(f"[code_refactor] pack_retrieve failed: {e}")
                retrieval_text = ""
        else:
            yield ("status",
                f"No pack installed for '{language or 'unknown'}'; refactoring "
                "from the model's general knowledge."
            )

        # ── Step 4: compose rewrite prompt ──────────────────────────────────
        yield ("status",
            f"Composing refactor prompt (goal: {goal}, language: "
            f"{language or 'unknown'})..."
        )
        yield ("result", _compose_refactor_prompt(
            goal=goal,
            language=language,
            framework=framework,
            retrieval_text=retrieval_text,
            user_query=query,
        ))


SKILL = CodeRefactorSkill()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _detect_goal_and_language(query: str, model: str) -> dict:
    """Single LLM call extracting refactor goal + language + framework.
    Combined to save one round trip vs. doing them separately."""
    goals_block = "\n".join(
        f"  {name}    — {desc.split('.')[0]}."
        for name, desc in _GOALS.items()
    )
    system = (
        "You analyze a refactor request. Reply with ONLY a single JSON "
        "object, no prose, no code fences. Schema:\n"
        '  {"goal": "<one of the goals below>", '
        '"language": "<lowercase target language or empty>", '
        '"framework": "<main framework or empty string>"}\n\n'
        "Goals:\n" + goals_block + "\n\n"
        "Default goal: 'improve' if the user just says 'make this better' "
        "or similar generic ask.\n"
        "Detect language from the code block (most reliable) or from "
        "explicit mentions in the question. Empty string if truly unclear."
    )
    examples = (
        "Examples:\n"
        '"add type hints to this Python code" → {"goal":"type-add","language":"python","framework":""}\n'
        '"rendi questa funzione più veloce" → {"goal":"optimize","language":"","framework":""}\n'
        '"split this class into smaller pieces" → {"goal":"split","language":"","framework":""}\n'
        '"modernize this jQuery code to vanilla JS" → {"goal":"modernize","language":"javascript","framework":"jquery"}\n'
        '"questo codice è insicuro, sistemalo" → {"goal":"secure","language":"","framework":""}\n'
        '"refactor for testability" → {"goal":"testable","language":"","framework":""}\n'
        '"make this Python code more pythonic" → {"goal":"improve","language":"python","framework":""}\n'
    )
    try:
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system + "\n\n" + examples},
                {"role": "user", "content": query[:3000]},
            ],
            think=False,
            keep_alive=-1,
            options={"temperature": 0.0, "num_predict": 120, "num_ctx": 2048},
            stream=False,
        )
        out = (resp.message.content or "").strip()
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if not m:
            return {}
        return json.loads(m.group(0))
    except Exception:
        return {}


def _build_keywords(goal: str, framework: str) -> str:
    """Compose retrieval keywords biased toward the refactor goal. With no
    code-specific pack installed yet, the result is generic — but this
    primes the pipeline for when those packs land."""
    goal_keywords = {
        "improve":   ["best practice", "convention", "idiom"],
        "modernize": ["modern", "feature", "version"],
        "optimize":  ["performance", "complexity", "efficient"],
        "simplify":  ["clean", "readable", "concise"],
        "robustify": ["error handling", "validation", "edge case"],
        "split":     ["separation", "responsibility", "modular"],
        "type-add":  ["type", "annotation", "static"],
        "secure":    ["security", "vulnerability", "sanitize"],
        "testable":  ["testable", "dependency injection", "pure"],
    }
    parts = list(goal_keywords.get(goal, ["best practice"]))
    if framework:
        parts.append(framework)
    return " ".join(parts)


def _no_code_response(query: str) -> str:
    """No code in the query → ask politely instead of guessing what to refactor."""
    return (
        "[code_refactor — no source code was provided]\n\n"
        f"[User's original request]\n{query.strip()}\n\n"
        "[Final instruction]\n"
        "Reply briefly in the user's language: explain that refactoring "
        "needs the actual source code to work on. Ask the user to paste "
        "the code in the chat (markdown ``` fences) or upload a file via "
        "the + button. Don't try to invent code to refactor."
    )


def _compose_refactor_prompt(
    goal: str,
    language: str,
    framework: str,
    retrieval_text: str,
    user_query: str,
) -> str:
    """Assemble the context block the engine feeds to Qwen for the rewrite.

    Structure:
      1. Recognition header — what the skill understood
      2. The user's original verbatim request (so Qwen sees the code too)
      3. Optional pack patterns (when available)
      4. Language-specific best-practice hints
      5. Final instruction tailored to the refactor goal
    """
    header_bits = [f"goal: {goal}", f"language: {language or 'unknown'}"]
    if framework:
        header_bits.append(f"framework: {framework}")
    header = "[code_refactor — " + " | ".join(header_bits) + "]"

    sections = [header]
    sections.append(f"\n[User's original request — preserve all code blocks verbatim]\n{user_query.strip()}")

    if retrieval_text.strip():
        sections.append(
            f"\n[Reference context from the {language} pack]\n"
            + retrieval_text.strip()
        )

    bp = _LANG_BEST_PRACTICES.get(language)
    if bp:
        sections.append(f"\n[Best practices for {language}]\n{bp}")

    sections.append(
        "\n[Final instruction]\n"
        + _GOALS[goal] + "\n\n"
        "Output format:\n"
        "1. The full rewritten code in a fenced code block.\n"
        "2. A short 'What changed' section listing the concrete changes "
        "(3-7 bullet points), each with a 1-line rationale.\n"
        "3. If any change might alter observable behavior (e.g. error type "
        "raised, ordering of side effects, edge case handling), flag it "
        "explicitly under a 'Behavior changes' subsection. Do NOT silently "
        "change semantics."
    )
    return "\n\n".join(sections)
