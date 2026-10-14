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
    GroundedExplanation,
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
        from app.agents.providers.prompts import TaskPromptBuilder
        sys_prompt, user_prompt = TaskPromptBuilder.build_intent_prompt(query, supported_intents)
        req = LLMRequest(
            task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
            prompt=user_prompt,
            system_prompt=sys_prompt,
            schema_model="IntentResult",
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
        semantic_context: dict[str, Any] | None = None,
    ) -> AnalysisPlan:
        """Create structured analysis plan via task-aware routing."""
        from app.agents.providers.prompts import TaskPromptBuilder, sanitize_fallback_reason
        sys_prompt, user_prompt = TaskPromptBuilder.build_planning_prompt(
            query=query,
            intent=intent,
            available_tools=available_tools,
            resolved_dates=resolved_dates,
            semantic_context=semantic_context,
        )
        req = LLMRequest(
            task_category=LLMTaskCategory.STRUCTURED_OUTPUT,
            prompt=user_prompt,
            system_prompt=sys_prompt,
            schema_model="AnalysisPlan",
            context={
                "intent": intent.value if hasattr(intent, "value") else str(intent),
                "available_tools": available_tools,
                "resolved_dates": resolved_dates,
                "semantic_context": semantic_context,
            },
        )
        plan, resp = self.generate_structured(req, AnalysisPlan)
        if getattr(resp, "is_fallback", False):
            plan.is_fallback = True
            plan.fallback_reason = sanitize_fallback_reason(getattr(resp, "fallback_reason", None))
        else:
            plan.is_fallback = False
            plan.fallback_reason = None

        plan.llm_provider = getattr(resp, "provider_name", "live_provider")
        plan.llm_model = getattr(resp, "model_name", "live_model")

        # Independent deterministic validation of proposed tools and schemas
        if not plan.is_fallback:
            from app.agents.tools.registry import tool_registry

            is_valid_plan = True
            invalid_reason = ""
            for step in plan.steps:
                if not tool_registry.has_tool(step.tool_name):
                    is_valid_plan = False
                    invalid_reason = f"Proposed tool '{step.tool_name}' is not in registered tool catalog"
                    break
                tool = tool_registry.get_tool(step.tool_name)
                if tool:
                    try:
                        tool.input_schema.model_validate(step.arguments)
                    except Exception as ve:  # noqa: BLE001
                        is_valid_plan = False
                        invalid_reason = f"Proposed arguments for tool '{step.tool_name}' failed schema validation: {ve}"
                        break

            if not is_valid_plan:
                fallback_plan = self._router.fallback_provider.create_plan(
                    query=query,
                    intent=intent,
                    available_tools=available_tools,
                    resolved_dates=resolved_dates,
                    semantic_context=semantic_context,
                )
                fallback_plan.is_fallback = True
                fallback_plan.fallback_reason = sanitize_fallback_reason(
                    f"Malformed structured output: {invalid_reason}"
                )
                fallback_plan.llm_provider = getattr(resp, "provider_name", "live_provider")
                fallback_plan.llm_model = getattr(resp, "model_name", "live_model")
                return fallback_plan

        return plan

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
        """Synthesize structured, schema-validated GroundedExplanation."""
        from app.agents.providers.guard import DeterministicCalculationGuard
        from app.agents.providers.prompts import TaskPromptBuilder, sanitize_fallback_reason
        from app.agents.state.models import GroundedExplanation

        t_results = tool_results or []
        ev_records = evidence or []
        rag_records = rag_evidence or []
        is_plan_fallback = getattr(plan, "is_fallback", False) if plan else False
        plan_fallback_reason = getattr(plan, "fallback_reason", None) if plan else None

        is_external_allowed = self._router.is_external_allowed()

        if not is_external_allowed:
            fallback_exp = self._router.fallback_provider.explain_results_structured(
                query=query,
                plan=plan,
                tool_results=t_results,
                evidence=ev_records,
                explanation_level=explanation_level,
                business_context=business_context,
                semantic_context=semantic_context,
                warnings=warnings,
                rag_evidence=rag_records,
            )
            fallback_exp.is_fallback = True
            if not fallback_exp.fallback_reason:
                fallback_exp.fallback_reason = sanitize_fallback_reason(
                    plan_fallback_reason or "Deterministic baseline fallback activated (external calls disabled by default)."
                )
            return fallback_exp

        sys_prompt, user_prompt = TaskPromptBuilder.build_explanation_prompt(
            query=query,
            plan=plan,
            tool_results=t_results,
            evidence=ev_records,
            explanation_level=explanation_level,
            business_context=business_context,
            is_fallback=is_plan_fallback,
            fallback_reason=plan_fallback_reason,
            semantic_context=semantic_context,
            warnings=warnings,
            rag_evidence=rag_records,
        )
        req = LLMRequest(
            task_category=LLMTaskCategory.STRUCTURED_OUTPUT,
            prompt=user_prompt,
            system_prompt=sys_prompt,
            schema_model="GroundedExplanation",
            context={
                "tool_results": t_results,
                "evidence": ev_records,
                "explanation_level": explanation_level.value if hasattr(explanation_level, "value") else str(explanation_level),
                "business_context": business_context,
                "semantic_context": semantic_context,
                "warnings": warnings,
                "rag_evidence": rag_records,
            },
        )
        try:
            exp_instance, resp = self.generate_structured(req, GroundedExplanation)
            if getattr(resp, "is_fallback", False):
                fallback_exp = self._router.fallback_provider.explain_results_structured(
                    query=query,
                    plan=plan,
                    tool_results=t_results,
                    evidence=ev_records,
                    explanation_level=explanation_level,
                    business_context=business_context,
                    semantic_context=semantic_context,
                    warnings=warnings,
                    rag_evidence=rag_records,
                )
                fallback_exp.is_fallback = True
                fallback_exp.fallback_reason = sanitize_fallback_reason(getattr(resp, "fallback_reason", None))
                fallback_exp.llm_provider = getattr(resp, "provider_name", "live_provider")
                fallback_exp.llm_model = getattr(resp, "model_name", "live_model")
                return fallback_exp

            # Deterministic Grounding & Verification
            is_valid, validation_err = DeterministicCalculationGuard.validate_grounded_explanation(
                explanation=exp_instance,
                tool_results=t_results,
                evidence=ev_records,
                rag_evidence=rag_records,
                semantic_context=semantic_context,
            )
            if not is_valid:
                fallback_exp = self._router.fallback_provider.explain_results_structured(
                    query=query,
                    plan=plan,
                    tool_results=t_results,
                    evidence=ev_records,
                    explanation_level=explanation_level,
                    business_context=business_context,
                    semantic_context=semantic_context,
                    warnings=warnings,
                    rag_evidence=rag_records,
                )
                fallback_exp.is_fallback = True
                fallback_exp.fallback_reason = sanitize_fallback_reason(f"Ungrounded explanation: {validation_err}")
                fallback_exp.llm_provider = getattr(resp, "provider_name", "live_provider")
                fallback_exp.llm_model = getattr(resp, "model_name", "live_model")
                return fallback_exp

            exp_instance.is_fallback = False
            exp_instance.fallback_reason = None
            exp_instance.llm_provider = getattr(resp, "provider_name", "live_provider")
            exp_instance.llm_model = getattr(resp, "model_name", "live_model")
            return exp_instance

        except Exception as exc:  # noqa: BLE001
            fallback_exp = self._router.fallback_provider.explain_results_structured(
                query=query,
                plan=plan,
                tool_results=t_results,
                evidence=ev_records,
                explanation_level=explanation_level,
                business_context=business_context,
                semantic_context=semantic_context,
                warnings=warnings,
                rag_evidence=rag_records,
            )
            fallback_exp.is_fallback = True
            fallback_exp.fallback_reason = sanitize_fallback_reason(str(exc))
            return fallback_exp

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
        exp = self.explain_results_structured(
            query=query,
            plan=plan,
            tool_results=tool_results,
            evidence=evidence,
            explanation_level=explanation_level,
            business_context=business_context,
        )
        return exp.to_formatted_text(explanation_level)

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
        from app.agents.providers.guard import DeterministicCalculationGuard

        req = LLMRequest(
            task_category=LLMTaskCategory.SQL_DATA_PLANNING,
            prompt=query,
            context={"schema_info": schema_info or {}},
        )
        response = self.generate(req)
        plan = dict(response.parsed_data) if response.parsed_data else {"content": response.content}
        DeterministicCalculationGuard.validate_sql_plan(plan)
        return plan

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
