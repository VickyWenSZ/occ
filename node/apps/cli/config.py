import json
import os
from pathlib import Path

from node import paths
from node.hardware import get_profile
from node.provider import BUDGET_MODEL

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _load_occ_config() -> dict:
    f = paths.config_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_occ_config(cfg: dict) -> None:
    f = paths.config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def save_openrouter_config(api_key: str, model: str):
    cfg = _load_occ_config()
    cfg["openrouter_api_key"] = api_key
    cfg["openrouter_model"] = model
    _save_occ_config(cfg)


def save_local_mode(enabled: bool):
    cfg = _load_occ_config()
    cfg["local_mode"] = enabled
    _save_occ_config(cfg)


def save_disabled_packs(disabled: list[str]) -> None:
    """Persist the list of pack_paths excluded from local retrieval.
    Empty list (default) means every pack is enabled. Order is not
    semantically meaningful; we sort+dedup before saving."""
    cfg = _load_occ_config()
    cfg["disabled_packs"] = sorted(set(p for p in disabled if isinstance(p, str) and p))
    _save_occ_config(cfg)


def load_disabled_packs() -> list[str]:
    """Read the persisted disabled-pack list. Tolerant to a missing or
    malformed entry — returns [] in those cases."""
    cfg = _load_occ_config()
    raw = cfg.get("disabled_packs", [])
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, str) and p]



class Config:
    def __init__(self):
        occ_cfg = _load_occ_config()
        profile = get_profile()

        self.hardware_profile: str = profile["name"]
        self.detected_vram_gb: float = profile["detected_vram_gb"]
        self.model: str = os.getenv("OCC_MODEL") or profile["model"]
        self.num_ctx_answer: int = profile["num_ctx_answer"]
        self.num_ctx_synth: int = profile["num_ctx_synth"]
        self.retrieval_chars: int = profile["retrieval_chars"]
        self.packs_root: Path = ROOT / "expert-packs"
        self.pack_name: str = os.getenv("OCC_PACK", "")
        self.show_deliberation: bool = os.getenv("OCC_VERBOSE", "").lower() in ("1", "true")
        self.port: int = int(os.getenv("OCC_PORT", "8000"))
        self.peers: list[str] = [
            p.strip() for p in os.getenv("OCC_PEERS", "").split(",") if p.strip()
        ]
        self.openrouter_api_key: str = (
            os.getenv("OCC_OPENROUTER_KEY") or occ_cfg.get("openrouter_api_key", "")
        )
        self.openrouter_model: str = (
            os.getenv("OCC_OPENROUTER_MODEL") or occ_cfg.get("openrouter_model", BUDGET_MODEL)
        )
        self.local_mode: bool = occ_cfg.get("local_mode", False)
        # Pack paths the user has explicitly disabled for local retrieval.
        # Read-once snapshot — the engine reads load_disabled_packs() per
        # query so UI toggles take effect without rebuilding the engine.
        _disabled_raw = occ_cfg.get("disabled_packs", [])
        self.disabled_packs: list[str] = (
            [p for p in _disabled_raw if isinstance(p, str) and p]
            if isinstance(_disabled_raw, list)
            else []
        )
