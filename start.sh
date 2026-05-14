#!/bin/bash

echo ""
echo " OCC Node"
echo " ════════════════════════════"
echo ""

OS="$(uname -s)"

# ── 1. Python ─────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo " [!] Python 3 not found."
    if [[ "$OS" == "Darwin" ]]; then
        echo "     Download Python 3.11+ from: https://www.python.org/downloads"
        open https://www.python.org/downloads
    else
        echo "     Install with: sudo apt install python3 python3-pip"
        echo "     Then run this script again."
    fi
    exit 1
fi
echo " [OK] Python found."

# ── 1b. Create virtual environment if missing ─────────────────────────────────
if [ ! -f ".venv/bin/python" ] && [ ! -f ".venv/bin/python3" ]; then
    echo " Creating virtual environment .venv/ (one-time, ~10 seconds)..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo " [!] Failed to create virtual environment."
        exit 1
    fi
    echo " [OK] Virtual environment created."
    .venv/bin/python -m pip install --upgrade pip --quiet 2>/dev/null
fi
PY=".venv/bin/python"
echo " [OK] Using Python from .venv/"

# ── 2. Ollama ─────────────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo " [!] Ollama not found."
    if [[ "$OS" == "Darwin" ]]; then
        echo "     Download Ollama from: https://ollama.com/download"
        echo "     After installing, run this script again."
        open https://ollama.com/download
        exit 1
    else
        echo "     Installing Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
        if ! command -v ollama &>/dev/null; then
            echo " [!] Ollama installation failed. Install manually: https://ollama.com/download"
            exit 1
        fi
    fi
fi
echo " [OK] Ollama found."

# ── 2b. Kill any running OCC server (would lock pip-managed files) ───────────
if [[ "$OS" == "Darwin" ]]; then
    lsof -ti TCP:7891 -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
else
    lsof -ti TCP:7891 -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || \
    fuser -k 7891/tcp 2>/dev/null || true
fi
sleep 1

# ── 3. Python dependencies ────────────────────────────────────────────────────
echo " Installing dependencies (skipped if already up to date)..."
$PY -m pip install -r node/requirements.txt -q
if [ $? -ne 0 ]; then
    echo " [!] Failed to install dependencies. Check your internet connection."
    exit 1
fi
echo " [OK] Dependencies ready."

# ── 4. Detect model ───────────────────────────────────────────────────────────
echo " Detecting hardware..."
OCC_MODEL=$($PY -c "from node.hardware import get_profile; print(get_profile()['model'])" 2>/dev/null)
if [ -z "$OCC_MODEL" ]; then
    echo " [!] Could not detect hardware profile."
    exit 1
fi
echo " [OK] Model: $OCC_MODEL"

# ── 5. Start Ollama (needed for pull) ─────────────────────────────────────────
echo " Starting Ollama..."
pkill -f "ollama serve" 2>/dev/null || true
sleep 2
ollama serve &>/dev/null &
sleep 4
echo " [OK] Ollama running."

# ── 6. Pull model if needed ───────────────────────────────────────────────────
if ! ollama show "$OCC_MODEL" &>/dev/null; then
    echo " Downloading model $OCC_MODEL..."
    echo " This may take several minutes. Do not close this window."
    echo ""
    ollama pull "$OCC_MODEL"
    if [ $? -ne 0 ]; then
        echo " [!] Model download failed. Check your internet connection and try again."
        exit 1
    fi
    echo " [OK] Model downloaded."

    # ── 7. Restart Ollama so it registers the new model ──────────────────────
    echo " Restarting Ollama..."
    pkill -f "ollama serve" 2>/dev/null || true
    sleep 2
    ollama serve &>/dev/null &
    sleep 4
    echo " [OK] Ollama restarted."
else
    echo " [OK] Model already installed."
fi

# ── 7b. Pre-download Whisper model (audio transcription) ─────────────────────
echo " Pre-loading audio transcription model (Whisper base, ~140MB on first run)..."
$PY -c "from faster_whisper import WhisperModel; WhisperModel('base')" &>/dev/null
if [ $? -ne 0 ]; then
    echo " [!] Whisper preload failed (non-critical, will retry on first audio use)."
else
    echo " [OK] Whisper model ready."
fi

# ── 8. Generate icons ─────────────────────────────────────────────────────────
echo " Generating icons..."
$PY make_icons.py || echo " [!] Icon generation failed (non-critical, continuing)."

# ── 9. Create desktop shortcut ────────────────────────────────────────────────
echo " Creating desktop shortcut..."
$PY setup_shortcut.py || echo " [!] Shortcut creation failed (non-critical, continuing)."
chmod +x launch.sh 2>/dev/null || true

# ── 10. Start GUI ─────────────────────────────────────────────────────────────
echo ""
echo " Starting OCC Node..."
echo " Opening browser at http://localhost:7891"
echo ""
$PY node/apps/gui/server.py
