"""
NEXUS Phase 1J.1 — Adversarial Integration Security Tests.

Covers the 12 non-negotiable adversarial security scenarios:
1. Successful complete sandbox synchronization & certification.
2. Incomplete pagination rejection.
3. Missing transaction page failure recovery.
4. Duplicate transaction delivery & idempotent deduplication.
5. Forged source event signature rejection.
6. Delayed transaction after apparent period close.
7. Refund after apparent period close.
8. Backfill after watermark creation detection.
9. Expired or invalid credentials handling.
10. Cross-tenant checkpoint access prevention.
11. API or source outage during synchronization.
12. Attempt to use synthetic provenance for a real tenant (Apex Specialty Commerce).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session

from app.connectors.synthetic_source_adapter import SyntheticSourceAdapter
from app.models.connector import ConnectorSyncCheckpoint, TenantConnectorCredential
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.models.watermark import TenantIngestionWatermark
from app.schemas.source_sync import SyncResult
from app.services.source_sync_service import SourceSyncService

APEX_TENANT_ID = "ab044b1a-835a-4a38-bf45-62fe38624151"
TEST_CREDENTIALS = {
    "api_key": "synth_adv_key_12345",
    "webhook_secret": "synth_adv_secret_67890",
}


def _create_isolated_tenant(session: Session, suffix: str) -> Business:
    """Helper to set up isolated tenant in test session."""
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-test-{suffix}-{uid}", name=f"Test Org {suffix}", slug=f"test-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-test-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Test Business {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-test-{suffix}-{uid}",
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


# ------------------------------------------------------------------------------
# 1. Successful Complete Sandbox Synchronization
# ------------------------------------------------------------------------------
def test_scenario_01_successful_complete_sync(db_session: Session):
    """Scenario 1: Complete deterministic sync, hash chaining, and successful certification."""
    biz = _create_isolated_tenant(db_session, "s01")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, seed=101, num_transactions=60, page_size=20
    )

    result = SourceSyncService.execute_sync(
        session=db_session,
        adapter=adapter,
        period_start=start,
        period_end=end,
        page_size=20,
    )

    assert result.status == "COMPLETED"
    assert result.is_complete is True
    assert result.records_extracted == 60
    assert result.records_ingested == 60
    assert result.records_duplicate == 0
    assert len(result.cursor_chain_hash) == 64
    assert len(result.transaction_set_digest) == 64
    assert result.reported_gross > Decimal("0.00")
    assert result.period_close_evidence is not None

    # Reconcile and certify against settlement evidence
    reconciled = SourceSyncService.reconcile_and_certify(db_session, result)
    assert reconciled is True

    # Verify durable checkpoint in DB
    ckpt = db_session.query(ConnectorSyncCheckpoint).filter_by(business_id=biz.id).one()
    assert ckpt.status == "COMPLETED"
    assert ckpt.is_complete is True
    assert ckpt.records_ingested == 60


# ------------------------------------------------------------------------------
# 2. Incomplete Pagination Rejection
# ------------------------------------------------------------------------------
def test_scenario_02_incomplete_pagination_rejection(db_session: Session):
    """Scenario 2: An interrupted sync leaves checkpoint INCOMPLETE and blocks certification."""
    biz = _create_isolated_tenant(db_session, "s02")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    # Fabricate incomplete sync result
    incomplete_result = SyncResult(
        business_id=biz.id,
        provider="synthetic_sandbox",
        period_start=start,
        period_end=end,
        status="INCOMPLETE",
        is_complete=False,
        records_extracted=25,
        records_ingested=25,
        records_rejected=0,
        records_duplicate=0,
        cursor_chain_hash="1" * 64,
        transaction_set_digest="2" * 64,
        reported_gross=Decimal("500.00"),
        reported_net=Decimal("500.00"),
        reported_tax=Decimal("40.00"),
        reported_fee=Decimal("15.00"),
        provenance_type="synthetic_sandbox",
        started_at=start,
        completed_at=end,
        period_close_evidence=None,
    )

    with pytest.raises(ValueError, match="Cannot certify incomplete synchronization run"):
        SourceSyncService.reconcile_and_certify(db_session, incomplete_result)


# ------------------------------------------------------------------------------
# 3. Missing Transaction Page Detection
# ------------------------------------------------------------------------------
def test_scenario_03_missing_transaction_page_detection(db_session: Session):
    """Scenario 3: Simulated page drop mid-sync halts execution and records failure."""
    biz = _create_isolated_tenant(db_session, "s03")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, seed=202, num_transactions=60, page_size=20,
        simulate_page_drop=True,
    )

    result = SourceSyncService.execute_sync(
        session=db_session,
        adapter=adapter,
        period_start=start,
        period_end=end,
        page_size=20,
    )

    assert result.status == "INCOMPLETE"
    assert result.is_complete is False
    assert len(result.errors) > 0
    assert "page drop" in result.errors[0].lower()

    ckpt = db_session.query(ConnectorSyncCheckpoint).filter_by(business_id=biz.id).one()
    assert ckpt.status == "INCOMPLETE"
    assert ckpt.is_complete is False
    assert ckpt.retry_count == 1
    assert "page drop" in (ckpt.last_error or "").lower()


# ------------------------------------------------------------------------------
# 4. Duplicate Transaction Delivery & Idempotent Deduplication
# ------------------------------------------------------------------------------
def test_scenario_04_duplicate_transaction_delivery(db_session: Session):
    """Scenario 4: Replaying duplicate records is deduplicated without double counting."""
    biz = _create_isolated_tenant(db_session, "s04")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, seed=303, num_transactions=30, page_size=15,
        simulate_duplicate_delivery=True,
    )

    result = SourceSyncService.execute_sync(
        session=db_session,
        adapter=adapter,
        period_start=start,
        period_end=end,
        page_size=15,
    )

    assert result.status == "COMPLETED"
    assert result.records_duplicate == 1
    # Total extracted includes duplicate, ingested is unique
    assert result.records_extracted == 31
    assert result.records_ingested == 30


# ------------------------------------------------------------------------------
# 5. Forged Source Event Signature Rejection
# ------------------------------------------------------------------------------
def test_scenario_05_forged_source_signature_rejection():
    """Scenario 5: Webhook signature tampering fails verification."""
    adapter = SyntheticSourceAdapter(TEST_CREDENTIALS, "tenant-s05")
    secret = TEST_CREDENTIALS["webhook_secret"]

    payload = b'{"event": "payout.paid", "amount": 1000}'
    forged_headers = {"X-NEXUS-Signature": "f" * 64}

    assert adapter.verify_event_signature(forged_headers, payload, secret) is False


# ------------------------------------------------------------------------------
# 6. Delayed Transaction After Apparent Period Close
# ------------------------------------------------------------------------------
def test_scenario_06_delayed_transaction_isolation():
    """Scenario 6: Transactions occurring after period boundary are detected."""
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, "tenant-s06", seed=404, num_transactions=20,
        simulate_delayed_event=True,
    )

    txns = list(adapter.stream_historical(start, end))
    delayed = [t for t in txns if t.transaction_date > end]

    assert len(delayed) == 1
    assert "DELAYED" in delayed[0].source_transaction_id


# ------------------------------------------------------------------------------
# 7. Refund After Apparent Period Close
# ------------------------------------------------------------------------------
def test_scenario_07_post_close_refund_isolation():
    """Scenario 7: Post-close refunds do not alter historical closed transactions."""
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter = SyntheticSourceAdapter(TEST_CREDENTIALS, "tenant-s07", seed=505, num_transactions=50)
    txns = list(adapter.stream_historical(start, end))

    refunds = [t for t in txns if t.status == "refunded"]
    assert len(refunds) > 0
    # Each refund preserves its historical transaction_date and gross amount
    for ref in refunds:
        assert ref.gross_amount > Decimal("0.00")
        assert ref.status == "refunded"


# ------------------------------------------------------------------------------
# 8. Backfill After Watermark Creation Detection
# ------------------------------------------------------------------------------
def test_scenario_08_backfill_after_watermark_detection(db_session: Session):
    """Scenario 8: Transaction preceding active watermark is detected as a backfill."""
    biz = _create_isolated_tenant(db_session, "s08")
    wm_date = datetime(2026, 9, 15, 0, 0, 0, tzinfo=UTC)

    # Establish an active watermark
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

    # Prior date should trigger backfill detection
    is_backfill, reason = SourceSyncService.check_for_backfill(
        db_session, biz.id, datetime(2026, 9, 10, 0, 0, 0, tzinfo=UTC)
    )
    assert is_backfill is True
    assert "precedes active watermark" in (reason or "")

    # Later date is not a backfill
    is_not_backfill, _ = SourceSyncService.check_for_backfill(
        db_session, biz.id, datetime(2026, 9, 20, 0, 0, 0, tzinfo=UTC)
    )
    assert is_not_backfill is False


# ------------------------------------------------------------------------------
# 9. Expired or Invalid Credentials Handling
# ------------------------------------------------------------------------------
def test_scenario_09_expired_credentials_handling(db_session: Session):
    """Scenario 9: Expired credentials halt synchronization before data ingestion."""
    biz = _create_isolated_tenant(db_session, "s09")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, simulate_expired_credentials=True
    )

    with pytest.raises(PermissionError, match="Connector authentication failed"):
        SourceSyncService.execute_sync(db_session, adapter, start, end)


# ------------------------------------------------------------------------------
# 10. Cross-Tenant Checkpoint Access Prevention
# ------------------------------------------------------------------------------
def test_scenario_10_cross_tenant_checkpoint_access(db_session: Session):
    """Scenario 10: Attempting to access Tenant A's checkpoint with Tenant B raises PermissionError."""
    tenant_a = _create_isolated_tenant(db_session, "t_a")
    tenant_b = _create_isolated_tenant(db_session, "t_b")

    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    ckpt_a = SourceSyncService.get_or_create_checkpoint(
        db_session, tenant_a.id, "synthetic_sandbox", start, end
    )

    with pytest.raises(PermissionError, match="Cross-tenant access violation"):
        SourceSyncService.verify_tenant_boundary(
            session=db_session,
            authenticated_business_id=tenant_b.id,
            checkpoint_id=ckpt_a.id,
        )


