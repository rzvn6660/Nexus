"""RAG Reranking Module."""

from app.rag.rerank.base import BaseRerankProvider
from app.rag.rerank.factory import get_rerank_provider


def __getattr__(name: str):
    if name == "LocalCrossScorerRerankProvider":
        from app.rag.rerank.providers.cross_scorer import LocalCrossScorerRerankProvider

        return LocalCrossScorerRerankProvider
    elif name == "NoOpRerankProvider":
        from app.rag.rerank.providers.noop import NoOpRerankProvider

        return NoOpRerankProvider
    elif name == "CohereRerankProvider":
        from app.rag.rerank.providers.cohere_rerank import CohereRerankProvider

        return CohereRerankProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseRerankProvider",
    "CohereRerankProvider",
    "LocalCrossScorerRerankProvider",
    "NoOpRerankProvider",
    "get_rerank_provider",
]
