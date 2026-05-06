---
title: Prompts MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, prompts, templates, workflows, llm]
---

# Prompts MCP

I Prompts in MCP sono template riusabili per strutturare interazioni con LLM. Consentono di standardizzare workflow conversazionali o task specifici.

## Funzioni principali

* riuso di istruzioni
* standardizzazione prompt
* orchestrazione workflow AI

## Possibili utilizzi

* prompt di analisi codice
* template QA
* workflow di retrieval
* task specializzati

## Posizionamento architetturale

I prompts sono una primitive distinta:

| Primitive | Scopo                    |
|-----------|--------------------------|
| tools     | azioni operative         |
| resources | dati contestuali         |
| prompts   | strutture di interazione |

## Punti chiave

* I prompts sono template riusabili esposti dal server.
* Permettono workflow AI standardizzati e riproducibili.
* Sono una primitive nativa del protocollo MCP distinta da tools e resources.
