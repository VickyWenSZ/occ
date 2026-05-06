from pathlib import Path
import os
from node.hardware import get_profile

ROOT = Path(__file__).resolve().parent.parent.parent.parent

_profile = get_profile()


class Config:
    # Hardware profile (auto-detected at startup)
    hardware_profile: str = _profile["name"]
    detected_vram_gb: float = _profile["detected_vram_gb"]

    # Model — env override wins, otherwise hardware profile default
    model: str = os.getenv("OCC_MODEL") or _profile["model"]

    # Context windows driven by hardware profile
    num_ctx_answer: int = _profile["num_ctx_answer"]
    num_ctx_synth: int = _profile["num_ctx_synth"]

    # Retrieval budget driven by hardware profile
    retrieval_chars: int = _profile["retrieval_chars"]

    # Paths
    packs_root: Path = ROOT / "expert-packs"

    # Optional: force a single pack via env (empty = load all packs)
    pack_name: str = os.getenv("OCC_PACK", "")

    # Other
    show_deliberation: bool = os.getenv("OCC_VERBOSE", "").lower() in ("1", "true")
    port: int = int(os.getenv("OCC_PORT", "8000"))
    peers: list[str] = [p.strip() for p in os.getenv("OCC_PEERS", "").split(",") if p.strip()]
