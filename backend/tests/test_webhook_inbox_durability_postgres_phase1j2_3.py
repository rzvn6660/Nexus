"""
NEXUS Phase 1J.2.3 — Durable Webhook Inbox PostgreSQL-Backed Durability & Concurrency Suite.

Tests against live PostgreSQL staging database (or isolated DB session):
1. Duplicate delivery is idempotent (same event ID processed once).
2. Concurrent workers cannot claim the same event (SELECT FOR UPDATE row-level locking).
3. Deduplication survives process/session restart.
4. Crashed workers can be recovered safely after stale timeout.
5. Active worker heartbeats prevent premature lock recovery.
6. Payload changes under an existing event ID are quarantined (PAYLOAD_DIGEST_MISMATCH).
7. Cross-tenant event injection is rejected with PermissionError.
8. Processing and checkpoint updates have safe transactional boundaries (handler atomicity).
"""

import json
import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.connector import ConnectorWebhookInbox
from app.models.tenant import Business, Organization
from app.services.webhook_inbox_service import WebhookInboxService
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

STAGING_DB_URL = os.getenv(
    "STAGING_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql+psycopg://nexus_staging_user:local_dev_password@127.0.0.1:5433/nexus_staging_db"),
)


@pytest.fixture(scope="module")
def pg_session_factory():
    """Create session factory for staging PostgreSQL."""
    try:
        engine = create_engine(STAGING_DB_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
        with engine.connect() as conn:
            pass
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
        return SessionLocal
    except Exception as e:
        pytest.skip(f"PostgreSQL staging database not available: {e}")


@pytest.fixture
def disposable_tenant(pg_session_factory) -> Generator[str, None, None]:
    """Create and clean up a disposable test tenant in staging PostgreSQL."""
    session: Session = pg_session_factory()
    tenant_id = str(uuid4())
    org_id = str(uuid4())

    try:
        org = Organization(id=org_id, name=f"Audit Org {tenant_id[:8]}", slug=f"audit-org-{tenant_id[:8]}")
        session.add(org)
        session.flush()

        biz = Business(
            id=tenant_id,
            organization_id=org_id,
            name=f"Audit Tenant {tenant_id[:8]}",
            industry="Apparel & Footwear",
        )
        session.add(biz)
        session.commit()
        yield tenant_id
    finally:
        # Cleanup
        try:
            cleanup_s = pg_session_factory()
            cleanup_s.query(ConnectorWebhookInbox).filter_by(business_id=tenant_id).delete()
            cleanup_s.query(Business).filter_by(id=tenant_id).delete()
            cleanup_s.query(Organization).filter_by(id=org_id).delete()
            cleanup_s.commit()
            cleanup_s.close()
        except Exception:
            pass
        session.close()


def test_postgres_duplicate_delivery_idempotent(pg_session_factory, disposable_tenant: str):
    """Test 1: Duplicate webhook event delivery is idempotent."""
    session = pg_session_factory()
    try:
        payload = json.dumps({"id": "evt_test_01", "type": "charge.succeeded"}).encode("utf-8")

        # Delivery 1
        item1, is_new1 = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="stripe",
            provider_account_id="acct_audit_01",
            event_id="evt_audit_dup_01",
            event_type="charge.succeeded",
            payload_bytes=payload,
            signature_verified=True,
        )
        session.commit()
        assert is_new1 is True
        assert item1.status == "PENDING"

        # Claim and complete
        claimed = WebhookInboxService.claim_event_for_processing(session, item1.id, worker_id="worker_1")
        assert claimed is not None
        session.commit()

        completed = WebhookInboxService.complete_event_processing(session, item1.id)
        session.commit()
        assert completed.status == "PROCESSED"

        # Delivery 2 (Duplicate)
        item2, is_new2 = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="stripe",
            provider_account_id="acct_audit_01",
            event_id="evt_audit_dup_01",
            event_type="charge.succeeded",
            payload_bytes=payload,
            signature_verified=True,
        )
        session.commit()
        assert is_new2 is False
        assert item2.id == item1.id
        assert item2.status == "PROCESSED"
    finally:
        session.close()


def test_postgres_concurrent_worker_lock_contention(pg_session_factory, disposable_tenant: str):
    """Test 2: Multiple concurrent workers cannot claim the same event."""
    session = pg_session_factory()
    try:
        payload = json.dumps({"id": "evt_conc_01", "type": "orders/create"}).encode("utf-8")
        item, is_new = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="shopify",
            provider_account_id="shop_conc.myshopify.com",
            event_id="evt_conc_order_01",
            event_type="orders/create",
            payload_bytes=payload,
            signature_verified=True,
        )
        session.commit()
        inbox_id = item.id

        claimed_workers = []

        def worker_attempt(worker_id: str):
            w_session = pg_session_factory()
            try:
                res = WebhookInboxService.claim_event_for_processing(w_session, inbox_id, worker_id=worker_id)
                if res is not None:
                    claimed_workers.append(worker_id)
                    w_session.commit()
                else:
                    w_session.rollback()
            except Exception:
                w_session.rollback()
            finally:
                w_session.close()

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(worker_attempt, f"worker_{i}") for i in range(5)]
            for f in futures:
                f.result()

        # Exactly 1 worker must have acquired the claim lock
        assert len(claimed_workers) == 1, f"Expected exactly 1 claim, got: {claimed_workers}"
    finally:
        session.close()


