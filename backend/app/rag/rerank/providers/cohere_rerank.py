"""Cohere Rerank API provider with resilient local fallback."""

import logging
from typing import Any

from app.core.config import settings
from app.rag.rerank.base import BaseRerankProvider
from app.rag.rerank.providers.cross_scorer import LocalCrossScorerRerankProvider
from app.rag.retrieval.models import RetrievedChunk

logger = logging.getLogger(__name__)


class CohereRerankProvider(BaseRerankProvider):
    """
    Reranks candidate chunks using Cohere Rerank API if api_key is configured.
    Falls back gracefully to LocalCrossScorerRerankProvider if API key is absent or on network errors.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "rerank-v3.5",
    ) -> None:
        self._api_key = api_key or getattr(settings, "COHERE_API_KEY", None)
        self._model_name = model_name
        self._fallback_provider = LocalCrossScorerRerankProvider()

    @property
    def provider_name(self) -> str:
        return "cohere"

    @property
    def model_name(self) -> str:
        return self._model_name

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int = 3,
    ) -> list[RetrievedChunk]:
        if not candidates or not query.strip():
            return candidates[:top_k]

        if not self._api_key:
            logger.debug(
                "Cohere API key not configured; routing to local deterministic cross-scorer."
            )
            return self._fallback_provider.rerank(query, candidates, top_k=top_k)

        try:
            import httpx

            documents = [c.content for c in candidates]
            payload: dict[str, Any] = {
                "model": self._model_name,
                "query": query,
                "documents": documents,
                "top_n": min(top_k, len(candidates)),
            }
            resp = httpx.post(
                "https://api.cohere.com/v1/rerank",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                reranked_results: list[RetrievedChunk] = []
                for item in data.get("results", []):
                    idx = item.get("index")
                    rel_score = float(item.get("relevance_score", 0.0))
                    rank_idx = len(reranked_results) + 1
                    if 0 <= idx < len(candidates):
                        chunk_copy = candidates[idx].model_copy()
                        chunk_copy.rerank_score = round(rel_score, 4)
                        chunk_copy.rerank_rank = rank_idx
                        reranked_results.append(chunk_copy)
                return reranked_results
            else:
                logger.warning(
                    "Cohere Rerank API returned HTTP %d, falling back to local cross-scorer.",
                    resp.status_code,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Cohere Rerank failed (%s), falling back to local cross-scorer.", str(exc)
            )
            return self._fallback_provider.rerank(query, candidates, top_k=top_k)
