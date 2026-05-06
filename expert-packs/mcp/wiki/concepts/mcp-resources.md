---
title: Resources MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, resources, context, data, uri]
---

# Resources MCP

Le Resources sono fonti dati esposte dal server MCP per fornire contesto al modello AI. Esempi: contenuti file, schema database, documentazione. Ogni resource è identificata da una URI (RFC 3986).

Le resources sono **application-driven**: l'host decide come incorporarle nel contesto (non l'LLM direttamente).

## Differenza rispetto ai Tools

| Resources           | Tools            |
|---------------------|------------------|
| forniscono contesto | eseguono azioni  |
| dati                | funzioni         |
| host-controlled     | model-controlled |

## Capability

```json
{"capabilities": {"resources": {"subscribe": true, "listChanged": true}}}
```

## Listing: resources/list

Ritorna array con: `uri`, `name`, `title`, `description`, `mimeType`, `size`.

## Lettura: resources/read

```json
{"method": "resources/read", "params": {"uri": "file:///project/main.py"}}
```

Risposta: `contents` array con `uri`, `mimeType` e `text` (testo) o `blob` (base64 binario).

## Resource Templates

URI parametrizzate (RFC 6570): `{"uriTemplate": "file:///{path}", "name": "Project Files"}`

## Subscriptions

Il client si iscrive a una URI. Quando la resource cambia il server invia:
`notifications/resources/updated` → il client rilege la resource.

## Annotazioni

* `audience`: `["user"]`, `["assistant"]`, o entrambi
* `priority`: 0.0 (opzionale) → 1.0 (essenziale)
* `lastModified`: timestamp ISO 8601

## URI Schemes standard

* `https://`: resource web che il client può fetchare direttamente
* `file://`: filesystem (può usare XDG MIME per directory)
* `git://`: version control
* Custom: devono seguire RFC 3986

## Punti chiave

* Resources = dati contestuali, non azioni.
* Identificate da URI univoche.
* Supportano subscription per aggiornamenti real-time.
* Error code: -32002 (not found), -32603 (internal).
