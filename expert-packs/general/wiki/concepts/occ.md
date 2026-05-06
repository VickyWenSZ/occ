---
title: Open Cognitive Commons
confidence: high
updated: 2026-05-01
---

# Open Cognitive Commons (OCC)

OCC is a distributed cognitive infrastructure where each node runs a small local
language model specialized by domain. Nodes collaborate over a P2P network to
answer questions with collective intelligence that exceeds what any single model
could produce alone.

## Core idea

Instead of one giant centralized model, OCC distributes cognition across many
specialized nodes — analogous to a Mixture of Experts (MoE) architecture, but
distributed across the internet rather than inside a single model file.

## How a query is answered

1. User asks a question locally.
2. The local node classifies the domain.
3. The deliberation engine consults a committee of relevant expert nodes.
4. Each node contributes analysis from its specialized knowledge base.
5. Results are synthesized into a single coherent answer.
6. The user sees only the final answer — the deliberation is invisible.

## Expert packs

Each node is specialized via an expert pack: a structured wiki of domain knowledge
(claims, sources, concepts, procedures) maintained using the LLM Wiki pattern.
No fine-tuning required — specialization comes from structured retrieval context.

## Phase 1 (current)

Single-node deliberation: three agent roles (expert, contrarian, synthesizer)
running on the same local model. Demonstrates the deliberation pattern
before P2P networking is added.