def test_postgres_deduplication_survives_process_restart(pg_session_factory, disposable_tenant: str):
    """Test 3: Webhook deduplication persists across completely independent database sessions."""
    # Worker process 1 records and processes
    session1 = pg_session_factory()
    payload = json.dumps({"id": "evt_restart_01", "type": "payment_intent.succeeded"}).encode("utf-8")
    item1, is_new1 = WebhookInboxService.record_incoming_event(
        session=session1,
        business_id=disposable_tenant,
        provider="stripe",
        provider_account_id="acct_audit_restart",
        event_id="evt_restart_100",
        event_type="payment_intent.succeeded",
        payload_bytes=payload,
        signature_verified=True,
    )
    session1.commit()
    claimed = WebhookInboxService.claim_event_for_processing(session1, item1.id, worker_id="worker_alpha")
    session1.commit()
    WebhookInboxService.complete_event_processing(session1, item1.id)
    session1.commit()
    session1.close()

    # Worker process 2 restarts, fresh session, tries to claim
    session2 = pg_session_factory()
    try:
        item2, is_new2 = WebhookInboxService.record_incoming_event(
            session=session2,
            business_id=disposable_tenant,
            provider="stripe",
            provider_account_id="acct_audit_restart",
            event_id="evt_restart_100",
            event_type="payment_intent.succeeded",
            payload_bytes=payload,
            signature_verified=True,
        )
        assert is_new2 is False
        assert item2.status == "PROCESSED"

        # Cannot be re-claimed
        reclaim = WebhookInboxService.claim_event_for_processing(session2, item2.id, worker_id="worker_beta")
        assert reclaim is None
    finally:
        session2.close()


def test_postgres_crashed_worker_safe_recovery(pg_session_factory, disposable_tenant: str):
    """Test 4: Crashed worker lock is recovered after stale timeout."""
    session = pg_session_factory()
    try:
        payload = json.dumps({"id": "evt_crash_01", "type": "charge.succeeded"}).encode("utf-8")
        item, is_new = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="stripe",
            provider_account_id="acct_audit_crash",
            event_id="evt_crash_200",
            event_type="charge.succeeded",
            payload_bytes=payload,
            signature_verified=True,
        )
        session.commit()

        # Worker 1 claims event, but "crashes" 10 minutes ago
        claimed = WebhookInboxService.claim_event_for_processing(session, item.id, worker_id="crashed_worker_01")
        session.commit()
        assert claimed is not None

        # Simulate crashed worker with old claimed_at
        past_time = datetime.now(UTC) - timedelta(minutes=10)
        session.execute(
            select(ConnectorWebhookInbox).where(ConnectorWebhookInbox.id == item.id)
        ).scalar_one().claimed_at = past_time
        session.commit()

        # Worker 2 recovers stale event with stale_timeout_minutes=5
        recovered = WebhookInboxService.claim_event_for_processing(
            session, item.id, worker_id="recovery_worker_02", stale_timeout_minutes=5
        )
        session.commit()
        assert recovered is not None
        assert recovered.claimed_by == "recovery_worker_02"
        assert recovered.retry_count == 2
    finally:
        session.close()


def test_postgres_active_heartbeat_prevents_premature_recovery(pg_session_factory, disposable_tenant: str):
    """Test 5: Active worker heartbeats renew lock freshness and prevent premature theft."""
    session = pg_session_factory()
    try:
        payload = json.dumps({"id": "evt_hb_01", "type": "orders/updated"}).encode("utf-8")
        item, is_new = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="shopify",
            provider_account_id="shop_hb.myshopify.com",
            event_id="evt_hb_300",
            event_type="orders/updated",
            payload_bytes=payload,
            signature_verified=True,
        )
        session.commit()

        # Worker 1 claims event
        claimed = WebhookInboxService.claim_event_for_processing(session, item.id, worker_id="active_worker_hb")
        session.commit()

        # Initial claim was 10 minutes ago, but worker sends heartbeat 1 minute ago!
        past_claimed = datetime.now(UTC) - timedelta(minutes=10)
        db_item = session.execute(
            select(ConnectorWebhookInbox).where(ConnectorWebhookInbox.id == item.id)
        ).scalar_one()
        db_item.claimed_at = past_claimed
        session.commit()

        # Worker sends heartbeat
        WebhookInboxService.record_heartbeat(session, item.id, worker_id="active_worker_hb")
        session.commit()

        # Worker 2 attempts to steal the lock with timeout 5 minutes -> MUST FAIL because heartbeat is fresh!
        theft_attempt = WebhookInboxService.claim_event_for_processing(
            session, item.id, worker_id="thief_worker_hb", stale_timeout_minutes=5
        )
        assert theft_attempt is None, "Theft attempt succeeded despite fresh worker heartbeat!"
    finally:
        session.close()


