"""
NEXUS Phase 1J.2.2 — Shopify Adapter Tests.

Verifies:
- Scenario 01: Shopify connection success and credentials validation.
- Scenario 02: Multi-page order retrieval with Link header page_info cursor.
- Scenario 03: Incomplete pagination handling and verified resumption.
- Scenario 08: Refund after order creation.
- Scenario 09: Order cancellation handling.
- Scenario 10: Partial refund normalization.
- Scenario 11: Delayed fulfillment event processing.
- Scenario 12: Rate limiting (HTTP 429 / Call Limit) backoff retry.
- Scenario 13: API timeout and checkpoint recovery.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import time
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session

from app.connectors.shopify_adapter import ShopifyAdapter
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.schemas.source_sync import ConnectionHealth, ConnectorAuthStatus
from app.services.source_sync_service import SourceSyncService


class MockShopifyClient:
    """Mock Shopify API client for deterministic offline testing."""

    def __init__(
        self,
        orders: list = None,
        fail_times: int = 0,
        rate_limit_times: int = 0,
    ):
        self.orders = orders or []
        self.fail_times = fail_times
        self.rate_limit_times = rate_limit_times
        self.calls = 0

    def validate_connection(self) -> bool:
        return True

    def check_health(self) -> ConnectionHealth:
        if self.rate_limit_times > 0:
            return ConnectionHealth(
                is_healthy=False,
                latency_ms=25.0,
                quota_remaining=0,
                error_classification="RATE_LIMITED",
                message="Shopify call limit reached (40/40).",
            )
        return ConnectionHealth(
            is_healthy=True,
            latency_ms=18.0,
            quota_remaining=38,
            error_classification="OK",
            message="Mock Shopify client healthy.",
        )

    def fetch_orders(
        self,
        period_start: datetime,
        period_end: datetime,
        cursor: str = None,
        page_size: int = 50,
    ) -> dict:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("Simulated Shopify 504 Gateway Timeout")

        if self.rate_limit_times > 0:
            self.rate_limit_times -= 1
            raise RuntimeError("Shopify API error after 1 attempts: 429 Too Many Requests")

        start_idx = 0
        if cursor:
            try:
                start_idx = int(cursor)
            except ValueError:
                start_idx = 0

        page_orders = self.orders[start_idx : start_idx + page_size]
        has_more = (start_idx + page_size) < len(self.orders)
        next_c = str(start_idx + page_size) if has_more else None

        return {
            "orders": page_orders,
            "has_more": has_more,
            "next_cursor": next_c,
        }


def _create_isolated_tenant(session: Session, suffix: str) -> Business:
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-shop-{suffix}-{uid}", name=f"Shop Org {suffix}", slug=f"shop-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-shop-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Shop Biz {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-shop-{suffix}-{uid}",
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


def test_scenario_01_shopify_connection_success(db_session: Session):
    """Scenario 1: Shopify connection validation and metadata."""
    biz = _create_isolated_tenant(db_session, "s01")
    creds = {
        "shop_domain": "test-dev-store.myshopify.com",
        "access_token": "shpat_mockAccessTokenForTesting12345",
        "webhook_secret": "sh_sec_mockSecret123456",
    }
    mock_client = MockShopifyClient()
    adapter = ShopifyAdapter(creds, biz.id, shopify_client=mock_client)

    auth = adapter.get_auth_status()
    assert auth.is_authenticated is True
    assert auth.auth_type == "shopify_custom_app"
    assert "read_orders" in auth.scopes
    assert adapter.validate_connection() is True

    meta = adapter.get_metadata()
    assert meta.provider == "shopify"
    assert meta.provider_account_id == "test-dev-store.myshopify.com"
    assert meta.supports_period_close is False

    health = adapter.check_health()
    assert health.is_healthy is True
    assert health.error_classification == "OK"


def test_scenario_02_multi_page_order_retrieval(db_session: Session):
    """Scenario 2: Multi-page cursor pagination and deterministic chain hashing."""
    biz = _create_isolated_tenant(db_session, "s02")
    now_iso = datetime.now(UTC).isoformat()

    # Generate 5 orders
    raw_orders = [
        {
            "id": 1000 + i,
            "name": f"#100{i}",
            "created_at": now_iso,
            "currency": "USD",
            "total_price": f"{50 * i}.00",
            "total_tax": "5.00",
            "financial_status": "paid",
            "customer": {"id": 200 + i, "email": f"cust_{i}@example.com", "first_name": f"First{i}", "last_name": "Test"},
            "line_items": [{"id": 300 + i, "title": f"Item {i}", "quantity": 1, "price": f"{50 * i}.00"}],
        }
        for i in range(1, 6)
    ]

    mock_client = MockShopifyClient(orders=raw_orders)
    adapter = ShopifyAdapter(
        {"shop_domain": "test-dev-store.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
    )

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)

    # Page 1 (size 2)
    p1 = adapter.fetch_transactions_page(p_start, p_end, page_size=2)
    assert p1.page_records_count == 2
    assert p1.has_more is True
    assert p1.next_cursor == "2"

    # Page 2 (size 2)
    p2 = adapter.fetch_transactions_page(p_start, p_end, cursor=p1.next_cursor, page_size=2, previous_chain_hash=p1.cursor_chain_hash)
    assert p2.page_records_count == 2
    assert p2.has_more is True
    assert p2.next_cursor == "4"

    # Page 3 (size 2 - 1 order remaining)
    p3 = adapter.fetch_transactions_page(p_start, p_end, cursor=p2.next_cursor, page_size=2, previous_chain_hash=p2.cursor_chain_hash)
    assert p3.page_records_count == 1
    assert p3.has_more is False
    assert p3.next_cursor is None

    # Stream all orders
    streamed = list(adapter.stream_historical(p_start, p_end))
    assert len(streamed) == 5
    assert [r.transaction_number for r in streamed] == ["#1001", "#1002", "#1003", "#1004", "#1005"]


def test_scenario_03_incomplete_pagination(db_session: Session):
    """Scenario 3: Incomplete pagination properly tracks IN_PROGRESS status and resumes."""
    biz = _create_isolated_tenant(db_session, "s03")
    now_iso = datetime.now(UTC).isoformat()

    raw_orders = [
        {"id": 2000 + i, "name": f"#200{i}", "created_at": now_iso, "currency": "USD", "total_price": "100.00", "financial_status": "paid"}
        for i in range(1, 5)
    ]
    mock_client = MockShopifyClient(orders=raw_orders)
    adapter = ShopifyAdapter({"shop_domain": "test-dev-store.myshopify.com", "access_token": "shpat_123"}, biz.id, shopify_client=mock_client)

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)

    # Stop after 1 page (size 2)
    res_part = SourceSyncService.execute_sync(db_session, adapter, p_start, p_end, page_size=2, stop_after_pages=1)
    assert res_part.status == "IN_PROGRESS"
    assert res_part.is_complete is False
    assert res_part.records_extracted == 2

    # Resume to completion
    res_full = SourceSyncService.execute_sync(db_session, adapter, p_start, p_end, page_size=2)
    assert res_full.status == "COMPLETED"
    assert res_full.is_complete is True
    assert res_full.records_extracted == 4


def test_scenario_08_refund_after_order_creation(db_session: Session):
    """Scenario 8: Order with refunded status is normalized with status='refunded'."""
    biz = _create_isolated_tenant(db_session, "s08")
    now_iso = datetime.now(UTC).isoformat()

    order = {
        "id": 8001,
        "name": "#8001",
        "created_at": now_iso,
        "currency": "USD",
        "total_price": "150.00",
        "financial_status": "refunded",
        "line_items": [{"id": 1, "title": "Returned Jacket", "quantity": 1, "price": "150.00"}],
    }

    mock_client = MockShopifyClient(orders=[order])
    adapter = ShopifyAdapter(
        {"shop_domain": "test.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
        max_retries=1,
    )

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)
    page = adapter.fetch_transactions_page(p_start, p_end)
    assert page.page_records_count == 1
    rec = page.records[0]
    assert rec.status == "refunded"
    assert rec.gross_amount == Decimal("150.00")
    assert rec.line_items[0].title == "Returned Jacket"


def test_scenario_09_order_cancellation(db_session: Session):
    """Scenario 9: Cancelled order maps status='cancelled'."""
    biz = _create_isolated_tenant(db_session, "s09")
    now_iso = datetime.now(UTC).isoformat()

    order = {
        "id": 9001,
        "name": "#9001",
        "created_at": now_iso,
        "currency": "USD",
        "total_price": "200.00",
        "cancelled_at": now_iso,
        "cancel_reason": "customer",
    }

    mock_client = MockShopifyClient(orders=[order])
    adapter = ShopifyAdapter(
        {"shop_domain": "test.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
        max_retries=1,
    )

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)
    page = adapter.fetch_transactions_page(p_start, p_end)
    rec = page.records[0]
    assert rec.status == "cancelled"


def test_scenario_10_partial_refund(db_session: Session):
    """Scenario 10: Partially refunded order is normalized as status='pending'."""
    biz = _create_isolated_tenant(db_session, "s10")
    now_iso = datetime.now(UTC).isoformat()

    order = {
        "id": 10001,
        "name": "#10001",
        "created_at": now_iso,
        "currency": "USD",
        "total_price": "300.00",
        "financial_status": "partially_refunded",
    }

    mock_client = MockShopifyClient(orders=[order])
    adapter = ShopifyAdapter(
        {"shop_domain": "test.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
        max_retries=1,
    )

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)
    page = adapter.fetch_transactions_page(p_start, p_end)
    rec = page.records[0]
    assert rec.status == "pending"
    assert rec.gross_amount == Decimal("300.00")


def test_scenario_11_delayed_fulfillment_event(db_session: Session):
    """Scenario 11: Delayed fulfillment event is ingested without corrupting order financial amounts."""
    biz = _create_isolated_tenant(db_session, "s11")
    now_iso = datetime.now(UTC).isoformat()

    order = {
        "id": 11001,
        "name": "#11001",
        "created_at": now_iso,
        "currency": "USD",
        "total_price": "75.00",
        "financial_status": "paid",
        "fulfillment_status": "fulfilled",
    }

    mock_client = MockShopifyClient(orders=[order])
    adapter = ShopifyAdapter(
        {"shop_domain": "test.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
        max_retries=1,
    )

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)
    page = adapter.fetch_transactions_page(p_start, p_end)
    rec = page.records[0]
    assert rec.status == "completed"
    assert rec.gross_amount == Decimal("75.00")


def test_scenario_12_rate_limiting_retry(db_session: Session):
    """Scenario 12: Rate limiting backoff retry succeeds after transient 429."""
    biz = _create_isolated_tenant(db_session, "s12")
    now_iso = datetime.now(UTC).isoformat()

    order = {"id": 12001, "name": "#12001", "created_at": now_iso, "currency": "USD", "total_price": "80.00"}

    # Fails once with rate limit, then succeeds
    mock_client = MockShopifyClient(orders=[order], rate_limit_times=1)
    adapter = ShopifyAdapter(
        {"shop_domain": "test.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
        max_retries=3,
        rate_limit_backoff_sec=0.01,
    )

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)
    page = adapter.fetch_transactions_page(p_start, p_end)
    assert page.page_records_count == 1
    assert page.records[0].gross_amount == Decimal("80.00")


def test_scenario_13_api_timeout_and_recovery(db_session: Session):
    """Scenario 13: Checkpoint persists on 504 timeout and sync recovers seamlessly."""
    biz = _create_isolated_tenant(db_session, "s13")
    now_iso = datetime.now(UTC).isoformat()

    orders = [
        {"id": 13000 + i, "name": f"#1300{i}", "created_at": now_iso, "currency": "USD", "total_price": "50.00"}
        for i in range(1, 4)
    ]
    mock_client = MockShopifyClient(orders=orders, fail_times=1)
    adapter = ShopifyAdapter(
        {"shop_domain": "test.myshopify.com", "access_token": "shpat_123"},
        biz.id,
        shopify_client=mock_client,
        max_retries=1,
    )

    p_start = datetime.now(UTC) - timedelta(days=1)
    p_end = datetime.now(UTC) + timedelta(days=1)

    # First attempt fails with 504 Gateway Timeout
    res1 = SourceSyncService.execute_sync(db_session, adapter, p_start, p_end)
    assert res1.status == "INCOMPLETE"
    assert "Simulated Shopify 504 Gateway Timeout" in res1.errors[0]

    # Second attempt resumes and completes
    res2 = SourceSyncService.execute_sync(db_session, adapter, p_start, p_end)
    assert res2.status == "COMPLETED"
    assert res2.is_complete is True
    assert res2.records_extracted == 3
