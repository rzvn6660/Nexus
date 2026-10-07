"""Unit and integration tests for NEXUS Phase 24 Hardening: Free-First, Capability-Based LLM Strategy.

Verifies:
1. Cheapest capable provider selection
2. Incapable cheap provider skipped
3. Strong provider selected for complex task
4. Free provider preferred for simple task
5. Provider quota unavailable → next capable provider
6. Provider failure → fallback
7. No capable external provider → local/mock
8. Deterministic numerical request bypasses LLM
9. External calls remain blocked by default
10. Provider capability registration
11. Configurable quota/budget values
12. Benchmark provider independence and baseline distinction
"""

import pytest
from pydantic import BaseModel

from app.agents.providers.base import BaseLLMProvider
from app.agents.providers.factory import (
    get_llm_interface,
    get_llm_provider,
    get_model_router,
)
from app.agents.providers.guard import DeterministicCalculationGuard
from app.agents.providers.interface import NexusLLMInterface
from app.agents.providers.mock import MockLLMProvider
from app.agents.providers.models import (
    DeterministicInvariantViolationError,
    IntelligenceLane,
    LLMProviderError,
    LLMProviderTimeoutError,
    LLMRequest,
    LLMResponse,
    LLMTaskCategory,
    MalformedLLMResponseError,
    ModelCapability,
    ModelTier,
    PricingCatalog,
    ProviderCandidateSpec,
    ProviderQuotaState,
    TokenUsage,
    UnsupportedLLMTaskError,
)
from app.agents.providers.registry import (
    ProviderCandidateRegistry,
    get_candidate_registry,
)
from app.agents.providers.router import ModelRouter
from app.agents.state.models import (
    AnalysisPlan,
    ExplanationLevel,
    IntentCategory,
    IntentResult,
)
from app.core.config import Settings, settings
from evaluation.benchmarks.llm_provider_benchmark import (
    BenchmarkMode,
    LLMProviderBenchmarkRunner,
)


# ----------------------------------------------------------------------
# Helper Mock/Stub Providers for Testing Edge Cases
# ----------------------------------------------------------------------

class FailingProviderStub(BaseLLMProvider):
    """Stub provider that simulates hard crash / exception."""
    @property
    def provider_name(self) -> str:
        return "FailingProviderStub"

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("Simulated remote provider connection crash")

    def classify_intent(self, query: str, supported_intents: list[str]) -> IntentResult:
        raise RuntimeError("Crash")

    def create_plan(self, query: str, intent: IntentCategory, available_tools: list, resolved_dates: dict) -> AnalysisPlan:
        raise RuntimeError("Crash")

    def explain_results(self, *args, **kwargs) -> str:
        raise RuntimeError("Crash")


class TimeoutProviderStub(BaseLLMProvider):
    """Stub provider that simulates network timeout."""
    @property
    def provider_name(self) -> str:
        return "TimeoutProviderStub"

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise LLMProviderTimeoutError("Simulated remote provider request timed out after 10000ms")

    def classify_intent(self, query: str, supported_intents: list[str]) -> IntentResult:
        raise LLMProviderTimeoutError("Timeout")

    def create_plan(self, query: str, intent: IntentCategory, available_tools: list, resolved_dates: dict) -> AnalysisPlan:
        raise LLMProviderTimeoutError("Timeout")

    def explain_results(self, *args, **kwargs) -> str:
        raise LLMProviderTimeoutError("Timeout")


class MalformedResponseProviderStub(BaseLLMProvider):
    """Stub provider that returns corrupt non-JSON or invalid schema."""
    @property
    def provider_name(self) -> str:
        return "MalformedResponseProviderStub"

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content="<<<INVALID NOT A JSON>>>",
            task_category=request.task_category,
            model_name="malformed-stub",
            provider_name=self.provider_name,
            tier=ModelTier.LOW_COST,
        )

    def classify_intent(self, query: str, supported_intents: list[str]) -> IntentResult:
        raise ValueError("Invalid")

    def create_plan(self, query: str, intent: IntentCategory, available_tools: list, resolved_dates: dict) -> AnalysisPlan:
        raise ValueError("Invalid")

    def explain_results(self, *args, **kwargs) -> str:
        return "Malformed"


