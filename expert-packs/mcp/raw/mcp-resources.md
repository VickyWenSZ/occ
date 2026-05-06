# Source: Model Context Protocol — Resources
# URL: https://modelcontextprotocol.io/docs/concepts/resources
# Retrieved: 2026-05-01

## What are Resources

Resources are data sources MCP servers expose to provide context to language models. Examples: file contents, database schemas, API responses. Each resource is uniquely identified by a URI (RFC 3986).

Resources are **application-driven**: the host app decides how to incorporate them (not the LLM directly, unlike tools).

## Capability Declaration

```json
{"capabilities": {"resources": {"subscribe": true, "listChanged": true}}}
```
Both `subscribe` and `listChanged` are optional.

## Listing Resources — resources/list

Returns array of resource objects with: `uri`, `name`, `title` (optional), `description` (optional), `mimeType` (optional), `size` (optional).

## Reading Resources — resources/read

Request: `{"method": "resources/read", "params": {"uri": "file:///project/src/main.rs"}}`

Response contains `contents` array. Each item has `uri`, `mimeType`, and either `text` (text content) or `blob` (base64 binary).

## Resource Templates — resources/templates/list

Parameterized resources using URI templates (RFC 6570).
Example: `{"uriTemplate": "file:///{path}", "name": "Project Files"}`

## Subscriptions

Client subscribes to a specific resource URI. When resource changes, server sends:
`{"method": "notifications/resources/updated", "params": {"uri": "..."}}`
Client then re-reads the resource.

## Annotations

All resources support optional annotations:
- `audience`: `["user"]`, `["assistant"]`, or `["user", "assistant"]`
- `priority`: 0.0 (optional) to 1.0 (required)
- `lastModified`: ISO 8601 timestamp

## Common URI Schemes

- `https://`: web resources client can fetch directly
- `file://`: filesystem-like resources (may use XDG MIME types for directories)
- `git://`: git version control
- Custom schemes: must follow RFC 3986

## Error Codes

- Resource not found: `-32002`
- Internal errors: `-32603`

## Security

Servers MUST validate all resource URIs. Access controls SHOULD be implemented. Binary data MUST be properly base64-encoded.