def test_postgres_payload_digest_mismatch_quarantine(pg_session_factory, disposable_tenant: str):
    """Test 6: Payload modification under existing event ID triggers QUARANTINED state."""
    session = pg_session_factory()
    try:
        orig_payload = json.dumps({"id": "evt_tamper_01", "amount": 1000}).encode("utf-8")
        item, is_new = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="stripe",
            provider_account_id="acct_audit_tamper",
            event_id="evt_tamper_400",
            event_type="charge.succeeded",
            payload_bytes=orig_payload,
            signature_verified=True,
        )
        session.commit()
        assert is_new is True
        assert item.status == "PENDING"

        # Tampered payload arrives with same provider and event_id
        tampered_payload = json.dumps({"id": "evt_tamper_01", "amount": 999999}).encode("utf-8")
        item2, is_new2 = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="stripe",
            provider_account_id="acct_audit_tamper",
            event_id="evt_tamper_400",
            event_type="charge.succeeded",
            payload_bytes=tampered_payload,
            signature_verified=True,
        )
        session.commit()
        assert is_new2 is False
        assert item2.status == "QUARANTINED"
        assert "QUARANTINED" in item2.last_error
        assert item2.metadata_json.get("quarantine_reason") == "PAYLOAD_DIGEST_MISMATCH"

        # Quarantined event cannot be claimed by workers
        claimed = WebhookInboxService.claim_event_for_processing(session, item2.id, worker_id="worker_tamper")
        assert claimed is None
    finally:
        session.close()


def test_postgres_cross_tenant_event_access_rejected(pg_session_factory, disposable_tenant: str):
    """Test 7: Attempting to access or record an event belonging to another tenant raises PermissionError."""
    session = pg_session_factory()
    tenant_b = str(uuid4())
    org_b = str(uuid4())
    try:
        org = Organization(id=org_b, name="Tenant B Org", slug=f"tenant-b-org-{org_b[:8]}")
        session.add(org)
        biz_b = Business(id=tenant_b, organization_id=org_b, name="Tenant B")
        session.add(biz_b)
        session.commit()

        # Tenant A records event
        payload = json.dumps({"id": "evt_iso_01"}).encode("utf-8")
        item_a, _ = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="stripe",
            provider_account_id="acct_shared",
            event_id="evt_iso_500",
            event_type="charge.succeeded",
            payload_bytes=payload,
            signature_verified=True,
        )
        session.commit()

        # Tenant B tries to claim or record under same event_id
        with pytest.raises(PermissionError, match="Security Violation: Webhook event"):
            WebhookInboxService.record_incoming_event(
                session=session,
                business_id=tenant_b,
                provider="stripe",
                provider_account_id="acct_shared",
                event_id="evt_iso_500",
                event_type="charge.succeeded",
                payload_bytes=payload,
                signature_verified=True,
            )
    finally:
        try:
            session.query(ConnectorWebhookInbox).filter_by(business_id=tenant_b).delete()
            session.query(Business).filter_by(id=tenant_b).delete()
            session.query(Organization).filter_by(id=org_b).delete()
            session.commit()
        except Exception:
            pass
        session.close()


def test_postgres_transactional_boundaries_handler_rollback(pg_session_factory, disposable_tenant: str):
    """Test 8: If a webhook processing handler fails, state transitions to FAILED without corrupting inbox."""
    session = pg_session_factory()
    try:
        payload = json.dumps({"id": "evt_tx_01", "type": "charge.failed"}).encode("utf-8")
        item, _ = WebhookInboxService.record_incoming_event(
            session=session,
            business_id=disposable_tenant,
            provider="stripe",
            provider_account_id="acct_audit_tx",
            event_id="evt_tx_600",
            event_type="charge.failed",
            payload_bytes=payload,
            signature_verified=True,
        )
        session.commit()

        claimed = WebhookInboxService.claim_event_for_processing(session, item.id, worker_id="worker_fail")
        session.commit()

        # Simulate handler failure
        try:
            raise RuntimeError("Database deadlock during order update")
        except Exception as exc:
            WebhookInboxService.fail_event_processing(session, item.id, error_message=str(exc))
            session.commit()

        # Refresh
        failed_item = session.execute(
            select(ConnectorWebhookInbox).where(ConnectorWebhookInbox.id == item.id)
        ).scalar_one()
        assert failed_item.status == "FAILED"
        assert "deadlock" in failed_item.last_error

        # Failed event can be re-claimed for retry
        retried = WebhookInboxService.claim_event_for_processing(session, item.id, worker_id="worker_retry")
        session.commit()
        assert retried is not None
        assert retried.status == "CLAIMED"
        assert retried.retry_count == 2
    finally:
        session.close()