# ----------------------------------------------------------------------
# Requirement 8 Test Suite
# ----------------------------------------------------------------------

def test_1_cheapest_capable_provider_selection() -> None:
    """Requirement 8.1: Verify the cheapest capable provider is ranked first."""
    registry = ProviderCandidateRegistry()

    # Query for structured output and low latency
    required = {ModelCapability.STRUCTURED_OUTPUT, ModelCapability.LOW_LATENCY}
    ranked = registry.rank_candidates(required_capabilities=required)

    assert len(ranked) >= 2
    # First model must be free-tier or cheapest unit cost
    first_model = ranked[0]
    assert first_model.is_free_tier is True or first_model.estimated_unit_cost() <= ranked[1].estimated_unit_cost()


def test_2_incapable_cheap_provider_skipped() -> None:
    """Requirement 8.2: Verify a cheap provider lacking a required capability is skipped."""
    registry = ProviderCandidateRegistry()

    # Register an ultra-cheap provider that ONLY has low_latency (no SQL planning)
    cheap_dumb = ProviderCandidateSpec(
        provider_id="cheap-dumb-model",
        model_name="dumb-1b",
        lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        capabilities={ModelCapability.LOW_COST, ModelCapability.LOW_LATENCY},
        cost_per_1m_input=0.01,
        cost_per_1m_output=0.01,
        is_free_tier=True,
    )
    registry.register(cheap_dumb)

    # Task requires SQL planning
    required = {ModelCapability.SQL_PLANNING}
    ranked = registry.rank_candidates(required_capabilities=required)

    # The cheap dumb model must NOT be in the ranked candidates
    candidate_ids = [c.provider_id for c in ranked]
    assert "cheap-dumb-model" not in candidate_ids
    assert all(c.matches_capabilities(required) for c in ranked)


def test_3_strong_provider_selected_for_complex_task() -> None:
    """Requirement 8.3: Verify strong reasoning provider is selected for complex investigation."""
    registry = ProviderCandidateRegistry()

    # Complex investigation requires BUSINESS_REASONING and REASONING
    required = {ModelCapability.BUSINESS_REASONING, ModelCapability.REASONING}
    ranked = registry.rank_candidates(required_capabilities=required, preferred_lane=IntelligenceLane.LANE_2_STRONG_ESCALATION)

    assert len(ranked) > 0
    # Winning candidate must possess business reasoning and reasoning capabilities
    top = ranked[0]
    assert ModelCapability.BUSINESS_REASONING in top.capabilities
    assert ModelCapability.REASONING in top.capabilities


def test_4_free_provider_preferred_for_simple_task() -> None:
    """Requirement 8.4: Verify free provider is preferred over expensive paid models for simple tasks."""
    registry = ProviderCandidateRegistry()

    # Simple intent understanding requires only LOW_COST
    required = {ModelCapability.LOW_COST}
    ranked = registry.rank_candidates(required_capabilities=required, preferred_lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME)

    assert len(ranked) >= 2
    top = ranked[0]
    # Winning model must be free-tier or zero cost
    assert top.is_free_tier is True or top.estimated_unit_cost() == 0.0


