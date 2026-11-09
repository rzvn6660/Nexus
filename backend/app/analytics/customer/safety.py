"""
NEXUS Phase 1H.2 — Controlled Pilot Safety Gates.

Enforces application-level safeguards for customer purchase cadence analytics:
1. Watermark Readiness Gate: Evaluates authoritative ingestion watermarks, temporal boundaries,
   and cohort adequacy to determine whether cadence risk is ACTIONABLE or DIAGNOSTIC_ONLY.
2. Seasonal Caution Disclosure: Surfaces explicit contextual warnings for seasonal and uncharacterized
   retail contexts without falsely attributing seasonal status to individual customers.
3. Human-Review-Only Action Gate: Prevents automated customer outreach, discounting, or termination
   by failing closed unless an explicit, auditable human approval record is verified.
"""

import os
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.core.context import AnalysisContext
from app.analytics.customer.cadence import (
    CadenceConfig,
    CadenceRiskTier,
    CustomerCadenceAnalyzer,
    CustomerCadenceRecord,
    CustomerCadenceSummary,
)
from app.models.customer import Customer
from app.models.history import DecisionRecord
from app.models.sale import Sale
from app.models.tenant import Business
from app.services.watermark_service import EffectiveWatermarkResult, WatermarkService


class CadenceEligibilityStatus(str, Enum):
    """Eligibility classification for customer purchase cadence analytics."""

    ACTIONABLE = "actionable"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    BLOCKED = "blocked"


class SafetyReasonCode(str, Enum):
    """Machine-readable reason codes explaining safety gate evaluation."""

    VERIFIED_ACTIONABLE = "VERIFIED_ACTIONABLE"
    DEMO_SYNTHETIC = "DEMO_SYNTHETIC"
    MISSING_WATERMARK = "MISSING_WATERMARK"
    PROVISIONAL_WATERMARK = "PROVISIONAL_WATERMARK"
    INVALIDATED_WATERMARK = "INVALIDATED_WATERMARK"
    STALE_WATERMARK = "STALE_WATERMARK"
    INCOMPLETE_IN_FLIGHT_JOBS = "INCOMPLETE_IN_FLIGHT_JOBS"
    INCOMPLETE_SOURCE_BOUNDARIES = "INCOMPLETE_SOURCE_BOUNDARIES"
    CUTOFF_EXCEEDS_WATERMARK = "CUTOFF_EXCEEDS_WATERMARK"
    INSUFFICIENT_REPEAT_COHORT = "INSUFFICIENT_REPEAT_COHORT"
    UNAUTHORIZED_TENANT = "UNAUTHORIZED_TENANT"
    SYNTHETIC_PROVENANCE_PROHIBITED = "SYNTHETIC_PROVENANCE_PROHIBITED"


class SeasonalContextType(str, Enum):
    """Classification of tenant seasonality."""

    CONFIRMED_SEASONAL = "confirmed_seasonal"
    CONFIRMED_NON_SEASONAL = "confirmed_non_seasonal"
    UNKNOWN_SEASONAL_CONTEXT = "unknown_seasonal_context"


class SeasonalCautionDisclosure(BaseModel):
    """Visible seasonal context disclosure for customer cadence analytics."""

    has_seasonal_caution: bool = Field(
        description="Whether a seasonal caution advisory applies to this business."
    )
    context_type: SeasonalContextType = Field(
        description="Tenant seasonal classification: confirmed_seasonal, confirmed_non_seasonal, or unknown_seasonal_context."
    )
    caution_title: str | None = Field(
        default=None,
        description="Short human-readable title for UI banner display.",
    )
    caution_message: str | None = Field(
        default=None,
        description="Detailed contextual advisory explaining that dormancy may resemble churn.",
    )
    customer_level_claim_permitted: bool = Field(
        default=False,
        description="Strict safety invariant: individual customers must not be classified as seasonal without verified order-level evidence.",
    )
    advisory_notes: list[str] = Field(
        default_factory=list,
        description="Key operational reminders for reviewers.",
    )


