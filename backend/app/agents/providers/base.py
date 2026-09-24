"""Abstract base class and schemas for LLM provider implementations."""

from abc import ABC, abstractmethod
from typing import Any

from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
    IntentCategory,
    IntentResult,
)


class BaseLLMProvider(ABC):
    """
    Abstract interface for model providers in NEXUS.
    
    Decouples the LangGraph orchestration layer from any single AI vendor,
    supporting OpenAI, Anthropic, local models, and offline deterministic mocks.
    """

    @abstractmethod
    def classify_intent(
        self, query: str, supported_intents: list[str]
    ) -> IntentResult:
        """Classify the user's business query into a supported analytical intent."""

    @abstractmethod
    def create_plan(
        self,
        query: str,
        intent: IntentCategory,
        available_tools: list[dict[str, Any]],
        resolved_dates: dict[str, Any],
    ) -> AnalysisPlan:
        """Generate a structured, inspectable multi-step analytical plan."""

    @abstractmethod
    def explain_results(
        self,
        query: str,
        plan: AnalysisPlan | None,
        tool_results: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        explanation_level: ExplanationLevel,
        business_context: str | None = None,
    ) -> str:
        """
        Synthesize a grounded natural language explanation based strictly on returned tool evidence
        and verified business context. Must not hallucinate or compute arithmetic independently.
        """
