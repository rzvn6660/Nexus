"""Abstract base class for vector embedding providers in NEXUS."""

from abc import ABC, abstractmethod
from typing import Any


class BaseEmbeddingProvider(ABC):
    """
    Abstract interface for generating dense vector representations of business text.
    Decouples document ingestion and vector retrieval from any single embedding vendor.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the vector space (e.g. 1536)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'openai', 'local', 'mock')."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier of the active model (e.g. 'text-embedding-3-small', 'bge-m3')."""

    @property
    def version(self) -> str:
        """Version of the embedding configuration/space (default: 'v1')."""
        return "v1"

    @property
    def is_mock(self) -> bool:
        """Indicates whether this is an offline test mock provider."""
        return False

    def get_metadata(self) -> dict[str, Any]:
        """Return structured metadata identifying the active embedding space."""
        return {
            "embedding_provider": self.provider_name,
            "embedding_model": self.model_name,
            "embedding_dimension": self.dimension,
            "embedding_version": self.version,
            "is_mock": self.is_mock,
        }

    @abstractmethod
    def get_embedding(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text chunk or query."""

    @abstractmethod
    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch generate embeddings for multiple text passages."""
