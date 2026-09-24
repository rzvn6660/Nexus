"""Abstract base class for vector embedding providers in NEXUS."""

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """
    Abstract interface for generating dense vector representations of business text.
    Decouples document ingestion and vector retrieval from any single embedding vendor.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the vector space (e.g. 1536)."""

    @abstractmethod
    def get_embedding(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text chunk or query."""

    @abstractmethod
    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch generate embeddings for multiple text passages."""
