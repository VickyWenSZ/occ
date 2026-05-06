"""
OCC node server — FastAPI HTTP endpoint.

Run with:
    OCC_PORT=8001 OCC_PACK=mcp python -m occ.node.server
"""
import os
from pathlib import Path

import ollama
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from node.deliberation.roles import ROLES
from node.expert_runtime.pack import ExpertPack

ROOT = Path(__file__).resolve().parent.parent.parent
_MODEL = os.getenv("OCC_MODEL", "qwen3.5:9b")
_PACK_NAME = os.getenv("OCC_PACK", "mcp")
_pack_path = ROOT / "expert-packs" / _PACK_NAME
_pack = ExpertPack(_pack_path) if _pack_path.exists() else None

app = FastAPI()


class QueryRequest(BaseModel):
    role: str
    query: str
    context: str = ""


class QueryResponse(BaseModel):
    role: str
    answer: str
    pack: str


@app.post("/query", response_model=QueryResponse)
async def handle_query(req: QueryRequest) -> QueryResponse:
    context = _pack.retrieve(req.query) if _pack else ""
    role_cfg = ROLES.get(req.role, ROLES["expert"])

    context_block = f"[Knowledge base context]\n{context}\n\n" if context else ""
    prompt = (
        f"{context_block}"
        f"Question: {req.query}\n\n"
        "Answer thoroughly using the knowledge base context."
    )

    response = ollama.chat(
        model=_MODEL,
        messages=[
            {"role": "system", "content": role_cfg["system"]},
            {"role": "user", "content": prompt},
        ],
        think=False,
        keep_alive=-1,
        options={
            "temperature": role_cfg["temperature"],
            "num_ctx": 6144,
            "stop": ["<|endoftext|>", "<|im_start|>", "<|im_end|>"],
        },
        stream=False,
    )

    answer = response.message.content or ""
    return QueryResponse(role=req.role, answer=answer, pack=_PACK_NAME)


@app.get("/manifest")
async def get_manifest() -> dict:
    import yaml
    manifest_path = _pack_path / "manifest.yaml"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            mf = yaml.safe_load(f) or {}
        return {"pack": mf.get("name", _PACK_NAME), "domains": mf.get("domains", [_PACK_NAME])}
    return {"pack": _PACK_NAME, "domains": [_PACK_NAME]}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": _MODEL, "pack": _PACK_NAME}


if __name__ == "__main__":
    port = int(os.getenv("OCC_PORT", "8000"))
    uvicorn.run("node.server.server:app", host="0.0.0.0", port=port, reload=False)
