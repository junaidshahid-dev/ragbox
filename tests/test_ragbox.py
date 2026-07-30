"""End-to-end tests: ingest -> chunk -> index -> retrieve -> answer, plus the API."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from ragbox.chunk import chunk_documents
from ragbox.index import TfidfIndex
from ragbox.ingest import Document, load_path
from ragbox.answer import answer_extractive

DOCS = [
    Document("handbook.md", None,
             "Refunds\n\nCustomers may request a full refund within 30 days of purchase. "
             "After 30 days, refunds are issued as store credit only.\n\n"
             "Shipping\n\nOrders ship within 2 business days via courier."),
    Document("faq.md", None,
             "Support hours\n\nOur support desk is open Monday to Friday, 9am to 6pm PKT.\n\n"
             "Warranty\n\nAll hardware carries a one-year limited warranty."),
]


def test_chunking_preserves_content():
    chunks = chunk_documents(DOCS, target_chars=120, overlap=20)
    assert len(chunks) >= 4
    joined = " ".join(c.text for c in chunks)
    assert "30 days" in joined and "warranty" in joined
    assert all(c.source in ("handbook.md", "faq.md") for c in chunks)


def test_retrieval_finds_right_chunk():
    chunks = chunk_documents(DOCS, target_chars=200, overlap=0)
    idx = TfidfIndex(chunks)
    hits = idx.search("request a refund for a purchase", k=2)
    assert hits, "expected at least one hit"
    assert "refund" in hits[0][0].text.lower()


@pytest.mark.xfail(reason="lexical TF-IDF cannot match pure paraphrases ('money back' shares no "
                          "terms with 'refund'); the embeddings backend handles this case",
                   strict=False)
def test_paraphrase_needs_semantic_backend():
    chunks = chunk_documents(DOCS, target_chars=200, overlap=0)
    hits = TfidfIndex(chunks).search("how do I get my money back", k=2)
    assert hits and "refund" in hits[0][0].text.lower()


def test_extractive_answer_cites_sources():
    chunks = chunk_documents(DOCS, target_chars=200, overlap=0)
    idx = TfidfIndex(chunks)
    ans = answer_extractive("what are the support hours?", idx.search("support hours", k=2))
    assert ans.citations and ans.citations[0].source == "faq.md"
    assert "9am to 6pm" in ans.text


def test_ingest_rejects_unknown_type(tmp_path):
    bad = tmp_path / "data.xyz"
    bad.write_text("hello")
    with pytest.raises(ValueError):
        load_path(bad)


def test_api_upload_and_ask(tmp_path, monkeypatch):
    """End-to-end through the authenticated API: signup -> upload -> cited answer.

    (Multi-tenant isolation and plan enforcement are covered in test_isolation.py.)
    """
    import importlib
    monkeypatch.setenv("RAGBOX_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("RAGBOX_DATA", str(tmp_path / "api_data"))
    import ragbox.api as api
    importlib.reload(api)
    client = TestClient(api.app)

    client.post("/signup", json={"email": "user@test.com", "password": "password123"})

    r = client.get("/status")
    assert r.status_code == 200 and r.json()["indexed_chunks"] == 0

    r = client.post("/ask", json={"query": "refund policy"})
    assert r.status_code == 409                       # nothing indexed yet -> clear error

    r = client.post("/upload",
                    files={"file": ("handbook.md", DOCS[0].text.encode(), "text/markdown")})
    assert r.status_code == 200 and r.json()["chunks_added"] > 0

    r = client.post("/ask", json={"query": "how do I get a refund?", "k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["citations"] and body["citations"][0]["source"] == "handbook.md"
    assert "refund" in body["text"].lower()
    assert body["usage"]["questions_used"] == 1
