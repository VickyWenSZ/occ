---
title: Transport Layer MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, transport, stdio, http, networking]
---

# Transport Layer MCP

Il transport layer definisce come client e server comunicano.

MCP supporta due modalità di trasporto principali.

## STDIO Transport

Usato per server locali. Comunicazione tramite standard input/output.

Caratteristiche:
* nessun overhead di rete
* semplice da implementare
* adatto a processi locali

Caso d'uso: `AI App -> processo locale MCP Server`

## Streamable HTTP Transport

Usato per server remoti. Basato su HTTP POST + opzionalmente Server-Sent Events (SSE).

Caratteristiche:
* accesso remoto
* streaming eventi
* compatibilità web

Caso d'uso: `AI App -> rete -> MCP Server remoto`

## Differenza tra trasporti

| Trasporto       | Uso    | Tecnologia   |
|-----------------|--------|--------------|
| STDIO           | locale | stdin/stdout |
| Streamable HTTP | remoto | HTTP + SSE   |

## Punti chiave

* MCP separa protocollo logico e trasporto.
* STDIO è ottimizzato per processi locali.
* Streamable HTTP abilita integrazioni remote.
