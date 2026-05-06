---
title: Capability Negotiation MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, capabilities, negotiation, listChanged, features]
---

# Capability Negotiation MCP

Durante l'inizializzazione, client e server dichiarano le rispettive capability. Consente compatibilità dinamica tra implementazioni diverse.

## Capability client (esempio)

```json
{"elicitation": {}}
```

Il client dichiara supporto per ricevere richieste di input utente dal server.

## Capability server (esempio)

```json
{
  "tools": {"listChanged": true},
  "resources": {}
}
```

* `tools` con `listChanged: true` → il server emetterà `notifications/tools/list_changed` quando la lista cambia
* `resources: {}` → supporta resources/list e resources/read

## Pattern generale

Ogni primitive (tools, resources, prompts) può avere flag opzionali:
* `listChanged`: il server notifica quando la lista cambia
* `subscribe` (solo resources): il client può sottoscriversi a resource specifiche

## Benefici

* compatibilità forward/backward tra versioni
* feature discovery senza errori
* adattamento dinamico delle capability
* riduzione accoppiamento tra implementazioni

## Punti chiave

* La negoziazione avviene nell'initialize exchange.
* Entrambe le parti dichiarano solo ciò che supportano realmente.
* `listChanged: true` abilita notifiche push sui cambiamenti.
* Se una capability non è dichiarata, non va usata.
