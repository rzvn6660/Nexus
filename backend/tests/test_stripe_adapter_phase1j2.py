"""
NEXUS Phase 1J.2.1 — Stripe Adapter Tests.

Verifies:
- Scenario 01: Successful connection and credentials validation.
- Scenario 02: Successful payment synchronization and record normalization.
- Scenario 03: Multiple-page cursor retrieval and deterministic chain hashing.
- Scenario 11: Rate limiting (HTTP 429) backoff retry and health classification.
- Scenario 12: API timeout and checkpoint recovery.
- Scenario 13: Cross-tenant credential access isolation.
- Scenario 14: Incomplete pagination detection and verified resumption.
- Scenario 15: Attempted synthetic / test-mode certification of real tenant (Apex) blocked.
- Live credentials guardrail: Prohibiting sk_live_ / rk_live_ in sandbox context.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
import time
from uuid import uuid4
import pytest
from sqlalchemy.orm import Session

from app.connectors.stripe_adapter import StripeAdapter
from app.core.kms import LocalDevelopmentKMSProvider
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.schemas.source_sync import ConnectionHealth, ConnectorAuthStatus
from app.services.source_sync_service import SourceSyncService


class MockStripeClient:
    """Mock Stripe API client for deterministic offline testing."""

    def __init__(
        self,
        transactions: list = None,
        payouts: dict = None,
        fail_times: int = 0,
        rate_limit_times: int = 0,
    ):
        self.transactions = transactions or []
        self.payouts = payouts or {}
        self.payout_txns = {}
        self.fail_times = fail_times
        self.rate_limit_times = rate_limit_times
        self.calls = 0

    def validate_connection(self) -> bool:
        return True

    def check_health(self) -> ConnectionHealth:
        if self.rate_limit_times > 0:
            return ConnectionHealth(
                is_healthy=False,
                latency_ms=12.5,
                quota_remaining=0,
                error_classification="RATE_LIMITED",
                message="Stripe rate limit simulated.",
            )
        return ConnectionHealth(
            is_healthy=True,
            latency_ms=15.0,
            quota_remaining=100,
            error_classification="OK",
            message="Mock client operational.",
        )

    def fetch_balance_transactions(
        self,
        period_start: datetime,
        period_end: datetime,
        cursor: str = None,
        page_size: int = 100,
    ) -> dict:
        self.calls += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("Simulated Stripe network timeout (504 Gateway Timeout)")

        if self.rate_limit_times > 0:
            self.rate_limit_times -= 1
            # Import stripe RateLimitError or simulate
            import stripe
            raise stripe.RateLimitError(
                message="Rate limit exceeded",
                http_status=429,
            )

        # Filter by created timestamp
        p_start_ts = int(period_start.timestamp())
        p_end_ts = int(period_end.timestamp())

        filtered = [
            t for t in self.transactions
            if p_start_ts <= t.get("created", 0) <= p_end_ts
        ]

        # Cursor pagination
        start_idx = 0
        if cursor:
            for idx, item in enumerate(filtered):
                if item["id"] == cursor:
                    start_idx = idx + 1
                    break

        page_items = filtered[start_idx : start_idx + page_size]
        has_more = (start_idx + page_size) < len(filtered)

        return {
            "data": page_items,
            "has_more": has_more,
        }

    def get_payout(self, payout_id: str) -> dict:
        return self.payouts.get(payout_id, {"id": payout_id, "status": "paid", "amount": 10000, "currency": "usd"})

    def get_payout_transactions(self, payout_id: str) -> list:
        return self.payout_txns.get(payout_id, self.transactions)


def _create_isolated_tenant(session: Session, suffix: str) -> Business:
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-stripe-{suffix}-{uid}", name=f"Stripe Org {suffix}", slug=f"stripe-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-stripe-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Stripe Biz {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-stripe-{suffix}-{uid}",
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


def test_scenario_01_successful_connection(db_session: Session):
    """Scenario 1: Successful connection with valid Stripe Test Mode key."""
    biz = _create_isolated_tenant(db_session, "s01")
    creds = {
        "api_key": "sk_" + "test_" + "mock_key_for_testing_12345",
        "webhook_secret": "wh" + "sec_" + "mock_test_webhook_secret_12345",
        "account_id": "acct_test_s01",
    }
    mock_client = MockStripeClient()
    adapter = StripeAdapter(creds, biz.id, stripe_client=mock_client)

    auth_status = adapter.get_auth_status()
    assert auth_status.is_authenticated is True
    assert auth_status.auth_type == "api_key_test_mode"
    assert "balance_transactions:read" in auth_status.scopes
    assert adapter.validate_connection() is True

    # Test metadata
    meta = adapter.get_metadata()
    assert meta.provider == "stripe"
    assert meta.settlement_type == "payout"
    assert meta.default_currency == "USD"

    # Test health
    health = adapter.check_health()
    assert health.is_healthy is True
    assert health.error_classification == "OK"


def test_livemode_credentials_prohibited(db_session: Session):
    """Guardrail: Livemode (production) Stripe credentials raise Security Violation."""
    biz = _create_isolated_tenant(db_session, "live")
    live_creds = {
        "api_key": "sk_" + "live_" + "dummy_test_value",
        "webhook_secret": "wh" + "sec_" + "live_dummy",
    }
    with pytest.raises(ValueError, match="Security Violation: Production Stripe credentials"):
        StripeAdapter(live_creds, biz.id)


def test_scenario_02_successful_payment_synchronization(db_session: Session):
    """Scenario 2: Successful payment synchronization and normalization."""
    biz = _create_isolated_tenant(db_session, "s02")
    base_ts = int(time.time()) - 3600

    raw_txns = [
        {
            "id": "txn_01",
            "type": "charge",
            "amount": 5000,  # $50.00
            "fee": 175,      # $1.75
            "net": 4825,     # $48.25
            "currency": "usd",
            "created": base_ts + 60,
            "status": "available",
            "source": "ch_mock_01",
            "description": "Premium Retail Purchase",
            "metadata": {"customer_id": "cus_123", "email": "customer@example.com"},
        },
        {
            "id": "txn_02",
            "type": "charge",
            "amount": 12500,  # $125.00
            "fee": 393,       # $3.93
            "net": 12107,     # $121.07
            "currency": "usd",
            "created": base_ts + 120,
            "status": "available",
            "source": "ch_mock_02",
            "description": "Express Order",
        },
    ]

    mock_client = MockStripeClient(transactions=raw_txns)
    adapter = StripeAdapter({"api_key": "sk_test_123"}, biz.id, stripe_client=mock_client)

    p_start = datetime.fromtimestamp(base_ts, tz=UTC)
    p_end = p_start + timedelta(hours=2)

    page = adapter.fetch_transactions_page(p_start, p_end, page_size=10)
    assert page.page_records_count == 2
    assert page.gross_page_sum == Decimal("175.00")
    assert page.has_more is False

    r1 = page.records[0]
    assert r1.source_transaction_id == "txn_01"
    assert r1.gross_amount == Decimal("50.00")
    assert r1.fee_amount == Decimal("1.75")
    assert r1.net_amount == Decimal("48.25")
    assert r1.status == "completed"
    assert r1.provenance_type == "stripe_test_mode"
    assert r1.customer_source_id == "cus_123"
    assert r1.customer_email == "customer@example.com"


def test_scenario_03_multiple_page_retrieval(db_session: Session):
    """Scenario 3: Multi-page cursor pagination and deterministic chain hashing."""
    biz = _create_isolated_tenant(db_session, "s03")
    base_ts = int(time.time()) - 7200

    # Create 5 distinct transactions
    raw_txns = [
        {
            "id": f"txn_{i:02d}",
            "type": "charge",
            "amount": 1000 * i,
            "fee": 30 * i,
            "net": 970 * i,
            "currency": "usd",
            "created": base_ts + (i * 100),
            "status": "available",
            "source": f"ch_{i:02d}",
        }
        for i in range(1, 6)
    ]

    mock_client = MockStripeClient(transactions=raw_txns)
    adapter = StripeAdapter({"api_key": "sk_test_123"}, biz.id, stripe_client=mock_client)

    p_start = datetime.fromtimestamp(base_ts, tz=UTC)
    p_end = p_start + timedelta(hours=4)

    # Fetch page 1 (size 2)
    p1 = adapter.fetch_transactions_page(p_start, p_end, page_size=2)
    assert p1.page_records_count == 2
    assert p1.has_more is True
    assert p1.next_cursor == "txn_02"

    # Fetch page 2 (size 2)
    p2 = adapter.fetch_transactions_page(
        p_start, p_end, cursor=p1.next_cursor, page_size=2, previous_chain_hash=p1.cursor_chain_hash
    )
    assert p2.page_records_count == 2
    assert p2.has_more is True
    assert p2.next_cursor == "txn_04"
    assert p2.cursor_chain_hash != p1.cursor_chain_hash

    # Fetch page 3 (size 2 - final page has 1 item)
    p3 = adapter.fetch_transactions_page(
        p_start, p_end, cursor=p2.next_cursor, page_size=2, previous_chain_hash=p2.cursor_chain_hash
    )
    assert p3.page_records_count == 1
    assert p3.has_more is False
    assert p3.next_cursor is None

    # Verify stream_historical retrieves all 5
    all_streamed = list(adapter.stream_historical(p_start, p_end))
    assert len(all_streamed) == 5
    assert [r.source_transaction_id for r in all_streamed] == ["txn_01", "txn_02", "txn_03", "txn_04", "txn_05"]


def test_scenario_11_rate_limiting_and_backoff(db_session: Session):
    """Scenario 11: Rate limiting (HTTP 429) backoff retry and health classification."""
    biz = _create_isolated_tenant(db_session, "s11")
    base_ts = int(time.time()) - 3600

    raw_txns = [{"id": "txn_rl_01", "type": "charge", "amount": 5000, "fee": 150, "net": 4850, "currency": "usd", "created": base_ts + 10}]

    # Mock client will fail with rate limit 2 times then succeed
    mock_client = MockStripeClient(transactions=raw_txns, rate_limit_times=2)
    adapter = StripeAdapter(
        {"api_key": "sk_test_123"},
        biz.id,
        stripe_client=mock_client,
        max_retries=3,
        rate_limit_backoff_sec=0.01,
    )

    # Health check correctly classifies rate limiting
    health = adapter.check_health()
    assert health.is_healthy is False
    assert health.error_classification == "RATE_LIMITED"

    # fetch_transactions_page backs off and succeeds on 3rd attempt
    p_start = datetime.fromtimestamp(base_ts, tz=UTC)
    p_end = p_start + timedelta(hours=1)
    page = adapter.fetch_transactions_page(p_start, p_end, page_size=10)
    assert page.page_records_count == 1


def test_scenario_12_api_timeout_and_recovery(db_session: Session):
    """Scenario 12: API timeout and recovery using durable checkpoint."""
    biz = _create_isolated_tenant(db_session, "s12")
    base_ts = int(time.time()) - 3600

    raw_txns = [
        {"id": f"txn_to_{i}", "type": "charge", "amount": 2000, "fee": 60, "net": 1940, "currency": "usd", "created": base_ts + (i * 10)}
        for i in range(1, 4)
    ]

    # Fails once with timeout
    mock_client = MockStripeClient(transactions=raw_txns, fail_times=1)
    adapter = StripeAdapter({"api_key": "sk_test_123"}, biz.id, stripe_client=mock_client)

    p_start = datetime.fromtimestamp(base_ts, tz=UTC)
    p_end = p_start + timedelta(hours=1)

    # Execute sync with SourceSyncService - should fail on first attempt and record checkpoint
    result1 = SourceSyncService.execute_sync(db_session, adapter, p_start, p_end, page_size=2)
    assert result1.status == "INCOMPLETE"
    assert result1.is_complete is False
    assert len(result1.errors) > 0
    assert "Simulated Stripe network timeout" in result1.errors[0]

    # Resume sync - now succeeds
    result2 = SourceSyncService.execute_sync(db_session, adapter, p_start, p_end, page_size=2)
    assert result2.status == "COMPLETED"
    assert result2.is_complete is True
    assert result2.records_extracted == 3


def test_scenario_13_cross_tenant_credential_access_rejection(db_session: Session):
    """Scenario 13: Cross-tenant credential access is strictly rejected."""
    biz_a = _create_isolated_tenant(db_session, "t_a")
    biz_b = _create_isolated_tenant(db_session, "t_b")

    kms = LocalDevelopmentKMSProvider()

    # Register credentials for Tenant A
    SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=biz_a.id,
        provider="stripe",
        provider_account_id="acct_stripe_tenant_a",
        credential_dict={"api_key": "sk_" + "test_" + "tenant_a_secret_key"},
        scopes=["charges:read"],
        kms_provider=kms,
    )
    db_session.commit()

    # Attempting to retrieve Tenant A's credentials under Tenant B's business_id fails
    with pytest.raises(ValueError, match="No credentials found for tenant"):
        SourceSyncService.get_decrypted_tenant_credentials(
            session=db_session,
            business_id=biz_b.id,
            provider="stripe",
            kms_provider=kms,
        )


def test_scenario_14_incomplete_pagination(db_session: Session):
    """Scenario 14: Incomplete pagination properly flags incomplete state and allows resumption."""
    biz = _create_isolated_tenant(db_session, "s14")
    base_ts = int(time.time()) - 3600

    raw_txns = [
        {"id": f"txn_inc_{i}", "type": "charge", "amount": 3000, "fee": 90, "net": 2910, "currency": "usd", "created": base_ts + (i * 20)}
        for i in range(1, 7)
    ]

    mock_client = MockStripeClient(transactions=raw_txns)
    adapter = StripeAdapter({"api_key": "sk_test_123"}, biz.id, stripe_client=mock_client)

    p_start = datetime.fromtimestamp(base_ts, tz=UTC)
    p_end = p_start + timedelta(hours=1)

    # Stop after 1 page (size 2 -> 2 records)
    res_partial = SourceSyncService.execute_sync(
        db_session, adapter, p_start, p_end, page_size=2, stop_after_pages=1
    )
    assert res_partial.status == "IN_PROGRESS"
    assert res_partial.is_complete is False
    assert res_partial.records_extracted == 2

    # Resume and run to completion
    res_full = SourceSyncService.execute_sync(
        db_session, adapter, p_start, p_end, page_size=2
    )
    assert res_full.status == "COMPLETED"
    assert res_full.is_complete is True
    assert res_full.records_extracted == 6


def test_scenario_15_attempted_synthetic_certification_of_real_tenant(db_session: Session):
    """Scenario 15: Attempted synthetic / test-mode certification of protected real tenant (Apex) fails closed."""
    apex_id = "ab044b1a-835a-4a38-bf45-62fe38624151"

    adapter = StripeAdapter({"api_key": "sk_test_123"}, apex_id)

    # 1. fetch_period_close_evidence fails closed immediately
    with pytest.raises(PermissionError, match="Governance Violation: Real tenant"):
        adapter.fetch_period_close_evidence("po_mock_123")

    # 2. SourceSyncService.reconcile_and_certify also fails closed immediately
    from app.schemas.source_sync import SyncResult
    mock_sync_result = SyncResult(
        sync_run_id=str(uuid4()),
        business_id=apex_id,
        provider="stripe",
        period_start=datetime.now(UTC) - timedelta(days=7),
        period_end=datetime.now(UTC),
        status="COMPLETED",
        is_complete=True,
        records_extracted=10,
        records_ingested=10,
        records_rejected=0,
        records_duplicate=0,
        cursor_chain_hash="0" * 64,
        transaction_set_digest="0" * 64,
        reported_gross=Decimal("500.00"),
        reported_net=Decimal("485.00"),
        reported_tax=Decimal("0.00"),
        reported_fee=Decimal("15.00"),
        provenance_type="stripe_test_mode",
        errors=[],
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    with pytest.raises(PermissionError, match="Governance Violation: Real tenant"):
        SourceSyncService.reconcile_and_certify(db_session, mock_sync_result)
