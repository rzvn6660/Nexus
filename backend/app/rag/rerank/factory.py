"""Factory for selecting and instantiating RAG rerank providers."""

import logging

from app.core.config import settings
from app.rag.rerank.base import BaseRerankProvider

logger = logging.getLogger(__name__)


def get_rerank_provider(
    provider_name: str | None = None,
    enabled: bool | None = None,
) -> BaseRerankProvider:
    """
    Instantiate the configured rerank provider.

    Reranking is optional and disabled by default (returning NoOpRerankProvider)
    unless explicitly enabled in settings or requested.
    """
    is_enabled = (
        enabled if enabled is not None else getattr(settings, "RAG_RERANK_ENABLED", False)
    )
    if not is_enabled:
        from app.rag.rerank.providers.noop import NoOpRerankProvider

        return NoOpRerankProvider()

    p_name = (
        provider_name or getattr(settings, "RAG_RERANK_PROVIDER", "local")
    ).lower()

    if p_name in ("none", "noop"):
        from app.rag.rerank.providers.noop import NoOpRerankProvider

        return NoOpRerankProvider()
    elif p_name in ("local", "cross_scorer", "cross-encoder"):
        from app.rag.rerank.providers.cross_scorer import LocalCrossScorerRerankProvider

        return LocalCrossScorerRerankProvider(
            model_name=getattr(settings, "RAG_RERANK_MODEL", "local-cross-scorer-v1")
        )
    elif p_name in ("cohere",):
        from app.rag.rerank.providers.cohere_rerank import CohereRerankProvider

        return CohereRerankProvider(
            api_key=getattr(settings, "COHERE_API_KEY", None),
            model_name=getattr(settings, "RAG_RERANK_MODEL", "rerank-v3.5"),
        )
    else:
        logger.warning(
            "Unknown RAG rerank provider '%s'; defaulting to local cross-scorer.",
            p_name,
        )
        from app.rag.rerank.providers.cross_scorer import LocalCrossScorerRerankProvider

        return LocalCrossScorerRerankProvider()
