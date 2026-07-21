"""CLI: ask questions of a folder of documents from the terminal.

    python -m ragbox.cli ask "What is the refund policy?" --docs ./my_docs
"""
from __future__ import annotations

import argparse

from .answer import answer_extractive, answer_llm
from .chunk import chunk_documents
from .index import build_index
from .ingest import load_path


def main() -> None:
    ap = argparse.ArgumentParser(prog="ragbox")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask", help="ask a question over a folder of documents")
    ask.add_argument("query")
    ask.add_argument("--docs", default="sample_docs", help="folder of .pdf/.txt/.md files")
    ask.add_argument("--k", type=int, default=4, help="passages to retrieve")
    ask.add_argument("--mode", choices=["extractive", "llm"], default="extractive")
    a = ap.parse_args()

    docs = load_path(a.docs)
    chunks = chunk_documents(docs)
    if not chunks:
        raise SystemExit(f"no supported documents found in {a.docs}")
    index = build_index(chunks)
    hits = index.search(a.query, k=a.k)
    ans = answer_llm(a.query, hits) if a.mode == "llm" else answer_extractive(a.query, hits)

    print(f"backend={index.name} chunks={len(chunks)} mode={ans.mode}\n")
    print(ans.text)
    if ans.citations:
        print("\n--- citations ---")
        for i, c in enumerate(ans.citations, 1):
            page = f" p.{c.page}" if c.page else ""
            print(f"[{i}] {c.source}{page} (score {c.score})")


if __name__ == "__main__":
    main()
