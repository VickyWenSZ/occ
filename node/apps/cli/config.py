import json
import os
from pathlib import Path

from node.hardware import get_profile
from node.provider import BUDGET_MODEL

ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CONFIG_FILE = Path.home() / ".occ" / "config.json"


def _load_occ_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_occ_config(cfg: dict) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def save_openrouter_config(api_key: str, model: str):
    cfg = _load_occ_config()
    cfg["openrouter_api_key"] = api_key
    cfg["openrouter_model"] = model
    _save_occ_config(cfg)


def save_local_mode(enabled: bool):
    cfg = _load_occ_config()
    cfg["local_mode"] = enabled
    _save_occ_config(cfg)



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
