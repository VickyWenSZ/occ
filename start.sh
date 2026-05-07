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

# ── 3. Python dependencies ────────────────────────────────────────────────────
echo " Installing dependencies (skipped if already up to date)..."
python3 -m pip install -r node/requirements.txt -q
if [ $? -ne 0 ]; then
    echo " [!] Failed to install dependencies. Check your internet connection."
    exit 1
fi
echo " [OK] Dependencies ready."

# ── 4. Detect model ───────────────────────────────────────────────────────────
echo " Detecting hardware..."
OCC_MODEL=$(python3 -c "from node.hardware import get_profile; print(get_profile()['model'])" 2>/dev/null)
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

# ── 8. Start GUI ──────────────────────────────────────────────────────────────
echo ""
echo " Starting OCC Node..."
echo " Opening browser at http://localhost:7891"
echo ""
python3 node/apps/gui/server.py
