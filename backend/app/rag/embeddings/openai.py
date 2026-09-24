"""OpenAI Embedding Provider implementation for production deployment."""


from app.core.config import settings
from app.rag.embeddings.base import BaseEmbeddingProvider


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """
    OpenAI embeddings provider using the standard text-embedding-3 models.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
    ) -> None:
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._model = model or settings.EMBEDDING_MODEL or "text-embedding-3-small"
        self._dim = dimension or settings.EMBEDDING_DIMENSION or 1536

        if not self._api_key:
            raise ValueError(
                "OPENAI_API_KEY must be provided or configured in settings to use OpenAIEmbeddingProvider."
            )

        try:
            import openai
            self._client = openai.OpenAI(api_key=self._api_key)
        except ImportError:
            raise ImportError(
                "The 'openai' package is required for OpenAIEmbeddingProvider. Install via requirements.txt."
            )

    @property
    def dimension(self) -> int:
        return self._dim

    def get_embedding(self, text: str) -> list[float]:
        """Fetch embedding for a single text from OpenAI API."""
        clean = text.replace("\n", " ")
        response = self._client.embeddings.create(
            input=[clean],
            model=self._model,
        )
        return response.data[0].embedding

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Batch fetch embeddings from OpenAI API."""
        cleaned = [t.replace("\n", " ") for t in texts]
        response = self._client.embeddings.create(
            input=cleaned,
            model=self._model,
        )
        return [d.embedding for d in response.data]
