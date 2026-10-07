"""Provider Candidate Registry for NEXUS Intelligence 2.0.

Provides capability declarations, pricing metadata, quota state, and operational constraints
for candidate LLM providers without activating live external network connections.
"""

import logging
from typing import Any

from app.agents.providers.models import (
    IntelligenceLane,
    ModelCapability,
    ProviderCandidateSpec,
    ProviderQuotaState,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class ProviderCandidateRegistry:
    """
    Central registry of candidate models and providers across the 3 Intelligence Lanes.
    
    Adheres strictly to the Free-First + Quota-Efficient strategy:
    - Declares capabilities per candidate model.
    - Tracks quota and budget state dynamically.
    - No external API key required for registration or evaluation.
    - Does not hard-code a single permanent winner.
    """

    def __init__(self) -> None:
        self._candidates: dict[str, ProviderCandidateSpec] = {}
        self._initialize_default_candidates()

    def _initialize_default_candidates(self) -> None:
        """Register initial representative candidates for benchmarking and routing.
        
        CRITICAL ARCHITECTURAL PRINCIPLE:
        Provider quotas, rate limits, and free-tier allowances are EXTERNALLY CONTROLLED
        and subject to arbitrary upstream provider changes. They are NOT authoritative
        or permanent system facts. Limits are registered as CONFIGURABLE or OBSERVED
        METADATA, and the system continues routing seamlessly when quotas are unknown.
        """
        # Configurable policy allowances derived from application settings
        default_req_limit = getattr(settings, "LLM_FREE_TIER_DAILY_REQUEST_LIMIT", 1000)
        default_token_limit = getattr(settings, "LLM_FREE_TIER_DAILY_TOKEN_LIMIT", 1_000_000)
        default_budget_usd = getattr(settings, "LLM_MONTHLY_BUDGET_USD", 50.0)

        # -------------------------------------------------------------
        # LANE 1: FREE / HIGH-VOLUME CANDIDATES
        # -------------------------------------------------------------
        self.register(
            ProviderCandidateSpec(
                provider_id="groq",
                model_name="llama-3.3-70b-versatile",
                lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
                capabilities={
                    ModelCapability.LOW_COST,
                    ModelCapability.LOW_LATENCY,
                    ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.TOOL_CALLING,
                    ModelCapability.SQL_PLANNING,
                },
                cost_per_1m_input=0.59,
                cost_per_1m_output=0.79,
                is_free_tier=True,
                context_window_tokens=128_000,
                quota_state=ProviderQuotaState(
                    requests_limit=default_req_limit,
                    tokens_limit=default_token_limit,
                    limit_source="configured",
                    quota_notes="Configured operational limit from application settings; subject to upstream vendor policy.",
                ),
            )
        )

        self.register(
            ProviderCandidateSpec(
                provider_id="openrouter-free",
                model_name="meta-llama/llama-3.1-8b-instruct:free",
                lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
                capabilities={
                    ModelCapability.LOW_COST,
                    ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.LOW_LATENCY,
                },
                cost_per_1m_input=0.0,
                cost_per_1m_output=0.0,
                is_free_tier=True,
                context_window_tokens=64_000,
                quota_state=ProviderQuotaState(
                    requests_limit=None,
                    tokens_limit=None,
                    limit_source="unknown",
                    quota_notes="OpenRouter free model tier limits are unconfigured/unknown; dynamically governed upstream.",
                ),
            )
        )

        self.register(
            ProviderCandidateSpec(
                provider_id="gemini-flash",
                model_name="gemini-1.5-flash",
                lane=IntelligenceLane.LANE_1_FREE_HIGH_VOLUME,
                capabilities={
                    ModelCapability.LOW_COST,
                    ModelCapability.LOW_LATENCY,
                    ModelCapability.CONTEXT_WINDOW,
                    ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.TOOL_CALLING,
                },
                cost_per_1m_input=0.075,
                cost_per_1m_output=0.30,
                is_free_tier=True,
                context_window_tokens=1_000_000,
                quota_state=ProviderQuotaState(
                    requests_limit=None,
                    tokens_limit=None,
                    limit_source="unknown",
                    quota_notes="Google AI Studio free tier limits are unconfigured/unknown; governed by account tier.",
                ),
            )
        )

        # -------------------------------------------------------------
        # LANE 2: STRONG / ESCALATION CANDIDATES
        # -------------------------------------------------------------
        self.register(
            ProviderCandidateSpec(
                provider_id="deepseek-r1",
                model_name="deepseek-r1",
                lane=IntelligenceLane.LANE_2_STRONG_ESCALATION,
                capabilities={
                    ModelCapability.REASONING,
                    ModelCapability.BUSINESS_REASONING,
                    ModelCapability.SQL_PLANNING,
                    ModelCapability.AMBIGUITY_RESOLUTION,
                    ModelCapability.EVIDENCE_INTERPRETATION,
                    ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.LOW_COST,
                },
                cost_per_1m_input=0.55,
                cost_per_1m_output=2.19,
                is_free_tier=False,
                context_window_tokens=64_000,
                quota_state=ProviderQuotaState(
                    cost_budget_usd=default_budget_usd,
                    limit_source="configured",
                    quota_notes="Monitored against configured monthly budget.",
                ),
            )
        )

        self.register(
            ProviderCandidateSpec(
                provider_id="deepseek-v3",
                model_name="deepseek-v3",
                lane=IntelligenceLane.LANE_2_STRONG_ESCALATION,
                capabilities={
                    ModelCapability.REASONING,
                    ModelCapability.BUSINESS_REASONING,
                    ModelCapability.SQL_PLANNING,
                    ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.LOW_COST,
                },
                cost_per_1m_input=0.14,
                cost_per_1m_output=0.28,
                is_free_tier=False,
                context_window_tokens=64_000,
                quota_state=ProviderQuotaState(
                    cost_budget_usd=default_budget_usd,
                    limit_source="configured",
                    quota_notes="Monitored against configured monthly budget.",
                ),
            )
        )

        self.register(
            ProviderCandidateSpec(
                provider_id="gemini-pro",
                model_name="gemini-1.5-pro",
                lane=IntelligenceLane.LANE_2_STRONG_ESCALATION,
                capabilities={
                    ModelCapability.REASONING,
                    ModelCapability.BUSINESS_REASONING,
                    ModelCapability.CONTEXT_WINDOW,
                    ModelCapability.EVIDENCE_INTERPRETATION,
                    ModelCapability.AMBIGUITY_RESOLUTION,
                    ModelCapability.STRUCTURED_OUTPUT,
                },
                cost_per_1m_input=1.25,
                cost_per_1m_output=5.00,
                is_free_tier=False,
                context_window_tokens=2_000_000,
                quota_state=ProviderQuotaState(
                    cost_budget_usd=default_budget_usd,
                    limit_source="configured",
                    quota_notes="Monitored against configured monthly budget.",
                ),
            )
        )

        self.register(
            ProviderCandidateSpec(
                provider_id="grok",
                model_name="grok-2",
                lane=IntelligenceLane.LANE_2_STRONG_ESCALATION,
                capabilities={
                    ModelCapability.REASONING,
                    ModelCapability.BUSINESS_REASONING,
                    ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.TOOL_CALLING,
                },
                cost_per_1m_input=2.00,
                cost_per_1m_output=10.00,
                is_free_tier=False,
                context_window_tokens=128_000,
                quota_state=ProviderQuotaState(
                    cost_budget_usd=default_budget_usd,
                    limit_source="configured",
                    quota_notes="Monitored against configured monthly budget.",
                ),
            )
        )

        self.register(
            ProviderCandidateSpec(
                provider_id="openai-gpt4o",
                model_name="gpt-4o",
                lane=IntelligenceLane.LANE_2_STRONG_ESCALATION,
                capabilities={
                    ModelCapability.REASONING,
                    ModelCapability.BUSINESS_REASONING,
                    ModelCapability.SQL_PLANNING,
                    ModelCapability.AMBIGUITY_RESOLUTION,
                    ModelCapability.EVIDENCE_INTERPRETATION,
                    ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.TOOL_CALLING,
                },
                cost_per_1m_input=2.50,
                cost_per_1m_output=10.00,
                is_free_tier=False,
                context_window_tokens=128_000,
                quota_state=ProviderQuotaState(
                    cost_budget_usd=default_budget_usd,
                    limit_source="configured",
                    quota_notes="Monitored against configured monthly budget.",
                ),
            )
        )

        # -------------------------------------------------------------
        # LANE 3: LOCAL / FALLBACK CANDIDATES
        # -------------------------------------------------------------
        self.register(
            ProviderCandidateSpec(
                provider_id="mock",
                model_name="mock-deterministic",
                lane=IntelligenceLane.LANE_3_LOCAL_FALLBACK,
                capabilities={c for c in ModelCapability},  # Fully capable deterministic mock
                cost_per_1m_input=0.0,
                cost_per_1m_output=0.0,
                is_free_tier=True,
                context_window_tokens=128_000,
                quota_state=ProviderQuotaState(
                    limit_source="unknown",
                    quota_notes="Offline deterministic fixture unconstrained by external quotas.",
                ),
            )
        )

        self.register(
            ProviderCandidateSpec(
                provider_id="ollama-local",
                model_name="llama3.2:latest",
                lane=IntelligenceLane.LANE_3_LOCAL_FALLBACK,
                capabilities={
                    ModelCapability.LOW_COST,
                    ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.TOOL_CALLING,
                    ModelCapability.REASONING,
                },
                cost_per_1m_input=0.0,
                cost_per_1m_output=0.0,
                is_free_tier=True,
                context_window_tokens=128_000,
                quota_state=ProviderQuotaState(
                    limit_source="unknown",
                    quota_notes="Local inference instance unconstrained by remote network quotas.",
                ),
            )
        )

    # -------------------------------------------------------------
    # Registry Management
    # -------------------------------------------------------------

    def register(self, spec: ProviderCandidateSpec) -> None:
        """Register or update a candidate model specification."""
        self._candidates[spec.provider_id.lower()] = spec

    def get(self, provider_id: str) -> ProviderCandidateSpec | None:
        """Lookup candidate specification by identifier."""
        return self._candidates.get(provider_id.lower())

    def list_candidates(self) -> list[ProviderCandidateSpec]:
        """Return all registered candidate specifications."""
        return list(self._candidates.values())

    def list_by_lane(self, lane: IntelligenceLane) -> list[ProviderCandidateSpec]:
        """List candidates assigned to a specific intelligence lane."""
        return [c for c in self._candidates.values() if c.lane == lane]

    def find_capable(
        self, required_capabilities: set[ModelCapability], lane: IntelligenceLane | None = None
    ) -> list[ProviderCandidateSpec]:
        """Filter candidates that satisfy all requested capability requirements."""
        candidates = self.list_by_lane(lane) if lane else self.list_candidates()
        return [c for c in candidates if c.is_active and c.matches_capabilities(required_capabilities)]

    def rank_candidates(
        self,
        required_capabilities: set[ModelCapability],
        preferred_lane: IntelligenceLane | None = None,
        check_quota: bool = True,
    ) -> list[ProviderCandidateSpec]:
        """
        Rank capable candidates using the Free-First + Quota-Efficient strategy:
        1. Candidates lacking required capabilities are skipped.
        2. Candidates with exhausted quota are skipped.
        3. Free-tier candidates ranked highest.
        4. Lower unit cost ranked before expensive providers.
        5. Preferred lane prioritized if costs are comparable.
        """
        capable = [c for c in self.list_candidates() if c.is_active and c.matches_capabilities(required_capabilities)]

        if check_quota:
            capable = [c for c in capable if c.quota_state.can_accept()]

        def sort_key(c: ProviderCandidateSpec) -> tuple:
            is_preferred_lane = 0 if (preferred_lane and c.lane == preferred_lane) else 1
            is_free = 0 if c.is_free_tier else 1
            cost = c.estimated_unit_cost()
            return (is_preferred_lane, is_free, cost)

        return sorted(capable, key=sort_key)

    def reset_all_quotas(self) -> None:
        """Reset quota states across all registered candidates."""
        for c in self._candidates.values():
            c.quota_state.reset_quota()


# Global default registry instance
_default_registry: ProviderCandidateRegistry | None = None


def get_candidate_registry() -> ProviderCandidateRegistry:
    """Return singleton instance of ProviderCandidateRegistry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ProviderCandidateRegistry()
    return _default_registry
