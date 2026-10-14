"""Abstract base class and schemas for LLM provider implementations."""

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agents.providers.models import (
    LLMRequest,
    LLMResponse,
    ModelTier,
    TokenUsage,
)
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
    GroundedExplanation,
    IntentCategory,
    IntentResult,
)

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """
    Abstract interface for model providers in NEXUS.
    
    Decouples the LangGraph orchestration and agent layers from any single AI vendor,
    supporting OpenAI, Anthropic, Gemini, local models, and offline deterministic mocks.
    """

    @property
    def provider_name(self) -> str:
        """Identifier name of the provider."""
        return self.__class__.__name__

    def health_check(self) -> bool:
        """Check if provider is configured and operational."""
        return True

    # ------------------------------------------------------------------
    # Intelligence 2.0 Unified Methods (Phase 24)
    # ------------------------------------------------------------------

    def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Execute a vendor-agnostic text or reasoning generation request.
        
        Subclasses may override this to connect to their concrete backend.
        Default implementation provides fallback execution via legacy methods.
        """
        return LLMResponse(
            content="Base provider response",
            task_category=request.task_category,
            model_name="base-llm",
            provider_name=self.provider_name,
            tier=request.preferred_tier or ModelTier.LOW_COST,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )

    def generate_structured(
        self, request: LLMRequest, response_model: type[T]
    ) -> tuple[T, LLMResponse]:
        """
        Execute a generation request and parse/validate the output against a Pydantic model.
        """
        response = self.generate(request)
        if response.parsed_data:
            instance = response_model.model_validate(response.parsed_data)
        else:
            import json
            data = json.loads(response.content)
            instance = response_model.model_validate(data)
        return instance, response

    # ------------------------------------------------------------------
    # Agent Workflow Methods (Preserved for compatibility)
    # ------------------------------------------------------------------

    def interpret_intent(self, query: str) -> IntentResult:
        """Classify user query against all standard IntentCategory values."""
        return self.classify_intent(query, [c.value for c in IntentCategory])

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
        semantic_context: dict[str, Any] | None = None,
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

    def explain_results_structured(
        self,
        query: str,
        plan: AnalysisPlan | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        explanation_level: ExplanationLevel = ExplanationLevel.MANAGER,
        business_context: str | None = None,
        semantic_context: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        rag_evidence: list[dict[str, Any]] | None = None,
    ) -> GroundedExplanation:
        """
        Synthesize a structured, schema-validated explanation grounded in tool results.
        Default implementation delegates to explain_results and wraps in GroundedExplanation.
        """
        raw_text = self.explain_results(
            query=query,
            plan=plan,
            tool_results=tool_results or [],
            evidence=evidence or [],
            explanation_level=explanation_level,
            business_context=business_context,
        )
        tools = [r.get("tool") for r in (tool_results or []) if isinstance(r, dict) and r.get("tool")]
        return GroundedExplanation(
            narrative=raw_text,
            warnings=warnings or [],
            evidence_citations=tools,
        )
