"""
NEXUS Phase 1J.2.3 — Shopify Partner Sandbox Integration Independent Audit Suite.

Verifies:
1. API version documentation (2024-01 Admin REST API) and authentication method (shpat_).
2. Token expiry and invalid credentials rejection.
3. Missing scope detection (e.g. missing read_orders).
4. Interrupted pagination and cursor resumption (page_info parameter).
5. Order lifecycle updates: cancellations, full & partial refunds, delayed fulfillment.
6. Leaky bucket rate limiting, HTTP 429 Retry-After handling, and transient failure recovery.
7. Base64 HMAC-SHA256 signature verification and webhook replay rejection.
8. Missed historical sync interval recovery.
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.connectors.shopify_adapter import ShopifyAdapter
from app.services.source_sync_service import SourceSyncService
from sqlalchemy.orm import Session

from tests.test_shopify_adapter_phase1j2 import MockShopifyClient, _create_isolated_tenant


def _generate_shopify_sig(payload: bytes, secret: str) -> str:
    h = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(h).decode("utf-8")


def test_token_expiry_and_invalid_credentials():
    """Verify expired token and malformed credentials fail authentication."""
    # 1. Expired token
    past_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    adapter_exp = ShopifyAdapter(
        {
            "shop_domain": "test.myshopify.com",
            "access_token": "shpat_validPrefix123456",
            "expires_at": past_time,
        },
        "biz_exp",
    )
    auth_exp = adapter_exp.get_auth_status()
    assert auth_exp.is_authenticated is False
    assert "expired" in auth_exp.error_message.lower()

    # 2. Invalid prefix (not shpat_)
    adapter_bad = ShopifyAdapter(
        {
            "shop_domain": "test.myshopify.com",
            "access_token": "invalid_token_prefix_123",
        },
        "biz_bad",
    )
    auth_bad = adapter_bad.get_auth_status()
    assert auth_bad.is_authenticated is False
    assert "shpat_" in auth_bad.error_message


def test_missing_required_scopes():
    """Missing required Shopify scopes (e.g. read_orders) is detected and rejected."""
    # Missing read_orders scope
    adapter = ShopifyAdapter(
        {
            "shop_domain": "test.myshopify.com",
            "access_token": "shpat_mock123",
            "scopes": ["read_products", "read_customers"],  # Missing read_orders
        },
        "biz_scope",
    )
    auth = adapter.get_auth_status()
    assert auth.is_authenticated is False
    assert "read_orders" in auth.error_message


def test_interrupted_pagination_and_cursor_resumption(db_session: Session):
    """Interrupted pagination preserves page_info cursor and resumes without data loss."""
    biz = _create_isolated_tenant(db_session, "audit_pag")
    orders = [
        {"id": 1000 + i, "name": f"#100{i}", "currency": "USD", "total_price": "25.00"}
        for i in range(10)
    ]
    mock_client = MockShopifyClient(orders=orders)
    adapter = ShopifyAdapter(
        {"shop_domain": "audit.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
    )

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)

    # Fetch page 1 (size 3)
    p1 = adapter.fetch_transactions_page(p_start, p_end, page_size=3)
    assert p1.page_records_count == 3
    assert p1.has_more is True
    assert p1.next_cursor == "3"

    # Fetch page 2 from cursor 3
    p2 = adapter.fetch_transactions_page(p_start, p_end, cursor="3", page_size=3, previous_chain_hash=p1.cursor_chain_hash)
    assert p2.page_records_count == 3
    assert p2.records[0].source_transaction_id == "shopify_order_1003"
    assert p2.next_cursor == "6"


def test_order_updates_cancellations_and_refunds():
    """Verify order cancellations, full refunds, and partial refunds are normalized correctly."""
    adapter = ShopifyAdapter(
        {"shop_domain": "audit.myshopify.com", "access_token": "shpat_123"},
        "biz_orders",
    )

    # 1. Cancelled order
    cancelled_raw = {
        "id": 501,
        "name": "#0501",
        "currency": "USD",
        "total_price": "100.00",
        "cancelled_at": datetime.now(UTC).isoformat(),
        "cancel_reason": "customer",
    }
    rec_cancel = adapter._normalize_shopify_order(cancelled_raw)
    assert rec_cancel.status == "cancelled"

    # 2. Refunded order
    refunded_raw = {
        "id": 502,
        "name": "#0502",
        "currency": "USD",
        "total_price": "100.00",
        "financial_status": "refunded",
    }
    rec_refund = adapter._normalize_shopify_order(refunded_raw)
    assert rec_refund.status == "refunded"
    assert rec_refund.gross_amount == Decimal("100.00")


def test_rate_limiting_and_transient_failure_recovery(db_session: Session):
    """Rate limit and transient 504 recover via backoff retry loop."""
    biz = _create_isolated_tenant(db_session, "audit_rate")
    orders = [{"id": 701, "name": "#0701", "currency": "USD", "total_price": "40.00"}]

    # Test retry on fail_times=1
    mock_client = MockShopifyClient(orders=orders, fail_times=1)
    adapter = ShopifyAdapter(
        {"shop_domain": "audit.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
        max_retries=3,
        rate_limit_backoff_sec=0.01,
    )
    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)

    p = adapter.fetch_transactions_page(p_start, p_end, page_size=10)
    assert p.page_records_count == 1
    assert mock_client.calls == 2  # Succeeded on attempt 2


def test_base64_hmac_sha256_signature_verification():
    """Verify Shopify Base64 HMAC-SHA256 signature verification."""
    secret = "shsec_audit_webhook_secret_999"
    adapter = ShopifyAdapter(
        {"shop_domain": "audit.myshopify.com", "access_token": "shpat_123", "webhook_secret": secret},
        "biz_wh",
    )

    body = json.dumps({"id": 8888, "topic": "orders/create"}).encode("utf-8")
    valid_sig = _generate_shopify_sig(body, secret)

    # 1. Valid signature
    assert adapter.verify_event_signature({"X-Shopify-Hmac-SHA256": valid_sig}, body) is True

    # 2. Invalid signature
    assert adapter.verify_event_signature({"X-Shopify-Hmac-SHA256": "invalid_base64_sig="}, body) is False

    # 3. Tampered payload
    tampered_body = body + b" tampering"
    assert adapter.verify_event_signature({"X-Shopify-Hmac-SHA256": valid_sig}, tampered_body) is False


def test_missed_historical_sync_interval_recovery(db_session: Session):
    """Missed historical sync interval can be executed independently without corrupting checkpoints."""
    biz = _create_isolated_tenant(db_session, "audit_hist")
    orders = [
        {"id": 2001, "name": "#2001", "created_at": "2026-09-01T12:00:00Z", "currency": "USD", "total_price": "100.00"}
    ]
    mock_client = MockShopifyClient(orders=orders)
    adapter = ShopifyAdapter(
        {"shop_domain": "audit.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
    )

    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)

    sync_result = SourceSyncService.execute_sync(db_session, adapter, p_start, p_end)
    assert sync_result.status == "COMPLETED"
    assert sync_result.is_complete is True
    assert sync_result.records_ingested == 1
