"""Answering layer with pluggable modes.

- extractive (default): returns the most relevant passages verbatim with citations.
  Needs NO API key — the honest baseline, and the demo always runs.
- llm: composes an answer with an LLM (Anthropic API via ANTHROPIC_API_KEY), grounded in the
  retrieved passages, with the same citations. The prompt forbids answering beyond the context —
  retrieval-grounding is the whole point of RAG.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .chunk import Chunk


@dataclass
class Citation:
    source: str
    page: int | None
    score: float
    excerpt: str


@dataclass
class Answer:
    query: str
    mode: str
    text: str
    citations: list[Citation] = field(default_factory=list)


def _citations(hits: list[tuple[Chunk, float]]) -> list[Citation]:
    return [Citation(source=c.source, page=c.page, score=round(s, 4),
                     excerpt=(c.text[:300] + "…") if len(c.text) > 300 else c.text)
            for c, s in hits]


def answer_extractive(query: str, hits: list[tuple[Chunk, float]]) -> Answer:
    if not hits:
        return Answer(query, "extractive", "No relevant passages found in the indexed documents.")
    parts = []
    for i, (chunk, _score) in enumerate(hits, start=1):
        where = f"{chunk.source}" + (f", p.{chunk.page}" if chunk.page else "")
        parts.append(f"[{i}] ({where})\n{chunk.text}")
    return Answer(query, "extractive", "\n\n".join(parts), _citations(hits))


def answer_llm(query: str, hits: list[tuple[Chunk, float]],
               model: str = "claude-sonnet-5") -> Answer:
    if not hits:
        return Answer(query, "llm", "No relevant passages found in the indexed documents.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        ans = answer_extractive(query, hits)
        ans.text = "(ANTHROPIC_API_KEY not set - extractive fallback)\n\n" + ans.text
        return ans
    import anthropic

    context = "\n\n".join(
        f"<passage id={i} source=\"{c.source}\" page=\"{c.page}\">\n{c.text}\n</passage>"
        for i, (c, _s) in enumerate(hits, start=1))
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=700,
        system=("Answer the user's question using ONLY the provided passages. Cite passages "
                "inline as [1], [2]... If the passages do not contain the answer, say so "
                "plainly - do not use outside knowledge."),
        messages=[{"role": "user",
                   "content": f"Passages:\n{context}\n\nQuestion: {query}"}])
    return Answer(query, "llm", msg.content[0].text, _citations(hits))
