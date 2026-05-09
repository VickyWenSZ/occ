#!/bin/bash
cd "$(dirname "$0")"
OS="$(uname -s)"

# If server already on 7891, just open browser
if lsof -i :7891 &>/dev/null 2>&1 || ss -ltn 2>/dev/null | grep -q ':7891'; then
    if [[ "$OS" == "Darwin" ]]; then open http://localhost:7891
    else xdg-open http://localhost:7891 2>/dev/null || python3 -m webbrowser http://localhost:7891; fi
    exit 0
fi

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
