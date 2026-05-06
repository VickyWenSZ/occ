# Schema — docker pack

## Page structure
- Location: `wiki/concepts/<slug>.md`
- Slug: lowercase, hyphen-separated (e.g. `docker-compose`)

## Frontmatter fields
- `title`: human-readable concept name
- `slug`: matches filename without .md extension
- `source`: name of the raw source document
- `confidence`: high / medium / low
- `tags`: list of relevant keywords

## Writing conventions
- Dense and factual — optimized for LLM consumption, not human reading
- Use `##` subheaders for logical sections
- Use code blocks for commands, configs, examples
- End every page with a `## Key Points` section (3-5 bullets)
- Flag contradictions between sources with `> ⚠️ Conflict: ...` blockquotes

## Source tracking
All ingestion events are recorded in `log.md`.
Each page's `source:` frontmatter field traces it back to the original document.
