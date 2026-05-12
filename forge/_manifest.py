"""
manifest.yaml creation and update for OCC Forge.
Produces Hub-ready format as defined in OCC Hub spec.
"""
from pathlib import Path
from datetime import date

import yaml


def load_or_create(pack_dir: Path, pack_name: str) -> dict:
    path = pack_dir / "manifest.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {
        "name": pack_name,
        "version": "1.0.0",
        "domains": [pack_name],
        "summary": "",
        "language": "it",
        "sources": [],
        "signature": None,
        "min_node_version": "0.1.0",
    }


def add_source(manifest: dict, url: str, content_hash: str):
    sources = manifest.setdefault("sources", [])
    for s in sources:
        if s.get("url") == url:
            s["fetched"] = date.today().isoformat()
            s["hash"] = content_hash
            return
    sources.append({
        "url": url,
        "fetched": date.today().isoformat(),
        "hash": content_hash,
    })


def save(pack_dir: Path, manifest: dict):
    path = pack_dir / "manifest.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, sort_keys=False)
