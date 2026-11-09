"""
NEXUS Phase 1J.2.2 — Shopify Webhook Security & Durable Inbox Tests.

Verifies:
- Scenario 04: Duplicate webhook delivery (database-backed inbox deduplication).
- Scenario 05: Invalid webhook signature (Base64 HMAC verification).
- Scenario 06: Concurrent duplicate events and safe worker claiming.
- Scenario 07: Worker restart during event processing (stale worker recovery).
- Scenario 14: Cross-tenant event isolation and access prevention.
- Cross-provider durability (Stripe and Shopify sharing the durable inbox).
"""

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import time
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session
from stripe import SignatureVerificationError

from app.connectors.shopify_adapter import ShopifyAdapter
from app.connectors.stripe_adapter import StripeAdapter
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.services.webhook_inbox_service import WebhookInboxService


def _generate_shopify_signature(payload_bytes: bytes, secret: str) -> str:
    """Helper to compute Shopify Base64-encoded HMAC-SHA256 signature."""
    raw_hmac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return base64.b64encode(raw_hmac).decode("utf-8")


def _create_isolated_tenant(session: Session, suffix: str) -> Business:
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-wh-{suffix}-{uid}", name=f"WH Org {suffix}", slug=f"wh-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-wh-{suffix}-{uid}",
        organization_id=org.id,
        name=f"WH Biz {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-wh-{suffix}-{uid}",
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
    session.flush()
    return biz


def test_scenario_05_shopify_signature_verification():
    """Scenario 5: Shopify Base64 HMAC signature verification."""
    secret = "sh_sec_testWebhookVerificationSecret123"
    adapter = ShopifyAdapter(
        {"shop_domain": "my-store.myshopify.com", "access_token": "shpat_123", "webhook_secret": secret},
        "biz_01",
    )

    body = json.dumps({"id": 123456, "total_price": "100.00"}).encode("utf-8")

    # 1. Valid signature
    valid_sig = _generate_shopify_signature(body, secret)
    headers = {"X-Shopify-Hmac-SHA256": valid_sig}
    assert adapter.verify_event_signature(headers, body) is True

    # 2. Tampered body
    tampered_body = json.dumps({"id": 123456, "total_price": "999.00"}).encode("utf-8")
    assert adapter.verify_event_signature(headers, tampered_body) is False

    # 3. Wrong secret
    wrong_sig = _generate_shopify_signature(body, "sh_sec_wrongSecret")
    assert adapter.verify_event_signature({"X-Shopify-Hmac-SHA256": wrong_sig}, body) is False

    # 4. Missing header
    assert adapter.verify_event_signature({}, body) is False


def test_scenario_04_durable_webhook_inbox_deduplication(db_session: Session):
    """Scenario 4: Durable database-backed webhook deduplication across sessions."""
    biz = _create_isolated_tenant(db_session, "s04")
    secret = "sh_sec_durable_dedup_123"
    adapter = ShopifyAdapter(
        {"shop_domain": "durable-store.myshopify.com", "access_token": "shpat_123", "webhook_secret": secret},
        biz.id,
    )

    event_id = f"evt_shop_{uuid4().hex[:10]}"
    body = json.dumps({"id": 555001, "total_price": "250.00"}).encode("utf-8")
    sig = _generate_shopify_signature(body, secret)
    headers = {
        "X-Shopify-Hmac-SHA256": sig,
        "X-Shopify-Webhook-Id": event_id,
        "X-Shopify-Topic": "orders/create",
    }

    # First delivery: processed into database inbox
    res1 = WebhookInboxService.process_inbound_webhook(db_session, adapter, headers, body, worker_id="worker_a")
    assert res1["status"] == "processed"
    assert res1["event_id"] == event_id
    db_session.commit()

    # Second delivery: suppressed via database lookup as duplicate_ignored
    res2 = WebhookInboxService.process_inbound_webhook(db_session, adapter, headers, body, worker_id="worker_b")
    assert res2["status"] == "duplicate_ignored"
    assert res2["event_id"] == event_id
    assert "already been processed" in res2["message"]


def test_scenario_06_concurrent_duplicate_events(db_session: Session):
    """Scenario 6: Concurrent event deliveries handled safely without duplicate processing."""
    biz = _create_isolated_tenant(db_session, "s06")
    event_id = f"evt_concurrent_{uuid4().hex[:8]}"
    body = b'{"id": 6001, "amount": 100}'

    # First worker records event
    item, is_new1 = WebhookInboxService.record_incoming_event(
        session=db_session,
        business_id=biz.id,
        provider="shopify",
        provider_account_id="store.myshopify.com",
        event_id=event_id,
        event_type="orders/create",
        payload_bytes=body,
        signature_verified=True,
    )
    assert is_new1 is True

    # Second concurrent worker attempts to record exact same event ID
    item_dup, is_new2 = WebhookInboxService.record_incoming_event(
        session=db_session,
        business_id=biz.id,
        provider="shopify",
        provider_account_id="store.myshopify.com",
        event_id=event_id,
        event_type="orders/create",
        payload_bytes=body,
        signature_verified=True,
    )
    assert is_new2 is False
    assert item_dup.id == item.id

    # Worker 1 claims event
    claimed1 = WebhookInboxService.claim_event_for_processing(db_session, item.id, worker_id="worker_01")
    assert claimed1 is not None
    assert claimed1.status == "CLAIMED"

    # Worker 2 attempts to claim active event -> returns None (locked)
    claimed2 = WebhookInboxService.claim_event_for_processing(db_session, item.id, worker_id="worker_02")
    assert claimed2 is None


