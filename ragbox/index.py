"""Retrieval index with pluggable backends.

- TfidfIndex: zero heavy dependencies, surprisingly strong lexical baseline. Always available.
- EmbeddingIndex: dense semantic search via sentence-transformers, used automatically when the
  library is installed. Falls back to TF-IDF otherwise — the service always works.

Both return the same (chunk, score) shape, so everything above them is backend-agnostic.
"""
from __future__ import annotations

import numpy as np

from .chunk import Chunk


class TfidfIndex:
    name = "tfidf"

    def __init__(self, chunks: list[Chunk]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.chunks = chunks
        self.vectorizer = TfidfVectorizer(lowercase=True, stop_words="english",
                                          ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(c.text for c in chunks)

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        q = self.vectorizer.transform([query])
        scores = (self.matrix @ q.T).toarray().ravel()
        order = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in order if scores[i] > 0]


class EmbeddingIndex:
    name = "embeddings"

    def __init__(self, chunks: list[Chunk], model: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self.chunks = chunks
        self.model = SentenceTransformer(model)
        self.vectors = self.model.encode([c.text for c in chunks], normalize_embeddings=True)

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        q = self.model.encode([query], normalize_embeddings=True)[0]
        scores = self.vectors @ q
        order = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in order if scores[i] > 0.1]


def build_index(chunks: list[Chunk], prefer_embeddings: bool = True):
    """Best available backend: embeddings when installed, TF-IDF otherwise."""
    if prefer_embeddings:
        try:
            return EmbeddingIndex(chunks)
        except ImportError:
            pass
    return TfidfIndex(chunks)
