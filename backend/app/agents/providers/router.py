"""ModelRouter: Free-First, Capability-Based Model Routing and Intelligent Escalation."""

import logging
import time
from typing import Any, TypeVar
from pydantic import BaseModel

from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.guard import DeterministicCalculationGuard
from app.agents.providers.mock import MockLLMProvider
from app.agents.providers.models import (
    IntelligenceLane,
    LLMProviderError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
    LLMRequest,
    LLMResponse,
    LLMTaskCategory,
    MalformedLLMResponseError,
    ModelCapability,
    ModelTier,
    PricingCatalog,
    ProviderCandidateSpec,
    TokenUsage,
    UnsupportedLLMTaskError,
)
from app.agents.providers.registry import ProviderCandidateRegistry, get_candidate_registry
from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ModelRouter:
    """
    Free-First + Quota-Efficient + Capability-Based Model Router for NEXUS Intelligence 2.0.
    
    Product Strategy:
    - Minimizes recurring LLM cost and avoids exhausting small free-tier quotas.
    - Does NOT hard-code a single permanent winner provider.
    - Routes requests across 3 Intelligence Lanes:
        * Lane 1: Free / High-Volume (Intent, simple Q&A, basic tools, simple explanations)
        * Lane 2: Strong / Escalation (Complex investigations, SQL planning, deep reasoning, evidence synthesis)
        * Lane 3: Local / Fallback (Offline dev, testing, provider outages, privacy isolation)
    - Selects models dynamically via capability matching:
        Task Requirements → Capability Compatibility → Availability → Remaining Quota → Cost → Latency.
    - The cheapest capable model normally wins.
    - Enforces the strict rule: Deterministic calculations bypass the LLM and execute via SQL/Python/stats.
    """

    # Default capability requirements per task category
    TASK_CAPABILITY_REQUIREMENTS: dict[LLMTaskCategory, set[ModelCapability]] = {
        LLMTaskCategory.INTENT_UNDERSTANDING: {ModelCapability.LOW_COST},
        LLMTaskCategory.STRUCTURED_OUTPUT: {ModelCapability.STRUCTURED_OUTPUT},
        LLMTaskCategory.TOOL_SELECTION: {ModelCapability.TOOL_CALLING},
        LLMTaskCategory.SQL_DATA_PLANNING: {ModelCapability.SQL_PLANNING, ModelCapability.STRUCTURED_OUTPUT},
        LLMTaskCategory.AMBIGUITY_RESOLUTION: {ModelCapability.AMBIGUITY_RESOLUTION},
        LLMTaskCategory.COMPLEX_INVESTIGATION_REASONING: {ModelCapability.BUSINESS_REASONING, ModelCapability.REASONING},
        LLMTaskCategory.EXPLANATION: {ModelCapability.STRUCTURED_OUTPUT},
        LLMTaskCategory.EVIDENCE_INTERPRETATION: {ModelCapability.EVIDENCE_INTERPRETATION},
    }

    # Default task category to Intelligence Lane mappings
    TASK_LANE_MAPPING: dict[LLMTaskCategory, IntelligenceLane] = {
        LLMTaskCategory.INTENT_UNDERSTANDING: IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        LLMTaskCategory.STRUCTURED_OUTPUT: IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        LLMTaskCategory.TOOL_SELECTION: IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        LLMTaskCategory.SQL_DATA_PLANNING: IntelligenceLane.LANE_2_STRONG_ESCALATION,
        LLMTaskCategory.AMBIGUITY_RESOLUTION: IntelligenceLane.LANE_2_STRONG_ESCALATION,
        LLMTaskCategory.COMPLEX_INVESTIGATION_REASONING: IntelligenceLane.LANE_2_STRONG_ESCALATION,
        LLMTaskCategory.EXPLANATION: IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        LLMTaskCategory.EVIDENCE_INTERPRETATION: IntelligenceLane.LANE_2_STRONG_ESCALATION,
    }

    # Default task category to capability tier mappings (backward compatibility)
    DEFAULT_TASK_TIER_MAPPING: dict[LLMTaskCategory, ModelTier] = {
        LLMTaskCategory.INTENT_UNDERSTANDING: ModelTier.LOW_COST,
        LLMTaskCategory.STRUCTURED_OUTPUT: ModelTier.LOW_COST,
        LLMTaskCategory.TOOL_SELECTION: ModelTier.LOW_COST,
        LLMTaskCategory.SQL_DATA_PLANNING: ModelTier.STRONG_REASONING,
        LLMTaskCategory.AMBIGUITY_RESOLUTION: ModelTier.STRONG_REASONING,
        LLMTaskCategory.COMPLEX_INVESTIGATION_REASONING: ModelTier.STRONG_REASONING,
        LLMTaskCategory.EXPLANATION: ModelTier.LOW_COST,
        LLMTaskCategory.EVIDENCE_INTERPRETATION: ModelTier.STRONG_REASONING,
    }

    def __init__(
        self,
        low_cost_provider: BaseLLMProvider | None = None,
        strong_reasoning_provider: BaseLLMProvider | None = None,
        fallback_provider: BaseLLMProvider | None = None,
        task_tier_mapping: dict[LLMTaskCategory, ModelTier] | None = None,
        registry: ProviderCandidateRegistry | None = None,
    ) -> None:
        self._fallback_provider = fallback_provider or MockLLMProvider()
        self._low_cost_provider = low_cost_provider
        self._strong_reasoning_provider = strong_reasoning_provider
        self._task_tier_mapping = dict(task_tier_mapping or self.DEFAULT_TASK_TIER_MAPPING)
        self._registry = registry or get_candidate_registry()

    @property
    def registry(self) -> ProviderCandidateRegistry:
        """Return the candidate provider registry."""
        return self._registry

    # ------------------------------------------------------------------
    # Configuration and Tier/Lane Resolution
    # ------------------------------------------------------------------

    def set_task_tier(self, task_category: LLMTaskCategory, tier: ModelTier) -> None:
        """Override tier assigned to a specific task category."""
        self._task_tier_mapping[task_category] = tier

    def get_tier_for_task(self, task_category: LLMTaskCategory) -> ModelTier:
        """Resolve model tier for a given task category."""
        return self._task_tier_mapping.get(task_category, ModelTier.LOW_COST)

    def get_lane_for_task(self, task_category: LLMTaskCategory) -> IntelligenceLane:
        """Resolve intelligence lane for a given task category."""
        return self.TASK_LANE_MAPPING.get(task_category, IntelligenceLane.LANE_1_FREE_HIGH_VOLUME)

    def get_required_capabilities(self, task_category: LLMTaskCategory) -> set[ModelCapability]:
        """Resolve baseline required capabilities for a given task category."""
        return set(self.TASK_CAPABILITY_REQUIREMENTS.get(task_category, {ModelCapability.LOW_COST}))

    # ------------------------------------------------------------------
    # Capability-Based Candidate Selection (Cheapest Capable Wins)
    # ------------------------------------------------------------------

    def select_candidate(self, request: LLMRequest) -> tuple[ProviderCandidateSpec, BaseLLMProvider]:
        """
        Select the optimal candidate model using capability matching and cost optimization:
        1. Determine required capabilities.
        2. Filter out incapable providers.
        3. Filter out providers with exhausted quota.
        4. If external calls are disabled/gated, select Lane 3 local fallback.
        5. Rank qualifying candidates: Free-tier first, then lowest unit cost.
        6. Return winning candidate spec and provider instance.
        """
        cat = request.task_category if isinstance(request.task_category, LLMTaskCategory) else LLMTaskCategory(request.task_category)
        required = self.get_required_capabilities(cat)
        if request.required_capabilities:
            required.update(request.required_capabilities)

        target_lane = request.preferred_lane or self.get_lane_for_task(cat)

        # Allow explicitly injected test/stub providers to be evaluated
        if (target_lane == IntelligenceLane.LANE_1_FREE_HIGH_VOLUME or request.preferred_tier == ModelTier.LOW_COST) and self._low_cost_provider:
            provider_id = getattr(self._low_cost_provider, "provider_name", "injected-low-cost")
            return ProviderCandidateSpec(
                provider_id=provider_id,
                model_name=getattr(self._low_cost_provider, "model_name", "injected-test-model"),
                lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
                capabilities={c for c in ModelCapability},
            ), self._low_cost_provider

        if (target_lane == IntelligenceLane.LANE_2_STRONG_ESCALATION or request.preferred_tier == ModelTier.STRONG_REASONING) and self._strong_reasoning_provider:
            provider_id = getattr(self._strong_reasoning_provider, "provider_name", "injected-strong-reasoning")
            return ProviderCandidateSpec(
                provider_id=provider_id,
                model_name=getattr(self._strong_reasoning_provider, "model_name", "injected-test-model"),
                lane=IntelligenceLane.LANE_2_STRONG_ESCALATION,
                capabilities={c for c in ModelCapability},
            ), self._strong_reasoning_provider

        # External call gating check
        is_external_allowed = (
            getattr(settings, "LLM_ALLOW_EXTERNAL_CALLS", False)
            and getattr(settings, "APP_ENV", "").lower() != "test"
        )

        # In offline/test or when external calls are blocked, always use Lane 3 local fallback
        if not is_external_allowed:
            fallback_spec = self._registry.get("mock") or ProviderCandidateSpec(
                provider_id="mock",
                model_name="mock-deterministic",
                lane=IntelligenceLane.LANE_3_LOCAL_FALLBACK,
                capabilities={c for c in ModelCapability},
                is_free_tier=True,
            )
            return fallback_spec, self._fallback_provider

        # Rank all capable candidates that still have quota
        candidates = self._registry.rank_candidates(
            required_capabilities=required,
            preferred_lane=target_lane,
            check_quota=True,
        )

        if not candidates:
            # No capable candidate with remaining quota found; escalate directly to local fallback
            logger.info(
                f"[ModelRouter] No available external candidate satisfied capabilities {required} with remaining quota. "
                "Escalating to Lane 3 Local Fallback."
            )
            fallback_spec = self._registry.get("mock") or ProviderCandidateSpec(
                provider_id="mock",
                model_name="mock-deterministic",
                lane=IntelligenceLane.LANE_3_LOCAL_FALLBACK,
                capabilities={c for c in ModelCapability},
                is_free_tier=True,
            )
            return fallback_spec, self._fallback_provider

        # The cheapest capable candidate wins!
        winning_candidate = candidates[0]
        provider_instance = self._resolve_candidate_instance(winning_candidate)
        return winning_candidate, provider_instance

    def _resolve_candidate_instance(self, spec: ProviderCandidateSpec) -> BaseLLMProvider:
        """Resolve executable BaseLLMProvider instance for a candidate specification."""
        pid = spec.provider_id.lower()
        if pid == "mock":
            return self._fallback_provider
        if pid in ("groq", "deepseek-v3", "deepseek-r1", "gemini-flash", "gemini-pro", "grok", "openrouter-free", "ollama-local"):
            # If custom injected provider matches
            if spec.lane == IntelligenceLane.LANE_1_FREE_HIGH_VOLUME and self._low_cost_provider:
                return self._low_cost_provider
            if spec.lane == IntelligenceLane.LANE_2_STRONG_ESCALATION and self._strong_reasoning_provider:
                return self._strong_reasoning_provider
            return self._fallback_provider
        if pid in ("openai", "openai-gpt4o"):
            from app.agents.providers.openai_provider import OpenAIProvider
            return OpenAIProvider(model=spec.model_name)
        return self._fallback_provider

    def resolve_provider(self, tier: ModelTier) -> tuple[BaseLLMProvider, str, bool]:
        """
        Backward-compatible provider resolution for existing tests and endpoints.
        """
        is_external_allowed = (
            getattr(settings, "LLM_ALLOW_EXTERNAL_CALLS", False)
            and getattr(settings, "APP_ENV", "").lower() != "test"
        )

        if tier == ModelTier.LOCAL_FALLBACK:
            return self._fallback_provider, getattr(settings, "LLM_FALLBACK_MODEL", "mock-deterministic"), False

        if tier == ModelTier.LOW_COST:
            provider_type = getattr(settings, "LLM_LOW_COST_PROVIDER", "mock").lower()
            model_name = getattr(settings, "LLM_LOW_COST_MODEL", "mock-fast")
            if self._low_cost_provider:
                return self._low_cost_provider, model_name, is_external_allowed
        elif tier == ModelTier.STRONG_REASONING:
            provider_type = getattr(settings, "LLM_STRONG_REASONING_PROVIDER", "mock").lower()
            model_name = getattr(settings, "LLM_STRONG_REASONING_MODEL", "mock-reasoning")
            if self._strong_reasoning_provider:
                return self._strong_reasoning_provider, model_name, is_external_allowed
        else:
            provider_type = "mock"
            model_name = "mock-deterministic"

        if provider_type == "mock":
            return self._fallback_provider, model_name, False

        if not is_external_allowed:
            return self._fallback_provider, "mock-deterministic", False

        if provider_type == "openai":
            from app.agents.providers.openai_provider import OpenAIProvider
            return OpenAIProvider(model=model_name), model_name, True

        return self._fallback_provider, model_name, False

    # ------------------------------------------------------------------
    # Routing Engine with Intelligent Escalation & Quota Accounting
    # ------------------------------------------------------------------

    def route(self, request: LLMRequest) -> LLMResponse:
        """
        Execute request routing across intelligence lanes with quota awareness,
        capability validation, deterministic calculation bypass, and safe fallback.
        """
        # 1. Deterministic numerical request check: bypass LLM completely!
        if DeterministicCalculationGuard.is_pure_numerical_request(request):
            return DeterministicCalculationGuard.bypass_llm_for_deterministic(request)

        # 2. Validate task category
        if not isinstance(request.task_category, LLMTaskCategory):
            try:
                request.task_category = LLMTaskCategory(request.task_category)
            except ValueError:
                raise UnsupportedLLMTaskError(
                    f"Unsupported LLM task category: '{request.task_category}'. "
                    f"Supported categories are: {[c.value for c in LLMTaskCategory]}"
                )

        # 3. Enforce calculation guard on prompt
        guard_warnings = DeterministicCalculationGuard.validate_request(request)

        # 4. Capability-based candidate selection (Cheapest Capable Wins)
        start_time = time.perf_counter()
        spec, provider = self.select_candidate(request)

        response: LLMResponse | None = None
        fallback_occurred = False
        fallback_reason: str | None = None

        try:
            # Check candidate quota capacity before execution
            if not spec.quota_state.can_accept():
                raise LLMProviderUnavailableError(f"Candidate '{spec.provider_id}' quota capacity exhausted.")

            # Execute with winning provider
            response = provider.generate(request)

        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            exc_str = str(exc).lower()
            spec.telemetry.failures_count += 1
            spec.telemetry.last_error = str(exc)

            if "429" in exc_str or "quota" in exc_str or "rate limit" in exc_str:
                spec.quota_state.mark_exhausted()
                fallback_reason = f"Provider '{spec.provider_id}' quota exhausted (429/RateLimit)"
                logger.warning(f"[ModelRouter] {fallback_reason}. Escalating to fallback.")
            elif "timeout" in exc_str or "timed out" in exc_str:
                fallback_reason = f"Provider '{spec.provider_id}' timed out after {elapsed_ms}ms"
                logger.warning(f"[ModelRouter] {fallback_reason}. Escalating to fallback.")
            else:
                fallback_reason = f"Provider '{spec.provider_id}' failed: {exc}"
                logger.warning(f"[ModelRouter] {fallback_reason}. Escalating to fallback.")

            fallback_occurred = True

        # 5. Intelligent Escalation / Fallback
        if fallback_occurred or response is None or not response.content:
            spec.telemetry.fallbacks_count += 1
            fallback_resp = self._fallback_provider.generate(request)
            fallback_resp.is_fallback = True
            fallback_resp.fallback_reason = fallback_reason or "Primary provider returned empty response"
            response = fallback_resp

        # 6. Quota and Cost Accounting
        elapsed_total_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if response.latency_ms <= 0.0:
            response.latency_ms = elapsed_total_ms

        response.tier = ModelTier.LOW_COST if spec.lane == IntelligenceLane.LANE_1_FREE_HIGH_VOLUME else (
            ModelTier.STRONG_REASONING if spec.lane == IntelligenceLane.LANE_2_STRONG_ESCALATION else ModelTier.LOCAL_FALLBACK
        )
        response.lane = spec.lane
        response.capabilities_matched = [c.value for c in spec.capabilities]

        cost = PricingCatalog.estimate_cost(spec.model_name, response.usage)
        response.estimated_cost_usd = cost

        # Update candidate quota state and telemetry
        spec.quota_state.record_usage(tokens=response.usage.total_tokens, cost=cost)
        spec.telemetry.total_requests += 1
        spec.telemetry.total_tokens += response.usage.total_tokens
        spec.telemetry.total_cost_usd += cost
        spec.telemetry.total_latency_ms += elapsed_total_ms

        eff_limit = spec.quota_state.effective_requests_limit
        if eff_limit is not None:
            response.quota_remaining_requests = max(0, eff_limit - spec.quota_state.requests_used)
        else:
            response.quota_remaining_requests = None

        # 7. Response Guardrails
        resp_warnings = DeterministicCalculationGuard.validate_response(response, request.context)
        response.warnings.extend(guard_warnings)
        response.warnings.extend(resp_warnings)

        return response

    def route_structured(
        self, request: LLMRequest, response_model: type[T]
    ) -> tuple[T, LLMResponse]:
        """
        Execute request routing and guarantee output conforming to Pydantic model.
        Falls back to local fallback engine if output is malformed or invalid.
        """
        request.schema_model = response_model.__name__
        response = self.route(request)

        try:
            if response.parsed_data:
                instance = response_model.model_validate(response.parsed_data)
            else:
                import json
                parsed_dict = json.loads(response.content)
                instance = response_model.model_validate(parsed_dict)
            return instance, response
        except Exception as validation_err:
            logger.warning(
                f"[ModelRouter] Structured output validation failed: {validation_err}. "
                f"Falling back to local fallback provider for schema '{response_model.__name__}'."
            )
            fallback_instance, fallback_response = self._fallback_provider.generate_structured(
                request, response_model
            )
            fallback_response.is_fallback = True
            fallback_response.fallback_reason = f"Malformed structured output: {validation_err}"
            return fallback_instance, fallback_response
