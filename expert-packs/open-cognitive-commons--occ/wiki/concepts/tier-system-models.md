---
title: Tier System for Models
slug: tier-system-models
source: occ
confidence: high
tags: [qwen, ollama, vram, quantization, moe]
---

# Tier System for Models

The OCC Node selects and runs a local LLM tier based on available VRAM/compute to guarantee consistent capabilities (vision, long context, thinking mode) across heterogeneous machines. All tiers use Qwen-family models to keep API and behavior uniform.

## Design Goals

- Uniform capabilities across tiers:
  - Vision-native (early fusion) on every tier.
  - 262K token context window on every tier (no truncation).
  - Thinking mode toggle available at call-time (top-level think parameter).
- Deterministic tiering:
  - Automatic VRAM detection at startup decides which model/quant fits.
  - Auto-pull the required model if missing.
  - keep_alive = -1 on all sessions to pin the model in VRAM until explicitly unloaded.
- Operational simplicity:
  - Single family (Qwen 3.5/3.6) for coherent API and reasoning profile.
  - Consistent quantization choices per VRAM tier to balance quality vs. footprint.

## Model Family and Capabilities

- Family: Qwen 3.5 / 3.6, including MoE variants.
- Modality: Vision-native (early fusion) across all tiers.
- Context window: 262K tokens for all tiers.
- Thinking mode: On/off via top-level think flag in ollama.chat() calls (per-request control).

## Tiers and Model Specs

Each tier specifies expected VRAM, model identifier, quantization, and usage notes:

- Micro
  - VRAM: CPU (no GPU)
  - Model: qwen3.5:2b
  - Quantization: Q4_K_M
  - Notes: Runs without GPU; significantly slower. Warn users about latency.

- Small
  - VRAM: 4 GB
  - Model: qwen3.5:4b
  - Quantization: Q4_K_M

- Mid
  - VRAM: 8 GB
  - Model: qwen3.5:9b
  - Quantization: Q4_K_M
  - Notes: Default tested configuration.

- Large
  - VRAM: 16 GB
  - Model: qwen3.6:27b
  - Quantization: Q4_K_M
  - Notes: Suitable for RTX 3090/4090 24 GB class GPUs.

- XL-32
  - VRAM: 32 GB
  - Model: qwen3.5-122b-a10b (Mixture-of-Experts)
  - Quantization: IQ2_M
  - Notes: MoE with 122B total parameters, ~10B active at inference.

- XL-48
  - VRAM: 48 GB
  - Model: qwen3.5-122b-a10b (Mixture-of-Experts)
  - Quantization: IQ3_S

- Server
  - VRAM: 64 GB+
  - Model: qwen3.5-122b-a10b (Mixture-of-Experts)
  - Quantization: Q4_K_M
  - Notes: Quality approaches near full-precision behavior.

Quantization notes:
- Q4_K_M: 4-bit K-quants (balanced quality/VRAM).
- IQ2_M / IQ3_S: ultra-low-bit mixed quantization variants for MoE that trade VRAM for quality differently.
- a10b in model name indicates ~10B active parameters per token step in the MoE.

## Automatic Tier Selection

- Hardware detection:
  - On node startup, VRAM is detected (hardware.py) and matched to the highest viable tier.
  - If no compatible GPU is found or VRAM is insufficient, Micro (CPU) is selected.
- Model provisioning:
  - If the selected tier’s model is not present locally, the node pulls it automatically.
  - keep_alive is set to -1 for all inference calls to keep the model resident in VRAM for the duration of the session.
- Runtime management:
  - CLI /unload frees VRAM (unload model from Ollama).
  - CLI /load reloads the selected model into VRAM.

Example selection logic (conceptual):

```python
def select_tier(vram_gb: float, has_gpu: bool) -> dict:
    if not has_gpu or vram_gb < 4:
        return {"tier": "micro", "model": "qwen3.5:2b", "quant": "Q4_K_M"}
    if vram_gb < 8:
        return {"tier": "small", "model": "qwen3.5:4b", "quant": "Q4_K_M"}
    if vram_gb < 16:
        return {"tier": "mid", "model": "qwen3.5:9b", "quant": "Q4_K_M"}
    if vram_gb < 32:
        return {"tier": "large", "model": "qwen3.6:27b", "quant": "Q4_K_M"}
    if vram_gb < 48:
        return {"tier": "xl-32", "model": "qwen3.5-122b-a10b", "quant": "IQ2_M"}
    if vram_gb < 64:
        return {"tier": "xl-48", "model": "qwen3.5-122b-a10b", "quant": "IQ3_S"}
    return {"tier": "server", "model": "qwen3.5-122b-a10b", "quant": "Q4_K_M"}
```

Notes:
- Exact Ollama tag strings may differ; OCC’s hardware.py maintains the authoritative mapping.
- When in doubt, choose the lower tier to avoid OOM; memory fragmentation and concurrent GPU workloads can reduce effective VRAM.

## Invocation and Runtime Behavior

- Inference backend: Ollama + Qwen models (local).
- API: ollama Python SDK (local inference).
- Session residency: keep_alive = -1 pins the model to VRAM to avoid repeated cold loads.
- Thinking mode:
  - Enabled/disabled per request via the think parameter at the top level of ollama.chat().
  - Use think=False for standard decoding; set think=True where chain-of-thought style internal reasoning is desired (implementation-dependent).

Example (Python) using Ollama SDK:

```python
from ollama import Client

client = Client()

# Assume selected contains {"model": "..."} as returned by select_tier()
model_id = selected["model"]

# Pin model in VRAM for the session and run a chat turn
resp = client.chat(
    model=model_id,
    messages=[
        {"role": "system", "content": "You are OCC Node answering with technical precision."},
        {"role": "user", "content": "Explain Docker image layers briefly."},
    ],
    keep_alive=-1,  # keep model resident
    think=False,    # toggle thinking mode here
)

print(resp["message"]["content"])
```

Vision input (early fusion) is supported across all tiers (pass images per Ollama’s multimodal message schema).

## Operational Guidance

- Performance expectations:
  - CPU-only (Micro) is functional but slow; recommend at least 8 GB VRAM (Mid) for smooth UX.
  - Large (27B Q4_K_M) is viable on 24 GB consumer GPUs (e.g., 3090/4090) with headroom for tools and OS.
- Default:
  - Mid (9B Q4_K_M) is the default tested tier and balances latency and quality well for most nodes.
- Model lifecycle:
  - Auto-pull on first use; subsequent sessions reuse the cached artifacts.
  - Use /unload to reclaim VRAM when switching workloads; /load to re-prime the model.

## Compatibility and Uniformity

- Single-family strategy (Qwen) ensures:
  - Consistent tokenization and API surface across tiers.
  - Homogeneous support for vision, long context, and thinking mode.
- Uniform context window (262K) means the same retrieval and deliberation prompts work identically on all tiers—no per-tier prompt truncation logic is needed.

## Key Points

- All tiers use Qwen models with vision-native early fusion, 262K context, and a per-call thinking mode toggle.
- Tier selection is automatic based on VRAM; models are auto-pulled and pinned in VRAM with keep_alive = -1.
- Quantizations are chosen per tier (Q4_K_M, IQ2_M, IQ3_S) to balance quality and footprint; MoE variants activate ~10B parameters.
- Mid (qwen3.5:9b Q4_K_M, 8 GB) is the tested default; Large (qwen3.6:27b Q4_K_M) targets 16 GB+ VRAM (e.g., 24 GB GPUs).
- CLI controls (/unload, /load) manage model residency; hardware.py centralizes tier detection and model mapping.