def test_5_provider_quota_unavailable_escalates_to_next_capable() -> None:
    """Requirement 8.5: When provider quota is exhausted, router escalates to the next capable provider."""
    registry = ProviderCandidateRegistry()

    # Register candidate A (free, but quota exhausted)
    spec_a = ProviderCandidateSpec(
        provider_id="candidate-a",
        model_name="model-a",
        lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        capabilities={ModelCapability.STRUCTURED_OUTPUT, ModelCapability.LOW_COST},
        is_free_tier=True,
        quota_state=ProviderQuotaState(requests_limit=10, requests_used=10, is_exhausted=True),
    )
    # Register candidate B (capable, with remaining quota)
    spec_b = ProviderCandidateSpec(
        provider_id="candidate-b",
        model_name="model-b",
        lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        capabilities={ModelCapability.STRUCTURED_OUTPUT, ModelCapability.LOW_COST},
        cost_per_1m_input=0.10,
        cost_per_1m_output=0.20,
        quota_state=ProviderQuotaState(requests_limit=100, requests_used=5),
    )
    registry.register(spec_a)
    registry.register(spec_b)

    required = {ModelCapability.STRUCTURED_OUTPUT}
    ranked = registry.rank_candidates(required_capabilities=required, check_quota=True)

    candidate_ids = [c.provider_id for c in ranked]
    assert "candidate-a" not in candidate_ids
    assert "candidate-b" in candidate_ids


def test_6_provider_failure_falls_back_cleanly() -> None:
    """Requirement 8.6: Verify provider crash or timeout triggers clean fallback to deterministic local mock."""
    failing = FailingProviderStub()
    router = ModelRouter(
        low_cost_provider=failing,
        fallback_provider=MockLLMProvider(),
    )

    req = LLMRequest(
        task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
        prompt="What was our total revenue last month?",
        preferred_tier=ModelTier.LOW_COST,
    )
    resp = router.route(req)

    assert resp.is_fallback is True
    assert "FailingProviderStub" in str(resp.fallback_reason)
    assert resp.content != ""
    assert resp.parsed_data is not None


def test_7_no_capable_external_provider_resolves_to_local_mock() -> None:
    """Requirement 8.7: When no external candidate qualifies, router resolves to Lane 3 Local Fallback."""
    empty_registry = ProviderCandidateRegistry()
    empty_registry._candidates.clear()  # Clear all candidates

    router = ModelRouter(
        fallback_provider=MockLLMProvider(),
        registry=empty_registry,
    )

    req = LLMRequest(
        task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
        prompt="What was total sales?",
    )
    spec, provider = router.select_candidate(req)

    assert spec.lane == IntelligenceLane.LANE_3_LOCAL_FALLBACK
    assert spec.provider_id == "mock"
    assert isinstance(provider, MockLLMProvider)


def test_8_deterministic_numerical_request_bypasses_llm() -> None:
    """Requirement 8.8: Verify pure numerical/calculation requests bypass LLM completely to SQL/analytics."""
    router = ModelRouter()

    # 1. Flagged request
    req1 = LLMRequest(
        task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
        prompt="125000 + 45000",
        is_deterministic_numerical_request=True,
    )
    resp1 = router.route(req1)
    assert resp1.bypassed_llm_for_deterministic is True
    assert resp1.usage.total_tokens == 0
    assert resp1.estimated_cost_usd == 0.0

    # 2. Arithmetic prompt pattern
    req2 = LLMRequest(
        task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
        prompt="calculate 5420 * 1.18 =",
    )
    resp2 = router.route(req2)
    assert resp2.bypassed_llm_for_deterministic is True
    assert resp2.usage.total_tokens == 0


