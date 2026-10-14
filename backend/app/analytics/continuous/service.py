"""Service layer coordinating Continuous Intelligence detection, deduplication, and persistence (Phase 29)."""

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.analytics.continuous.engine import (
    ContinuousDetectionEngine,
    compute_finding_fingerprint,
)
from app.analytics.continuous.schemas import (
    ContinuousFindingListResponse,
    ContinuousFindingResponse,
    ContinuousScanRequest,
    ContinuousScanResponse,
    FeedbackType,
    FindingFeedbackResponse,
    FindingSeverity,
    FindingStatus,
)
from app.core.auth import verify_user_business_access
from app.core.logging import get_logger
from app.models.continuous import (
    ContinuousFinding,
    FindingFeedback,
    FindingScanRun,
)
from app.models.history import DecisionRecord
from app.models.tenant import (
    Business,
    IngestionJob,
    TenantSemanticModel,
    UploadedDataset,
    UserIdentity,
)

logger = get_logger(__name__)

ALLOWED_STATUS_TRANSITIONS: dict[FindingStatus, set[FindingStatus]] = {
    FindingStatus.ACTIVE: {
        FindingStatus.ACKNOWLEDGED,
        FindingStatus.DISMISSED,
        FindingStatus.RESOLVED,
    },
    FindingStatus.ACKNOWLEDGED: {
        FindingStatus.RESOLVED,
        FindingStatus.DISMISSED,
        FindingStatus.ACTIVE,
    },
    FindingStatus.DISMISSED: {
        FindingStatus.ACTIVE,
    },
    FindingStatus.RESOLVED: {
        FindingStatus.ACTIVE,
    },
    FindingStatus.EXPIRED: {
        FindingStatus.ACTIVE,
    },
}


