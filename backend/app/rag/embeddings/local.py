"""Local and Open-Source Embedding Provider (Phase 25B Architecture).

Supports local embedding inference engines (e.g. HuggingFace Text Embeddings Inference / TEI,
Ollama, vLLM, or local ONNX runtime) for private on-premises and air-gapped deployments.
"""

import logging
from typing import Any

from app.core.config import settings
from app.rag.embeddings.base import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """
    Local / self-hosted embedding provider.
    Connects to an OpenAI-compatible local HTTP endpoint (e.g. TEI, vLLM, Ollama)
    serving multilingual models such as BAAI/bge-m3 or Qwen2.5.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        version: str | None = None,
        timeout_seconds: float | None = None,
        client: Any = None,
    ) -> None:
        self._base_url = base_url or settings.LOCAL_EMBEDDING_BASE_URL or "http://localhost:8080/v1"
        self._model = model or settings.LOCAL_EMBEDDING_MODEL or "BAAI/bge-m3"
        self._dim = dimension or settings.EMBEDDING_DIMENSION or 1024
        self._version = version or settings.EMBEDDING_VERSION or "v1"
        self._timeout_seconds = timeout_seconds or settings.EMBEDDING_TIMEOUT_SECONDS or 15.0

        if client is not None:
            self._client = client
        else:
            try:
                import openai
                # Local inference servers expose OpenAI-compatible /v1/embeddings endpoints
                self._client = openai.OpenAI(
                    base_url=self._base_url,
                    api_key="local-no-key-required",
                    timeout=self._timeout_seconds,
                )
            except ImportError:
                raise ImportError(
                    "The 'openai' package is required for LocalEmbeddingProvider to query local endpoints. "
                    "Install via requirements.txt."
                )

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def version(self) -> str:
        return self._version

    @property
    def is_mock(self) -> bool:
        return False

    def get_embedding(self, text: str) -> list[float]:
        """Fetch embedding for single text from local model service."""
        clean = text.replace("\n", " ").strip() or " "
        try:
            response = self._client.embeddings.create(
                input=[clean],
                model=self._model,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("Local embedding generation failed against %s: %s", self._base_url, e)
            raise RuntimeError(
                f"LocalEmbeddingProvider failed to connect to {self._base_url} ({self._model}): {e}"
            ) from e

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch fetch embeddings from local model service."""
        if not texts:
            return []
        cleaned = [t.replace("\n", " ").strip() or " " for t in texts]
        try:
            response = self._client.embeddings.create(
                input=cleaned,
                model=self._model,
            )
            return [d.embedding for d in response.data]
        except Exception as e:
            logger.error("Local batch embedding generation failed against %s: %s", self._base_url, e)
            raise RuntimeError(
                f"LocalEmbeddingProvider batch failed against {self._base_url} ({self._model}): {e}"
            ) from e
