"""Provider factory for instantiating the active LLM provider and ModelRouter."""

from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.interface import NexusLLMInterface
from app.agents.providers.mock import MockLLMProvider
from app.agents.providers.openai_provider import OpenAIProvider
from app.agents.providers.router import ModelRouter
from app.core.config import settings

_global_router: ModelRouter | None = None
_global_interface: NexusLLMInterface | None = None


def get_model_router(force_new: bool = False) -> ModelRouter:
    """Return singleton or configured ModelRouter."""
    global _global_router
    if _global_router is None or force_new:
        _global_router = ModelRouter()
    return _global_router


def get_llm_interface(force_new: bool = False) -> NexusLLMInterface:
    """Return singleton or configured NexusLLMInterface."""
    global _global_interface
    if _global_interface is None or force_new:
        router = get_model_router(force_new=force_new)
        _global_interface = NexusLLMInterface(router=router)
    return _global_interface


def get_llm_provider(provider_type: str | None = None) -> BaseLLMProvider:
    """
    Return configured LLM provider instance.
    
    If in test mode (or APP_ENV == 'test'), always returns MockLLMProvider
    to guarantee zero external API calls and complete determinism.
    
    When routing is enabled (default in Phase 24), returns NexusLLMInterface
    wrapping the ModelRouter, supporting multi-tier routing with local fallback.
    """
    if settings.APP_ENV == "test":
        # Safe default in test mode
        if provider_type == "router" or provider_type == "interface":
            return get_llm_interface()
        return MockLLMProvider()

    p = (provider_type or settings.DEFAULT_LLM_PROVIDER).lower()
    if p == "mock":
        return MockLLMProvider()
    if p in ("router", "interface"):
        return get_llm_interface()
    if p == "openai":
        return OpenAIProvider()

    # If routing is explicitly enabled in config
    if getattr(settings, "LLM_ROUTING_ENABLED", True):
        return get_llm_interface()

    # Default fallback
    return MockLLMProvider()
