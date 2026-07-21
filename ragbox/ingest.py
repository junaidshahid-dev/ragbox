"""Document ingestion: turn files (.pdf, .txt, .md) into clean text with source metadata."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {".pdf", ".txt", ".md"}


@dataclass
class Document:
    source: str          # file name
    page: int | None     # 1-based page for PDFs, None for text files
    text: str


def _read_pdf(path: Path) -> list[Document]:
    import fitz  # PyMuPDF

    docs = []
    with fitz.open(path) as pdf:
        for i, page in enumerate(pdf, start=1):
            text = page.get_text("text").strip()
            if text:
                docs.append(Document(source=path.name, page=i, text=text))
    return docs


def _read_text(path: Path) -> list[Document]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return [Document(source=path.name, page=None, text=text)] if text else []


def load_path(path: str | Path) -> list[Document]:
    """Load a file or every supported file in a directory (recursive)."""
    path = Path(path)
    if path.is_dir():
        docs = []
        for p in sorted(path.rglob("*")):
            if p.suffix.lower() in SUPPORTED and p.is_file():
                docs.extend(load_path(p))
        return docs
    if path.suffix.lower() == ".pdf":
        return _read_pdf(path)
    if path.suffix.lower() in SUPPORTED:
        return _read_text(path)
    raise ValueError(f"unsupported file type: {path.suffix} ({path})")
