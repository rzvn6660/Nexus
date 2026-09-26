"""Abstract base class for all Decision Gateway provider implementations."""

from abc import ABC, abstractmethod
from app.decisions.models import DecisionRequest, DecisionResult


class BaseDecisionProvider(ABC):
    """
    Abstract interface for decision execution engines.
    
    Decouples callers from specific model architectures (e.g. general LLMs,
    specialized structured decision models like Jev, or test mocks).
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier of the provider (e.g., 'structured_llm', 'mock')."""
        pass

    @abstractmethod
    def execute_decision(self, request: DecisionRequest) -> DecisionResult:
        """
        Execute a structured decision against the provided request.
        
        Must record latency, normalize provider-specific errors, and return
        a strictly validated DecisionResult.
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Verify provider availability and operational readiness."""
        pass
