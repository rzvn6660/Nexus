"""Unit and Integration Tests for Phase 29 Stage 3: Scheduled Continuous Intelligence.

Verifies:
1. Scheduler initialization, default configuration, and telemetry properties.
2. Disabled scheduler configuration handling.
3. Cooperative lifecycle management (start, graceful stop with timeout, idempotent stop).
4. Autonomous reconciliation execution via run_single_tick.
5. Completed scans are not repeated (idempotency under background execution).
6. Bounded batch execution per tick (max_businesses and batch_size limits).
7. Failed scans remain retryable on subsequent scheduler ticks.
8. Fault tolerance and tenant error isolation across businesses.
9. Multi-instance concurrency safety and PostgreSQL lease lock skipping simulation.
10. REST API telemetry endpoint (/api/v1/continuous/scheduler/status) authentication and schema.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from app.analytics.continuous.engine import ContinuousDetectionEngine
from app.analytics.continuous.scheduler import ContinuousIntelligenceScheduler
from app.analytics.continuous.service import ContinuousIntelligenceService
from app.core.auth import AuthService
from app.core.config import settings
from app.models.continuous import FindingScanRun
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import (
    Business,
    IngestionJob,
    Organization,
    OrganizationMembership,
    UploadedDataset,
    UserIdentity,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def scheduler_tenant(db_session: Session) -> dict:
    """Seed Org, User, and Business for scheduler tests."""
    org = Organization(id=f"org_sched_{uuid.uuid4().hex[:8]}", name="Scheduler Org", slug=f"sched-org-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    db_session.flush()

    user = UserIdentity(
        id=f"usr_sched_{uuid.uuid4().hex[:8]}",
        email=f"sched_{uuid.uuid4().hex[:6]}@nexus.internal",
        full_name="Scheduler Analyst",
        password_hash="pw_hash_test",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.flush()

    mem = OrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role="owner",
    )
    db_session.add(mem)

    biz = Business(
        id=f"biz_sched_{uuid.uuid4().hex[:8]}",
        organization_id=org.id,
        name="Scheduler Test Workspace",
        status="active",
    )
    db_session.add(biz)
    db_session.commit()

    return {"org": org, "user": user, "biz": biz}


def _seed_completed_ingestion(
    db: Session,
    biz_id: str,
    org_id: str,
    filename: str = "sales.csv",
) -> IngestionJob:
    """Helper to create a completed IngestionJob with ready dataset."""
    ds = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        business_id=biz_id,
        filename=filename,
        file_type="csv",
        storage_key=f"/tmp/{filename}",
        file_size_bytes=1024,
        readiness_status="READY",
    )
    job = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        business_id=biz_id,
        dataset_id=ds.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(ds)
    db.add(job)
    db.commit()
    return job


def _seed_sale(
    db: Session,
    biz_id: str,
    days_ago: int,
    amount: float,
) -> Sale:
    """Helper to seed minimal sale records for metrics detection."""
    uid = uuid.uuid4().hex[:8]
    cust = Customer(
        business_id=biz_id,
        customer_code=f"CUST-{uid}",
        name=f"Scheduler Customer {uid}",
        email=f"sched_{uid}@example.com",
        city="New York",
        customer_segment="Standard",
        acquisition_date=date(2024, 1, 1),
    )
    db.add(cust)
    db.flush()

    dt = datetime.now(UTC) - timedelta(days=days_ago)
    s = Sale(
        business_id=biz_id,
        customer_id=cust.id,
        transaction_date=dt,
        transaction_number=f"TXN-SCHED-{uuid.uuid4().hex[:8]}",
        subtotal=Decimal(str(amount)),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal(str(amount)),
        status="completed",
    )
    db.add(s)
    db.flush()
    return s


# ---------------------------------------------------------------------------
# 1. SCHEDULER CONFIGURATION & TELEMETRY TESTS
# ---------------------------------------------------------------------------

def test_scheduler_default_config_and_telemetry_properties():
    """Verify scheduler defaults from settings and configurable parameters."""
    scheduler = ContinuousIntelligenceScheduler()
    assert scheduler.interval_seconds == settings.CONTINUOUS_SCHEDULER_INTERVAL_SECONDS
    assert scheduler.batch_size == settings.CONTINUOUS_SCHEDULER_BATCH_SIZE
    assert scheduler.max_businesses == settings.CONTINUOUS_SCHEDULER_MAX_BUSINESSES_PER_TICK
    assert scheduler.startup_delay_seconds == settings.CONTINUOUS_SCHEDULER_STARTUP_DELAY_SECONDS
    assert not scheduler.is_running

    stats = scheduler.stats
    assert stats["is_running"] is False
    assert stats["enabled"] == settings.CONTINUOUS_SCHEDULER_ENABLED
    assert stats["interval_seconds"] == settings.CONTINUOUS_SCHEDULER_INTERVAL_SECONDS
    assert stats["batch_size"] == settings.CONTINUOUS_SCHEDULER_BATCH_SIZE
    assert stats["max_businesses"] == settings.CONTINUOUS_SCHEDULER_MAX_BUSINESSES_PER_TICK
    assert stats["total_ticks"] == 0
    assert stats["total_reconciled_scans"] == 0
    assert stats["last_tick_at"] is None
    assert stats["last_tick_duration_ms"] is None
    assert stats["last_tick_reconciled"] == 0
    assert stats["last_tick_errors"] == 0


def test_scheduler_custom_constructor_overrides():
    """Verify custom parameters override system settings."""
    scheduler = ContinuousIntelligenceScheduler(
        interval_seconds=30,
        batch_size=5,
        max_businesses=15,
        startup_delay_seconds=2,
    )
    assert scheduler.interval_seconds == 30
    assert scheduler.batch_size == 5
    assert scheduler.max_businesses == 15
    assert scheduler.startup_delay_seconds == 2


def test_scheduler_disabled_configuration_skips_start():
    """Verify scheduler respects master disable switch."""
    with patch("app.analytics.continuous.scheduler.settings.CONTINUOUS_SCHEDULER_ENABLED", False):
        scheduler = ContinuousIntelligenceScheduler()
        scheduler.start()
        assert not scheduler.is_running
        assert scheduler.stats["is_running"] is False


# ---------------------------------------------------------------------------
# 2. LIFECYCLE & COOPERATIVE SHUTDOWN TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduler_startup_and_graceful_shutdown():
    """Verify start and cooperative stop sequence with timeout."""
    with patch("app.analytics.continuous.scheduler.settings.CONTINUOUS_SCHEDULER_ENABLED", True):
        scheduler = ContinuousIntelligenceScheduler(
            interval_seconds=1,
            startup_delay_seconds=0,
        )
        scheduler.start()
        assert scheduler.is_running is True

        # Idempotent second start
        scheduler.start()
        assert scheduler.is_running is True

        # Graceful stop
        await scheduler.stop(timeout_seconds=2.0)
        assert scheduler.is_running is False
        assert scheduler._task is None

        # Idempotent second stop
        await scheduler.stop(timeout_seconds=1.0)
        assert scheduler.is_running is False


# ---------------------------------------------------------------------------
# 3. DETERMINISTIC RECONCILIATION TICK TESTS
# ---------------------------------------------------------------------------

def test_scheduler_run_single_tick_autonomous_reconciliation(
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify run_single_tick reconciles an un-scanned completed ingestion job."""
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    _seed_sale(db_session, biz.id, days_ago=5, amount=500.0)
    _seed_sale(db_session, biz.id, days_ago=35, amount=1200.0)
    job = _seed_completed_ingestion(db_session, biz.id, org.id)

    # Verify no scans exist
    initial_runs = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
    ).scalars().all()
    assert len(initial_runs) == 0

    # Run scheduler tick
    summary = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=5,
    )

    assert summary["businesses_scanned"] >= 1
    assert summary["total_reconciled"] == 1
    assert len(summary["errors"]) == 0

    # Verify scan run exists with COMPLETED status
    runs = db_session.execute(
        select(FindingScanRun).where(
            FindingScanRun.business_id == biz.id,
            FindingScanRun.trigger_type == "INGESTION",
        )
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "COMPLETED"
    assert runs[0].metadata_json["ingestion_job_id"] == job.id


def test_scheduler_run_single_tick_completed_scans_not_repeated(
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify completed scans are not repeatedly reconciled on subsequent ticks."""
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    job = _seed_completed_ingestion(db_session, biz.id, org.id)

    # Seed a pre-existing COMPLETED scan run for this job
    run = FindingScanRun(
        business_id=biz.id,
        organization_id=org.id,
        status="COMPLETED",
        trigger_type="INGESTION",
        metrics_scanned=["net_sales"],
        metadata_json={"ingestion_job_id": job.id},
    )
    db_session.add(run)
    db_session.commit()

    # Run tick
    summary = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=5,
    )

    # Must be 0 reconciled (idempotent no-op)
    assert summary["total_reconciled"] == 0

    # Verify total scan count remains 1
    runs = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
    ).scalars().all()
    assert len(runs) == 1


def test_scheduler_run_single_tick_bounded_batches(
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify batch_size enforces bounded processing per business."""
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    _seed_completed_ingestion(db_session, biz.id, org.id, filename="job1.csv")
    _seed_completed_ingestion(db_session, biz.id, org.id, filename="job2.csv")
    _seed_completed_ingestion(db_session, biz.id, org.id, filename="job3.csv")

    # Tick 1: batch_size = 2 -> should reconcile exactly 2 jobs
    summary1 = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=2,
    )
    assert summary1["total_reconciled"] == 2

    # Tick 2: batch_size = 2 -> should reconcile remaining 1 job
    summary2 = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=2,
    )
    assert summary2["total_reconciled"] == 1

    # Tick 3: all done -> 0 reconciled
    summary3 = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=2,
    )
    assert summary3["total_reconciled"] == 0


