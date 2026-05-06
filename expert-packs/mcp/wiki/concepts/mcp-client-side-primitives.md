---
title: Primitive Client-side MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, client-side, sampling, elicitation, logging]
---

# Primitive Client-side MCP

MCP definisce primitive lato client che consentono al server di interagire con l'applicazione AI e l'utente.

## Sampling

Il server può richiedere una completion LLM al client tramite `sampling/createMessage`.

Scopo: delegare la generazione di testo al modello disponibile nell'applicazione host, senza includere un LLM SDK nel server MCP. Permette ai server di restare model-agnostic.

## Elicitation

Il server può richiedere informazioni aggiuntive all'utente tramite `elicitation/create`.

Scopo: raccogliere input mancanti, chiedere conferma di azioni, completare workflow interattivi.

## Logging

Il server può inviare messaggi di log al client.

Scopo: debugging, monitoraggio, osservabilità delle operazioni server.

## Schema concettuale

```
MCP Server
  -> sampling/createMessage   (richiede LLM completion)
  -> elicitation/create       (richiede input utente)
  -> log messages             (invia log al client)
MCP Client / Host
```

## Punti chiave

* Le primitive client-side invertono il flusso: è il server a fare richieste al client.
* Sampling: il server usa l'LLM del client senza dipendere da un modello specifico.
* Elicitation: raccolta input utente orchestrata dal server.
* Logging: canale di osservabilità dal server verso il client.
