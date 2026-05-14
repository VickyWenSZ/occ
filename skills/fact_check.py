"""
fact_check — verify a specific claim against web evidence.

Pipeline: web_search the claim → open top 2 results → assemble evidence →
ask Qwen to render a verdict (supports / contradicts / insufficient evidence)
with citations.
"""
import re
from node.deliberation.skills import Skill
from node.deliberation.tools import web_search, fetch_url


_PER_SOURCE_CAP = 3000
_TOP_N = 2


class FactCheckSkill(Skill):
    name = "fact_check"
    description = (
        "Verify a specific factual claim against web evidence. Searches the "
        "web for the claim, opens the top 2 sources, and gathers their "
        "content so the user can get a grounded verdict (supported / "
        "contradicted / insufficient evidence) with citations. Use when the "
        "user asks to verify, check, debunk, or confirm a specific assertion."
    )
    parameters = {
        "type": "object",
        "properties": {
            "claim": {
                "type": "string",
                "description": "The factual claim to verify, stated concisely",
            },
        },
        "required": ["claim"],
    }
    tier_min = 1

    def run(self, args: dict, ctx=None):
        claim = (args or {}).get("claim", "").strip()
        if not claim:
            yield ("result", "fact_check: missing 'claim' argument.")
            return

        yield ("status", f"Searching evidence for: {claim}...")
        search_text = web_search(claim, max_results=4)
        if not search_text or "No results" in search_text:
            yield ("result",
                f"Claim to verify: {claim}\n\n"
                "No relevant web results found. State this honestly to the user "
                "and indicate the claim cannot be verified online right now."
            )
            return

        urls = re.findall(r"Source:\s*(https?://\S+)", search_text)[:_TOP_N]
        if not urls:
            yield ("result", f"fact_check: no parseable URLs.\n\n{search_text}")
            return

        evidence_blocks = []
        for i, url in enumerate(urls, 1):
            yield ("status", f"Reading evidence {i} of {len(urls)}: {url}")
            try:
                content = fetch_url(url)
            except Exception as e:
                content = f"(failed to fetch: {e})"
            if len(content) > _PER_SOURCE_CAP:
                content = content[:_PER_SOURCE_CAP] + "\n\n[...truncated]"
            evidence_blocks.append(
                f"=== Evidence {i} — {url} ===\n{content.strip()}"
            )

        yield ("status", "Assessing claim against evidence...")
        yield ("result",
            f"Claim to verify: {claim}\n\n"
            f"Search summary:\n{search_text.strip()}\n\n"
            "Evidence gathered:\n\n"
            + "\n\n".join(evidence_blocks)
            + "\n\nNow assess the claim against this evidence. Reply with one "
            "of three verdicts — Supported, Contradicted, or Insufficient "
            "evidence — and cite the URL(s) that justify your conclusion. "
            "If the evidence only partially supports the claim, say so "
            "explicitly and explain what's missing."
        )


SKILL = FactCheckSkill()
