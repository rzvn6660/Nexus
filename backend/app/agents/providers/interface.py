"""NexusLLMInterface: Unified, vendor-agnostic LLM interface for NEXUS Agent."""

from typing import Any, TypeVar
from pydantic import BaseModel

from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.models import (
    LLMRequest,
    LLMResponse,
    LLMTaskCategory,
)
from app.agents.providers.router import ModelRouter
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
    IntentCategory,
    IntentResult,
)

T = TypeVar("T", bound=BaseModel)


class NexusLLMInterface(BaseLLMProvider):
    """
    Unified LLM Interface for NEXUS Agent orchestration.
    
    Acts as the single front door for all agent nodes and analytical tasks.
    Hides all vendor-specific details (OpenAI, Anthropic, Gemini, local models)
    behind high-level business tasks and routes them through the ModelRouter.
    """

    def __init__(self, router: ModelRouter | None = None) -> None:
        self._router = router or ModelRouter()

    @property
    def router(self) -> ModelRouter:
        """Return the underlying model router."""
        return self._router

    @property
    def provider_name(self) -> str:
        return "NexusLLMInterface"

    def health_check(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Unified Generation Methods
    # ------------------------------------------------------------------

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute request routing through ModelRouter."""
        return self._router.route(request)

    def generate_structured(
        self, request: LLMRequest, response_model: type[T]
    ) -> tuple[T, LLMResponse]:
        """Execute structured output request conforming to response_model."""
        return self._router.route_structured(request, response_model)

    # ------------------------------------------------------------------
    # High-Level Task Methods
    # ------------------------------------------------------------------

    def classify_intent(
        self, query: str, supported_intents: list[str]
    ) -> IntentResult:
        """Classify query intent via task-aware routing."""
        req = LLMRequest(
            task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
            prompt=query,
            context={"supported_intents": supported_intents},
        )
        result, _ = self.generate_structured(req, IntentResult)
        return result

    def create_plan(
        self,
        query: str,
        intent: IntentCategory,
        available_tools: list[dict[str, Any]],
        resolved_dates: dict[str, Any],
    ) -> AnalysisPlan:
        """Create structured analysis plan via task-aware routing."""
        req = LLMRequest(
            task_category=LLMTaskCategory.STRUCTURED_OUTPUT,
            prompt=query,
            schema_model="AnalysisPlan",
            context={
                "intent": intent.value if hasattr(intent, "value") else str(intent),
                "available_tools": available_tools,
                "resolved_dates": resolved_dates,
            },
        )
        plan, _ = self.generate_structured(req, AnalysisPlan)
        return plan

    def explain_results(
        self,
        query: str,
        plan: AnalysisPlan | None,
        tool_results: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        explanation_level: ExplanationLevel,
        business_context: str | None = None,
    ) -> str:
        """Synthesize natural language explanation grounded in evidence."""
        req = LLMRequest(
            task_category=LLMTaskCategory.EXPLANATION,
            prompt=query,
            context={
                "tool_results": tool_results,
                "evidence": evidence,
                "explanation_level": explanation_level.value if hasattr(explanation_level, "value") else str(explanation_level),
                "business_context": business_context,
            },
        )
        response = self.generate(req)
        return response.content

    def resolve_ambiguity(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resolve ambiguous or underspecified queries into clarifying questions."""
        req = LLMRequest(
            task_category=LLMTaskCategory.AMBIGUITY_RESOLUTION,
            prompt=query,
            context=context or {},
        )
        response = self.generate(req)
        return response.parsed_data or {"content": response.content}

    def plan_sql(self, query: str, schema_info: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate read-only SQL aggregation plan without executing calculations in LLM."""
        req = LLMRequest(
            task_category=LLMTaskCategory.SQL_DATA_PLANNING,
            prompt=query,
            context={"schema_info": schema_info or {}},
        )
        response = self.generate(req)
        return response.parsed_data or {"content": response.content}

    def reason_investigation(
        self, anomaly_description: str, metrics: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Generate multi-hypothesis investigative reasoning from diagnostic metrics."""
        req = LLMRequest(
            task_category=LLMTaskCategory.COMPLEX_INVESTIGATION_REASONING,
            prompt=anomaly_description,
            context={"metrics": metrics or {}},
        )
        response = self.generate(req)
        return response.parsed_data or {"content": response.content}

    def interpret_evidence(
        self, query: str, evidence: list[dict[str, Any]], tool_results: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Synthesize objective evidence interpretation grounded in deterministic facts."""
        req = LLMRequest(
            task_category=LLMTaskCategory.EVIDENCE_INTERPRETATION,
            prompt=query,
            context={"evidence": evidence, "tool_results": tool_results or []},
        )
        response = self.generate(req)
        return response.parsed_data or {"content": response.content}
