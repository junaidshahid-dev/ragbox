"""FastAPI service: upload documents, ask questions, get cited answers.

Run:  uvicorn ragbox.api:app --reload
Docs: http://127.0.0.1:8000/docs  (interactive OpenAPI UI, free with FastAPI)
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from .answer import answer_extractive, answer_llm
from .chunk import chunk_documents
from .index import build_index
from .ingest import SUPPORTED, load_path

app = FastAPI(title="ragbox", description="Document Q&A with citations (RAG)", version="1.0.0")

DOCS_DIR = Path(os.environ.get("RAGBOX_DOCS", "sample_docs"))
_state: dict = {"index": None, "n_chunks": 0, "sources": []}


class AskRequest(BaseModel):
    query: str
    k: int = 4
    mode: str = "extractive"          # "extractive" | "llm"


def _rebuild() -> None:
    docs = load_path(DOCS_DIR) if DOCS_DIR.exists() else []
    chunks = chunk_documents(docs)
    _state["index"] = build_index(chunks) if chunks else None
    _state["n_chunks"] = len(chunks)
    _state["sources"] = sorted({d.source for d in docs})


@app.on_event("startup")
def startup() -> None:
    _rebuild()


@app.get("/status")
def status() -> dict:
    idx = _state["index"]
    return {"indexed_chunks": _state["n_chunks"], "sources": _state["sources"],
            "retrieval_backend": idx.name if idx else None}


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(400, f"unsupported type {suffix}; supported: {sorted(SUPPORTED)}")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # sanitize: keep the base name only, never a client-supplied path
    safe_name = Path(file.filename).name
    dest = DOCS_DIR / safe_name
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
    shutil.move(tmp.name, dest)
    _rebuild()
    return {"stored": safe_name, "indexed_chunks": _state["n_chunks"]}


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    if _state["index"] is None:
        raise HTTPException(409, "no documents indexed yet - POST a file to /upload first")
    hits = _state["index"].search(req.query, k=req.k)
    ans = answer_llm(req.query, hits) if req.mode == "llm" else answer_extractive(req.query, hits)
    return asdict(ans)
