# Source: Model Context Protocol — Tools
# URL: https://modelcontextprotocol.io/docs/concepts/tools
# Retrieved: 2026-05-01

## What are Tools

Tools are executable functions exposed by MCP servers that language models can invoke. They enable models to interact with external systems: querying databases, calling APIs, performing computations.

Each tool is uniquely identified by a name and includes metadata describing its schema.

Tools are **model-controlled**: the LLM discovers and invokes them automatically based on context. Always keep a human in the loop for sensitive operations.

## Capability Declaration

Server must declare tools capability:
```json
{"capabilities": {"tools": {"listChanged": true}}}
```

## Listing Tools — tools/list

Request:
```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"cursor": "optional"}}
```

Response:
```json
{
  "result": {
    "tools": [{
      "name": "get_weather",
      "title": "Weather Information Provider",
      "description": "Get current weather for a location",
      "inputSchema": {
        "type": "object",
        "properties": {"location": {"type": "string", "description": "City or zip"}},
        "required": ["location"]
      }
    }],
    "nextCursor": "next-page-cursor"
  }
}
```

## Calling Tools — tools/call

Request:
```json
{
  "jsonrpc": "2.0", "id": 2, "method": "tools/call",
  "params": {"name": "get_weather", "arguments": {"location": "New York"}}
}
```

Response:
```json
{
  "result": {
    "content": [{"type": "text", "text": "Temperature: 72°F, Partly cloudy"}],
    "isError": false
  }
}
```

## Tool Definition Fields

- `name`: unique identifier (required)
- `title`: human-readable display name (optional)
- `description`: what the tool does (required for LLM to use it correctly)
- `inputSchema`: JSON Schema for parameters (required)
- `outputSchema`: JSON Schema for structured output (optional)
- `annotations`: metadata about behavior (untrusted unless from trusted server)

## Error Handling

Two mechanisms:
1. Protocol errors (JSON-RPC errors): unknown tool, invalid arguments
   ```json
   {"error": {"code": -32602, "message": "Unknown tool: invalid_tool_name"}}
   ```

2. Tool execution errors (in result with isError: true):
   ```json
   {"result": {"content": [{"type": "text", "text": "API rate limit exceeded"}], "isError": true}}
   ```

## Tool Result Content Types

- `text`: plain text
- `image`: base64 image data + mimeType
- `audio`: base64 audio data + mimeType
- `resource_link`: URI pointing to a resource
- `resource`: embedded resource with full content

## Structured Content (outputSchema)

If tool declares outputSchema, structured results go in `structuredContent` field alongside text content. Clients SHOULD validate against schema.

## List Changed Notification

When tool list changes, server sends:
```json
{"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
```
Client should then re-call tools/list to refresh.

## Security

Servers MUST: validate inputs, implement access controls, rate limit, sanitize outputs.
Clients SHOULD: confirm sensitive operations with user, show tool inputs before calling, implement timeouts, log usage.
