"""Authoritative Ingestion Watermark Service (Phase 1F.2 / Phase 1G.2).

Manages tenant-scoped data completeness watermarks across single and multiple
ingestion sources. Guarantees that:
1. Completeness is never inferred from MAX(transaction_date) alone.
2. In-flight or failed ingestion jobs block watermark advancement.
3. Multiple sources combine via minimum complete-through date, requiring all sources.
4. Backfilled or corrected historical transactions invalidate affected watermarks.
5. All watermark transitions preserve an immutable audit ledger.
6. Inputs, timestamps, provenance types, and statuses are strictly validated.
7. Cross-tenant access is rejected with hard authorization checks.
8. Idempotent retries are supported without duplicate active rows.
"""

from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.tenant import IngestionJob
from app.models.watermark import TenantIngestionWatermark

logger = get_logger(__name__)

ALLOWED_PROVENANCE_TYPES: set[str] = {
    "manual_close",
    "batch_file",
    "cdc_stream",
    "pos_daily_sync",
    "accounting_period_close",
    "synthetic_fixture",
}

ALLOWED_VERIFICATION_STATUSES: set[str] = {
    "verified",
    "provisional",
    "invalidated",
}


class WatermarkCertificationState(str, Enum):
    """
    Authoritative governance states for ingestion completeness and period close.
    Guarantees that an import completion or high-water mark observation does not
    silently manufacture a period-close certification.
    """
    DEMO_SYNTHETIC = "DEMO_SYNTHETIC"
    IMPORT_COMPLETED = "IMPORT_COMPLETED"
    LATEST_OBSERVED_DATE = "LATEST_OBSERVED_DATE"
    SOURCE_COMPLETENESS_UNVERIFIED = "SOURCE_COMPLETENESS_UNVERIFIED"
    SOURCE_COMPLETENESS_VERIFIED = "SOURCE_COMPLETENESS_VERIFIED"
    PERIOD_CLOSE_CERTIFIED = "PERIOD_CLOSE_CERTIFIED"


