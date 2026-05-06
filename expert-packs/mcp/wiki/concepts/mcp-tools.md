---
title: Tools MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, tools, functions, ai-actions, execution]
---

# Tools MCP

I Tools sono funzioni eseguibili esposte dal server MCP che consentono al modello AI di eseguire operazioni concrete: query database, chiamate API, motori di ricerca, calcolatori.

## Caratteristica fondamentale

I tools sono **model-controlled**: è il modello LLM a decidere quando invocarli in autonomia.

```
LLM -> decide tool call -> MCP Client -> MCP Server -> sistema esterno
```

## Listing: tools/list

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

Risposta: array di tool objects con `name`, `title`, `description`, `inputSchema` (JSON Schema), `outputSchema` (opzionale).

## Esecuzione: tools/call

```json
{
  "jsonrpc": "2.0", "id": 2, "method": "tools/call",
  "params": {"name": "get_weather", "arguments": {"location": "Roma"}}
}
```

Risposta:
```json
{"result": {"content": [{"type": "text", "text": "..."}], "isError": false}}
```

## Notifica lista cambiata

```json
{"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
```

Il client deve richiamare `tools/list` per aggiornare.

## Tipi di contenuto nella risposta

* `text`: testo semplice
* `image`: immagine base64 + mimeType
* `audio`: audio base64 + mimeType
* `resource_link`: URI a una resource
* `resource`: resource embedded con contenuto completo

## Gestione errori

1. Protocol errors (JSON-RPC): tool sconosciuto, argomenti invalidi → `{"error": {"code": -32602, ...}}`
2. Tool execution errors (in result): `{"content": [...], "isError": true}`

## Punti chiave

* I tools sono funzioni eseguibili model-controlled.
* Ogni tool ha name, description e inputSchema obbligatori.
* Il server deve dichiarare capability `tools` nell'initialize.
* Sicurezza: validare input, rate limiting, audit log, conferma utente per operazioni sensibili.
