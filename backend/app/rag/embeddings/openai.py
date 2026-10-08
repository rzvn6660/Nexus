"""OpenAI Embedding Provider implementation for production deployment."""

import logging
import time
from typing import Any

from app.core.config import settings
from app.rag.embeddings.base import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """
    OpenAI embeddings provider using the standard text-embedding-3 models.
    Hardened for production with bounded batching, exponential backoff retries,
    transient 429/5xx error handling, and structured metadata tracking.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        version: str | None = None,
        batch_size: int | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        client: Any = None,
    ) -> None:
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._model = model or settings.EMBEDDING_MODEL or "text-embedding-3-small"
        self._dim = dimension or settings.EMBEDDING_DIMENSION or 1536
        self._version = version or settings.EMBEDDING_VERSION or "v1"
        self._batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE or 64
        self._timeout_seconds = timeout_seconds or settings.EMBEDDING_TIMEOUT_SECONDS or 15.0
        self._max_retries = max_retries if max_retries is not None else settings.EMBEDDING_MAX_RETRIES

        if client is not None:
            self._client = client
        else:
            if not self._api_key:
                raise ValueError(
                    "OPENAI_API_KEY must be provided or configured in settings to use OpenAIEmbeddingProvider."
                )
            try:
                import openai
                self._client = openai.OpenAI(
                    api_key=self._api_key,
                    timeout=self._timeout_seconds,
                )
            except ImportError:
                raise ImportError(
                    "The 'openai' package is required for OpenAIEmbeddingProvider. Install via requirements.txt."
                )

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def version(self) -> str:
        return self._version

    @property
    def is_mock(self) -> bool:
        return False

    def _call_with_retry(self, input_batch: list[str]) -> list[list[float]]:
        """Execute embedding API call with bounded exponential backoff retries."""
        last_exception: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                # Prepare optional dimensions parameter for text-embedding-3 models
                kwargs: dict[str, Any] = {
                    "input": input_batch,
                    "model": self._model,
                }
                if "text-embedding-3" in self._model:
                    kwargs["dimensions"] = self._dim

                response = self._client.embeddings.create(**kwargs)
                return [d.embedding for d in response.data]
            except Exception as e:
                last_exception = e
                err_str = str(e).lower()

                # Check if error is permanent (do not retry)
                is_permanent = any(
                    term in err_str
                    for term in ["invalid_api_key", "incorrect api key", "authentication", "unauthorized", "model_not_found"]
                )
                if is_permanent:
                    logger.error("Permanent OpenAI embedding failure encountered: %s", e)
                    raise

                if attempt < self._max_retries:
                    backoff = min(1.0 * (2 ** attempt), 10.0)
                    logger.warning(
                        "Transient OpenAI embedding error (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1,
                        self._max_retries,
                        e,
                        backoff,
                    )
                    time.sleep(backoff)
                else:
                    logger.error(
                        "Exhausted %d retries for OpenAI embeddings batch of size %d: %s",
                        self._max_retries,
                        len(input_batch),
                        e,
                    )

        raise RuntimeError(
            f"OpenAI embedding generation failed after {self._max_retries} retries: {last_exception}"
        )

    def get_embedding(self, text: str) -> list[float]:
        """Fetch embedding for a single text from OpenAI API."""
        clean = text.replace("\n", " ").strip()
        if not clean:
            clean = " "
        results = self._call_with_retry([clean])
        return results[0]

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch fetch embeddings from OpenAI API with chunked batching."""
        if not texts:
            return []

        cleaned = [t.replace("\n", " ").strip() or " " for t in texts]
        all_embeddings: list[list[float]] = []

        # Slice into chunks of self._batch_size
        for i in range(0, len(cleaned), self._batch_size):
            batch = cleaned[i : i + self._batch_size]
            batch_embeddings = self._call_with_retry(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
