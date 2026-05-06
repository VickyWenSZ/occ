# Source: Model Context Protocol — Introduction
# URL: https://modelcontextprotocol.io/introduction
# Retrieved: 2026-05-01

MCP (Model Context Protocol) is an open-source standard for connecting AI applications to external systems.

Using MCP, AI applications like Claude or ChatGPT can connect to data sources (e.g. local files, databases), tools (e.g. search engines, calculators) and workflows (e.g. specialized prompts)—enabling them to access key information and perform tasks.

Think of MCP like a USB-C port for AI applications. Just as USB-C provides a standardized way to connect electronic devices, MCP provides a standardized way to connect AI applications to external systems.

## Architecture

MCP follows a client-server architecture:
- **MCP Host**: The AI application (e.g. Claude Code, VS Code) that coordinates MCP clients
- **MCP Client**: Component that maintains a dedicated connection to one MCP server
- **MCP Server**: Program that exposes tools, resources, and prompts to clients

Each MCP Host creates one MCP Client per MCP Server. Local servers use STDIO transport; remote servers use Streamable HTTP transport.

## Two Layers

**Data layer**: JSON-RPC 2.0 based protocol for client-server communication. Defines lifecycle management and core primitives (tools, resources, prompts, notifications).

**Transport layer**: Communication mechanisms. Two types:
- STDIO transport: standard input/output for local processes (no network overhead)
- Streamable HTTP transport: HTTP POST + optional Server-Sent Events for remote servers

## Three Core Primitives (Server-side)

**Tools**: Executable functions the AI can invoke (e.g. query database, call API). Model-controlled — the LLM decides when to call them.

**Resources**: Data sources providing context (e.g. file contents, DB schema). Application-driven — the host app decides how to incorporate them.

**Prompts**: Reusable templates for structuring LLM interactions.

## Client-side Primitives

**Sampling**: Server requests LLM completion from the client's AI application.
**Elicitation**: Server requests additional info from the user.
**Logging**: Server sends log messages to client.

## Lifecycle

1. Client sends `initialize` request with protocol version + capabilities
2. Server responds with its capabilities
3. Client sends `notifications/initialized`
4. Normal operation begins

Protocol version: `2025-06-18` (latest)

## Capability Negotiation Example

Client declares: `{"elicitation": {}}`
Server declares: `{"tools": {"listChanged": true}, "resources": {}}`

`listChanged: true` means server will emit notifications when tool list changes.
