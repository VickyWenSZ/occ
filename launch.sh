#!/bin/bash
cd "$(dirname "$0")"
OS="$(uname -s)"

# Kill any process currently on port 7891
if [[ "$OS" == "Darwin" ]]; then
    lsof -ti TCP:7891 -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
else
    lsof -ti TCP:7891 -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || \
    fuser -k 7891/tcp 2>/dev/null || true
fi
sleep 1

# Start Ollama if not running
ollama list &>/dev/null || (ollama serve &>/dev/null & sleep 3)

# Start OCC Node
nohup python3 node/apps/gui/server.py &>/dev/null &
sleep 2

if [[ "$OS" == "Darwin" ]]; then
    open http://localhost:7891
else
    xdg-open http://localhost:7891 2>/dev/null || python3 -m webbrowser http://localhost:7891
fi
