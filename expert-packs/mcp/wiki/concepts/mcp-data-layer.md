---
title: Data Layer MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, json-rpc, protocol, lifecycle, primitives]
---

# Data Layer MCP

Il data layer definisce il protocollo logico usato per la comunicazione tra client e server. È basato su JSON-RPC 2.0.

## Responsabilità

Il data layer gestisce:
* lifecycle management
* primitive core del protocollo
* notifiche
* richieste e risposte RPC

## Primitive gestite

Il protocollo definisce: tools, resources, prompts, notifications.

## Esempio

```json
{
  "jsonrpc": "2.0",
  "method": "initialize",
  "params": {"protocolVersion": "2025-06-18"}
}
```

## Separazione dei livelli

| Livello         | Responsabilità       |
|-----------------|----------------------|
| Data layer      | semantica protocollo |
| Transport layer | trasmissione dati    |

Questa separazione rende il protocollo indipendente dal meccanismo di trasporto.

## Punti chiave

* Il protocollo usa JSON-RPC 2.0.
* Il data layer gestisce primitive e lifecycle.
* Trasporto e protocollo logico sono separati.
