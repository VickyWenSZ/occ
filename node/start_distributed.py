"""
Start distributed OCC — launches two broker agents (mcp and docker packs).
Both connect to broker.opencognitivecommons.org automatically.
Then starts the CLI in broker mode.

Usage:
    python start_distributed.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def start_broker_agent(pack: str) -> subprocess.Popen:
    model = os.getenv("OCC_MODEL", "qwen3.5:9b")
    env_patch = f'$env:OCC_PACK="{pack}"; $env:OCC_MODEL="{model}"'
    cmd = f'{env_patch}; python -m node.server.broker_agent'
    return subprocess.Popen(
        ["powershell", "-NoExit", "-Command", cmd],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


print("Starting Node B (mcp pack) — connecting to broker...")
start_broker_agent("mcp")

print("Starting Node C (docker pack) — connecting to broker...")
start_broker_agent("docker")

print("\nWaiting for nodes to connect (5s)...")
time.sleep(5)

print("Starting CLI with broker mode...\n")
subprocess.run(
    [PYTHON, "node/apps/cli/main.py"],
    cwd=str(ROOT),
    env={**os.environ, "OCC_PEERS": "broker"},
)
