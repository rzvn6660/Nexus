"""Factory function for instantiating embedding providers based on environment configuration."""

import logging

from app.core.config import settings
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.mock import MockEmbeddingProvider
from app.rag.embeddings.openai import OpenAIEmbeddingProvider

logger = logging.getLogger(__name__)

# Global cached provider instance
_embedding_provider_instance: BaseEmbeddingProvider | None = None


def get_embedding_provider(
    provider_name: str | None = None,
    force_new: bool = False,
) -> BaseEmbeddingProvider:
    """
    Retrieve configured embedding provider. Defaults to MockEmbeddingProvider for offline CI.
    """
    global _embedding_provider_instance
    if _embedding_provider_instance is not None and not force_new and provider_name is None:
        return _embedding_provider_instance

    chosen = (provider_name or settings.EMBEDDING_PROVIDER or "mock").lower()

    if chosen == "openai":
        if not settings.OPENAI_API_KEY:
            logger.warning(
                "OPENAI_API_KEY is not set. Falling back to MockEmbeddingProvider for safe execution."
            )
            provider = MockEmbeddingProvider(dimension=settings.EMBEDDING_DIMENSION)
        else:
            try:
                provider = OpenAIEmbeddingProvider()
            except (ImportError, ValueError, RuntimeError, OSError) as e:
                logger.error(f"Failed to initialize OpenAIEmbeddingProvider: {e}. Falling back to mock.")
                provider = MockEmbeddingProvider(dimension=settings.EMBEDDING_DIMENSION)
    elif chosen == "mock":
        provider = MockEmbeddingProvider(dimension=settings.EMBEDDING_DIMENSION)
    else:
        logger.warning(f"Unknown embedding provider '{chosen}', defaulting to MockEmbeddingProvider.")
        provider = MockEmbeddingProvider(dimension=settings.EMBEDDING_DIMENSION)

    if provider_name is None and not force_new:
        _embedding_provider_instance = provider

    return provider
