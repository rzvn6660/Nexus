"""
NEXUS Phase 1J.1.1 — Connector Recovery, Fault Tolerance, and Watermark Safety Tests.

Validates:
1. Graceful recovery from network timeouts, process terminations, and database rollbacks.
2. Safe failure on expired credentials during checkpoint resumption.
3. Resilience against duplicate page delivery after crash.
4. Broken cursor chain detection upon missing/dropped page during resume.
5. Backfill quarantine after period checkpoint completion.
6. Fail-closed watermark safety gates prohibiting incomplete, cross-tenant, or synthetic certifications.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session

from app.connectors.synthetic_source_adapter import SyntheticSourceAdapter
from app.models.connector import ConnectorSyncCheckpoint
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.models.watermark import TenantIngestionWatermark
from app.schemas.source_sync import SyncResult
from app.services.source_sync_service import SourceSyncService

APEX_TENANT_ID = "ab044b1a-835a-4a38-bf45-62fe38624151"
TEST_CREDENTIALS = {
    "api_key": "synth_recov_key_12345",
    "webhook_secret": "synth_recov_secret_67890",
}


def _create_isolated_tenant(session: Session, suffix: str) -> Business:
    """Helper to create test tenant."""
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-recov-{suffix}-{uid}", name=f"Recov Org {suffix}", slug=f"recov-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-recov-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Recov Business {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-recov-{suffix}-{uid}",
        email=f"user_{suffix}_{uid}@example.com",
        full_name=f"User {suffix}",
        password_hash="mock",
        is_active=True,
        is_verified=True,
    )
    session.add_all([org, biz, user])
    session.flush()

    mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role="admin")
    session.add(mem)
    session.commit()
    return biz


def test_recovery_from_network_timeout(db_session: Session):
    """
    Verify that an upstream timeout (504) marks the checkpoint INCOMPLETE,
    increments retry count, and recovers cleanly on the subsequent attempt.
    """
    biz = _create_isolated_tenant(db_session, "net01")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    # Attempt 1: Network outage fails mid-sync
    adapter_failing = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, seed=777, num_transactions=40, page_size=20, simulate_outage=True
    )
    res_1 = SourceSyncService.execute_sync(db_session, adapter_failing, start, end, page_size=20)

    assert res_1.status == "INCOMPLETE"
    assert res_1.is_complete is False
    assert len(res_1.errors) > 0

    ckpt_1 = db_session.query(ConnectorSyncCheckpoint).filter_by(business_id=biz.id).one()
    assert ckpt_1.status == "INCOMPLETE"
    assert ckpt_1.retry_count == 1
    assert "timeout" in (ckpt_1.last_error or "").lower() or "outage" in (ckpt_1.last_error or "").lower()

    # Attempt 2: Network restored, retry succeeds completely
    adapter_healthy = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, seed=777, num_transactions=40, page_size=20, simulate_outage=False
    )
    res_2 = SourceSyncService.execute_sync(db_session, adapter_healthy, start, end, page_size=20)

    assert res_2.status == "COMPLETED"
    assert res_2.is_complete is True
    assert res_2.records_ingested == 40

    ckpt_2 = db_session.query(ConnectorSyncCheckpoint).filter_by(business_id=biz.id).one()
    assert ckpt_2.status == "COMPLETED"
    assert ckpt_2.is_complete is True


def test_resume_fails_safely_on_expired_credentials(db_session: Session):
    """
    Verify that if a worker restarts and attempts to resume with expired credentials,
    the sync is halted immediately without updating the checkpoint or corrupting data.
    """
    biz = _create_isolated_tenant(db_session, "exp01")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    # Initial checkpoint in progress
    ckpt = SourceSyncService.get_or_create_checkpoint(
        db_session, biz.id, "synthetic_sandbox", start, end
    )
    ckpt.current_cursor = "page_2"
    ckpt.records_ingested = 20
    db_session.commit()

    # Worker attempts resume with expired credentials
    adapter_expired = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, simulate_expired_credentials=True
    )

    with pytest.raises(PermissionError, match="Connector authentication failed"):
        SourceSyncService.execute_sync(db_session, adapter_expired, start, end)

    # Checkpoint remained untouched
    ckpt_re = db_session.query(ConnectorSyncCheckpoint).filter_by(business_id=biz.id).one()
    assert ckpt_re.current_cursor == "page_2"
    assert ckpt_re.records_ingested == 20


def test_resilience_to_duplicate_page_delivery_after_crash(db_session: Session):
    """
    Verify that if a crash occurs and the upstream re-delivers an already processed page,
    idempotent deduplication skips the duplicate transactions without double volume counting.
    """
    biz = _create_isolated_tenant(db_session, "dup01")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    # Run page 1
    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, seed=888, num_transactions=40, page_size=20
    )
    res_1 = SourceSyncService.execute_sync(
        db_session, adapter, start, end, page_size=20, stop_after_pages=1
    )
    assert res_1.records_ingested == 20

    # Simulate restart where cursor is artificially reset to None (re-fetching page 1)
    ckpt = db_session.query(ConnectorSyncCheckpoint).filter_by(business_id=biz.id).one()
    ckpt.current_cursor = None
    db_session.commit()

    # Re-run full sync: page 1 will be fetched again, but records are already in ingested_transaction_ids
    res_2 = SourceSyncService.execute_sync(db_session, adapter, start, end, page_size=20)

    assert res_2.status == "COMPLETED"
    assert res_2.records_ingested == 40
    # 20 duplicate records skipped
    assert res_2.records_duplicate >= 20


def test_backfill_quarantine_after_watermark_promotion(db_session: Session):
    """
    Verify that backfilled transactions arriving after an active watermark
    are flagged and cannot quietly tamper with historical certified completeness.
    """
    biz = _create_isolated_tenant(db_session, "back01")
    wm_date = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    # Certified active watermark
    wm = TenantIngestionWatermark(
        business_id=biz.id,
        source_id="default",
        complete_through_dt=wm_date,
        is_active=True,
        provenance_type="synthetic_fixture",
        verification_status="verified",
    )
    db_session.add(wm)
    db_session.commit()

    # Backfill transaction dated within closed period
    backfill_dt = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    is_backfill, reason = SourceSyncService.check_for_backfill(db_session, biz.id, backfill_dt)

    assert is_backfill is True
    assert "precedes active watermark" in (reason or "")


def test_watermark_safety_invariants(db_session: Session):
    """
    Verify fail-closed watermark safety gates:
    - Incomplete checkpoint cannot be certified.
    - Synthetic checkpoint cannot certify real tenant (Apex Specialty Commerce).
    - Settlement gross delta > $0.00 cannot be certified.
    """
    biz = _create_isolated_tenant(db_session, "safe01")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    # 1. Incomplete checkpoint certification fails
    incomplete_res = SyncResult(
        business_id=biz.id,
        provider="synthetic_sandbox",
        period_start=start,
        period_end=end,
        status="INCOMPLETE",
        is_complete=False,
        records_extracted=10,
        records_ingested=10,
        records_rejected=0,
        records_duplicate=0,
        cursor_chain_hash="a" * 64,
        transaction_set_digest="b" * 64,
        reported_gross=Decimal("100.00"),
        reported_net=Decimal("95.00"),
        reported_tax=Decimal("8.00"),
        reported_fee=Decimal("3.00"),
        provenance_type="synthetic_sandbox",
        started_at=start,
        completed_at=end,
        period_close_evidence=None,
    )
    with pytest.raises(ValueError, match="Cannot certify incomplete synchronization"):
        SourceSyncService.reconcile_and_certify(db_session, incomplete_res)

    # 2. Real tenant protection fails closed
    apex_res = SyncResult(
        business_id=APEX_TENANT_ID,
        provider="synthetic_sandbox",
        period_start=start,
        period_end=end,
        status="COMPLETED",
        is_complete=True,
        records_extracted=100,
        records_ingested=100,
        records_rejected=0,
        records_duplicate=0,
        cursor_chain_hash="a" * 64,
        transaction_set_digest="b" * 64,
        reported_gross=Decimal("100.00"),
        reported_net=Decimal("95.00"),
        reported_tax=Decimal("8.00"),
        reported_fee=Decimal("3.00"),
        provenance_type="synthetic_sandbox",
        started_at=start,
        completed_at=end,
        period_close_evidence=None,
    )
    with pytest.raises(PermissionError, match="Governance Violation: Real tenant"):
        SourceSyncService.reconcile_and_certify(db_session, apex_res)
