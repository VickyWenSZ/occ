---
title: Deliberative Intelligence
confidence: high
updated: 2026-05-01
---

# Deliberative Intelligence

OCC answers questions through structured deliberation rather than a single
model pass. Multiple agent roles each contribute a perspective, and a
synthesizer produces the final response.

## Agent roles

**Expert**: Answers the question using domain knowledge and retrieved context.
Prioritizes accuracy and completeness.

**Contrarian**: Critiques the expert answer. Looks for edge cases, missing
caveats, counterarguments, and common misconceptions. Does not simply negate —
identifies genuine gaps.

**Synthesizer**: Receives the question, expert answer, and contrarian critique.
Produces the single best answer for the user, incorporating valid points from
both perspectives. Never mentions the deliberation process.

## Why this produces better answers

A single model pass is susceptible to confident errors and missing edge cases.
The contrarian role specifically hunts for what the expert missed. The
synthesizer then produces a response that has been stress-tested against its
own weaknesses before the user sees it.

## Scaling to distributed nodes

In Phase 2+, expert and contrarian roles are fulfilled by different remote nodes
with different expert packs, different model weights, and different source sets.
This maximizes diversity and minimizes correlated errors (synchronized hallucinations).
