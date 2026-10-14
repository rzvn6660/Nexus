"""Pydantic schemas for Phase 28 Decision Memory, Snapshots, and Audit Ledger."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RecommendationSnapshot(BaseModel):
    """Immutable snapshot of recommendation inputs, outputs, facts, and limitations."""
    model_config = ConfigDict(extra="forbid")

    recommendation_type: str = Field(..., description="Action category, e.g. INVENTORY_REORDER, PRICE_MARKDOWN")
    action_target_type: str = Field(..., description="Target entity type, e.g. SKU, CATEGORY, STORE")
    action_target_id: str = Field(..., description="Unique target identifier, e.g. SKU-PREM-101")
    point_recommendation: dict[str, Any] = Field(..., description="Concrete proposed quantities, discounts, timings")
    observed_facts: dict[str, Any] = Field(default_factory=dict, description="Empirical inputs at creation time (cost, stock, price)")
    forecast_outputs: dict[str, Any] = Field(default_factory=dict, description="Forecast point, intervals, horizon, model identifier")
    assumptions: list[str] = Field(default_factory=list, description="Explicit operational and mathematical assumptions")
    limitations: list[str] = Field(default_factory=list, description="Statistical boundaries and data disclosures")
    engine_metadata: dict[str, Any] = Field(default_factory=dict, description="Engine version, timestamp, determinism seeds")


class BaselineMetricsSnapshot(BaseModel):
    """Pre-decision operational metrics and provenance snapshot."""
    model_config = ConfigDict(extra="forbid")

    window_start: str = Field(..., description="ISO 8601 UTC start of baseline window")
    window_end: str = Field(..., description="ISO 8601 UTC end of baseline window")
    window_days: int = Field(..., ge=1, description="Length of baseline measurement window in calendar days")
    metrics: dict[str, float] = Field(..., description="Calculated metric values, e.g. baseline revenue, margin, stockouts")
    metric_definitions: dict[str, str] = Field(default_factory=dict, description="Exact formula and definition per metric")
    provenance: dict[str, Any] = Field(default_factory=dict, description="Dataset content hash, ingestion job ID, capture timestamp")


class DecisionCreatePayload(BaseModel):
    """Payload for registering a recommendation with full immutable provenance."""
    model_config = ConfigDict(extra="forbid")

    recommendation_text: str = Field(..., min_length=1, description="Human-readable recommendation summary")
    recommendation_snapshot: RecommendationSnapshot | None = Field(default=None, description="Structured snapshot of prescriptive engine output")
    baseline_metrics_snapshot: BaselineMetricsSnapshot | None = Field(default=None, description="Baseline performance snapshot")
    analysis_id: int | None = Field(default=None, description="Optional associated AnalysisRun ID")
    reviewer_notes: str | None = Field(default=None, description="Optional initial notes or context")
    outcome_window_days: int | None = Field(default=30, ge=1, description="Configured evaluation window duration in days")


class DecisionReviewPayload(BaseModel):
    """Payload for committing a Human-in-the-Loop review disposition."""
    model_config = ConfigDict(extra="forbid")

    status: Literal["APPROVED", "REJECTED", "MODIFIED", "DEFERRED"] = Field(..., description="Human review decision")
    reviewer_notes: str | None = Field(default=None, description="Analyst rationale or rejection reason")
    reviewed_by: str | None = Field(default=None, description="Reviewer identifier or email")
    modified_parameters: dict[str, Any] | None = Field(default=None, description="Adjusted parameters when status is MODIFIED")


class DecisionAuditEventResponse(BaseModel):
    """API response model for an immutable audit ledger event."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_id: int
    business_id: str
    organization_id: str
    revision: int
    event_type: str
    idempotency_key: str
    actor_id: str
    actor_role: str
    prev_event_hash: str
    event_hash: str
    canonical_payload: dict[str, Any]
    created_at: datetime


class AuditChainVerificationReport(BaseModel):
    """Integrity verification report across a decision's hash chain."""
    model_config = ConfigDict(extra="forbid")

    decision_id: int
    is_valid: bool
    total_events: int
    latest_revision: int
    error_type: str | None = None
    error_revision: int | None = None
    details: str


class EvidenceQualityGrade(str, Enum):
    """Deterministic evidence quality rating per Phase 28 rules."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OutcomeMaturityStatus(str, Enum):
    """Explicit outcome-window maturity states."""
    NOT_YET_DUE = "NOT_YET_DUE"
    DUE_INSUFFICIENT = "DUE_INSUFFICIENT"
    MATURE_SUFFICIENT = "MATURE_SUFFICIENT"
    CONFLICTING_OR_INVALID = "CONFLICTING_OR_INVALID"


class OutcomeObservationCreateRequest(BaseModel):
    """Input payload to record an empirical outcome observation."""
    model_config = ConfigDict(extra="forbid")

    metric_name: str = Field(..., min_length=1, description="Observed operational metric, e.g. revenue, stockout_days, margin")
    unit: str = Field(..., min_length=1, description="Measurement unit, e.g. USD, units, days, ratio")
    period_start: datetime = Field(..., description="UTC start of observation measurement period")
    period_end: datetime = Field(..., description="UTC end of observation measurement period")
    observed_value: float = Field(..., description="Finite empirical measured quantity")
    source: str = Field(..., min_length=1, description="System or audit source, e.g. pos_sales_stream, inventory_audit")
    dataset_version: str | None = Field(default=None, description="Optional ingestion fingerprint or version ID")
    coverage_pct: float = Field(default=100.0, ge=0.0, le=100.0, description="Data completeness percentage over period")
    is_partial: bool = Field(default=False, description="Flag indicating incomplete, early, or estimated data")
    idempotency_key: str = Field(..., min_length=1, description="Unique client key preventing duplicate recording")
    metadata: dict[str, Any] | None = Field(default=None, description="Optional contextual metadata, e.g. external confounders")


class OutcomeObservationResponse(BaseModel):
    """API response model for a recorded outcome observation."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_id: int
    business_id: str
    organization_id: str
    metric_name: str
    unit: str
    period_start: datetime
    period_end: datetime
    observed_value: float
    source: str
    dataset_version: str | None = None
    coverage_pct: float
    is_partial: bool
    actor_id: str
    actor_role: str
    idempotency_key: str
    metadata_json: dict[str, Any] | None = None
    created_at: datetime


