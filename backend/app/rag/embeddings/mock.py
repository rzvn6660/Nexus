"""Deterministic, offline Mock Embedding Provider for NEXUS CI and test suites."""

import hashlib
import math
import re

from app.rag.embeddings.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic offline embedding provider.
    
    Generates 1536-dimensional L2-normalized vectors using token and character
    n-gram feature hashing with SHA-256. Guaranteed to:
    1. Produce identical embeddings for identical text.
    2. Exhibit higher cosine similarity for semantically overlapping phrases.
    3. Require zero external API keys or network calls.
    """

    def __init__(self, dimension: int = 1536) -> None:
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def _hash_token(self, token: str, seed: int = 0) -> int:
        """Produce a deterministic 32-bit integer hash from token string."""
        raw = f"{seed}:{token}".encode()
        return int(hashlib.sha256(raw).hexdigest()[:8], 16)

    def get_embedding(self, text: str) -> list[float]:
        """Generate a deterministic 1536-dim unit vector for a given text."""
        vec = [0.0] * self._dim
        clean = text.lower().strip()
        if not clean:
            # Return canonical unit vector along first dimension
            vec[0] = 1.0
            return vec

        # Tokenize into words
        tokens = re.findall(r"\b\w+\b", clean)
        if not tokens:
            tokens = [clean]

        # Populate sparse buckets using multi-hash projection
        for token in tokens:
            for seed in range(3):
                h = self._hash_token(token, seed=seed)
                idx = h % self._dim
                sign = 1.0 if (h // self._dim) % 2 == 0 else -1.0
                vec[idx] += sign

        # Add 3-character character n-grams for subword similarity
        for i in range(len(clean) - 2):
            trigram = clean[i : i + 3]
            h = self._hash_token(trigram, seed=7)
            idx = h % self._dim
            sign = 0.5 if (h // self._dim) % 2 == 0 else -0.5
            vec[idx] += sign

        # Compute L2 norm and normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]
        else:
            vec[0] = 1.0

        return [round(x, 6) for x in vec]

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch process texts deterministically."""
        return [self.get_embedding(t) for t in texts]
