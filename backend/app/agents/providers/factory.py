"""Provider factory for instantiating the active LLM provider."""


from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.mock import MockLLMProvider
from app.agents.providers.openai_provider import OpenAIProvider
from app.core.config import settings


def get_llm_provider(provider_type: str | None = None) -> BaseLLMProvider:
    """
    Return configured LLM provider instance.
    
    If in test mode (or APP_ENV == 'test'), always returns MockLLMProvider
    to guarantee zero external API calls and complete determinism.
    """
    if settings.APP_ENV == "test":
        return MockLLMProvider()

    p = (provider_type or settings.DEFAULT_LLM_PROVIDER).lower()
    if p == "mock":
        return MockLLMProvider()
    if p == "openai":
        return OpenAIProvider()

    # Default fallback
    return MockLLMProvider()
