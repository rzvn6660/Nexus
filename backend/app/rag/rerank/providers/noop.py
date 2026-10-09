from __future__ import annotations

from typing import TYPE_CHECKING

from app.rag.rerank.base import BaseRerankProvider

if TYPE_CHECKING:
    from app.rag.retrieval.models import RetrievedChunk


class NoOpRerankProvider(BaseRerankProvider):
    """
    Default passthrough reranker when reranking is disabled or not applicable.
    Leaves candidate ordering and scores untouched.
    """

    @property
    def provider_name(self) -> str:
        return "none"

    @property
    def model_name(self) -> str:
        return "noop-passthrough"

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int = 3,
    ) -> list[RetrievedChunk]:
        return candidates[:top_k]
