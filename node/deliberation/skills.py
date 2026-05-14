"""
OCC skill framework — Phase 1.

A "skill" is a higher-level capability that orchestrates tools to accomplish a
task that Qwen alone wouldn't handle well in a single tool call. Examples
(future Phase 2): web_research (web_search + fetch_url ×N + synth),
document_qa, fact_check.

This module defines the contract and the registry. Individual skills live in
the top-level `skills/` directory, one file per skill, each exporting a
module-level `SKILL = MySkill()` instance. The loader scans that directory at
boot, imports each file, and collects the SKILL attributes.

Skills are exposed to Qwen as additional tools via the standard tool-use loop
in engine.py. The skill's `name` attribute is automatically prefixed with
`skill_` to avoid any collision with regular tools (web_search, read_pdf, etc.).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


SKILL_NAME_PREFIX = "skill_"


class Skill:
    """Base class for OCC skills.

    Subclass this and set the four class attributes, then implement `run`.
    Export a module-level `SKILL = MySkill()` so the loader picks it up.

    Attributes:
        name        Short identifier (lowercase, no spaces). Becomes
                    `skill_<name>` in the OpenAI tool schema exposed to Qwen.
        description One-sentence summary of what the skill does and when to
                    invoke it. Qwen reads this AND the classifier reads it
                    when deciding whether to route to this skill semantically.
                    Make it specific and use-case-driven.
        parameters  OpenAI-style JSON schema for the skill's arguments.
                    Empty dict if no arguments.
        tier_min    Minimum hardware tier required (1=micro, 4=high). Phase 1
                    does not enforce this; reserved for future routing.
    """

    name: str = ""
    description: str = ""
    parameters: dict = {"type": "object", "properties": {}, "required": []}
    tier_min: int = 1

    def schema(self) -> dict:
        """Return the OpenAI tool schema for this skill."""
        return {
            "type": "function",
            "function": {
                "name": SKILL_NAME_PREFIX + self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, args: dict, ctx=None):
        """Execute the skill with the given arguments.

        Args:
            args: parameters extracted from the user's query (or built by the
                  classifier). Keys match the `parameters` schema.
            ctx:  optional SimpleNamespace with runtime info the skill may
                  need for internal LLM calls. Fields available:
                    ctx.model      — local Ollama model name (e.g. 'qwen3.5:9b')
                    ctx.or_key     — OpenRouter API key (may be '')
                    ctx.or_model   — OpenRouter model name (may be '')
                  Skills that don't need an LLM call internally can ignore ctx.

        Return ONE of:
          - str: the final text result that goes back to Qwen as the tool
                 result. Use this for trivial skills that have nothing to
                 stream.
          - iterator of (kind, value) tuples: streams intermediate events
                 to the UI as the skill executes (multi-step skills).
                 Allowed kinds:
                    'status' — progress message shown under the badge
                               (e.g. 'Reading source 2 of 3...')
                    'result' — the FINAL text that goes back to Qwen.
                               MUST be yielded exactly once, at the end.

        Override in subclasses.
        """
        raise NotImplementedError


class SkillRegistry:
    """In-memory registry of all loaded skills, keyed by qualified name
    (`skill_<name>`)."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError(f"Skill {type(skill).__name__} has no name set.")
        qualified = SKILL_NAME_PREFIX + skill.name
        if qualified in self._skills:
            raise ValueError(f"Skill name collision: {qualified}")
        self._skills[qualified] = skill

    def get(self, qualified_name: str) -> Skill | None:
        return self._skills.get(qualified_name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def schemas(self) -> list[dict]:
        return [s.schema() for s in self._skills.values()]

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def __len__(self) -> int:
        return len(self._skills)


# Module-level singleton, populated by `load_skills_from_dir` at boot.
REGISTRY = SkillRegistry()


def load_skills_from_dir(skills_dir: Path) -> int:
    """Import every `*.py` file in `skills_dir` (skipping `_*.py` and
    `__init__.py`), look for a module-level `SKILL` attribute, and register
    its value in the global REGISTRY. Returns the count loaded.

    Errors during a single file load are swallowed (and logged) so a broken
    skill file never prevents OCC from booting.
    """
    if not skills_dir.exists() or not skills_dir.is_dir():
        return 0

    loaded = 0
    for file in sorted(skills_dir.glob("*.py")):
        if file.name.startswith("_"):
            continue
        try:
            mod_name = f"_occ_skill_{file.stem}"
            spec = importlib.util.spec_from_file_location(mod_name, file)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            skill = getattr(mod, "SKILL", None)
            if isinstance(skill, Skill):
                REGISTRY.register(skill)
                loaded += 1
            else:
                _log(f"[skills] {file.name}: no SKILL exported, skipped")
        except Exception as e:
            _log(f"[skills] {file.name}: failed to load — {e}")
    return loaded


def _log(msg: str) -> None:
    """Write to the GUI log bus when available."""
    try:
        from node.apps.gui import log_bus
        log_bus.write(msg)
    except Exception:
        pass
