"""Data models, task categories, capabilities, schemas, and telemetry for LLM provider architecture."""

from enum import Enum
import time
from typing import Any
from pydantic import BaseModel, Field


class ModelCapability(str, Enum):
    """
    Fine-grained model capabilities declared by providers and required by tasks.
    
    Enables capability-based routing:
    Task Requirements → Capability Compatibility → Availability → Quota → Cost → Latency.
    """
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
    REASONING = "reasoning"
    CONTEXT_WINDOW = "context_window"
    LOW_LATENCY = "low_latency"
    LOW_COST = "low_cost"
    SQL_PLANNING = "sql_planning"
    AMBIGUITY_RESOLUTION = "ambiguity_resolution"
    BUSINESS_REASONING = "business_reasoning"
    EVIDENCE_INTERPRETATION = "evidence_interpretation"


class IntelligenceLane(str, Enum):
    """
    Three strategic operational lanes for SaaS intelligence.
    
    Prevents single-vendor lock-in and isolates high-volume routine tasks from expensive reasoning.
    """
    LANE_1_FREE_HIGH_VOLUME = "lane_1_free_high_volume"  # Intent classification, simple questions, basic tools, summaries
    LANE_2_STRONG_ESCALATION = "lane_2_strong_escalation"  # Complex investigations, difficult SQL, deep ambiguity, evidence synthesis
    LANE_3_LOCAL_FALLBACK = "lane_3_local_fallback"      # Offline dev, unit tests, privacy-strict deployments, outage recovery


class LLMTaskCategory(str, Enum):
    """
    Task-aware model routing categories for NEXUS.
    
    Each category reflects an analytical or linguistic sub-problem that can be
    routed to the optimal model tier (low-cost, strong reasoning, or local fallback).
    """
    INTENT_UNDERSTANDING = "intent_understanding"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_SELECTION = "tool_selection"
    SQL_DATA_PLANNING = "sql_data_planning"
    AMBIGUITY_RESOLUTION = "ambiguity_resolution"
    COMPLEX_INVESTIGATION_REASONING = "complex_investigation_reasoning"
    EXPLANATION = "explanation"
    EVIDENCE_INTERPRETATION = "evidence_interpretation"


class ModelTier(str, Enum):
    """
    Standardized model capability tiers (backward-compatible view of Intelligence Lanes).
    """
    LOW_COST = "low_cost"                 # Maps to LANE_1_FREE_HIGH_VOLUME
    STRONG_REASONING = "strong_reasoning" # Maps to LANE_2_STRONG_ESCALATION
    LOCAL_FALLBACK = "local_fallback"     # Maps to LANE_3_LOCAL_FALLBACK