class CadenceSafetyVerdict(BaseModel):
    """Structured decision explaining whether cadence risk metrics are actionable."""

    eligibility_status: CadenceEligibilityStatus = Field(
        description="Eligibility decision: 'actionable', 'diagnostic_only', or 'blocked'."
    )
    is_actionable: bool = Field(
        description="Whether cadence risk tiers may be used for operational decision-making."
    )
    reason_code: SafetyReasonCode = Field(
        description="Machine-readable code identifying the governing gate decision."
    )
    explanation: str = Field(
        description="Human-readable explanation of why this eligibility status was assigned."
    )
    non_actionable_notice: str | None = Field(
        default=None,
        description="Mandatory disclaimer attached when eligibility is diagnostic_only.",
    )
    effective_watermark_status: str | None = Field(
        default=None,
        description="Verification state of tenant ingestion watermarks.",
    )
    effective_complete_through_dt: str | None = Field(
        default=None,
        description="Certified completeness boundary (ISO-8601 UTC) if verified.",
    )
    as_of_date_requested: str = Field(
        description="Evaluation cutoff date evaluated against watermark."
    )
    eligible_repeat_buyers_count: int = Field(
        default=0,
        description="Observed repeat buyer cohort count at or before cutoff.",
    )
    min_required_repeat_buyers: int = Field(
        default=30,
        description="Minimum repeat buyers required for controlled pilot eligibility.",
    )
    seasonal_disclosure: SeasonalCautionDisclosure = Field(
        description="Seasonal purchasing pattern advisory."
    )
    human_review_policy: str = Field(
        default=(
            "Cadence risk tiers must never trigger automated customer outreach, discounting, "
            "or account termination. Explicit human review and approval is required for all customer-facing interventions."
        ),
        description="Mandatory human-in-the-loop policy statement.",
    )
    diagnostic_details: dict[str, Any] = Field(
        default_factory=dict,
        description="Telemetry and diagnostics preserved for authorized analysts.",
    )


class ActionExecutionStatus(str, Enum):
    """Outcome status for customer action authorization requests."""

    APPROVED_FOR_EXECUTION = "approved_for_execution"
    BLOCKED_AUTOMATION_PROHIBITED = "blocked_automation_prohibited"
    BLOCKED_UNAPPROVED = "blocked_unapproved"
    BLOCKED_MISSING_REVIEWER = "blocked_missing_reviewer"
    BLOCKED_TENANT_VIOLATION = "blocked_tenant_violation"