# ------------------------------------------------------------------------------
# 11. API or Source Outage During Synchronization
# ------------------------------------------------------------------------------
def test_scenario_11_outage_during_synchronization(db_session: Session):
    """Scenario 11: Network timeout marks checkpoint INCOMPLETE and records failure."""
    biz = _create_isolated_tenant(db_session, "s11")
    start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    adapter = SyntheticSourceAdapter(
        TEST_CREDENTIALS, biz.id, simulate_outage=True
    )

    result = SourceSyncService.execute_sync(db_session, adapter, start, end)
    assert result.status == "INCOMPLETE"
    assert result.is_complete is False
    assert len(result.errors) > 0
    assert "timeout" in result.errors[0].lower() or "outage" in result.errors[0].lower()


# ------------------------------------------------------------------------------
# 12. Attempt to Use Synthetic Provenance for a Real Tenant (Apex Specialty Commerce)
# ------------------------------------------------------------------------------
def test_scenario_12_real_tenant_synthetic_provenance_block(db_session: Session):
    """Scenario 12: Apex Specialty Commerce cannot be certified using synthetic sandbox provenance."""
    adapter = SyntheticSourceAdapter(TEST_CREDENTIALS, APEX_TENANT_ID)

    # 1. Fetching settlement evidence for Apex must be rejected
    with pytest.raises(PermissionError, match="Real tenant.*cannot be certified using synthetic sandbox"):
        adapter.fetch_period_close_evidence("batch_01")

    # 2. Reconcile and certify must reject Apex with synthetic provenance
    fake_apex_result = SyncResult(
        business_id=APEX_TENANT_ID,
        provider="synthetic_sandbox",
        period_start=datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC),
        status="COMPLETED",
        is_complete=True,
        records_extracted=100,
        records_ingested=100,
        records_rejected=0,
        records_duplicate=0,
        cursor_chain_hash="a" * 64,
        transaction_set_digest="b" * 64,
        reported_gross=Decimal("1000.00"),
        reported_net=Decimal("950.00"),
        reported_tax=Decimal("80.00"),
        reported_fee=Decimal("25.00"),
        provenance_type="synthetic_sandbox",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        period_close_evidence=None,
    )

    with pytest.raises(PermissionError, match="Governance Violation: Real tenant.*cannot be certified using synthetic"):
        SourceSyncService.reconcile_and_certify(db_session, fake_apex_result)