class WatermarkContract(BaseModel):
    """Specification for recording or certifying an ingestion completeness watermark."""

    business_id: str = Field(
        min_length=1,
        max_length=36,
        description="Tenant business identifier.",
    )
    source_id: str = Field(
        default="default",
        min_length=1,
        max_length=64,
        description="Source identifier (e.g. 'pos', 'ecommerce', 'shopify', 'wholesale').",
    )
    complete_through_dt: datetime = Field(
        description="Certified event date/time through which all data is ingested."
    )
    provenance_type: str = Field(
        default="manual_close",
        description="Provenance: manual_close, batch_file, cdc_stream, pos_daily_sync, accounting_period_close, synthetic_fixture.",
    )
    verification_status: str = Field(
        default="verified",
        description="Status: verified, provisional, invalidated.",
    )
    ingestion_job_id: str | None = Field(
        default=None,
        max_length=36,
        description="Optional IngestionJob.id that established this watermark.",
    )
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        description="Optional telemetry: row counts, file hashes, external batch IDs.",
    )

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("source_id cannot be empty or whitespace only")
        if len(s) > 64:
            raise ValueError("source_id cannot exceed 64 characters")
        return s

    @field_validator("provenance_type")
    @classmethod
    def validate_provenance_type(cls, v: str) -> str:
        if v not in ALLOWED_PROVENANCE_TYPES:
            raise ValueError(
                f"Invalid provenance_type '{v}'. Allowed: {sorted(ALLOWED_PROVENANCE_TYPES)}"
            )
        return v

    @field_validator("verification_status")
    @classmethod
    def validate_verification_status(cls, v: str) -> str:
        if v not in ALLOWED_VERIFICATION_STATUSES:
            raise ValueError(
                f"Invalid verification_status '{v}'. Allowed: {sorted(ALLOWED_VERIFICATION_STATUSES)}"
            )
        return v

    @field_validator("complete_through_dt")
    @classmethod
    def validate_complete_through_dt(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            utc_dt = v.replace(tzinfo=UTC)
        else:
            utc_dt = v.astimezone(UTC)

        # Sanity lower bound
        if utc_dt.year < 2000:
            raise ValueError(f"complete_through_dt cannot be before year 2000: {utc_dt.isoformat()}")

        # Timestamp cannot be in the future (allow 5 min clock skew)
        now_skew = datetime.now(UTC) + timedelta(minutes=5)
        if utc_dt > now_skew:
            raise ValueError(
                f"complete_through_dt cannot be in the future (timestamp={utc_dt.isoformat()}, now={datetime.now(UTC).isoformat()})"
            )

        return utc_dt


class EffectiveWatermarkResult(BaseModel):
    """Evaluated tenant-level effective watermark combining all relevant sources."""

    business_id: str
    is_verified: bool = Field(
        description="Whether an authoritative completeness watermark is verified and active."
    )
    status: str = Field(
        description="Status: verified_complete, unverified_missing, incomplete_in_flight, incomplete_watermark_gap, invalidated."
    )
    certification_state: str = Field(
        default=WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value,
        description="Governance certification state: IMPORT_COMPLETED, LATEST_OBSERVED_DATE, SOURCE_COMPLETENESS_UNVERIFIED, SOURCE_COMPLETENESS_VERIFIED, PERIOD_CLOSE_CERTIFIED.",
    )
    latest_observed_date: datetime | None = Field(
        default=None,
        description="Maximum observed transaction timestamp in tenant records (observed high-water mark).",
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
    is_stale: bool = Field(
        default=False,
        description="Whether the effective watermark boundary exceeds max staleness threshold.",
    )
    stale_warning: str | None = Field(
        default=None,
        description="Diagnostic warning if watermark is stale.",
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
        allow_regression: bool = False,
    ) -> TenantIngestionWatermark:
        """
        Record a completeness watermark for a tenant and source.

        Deactivates previous active watermarks for the source, maintaining
        an auditable ledger of all historical watermark transitions.

        Supports idempotent invocations if an active watermark with identical
        boundary, status, and provenance already exists.
        """
        if isinstance(contract, dict):
            contract = WatermarkContract(**contract)

        complete_utc = cls._normalize_utc(contract.complete_through_dt)

        # 1. Cross-tenant safety check on ingestion_job_id if supplied
        if contract.ingestion_job_id:
            job = session.execute(
                select(IngestionJob).where(IngestionJob.id == contract.ingestion_job_id)
            ).scalar_one_or_none()
            if job and job.business_id != contract.business_id:
                raise PermissionError(
                    f"Cross-tenant access violation: ingestion_job {contract.ingestion_job_id} "
                    f"belongs to business {job.business_id}, not {contract.business_id}."
                )

        # 1b. Non-negotiable safety guard: Synthetic provenance cannot certify real operational tenants
        if contract.verification_status == "verified":
            from app.services.tenant_certification_policy import TenantCertificationPolicy
            if TenantCertificationPolicy.is_protected_real_tenant(contract.business_id, session) and TenantCertificationPolicy.is_sandbox_provenance(contract.provenance_type):
                raise ValueError(
                    f"GOVERNANCE VIOLATION: Cannot record verified watermark for real tenant '{contract.business_id}' "
                    f"using synthetic/sandbox provenance '{contract.provenance_type}'."
                )

        # 2. Check existing active watermarks for this (business_id, source_id)
        existing_active = session.execute(
            select(TenantIngestionWatermark).where(
                TenantIngestionWatermark.business_id == contract.business_id,
                TenantIngestionWatermark.source_id == contract.source_id,
                TenantIngestionWatermark.is_active.is_(True),
            )
        ).scalars().all()

        # 2a. Idempotency guard: If identical active watermark exists, return it
        for active_wm in existing_active:
            if (
                cls._normalize_utc(active_wm.complete_through_dt) == complete_utc
                and active_wm.verification_status == contract.verification_status
                and active_wm.provenance_type == contract.provenance_type
            ):
                logger.info(
                    "Idempotent watermark record request: returning active watermark %s "
                    "for business %s source %s",
                    active_wm.id,
                    contract.business_id,
                    contract.source_id,
                )
                return active_wm

        # 2b. Backward regression prevention for verified boundaries
        if not allow_regression and contract.verification_status == "verified":
            for active_wm in existing_active:
                if active_wm.verification_status == "verified":
                    existing_utc = cls._normalize_utc(active_wm.complete_through_dt)
                    if complete_utc < existing_utc:
                        raise ValueError(
                            f"Cannot advance verified watermark backward in time. "
                            f"Active verified watermark already exists through {existing_utc.isoformat()}, "
                            f"attempted to record earlier boundary {complete_utc.isoformat()}. "
                            f"If this is a backfill or data correction, invalidate the active watermark first."
                        )

        # 3. Audit preservation: Deactivate previous active watermarks for this (business_id, source_id)
        for old_wm in existing_active:
            old_wm.is_active = False
            old_wm.updated_at = datetime.now(UTC)

        # Flush deactivation first to respect partial unique index uq_tenant_watermarks_active_source
        session.flush()

        # 4. Insert new active watermark
        new_wm = TenantIngestionWatermark(
            id=str(uuid4()),
            business_id=contract.business_id,
            source_id=contract.source_id,
            complete_through_dt=complete_utc,
            recorded_at=datetime.now(UTC),
            ingestion_job_id=contract.ingestion_job_id,
            provenance_type=contract.provenance_type,
            verification_status=contract.verification_status,
            invalidation_reason=None,
            is_active=True,
            metadata_json=contract.metadata_json,
        )
        session.add(new_wm)
        session.flush()

        logger.info(
            "Recorded authoritative ingestion watermark: business_id=%s source_id=%s "
            "complete_through=%s status=%s provenance=%s",
            contract.business_id,
            contract.source_id,
            complete_utc.isoformat(),
            contract.verification_status,
            contract.provenance_type,
        )
        return new_wm

    @classmethod
    def promote_provisional_watermark(
        cls,
        session: Session,
        business_id: str,
        watermark_id: str,
        verification_job_id: str | None = None,
        audit_metadata: dict[str, Any] | None = None,
    ) -> TenantIngestionWatermark:
        """
        Promote a provisional watermark to verified after post-ingestion validation.

        Enforces tenant scoping, active state, and valid state transition.
        """
        # 0. Acquire row lock on watermark to prevent TOCTOU race conditions
        wm = session.execute(
            select(TenantIngestionWatermark)
            .where(TenantIngestionWatermark.id == watermark_id)
            .with_for_update()
        ).scalar_one_or_none()

        if not wm:
            raise ValueError(f"Watermark '{watermark_id}' not found.")
        if wm.business_id != business_id:
            raise PermissionError(
                f"Cross-tenant access violation: watermark {watermark_id} "
                f"does not belong to business {business_id}."
            )
        if not wm.is_active:
            raise ValueError(f"Cannot promote inactive historical watermark '{watermark_id}'.")
        if wm.verification_status != "provisional":
            raise ValueError(
                f"Cannot promote watermark with verification_status '{wm.verification_status}'; "
                "only 'provisional' watermarks can be promoted to 'verified'."
            )

        # Multi-source / Tenant Governance Check: Synthetic provenance cannot promote real operational tenants
        from app.services.tenant_certification_policy import TenantCertificationPolicy
        if TenantCertificationPolicy.is_protected_real_tenant(business_id, session) and TenantCertificationPolicy.is_sandbox_provenance(wm.provenance_type):
            raise ValueError(
                f"GOVERNANCE VIOLATION: Cannot promote watermark '{watermark_id}' for real tenant '{business_id}' "
                f"using synthetic/sandbox provenance '{wm.provenance_type}'."
            )

        # Verify job tenant scoping if verification_job_id provided
        if verification_job_id:
            v_job = session.execute(
                select(IngestionJob).where(IngestionJob.id == verification_job_id)
            ).scalar_one_or_none()
            if v_job and v_job.business_id != business_id:
                raise PermissionError(
                    f"Cross-tenant access violation: verification job {verification_job_id} "
                    f"does not belong to business {business_id}."
                )

        # Database Persisted Row Reconciliation (Phase 1I.4 Remediation C1 & Phase 1I.5 Hardening)
        meta = dict(wm.metadata_json or {})
        rec_summary = meta.get("reconciliation_summary") or {}
        expected_rows = rec_summary.get("sales_row_count") or meta.get("expected_sales_row_count")
        expected_gross = rec_summary.get("gross_total_amount") or meta.get("expected_gross_total_amount")
        period_start_raw = meta.get("period_start")

        if expected_rows is not None and expected_gross is not None and period_start_raw:
            import hashlib
            from decimal import Decimal

            from app.models.sale import Sale
            from app.models.tenant import Business

            period_start_dt = cls._normalize_utc(
                datetime.fromisoformat(period_start_raw)
                if isinstance(period_start_raw, str)
                else period_start_raw
            )
            period_end_dt = cls._normalize_utc(wm.complete_through_dt)
            status_allowlist = meta.get("eligible_status_allowlist") or ["completed", "shipped"]

            # 1. Query and lock persisted sales within certified period (Finding C1: TOCTOU prevention)
            sales_rows = session.execute(
                select(Sale)
                .where(
                    Sale.business_id == business_id,
                    Sale.transaction_date >= period_start_dt,
                    Sale.transaction_date <= period_end_dt,
                    Sale.status.in_(status_allowlist),
                )
                .with_for_update()
            ).scalars().all()

            persisted_count = len(sales_rows)
            persisted_gross = sum((Decimal(str(s.total_amount)) for s in sales_rows), Decimal("0.00"))
            unlinked_count = sum(1 for s in sales_rows if s.customer_id is None)

            # 2. Assert persisted row count matches
            if persisted_count != expected_rows:
                raise ValueError(
                    f"Persisted ingestion reconciliation failure: manifest expected {expected_rows} rows, "
                    f"but database contains {persisted_count} matching sales for business '{business_id}'."
                )

            # 3. Assert persisted gross monetary sum matches
            exp_gross_dec = Decimal(str(expected_gross))
            actual_gross_dec = Decimal(str(persisted_gross))
            if abs(actual_gross_dec - exp_gross_dec) > Decimal("0.01"):
                raise ValueError(
                    f"Persisted monetary reconciliation failure: manifest expected ${exp_gross_dec:.2f}, "
                    f"but database sum is ${actual_gross_dec:.2f} (difference: ${abs(actual_gross_dec - exp_gross_dec):.2f})."
                )

            # 4. Assert zero unlinked customers within period
            if unlinked_count > 0:
                raise ValueError(
                    f"Persisted reconciliation failure: {unlinked_count} sales within certified period "
                    f"have unlinked/null customer_id in business '{business_id}'."
                )

            # 5. Assert no duplicate transaction numbers in database
            persisted_txns = [s.transaction_number for s in sales_rows if s.transaction_number]
            if len(persisted_txns) != len(set(persisted_txns)):
                raise ValueError(
                    f"Persisted reconciliation failure: duplicate transaction numbers detected in database sales for business '{business_id}'."
                )

            # 6. Exact transaction identity reconciliation (Finding C1: Adversarial txn replacement defense)
            expected_txns = rec_summary.get("transaction_numbers")
            expected_digest = rec_summary.get("transaction_set_digest")
            if expected_txns:
                persisted_set = set(persisted_txns)
                expected_set = set(expected_txns)
                if persisted_set != expected_set:
                    missing = expected_set - persisted_set
                    unexpected = persisted_set - expected_set
                    raise ValueError(
                        f"Exact transaction identity mismatch: expected {len(expected_set)} txns, found {len(persisted_set)}. "
                        f"Missing in DB: {sorted(missing)[:5]}. Unexpected in DB: {sorted(unexpected)[:5]}."
                    )
            if expected_digest and persisted_txns:
                actual_digest = hashlib.sha256("||".join(sorted(persisted_txns)).encode("utf-8")).hexdigest()
                if actual_digest != expected_digest:
                    raise ValueError(
                        f"Transaction set digest mismatch: expected '{expected_digest}', calculated '{actual_digest}'."
                    )

            # 7. Currency consistency verification
            expected_currency = rec_summary.get("currency")
            if expected_currency:
                biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
                if biz and biz.currency and biz.currency.upper() != expected_currency.upper():
                    raise ValueError(
                        f"Currency mismatch: manifest declared currency '{expected_currency}', "
                        f"but business '{business_id}' is configured with currency '{biz.currency}'."
                    )

            meta["db_reconciled"] = True
            meta["db_reconciled_at"] = datetime.now(UTC).isoformat()
            meta["db_persisted_row_count"] = persisted_count
            meta["db_persisted_gross_total"] = str(persisted_gross)

            # Update ManifestSubmission if exists
            manifest_id = meta.get("manifest_id")
            if manifest_id:
                from app.models.manifest import ManifestSubmission
                sub = session.execute(
                    select(ManifestSubmission).where(ManifestSubmission.manifest_id == manifest_id)
                ).scalar_one_or_none()
                if sub:
                    sub.db_reconciled = True
                    sub.db_reconciled_at = datetime.now(UTC)
                    sub.db_persisted_row_count = persisted_count
                    sub.db_persisted_gross_total = Decimal(str(persisted_gross))
                    sub.verification_status = "verified"

        wm.verification_status = "verified"
        wm.updated_at = datetime.now(UTC)

        meta = dict(wm.metadata_json or {})
        if verification_job_id:
            meta["promoted_by_job_id"] = verification_job_id
        if audit_metadata:
            meta.update(audit_metadata)
        wm.metadata_json = meta

        session.flush()
        logger.info(
            "Promoted provisional watermark to verified: watermark_id=%s business_id=%s source_id=%s",
            wm.id,
            business_id,
            wm.source_id,
        )
        return wm

    @classmethod
    def invalidate_watermark(
        cls,
        session: Session,
        business_id: str,
        source_id: str = "*",
        reason: str = "Ingestion failure or data correction detected",
        job_id: str | None = None,
    ) -> list[TenantIngestionWatermark]:
        """
        Invalidate active watermarks for a tenant and source.

        Watermarks are marked verification_status='invalidated' while remaining
        active until superseded by a newly certified watermark.
        """
        if not business_id or not business_id.strip():
            raise ValueError("business_id cannot be empty")

        stmt = select(TenantIngestionWatermark).where(
            TenantIngestionWatermark.business_id == business_id,
            TenantIngestionWatermark.is_active.is_(True),
        )
        if source_id != "*":
            clean_source = source_id.strip()
            if not clean_source:
                raise ValueError("source_id cannot be whitespace only")
            stmt = stmt.where(TenantIngestionWatermark.source_id == clean_source)

        active_wms = session.execute(stmt).scalars().all()
        for wm in active_wms:
            wm.verification_status = "invalidated"
            wm.invalidation_reason = reason
            wm.updated_at = datetime.now(UTC)
            if job_id:
                meta = dict(wm.metadata_json or {})
                meta["invalidated_by_job_id"] = job_id
                wm.metadata_json = meta

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
    def get_watermark_history(
        cls,
        session: Session,
        business_id: str,
        source_id: str | None = None,
        limit: int = 50,
    ) -> list[TenantIngestionWatermark]:
        """
        Retrieve complete audit history of all watermark transitions (active and inactive)
        for a tenant, ordered by recorded_at descending.
        """
        if not business_id or not business_id.strip():
            raise ValueError("business_id cannot be empty")

        stmt = select(TenantIngestionWatermark).where(
            TenantIngestionWatermark.business_id == business_id
        )
        if source_id:
            stmt = stmt.where(TenantIngestionWatermark.source_id == source_id.strip())

        stmt = stmt.order_by(TenantIngestionWatermark.recorded_at.desc()).limit(limit)
        return list(session.execute(stmt).scalars().all())

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

    DEFAULT_MAX_STALENESS_DAYS: int = 90

    @classmethod
    def get_effective_tenant_watermark(
        cls,
        session: Session,
        business_id: str,
        required_sources: list[str] | None = None,
        max_staleness_days: int | None = 90,
    ) -> EffectiveWatermarkResult:
        """
        Compute the effective certified complete-through date for a tenant.

        Combines multiple sources via min(complete_through_dt).
        Strict safety gates:
        1. Any in-flight, pending, or failed IngestionJob for the tenant blocks verification.
        2. Any active watermark that is invalidated blocks verification.
        3. Any active watermark that is provisional blocks verification.
        4. Any required source lacking a verified active watermark produces 'incomplete_watermark_gap'.
        5. If no watermarks exist, produces 'unverified_missing'.
        """
        blocking_reasons: list[str] = []

        # 1. Gate 1: Check for in-flight or failed ingestion jobs
        # Resolve latest observed transaction timestamp (high-water mark observation)
        latest_observed_dt: datetime | None = None
        try:
            from app.models.sale import Sale
            latest_sale_dt = session.execute(
                select(func.max(Sale.transaction_date)).where(Sale.business_id == business_id)
            ).scalar()
            if latest_sale_dt:
                latest_observed_dt = cls._normalize_utc(latest_sale_dt)
        except Exception:  # noqa: BLE001
            pass

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
                certification_state=WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value,
                latest_observed_date=latest_observed_dt,
                effective_complete_through_dt=None,
                earliest_source_id=None,
                source_watermarks={},
                unverified_sources=[],
                in_flight_or_failed_jobs_count=unresolved_jobs_count,
                blocking_reasons=blocking_reasons,
            )

        # 2. Gate 2: Inspect active watermarks
        active_wms = cls.get_active_watermarks(session, business_id)
        if latest_observed_dt is None and active_wms:
            latest_observed_dt = max(cls._normalize_utc(w.complete_through_dt) for w in active_wms)

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
                certification_state=WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value,
                latest_observed_date=latest_observed_dt,
                effective_complete_through_dt=None,
                earliest_source_id=invalidated_wms[0].source_id,
                source_watermarks=source_ts_map,
                unverified_sources=[inv.source_id for inv in invalidated_wms],
                in_flight_or_failed_jobs_count=0,
                blocking_reasons=blocking_reasons,
            )

        # Check for provisional (unpromoted) active watermarks
        provisional_wms = [wm for wm in active_wms if wm.verification_status == "provisional"]
        if provisional_wms:
            for prov in provisional_wms:
                blocking_reasons.append(
                    f"Watermark for source '{prov.source_id}' is provisional and pending post-ingestion verification."
                )

        # 3. Gate 3: If required_sources are explicitly specified
        if required_sources:
            missing_sources = [
                s for s in required_sources
                if s not in source_map or source_map[s].verification_status != "verified"
            ]
            if missing_sources:
                for ms in missing_sources:
                    blocking_reasons.append(
                        f"Required ingestion source '{ms}' has no verified active watermark."
                    )
                return EffectiveWatermarkResult(
                    business_id=business_id,
                    is_verified=False,
                    status="incomplete_watermark_gap",
                    certification_state=WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value,
                    latest_observed_date=latest_observed_dt,
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

            # Staleness evaluation
            is_stale = False
            stale_warning = None
            if max_staleness_days is not None:
                age_days = (datetime.now(UTC) - eff_dt).days
                if age_days > max_staleness_days:
                    is_stale = True
                    stale_warning = (
                        f"Effective watermark ({eff_dt.isoformat()}) is {age_days} days old, "
                        f"exceeding max staleness threshold of {max_staleness_days} days."
                    )

            has_period_close = any(w.provenance_type in ("accounting_period_close", "multi_source_period_close") for w in relevant_wms)
            cert_state = (
                WatermarkCertificationState.PERIOD_CLOSE_CERTIFIED.value
                if has_period_close
                else WatermarkCertificationState.SOURCE_COMPLETENESS_VERIFIED.value
            )

            return EffectiveWatermarkResult(
                business_id=business_id,
                is_verified=True,
                status="verified_complete",
                certification_state=cert_state,
                latest_observed_date=latest_observed_dt,
                effective_complete_through_dt=eff_dt,
                earliest_source_id=earliest_wm.source_id,
                source_watermarks=source_ts_map,
                unverified_sources=[],
                in_flight_or_failed_jobs_count=0,
                blocking_reasons=[],
                is_stale=is_stale,
                stale_warning=stale_warning,
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
                certification_state=WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value,
                latest_observed_date=latest_observed_dt,
                effective_complete_through_dt=None,
                earliest_source_id=None,
                source_watermarks={},
                unverified_sources=[],
                in_flight_or_failed_jobs_count=0,
                blocking_reasons=blocking_reasons,
            )

        # If any active watermark is provisional, it cannot produce a verified effective boundary
        if provisional_wms:
            return EffectiveWatermarkResult(
                business_id=business_id,
                is_verified=False,
                status="incomplete_watermark_gap",
                certification_state=WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value,
                latest_observed_date=latest_observed_dt,
                effective_complete_through_dt=None,
                earliest_source_id=provisional_wms[0].source_id,
                source_watermarks=source_ts_map,
                unverified_sources=[p.source_id for p in provisional_wms],
                in_flight_or_failed_jobs_count=0,
                blocking_reasons=blocking_reasons,
            )

        # All existing active watermarks are verified
        earliest_wm = min(active_wms, key=lambda w: cls._normalize_utc(w.complete_through_dt))
        eff_dt = cls._normalize_utc(earliest_wm.complete_through_dt)

        is_stale = False
        stale_warning = None
        if max_staleness_days is not None:
            age_days = (datetime.now(UTC) - eff_dt).days
            if age_days > max_staleness_days:
                is_stale = True
                stale_warning = (
                    f"Effective watermark ({eff_dt.isoformat()}) is {age_days} days old, "
                    f"exceeding max staleness threshold of {max_staleness_days} days."
                )

        has_period_close = any(w.provenance_type in ("accounting_period_close", "multi_source_period_close") for w in active_wms)
        cert_state = (
            WatermarkCertificationState.PERIOD_CLOSE_CERTIFIED.value
            if has_period_close
            else WatermarkCertificationState.SOURCE_COMPLETENESS_VERIFIED.value
        )

        return EffectiveWatermarkResult(
            business_id=business_id,
            is_verified=True,
            status="verified_complete",
            certification_state=cert_state,
            latest_observed_date=latest_observed_dt,
            effective_complete_through_dt=eff_dt,
            earliest_source_id=earliest_wm.source_id,
            source_watermarks=source_ts_map,
            unverified_sources=[],
            in_flight_or_failed_jobs_count=0,
            blocking_reasons=[],
            is_stale=is_stale,
            stale_warning=stale_warning,
        )

    @classmethod
    def record_import_completion(
        cls,
        session: Session,
        business_id: str,
        source_id: str,
        transaction_dates: list[datetime | date | str] | None = None,
        certified_complete_through: datetime | date | str | None = None,
        job_id: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> TenantIngestionWatermark | None:
        """
        Record the completion of a data import (CSV, Excel, PostgreSQL).
        Guarantees distinct governance states:
        - Updates observed high-water mark (LATEST_OBSERVED_DATE).
        - If certified_complete_through is provided and verified, establishes SOURCE_COMPLETENESS_VERIFIED.
        - Otherwise, establishes IMPORT_COMPLETED with status SOURCE_COMPLETENESS_UNVERIFIED (provisional).
        - NEVER automatically manufactures PERIOD_CLOSE_CERTIFIED on import completion alone.
        """
        if not transaction_dates and not certified_complete_through:
            return None

        parsed_dates: list[datetime] = []
        for d in (transaction_dates or []):
            try:
                if isinstance(d, datetime):
                    parsed_dates.append(cls._normalize_utc(d))
                elif isinstance(d, date):
                    parsed_dates.append(cls._normalize_utc(datetime.combine(d, datetime.min.time(), tzinfo=UTC)))
                elif isinstance(d, str):
                    parsed_dates.append(cls._normalize_utc(datetime.fromisoformat(d.replace("Z", "+00:00"))))
            except Exception:
                continue

        latest_observed = max(parsed_dates) if parsed_dates else None

        # Check if an explicit authoritative certification was supplied
        is_certified = False
        cert_dt: datetime | None = None
        if certified_complete_through:
            try:
                if isinstance(certified_complete_through, datetime):
                    cert_dt = cls._normalize_utc(certified_complete_through)
                elif isinstance(certified_complete_through, date):
                    cert_dt = cls._normalize_utc(datetime.combine(certified_complete_through, datetime.min.time(), tzinfo=UTC))
                elif isinstance(certified_complete_through, str):
                    cert_dt = cls._normalize_utc(datetime.fromisoformat(certified_complete_through.replace("Z", "+00:00")))
                is_certified = True
            except Exception:
                is_certified = False

        effective_boundary = cert_dt or latest_observed
        if not effective_boundary:
            return None

        # Determine distinct certification governance state
        # Source completeness verification requires:
        # 1. Authoritative reporting-period boundary (cert_dt)
        # 2. Authoritative source evidence (source_id, file_hash, or dataset_id)
        # 3. Source-to-database reconciliation (db_reconciled or verified row counts)
        meta = dict(metadata_json or {})
        # Source completeness verification requires:
        # 1. Authoritative reporting-period boundary (cert_dt)
        # 2. Reconciled evidence (cannot certify if explicitly unreconciled or variances detected)
        is_unreconciled = (
            meta.get("db_reconciled") is False
            or meta.get("reconciliation_status") in ("unreconciled", "mismatched", "failed")
        )

        if is_certified and not is_unreconciled:
            verification_status = "verified"
            gov_state = WatermarkCertificationState.SOURCE_COMPLETENESS_VERIFIED.value
        else:
            # Remains unverified when evidence or reconciliation is incomplete
            verification_status = "provisional"
            gov_state = WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value

        meta["import_status"] = WatermarkCertificationState.IMPORT_COMPLETED.value
        meta["governance_state"] = gov_state
        if latest_observed:
            meta["latest_observed_date"] = latest_observed.isoformat()

        contract = {
            "business_id": business_id,
            "source_id": source_id,
            "complete_through_dt": effective_boundary,
            "provenance_type": "batch_file",
            "verification_status": verification_status,
            "ingestion_job_id": job_id,
            "metadata_json": meta,
        }
        return cls.record_watermark(session=session, contract=contract)

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
                wm.updated_at = datetime.now(UTC)
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
