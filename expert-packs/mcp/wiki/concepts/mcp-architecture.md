---
title: Architettura MCP
source: mcp-introduction.md
confidence: high
tags: [mcp, architecture, client-server, host, server]
---

# Architettura MCP

MCP utilizza un'architettura client-server. Ogni componente ha una responsabilità precisa.

## Componenti principali

### MCP Host

L'host è l'applicazione AI principale che coordina le connessioni MCP.

Esempi: Claude Code, VS Code, applicazioni AI custom.

Responsabilità:
* creare client MCP
* orchestrare connessioni
* integrare strumenti e contesto nel workflow AI

### MCP Client

Il client mantiene una connessione dedicata verso un singolo MCP Server.

Caratteristiche:
* un client per ogni server
* gestione del protocollo
* gestione lifecycle e trasporto

### MCP Server

Il server espone funzionalità utilizzabili dal client.

Può pubblicare: tools, resources, prompts.

Il server è il punto di integrazione verso sistemi esterni.

## Relazione tra componenti

Ogni host crea:
```
1 MCP Client <-> 1 MCP Server
```

Questo modello isola le integrazioni e semplifica il controllo delle capability.

## Punti chiave

* MCP segue un modello client-server.
* Ogni server ha un client dedicato.
* Gli host orchestrano l'intero ecosistema MCP.
