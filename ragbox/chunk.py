"""Chunking: split documents into overlapping passages sized for retrieval.

Splits on paragraph boundaries first (semantic units), then packs paragraphs into
chunks of ~`target_chars` with `overlap` characters of context carried between
consecutive chunks so answers spanning a boundary aren't lost.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ingest import Document


@dataclass
class Chunk:
    chunk_id: int
    source: str
    page: int | None
    text: str


def chunk_documents(docs: list[Document], target_chars: int = 1200,
                    overlap: int = 150) -> list[Chunk]:
    chunks: list[Chunk] = []
    cid = 0
    for doc in docs:
        paras = [p.strip() for p in doc.text.split("\n\n") if p.strip()]
        if not paras:
            continue
        buf = ""
        for para in paras:
            if buf and len(buf) + len(para) + 2 > target_chars:
                chunks.append(Chunk(cid, doc.source, doc.page, buf.strip()))
                cid += 1
                buf = buf[-overlap:] if overlap else ""
            buf = (buf + "\n\n" + para) if buf else para
            # a single paragraph longer than target gets hard-split
            while len(buf) > target_chars * 2:
                chunks.append(Chunk(cid, doc.source, doc.page, buf[:target_chars].strip()))
                cid += 1
                buf = buf[target_chars - overlap:]
        if buf.strip():
            chunks.append(Chunk(cid, doc.source, doc.page, buf.strip()))
            cid += 1
    return chunks