def test_9_external_calls_remain_blocked_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 8.9: Strict test confirming external calls remain gated off by default."""
    router = ModelRouter()

    # Simulate presence of production API key in settings, but LLM_ALLOW_EXTERNAL_CALLS is False
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-proj-simulated-key")
    monkeypatch.setattr(settings, "LLM_ALLOW_EXTERNAL_CALLS", False)

    req = LLMRequest(
        task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
        prompt="What was total revenue?",
    )
    spec, provider = router.select_candidate(req)

    # Must resolve to Lane 3 Local Fallback
    assert spec.lane == IntelligenceLane.LANE_3_LOCAL_FALLBACK
    assert spec.provider_id == "mock"
    assert isinstance(provider, MockLLMProvider)


def test_10_provider_capability_registration() -> None:
    """Requirement 8.10: Verify provider candidate registry stores capabilities and lanes for future candidates."""
    registry = get_candidate_registry()

    # Candidates should include Groq, DeepSeek, Gemini, Grok, OpenRouter, and Ollama
    groq = registry.get("groq")
    assert groq is not None
    assert groq.lane == IntelligenceLane.LANE_1_FREE_HIGH_VOLUME
    assert ModelCapability.LOW_LATENCY in groq.capabilities
    assert ModelCapability.TOOL_CALLING in groq.capabilities

    deepseek = registry.get("deepseek-r1")
    assert deepseek is not None
    assert deepseek.lane == IntelligenceLane.LANE_2_STRONG_ESCALATION
    assert ModelCapability.BUSINESS_REASONING in deepseek.capabilities
    assert ModelCapability.REASONING in deepseek.capabilities

    ollama = registry.get("ollama-local")
    assert ollama is not None
    assert ollama.lane == IntelligenceLane.LANE_3_LOCAL_FALLBACK
    assert ollama.is_free_tier is True


def test_11_configurable_quota_and_budget_values() -> None:
    """Requirement 8.11: Verify quota and budget limits are configurable from Settings."""
    cfg = Settings()
    assert hasattr(cfg, "LLM_FREE_TIER_DAILY_REQUEST_LIMIT")
    assert hasattr(cfg, "LLM_FREE_TIER_DAILY_TOKEN_LIMIT")
    assert hasattr(cfg, "LLM_MONTHLY_BUDGET_USD")

    assert cfg.LLM_FREE_TIER_DAILY_REQUEST_LIMIT == 1000
    assert cfg.LLM_FREE_TIER_DAILY_TOKEN_LIMIT == 1_000_000
    assert cfg.LLM_MONTHLY_BUDGET_USD == 50.0

    quota = ProviderQuotaState(
        requests_limit=5,
        tokens_limit=500,
        cost_budget_usd=1.0,
    )
    assert quota.can_accept() is True
    quota.record_usage(tokens=600, cost=0.01)
    assert quota.can_accept() is False
    assert quota.is_exhausted is True


def test_12_benchmark_provider_independence_and_baseline_distinction() -> None:
    """Requirement 8.12: Verify benchmark runner clearly distinguishes deterministic baseline vs live measurement."""
    # Test deterministic local baseline
    mock_runner = LLMProviderBenchmarkRunner(provider=MockLLMProvider())
    assert mock_runner.mode == BenchmarkMode.DETERMINISTIC_LOCAL_BASELINE

    report = mock_runner.run_benchmark()
    assert report.benchmark_mode == BenchmarkMode.DETERMINISTIC_LOCAL_BASELINE
    assert "DETERMINISTIC LOCAL BASELINE NOTE" in report.disclaimer
    assert report.quota_efficiency_pct >= 90.0
    assert report.avg_input_tokens > 0.0
    assert report.avg_output_tokens > 0.0

    # Test live provider distinction
    class DummyLiveProvider(BaseLLMProvider):
        @property
        def provider_name(self) -> str: return "Groq-Candidate"
        def generate(self, r): return MockLLMProvider().generate(r)
        def classify_intent(self, q, s): return MockLLMProvider().classify_intent(q, s)
        def create_plan(self, q, i, a, r): return MockLLMProvider().create_plan(q, i, a, r)
        def explain_results(self, *a, **k): return MockLLMProvider().explain_results(*a, **k)

    live_runner = LLMProviderBenchmarkRunner(provider=DummyLiveProvider())
    assert live_runner.mode == BenchmarkMode.MEASURED_LIVE_PROVIDER
    live_report = live_runner.run_benchmark()
    assert live_report.benchmark_mode == BenchmarkMode.MEASURED_LIVE_PROVIDER
    assert "MEASURED LIVE RESULTS" in live_report.disclaimer


def test_13_deterministic_calculation_invariant_guard() -> None:
    """Requirement 5: Verify DeterministicCalculationGuard flags attempts to calculate numbers in LLM."""
    # Request validation
    arithmetic_req = LLMRequest(
        task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
        prompt="Calculate the sum of orders manually: 120 + 350 + 90 =",
        enforce_deterministic_invariants=True,
    )
    warnings = DeterministicCalculationGuard.validate_request(arithmetic_req, strict=False)
    assert len(warnings) > 0
    assert "Deterministic Invariant Warning" in warnings[0]

    with pytest.raises(DeterministicInvariantViolationError):
        DeterministicCalculationGuard.validate_request(arithmetic_req, strict=True)

    # Response validation on fake zero costs
    hallucinated_resp = LLMResponse(
        content="Our COGS was $0.00 and Gross Margin was 100% for this period.",
        task_category=LLMTaskCategory.EXPLANATION,
        model_name="mock",
        provider_name="mock",
        tier=ModelTier.LOW_COST,
    )
    context_missing_costs = {
        "tool_results": [{"result": {"cost_status": "incomplete", "missing_unit_costs": True}}]
    }
    with pytest.raises(DeterministicInvariantViolationError):
        DeterministicCalculationGuard.validate_response(
            hallucinated_resp, context=context_missing_costs, strict=True
        )


def test_14_malformed_provider_response_recovery() -> None:
    """Verify recovery when provider outputs malformed/unparseable structured data."""
    malformed_provider = MalformedResponseProviderStub()
    router = ModelRouter(
        low_cost_provider=malformed_provider,
        fallback_provider=MockLLMProvider(),
    )

    req = LLMRequest(
        task_category=LLMTaskCategory.STRUCTURED_OUTPUT,
        prompt="Analyze revenue metrics",
        schema_model="AnalysisPlan",
        context={"available_tools": [{"name": "get_revenue_metrics"}], "resolved_dates": {}},
        preferred_tier=ModelTier.LOW_COST,
    )
    plan, resp = router.route_structured(req, AnalysisPlan)

    assert isinstance(plan, AnalysisPlan)
    assert resp.is_fallback is True
    assert "Malformed structured output" in str(resp.fallback_reason)
    assert len(plan.steps) > 0


def test_15_nexus_llm_interface_methods() -> None:
    """Verify high-level methods on NexusLLMInterface."""
    interface = NexusLLMInterface()

    amb_res = interface.resolve_ambiguity("give me a breakdown please")
    assert amb_res.get("is_ambiguous") is True

    sql_plan = interface.plan_sql("Show daily orders aggregation")
    assert sql_plan.get("safe_read_only") is True

    inv_reasoning = interface.reason_investigation("Investigate net profit variance")
    assert "hypotheses_evaluated" in inv_reasoning

    ev_interp = interface.interpret_evidence("Analyze margin", evidence=[{"metric": "sales"}])
    assert ev_interp.get("evidence_status") in ("SUFFICIENT", "PARTIAL")


def test_16_routing_works_with_unknown_quota() -> None:
    """Verify router functions seamlessly when provider quota information is unknown/unconfigured."""
    registry = ProviderCandidateRegistry()

    # Candidate with explicitly unknown quota
    unknown_spec = ProviderCandidateSpec(
        provider_id="unknown-quota-model",
        model_name="unknown-v1",
        lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        capabilities={ModelCapability.LOW_COST, ModelCapability.STRUCTURED_OUTPUT},
        is_free_tier=True,
        quota_state=ProviderQuotaState(
            requests_limit=None,
            tokens_limit=None,
            limit_source="unknown",
            quota_notes="Vendor limits unconfigured.",
        ),
    )
    registry.register(unknown_spec)

    assert unknown_spec.quota_state.is_unknown_quota is True
    assert unknown_spec.quota_state.can_accept() is True

    # Ranking must include candidates with unknown quota
    ranked = registry.rank_candidates(
        required_capabilities={ModelCapability.STRUCTURED_OUTPUT},
        check_quota=True,
    )
    candidate_ids = [c.provider_id for c in ranked]
    assert "unknown-quota-model" in candidate_ids

    # Routing execution must succeed with quota_remaining_requests returning None
    router = ModelRouter(
        low_cost_provider=MockLLMProvider(),
        fallback_provider=MockLLMProvider(),
        registry=registry,
    )
    req = LLMRequest(
        task_category=LLMTaskCategory.INTENT_UNDERSTANDING,
        prompt="Show sales summary",
    )
    resp = router.route(req)
    assert resp.content != ""


def test_17_configured_quota_is_respected() -> None:
    """Verify configured quota limits are strictly enforced and decremented."""
    quota = ProviderQuotaState(
        requests_limit=2,
        tokens_limit=1000,
        limit_source="configured",
        quota_notes="Operational daily ceiling",
    )
    assert quota.has_configured_limits is True
    assert quota.can_accept(tokens_estimate=100) is True

    # 1st request
    quota.record_usage(tokens=200, cost=0.001)
    assert quota.requests_used == 1
    assert quota.is_exhausted is False
    assert quota.can_accept(tokens_estimate=100) is True

    # 2nd request hits requests_limit
    quota.record_usage(tokens=300, cost=0.001)
    assert quota.requests_used == 2
    assert quota.is_exhausted is True
    assert quota.can_accept(tokens_estimate=10) is False


def test_18_exhausted_quota_is_skipped() -> None:
    """Verify exhausted providers are skipped during candidate ranking."""
    registry = ProviderCandidateRegistry()

    active_candidate = ProviderCandidateSpec(
        provider_id="active-model",
        model_name="active-v1",
        lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        capabilities={ModelCapability.SQL_PLANNING},
        is_free_tier=True,
        quota_state=ProviderQuotaState(requests_limit=10, requests_used=2),
    )
    exhausted_candidate = ProviderCandidateSpec(
        provider_id="exhausted-model",
        model_name="exhausted-v1",
        lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
        capabilities={ModelCapability.SQL_PLANNING},
        is_free_tier=True,
        quota_state=ProviderQuotaState(requests_limit=10, requests_used=10, is_exhausted=True),
    )
    registry.register(active_candidate)
    registry.register(exhausted_candidate)

    ranked = registry.rank_candidates(
        required_capabilities={ModelCapability.SQL_PLANNING},
        check_quota=True,
    )
    candidate_ids = [c.provider_id for c in ranked]
    assert "active-model" in candidate_ids
    assert "exhausted-model" not in candidate_ids


def test_19_no_provider_limit_is_treated_as_permanently_authoritative() -> None:
    """Verify that quota and rate limits are treated as metadata rather than permanent facts."""
    registry = get_candidate_registry()

    # Verify default candidates hold non-authoritative metadata
    gemini_flash = registry.get("gemini-flash")
    assert gemini_flash is not None
    assert gemini_flash.quota_state.is_authoritative is False
    assert gemini_flash.quota_state.is_unknown_quota is True
    assert "authoritative" in gemini_flash.quota_metadata_notes.lower() or "externally controlled" in gemini_flash.quota_metadata_notes.lower()

    openrouter = registry.get("openrouter-free")
    assert openrouter is not None
    assert openrouter.quota_state.is_authoritative is False
    assert openrouter.quota_state.is_unknown_quota is True

    # Dynamic observation updates must be supported at runtime
    gemini_flash.quota_state.observed_requests_limit = 2500
    gemini_flash.quota_state.observed_rpm = 15
    gemini_flash.quota_state.limit_source = "observed"
    assert gemini_flash.quota_state.has_observed_limits is True
    assert gemini_flash.quota_state.effective_requests_limit == 2500

    # Configured overrides supersede observed metadata
    gemini_flash.quota_state.requests_limit = 500
    gemini_flash.quota_state.limit_source = "configured"
    assert gemini_flash.quota_state.effective_requests_limit == 500

