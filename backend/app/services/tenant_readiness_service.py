"""NEXUS Authoritative Tenant Readiness Service.

Unified single-source-of-truth service for tenant data readiness and governance across all modules:
- Analyst Studio
- Customer Retention
- NEXUS Pulse
- Executive Dashboard & Data Gateway

Enforces the 6 distinct governance readiness states:
1. DEMO_SYNTHETIC: Deterministic synthetic sandbox tenant (isolated from live operational workflows).
2. IMPORT_COMPLETED: Raw ingestion has completed, but source boundaries & reconciliation are unverified.
3. LATEST_OBSERVED_DATE: High-water mark transaction timestamps observed, but no authoritative complete-through boundary exists.
4. SOURCE_COMPLETENESS_UNVERIFIED: Ingestion jobs, boundary gaps, or unverified watermarks exist.
5. SOURCE_COMPLETENESS_VERIFIED: All required sources have verified active watermarks and reconciled transactions.
6. PERIOD_CLOSE_CERTIFIED: Authoritative signed period-close manifest or accounting close certified.
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.customer import Customer
from app.models.manifest import ManifestSubmission
from app.models.sale import Sale
from app.models.tenant import Business, IngestionJob
from app.services.tenant_certification_policy import TenantCertificationPolicy
from app.services.watermark_service import EffectiveWatermarkResult, WatermarkService

logger = get_logger(__name__)


class TenantReadinessState(str, Enum):
    """Authoritative governance states for tenant data readiness."""
    DEMO_SYNTHETIC = "DEMO_SYNTHETIC"
    IMPORT_COMPLETED = "IMPORT_COMPLETED"
    LATEST_OBSERVED_DATE = "LATEST_OBSERVED_DATE"
    SOURCE_COMPLETENESS_UNVERIFIED = "SOURCE_COMPLETENESS_UNVERIFIED"
    SOURCE_COMPLETENESS_VERIFIED = "SOURCE_COMPLETENESS_VERIFIED"
    PERIOD_CLOSE_CERTIFIED = "PERIOD_CLOSE_CERTIFIED"


class TenantReadinessPacket(BaseModel):
    """Complete readiness evaluation packet for a tenant."""
    business_id: str
    business_name: str
    readiness_status: TenantReadinessState
    is_synthetic: bool = False
    is_actionable: bool = False
    confidence_cap: float = 1.0
    latest_observed_date: datetime | None = None
    effective_complete_through_dt: datetime | None = None
    total_sales_count: int = 0
    total_customers_count: int = 0
    active_watermark_status: str = "unverified_missing"
    explanation: str
    governance_notes: list[str] = Field(default_factory=list)


class TenantReadinessService:
    """Central authority providing tenant-scoped readiness evaluations."""

    @classmethod
    def get_tenant_readiness(
        cls,
        session: Session,
        business_id: str,
        required_sources: list[str] | None = None,
        max_staleness_days: int | None = 90,
    ) -> TenantReadinessPacket:
        """
        Evaluate and return the definitive data readiness packet for a tenant.
        Guarantees that all modules reflect identical status, confidence caps, and actionability.
        """
        biz = session.execute(
            select(Business).where(Business.id == business_id)
        ).scalar_one_or_none()

        biz_name = biz.name if biz else f"Tenant-{business_id[:8]}"
        is_sandbox = TenantCertificationPolicy.is_sandbox_merchant(business_id, session=session)

        # Count total sales & customers
        sales_count = session.execute(
            select(func.count(Sale.id)).where(Sale.business_id == business_id)
        ).scalar() or 0

        customers_count = session.execute(
            select(func.count(Customer.id)).where(Customer.business_id == business_id)
        ).scalar() or 0

        # Query latest transaction date
        latest_sale_dt = session.execute(
            select(func.max(Sale.transaction_date)).where(Sale.business_id == business_id)
        ).scalar()

        latest_observed = None
        if latest_sale_dt:
            if isinstance(latest_sale_dt, datetime):
                latest_observed = latest_sale_dt if latest_sale_dt.tzinfo else latest_sale_dt.replace(tzinfo=UTC)
            else:
                latest_observed = datetime.combine(latest_sale_dt, datetime.min.time(), tzinfo=UTC)

        # 1. State 1: DEMO_SYNTHETIC
        # If business is a dedicated synthetic sandbox or contains explicit synthetic metadata
        if is_sandbox:
            return TenantReadinessPacket(
                business_id=business_id,
                business_name=biz_name,
                readiness_status=TenantReadinessState.DEMO_SYNTHETIC,
                is_synthetic=True,
                is_actionable=False,
                confidence_cap=0.70,
                latest_observed_date=latest_observed,
                effective_complete_through_dt=latest_observed,
                total_sales_count=sales_count,
                total_customers_count=customers_count,
                active_watermark_status="DEMO_SYNTHETIC",
                explanation=(
                    f"Tenant '{biz_name}' operates under controlled synthetic validation. "
                    "Customer cadences, 12-month histories, and seasonal sales curves are deterministically generated. "
                    "Analytical queries execute correctly, but conclusions cannot be certified for live commercial operations."
                ),
                governance_notes=[
                    "Deterministic synthetic data generated for controlled product validation.",
                    "Confidence scores are strictly capped at 70.0% to prevent overconfidence.",
                    "Live external customer outreach and billing interventions are disabled.",
                ],
            )

        # 2. Query Authoritative Watermark
        eff_wm: EffectiveWatermarkResult = WatermarkService.get_effective_tenant_watermark(
            session=session,
            business_id=business_id,
            required_sources=required_sources,
            max_staleness_days=max_staleness_days,
        )

        # 3. Check for PERIOD_CLOSE_CERTIFIED
        # Requires verified manifest or verified accounting_period_close watermark
        has_verified_manifest = session.execute(
            select(func.count(ManifestSubmission.id)).where(
                ManifestSubmission.business_id == business_id,
                ManifestSubmission.verification_status == "verified",
            )
        ).scalar() or 0

        active_wms = WatermarkService.get_active_watermarks(session, business_id)
        has_period_close_wm = any(
            w.verification_status == "verified"
            and w.provenance_type in ("accounting_period_close", "multi_source_period_close")
            for w in active_wms
        )

        if eff_wm.is_verified and (has_verified_manifest > 0 or has_period_close_wm):
            return TenantReadinessPacket(
                business_id=business_id,
                business_name=biz_name,
                readiness_status=TenantReadinessState.PERIOD_CLOSE_CERTIFIED,
                is_synthetic=False,
                is_actionable=True,
                confidence_cap=1.0,
                latest_observed_date=latest_observed,
                effective_complete_through_dt=eff_wm.effective_complete_through_dt,
                total_sales_count=sales_count,
                total_customers_count=customers_count,
                active_watermark_status=eff_wm.status,
                explanation=(
                    f"Accounting period close certified through "
                    f"{eff_wm.effective_complete_through_dt.isoformat() if eff_wm.effective_complete_through_dt else 'N/A'}. "
                    "Transactions, customer mapping, and ledger digest proofs have been cryptographically verified."
                ),
                governance_notes=[
                    "Period-close manifest cryptographically verified against committed database records.",
                    "Fully actionable for executive reporting and customer intervention.",
                ],
            )

        # 4. Check for SOURCE_COMPLETENESS_VERIFIED
        if eff_wm.is_verified and eff_wm.effective_complete_through_dt:
            return TenantReadinessPacket(
                business_id=business_id,
                business_name=biz_name,
                readiness_status=TenantReadinessState.SOURCE_COMPLETENESS_VERIFIED,
                is_synthetic=False,
                is_actionable=True,
                confidence_cap=0.90,
                latest_observed_date=latest_observed,
                effective_complete_through_dt=eff_wm.effective_complete_through_dt,
                total_sales_count=sales_count,
                total_customers_count=customers_count,
                active_watermark_status=eff_wm.status,
                explanation=(
                    f"Source completeness verified through {eff_wm.effective_complete_through_dt.isoformat()}. "
                    "Transactions match source ingestion boundaries with zero unresolved ingestion jobs."
                ),
                governance_notes=[
                    "All required source connectors report certified complete boundaries.",
                    "Eligible for operational reporting and assisted retention recommendations.",
                ],
            )

        # 5. Check for IMPORT_COMPLETED vs LATEST_OBSERVED_DATE vs SOURCE_COMPLETENESS_UNVERIFIED
        # Check if an IngestionJob completed for this tenant
        completed_jobs = session.execute(
            select(func.count(IngestionJob.id)).where(
                IngestionJob.business_id == business_id,
                IngestionJob.status == "COMPLETED",
            )
        ).scalar() or 0

        in_flight_jobs = session.execute(
            select(func.count(IngestionJob.id)).where(
                IngestionJob.business_id == business_id,
                IngestionJob.status.in_(["PENDING", "PROCESSING", "FAILED", "REQUIRES_REVIEW"]),
            )
        ).scalar() or 0

        if in_flight_jobs > 0 or eff_wm.status in ("incomplete_in_flight", "invalidated"):
            return TenantReadinessPacket(
                business_id=business_id,
                business_name=biz_name,
                readiness_status=TenantReadinessState.SOURCE_COMPLETENESS_UNVERIFIED,
                is_synthetic=False,
                is_actionable=False,
                confidence_cap=0.65,
                latest_observed_date=latest_observed,
                effective_complete_through_dt=None,
                total_sales_count=sales_count,
                total_customers_count=customers_count,
                active_watermark_status=eff_wm.status,
                explanation=(
                    f"Completeness is unverified: {in_flight_jobs} unresolved ingestion jobs or invalidated watermarks. "
                    "Outputs are diagnostic only and cannot authorize automated actions."
                ),
                governance_notes=[
                    "Unresolved ingestion pipelines block completeness certification.",
                    "Confidence capped at 65.0%.",
                ],
            )

        if completed_jobs > 0 and sales_count > 0:
            return TenantReadinessPacket(
                business_id=business_id,
                business_name=biz_name,
                readiness_status=TenantReadinessState.IMPORT_COMPLETED,
                is_synthetic=False,
                is_actionable=False,
                confidence_cap=0.75,
                latest_observed_date=latest_observed,
                effective_complete_through_dt=None,
                total_sales_count=sales_count,
                total_customers_count=customers_count,
                active_watermark_status="IMPORT_COMPLETED",
                explanation=(
                    f"Raw ingestion completed ({sales_count} sales records ingested), but authoritative completeness "
                    "watermarks or period boundaries have not been registered."
                ),
                governance_notes=[
                    "Raw records imported successfully.",
                    "Awaiting source completeness certification.",
                ],
            )

        if sales_count > 0:
            return TenantReadinessPacket(
                business_id=business_id,
                business_name=biz_name,
                readiness_status=TenantReadinessState.LATEST_OBSERVED_DATE,
                is_synthetic=False,
                is_actionable=False,
                confidence_cap=0.70,
                latest_observed_date=latest_observed,
                effective_complete_through_dt=None,
                total_sales_count=sales_count,
                total_customers_count=customers_count,
                active_watermark_status="LATEST_OBSERVED_DATE",
                explanation=(
                    f"Transactions observed up to {latest_observed.isoformat() if latest_observed else 'unknown'}, "
                    "but no ingestion job or certified completeness watermark exists for this workspace."
                ),
                governance_notes=[
                    "High-water mark observation only.",
                    "Completeness uncertified.",
                ],
            )

        # Fallback: Zero records
        return TenantReadinessPacket(
            business_id=business_id,
            business_name=biz_name,
            readiness_status=TenantReadinessState.SOURCE_COMPLETENESS_UNVERIFIED,
            is_synthetic=False,
            is_actionable=False,
            confidence_cap=0.0,
            latest_observed_date=None,
            effective_complete_through_dt=None,
            total_sales_count=0,
            total_customers_count=0,
            active_watermark_status="NOT_CONNECTED",
            explanation="No sales transactions found in workspace. Data connectors have not ingested records.",
            governance_notes=["Workspace empty."],
        )
