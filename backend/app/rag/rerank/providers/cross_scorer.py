"""Deterministic, dependency-free local cross-scorer reranking provider."""

import math
import re
from collections.abc import Sequence

from app.rag.rerank.base import BaseRerankProvider
from app.rag.retrieval.models import RetrievedChunk


def _tokenize(text: str) -> list[str]:
    """Extract lowercase unicode alphanumeric and hyphenated tokens."""
    if not text:
        return []
    return [t.lower() for t in re.findall(r"[\w\-]+", text)]


def _is_code_token(token: str) -> bool:
    """Detect if token looks like a product SKU, model code, or technical ID."""
    return ("-" in token or any(c.isdigit() for c in token)) and len(token) >= 3


class LocalCrossScorerRerankProvider(BaseRerankProvider):
    """
    Deterministic cross-scorer that computes joint query-passage relevance without
    external heavyweight neural networks or paid APIs.

    Evaluates:
    - Exact contiguous phrase matching
    - Normalized token coverage / overlap
    - Alphanumeric SKU and code token exact matching
    - Title-specific token alignment
    - Term density and proximity
    - Interpolation with incoming hybrid similarity
    """

    def __init__(self, model_name: str = "local-cross-scorer-v1") -> None:
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    def _compute_score(
        self,
        query: str,
        q_tokens: Sequence[str],
        chunk: RetrievedChunk,
    ) -> float:
        content_lower = chunk.content.lower() if chunk.content else ""
        title_lower = (chunk.title or chunk.document_title or "").lower()
        full_text = f"{title_lower} {content_lower}"
        full_tokens = set(_tokenize(full_text))

        if not q_tokens:
            return 0.0

        # 1. Token Coverage (fraction of query tokens found)
        matched_tokens = [t for t in q_tokens if t in full_tokens]
        coverage = len(matched_tokens) / len(q_tokens)

        # 2. Exact Contiguous Query Match Bonus
        q_clean = query.strip().lower()
        exact_match_score = 0.0
        if len(q_clean) >= 4 and q_clean in full_text:
            exact_match_score = 1.0
        elif len(q_clean) >= 4 and q_clean in title_lower:
            exact_match_score = 1.2

        # 3. Code / SKU Token Alignment Bonus
        sku_score = 0.0
        code_tokens = [t for t in q_tokens if _is_code_token(t)]
        if code_tokens:
            matched_code_tokens = [t for t in code_tokens if t in full_tokens]
            sku_score = len(matched_code_tokens) / len(code_tokens)

        # 4. Title Alignment
        title_tokens = set(_tokenize(title_lower))
        title_match = sum(1 for t in q_tokens if t in title_tokens) / len(q_tokens)

        # 5. Term Proximity / Density in Content
        density_score = 0.0
        if len(matched_tokens) >= 2:
            positions: list[int] = []
            for t in set(matched_tokens):
                pos = content_lower.find(t)
                if pos >= 0:
                    positions.append(pos)
            if len(positions) >= 2:
                positions.sort()
                span = positions[-1] - positions[0]
                # Closer together => higher density score
                density_score = 1.0 / (1.0 + math.log1p(max(span, 1)))

        # 6. Incoming Hybrid Score Component
        base_sim = max(0.0, min(1.0, float(chunk.similarity)))

        # Composite cross-score (0.0 to 1.0+)
        cross_score = (
            0.35 * coverage
            + 0.25 * exact_match_score
            + 0.15 * sku_score
            + 0.10 * title_match
            + 0.05 * density_score
            + 0.10 * base_sim
        )
        return cross_score

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int = 3,
    ) -> list[RetrievedChunk]:
        if not candidates or not query.strip():
            return candidates[:top_k]

        q_tokens = _tokenize(query)
        scored: list[tuple[float, RetrievedChunk]] = []

        for c in candidates:
            score = self._compute_score(query, q_tokens, c)
            scored.append((score, c))

        # Deterministic tie-breaking:
        # 1. -score (descending)
        # 2. -similarity (descending)
        # 3. document_id (alphabetical ascending)
        # 4. chunk_index (sequential ascending)
        scored.sort(
            key=lambda x: (
                -x[0],
                -x[1].similarity,
                x[1].document_id,
                x[1].chunk_index if x[1].chunk_index is not None else 0,
            )
        )

        reranked_results: list[RetrievedChunk] = []
        for rank_idx, (score, orig_chunk) in enumerate(scored[:top_k], start=1):
            # Create enriched copy preserving all provenance
            chunk_copy = orig_chunk.model_copy()
            chunk_copy.rerank_score = round(score, 4)
            chunk_copy.rerank_rank = rank_idx
            reranked_results.append(chunk_copy)

        return reranked_results