class ActionExecutionResult(BaseModel):
    """Auditable result of evaluating an action authorization request."""

    status: ActionExecutionStatus
    is_allowed: bool
    reason: str
    decision_id: int | None = None
    action_type: str
    actor_id: str | None = None
    actor_is_human: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class CadenceSafetyGate:
    """Central evaluator for cadence analysis readiness, seasonal caution, and action gating."""

    MIN_PILOT_REPEAT_BUYERS: int = 30
    DEFAULT_MAX_STALENESS_DAYS: int = 90

    @classmethod
    def resolve_seasonal_context(
        cls,
        session: Session,
        business_id: str,
        configured_context: str | None = None,
    ) -> SeasonalCautionDisclosure:
        """
        Resolve seasonal context for a tenant without inventing ungrounded customer claims.
        """
        # 1. Explicit configuration takes precedence if valid
        if configured_context:
            clean_ctx = configured_context.strip().lower()
            if clean_ctx in {"seasonal", "confirmed_seasonal"}:
                return SeasonalCautionDisclosure(
                    has_seasonal_caution=True,
                    context_type=SeasonalContextType.CONFIRMED_SEASONAL,
                    caution_title="Seasonal Retail Inactivity Advisory",
                    caution_message=(
                        "This business operates in a confirmed seasonal retail context. Prolonged intervals "
                        "between purchases often reflect annual demand cycles or holiday purchasing rather "
                        "than customer churn. Individual customer records should not be classified as churned "
                        "without season-adjusted evidence."
                    ),
                    customer_level_claim_permitted=False,
                    advisory_notes=[
                        "Annual purchasing cycles naturally produce extended inter-purchase intervals.",
                        "Do not assume individual customer dormancy represents permanent attrition.",
                    ],
                )
            if clean_ctx in {"non_seasonal", "confirmed_non_seasonal"}:
                return SeasonalCautionDisclosure(
                    has_seasonal_caution=False,
                    context_type=SeasonalContextType.CONFIRMED_NON_SEASONAL,
                    caution_title=None,
                    caution_message=None,
                    customer_level_claim_permitted=False,
                    advisory_notes=[],
                )
            if clean_ctx in {"unknown", "unknown_seasonal_context"}:
                return SeasonalCautionDisclosure(
                    has_seasonal_caution=True,
                    context_type=SeasonalContextType.UNKNOWN_SEASONAL_CONTEXT,
                    caution_title="Uncharacterized Seasonality Disclosure",
                    caution_message=(
                        "Seasonal purchasing patterns have not been empirically calibrated for this business. "
                        "Observed customer inactivity may be driven by annual dormancy or periodic buying cycles "
                        "rather than true churn. Treat cadence risk tiers with caution."
                    ),
                    customer_level_claim_permitted=False,
                    advisory_notes=[
                        "Seasonality is uncharacterized; inactivity cannot be definitively attributed to churn.",
                        "Individual customer seasonal classification is prohibited without explicit transaction history evidence.",
                    ],
                )

        # 2. Inspect Business industry
        biz = session.execute(
            select(Business).where(Business.id == business_id)
        ).scalar_one_or_none()

        industry = (biz.industry or "").lower() if biz else ""
        name = (biz.name or "").lower() if biz else ""

        # Retail context check: default to UNKNOWN_SEASONAL_CONTEXT with cautious disclosure
        # We do NOT hardcode confirmed seasonality without evidence
        is_retail = any(
            term in industry or term in name
            for term in ["retail", "commerce", "specialty", "apparel", "ecommerce", "goods", "shop"]
        )

        if is_retail:
            return SeasonalCautionDisclosure(
                has_seasonal_caution=True,
                context_type=SeasonalContextType.UNKNOWN_SEASONAL_CONTEXT,
                caution_title="Retail Seasonality Advisory",
                caution_message=(
                    "This business operates in a retail environment where seasonal purchasing cycles (e.g. holidays, "
                    "annual promotions, seasonal goods) commonly produce extended dormancy. Heuristic cadence metrics "
                    "cannot distinguish seasonal pauses from customer attrition without empirical time-series decomposition."
                ),
                customer_level_claim_permitted=False,
                advisory_notes=[
                    "Retail inactivity often reflects natural buying cycles rather than churn.",
                    "Review customer history manually before concluding an account is at risk.",
                ],
            )

        # Non-retail or unknown industry: cautious uncharacterized disclosure
        return SeasonalCautionDisclosure(
            has_seasonal_caution=True,
            context_type=SeasonalContextType.UNKNOWN_SEASONAL_CONTEXT,
            caution_title="Uncharacterized Operating Context",
            caution_message=(
                "Operating seasonality and purchase cycle dynamics have not been calibrated for this tenant. "
                "Cadence ratios reflect heuristic recency vs observed historical intervals only."
            ),
            customer_level_claim_permitted=False,
            advisory_notes=[
                "Individual seasonal classification is prohibited.",
            ],
        )

    @classmethod
    def evaluate_tenant_safety(
        cls,
        session: Session,
        business_id: str,
        as_of_date: datetime | date | None = None,
        required_sources: list[str] | None = None,
        max_staleness_days: int | None = 90,
        seasonal_context: str | None = None,
        min_repeat_buyers: int = 30,
    ) -> CadenceSafetyVerdict:
        """
        Evaluate all application-level safeguards for customer cadence analytics.

        Parameters:
            session: Active database session.
            business_id: Authorized tenant identifier.
            as_of_date: Requested evaluation cutoff timestamp.
            required_sources: List of required ingestion sources for watermark check.
            max_staleness_days: Maximum allowable watermark age in days.
            seasonal_context: Explicit override for seasonal context ('seasonal', 'non_seasonal', 'unknown').
            min_repeat_buyers: Minimum eligible repeat buyer cohort size for actionable pilot.
        """
        # 1. Tenant Scoping and Authorization
        if not business_id or not business_id.strip():
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.BLOCKED,
                is_actionable=False,
                reason_code=SafetyReasonCode.UNAUTHORIZED_TENANT,
                explanation="Tenant business_id must be provided.",
                non_actionable_notice="BLOCKED: Tenant access unverified.",
                as_of_date_requested=datetime.now(UTC).isoformat(),
                seasonal_disclosure=SeasonalCautionDisclosure(
                    has_seasonal_caution=False,
                    context_type=SeasonalContextType.UNKNOWN_SEASONAL_CONTEXT,
                ),
            )

        biz = session.execute(
            select(Business).where(Business.id == business_id)
        ).scalar_one_or_none()

        if not biz:
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.BLOCKED,
                is_actionable=False,
                reason_code=SafetyReasonCode.UNAUTHORIZED_TENANT,
                explanation=f"Business '{business_id}' does not exist or access is unauthorized.",
                non_actionable_notice="BLOCKED: Unauthorized business boundary.",
                as_of_date_requested=datetime.now(UTC).isoformat(),
                seasonal_disclosure=SeasonalCautionDisclosure(
                    has_seasonal_caution=False,
                    context_type=SeasonalContextType.UNKNOWN_SEASONAL_CONTEXT,
                ),
            )

        # 2. Normalize requested evaluation cutoff
        if as_of_date is not None:
            if isinstance(as_of_date, datetime):
                ref_dt = as_of_date if as_of_date.tzinfo is not None else as_of_date.replace(tzinfo=UTC)
                ref_dt = ref_dt.astimezone(UTC)
            elif isinstance(as_of_date, date):
                ref_dt = datetime.combine(as_of_date, datetime.max.time().replace(microsecond=0), tzinfo=UTC)
            else:
                ref_dt = datetime.now(UTC)
        else:
            latest_txn = session.execute(
                select(func.max(Sale.transaction_date)).where(Sale.business_id == business_id)
            ).scalar()
            now_utc = datetime.now(UTC)
            if latest_txn:
                latest_utc = latest_txn if latest_txn.tzinfo is not None else latest_txn.replace(tzinfo=UTC)
                if (now_utc - latest_utc).days > 30:
                    ref_dt = latest_utc
                else:
                    ref_dt = now_utc
            else:
                ref_dt = now_utc

        ref_dt_iso = ref_dt.isoformat()

        # 3. Resolve Seasonal Caution Disclosure
        seasonal_disclosure = cls.resolve_seasonal_context(session, business_id, seasonal_context)

        # 4. Evaluate Effective Ingestion Watermark
        effective_wm: EffectiveWatermarkResult = WatermarkService.get_effective_tenant_watermark(
            session=session,
            business_id=business_id,
            required_sources=required_sources,
            max_staleness_days=max_staleness_days,
        )

        wm_complete_iso = (
            effective_wm.effective_complete_through_dt.isoformat()
            if effective_wm.effective_complete_through_dt
            else None
        )

        # 5. Query Observed Repeat Buyer Cohort Size at/before cutoff
        repeat_buyer_stmt = (
            select(Sale.customer_id)
            .where(
                Sale.business_id == business_id,
                Sale.transaction_date <= ref_dt,
                Sale.status.in_(["completed", "shipped"]),
                Sale.customer_id.is_not(None),
            )
            .group_by(Sale.customer_id)
            .having(func.count(func.distinct(Sale.transaction_date)) >= 2)
        )
        repeat_buyers_count = len(session.execute(repeat_buyer_stmt).all())

        diagnostic_details = {
            "business_id": business_id,
            "business_name": biz.name,
            "business_industry": biz.industry,
            "watermark_status": effective_wm.status,
            "effective_complete_through_dt": wm_complete_iso,
            "unverified_sources": effective_wm.unverified_sources,
            "source_watermarks": effective_wm.source_watermarks,
            "in_flight_or_failed_jobs_count": effective_wm.in_flight_or_failed_jobs_count,
            "blocking_reasons": effective_wm.blocking_reasons,
            "watermark_is_stale": effective_wm.is_stale,
            "watermark_stale_warning": effective_wm.stale_warning,
            "observed_repeat_buyers_at_cutoff": repeat_buyers_count,
        }

        # --- GATE EVALUATION SEQUENCE ---

        # Gate 0: Sandbox Merchant Validation Check
        from app.services.tenant_certification_policy import TenantCertificationPolicy
        if TenantCertificationPolicy.is_sandbox_merchant(business_id, session=session):
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                is_actionable=False,
                reason_code=SafetyReasonCode.DEMO_SYNTHETIC,
                explanation=(
                    f"Business '{biz.name}' operates under controlled synthetic validation (DEMO_SYNTHETIC). "
                    "Customer cadences and risk tiers are deterministically generated for demonstration and "
                    "cannot be used for real customer outreach or retention intervention."
                ),
                non_actionable_notice=(
                    "CONTROLLED SANDBOX VALIDATION: Synthetic merchant data is isolated from automated execution. "
                    "Human review and action proposals are functional for workflow testing only."
                ),
                effective_watermark_status="DEMO_SYNTHETIC",
                effective_complete_through_dt=wm_complete_iso or (latest_txn.isoformat() if 'latest_txn' in locals() and latest_txn else None),
                as_of_date_requested=ref_dt_iso,
                eligible_repeat_buyers_count=repeat_buyers_count,
                min_required_repeat_buyers=min_repeat_buyers,
                seasonal_disclosure=seasonal_disclosure,
                diagnostic_details=diagnostic_details,
            )

        # Gate 1: Check Watermark Presence and Integrity
        if effective_wm.status == "unverified_missing":
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                is_actionable=False,
                reason_code=SafetyReasonCode.MISSING_WATERMARK,
                explanation=(
                    f"No authoritative ingestion watermark is registered for business '{biz.name}'. "
                    "Transaction completeness cannot be certified. MAX(transaction_date) will not be "
                    "substituted as an authoritative completeness boundary."
                ),
                non_actionable_notice=(
                    "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Ingestion completeness is uncertified for this tenant. "
                    "Cadence metrics are exploratory diagnostics only and must NOT be used for customer outreach, "
                    "churn alerting, or account intervention."
                ),
                effective_watermark_status=effective_wm.status,
                effective_complete_through_dt=None,
                as_of_date_requested=ref_dt_iso,
                eligible_repeat_buyers_count=repeat_buyers_count,
                min_required_repeat_buyers=min_repeat_buyers,
                seasonal_disclosure=seasonal_disclosure,
                diagnostic_details=diagnostic_details,
            )

        if effective_wm.status in {"incomplete_in_flight", "unverified_jobs_blocking"} or effective_wm.in_flight_or_failed_jobs_count > 0:
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                is_actionable=False,
                reason_code=SafetyReasonCode.INCOMPLETE_IN_FLIGHT_JOBS,
                explanation=(
                    f"Completeness verification blocked: {effective_wm.in_flight_or_failed_jobs_count} "
                    "in-flight, pending, or failed ingestion jobs exist for this tenant."
                ),
                non_actionable_notice=(
                    "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Unresolved ingestion jobs block completeness certification. "
                    "Cadence tiers are provisional and not actionable."
                ),
                effective_watermark_status=effective_wm.status,
                effective_complete_through_dt=wm_complete_iso,
                as_of_date_requested=ref_dt_iso,
                eligible_repeat_buyers_count=repeat_buyers_count,
                min_required_repeat_buyers=min_repeat_buyers,
                seasonal_disclosure=seasonal_disclosure,
                diagnostic_details=diagnostic_details,
            )

        if effective_wm.status == "invalidated" or any("invalidated" in r.lower() for r in effective_wm.blocking_reasons):
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                is_actionable=False,
                reason_code=SafetyReasonCode.INVALIDATED_WATERMARK,
                explanation=(
                    "Active ingestion watermark has been invalidated due to subsequent data corrections "
                    "or backfilled transactions."
                ),
                non_actionable_notice=(
                    "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Ingestion watermark is invalidated."
                ),
                effective_watermark_status=effective_wm.status,
                effective_complete_through_dt=wm_complete_iso,
                as_of_date_requested=ref_dt_iso,
                eligible_repeat_buyers_count=repeat_buyers_count,
                min_required_repeat_buyers=min_repeat_buyers,
                seasonal_disclosure=seasonal_disclosure,
                diagnostic_details=diagnostic_details,
            )

        if any("provisional" in r.lower() for r in effective_wm.blocking_reasons):
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                is_actionable=False,
                reason_code=SafetyReasonCode.PROVISIONAL_WATERMARK,
                explanation=(
                    "Active ingestion watermark is provisional and has not undergone post-ingestion verification."
                ),
                non_actionable_notice=(
                    "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Watermark is provisional and unpromoted."
                ),
                effective_watermark_status=effective_wm.status,
                effective_complete_through_dt=wm_complete_iso,
                as_of_date_requested=ref_dt_iso,
                eligible_repeat_buyers_count=repeat_buyers_count,
                min_required_repeat_buyers=min_repeat_buyers,
                seasonal_disclosure=seasonal_disclosure,
                diagnostic_details=diagnostic_details,
            )

        if effective_wm.status == "incomplete_watermark_gap":
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                is_actionable=False,
                reason_code=SafetyReasonCode.INCOMPLETE_SOURCE_BOUNDARIES,
                explanation=(
                    "One or more required ingestion sources lack certified active watermarks: "
                    f"{effective_wm.unverified_sources}."
                ),
                non_actionable_notice=(
                    "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Missing required source watermarks block certification."
                ),
                effective_watermark_status=effective_wm.status,
                effective_complete_through_dt=wm_complete_iso,
                as_of_date_requested=ref_dt_iso,
                eligible_repeat_buyers_count=repeat_buyers_count,
                min_required_repeat_buyers=min_repeat_buyers,
                seasonal_disclosure=seasonal_disclosure,
                diagnostic_details=diagnostic_details,
            )

        # Gate 1c: Synthetic Provenance Quarantine & Approved Provenance Validation (H2)
        active_wms = WatermarkService.get_active_watermarks(session, business_id)
        from app.services.watermark_service import ALLOWED_PROVENANCE_TYPES
        for w in active_wms:
            if w.provenance_type not in ALLOWED_PROVENANCE_TYPES:
                return CadenceSafetyVerdict(
                    eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                    is_actionable=False,
                    reason_code=SafetyReasonCode.SYNTHETIC_PROVENANCE_PROHIBITED,
                    explanation=(
                        f"Business '{biz.name}' relies on ingestion watermark with unapproved provenance_type='{w.provenance_type}'. "
                        f"Approved provenance types are: {sorted(ALLOWED_PROVENANCE_TYPES)}."
                    ),
                    non_actionable_notice=(
                        "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Unapproved watermark provenance quarantined. "
                        "Real tenant certification requires accounting_period_close or verified automated source."
                    ),
                    effective_watermark_status="unapproved_provenance_quarantined",
                    effective_complete_through_dt=wm_complete_iso,
                    as_of_date_requested=ref_dt_iso,
                    eligible_repeat_buyers_count=repeat_buyers_count,
                    min_required_repeat_buyers=min_repeat_buyers,
                    seasonal_disclosure=seasonal_disclosure,
                    diagnostic_details=diagnostic_details,
                )

        has_synthetic = any(w.provenance_type == "synthetic_fixture" for w in active_wms)
        if has_synthetic:
            from app.core.config import get_settings
            app_env = (get_settings().APP_ENV or "").lower()
            is_prod = (app_env == "production") or (os.environ.get("APP_ENV", "").lower() == "production")

            is_fixture_tenant = (
                not is_prod and (
                    business_id.startswith("biz-rh-")
                    or business_id.startswith("biz-test-")
                    or "rehearsal" in (biz.name or "").lower()
                    or "fixture" in (biz.name or "").lower()
                    or "synthetic" in (biz.name or "").lower()
                )
            )
            if not is_fixture_tenant:
                explanation = (
                    "Synthetic provenance is strictly prohibited in production environments, even for test fixtures."
                    if is_prod
                    else (
                        f"Business '{biz.name}' relies on ingestion watermark with provenance_type='synthetic_fixture'. "
                        "Synthetic fixtures are quarantined and cannot establish actionable pilot eligibility for real customer tenants."
                    )
                )
                return CadenceSafetyVerdict(
                    eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                    is_actionable=False,
                    reason_code=SafetyReasonCode.SYNTHETIC_PROVENANCE_PROHIBITED,
                    explanation=explanation,
                    non_actionable_notice=(
                        "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Synthetic provenance quarantined. "
                        "Real tenant certification requires accounting_period_close or verified automated source."
                    ),
                    effective_watermark_status="synthetic_quarantined",
                    effective_complete_through_dt=wm_complete_iso,
                    as_of_date_requested=ref_dt_iso,
                    eligible_repeat_buyers_count=repeat_buyers_count,
                    min_required_repeat_buyers=min_repeat_buyers,
                    seasonal_disclosure=seasonal_disclosure,
                    diagnostic_details=diagnostic_details,
                )

        # Gate 2: Check Evaluation Cutoff vs Certified Completeness Boundary
        if effective_wm.effective_complete_through_dt:
            if ref_dt > effective_wm.effective_complete_through_dt:
                return CadenceSafetyVerdict(
                    eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                    is_actionable=False,
                    reason_code=SafetyReasonCode.CUTOFF_EXCEEDS_WATERMARK,
                    explanation=(
                        f"Requested evaluation cutoff ({ref_dt_iso}) extends beyond the certified complete-through "
                        f"boundary ({wm_complete_iso}). Data between the watermark and cutoff may be incomplete, "
                        "which can falsely produce inactivity signals."
                    ),
                    non_actionable_notice=(
                        "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Evaluation cutoff exceeds certified completeness. "
                        "Unreceived transactions cannot be distinguished from customer inactivity."
                    ),
                    effective_watermark_status=effective_wm.status,
                    effective_complete_through_dt=wm_complete_iso,
                    as_of_date_requested=ref_dt_iso,
                    eligible_repeat_buyers_count=repeat_buyers_count,
                    min_required_repeat_buyers=min_repeat_buyers,
                    seasonal_disclosure=seasonal_disclosure,
                    diagnostic_details=diagnostic_details,
                )

        # Gate 3: Staleness Check
        if effective_wm.is_stale:
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                is_actionable=False,
                reason_code=SafetyReasonCode.STALE_WATERMARK,
                explanation=(
                    f"Watermark boundary exceeds maximum staleness window ({effective_wm.stale_warning}). "
                    "Stale watermarks cannot certify current customer cadence."
                ),
                non_actionable_notice=(
                    "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Watermark staleness threshold exceeded."
                ),
                effective_watermark_status=effective_wm.status,
                effective_complete_through_dt=wm_complete_iso,
                as_of_date_requested=ref_dt_iso,
                eligible_repeat_buyers_count=repeat_buyers_count,
                min_required_repeat_buyers=min_repeat_buyers,
                seasonal_disclosure=seasonal_disclosure,
                diagnostic_details=diagnostic_details,
            )

        # Gate 4: Check Repeat Buyer Cohort Adequacy for Controlled Pilot
        if repeat_buyers_count < min_repeat_buyers:
            return CadenceSafetyVerdict(
                eligibility_status=CadenceEligibilityStatus.DIAGNOSTIC_ONLY,
                is_actionable=False,
                reason_code=SafetyReasonCode.INSUFFICIENT_REPEAT_COHORT,
                explanation=(
                    f"Observed repeat buyer cohort at cutoff ({repeat_buyers_count}) is below the required "
                    f"controlled-pilot minimum threshold of {min_repeat_buyers}. Statistical power is inadequate "
                    "for actionable pilot deployment."
                ),
                non_actionable_notice=(
                    "NON-ACTIONABLE DIAGNOSTIC TELEMETRY: Cohort sample size below pilot minimum threshold."
                ),
                effective_watermark_status=effective_wm.status,
                effective_complete_through_dt=wm_complete_iso,
                as_of_date_requested=ref_dt_iso,
                eligible_repeat_buyers_count=repeat_buyers_count,
                min_required_repeat_buyers=min_repeat_buyers,
                seasonal_disclosure=seasonal_disclosure,
                diagnostic_details=diagnostic_details,
            )

        # Gate 5: All Criteria Satisfied -> ACTIONABLE
        return CadenceSafetyVerdict(
            eligibility_status=CadenceEligibilityStatus.ACTIONABLE,
            is_actionable=True,
            reason_code=SafetyReasonCode.VERIFIED_ACTIONABLE,
            explanation=(
                f"Tenant transaction data is certified complete through {wm_complete_iso}. "
                f"Evaluation cutoff is within boundary and repeat buyer cohort ({repeat_buyers_count}) "
                f"meets the pilot requirement (>= {min_repeat_buyers})."
            ),
            non_actionable_notice=None,
            effective_watermark_status=effective_wm.status,
            effective_complete_through_dt=wm_complete_iso,
            as_of_date_requested=ref_dt_iso,
            eligible_repeat_buyers_count=repeat_buyers_count,
            min_required_repeat_buyers=min_repeat_buyers,
            seasonal_disclosure=seasonal_disclosure,
            diagnostic_details=diagnostic_details,
        )

    @classmethod
    def evaluate_customer_cadence_with_safety(
        cls,
        session: Session,
        business_id: str,
        as_of_date: datetime | date | None = None,
        config: CadenceConfig | None = None,
        required_sources: list[str] | None = None,
        max_staleness_days: int | None = 90,
        seasonal_context: str | None = None,
        min_repeat_buyers: int = 30,
    ) -> tuple[CustomerCadenceSummary, CadenceSafetyVerdict]:
        """
        Evaluate customer cadence while applying strict watermark readiness, seasonal context,
        and actionability gating.
        """
        verdict = cls.evaluate_tenant_safety(
            session=session,
            business_id=business_id,
            as_of_date=as_of_date,
            required_sources=required_sources,
            max_staleness_days=max_staleness_days,
            seasonal_context=seasonal_context,
            min_repeat_buyers=min_repeat_buyers,
        )

        if verdict.eligibility_status == CadenceEligibilityStatus.BLOCKED:
            raise PermissionError(f"Access to business '{business_id}' is blocked: {verdict.explanation}")

        # Compute empirical cadence using standard analyzer
        context = AnalysisContext(business_id=business_id)
        effective_cutoff = as_of_date if as_of_date is not None else datetime.fromisoformat(verdict.as_of_date_requested)
        summary = CustomerCadenceAnalyzer.evaluate(
            session=session,
            context=context,
            as_of_date=effective_cutoff,
            config=config,
        )

        # Enforce safety modifications on summary records
        if not verdict.is_actionable:
            # Add safety advisory to summary limitations
            summary.limitations.insert(
                0,
                f"SAFETY GATE ENGAGED [{verdict.reason_code.value}]: {verdict.explanation}"
            )
            if verdict.non_actionable_notice:
                summary.limitations.insert(1, verdict.non_actionable_notice)

        if verdict.seasonal_disclosure.has_seasonal_caution:
            if verdict.seasonal_disclosure.caution_message:
                summary.limitations.append(
                    f"SEASONAL ADVISORY: {verdict.seasonal_disclosure.caution_message}"
                )

        return summary, verdict