class OutcomeActionExecutionRequest(BaseModel):
    """Input payload to record action execution or monitoring start for deferred decisions."""
    model_config = ConfigDict(extra="forbid")

    action_type: Literal["ACTION_EXECUTED", "STATUS_QUO_MONITORING_STARTED"] = Field(
        ..., description="Whether effective action occurred or explicit status-quo monitoring began"
    )
    effective_timestamp: datetime | None = Field(default=None, description="Optional explicit effective start timestamp")
    notes: str | None = Field(default=None, description="Contextual notes on action execution")
    idempotency_key: str = Field(..., min_length=1, description="Unique idempotency key")


class OutcomeEvaluationResponse(BaseModel):
    """Comprehensive outcome maturity and evidence quality evaluation report."""
    model_config = ConfigDict(extra="forbid")

    decision_id: int
    business_id: str
    metric_name: str
    unit: str
    decision_status: str
    maturity_status: OutcomeMaturityStatus
    evidence_quality: EvidenceQualityGrade
    window_started: bool
    window_start: datetime | None = None
    window_end: datetime | None = None
    window_days: int
    elapsed_days: float
    is_window_elapsed: bool
    coverage_pct: float
    observation_count: int
    pre_decision_baseline_value: float | None = None
    post_decision_observed_value: float | None = None
    observed_delta: float | None = None
    observed_pct_change: float | None = None
    is_status_quo_monitoring: bool = False
    causal_attribution_claimed: bool = False
    causal_disclaimer: str
    evidence_explanation: str
    evidence_reasons: list[str] = Field(default_factory=list, description="Explicit reasons for assigned evidence quality grade")
    evaluation_timestamp: datetime


# ---------------------------------------------------------------------------
# Phase 28 Stage 3: Decision-Memory Retrieval Schemas
# ---------------------------------------------------------------------------

class DecisionRetrievalFilter(BaseModel):
    """Filters for deterministic, tenant-scoped historical decision retrieval (Phase 28 Stage 3)."""
    model_config = ConfigDict(extra="forbid")

    recommendation_type: str | None = Field(default=None, description="Action category, e.g. INVENTORY_REORDER, PRICE_MARKDOWN")
    action_target_type: str | None = Field(default=None, description="Target entity type, e.g. SKU, CATEGORY, STORE")
    action_target_id: str | None = Field(default=None, description="Target identifier, e.g. SKU-PREM-101")
    metric_name: str | None = Field(default=None, description="Canonical metric identifier, e.g. revenue, stockout_days, margin")
    status: Literal["PENDING", "APPROVED", "REJECTED", "MODIFIED", "DEFERRED"] | None = Field(default=None, description="Human review disposition")
    is_action_executed: bool | None = Field(default=None, description="Filter by whether downstream action execution occurred")
    maturity_status: OutcomeMaturityStatus | None = Field(default=None, description="Filter by outcome maturity status")
    min_evidence_quality: EvidenceQualityGrade | None = Field(default=None, description="Minimum evidence quality threshold")
    created_after: datetime | None = Field(default=None, description="Filter decisions created at or after UTC timestamp")
    created_before: datetime | None = Field(default=None, description="Filter decisions created at or before UTC timestamp")
    limit: int = Field(default=5, ge=1, le=50, description="Maximum number of historical records to retrieve")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")


class RetrievedDecisionItem(BaseModel):
    """Structured, verified historical decision record with outcome evaluation and provenance."""
    model_config = ConfigDict(extra="forbid")

    decision_id: int
    business_id: str
    organization_id: str
    recommendation_type: str | None = None
    action_target_type: str | None = None
    action_target_id: str | None = None
    decision_status: str
    recommendation_text: str
    reviewer_notes: str | None = None
    reviewed_at: datetime | None = None
    is_action_executed: bool = False
    action_executed_at: datetime | None = None
    target_metric: str | None = None
    unit: str | None = None
    pre_decision_baseline_value: float | None = None
    post_decision_observed_value: float | None = None
    observed_delta: float | None = None
    observed_pct_change: float | None = None
    maturity_status: OutcomeMaturityStatus
    evidence_quality: EvidenceQualityGrade
    coverage_pct: float
    observation_period_start: datetime | None = None
    observation_period_end: datetime | None = None
    observation_count: int = 0
    provenance: dict[str, Any] = Field(default_factory=dict, description="Audit hash chain, revision, dataset versions, observation sources")
    is_status_quo_monitoring: bool = False
    causal_attribution_claimed: bool = False
    limitations: list[str] = Field(default_factory=list, description="Methodological caveats, sample boundaries, and evaluation disclosures")
    evidence_reasons: list[str] = Field(default_factory=list, description="Explicit reasons for evidence quality rating and maturity")
    sanitized_prompt_context: str = Field(..., description="Safely delimited and encapsulated read-only context string for planner/explainer")


class HistoricalDecisionRetrievalResponse(BaseModel):
    """Response containing retrieved historical decision items and structured planning context."""
    model_config = ConfigDict(extra="forbid")

    business_id: str
    total_found: int
    items: list[RetrievedDecisionItem]
    context_summary: str
    retrieval_query: dict[str, Any]