class ContinuousIntelligenceService:
    """Orchestrates proactive business metric scans, deduplication, and feedback."""

    @classmethod
    def trigger_ingestion_scan(
        cls,
        db: Session,
        business_id: str,
        organization_id: str,
        dataset_id: str,
        ingestion_job_id: str,
        dataset_version: int = 1,
        entity: str | None = None,
        current_user: UserIdentity | None = None,
        reference_time: datetime | None = None,
    ) -> ContinuousScanResponse | None:
        """
        Trigger continuous intelligence scan after successful data ingestion.
        Guarantees:
        - Only runs after ingestion has committed and completed.
        - Enforces tenant isolation (business and organization match).
        - Idempotent: duplicate calls for the same ingestion_job_id return the existing scan run.
        - Isolated error handling: failures do not reverse or corrupt committed ingestion.
        """
        # 1. Authorization & Tenant Security Check
        if current_user is not None:
            verify_user_business_access(db, current_user, business_id, action="trigger ingestion scan")

        biz = db.execute(
            select(Business).where(
                Business.id == business_id,
                Business.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        if not biz:
            logger.warning(
                "Ingestion scan trigger rejected: Business %s not found in Organization %s",
                business_id,
                organization_id,
            )
            return None

        # 2. Ingestion Job & Dataset State Verification
        bind = db.get_bind() if hasattr(db, "get_bind") else getattr(db, "bind", None)
        is_postgres = (
            bind is not None
            and getattr(bind, "dialect", None) is not None
            and bind.dialect.name == "postgresql"
        )

        stmt = select(IngestionJob).where(
            IngestionJob.id == ingestion_job_id,
            IngestionJob.business_id == business_id,
            IngestionJob.organization_id == organization_id,
        )
        if is_postgres:
            stmt = stmt.with_for_update(skip_locked=True)

        job = db.execute(stmt).scalar_one_or_none()
        if not job:
            if is_postgres:
                unlocked_job = db.execute(
                    select(IngestionJob.id).where(
                        IngestionJob.id == ingestion_job_id,
                        IngestionJob.business_id == business_id,
                    )
                ).scalar_one_or_none()
                if unlocked_job:
                    logger.info(
                        "Ingestion job %s is currently locked by a concurrent scan worker - skipping competing scan.",
                        ingestion_job_id,
                    )
                    return None
            logger.warning(
                "Ingestion scan trigger rejected: IngestionJob %s not found for business %s",
                ingestion_job_id,
                business_id,
            )
            return None

        if job.status != "COMPLETED":
            logger.warning(
                "Ingestion scan trigger skipped: IngestionJob %s is not COMPLETED (status=%s)",
                ingestion_job_id,
                job.status,
            )
            return None

        dataset = db.execute(
            select(UploadedDataset).where(
                UploadedDataset.id == dataset_id,
                UploadedDataset.business_id == business_id,
                UploadedDataset.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        if not dataset:
            logger.warning(
                "Ingestion scan trigger rejected: Dataset %s not found for business %s",
                dataset_id,
                business_id,
            )
            return None

        # 3. Idempotency Guard: Check if a scan already ran for this ingestion_job_id
        recent_runs = db.execute(
            select(FindingScanRun).where(
                FindingScanRun.business_id == business_id,
                FindingScanRun.trigger_type == "INGESTION",
            ).order_by(desc(FindingScanRun.id)).limit(100)
        ).scalars().all()

        for run in recent_runs:
            if (
                run.status == "COMPLETED"
                and run.metadata_json
                and run.metadata_json.get("ingestion_job_id") == ingestion_job_id
            ):
                logger.info(
                    "Continuous intelligence scan already completed for ingestion job %s (scan_run_id=%s) - idempotent no-op.",
                    ingestion_job_id,
                    run.id,
                )
                return ContinuousScanResponse(
                    scan_run_id=run.id,
                    business_id=run.business_id,
                    status=run.status,
                    trigger_type=run.trigger_type,
                    metrics_scanned=run.metrics_scanned,
                    findings_detected_count=run.findings_detected_count,
                    findings_new_count=run.findings_new_count,
                    findings_updated_count=run.findings_updated_count,
                    execution_time_ms=run.execution_time_ms or 0.0,
                )

        # 4. Execute Business Scan with Ingestion Provenance Metadata
        metadata = {
            "ingestion_job_id": ingestion_job_id,
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "entity": entity or job.target_entity,
        }

        return cls.execute_business_scan(
            db=db,
            current_user=current_user,
            business_id=business_id,
            trigger_type="INGESTION",
            reference_time=reference_time,
            metadata_json=metadata,
        )

    @classmethod
    def execute_business_scan(
        cls,
        db: Session,
        current_user: UserIdentity | None,
        business_id: str,
        scan_request: ContinuousScanRequest | None = None,
        trigger_type: str = "MANUAL",
        reference_time: datetime | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> ContinuousScanResponse:
        """
        Execute an end-to-end continuous intelligence scan for a business workspace.
        Enforces tenant isolation, idempotency, and deduplication of active findings.
        """
        start_time = time.perf_counter()
        if current_user is not None:
            verify_user_business_access(db, current_user, business_id, action="run continuous intelligence scan")

        biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if not biz:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Business '{business_id}' not found.")

        req = scan_request or ContinuousScanRequest()

        # 1. Determine metrics to scan (filter against active semantic model if present)
        available_metrics = ContinuousDetectionEngine.SUPPORTED_METRICS
        semantic_model = db.execute(
            select(TenantSemanticModel)
            .where(TenantSemanticModel.business_id == business_id, TenantSemanticModel.status == "ACTIVE")
            .order_by(desc(TenantSemanticModel.version))
        ).scalars().first()

        if semantic_model and semantic_model.metrics_json:
            unsupported_metrics = set()
            for m_key, m_info in semantic_model.metrics_json.items():
                if isinstance(m_info, dict) and m_info.get("status") in ("UNAVAILABLE", "INSUFFICIENT_HISTORY"):
                    unsupported_metrics.add(m_key)
            metrics_to_scan = [m for m in (req.metrics or available_metrics) if m not in unsupported_metrics]
        else:
            metrics_to_scan = req.metrics or available_metrics

        # 2. Initialize Audit Scan Run
        scan_run = FindingScanRun(
            business_id=biz.id,
            organization_id=biz.organization_id,
            status="RUNNING",
            trigger_type=trigger_type,
            metrics_scanned=metrics_to_scan,
            metadata_json=metadata_json,
        )
        db.add(scan_run)
        db.flush()

        detected_count = 0
        new_count = 0
        updated_count = 0

        # 3. Deterministic Metric Evaluations
        try:
            for metric in metrics_to_scan:
                obs = ContinuousDetectionEngine.evaluate_metric_shift(
                    db=db,
                    business_id=biz.id,
                    metric_key=metric,
                    lookback_days=req.lookback_days,
                    baseline_days=req.baseline_days,
                    min_relative_change=req.min_relative_change,
                    anomaly_iqr_multiplier=req.anomaly_iqr_multiplier,
                    reference_time=reference_time,
                )

                if obs is None:
                    continue

                detected_count += 1
                fingerprint = compute_finding_fingerprint(
                    business_id=biz.id,
                    metric_key=obs.metric_key,
                    entity_type=obs.entity_type,
                    entity_id=obs.entity_id,
                )

                now_utc = reference_time or datetime.now(UTC)

                # 4. Fingerprint-based Deduplication & Lifecycle Logic
                existing_active = db.execute(
                    select(ContinuousFinding).where(
                        ContinuousFinding.business_id == biz.id,
                        ContinuousFinding.fingerprint == fingerprint,
                        ContinuousFinding.status.in_([FindingStatus.ACTIVE.value, FindingStatus.ACKNOWLEDGED.value]),
                    )
                ).scalars().first()

                if existing_active:
                    # Update active finding in place
                    existing_active.current_value = obs.current_value
                    existing_active.delta_value = obs.delta_value
                    existing_active.relative_change_pct = obs.relative_change_pct
                    existing_active.last_detected_at = now_utc
                    existing_active.occurrence_count += 1
                    existing_active.severity = obs.severity.value
                    existing_active.confidence_score = obs.confidence_score
                    existing_active.business_impact_score = obs.business_impact_score
                    existing_active.urgency_score = obs.urgency_score
                    existing_active.calculation_details = obs.calculation_details
                    existing_active.scan_run_id = scan_run.id
                    updated_count += 1
                else:
                    # Check cooldown suppression for recently resolved or dismissed findings
                    cooldown_cutoff = now_utc - timedelta(days=req.cooldown_days)
                    recent_inactive = db.execute(
                        select(ContinuousFinding).where(
                            ContinuousFinding.business_id == biz.id,
                            ContinuousFinding.fingerprint == fingerprint,
                            ContinuousFinding.status.in_([FindingStatus.RESOLVED.value, FindingStatus.DISMISSED.value]),
                            ContinuousFinding.updated_at >= cooldown_cutoff,
                        )
                    ).scalars().first()

                    if recent_inactive:
                        # Finding is within cooldown suppression window: do not re-create
                        continue

                    # Check if an older resolved or dismissed finding exists to track recurrence count
                    older_inactive = db.execute(
                        select(ContinuousFinding)
                        .where(
                            ContinuousFinding.business_id == biz.id,
                            ContinuousFinding.fingerprint == fingerprint,
                            ContinuousFinding.status.in_([FindingStatus.RESOLVED.value, FindingStatus.DISMISSED.value]),
                        )
                        .order_by(desc(ContinuousFinding.updated_at))
                    ).scalars().first()

                    prev_occurrences = older_inactive.occurrence_count if older_inactive else 0

                    # Create new proactive finding record preserving prior history uncorrupted
                    new_finding = ContinuousFinding(
                        business_id=biz.id,
                        organization_id=biz.organization_id,
                        scan_run_id=scan_run.id,
                        fingerprint=fingerprint,
                        metric_key=obs.metric_key,
                        entity_type=obs.entity_type,
                        entity_id=obs.entity_id,
                        entity_name=obs.entity_name,
                        change_type=obs.change_type.value,
                        severity=obs.severity.value,
                        status=FindingStatus.ACTIVE.value,
                        title=obs.title,
                        summary=obs.summary,
                        current_value=obs.current_value,
                        baseline_value=obs.baseline_value,
                        delta_value=obs.delta_value,
                        relative_change_pct=obs.relative_change_pct,
                        unit=obs.unit,
                        period_start=obs.period_start,
                        period_end=obs.period_end,
                        baseline_period_start=obs.baseline_period_start,
                        baseline_period_end=obs.baseline_period_end,
                        confidence_score=obs.confidence_score,
                        business_impact_score=obs.business_impact_score,
                        urgency_score=obs.urgency_score,
                        evidence_quality=obs.evidence_quality.value,
                        calculation_details=obs.calculation_details,
                        provenance_json=obs.provenance,
                        occurrence_count=prev_occurrences + 1,
                        first_detected_at=now_utc,
                        last_detected_at=now_utc,
                    )
                    try:
                        with db.begin_nested():
                            db.add(new_finding)
                            db.flush()
                            new_count += 1
                    except IntegrityError:
                        # Concurrent scan committed in race window; update existing row
                        existing_race = db.execute(
                            select(ContinuousFinding).where(
                                ContinuousFinding.business_id == biz.id,
                                ContinuousFinding.fingerprint == fingerprint,
                                ContinuousFinding.status.in_([FindingStatus.ACTIVE.value, FindingStatus.ACKNOWLEDGED.value]),
                            )
                        ).scalars().first()
                        if existing_race:
                            existing_race.current_value = obs.current_value
                            existing_race.delta_value = obs.delta_value
                            existing_race.relative_change_pct = obs.relative_change_pct
                            existing_race.last_detected_at = now_utc
                            existing_race.occurrence_count += 1
                            existing_race.severity = obs.severity.value
                            existing_race.confidence_score = obs.confidence_score
                            existing_race.business_impact_score = obs.business_impact_score
                            existing_race.urgency_score = obs.urgency_score
                            existing_race.calculation_details = obs.calculation_details
                            existing_race.scan_run_id = scan_run.id
                            updated_count += 1

            # 5. Finalize Scan Run Audit
            scan_run.status = "COMPLETED"
            scan_run.findings_detected_count = detected_count
            scan_run.findings_new_count = new_count
            scan_run.findings_updated_count = updated_count
            scan_run.execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            db.commit()

            return ContinuousScanResponse(
                scan_run_id=scan_run.id,
                business_id=biz.id,
                status="COMPLETED",
                trigger_type=trigger_type,
                metrics_scanned=metrics_to_scan,
                findings_detected_count=detected_count,
                findings_new_count=new_count,
                findings_updated_count=updated_count,
                execution_time_ms=scan_run.execution_time_ms,
            )

        except Exception as scan_err:
            db.rollback()
            logger.exception(f"Continuous intelligence scan failed for business {business_id}")
            failed_run = FindingScanRun(
                business_id=biz.id,
                organization_id=biz.organization_id,
                status="FAILED",
                trigger_type=trigger_type,
                metrics_scanned=metrics_to_scan,
                error_message=str(scan_err)[:1000],
                execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                metadata_json=metadata_json,
            )
            try:
                db.add(failed_run)
                db.commit()
            except SQLAlchemyError:
                db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Continuous intelligence scan failed: {scan_err}",
            )

    @classmethod
    def list_findings(
        cls,
        db: Session,
        current_user: UserIdentity,
        business_id: str,
        status_filter: str | None = None,
        severity_filter: str | None = None,
        metric_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ContinuousFindingListResponse:
        """Retrieve paginated findings scoped strictly to authorized business."""
        verify_user_business_access(db, current_user, business_id, action="list continuous findings")

        base_stmt = select(ContinuousFinding).where(ContinuousFinding.business_id == business_id)

        if status_filter:
            base_stmt = base_stmt.where(ContinuousFinding.status == status_filter.upper())
        if severity_filter:
            base_stmt = base_stmt.where(ContinuousFinding.severity == severity_filter.upper())
        if metric_filter:
            base_stmt = base_stmt.where(ContinuousFinding.metric_key == metric_filter)

        total_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_count = db.execute(total_stmt).scalar() or 0

        active_stmt = select(func.count(ContinuousFinding.id)).where(
            ContinuousFinding.business_id == business_id,
            ContinuousFinding.status == FindingStatus.ACTIVE.value,
        )
        active_count = db.execute(active_stmt).scalar() or 0

        crit_stmt = select(func.count(ContinuousFinding.id)).where(
            ContinuousFinding.business_id == business_id,
            ContinuousFinding.status == FindingStatus.ACTIVE.value,
            ContinuousFinding.severity == FindingSeverity.CRITICAL.value,
        )
        critical_count = db.execute(crit_stmt).scalar() or 0

        ordered_stmt = base_stmt.order_by(
            desc(ContinuousFinding.last_detected_at),
            desc(ContinuousFinding.id),
        ).limit(limit).offset(offset)

        items = db.execute(ordered_stmt).scalars().all()

        return ContinuousFindingListResponse(
            items=[ContinuousFindingResponse.model_validate(it) for it in items],
            total_count=total_count,
            active_count=active_count,
            critical_count=critical_count,
        )

    @classmethod
    def get_finding_detail(
        cls,
        db: Session,
        current_user: UserIdentity,
        business_id: str,
        finding_id: int,
    ) -> ContinuousFindingResponse:
        """Retrieve finding details with strict business ownership validation."""
        verify_user_business_access(db, current_user, business_id, action="view finding details")

        finding = db.execute(
            select(ContinuousFinding).where(ContinuousFinding.id == finding_id)
        ).scalar_one_or_none()

        if not finding:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Finding #{finding_id} not found.")

        if finding.business_id != business_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Finding belongs to another business workspace.",
            )

        return ContinuousFindingResponse.model_validate(finding)

    @classmethod
    def update_finding_status(
        cls,
        db: Session,
        current_user: UserIdentity,
        business_id: str,
        finding_id: int,
        new_status: FindingStatus,
    ) -> ContinuousFindingResponse:
        """Acknowledge, dismiss, or resolve a proactive finding."""
        verify_user_business_access(db, current_user, business_id, action="update finding status")

        finding = db.execute(
            select(ContinuousFinding).where(ContinuousFinding.id == finding_id)
        ).scalar_one_or_none()

        if not finding:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Finding #{finding_id} not found.")

        if finding.business_id != business_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Finding belongs to another business workspace.",
            )

        current_status = FindingStatus(finding.status)
        if new_status != current_status and new_status not in ALLOWED_STATUS_TRANSITIONS.get(current_status, set()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid finding status transition from '{current_status.value}' to '{new_status.value}'.",
            )

        finding.status = new_status.value
        if new_status in (FindingStatus.ACKNOWLEDGED, FindingStatus.RESOLVED):
            finding.acknowledged_at = datetime.now(UTC)
            finding.acknowledged_by = current_user.email
        elif new_status == FindingStatus.ACTIVE:
            finding.acknowledged_at = None
            finding.acknowledged_by = None

        db.commit()
        db.refresh(finding)
        return ContinuousFindingResponse.model_validate(finding)

    @classmethod
    def record_finding_feedback(
        cls,
        db: Session,
        current_user: UserIdentity,
        business_id: str,
        finding_id: int,
        feedback_type: FeedbackType,
        notes: str | None = None,
    ) -> FindingFeedbackResponse:
        """Record human feedback on a continuous intelligence finding."""
        verify_user_business_access(db, current_user, business_id, action="record finding feedback")

        finding = db.execute(
            select(ContinuousFinding).where(ContinuousFinding.id == finding_id)
        ).scalar_one_or_none()

        if not finding:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Finding #{finding_id} not found.")

        if finding.business_id != business_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Finding belongs to another business workspace.",
            )

        feedback_entry = FindingFeedback(
            finding_id=finding.id,
            business_id=finding.business_id,
            organization_id=finding.organization_id,
            user_id=current_user.id,
            feedback_type=feedback_type.value,
            notes=notes,
        )
        db.add(feedback_entry)
        db.commit()
        db.refresh(feedback_entry)
        return FindingFeedbackResponse.model_validate(feedback_entry)

    @classmethod
    def link_finding_to_decision(
        cls,
        db: Session,
        current_user: UserIdentity,
        business_id: str,
        finding_id: int,
        decision_id: int,
    ) -> ContinuousFindingResponse:
        """
        Link a continuous intelligence finding to a Human-in-the-Loop DecisionRecord (Phase 28).
        Validates cross-entity ownership to prevent cross-business linkage.
        """
        verify_user_business_access(db, current_user, business_id, action="link finding to decision")

        finding = db.execute(
            select(ContinuousFinding).where(ContinuousFinding.id == finding_id)
        ).scalar_one_or_none()

        if not finding:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Finding #{finding_id} not found.")

        if finding.business_id != business_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Finding belongs to another business workspace.",
            )

        decision = db.execute(
            select(DecisionRecord).where(DecisionRecord.id == decision_id)
        ).scalar_one_or_none()

        if not decision:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decision #{decision_id} not found.")

        if decision.business_id != business_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Decision record belongs to another business workspace.",
            )

        finding.decision_id = decision.id
        db.commit()
        db.refresh(finding)
        return ContinuousFindingResponse.model_validate(finding)

    @classmethod
    def reconcile_pending_ingestion_scans(
        cls,
        db: Session,
        business_id: str,
        current_user: UserIdentity | None = None,
        limit: int = 10,
    ) -> list[ContinuousScanResponse]:
        """
        Reconciliation mechanism for completed ingestion jobs lacking a completed scan run.
        Recovers scans that may have been lost due to process crashes between commit and trigger.
        Enforces tenant authorization, idempotency, bounded batching, and concurrent run safety.

        NOTE: Scans are executed autonomously in the background via ContinuousIntelligenceScheduler
        when CONTINUOUS_SCHEDULER_ENABLED=True, or manually on-demand via operational trigger
        (POST /api/v1/continuous/reconcile) or ingestion retry.
        """
        if current_user is not None:
            verify_user_business_access(
                db, current_user, business_id, action="reconcile continuous intelligence scans"
            )

        candidate_jobs = (
            db.execute(
                select(IngestionJob)
                .where(
                    IngestionJob.business_id == business_id,
                    IngestionJob.status == "COMPLETED",
                )
                .order_by(desc(IngestionJob.completed_at))
                .limit(limit * 2)
            )
            .scalars()
            .all()
        )

        bind = db.get_bind() if hasattr(db, "get_bind") else getattr(db, "bind", None)
        is_postgres = (
            bind is not None
            and getattr(bind, "dialect", None) is not None
            and bind.dialect.name == "postgresql"
        )

        reconciled_responses: list[ContinuousScanResponse] = []
        for candidate in candidate_jobs:
            # 1. Concurrency-safe atomic claim on candidate IngestionJob
            stmt = select(IngestionJob).where(
                IngestionJob.id == candidate.id,
                IngestionJob.business_id == business_id,
                IngestionJob.status == "COMPLETED",
            )
            if is_postgres:
                stmt = stmt.with_for_update(skip_locked=True)

            job = db.execute(stmt).scalar_one_or_none()
            if not job:
                # In PostgreSQL: Job is currently locked by a concurrent worker
                logger.info(
                    "Candidate ingestion job %s locked by concurrent worker - skipping.",
                    candidate.id,
                )
                continue

            # 2. Check under lock if job already has a completed or in-flight scan run
            existing_runs = (
                db.execute(
                    select(FindingScanRun).where(
                        FindingScanRun.business_id == business_id,
                        FindingScanRun.trigger_type == "INGESTION",
                        FindingScanRun.status.in_(["COMPLETED", "RUNNING"]),
                    )
                )
                .scalars()
                .all()
            )
            already_scanned = any(
                r.metadata_json and r.metadata_json.get("ingestion_job_id") == job.id
                for r in existing_runs
            )
            if already_scanned:
                continue

            logger.info(
                "Reconciling pending ingestion scan for job %s (business %s)",
                job.id,
                business_id,
            )
            try:
                resp = cls.trigger_ingestion_scan(
                    db=db,
                    business_id=business_id,
                    organization_id=job.organization_id,
                    dataset_id=job.dataset_id,
                    ingestion_job_id=job.id,
                    entity=job.target_entity,
                )
                if resp:
                    reconciled_responses.append(resp)
            except Exception as scan_err:  # noqa: BLE001
                logger.warning(
                    "Reconciliation scan execution failed for job %s (business %s): %s",
                    job.id,
                    business_id,
                    scan_err,
                )
                if is_postgres:
                    db.rollback()

            if len(reconciled_responses) >= limit:
                break

        return reconciled_responses
