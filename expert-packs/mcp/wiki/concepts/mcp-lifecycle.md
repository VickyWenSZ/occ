---
title: Lifecycle MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, lifecycle, initialization, handshake, capabilities]
---

# Lifecycle MCP

MCP è un protocollo stateful che richiede lifecycle management. La sequenza di inizializzazione negozia le capability tra client e server.

## Sequenza di inizializzazione

### 1. Initialize Request (client → server)

```json
{
  "jsonrpc": "2.0", "id": 1, "method": "initialize",
  "params": {
    "protocolVersion": "2025-06-18",
    "capabilities": {"elicitation": {}},
    "clientInfo": {"name": "my-client", "version": "1.0.0"}
  }
}
```

### 2. Initialize Response (server → client)

```json
{
  "jsonrpc": "2.0", "id": 1, "result": {
    "protocolVersion": "2025-06-18",
    "capabilities": {"tools": {"listChanged": true}, "resources": {}},
    "serverInfo": {"name": "my-server", "version": "1.0.0"}
  }
}
```

### 3. Initialized Notification (client → server)

```json
{"jsonrpc": "2.0", "method": "notifications/initialized"}
```

Segnala il completamento dell'handshake. Dopo questo, inizia l'operatività normale.

## Versione protocollo attuale

`2025-06-18`

Se le versioni non sono compatibili, la connessione deve essere terminata.

## Scopo del lifecycle

1. **Negoziazione versione**: garantisce compatibilità
2. **Capability discovery**: ogni parte dichiara cosa supporta
3. **Identity exchange**: clientInfo / serverInfo per debugging

## Punti chiave

* MCP usa un handshake a 3 step: initialize → response → initialized.
* Client e server negoziano capability durante l'init.
* Dopo `notifications/initialized` inizia l'operatività normale.
* Versione corrente del protocollo: `2025-06-18`.
