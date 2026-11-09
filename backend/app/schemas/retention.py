"""Pydantic schemas and contracts for NEXUS Intelligent Churn Prediction & Customer Retention.

Covers the Five Essential Customer Retention Capabilities:
A. Which customers are at risk (risk tiers, cohort distribution, attention required)?
B. Why is each customer at risk (factual observed history, cadence deviation, behavioral change)?
C. How serious is the risk (multi-dimensional severity, confidence, evidence sufficiency)?
D. When should the merchant act (actionable intervention timing without false urgency)?
E. What can the merchant do (contextual practical retention recommendations with HITL gating)?
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.customer.cadence import CadenceRiskTier
from app.analytics.customer.safety import CadenceSafetyVerdict


class RetentionActionType(str, Enum):
    """Contextual commercial action alternatives for customer retention."""

    PERSONAL_FOLLOW_UP = "personal_follow_up"
    PRODUCT_RECOMMENDATION = "product_recommendation"
    REENGAGEMENT_CHECKIN = "reengagement_checkin"
    SERVICE_EXPERIENCE_REVIEW = "service_experience_review"
    LOYALTY_RETENTION_OFFER = "loyalty_retention_offer"
    ONBOARDING_NURTURE = "onboarding_nurture"
    MONITOR_ONLY = "monitor_only"


class InterventionUrgency(str, Enum):
    """Actionable intervention timing based on customer purchase cadence and recency."""

    IMMEDIATE = "immediate"  # Cadence ratio >= 3.0x (Critical: Contact within 7 days)
    PROACTIVE = "proactive"  # Cadence ratio 2.0x - 3.0x (High: Optimal window 14 days)
    WATCHLIST = "watchlist"  # Cadence ratio 1.25x - 2.0x (Medium: Monitor 30 days)
    HEALTHY = "healthy"  # Cadence ratio < 1.25x (Low: On track)
    INSUFFICIENT_HISTORY = "insufficient_history"  # < 2 distinct completed purchases


class RetentionConfidenceLevel(str, Enum):
    """Confidence rating based on observed history and interval count."""

    HIGH = "high"  # >= 5 distinct completed purchase events
    MEDIUM = "medium"  # 3 - 4 distinct completed purchase events
    LOW = "low"  # 2 distinct completed purchase events (minimal repeat baseline)
    INSUFFICIENT_HISTORY = "insufficient_history"  # < 2 distinct events (one-time or zero)


class CustomerRetentionRecommendation(BaseModel):
    """Prescriptive retention recommendation for a specific customer."""

    model_config = ConfigDict(extra="ignore")

    recommendation_id: str = Field(description="Unique recommendation identifier (e.g. REC-RET-XXXX).")
    customer_id: int
    customer_code: str
    customer_name: str
    action_type: RetentionActionType
    title: str
    summary: str
    urgency: InterventionUrgency
    recommended_window: str = Field(description="Actionable timeframe for merchant intervention.")
    suggested_channel: str = Field(description="Recommended communication channel.")
    action_steps: list[str] = Field(default_factory=list, description="Step-by-step guidance for merchant.")
    rationale: str = Field(description="Why this specific action fits this customer's profile.")
    trade_offs: list[str] = Field(default_factory=list, description="Commercial trade-offs and operational risks.")
    estimated_cost_usd: float = Field(default=0.0, description="Estimated direct expense or discount cost.")
    expected_margin_impact_usd: float = Field(default=0.0, description="Expected net gross margin delta if retained.")
    requires_human_approval: bool = Field(
        default=True,
        description="Strict safety invariant: Automated execution is prohibited; merchant approval required.",
    )
    decision_record_id: int | None = Field(default=None, description="Linked DecisionRecord ID if persisted.")
    decision_status: str | None = Field(
        default=None, description="Current HITL status (PENDING, APPROVED, REJECTED, MODIFIED, DEFERRED)."
    )


class CustomerRiskDetail(BaseModel):
    """Comprehensive customer-level risk profile uniting facts, cadence metrics, and retention proposals."""

    model_config = ConfigDict(extra="ignore")

    # Identity
    customer_id: int
    customer_code: str
    customer_name: str
    customer_segment: str | None = None
    email: str | None = None
    city: str | None = None
    acquisition_date: str | None = None

    # Observed Facts (Verifiable historical records)
    total_lifetime_orders: int
    distinct_purchase_dates: int
    total_lifetime_spend: float
    average_order_value: float
    last_purchase_date: str | None = None
    days_since_last_purchase: float | None = None
    top_categories_purchased: list[str] = Field(default_factory=list)
    recent_refund_or_cancelled_count: int = 0

    # Inferred Cadence & Risk Status
    is_repeat_buyer: bool
    baseline_cadence_days: float | None = None
    cadence_source: str
    cadence_ratio: float | None = None
    risk_tier: CadenceRiskTier
    urgency: InterventionUrgency
    evidence_sufficiency_score: float = Field(
        ge=0.0, le=1.0, description="Normalized score reflecting depth and regularity of order history."
    )
    confidence_level: RetentionConfidenceLevel
    uncertainty_notice: str = Field(
        description="Disclosure regarding non-contractual right-censoring in retail transactions."
    )

    # Behavioral Changes & Trends Over Time
    cadence_trend: str = Field(
        description="Temporal trend: 'decelerating' (intervals widening), 'stable', 'accelerating', or 'insufficient_history'."
    )
    recent_intervals_days: list[float] = Field(
        default_factory=list, description="Historical sequence of inter-purchase intervals in chronological order."
    )
    last_order_amount: float | None = None
    spend_trend: str = Field(
        description="Order value trend: 'declining', 'stable', 'increasing', or 'insufficient_history'."
    )

    # Understandable Explanations
    why_at_risk_summary: str
    risk_factors: list[str] = Field(default_factory=list)

    # Retention Action & HITL Tracking
    recommended_action: CustomerRetentionRecommendation | None = None
    existing_decision_id: int | None = None
    decision_status: str | None = None
    action_execution_status: str | None = None
    action_executed_at: str | None = None
    action_channel: str | None = None
    latest_customer_response: str | None = None
    customer_responded_at: str | None = None
    subsequent_outcome: str | None = None


class RetentionOverview(BaseModel):
    """Aggregate customer risk distribution, workload prioritization, and safety disclosures."""

    model_config = ConfigDict(extra="ignore")

    as_of_date: str
    business_id: str | None = None
    total_customers_evaluated: int
    repeat_buyers_count: int
    one_time_buyers_count: int
    zero_purchase_count: int
    risk_distribution: dict[str, int]
    urgency_distribution: dict[str, int]
    total_revenue_at_risk_usd: float = Field(
        description="Summed lifetime revenue of Critical and High risk repeat buyers."
    )
    customers_requiring_attention_count: int = Field(
        description="Total repeat buyers classified as Critical or High risk."
    )
    safety_verdict: CadenceSafetyVerdict
    data_freshness_days: float | None = None
    limitations: list[str] = Field(default_factory=list)
    total_customers: int | None = None
    active_customers_count: int | None = None

    @model_validator(mode="after")
    def populate_customer_count_aliases(self) -> "RetentionOverview":
        if self.active_customers_count is None:
            self.active_customers_count = self.total_customers_evaluated
        if self.total_customers is None:
            self.total_customers = self.total_customers_evaluated
        return self


class RetentionCustomerFilter(BaseModel):
    """Filter criteria for customer retention queries."""

    risk_tiers: list[CadenceRiskTier] | None = None
    urgencies: list[InterventionUrgency] | None = None
    segments: list[str] | None = None
    min_lifetime_spend: float | None = None
    is_repeat_only: bool = True
    requires_attention_only: bool = False
    search: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


class RetentionCustomerListResponse(BaseModel):
    """Paginated list of customer retention profiles."""

    total_count: int
    page: int
    page_size: int
    items: list[CustomerRiskDetail]


class RetentionActionCreateRequest(BaseModel):
    """Request to create and register a retention recommendation in the HITL ledger."""

    customer_id: int
    action_type: RetentionActionType | None = None
    custom_notes: str | None = None


class RetentionActionReviewRequest(BaseModel):
    """Request to record a merchant's review of a retention decision."""

    decision_id: int
    status: Literal["APPROVED", "REJECTED", "MODIFIED", "DEFERRED"]
    reviewer_notes: str | None = None
    reviewer_id: str = Field(..., min_length=1, description="Verified identity of human merchant reviewer.")
    modified_action_type: RetentionActionType | None = None
    modified_notes: str | None = None


