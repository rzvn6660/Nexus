from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.rag.retrieval.models import RetrievedChunk


class BaseRerankProvider(ABC):
    """
    Abstract base class for candidate passage rerankers.

    Reranks a list of retrieved chunks against the original user query,
    enriching each chunk with rerank_score and rerank_rank, while preserving
    all existing provenance, metadata, and embedding compatibility fields.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifier for the reranker provider (e.g. 'none', 'local', 'cohere')."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier for the specific reranking model."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int = 3,
    ) -> list[RetrievedChunk]:
        """
        Rerank candidate passages against the query.

        Args:
            query: User search query string.
            candidates: Pre-ranked candidate chunks from hybrid retrieval.
            top_k: Number of top reranked chunks to return.

        Returns:
            List of up to top_k RetrievedChunk objects sorted by rerank relevance.
        """
