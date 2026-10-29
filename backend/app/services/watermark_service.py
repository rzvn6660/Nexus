"""Authoritative Ingestion Watermark Service (Phase 1F.2).

Manages tenant-scoped data completeness watermarks across single and multiple
ingestion sources. Guarantees that:
1. Completeness is never inferred from MAX(transaction_date) alone.
2. In-flight or failed ingestion jobs block watermark advancement.
3. Multiple sources combine via minimum complete-through date, requiring all sources.
4. Backfilled or corrected historical transactions invalidate affected watermarks.
5. All watermark transitions preserve an immutable audit ledger.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.tenant import IngestionJob
from app.models.watermark import TenantIngestionWatermark

logger = get_logger(__name__)


class WatermarkContract(BaseModel):
    """Specification for recording or certifying an ingestion completeness watermark."""

    business_id: str = Field(description="Tenant business identifier.")
    source_id: str = Field(
        default="default",
        description="Source identifier (e.g. 'pos', 'ecommerce', 'shopify', 'wholesale').",
    )
    complete_through_dt: datetime = Field(
        description="Certified event date/time through which all data is ingested."
    )
    provenance_type: str = Field(
        default="manual_close",
        description="Provenance: manual_close, batch_file, cdc_stream, pos_daily_sync, accounting_period_close, synthetic_fixture.",
    )
    ingestion_job_id: str | None = Field(
        default=None,
        description="Optional IngestionJob.id that established this watermark.",
    )
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        description="Optional telemetry: row counts, file hashes, external batch IDs.",
    )


class EffectiveWatermarkResult(BaseModel):
    """Evaluated tenant-level effective watermark combining all relevant sources."""

    business_id: str
    is_verified: bool = Field(
        description="Whether an authoritative completeness watermark is verified and active."
    )
    status: str = Field(
        description="Status: verified_complete, unverified_missing, incomplete_in_flight, incomplete_watermark_gap, invalidated."
    )
    effective_complete_through_dt: datetime | None = Field(
        default=None,
        description="Minimum certified complete-through datetime across all required sources (UTC).",
    )
    earliest_source_id: str | None = Field(
        default=None,
        description="Identifier of the source that limits the effective watermark.",
    )
    source_watermarks: dict[str, str | None] = Field(
        default_factory=dict,
        description="Mapping of source_id to ISO-8601 complete-through timestamps.",
    )
    unverified_sources: list[str] = Field(
        default_factory=list,
        description="List of required sources missing verified completeness.",
    )
    in_flight_or_failed_jobs_count: int = Field(
        default=0,
        description="Number of unresolved IngestionJobs blocking verification.",
    )
    blocking_reasons: list[str] = Field(
        default_factory=list,
        description="Explanations for why completeness is unverified or blocked.",
    )


class WatermarkService:
    """Service orchestrating authoritative ingestion watermark lifecycles and audits."""

    @staticmethod
    def _normalize_utc(dt: datetime | date) -> datetime:
        """Convert datetime or date to timezone-aware UTC datetime."""
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        if isinstance(dt, date):
            return datetime.combine(dt, datetime.max.time().replace(microsecond=0), tzinfo=UTC)
        raise ValueError(f"Invalid datetime/date object: {type(dt)}")

    @classmethod
    def record_watermark(
        cls,
        session: Session,
        contract: WatermarkContract | dict[str, Any],
    ) -> TenantIngestionWatermark:
        """
        Record a certified completeness watermark for a tenant and source.

        Deactivates previous active watermarks for the source, maintaining
        an auditable ledger of all historical watermark transitions.
        """
        if isinstance(contract, dict):
            contract = WatermarkContract(**contract)

        complete_utc = cls._normalize_utc(contract.complete_through_dt)

        # 1. Audit preservation: Deactivate previous active watermark for this (business_id, source_id)
        existing_active = session.execute(
            select(TenantIngestionWatermark).where(
                TenantIngestionWatermark.business_id == contract.business_id,
                TenantIngestionWatermark.source_id == contract.source_id,
                TenantIngestionWatermark.is_active.is_(True),
            )
        ).scalars().all()

        for old_wm in existing_active:
            old_wm.is_active = False

        # 2. Insert new active verified watermark
        new_wm = TenantIngestionWatermark(
            id=str(uuid4()),
            business_id=contract.business_id,
            source_id=contract.source_id,
            complete_through_dt=complete_utc,
            recorded_at=datetime.now(UTC),
            ingestion_job_id=contract.ingestion_job_id,
            provenance_type=contract.provenance_type,
            verification_status="verified",
            invalidation_reason=None,
            is_active=True,
            metadata_json=contract.metadata_json,
        )
        session.add(new_wm)
        session.flush()

        logger.info(
            "Recorded authoritative ingestion watermark: business_id=%s source_id=%s complete_through=%s provenance=%s",
            contract.business_id,
            contract.source_id,
            complete_utc.isoformat(),
            contract.provenance_type,
        )
        return new_wm

    @classmethod
    def invalidate_watermark(
        cls,
        session: Session,
        business_id: str,
        source_id: str = "*",
        reason: str = "Ingestion failure or data correction detected",
    ) -> list[TenantIngestionWatermark]:
        """
        Invalidate active watermarks for a tenant and source.

        Watermarks are marked verification_status='invalidated' while remaining
        active until superseded by a newly certified watermark.
        """
        stmt = select(TenantIngestionWatermark).where(
            TenantIngestionWatermark.business_id == business_id,
            TenantIngestionWatermark.is_active.is_(True),
        )
        if source_id != "*":
            stmt = stmt.where(TenantIngestionWatermark.source_id == source_id)

        active_wms = session.execute(stmt).scalars().all()
        for wm in active_wms:
            wm.verification_status = "invalidated"
            wm.invalidation_reason = reason

        session.flush()
        logger.warning(
            "Invalidated ingestion watermark(s): business_id=%s source_id=%s count=%d reason=%s",
            business_id,
            source_id,
            len(active_wms),
            reason,
        )
        return active_wms

    @classmethod
    def get_active_watermarks(
        cls, session: Session, business_id: str
    ) -> list[TenantIngestionWatermark]:
        """Query active watermarks for a tenant."""
        try:
            return session.execute(
                select(TenantIngestionWatermark)
                .where(
                    TenantIngestionWatermark.business_id == business_id,
                    TenantIngestionWatermark.is_active.is_(True),
                )
                .order_by(TenantIngestionWatermark.source_id)
            ).scalars().all()
        except Exception as e:  # noqa: BLE001
            # Table might not exist in unmigrated databases; handle gracefully
            logger.debug("Failed querying tenant_ingestion_watermarks (table may be unmigrated): %s", e)
            return []

    @classmethod
    def get_effective_tenant_watermark(
        cls,
        session: Session,
        business_id: str,
        required_sources: list[str] | None = None,
    ) -> EffectiveWatermarkResult:
        """
        Compute the effective certified complete-through date for a tenant.

        Combines multiple sources via min(complete_through_dt).
        Strict safety gates:
        1. Any in-flight or failed IngestionJob for the tenant blocks verification.
        2. Any required source lacking a verified watermark produces 'incomplete_watermark_gap'.
        3. If any active watermark is invalidated, produces 'invalidated'.
        4. If no watermarks exist, produces 'unverified_missing'.
        """
        blocking_reasons: list[str] = []

        # 1. Gate 1: Check for in-flight or failed ingestion jobs
        job_stmt = select(func.count(IngestionJob.id)).where(
            IngestionJob.business_id == business_id,
            IngestionJob.status.in_(["PENDING", "PROCESSING", "FAILED", "REQUIRES_REVIEW"]),
        )
        unresolved_jobs_count = session.execute(job_stmt).scalar() or 0

        if unresolved_jobs_count > 0:
            blocking_reasons.append(
                f"{unresolved_jobs_count} in-flight, pending, or failed ingestion jobs exist for tenant. "
                "Completeness cannot be certified while ingestion pipelines are unresolved."
            )
            return EffectiveWatermarkResult(
                business_id=business_id,
                is_verified=False,
                status="incomplete_in_flight",
                effective_complete_through_dt=None,
                earliest_source_id=None,
                source_watermarks={},
                unverified_sources=[],
                in_flight_or_failed_jobs_count=unresolved_jobs_count,
                blocking_reasons=blocking_reasons,
            )

        # 2. Gate 2: Inspect active watermarks
        active_wms = cls.get_active_watermarks(session, business_id)

        source_map: dict[str, TenantIngestionWatermark] = {
            wm.source_id: wm for wm in active_wms
        }
        source_ts_map: dict[str, str | None] = {
            wm.source_id: (
                wm.complete_through_dt.isoformat()
                if wm.complete_through_dt
                else None
            )
            for wm in active_wms
        }

        # Check for invalidated active watermarks
        invalidated_wms = [wm for wm in active_wms if wm.verification_status == "invalidated"]
        if invalidated_wms:
            for inv in invalidated_wms:
                blocking_reasons.append(
                    f"Watermark for source '{inv.source_id}' was invalidated: {inv.invalidation_reason}"
                )
            return EffectiveWatermarkResult(
                business_id=business_id,
                is_verified=False,
                status="invalidated",
                effective_complete_through_dt=None,
                earliest_source_id=invalidated_wms[0].source_id,
                source_watermarks=source_ts_map,
                unverified_sources=[inv.source_id for inv in invalidated_wms],
                in_flight_or_failed_jobs_count=0,
                blocking_reasons=blocking_reasons,
            )

        # 3. Gate 3: If required_sources are explicitly specified
        if required_sources:
            missing_sources = [s for s in required_sources if s not in source_map or source_map[s].verification_status != "verified"]
            if missing_sources:
                for ms in missing_sources:
                    blocking_reasons.append(
                        f"Required ingestion source '{ms}' has no verified active watermark."
                    )
                return EffectiveWatermarkResult(
                    business_id=business_id,
                    is_verified=False,
                    status="incomplete_watermark_gap",
                    effective_complete_through_dt=None,
                    earliest_source_id=missing_sources[0],
                    source_watermarks=source_ts_map,
                    unverified_sources=missing_sources,
                    in_flight_or_failed_jobs_count=0,
                    blocking_reasons=blocking_reasons,
                )

            # All required sources are present and verified
            relevant_wms = [source_map[s] for s in required_sources]
            earliest_wm = min(relevant_wms, key=lambda w: cls._normalize_utc(w.complete_through_dt))
            eff_dt = cls._normalize_utc(earliest_wm.complete_through_dt)
            return EffectiveWatermarkResult(
                business_id=business_id,
                is_verified=True,
                status="verified_complete",
                effective_complete_through_dt=eff_dt,
                earliest_source_id=earliest_wm.source_id,
                source_watermarks=source_ts_map,
                unverified_sources=[],
                in_flight_or_failed_jobs_count=0,
                blocking_reasons=[],
            )

        # 4. Gate 4: No required sources specified
        if not active_wms:
            blocking_reasons.append(
                "No authoritative completeness watermark is registered for this tenant. "
                "Historical follow-up relies solely on raw observed database timestamps."
            )
            return EffectiveWatermarkResult(
                business_id=business_id,
                is_verified=False,
                status="unverified_missing",
                effective_complete_through_dt=None,
                earliest_source_id=None,
                source_watermarks={},
                unverified_sources=[],
                in_flight_or_failed_jobs_count=0,
                blocking_reasons=blocking_reasons,
            )

        # All existing active watermarks are verified
        earliest_wm = min(active_wms, key=lambda w: cls._normalize_utc(w.complete_through_dt))
        eff_dt = cls._normalize_utc(earliest_wm.complete_through_dt)
        return EffectiveWatermarkResult(
            business_id=business_id,
            is_verified=True,
            status="verified_complete",
            effective_complete_through_dt=eff_dt,
            earliest_source_id=earliest_wm.source_id,
            source_watermarks=source_ts_map,
            unverified_sources=[],
            in_flight_or_failed_jobs_count=0,
            blocking_reasons=[],
        )

    @classmethod
    def detect_backfill_and_handle(
        cls,
        session: Session,
        business_id: str,
        source_id: str,
        transaction_dates: list[datetime],
        job_id: str | None = None,
    ) -> bool:
        """
        Check whether incoming transaction records fall on or before an active watermark.

        If so, the active watermark is safely invalidated because late-arriving
        data proves the historical interval was not complete when certified.
        """
        if not transaction_dates:
            return False

        active_wms = session.execute(
            select(TenantIngestionWatermark).where(
                TenantIngestionWatermark.business_id == business_id,
                TenantIngestionWatermark.source_id == source_id,
                TenantIngestionWatermark.is_active.is_(True),
                TenantIngestionWatermark.verification_status == "verified",
            )
        ).scalars().all()

        if not active_wms:
            return False

        min_incoming_dt = min(
            cls._normalize_utc(d) for d in transaction_dates
        )

        invalidated_any = False
        for wm in active_wms:
            wm_dt = cls._normalize_utc(wm.complete_through_dt)
            if min_incoming_dt <= wm_dt:
                reason = (
                    f"Backfill detected: incoming transaction dated {min_incoming_dt.isoformat()} "
                    f"is at or before certified watermark {wm_dt.isoformat()} (job: {job_id})"
                )
                wm.verification_status = "invalidated"
                wm.invalidation_reason = reason
                invalidated_any = True
                logger.warning(
                    "Backfill invalidated watermark: business_id=%s source_id=%s watermark_id=%s reason=%s",
                    business_id,
                    source_id,
                    wm.id,
                    reason,
                )

        if invalidated_any:
            session.flush()

        return invalidated_any