class RetentionActionExecuteRequest(BaseModel):
    """Request to record execution of an approved customer retention action."""

    decision_id: int
    execution_channel: str = Field(..., description="Communication channel (email, phone, in_person, promo_code, etc.).")
    executed_by: str = Field(..., description="Staff member or system operator performing execution.")
    execution_notes: str | None = None
    offer_code: str | None = None
    execution_date: datetime | None = None


class RetentionCustomerResponseRequest(BaseModel):
    """Request to log a customer's subsequent behavioral response to a retention action."""

    decision_id: int
    response_status: Literal["opened", "replied", "redeemed_code", "no_response", "declined", "purchased"]
    logged_by: str
    response_notes: str | None = None
    response_date: datetime | None = None


class RetentionOutcomeEvaluation(BaseModel):
    """Empirical evaluation of customer retention interventions vs baseline and control cohorts."""

    model_config = ConfigDict(extra="ignore")

    business_id: str | None = None
    as_of_date: str
    evaluation_window_days: int
    total_actions_recorded: int
    total_actions_approved: int
    total_actions_executed: int

    # Intervention Group Metrics
    intervened_customers_count: int
    intervened_reordered_count: int
    intervened_reorder_rate_pct: float
    intervened_subsequent_revenue_usd: float

    # Non-Intervened Comparison Group (At-Risk repeat buyers with no executed action)
    comparison_customers_count: int
    comparison_reordered_count: int
    comparison_reorder_rate_pct: float

    # Lift & Efficacy
    retention_lift_pct_points: float = Field(
        description="Percentage point difference: intervened_reorder_rate_pct - comparison_reorder_rate_pct."
    )
    relative_lift_ratio: float | None = Field(
        description="intervened_reorder_rate / comparison_reorder_rate, where comparison > 0."
    )

    # Predictive Quality for Risk Signals
    precision: float | None = Field(description="Proportion of flagged customers who actually showed no repeat purchase.")
    recall: float | None = Field(description="Proportion of all churning customers correctly flagged as at-risk.")
    false_positive_rate: float | None = Field(description="Proportion of active customers incorrectly flagged as at-risk.")
    false_negative_rate: float | None = Field(description="Proportion of churning customers missed by risk filters.")
    average_lead_time_days: float | None = Field(
        description="Average days between risk alert date and customer's expected normal cycle boundary."
    )

    # Segment Breakdown
    segment_performance: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Scientific Disclosures & Limitations
    methodology_disclaimer: str = Field(
        default=(
            "Observational comparative evaluation of repeat-purchase rates between intervened at-risk customers "
            "and non-intervened cohort members over a defined post-action window. This is an empirical comparison, "
            "not a randomized controlled trial (RCT); correlation does not establish definitive causal efficacy."
        )
    )
    limitations: list[str] = Field(default_factory=list)
