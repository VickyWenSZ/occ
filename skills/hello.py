"""
Canary skill — verifies the skill framework end-to-end.

Invocation: ask Qwen to "esegui la skill hello" / "run the hello skill" /
"test the skill framework". Qwen sees `skill_hello` in its tool list, calls
it, and the user gets a confirmation message back.

This skill is intentionally trivial — its purpose is to prove the plumbing
works (loader → registration → schema exposure → tool dispatch → result
return → UI display), not to do anything useful.
"""
from node.deliberation.skills import Skill


class HelloSkill(Skill):
    name = "hello"
    description = (
        "Canary skill that returns a confirmation message. Use ONLY when the "
        "user explicitly asks to test, run, or verify the 'hello skill' or "
        "the 'skill framework'. Never call autonomously."
    )
    parameters = {
        "type": "object",
        "properties": {
            "echo": {
                "type": "string",
                "description": "Optional text to echo back in the confirmation.",
            }
        },
        "required": [],
    }
    tier_min = 1

    def run(self, args: dict, ctx=None) -> str:
        echo = (args or {}).get("echo", "")
        suffix = f' You said: "{echo}".' if echo else ""
        return (
            "Hello from the OCC skill framework! "
            "Registration, schema exposure, dispatch, and result return all "
            "work end-to-end." + suffix
        )


SKILL = HelloSkill()
