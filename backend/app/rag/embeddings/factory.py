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
            raise ValueError(
                "EMBEDDING_PROVIDER is configured as 'openai', but OPENAI_API_KEY is missing. "
                "Configure OPENAI_API_KEY in your environment, or explicitly set EMBEDDING_PROVIDER='mock' "
                "for offline testing."
            )
        try:
            provider = OpenAIEmbeddingProvider()
        except Exception as e:
            logger.error("Failed to initialize OpenAIEmbeddingProvider: %s", e)
            raise RuntimeError(
                f"Failed to initialize configured OpenAIEmbeddingProvider: {e}. "
                "Silent fallback to mock is prohibited in production."
            ) from e
    elif chosen == "local":
        try:
            from app.rag.embeddings.local import LocalEmbeddingProvider
            provider = LocalEmbeddingProvider()
        except Exception as e:
            logger.error("Failed to initialize LocalEmbeddingProvider: %s", e)
            raise RuntimeError(
                f"Failed to initialize configured LocalEmbeddingProvider: {e}. "
                "Silent fallback to mock is prohibited in production."
            ) from e
    elif chosen == "mock":
        provider = MockEmbeddingProvider(
            dimension=settings.EMBEDDING_DIMENSION,
            version=settings.EMBEDDING_VERSION,
        )
    else:
        raise ValueError(
            f"Unsupported EMBEDDING_PROVIDER '{chosen}'. "
            "Supported providers: 'openai', 'local', 'mock'."
        )

    if provider_name is None and not force_new:
        _embedding_provider_instance = provider

    return provider