def test_scheduler_run_single_tick_retries_failed_scans(
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify prior FAILED scans remain retryable and reconcile to COMPLETED."""
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    job = _seed_completed_ingestion(db_session, biz.id, org.id)

    # Seed a prior FAILED scan run
    failed_run = FindingScanRun(
        business_id=biz.id,
        organization_id=org.id,
        status="FAILED",
        trigger_type="INGESTION",
        metrics_scanned=[],
        error_message="Simulated prior timeout",
        metadata_json={"ingestion_job_id": job.id},
    )
    db_session.add(failed_run)
    db_session.commit()

    # Scheduler tick executes
    summary = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=5,
    )

    # Candidate job was eligible for retry
    assert summary["total_reconciled"] == 1

    # DB now has 1 FAILED run and 1 COMPLETED run for this job
    runs = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
    ).scalars().all()
    assert len(runs) == 2
    statuses = {r.status for r in runs}
    assert statuses == {"FAILED", "COMPLETED"}


def test_scheduler_run_single_tick_error_isolation_across_businesses(
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify an unhandled exception in one business workspace does not abort others."""
    biz_a = scheduler_tenant["biz"]
    org_a = scheduler_tenant["org"]

    # Create second business
    biz_b = Business(
        id=f"biz_b_{uuid.uuid4().hex[:8]}",
        organization_id=org_a.id,
        name="Second Business",
        status="active",
    )
    db_session.add(biz_b)
    db_session.commit()

    _seed_completed_ingestion(db_session, biz_a.id, org_a.id)
    _seed_completed_ingestion(db_session, biz_b.id, org_a.id)

    orig_reconcile = ContinuousIntelligenceService.reconcile_pending_ingestion_scans

    def flaky_reconcile(db, business_id, current_user=None, limit=10):
        if business_id == biz_a.id:
            raise RuntimeError(f"Database error for workspace {business_id}")
        return orig_reconcile(db, business_id, current_user, limit)

    with patch.object(ContinuousIntelligenceService, "reconcile_pending_ingestion_scans", side_effect=flaky_reconcile):
        summary = ContinuousIntelligenceScheduler.run_single_tick(
            db=db_session,
            max_businesses=10,
            batch_size=5,
        )

    assert summary["businesses_scanned"] >= 2
    assert summary["total_reconciled"] == 1
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["business_id"] == biz_a.id


# ---------------------------------------------------------------------------
# 4. MULTI-INSTANCE CONCURRENCY & LOCK SEMANTICS (AUDIT VERIFICATION)
# ---------------------------------------------------------------------------

def test_scheduler_multiple_jobs_same_business_reconciled(
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify multiple completed ingestion jobs for the same business are all cleanly reconciled."""
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    job1 = _seed_completed_ingestion(db_session, biz.id, org.id, filename="sales_q1.csv")
    job2 = _seed_completed_ingestion(db_session, biz.id, org.id, filename="sales_q2.csv")
    job3 = _seed_completed_ingestion(db_session, biz.id, org.id, filename="sales_q3.csv")

    summary = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=10,
    )

    assert summary["total_reconciled"] == 3
    assert len(summary["errors"]) == 0

    runs = db_session.execute(
        select(FindingScanRun).where(
            FindingScanRun.business_id == biz.id,
            FindingScanRun.trigger_type == "INGESTION",
        )
    ).scalars().all()
    assert len(runs) == 3
    scanned_job_ids = {r.metadata_json.get("ingestion_job_id") for r in runs}
    assert scanned_job_ids == {job1.id, job2.id, job3.id}

    # Subsequent tick reconciles 0 (idempotent)
    second_summary = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=10,
    )
    assert second_summary["total_reconciled"] == 0


def test_scheduler_two_instances_concurrent_job_partitioning(
    db_session: Session,
    scheduler_tenant: dict,
):
    """
    Verify two scheduler instances processing the same business with multiple jobs.
    When Instance 1 holds the lock on Job A, Instance 2 cleanly skips Job A (SKIP LOCKED)
    and processes Job B, avoiding duplication and deadlocks.
    """
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    job_a = _seed_completed_ingestion(db_session, biz.id, org.id, filename="job_a.csv")
    job_b = _seed_completed_ingestion(db_session, biz.id, org.id, filename="job_b.csv")

    orig_execute = db_session.execute

    # Simulate Instance 2: Job A is locked by Instance 1, so Job A returns None under FOR UPDATE SKIP LOCKED
    def instance2_execute(stmt, *args, **kwargs):
        if hasattr(stmt, "_for_update_arg") and stmt._for_update_arg is not None and getattr(stmt._for_update_arg, "skip_locked", False):
            stmt_str = str(stmt)
            if "ingestion_jobs" in stmt_str and job_a.id in stmt_str:
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None
                return mock_result
        return orig_execute(stmt, *args, **kwargs)

    # 1. Instance 1 reconciles (processes Job A)
    with patch.object(db_session.bind.dialect, "name", "postgresql"):
        reconciled_inst1 = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
            db=db_session,
            business_id=biz.id,
            limit=1,
        )
    assert len(reconciled_inst1) == 1
    assert reconciled_inst1[0].status == "COMPLETED"

    # 2. Instance 2 reconciles concurrently (Job A is locked/skipped, so Instance 2 claims Job B)
    with patch.object(db_session.bind.dialect, "name", "postgresql"), patch.object(db_session, "execute", side_effect=instance2_execute):
        reconciled_inst2 = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
            db=db_session,
            business_id=biz.id,
            limit=1,
        )
    assert len(reconciled_inst2) == 1
    assert reconciled_inst2[0].status == "COMPLETED"

    # Verify both jobs were scanned exactly once across both instances
    all_runs = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
    ).scalars().all()
    job_ids = [r.metadata_json.get("ingestion_job_id") for r in all_runs if r.metadata_json]
    assert sorted(job_ids) == sorted([job_a.id, job_b.id])
    assert len(all_runs) == 2


def test_scheduler_overlapping_manual_and_ingestion_triggers(
    db_session: Session,
    scheduler_tenant: dict,
):
    """
    Verify scheduled reconciliation overlapping manual reconciliation and ingestion-triggered scans.
    All three pathways use the exact same atomic IngestionJob row-locking protocol.
    """
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    job = _seed_completed_ingestion(db_session, biz.id, org.id, filename="overlap.csv")

    orig_execute = db_session.execute

    # 1. Simulate lock contention: while Scheduled reconciliation holds Job lock,
    # manual reconciliation attempts to process the same job
    def locked_job_execute(stmt, *args, **kwargs):
        if hasattr(stmt, "_for_update_arg") and stmt._for_update_arg is not None and getattr(stmt._for_update_arg, "skip_locked", False):
            stmt_str = str(stmt)
            if "ingestion_jobs" in stmt_str:
                mock_res = MagicMock()
                mock_res.scalar_one_or_none.return_value = None
                return mock_res
        return orig_execute(stmt, *args, **kwargs)

    # Manual reconciliation caller sees job is locked by another worker -> skips cleanly
    with patch.object(db_session.bind.dialect, "name", "postgresql"), patch.object(db_session, "execute", side_effect=locked_job_execute):
        manual_results = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
            db=db_session,
            business_id=biz.id,
            limit=10,
        )
    assert manual_results == []

    # Ingestion-triggered caller sees job is locked by another worker -> returns None cleanly
    with patch.object(db_session.bind.dialect, "name", "postgresql"), patch.object(db_session, "execute", side_effect=locked_job_execute):
        trigger_result = ContinuousIntelligenceService.trigger_ingestion_scan(
            db=db_session,
            business_id=biz.id,
            organization_id=org.id,
            dataset_id=job.dataset_id,
            ingestion_job_id=job.id,
        )
    assert trigger_result is None

    # Now Scheduled reconciliation executes successfully
    with patch.object(db_session.bind.dialect, "name", "postgresql"):
        sched_results = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
            db=db_session,
            business_id=biz.id,
            limit=10,
        )
    assert len(sched_results) == 1
    assert sched_results[0].status == "COMPLETED"

    # After Scheduled scan commits, subsequent ingestion trigger returns existing scan run (idempotent)
    post_commit_trigger = ContinuousIntelligenceService.trigger_ingestion_scan(
        db=db_session,
        business_id=biz.id,
        organization_id=org.id,
        dataset_id=job.dataset_id,
        ingestion_job_id=job.id,
    )
    assert post_commit_trigger is not None
    assert post_commit_trigger.scan_run_id == sched_results[0].scan_run_id
    assert post_commit_trigger.status == "COMPLETED"


def test_scheduler_commit_rollback_and_failed_scan_retry_lifecycle(
    db_session: Session,
    scheduler_tenant: dict,
):
    """
    Verify complete transaction lifecycle:
    1. Scan execution error triggers transaction rollback of findings.
    2. A FAILED FindingScanRun is persisted in a clean committed transaction.
    3. The job lock is released on failure commit.
    4. On subsequent scheduler tick, the job is cleanly re-claimed and retried to COMPLETED.
    """
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    job = _seed_completed_ingestion(db_session, biz.id, org.id, filename="flaky_scan.csv")

    # Step 1: Force failure during metric evaluation
    with patch.object(ContinuousDetectionEngine, "evaluate_metric_shift", side_effect=RuntimeError("Transient calculation fault")):
        summary1 = ContinuousIntelligenceScheduler.run_single_tick(
            db=db_session,
            max_businesses=10,
            batch_size=5,
        )

    # Tick completes without crashing; scan failed
    assert summary1["total_reconciled"] == 0

    # Verify FAILED run was persisted after rollback
    failed_runs = db_session.execute(
        select(FindingScanRun).where(
            FindingScanRun.business_id == biz.id,
            FindingScanRun.status == "FAILED",
        )
    ).scalars().all()
    assert len(failed_runs) == 1
    assert failed_runs[0].metadata_json["ingestion_job_id"] == job.id
    assert "Transient calculation fault" in (failed_runs[0].error_message or "")

    # Step 2: Next scheduler tick runs with healthy engine -> retry succeeds
    summary2 = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=5,
    )
    assert summary2["total_reconciled"] == 1

    # Verify DB now has 1 FAILED run and 1 COMPLETED run
    all_runs = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
    ).scalars().all()
    assert len(all_runs) == 2
    statuses = {r.status for r in all_runs}
    assert statuses == {"FAILED", "COMPLETED"}

    # Step 3: Third tick finds nothing to reconcile
    summary3 = ContinuousIntelligenceScheduler.run_single_tick(
        db=db_session,
        max_businesses=10,
        batch_size=5,
    )
    assert summary3["total_reconciled"] == 0


def test_scheduler_simulated_postgres_job_lock_skipping(
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify simulated PostgreSQL FOR UPDATE SKIP LOCKED on IngestionJob bypasses locked candidate jobs."""
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    _seed_completed_ingestion(db_session, biz.id, org.id)

    orig_execute = db_session.execute

    def mock_execute(stmt, *args, **kwargs):
        if hasattr(stmt, "_for_update_arg") and stmt._for_update_arg is not None and getattr(stmt._for_update_arg, "skip_locked", False):
            stmt_str = str(stmt)
            if "ingestion_jobs" in stmt_str:
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None
                return mock_result
        return orig_execute(stmt, *args, **kwargs)

    with patch.object(db_session.bind.dialect, "name", "postgresql"), patch.object(db_session, "execute", side_effect=mock_execute):
        summary = ContinuousIntelligenceScheduler.run_single_tick(
            db=db_session,
            max_businesses=10,
            batch_size=5,
        )

    # Job was locked by another worker -> skipped cleanly
    assert summary["total_reconciled"] == 0


# ---------------------------------------------------------------------------
# 5. REST API TELEMETRY ENDPOINT TESTS
# ---------------------------------------------------------------------------

def test_scheduler_status_api_endpoint_authenticated(
    api_client: TestClient,
    auth_headers: dict[str, str],
):
    """Verify GET /api/v1/continuous/scheduler/status returns runtime statistics."""
    resp = api_client.get(
        "/api/v1/continuous/scheduler/status",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "is_running" in data
    assert "enabled" in data
    assert "interval_seconds" in data
    assert "batch_size" in data
    assert "max_businesses" in data
    assert "total_ticks" in data
    assert "total_reconciled_scans" in data
    assert "last_tick_at" in data
    assert "last_tick_duration_ms" in data


def test_scheduler_status_api_endpoint_unauthenticated(
    api_client: TestClient,
):
    """Verify GET /api/v1/continuous/scheduler/status rejects anonymous requests."""
    resp = api_client.get("/api/v1/continuous/scheduler/status")
    assert resp.status_code == 401


def test_scheduler_status_api_endpoint_forbidden_for_regular_member(
    api_client: TestClient,
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify GET /api/v1/continuous/scheduler/status rejects authenticated non-admin users (role=member)."""
    org = scheduler_tenant["org"]
    biz = scheduler_tenant["biz"]

    member_user = UserIdentity(
        id=f"usr_mem_{uuid.uuid4().hex[:8]}",
        email=f"member_{uuid.uuid4().hex[:6]}@nexus.internal",
        full_name="Regular Member",
        password_hash="pw_hash_test",
        is_active=True,
        is_verified=True,
    )
    db_session.add(member_user)
    db_session.flush()

    mem_membership = OrganizationMembership(
        user_id=member_user.id,
        organization_id=org.id,
        role="member",
    )
    db_session.add(mem_membership)
    db_session.commit()

    token = AuthService.create_access_token(
        user_id=member_user.id,
        email=member_user.email,
        organization_id=org.id,
        business_id=biz.id,
    )
    headers = {"Authorization": f"Bearer {token}", "X-Business-ID": biz.id}

    resp = api_client.get("/api/v1/continuous/scheduler/status", headers=headers)
    assert resp.status_code == 403
    assert "Administrative privileges" in resp.json()["detail"]


def test_scheduler_status_api_endpoint_allowed_for_admin_role(
    api_client: TestClient,
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify GET /api/v1/continuous/scheduler/status succeeds for admin role."""
    org = scheduler_tenant["org"]
    biz = scheduler_tenant["biz"]

    admin_user = UserIdentity(
        id=f"usr_adm_{uuid.uuid4().hex[:8]}",
        email=f"admin_{uuid.uuid4().hex[:6]}@nexus.internal",
        full_name="Admin User",
        password_hash="pw_hash_test",
        is_active=True,
        is_verified=True,
    )
    db_session.add(admin_user)
    db_session.flush()

    admin_membership = OrganizationMembership(
        user_id=admin_user.id,
        organization_id=org.id,
        role="admin",
    )
    db_session.add(admin_membership)
    db_session.commit()

    token = AuthService.create_access_token(
        user_id=admin_user.id,
        email=admin_user.email,
        organization_id=org.id,
        business_id=biz.id,
    )
    headers = {"Authorization": f"Bearer {token}", "X-Business-ID": biz.id}

    resp = api_client.get("/api/v1/continuous/scheduler/status", headers=headers)
    assert resp.status_code == 200
    assert "is_running" in resp.json()


def test_reconcile_service_skips_when_job_locked_by_concurrent_worker(
    db_session: Session,
    scheduler_tenant: dict,
):
    """Verify reconcile_pending_ingestion_scans skips candidate IngestionJobs currently locked by another worker."""
    biz = scheduler_tenant["biz"]
    org = scheduler_tenant["org"]

    _seed_completed_ingestion(db_session, biz.id, org.id)

    orig_execute = db_session.execute

    def mock_execute(stmt, *args, **kwargs):
        # When checking SELECT IngestionJob ... FOR UPDATE SKIP LOCKED
        if hasattr(stmt, "_for_update_arg") and stmt._for_update_arg is not None and getattr(stmt._for_update_arg, "skip_locked", False):
            stmt_str = str(stmt)
            if "ingestion_jobs" in stmt_str:
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None
                return mock_result
        return orig_execute(stmt, *args, **kwargs)

    with patch.object(db_session.bind.dialect, "name", "postgresql"), patch.object(db_session, "execute", side_effect=mock_execute):
        reconciled = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
            db=db_session,
            business_id=biz.id,
            limit=10,
        )

    # Job was locked by another instance -> returns empty list immediately
    assert reconciled == []
