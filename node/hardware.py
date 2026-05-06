"""
Hardware detection and tier selection for OCC Node.

Tiers (lowest to highest):
  micro  — CPU only        — qwen3.5:2b
  small  — 4GB  VRAM       — qwen3.5:4b
  mid    — 8GB  VRAM       — qwen3.5:9b        (8GB is minimum, 10GB+ comfortable)
  large  — 16GB VRAM       — qwen3.6:27b
  xl-32  — 32GB VRAM       — qwen3.5-122b-a10b:IQ2_M
  xl-48  — 48GB VRAM       — qwen3.5-122b-a10b:IQ3_S
  server — 64GB VRAM       — qwen3.5-122b-a10b:Q4_K_M
"""
import subprocess
import shutil
import platform
import sys
from urllib.request import urlopen
from urllib.error import URLError

# ---------------------------------------------------------------------------
# Tier definitions — ordered highest to lowest, first match wins
# ---------------------------------------------------------------------------

TIERS = [
    {
        "name": "server",
        "vram_min_gb": 64,
        "vram_comfortable_gb": 72,
        "model": "qwen3.5-122b-a10b:Q4_K_M",
        "num_ctx_answer": 131072,
        "num_ctx_synth": 131072,
        "retrieval_chars": 80_000,   # ~22K tokens, leaves 109K for history+system+response
    },
    {
        "name": "xl-48",
        "vram_min_gb": 48,
        "vram_comfortable_gb": 52,
        "model": "qwen3.5-122b-a10b:IQ3_S",
        "num_ctx_answer": 131072,
        "num_ctx_synth": 131072,
        "retrieval_chars": 80_000,
    },
    {
        "name": "xl-32",
        "vram_min_gb": 32,
        "vram_comfortable_gb": 36,
        "model": "qwen3.5-122b-a10b:IQ2_M",
        "num_ctx_answer": 65536,
        "num_ctx_synth": 65536,
        "retrieval_chars": 40_000,   # ~11K tokens, leaves 54K for history+system+response
    },
    {
        "name": "large",
        "vram_min_gb": 16,
        "vram_comfortable_gb": 20,
        "model": "qwen3.6:27b",
        "num_ctx_answer": 65536,
        "num_ctx_synth": 65536,
        "retrieval_chars": 40_000,
    },
    {
        "name": "mid",
        "vram_min_gb": 8,
        "vram_comfortable_gb": 10,
        "model": "qwen3.5:9b",
        "num_ctx_answer": 32768,
        "num_ctx_synth": 32768,
        "retrieval_chars": 16_000,   # ~4.5K tokens, leaves 28K for history+system+response
    },
    {
        "name": "small",
        "vram_min_gb": 4,
        "vram_comfortable_gb": 6,
        "model": "qwen3.5:4b",
        "num_ctx_answer": 32768,
        "num_ctx_synth": 32768,
        "retrieval_chars": 16_000,
    },
    {
        "name": "micro",
        "vram_min_gb": 0,
        "vram_comfortable_gb": 0,
        "model": "qwen3.5:2b",
        "num_ctx_answer": 32768,
        "num_ctx_synth": 32768,
        "retrieval_chars": 16_000,
    },
]

OLLAMA_URL = "http://localhost:11434"
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"


# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------

def detect_vram_gb() -> float:
    """Detect total GPU VRAM. Returns 0.0 if no GPU found."""
    vram = _detect_nvidia()
    if vram > 0:
        return vram
    vram = _detect_amd()
    if vram > 0:
        return vram
    vram = _detect_apple_silicon()
    if vram > 0:
        return vram
    return 0.0


def _detect_nvidia() -> float:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            return sum(int(l) for l in lines) / 1024
    except Exception:
        pass
    return 0.0


def _detect_amd() -> float:
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            import json
            data = json.loads(result.stdout)
            total_mb = sum(
                int(v.get("VRAM Total Memory (B)", 0)) / (1024 * 1024)
                for v in data.values() if isinstance(v, dict)
            )
            return total_mb / 1024
    except Exception:
        pass
    return 0.0


def _detect_apple_silicon() -> float:
    if platform.system() != "Darwin":
        return 0.0
    try:
        result = subprocess.run(
            ["system_profiler", "SPHardwareDataType"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "Memory:" in line:
                    parts = line.strip().split()
                    for i, p in enumerate(parts):
                        if p == "GB" and i > 0:
                            return float(parts[i - 1])
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# Tier selection
# ---------------------------------------------------------------------------

def select_tier(vram_gb: float) -> dict:
    """Return the best matching tier for the given VRAM.
    Uses a 0.5GB tolerance to handle cards reporting slightly under their nominal size.
    """
    for tier in TIERS:
        if vram_gb >= tier["vram_min_gb"] - 0.5:
            at_minimum = vram_gb < tier["vram_comfortable_gb"]
            return {**tier, "detected_vram_gb": round(vram_gb, 1), "at_minimum": at_minimum}
    # Fallback: always micro
    return {**TIERS[-1], "detected_vram_gb": 0.0, "at_minimum": False}


def get_profile(vram_gb: float | None = None) -> dict:
    """Backwards-compatible wrapper used by Config."""
    if vram_gb is None:
        vram_gb = detect_vram_gb()
    tier = select_tier(vram_gb)
    return {
        "name": tier["name"],
        "detected_vram_gb": tier["detected_vram_gb"],
        "model": tier["model"],
        "num_ctx_answer": tier["num_ctx_answer"],
        "num_ctx_synth": tier["num_ctx_synth"],
        "retrieval_chars": tier["retrieval_chars"],
    }


# ---------------------------------------------------------------------------
# Ollama management
# ---------------------------------------------------------------------------

def is_ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def is_ollama_running() -> bool:
    try:
        urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
        return True
    except (URLError, OSError):
        return False


def start_ollama() -> bool:
    """Attempt to start Ollama in background. Returns True if successful."""
    try:
        if platform.system() == "Windows":
            subprocess.Popen(
                ["ollama", "serve"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        import time
        for _ in range(10):
            time.sleep(1)
            if is_ollama_running():
                return True
        return False
    except Exception:
        return False


def install_ollama_linux() -> bool:
    """Auto-install Ollama on Linux via official install script."""
    try:
        result = subprocess.run(
            "curl -fsSL https://ollama.com/install.sh | sh",
            shell=True, timeout=120,
        )
        return result.returncode == 0
    except Exception:
        return False


def is_model_installed(model: str) -> bool:
    """Check if a model is already pulled in Ollama."""
    try:
        import ollama as _ollama
        models = _ollama.list()
        base = model.split(":")[0].lower()
        tag = model.split(":")[1].lower() if ":" in model else "latest"
        for m in models.models:
            name = m.model.lower()
            if base in name and tag in name:
                return True
        return False
    except Exception:
        return False


def pull_model_stream(model: str):
    """Pull a model from Ollama, yielding (status, completed, total) tuples."""
    import ollama as _ollama
    for progress in _ollama.pull(model, stream=True):
        status = getattr(progress, "status", "") or ""
        completed = getattr(progress, "completed", 0) or 0
        total = getattr(progress, "total", 0) or 0
        yield status, completed, total