class TokenUsage(BaseModel):
    """Normalized token accounting across model providers."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ProviderQuotaState(BaseModel):
    """
    Tracks and enforces quota and budget limits for a provider or model.
    
    IMPORTANT: Provider quotas, rate limits, and free-tier allowances are externally
    controlled by upstream vendors and change frequently. They are NEVER permanent
    or authoritative system truths. Limits are treated as operational metadata:
      1. 'configured': Explicit operational limits set via application configuration.
      2. 'observed': Empirical limits inferred from vendor response headers or rate limits.
      3. 'unknown': Unconstrained local tracking where upstream capacity is unverified.
    """
    # Configured limits (from application settings or tenant policy)
    requests_limit: int | None = None
    tokens_limit: int | None = None
    cost_budget_usd: float | None = None

    # Observed / empirical limits (discovered dynamically from runtime responses or docs)
    observed_requests_limit: int | None = None
    observed_tokens_limit: int | None = None
    observed_rpm: int | None = None
    observed_tpm: int | None = None

    # Source classification and metadata
    limit_source: str = "unknown"  # "configured" | "observed" | "unknown"
    quota_notes: str | None = None  # Explanatory provenance for operational tracking
    is_authoritative: bool = False  # Always False: vendor quotas are never permanent facts

    # Runtime consumption
    requests_used: int = 0
    tokens_used: int = 0
    cost_spent_usd: float = 0.0
    is_exhausted: bool = False
    reset_epoch_seconds: float | None = None

    @property
    def has_configured_limits(self) -> bool:
        """True if explicit configured request, token, or budget limits are set."""
        return self.requests_limit is not None or self.tokens_limit is not None or self.cost_budget_usd is not None

    @property
    def has_observed_limits(self) -> bool:
        """True if observed/empirical request or token limits are recorded."""
        return self.observed_requests_limit is not None or self.observed_tokens_limit is not None

    @property
    def is_unknown_quota(self) -> bool:
        """True if no configured or observed request/token constraints are established."""
        return not self.has_configured_limits and not self.has_observed_limits

    @property
    def effective_requests_limit(self) -> int | None:
        """Configured limit takes precedence over observed limit; None if unknown."""
        if self.requests_limit is not None:
            return self.requests_limit
        return self.observed_requests_limit

    @property
    def effective_tokens_limit(self) -> int | None:
        """Configured limit takes precedence over observed limit; None if unknown."""
        if self.tokens_limit is not None:
            return self.tokens_limit
        return self.observed_tokens_limit

    def can_accept(self, tokens_estimate: int = 0) -> bool:
        """Verify whether the provider currently has remaining quota/budget capacity.
        
        When limits are unknown (None), the provider can accept requests unless explicitly
        flagged as exhausted (e.g. following an observed 429 response).
        """
        if self.is_exhausted:
            return False
        eff_req = self.effective_requests_limit
        if eff_req is not None and self.requests_used >= eff_req:
            return False
        eff_tok = self.effective_tokens_limit
        if eff_tok is not None and (self.tokens_used + tokens_estimate) > eff_tok:
            return False
        if self.cost_budget_usd is not None and self.cost_spent_usd >= self.cost_budget_usd:
            return False
        return True

    def record_usage(self, tokens: int, cost: float) -> None:
        """Record completed request token and cost metrics against limits."""
        self.requests_used += 1
        self.tokens_used += tokens
        self.cost_spent_usd = round(self.cost_spent_usd + cost, 6)
        
        eff_req = self.effective_requests_limit
        eff_tok = self.effective_tokens_limit
        if (eff_req is not None and self.requests_used >= eff_req) or \
           (eff_tok is not None and self.tokens_used >= eff_tok) or \
           (self.cost_budget_usd is not None and self.cost_spent_usd >= self.cost_budget_usd):
            self.is_exhausted = True

    def mark_exhausted(self) -> None:
        """Explicitly mark provider quota as exhausted (e.g. on 429 response)."""
        self.is_exhausted = True

    def reset_quota(self) -> None:
        """Reset quota counters (e.g. on daily or hourly cycle)."""
        self.requests_used = 0
        self.tokens_used = 0
        self.cost_spent_usd = 0.0
        self.is_exhausted = False


class ProviderTelemetry(BaseModel):
    """Operational telemetry tracking performance and reliability across providers."""
    total_requests: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    failures_count: int = 0
    fallbacks_count: int = 0
    last_error: str | None = None

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return round(self.total_latency_ms / self.total_requests, 2)


class ProviderAvailabilityStatus(str, Enum):
    """Categorizes provider availability status for live benchmark runs."""
    AVAILABLE = "AVAILABLE"
    NOT_RUN_MISSING_CREDENTIALS = "NOT_RUN_MISSING_CREDENTIALS"
    NOT_RUN_EXTERNAL_CALLS_DISABLED = "NOT_RUN_EXTERNAL_CALLS_DISABLED"
    NOT_RUN_UNREACHABLE = "NOT_RUN_UNREACHABLE"


class ProviderCandidateSpec(BaseModel):
    """
    Specification declaring a candidate model's capabilities, lane, and operational constraints.
    All quota and rate-limit metadata are non-authoritative and subject to external provider change.
    """
    provider_id: str
    model_name: str
    lane: IntelligenceLane
    capabilities: set[ModelCapability] = Field(default_factory=set)
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0
    is_free_tier: bool = False
    context_window_tokens: int = 128_000
    supports_streaming: bool = True
    is_active: bool = True
    api_key_env_var: str | None = None
    base_url: str | None = None
    quota_state: ProviderQuotaState = Field(default_factory=ProviderQuotaState)
    telemetry: ProviderTelemetry = Field(default_factory=ProviderTelemetry)
    quota_metadata_notes: str = (
        "Quota and rate limits are externally controlled non-authoritative metadata subject to change."
    )

    def matches_capabilities(self, required: set[ModelCapability]) -> bool:
        """Check if this candidate possesses all required capabilities."""
        return required.issubset(self.capabilities)

    def estimated_unit_cost(self) -> float:
        """Calculate weighted unit cost for sorting (blended prompt + completion)."""
        if self.is_free_tier:
            return 0.0
        return (self.cost_per_1m_input * 0.7) + (self.cost_per_1m_output * 0.3)

    def check_availability(self, allow_external: bool = False) -> tuple[bool, str]:
        """
        Verify whether this candidate is ready for live execution.
        Returns (is_available, reason_or_status).
        """
        if self.provider_id in ("mock", "local"):
            return True, ProviderAvailabilityStatus.AVAILABLE.value

        if self.provider_id == "ollama-local":
            # Local service; does not require remote paid credentials
            return True, ProviderAvailabilityStatus.AVAILABLE.value

        # External provider checks
        if not allow_external:
            return False, ProviderAvailabilityStatus.NOT_RUN_EXTERNAL_CALLS_DISABLED.value

        if self.api_key_env_var:
            from app.core.config import settings
            import os
            key_val = getattr(settings, self.api_key_env_var, None) or os.getenv(self.api_key_env_var)
            if not key_val and self.api_key_env_var == "KIMI_API_KEY":
                key_val = getattr(settings, "MOONSHOT_API_KEY", None) or os.getenv("MOONSHOT_API_KEY")
            if not key_val:
                return False, f"{ProviderAvailabilityStatus.NOT_RUN_MISSING_CREDENTIALS.value} ({self.api_key_env_var} not configured)"

        return True, ProviderAvailabilityStatus.AVAILABLE.value


class PricingCatalog:
    """Estimated cost rates per 1M tokens in USD for multi-provider benchmarking."""
    # (prompt_cost_per_1m, completion_cost_per_1m)
    RATES: dict[str, tuple[float, float]] = {
        # OpenAI models
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        # Anthropic models
        "claude-3-5-sonnet": (3.00, 15.00),
        "claude-3-5-haiku": (0.80, 4.00),
        # Google Gemini models
        "gemini-1.5-pro": (1.25, 5.00),
        "gemini-1.5-flash": (0.075, 0.30),
        "gemini-2.0-flash": (0.075, 0.30),
        "gemini-3.8-flash": (0.075, 0.30),
        "openai/gpt-oss-120b": (0.0, 0.0),
        # DeepSeek models
        "deepseek-v3": (0.14, 0.28),
        "deepseek-chat": (0.14, 0.28),
        "deepseek/deepseek-chat": (0.14, 0.28),
        "deepseek-r1": (0.55, 2.19),
        "deepseek/deepseek-r1": (0.55, 2.19),
        # Qwen models (Alibaba Cloud / DashScope / OpenRouter)
        "qwen-2.5-72b-instruct": (0.35, 0.70),
        "qwen/qwen-2.5-72b-instruct": (0.35, 0.70),
        "qwen-2.5-32b-instruct": (0.20, 0.40),
        "qwen-2.5-7b-instruct": (0.05, 0.10),
        "qwen/qwen-2.5-7b-instruct": (0.05, 0.10),
        "qwen": (0.35, 0.70),
        # Kimi models (Moonshot AI K2 / K2.6)
        "kimi-k2.6": (0.60, 2.40),
        "kimi-k2": (0.60, 2.40),
        "moonshot-v1-32k": (0.60, 2.40),
        "kimi": (0.60, 2.40),
        # Groq models
        "llama-3.3-70b-versatile": (0.59, 0.79),
        "mixtral-8x7b-32768": (0.24, 0.24),
        # xAI Grok
        "grok-2": (2.00, 10.00),
        # OpenRouter free models
        "meta-llama/llama-3.1-8b-instruct:free": (0.0, 0.0),
        "qwen/qwen-2.5-7b-instruct:free": (0.0, 0.0),
        # Local & Mock
        "ollama-local": (0.0, 0.0),
        "phi3:latest": (0.0, 0.0),
        "llama3:latest": (0.0, 0.0),
        "mistral:latest": (0.0, 0.0),
        "vllm-local": (0.0, 0.0),
        "mock": (0.0, 0.0),
        "local": (0.0, 0.0),
        "mock-fast": (0.0, 0.0),
        "mock-reasoning": (0.0, 0.0),
        "mock-deterministic": (0.0, 0.0),
    }

    @classmethod
    def estimate_cost(cls, model_name: str, usage: TokenUsage) -> float:
        """Calculate estimated cost in USD based on model rates."""
        clean_name = model_name.lower().strip()
        rate = cls.RATES.get(clean_name)
        if not rate:
            for known_key, known_rate in cls.RATES.items():
                if known_key in clean_name:
                    rate = known_rate
                    break
        if not rate:
            rate = (0.0, 0.0)

        prompt_cost = (usage.prompt_tokens / 1_000_000.0) * rate[0]
        completion_cost = (usage.completion_tokens / 1_000_000.0) * rate[1]
        return round(prompt_cost + completion_cost, 6)


class LLMRequest(BaseModel):
    """
    Vendor-agnostic request envelope passed into the LLM Interface and Model Router.
    """
    task_category: LLMTaskCategory | str
    prompt: str
    system_prompt: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_seconds: float | None = None
    schema_model: str | None = None
    preferred_tier: ModelTier | None = None
    preferred_lane: IntelligenceLane | None = None
    required_capabilities: set[ModelCapability] = Field(default_factory=set)
    is_deterministic_numerical_request: bool = False
    enforce_deterministic_invariants: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """
    Vendor-agnostic response envelope returned by the Model Router and LLM Interface.
    """
    content: str
    parsed_data: dict[str, Any] | None = None
    task_category: LLMTaskCategory
    model_name: str
    provider_name: str
    tier: ModelTier
    lane: IntelligenceLane | None = None
    capabilities_matched: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    usage: TokenUsage = Field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0
    is_fallback: bool = False
    fallback_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    bypassed_llm_for_deterministic: bool = False
    quota_remaining_requests: int | None = None


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------

class LLMProviderError(Exception):
    """Base exception for all LLM provider and routing errors."""
    pass


class LLMProviderTimeoutError(LLMProviderError):
    """Raised when an LLM provider request exceeds its configured timeout window."""
    pass


class LLMProviderUnavailableError(LLMProviderError):
    """Raised when an LLM provider is unconfigured, unreachable, or network fails."""
    pass


class MalformedLLMResponseError(LLMProviderError):
    """Raised when an LLM provider produces unparseable JSON or invalid payload."""
    pass


class UnsupportedLLMTaskError(LLMProviderError):
    """Raised when a requested task category is unrecognized or unsupported."""
    pass


class LLMSafetyGuardViolationError(LLMProviderError):
    """Raised when an external paid LLM call is attempted without explicit authorization."""
    pass


class DeterministicInvariantViolationError(LLMProviderError):
    """
    Raised when an LLM call violates the core invariant:
    Deterministic calculations must be executed via SQL/Python/statistics/ML,
    never computed independently by the language model.
    """
    pass
