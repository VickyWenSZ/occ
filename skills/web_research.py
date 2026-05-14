"""
web_research — deep research on a topic by combining web_search + fetch_url
across the top 3 results. Returns assembled context for Qwen to synthesize.

Why this is a skill, not a single tool: Qwen alone tends to call web_search
once and stop. This skill forces the read-multiple-sources pattern, ensuring
the user gets a grounded answer with citations rather than the first hit.
"""
import re
from node.deliberation.skills import Skill
from node.deliberation.tools import web_search, fetch_url


_PER_SOURCE_CAP = 2500   # max chars kept per fetched page
_TOP_N = 3               # number of sources to open


class WebResearchSkill(Skill):
    name = "web_research"
    description = (
        "Perform deep web research on a topic: search the web, then open and "
        "read the top 3 most relevant pages, returning their content as "
        "grounded context. Use when the user asks for in-depth information, "
        "current events, or anything requiring multiple web sources rather "
        "than a single quick answer."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The research question or topic to investigate",
            },
        },
        "required": ["query"],
    }
    tier_min = 1

    def run(self, args: dict, ctx=None):
        query = (args or {}).get("query", "").strip()
        if not query:
            yield ("result", "web_research: missing 'query' argument.")
            return

        yield ("status", f"Searching the web: {query}...")
        search_text = web_search(query, max_results=5)
        if not search_text or "No results" in search_text:
            yield ("result", f"No web results for: {query}")
            return

        urls = re.findall(r"Source:\s*(https?://\S+)", search_text)[:_TOP_N]
        if not urls:
            yield ("result", f"web_research: search returned text but no parseable URLs.\n\n{search_text}")
            return

        sources_blocks = []
        for i, url in enumerate(urls, 1):
            yield ("status", f"Reading source {i} of {len(urls)}: {url}")
            try:
                content = fetch_url(url)
            except Exception as e:
                content = f"(failed to fetch: {e})"
            if len(content) > _PER_SOURCE_CAP:
                content = content[:_PER_SOURCE_CAP] + "\n\n[...truncated]"
            sources_blocks.append(
                f"=== Source {i} — {url} ===\n{content.strip()}"
            )

        yield ("status", "Synthesizing research...")
        yield ("result",
            f"Web research for: {query}\n\n"
            f"Search summary:\n{search_text.strip()}\n\n"
            f"Top {len(urls)} sources content:\n\n"
            + "\n\n".join(sources_blocks)
            + "\n\nWrite a structured answer to the user's question using these "
            "sources, citing each by its URL where appropriate."
        )


SKILL = WebResearchSkill()