def test_scenario_07_worker_restart_during_event_processing(db_session: Session):
    """Scenario 7: Worker crash/restart during processing is safely recovered after timeout."""
    biz = _create_isolated_tenant(db_session, "s07")
    event_id = f"evt_crash_{uuid4().hex[:8]}"
    body = b'{"id": 7001, "order": "crashed"}'

    item, _ = WebhookInboxService.record_incoming_event(
        session=db_session,
        business_id=biz.id,
        provider="shopify",
        provider_account_id="store.myshopify.com",
        event_id=event_id,
        event_type="orders/create",
        payload_bytes=body,
        signature_verified=True,
    )

    # Worker 1 claims event
    claimed = WebhookInboxService.claim_event_for_processing(db_session, item.id, worker_id="worker_crashed")
    assert claimed is not None

    # Simulate crash: 10 minutes pass without completion
    stale_time = datetime.now(UTC) - timedelta(minutes=10)
    item.claimed_at = stale_time
    db_session.commit()

    # Worker 2 restarts and re-claims stale event (timeout = 5 minutes)
    recovered = WebhookInboxService.claim_event_for_processing(
        db_session, item.id, worker_id="worker_replacement", stale_timeout_minutes=5
    )
    assert recovered is not None
    assert recovered.claimed_by == "worker_replacement"
    assert recovered.retry_count == 2

    # Worker 2 completes processing
    completed = WebhookInboxService.complete_event_processing(db_session, item.id)
    assert completed.status == "PROCESSED"
    assert completed.processed_at is not None


def test_scenario_14_cross_tenant_event_access_prevention(db_session: Session):
    """Scenario 14: Tenant B cannot access or record under Tenant A's existing event ID."""
    biz_a = _create_isolated_tenant(db_session, "wh_a")
    biz_b = _create_isolated_tenant(db_session, "wh_b")

    shared_event_id = f"evt_collision_{uuid4().hex[:8]}"
    body = b'{"msg": "data"}'

    # Tenant A records event
    WebhookInboxService.record_incoming_event(
        session=db_session,
        business_id=biz_a.id,
        provider="shopify",
        provider_account_id="store-shared.myshopify.com",
        event_id=shared_event_id,
        event_type="orders/create",
        payload_bytes=body,
        signature_verified=True,
    )
    db_session.commit()

    # Tenant B attempts to claim or re-record Tenant A's event ID -> PermissionError
    with pytest.raises(PermissionError, match="Security Violation: Webhook event"):
        WebhookInboxService.record_incoming_event(
            session=db_session,
            business_id=biz_b.id,
            provider="shopify",
            provider_account_id="store-shared.myshopify.com",
            event_id=shared_event_id,
            event_type="orders/create",
            payload_bytes=body,
            signature_verified=True,
        )


def test_cross_provider_shared_inbox(db_session: Session):
    """Verify that Stripe and Shopify share the same durable database inbox safely."""
    biz = _create_isolated_tenant(db_session, "shared_p")

    # Ingest Stripe webhook
    stripe_adapter = StripeAdapter({"api_key": "sk_test_123", "webhook_secret": "whsec_shared123"}, biz.id)
    now_ts = int(time.time())
    stripe_payload = json.dumps({"id": "evt_stripe_shared_01", "type": "charge.succeeded", "created": now_ts}).encode("utf-8")
    signed_p = f"{now_ts}.".encode("utf-8") + stripe_payload
    stripe_sig = hmac.new(b"whsec_shared123", signed_p, hashlib.sha256).hexdigest()
    stripe_hdr = {"Stripe-Signature": f"t={now_ts},v1={stripe_sig}"}

    res_stripe = stripe_adapter.process_webhook_event(stripe_hdr, stripe_payload, session=db_session)
    assert res_stripe["status"] == "processed"

    # Ingest Shopify webhook
    shopify_adapter = ShopifyAdapter(
        {"shop_domain": "shared.myshopify.com", "access_token": "shpat_123", "webhook_secret": "sh_sec_shared456"},
        biz.id,
    )
    shopify_body = json.dumps({"id": 888001, "name": "#8881"}).encode("utf-8")
    shopify_sig = _generate_shopify_signature(shopify_body, "sh_sec_shared456")
    shopify_hdr = {
        "X-Shopify-Hmac-SHA256": shopify_sig,
        "X-Shopify-Webhook-Id": "evt_shopify_shared_01",
        "X-Shopify-Topic": "orders/create",
    }

    res_shopify = shopify_adapter.process_webhook_event(shopify_hdr, shopify_body, session=db_session)
    assert res_shopify["status"] == "processed"
    db_session.commit()