class CadenceActionGate:
    """Enforces human-review-only policy for customer cadence actions."""

    @classmethod
    def evaluate_action_eligibility(
        cls,
        session: Session,
        business_id: str,
        action_type: str,
        decision_id: int | None = None,
        reviewer_id: str | None = None,
        is_automated_caller: bool = False,
    ) -> ActionExecutionResult:
        """
        Enforce that cadence risk tiers cannot trigger automated customer actions.

        Fails closed unless an explicit human approval record (DecisionRecord) exists
        with status == 'APPROVED' and a non-automated reviewer.
        """
        # 1. Reject automated callers unconditionally
        if is_automated_caller:
            return ActionExecutionResult(
                status=ActionExecutionStatus.BLOCKED_AUTOMATION_PROHIBITED,
                is_allowed=False,
                reason=(
                    "Automated customer interventions (emails, notifications, discounts, or account termination) "
                    "triggered by customer cadence risk tiers are strictly prohibited. Explicit human review is mandatory."
                ),
                decision_id=decision_id,
                action_type=action_type,
                actor_id=reviewer_id,
                actor_is_human=False,
            )

        # 2. Require an approved DecisionRecord
        if decision_id is None:
            return ActionExecutionResult(
                status=ActionExecutionStatus.BLOCKED_UNAPPROVED,
                is_allowed=False,
                reason=(
                    "Consequential customer actions require an approved DecisionRecord. "
                    "No decision_id was supplied."
                ),
                decision_id=None,
                action_type=action_type,
                actor_id=reviewer_id,
                actor_is_human=False,
            )

        # Query DecisionRecord with strict tenant scoping
        record = session.execute(
            select(DecisionRecord).where(DecisionRecord.id == decision_id)
        ).scalar_one_or_none()

        if not record:
            return ActionExecutionResult(
                status=ActionExecutionStatus.BLOCKED_UNAPPROVED,
                is_allowed=False,
                reason=f"DecisionRecord '{decision_id}' does not exist.",
                decision_id=decision_id,
                action_type=action_type,
                actor_id=reviewer_id,
                actor_is_human=False,
            )

        if record.business_id != business_id:
            return ActionExecutionResult(
                status=ActionExecutionStatus.BLOCKED_TENANT_VIOLATION,
                is_allowed=False,
                reason=(
                    f"Tenant isolation violation: DecisionRecord {decision_id} belongs to "
                    f"business '{record.business_id}', not '{business_id}'."
                ),
                decision_id=decision_id,
                action_type=action_type,
                actor_id=reviewer_id,
                actor_is_human=False,
            )

        # Check approval status
        if record.status != "APPROVED":
            return ActionExecutionResult(
                status=ActionExecutionStatus.BLOCKED_UNAPPROVED,
                is_allowed=False,
                reason=(
                    f"DecisionRecord {decision_id} has status '{record.status}'. "
                    "Only APPROVED decisions may proceed to execution."
                ),
                decision_id=decision_id,
                action_type=action_type,
                actor_id=reviewer_id,
                actor_is_human=False,
            )

        # Check reviewer identity
        effective_reviewer = reviewer_id or record.reviewed_by
        if not effective_reviewer or effective_reviewer.strip().lower() in {"system", "bot", "auto", "cron", "agent"}:
            return ActionExecutionResult(
                status=ActionExecutionStatus.BLOCKED_MISSING_REVIEWER,
                is_allowed=False,
                reason="DecisionRecord missing verified human reviewer identity.",
                decision_id=decision_id,
                action_type=action_type,
                actor_id=effective_reviewer,
                actor_is_human=False,
            )

        # Passed all human-review checks
        return ActionExecutionResult(
            status=ActionExecutionStatus.APPROVED_FOR_EXECUTION,
            is_allowed=True,
            reason=f"Action '{action_type}' authorized via approved human DecisionRecord {decision_id} by {effective_reviewer}.",
            decision_id=decision_id,
            action_type=action_type,
            actor_id=effective_reviewer,
            actor_is_human=True,
        )
