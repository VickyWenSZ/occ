"""
Hardware detection and tier selection for OCC Node.

Tiers (lowest to highest):
  micro    — CPU only        — qwen3.5:2b
  small    — 4GB  VRAM       — qwen3.5:4b
  mid      — 8GB  VRAM       — qwen3.5:9b          (Q4_K_M,  5.97 GB)
  large    — 16GB VRAM       — qwen3.5:9b-q8_0     (Q8_0,    9.53 GB)
  xl       — 24GB VRAM       — qwen3.5:9b-bf16      (BF16,   19    GB)
  server-s — 32GB VRAM       — qwen3.6:27b           (Q4_K_M, 16.8  GB)
  server-l — 80GB VRAM       — qwen3.6:27b-bf16     (BF16,   56    GB)
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
        "name": "server-l",
        "vram_min_gb": 80,
        "vram_comfortable_gb": 84,
        "model": "qwen3.6:27b-bf16",
        "num_ctx_answer": 131072,
        "num_ctx_synth": 131072,
        "retrieval_chars": 65_000,
    },
    {
        "name": "server-s",
        "vram_min_gb": 32,
        "vram_comfortable_gb": 36,
        "model": "qwen3.6:27b",
        "num_ctx_answer": 131072,
        "num_ctx_synth": 131072,
        "retrieval_chars": 65_000,
    },
    {
        "name": "xl",
        "vram_min_gb": 24,
        "vram_comfortable_gb": 28,
        "model": "qwen3.5:9b-bf16",
        "num_ctx_answer": 65536,
        "num_ctx_synth": 65536,
        "retrieval_chars": 32_000,
    },
    {
        "name": "large",
        "vram_min_gb": 16,
        "vram_comfortable_gb": 20,
        "model": "qwen3.5:9b-q8_0",
        "num_ctx_answer": 65536,
        "num_ctx_synth": 65536,
        "retrieval_chars": 32_000,
    },
    {
        "name": "mid",
        "vram_min_gb": 8,
        "vram_comfortable_gb": 10,
        "model": "qwen3.5:9b",
        # 9B Q4_K_M ≈ 6GB weights. KV cache for 16384 tokens ≈ 1.75GB → total ≈ 7.75GB, fits 8GB.
        # 32768 tokens would require ~3.5GB KV → 9.5GB → OOM on 8GB cards.
        "num_ctx_answer": 16384,
        "num_ctx_synth": 16384,
        "retrieval_chars": 12_000,
    },
    {
        "name": "small",
        "vram_min_gb": 4,
        "vram_comfortable_gb": 6,
        "model": "qwen3.5:4b",
        # 4B Q4_K_M ≈ 2.7GB weights. KV cache for 8192 tokens ≈ 0.9GB → total ≈ 3.6GB, fits 4GB.
        "num_ctx_answer": 8192,
        "num_ctx_synth": 8192,
        "retrieval_chars": 8_000,
    },
    {
        "name": "micro",
        "vram_min_gb": 0,
        "vram_comfortable_gb": 0,
        "model": "qwen3.5:2b",
        "num_ctx_answer": 8192,
        "num_ctx_synth": 8192,
        "retrieval_chars": 8_000,
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


# ---------------------------------------------------------------------------
# GPU utilization (real-time, 0-100 or None)
# ---------------------------------------------------------------------------

def get_vram_used_mb() -> int:
    """VRAM occupied by the model currently loaded in Ollama (from /api/ps)."""
    try:
        from urllib.request import urlopen
        import json as _json
        with urlopen(f"{OLLAMA_URL}/api/ps", timeout=3) as r:
            models = _json.loads(r.read()).get("models", [])
        if models:
            return max(m.get("size_vram", 0) for m in models) // (1024 * 1024)
    except Exception:
        pass
    return _estimate_vram_from_tier()


def _estimate_vram_from_tier() -> int:
    """Fallback: estimate used VRAM from detected hardware tier."""
    vram_gb = detect_vram_gb()
    tier = select_tier(vram_gb)
    # Use vram_min_gb of selected tier as a conservative estimate
    return int(tier.get("vram_min_gb", 0) * 1024)


def gpu_utilization_pct() -> int | None:
    """Return GPU utilization % (0-100) or None if hardware not supported."""
    pct = _gpu_util_nvidia()
    if pct is not None:
        return pct
    return _gpu_util_amd_linux()


def _gpu_util_nvidia() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            values = [int(l.strip()) for l in result.stdout.strip().splitlines() if l.strip().isdigit()]
            if values:
                return max(values)
    except Exception:
        pass
    return None


def _gpu_util_amd_linux() -> int | None:
    if platform.system() != "Linux":
        return None
    try:
        paths = sorted(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"))
        if paths:
            return int(paths[0].read_text().strip())
    except Exception:
        pass
    return None
