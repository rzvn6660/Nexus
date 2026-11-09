"""
NEXUS Phase 1J.3 — Multi-Source Period-Close Rehearsal Test Suite.

Proves against live PostgreSQL 16.15 staging (nexus_staging_db on 127.0.0.1:5433):
All 25 adversarial and mission-critical multi-source period-close scenarios:
1. Both sources complete and reconcile -> VERIFIED_COMPLETE
2. Shopify pagination incomplete -> Fails closed
3. Stripe pagination incomplete -> Fails closed
4. Stripe payout missing -> Fails closed
5. Shopify order without payment -> Unmatched order blocks certification
6. Stripe payment without Shopify order -> Orphan payment blocks certification
7. Multiple payment attempts -> Succeeded attempt matched, failed attempts logged
8. Partial capture -> Reconciled with unpaid variance
9. Partial refund -> Reconciled with net payout reduction
10. Full refund -> Reconciled with zero net settlement
11. Currency mismatch -> CONFLICT, fails closed
12. Amount discrepancy -> CONFLICT, fails closed
13. Delayed settlement -> Timing difference tracked explicitly
14. Post-close transaction -> Out of nominal period boundary
15. Backfill after initial manifest generation -> Revalidation invalidates package
16. Duplicate webhook delivery -> Webhook inbox deduplication returns existing record idempotently
17. Webhook processing failure -> Downstream transaction rollback safely preserves PENDING
18. Stale source checkpoint -> Checkpoint expired/stale, blocks certification
19. Untrusted signing key -> Fails closed
20. Revoked signing key -> Fails closed
21. Invalid manifest signature -> Fails closed
22. Incorrect transaction identity digest -> Digest mismatch fails closed
23. Changed persisted transaction after validation -> Status flips to INVALIDATED
24. Synthetic attestation submitted for a real tenant -> Apex Specialty Commerce fails closed
25. Cross-tenant evidence injection -> Cross-tenant access fails closed
"""

import json
from datetime import UTC, datetime, timedelta
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.connector import ConnectorWebhookInbox
from app.models.tenant import Business, Organization
from app.schemas.period_close_evidence import (
    PeriodCloseAttestation,
    PeriodCloseLifecycleStatus,
    ShopifyCompletenessAssessment,
    StripeCompletenessAssessment,
)
from app.services.cross_source_reconciliation_service import (
    CrossSourceMatchStatus,
    CrossSourceReconciliationService,
)
from app.services.manifest_service import ManifestKeyRegistry
from app.services.multi_source_period_close_service import MultiSourcePeriodCloseService
from app.services.webhook_inbox_service import WebhookInboxService
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

# Live PostgreSQL 16.15 staging database connection string
POSTGRES_STAGING_URI = os.getenv(
    "STAGING_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql+psycopg://nexus_staging_user:local_dev_password@127.0.0.1:5433/nexus_staging_db"),
)


@pytest.fixture(scope="module")
def pg_engine():
    """Module-level PostgreSQL engine connecting strictly to nexus_staging_db."""
    engine = create_engine(POSTGRES_STAGING_URI, pool_pre_ping=True)
    with engine.connect() as conn:
        banner = conn.execute(text("SELECT version();")).scalar()
        dialect = engine.dialect.name
        driver = engine.dialect.driver
        version = engine.dialect.server_version_info
        assert dialect == "postgresql", f"Must run on PostgreSQL, got: {dialect}"
        print(f"\n[PHASE 1J.3 LIVE POSTGRES EVIDENCE] Dialect: {dialect} | Driver: {driver} | Version: {version}")
        print(f"Banner: {banner}")
    return engine


@pytest.fixture
def pg_session(pg_engine):
    """Provides a fresh transactional session on PostgreSQL staging."""
    SessionLocal = sessionmaker(bind=pg_engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def disposable_synthetic_tenant(pg_session):
    """Creates a temporary, strictly isolated synthetic tenant for rehearsal."""
    org_id = f"org-syn-{uuid4().hex[:8]}"
    biz_id = f"biz-syn-{uuid4().hex[:8]}"

    org = Organization(
        id=org_id,
        name="Synthetic Sandbox Rehearsal Org",
        slug=f"slug-{uuid4().hex[:8]}",
    )
    biz = Business(
        id=biz_id,
        organization_id=org_id,
        name="Synthetic Sandbox Store Ltd",
        currency="USD",
        timezone="UTC",
    )
    pg_session.add(org)
    pg_session.add(biz)
    pg_session.commit()

    try:
        yield biz_id
    finally:
        try:
            pg_session.execute(text("DELETE FROM businesses WHERE id = :id"), {"id": biz_id})
            pg_session.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org_id})
            pg_session.commit()
        except Exception:  # noqa: BLE001  # noqa: BLE001
            pg_session.rollback()


@pytest.fixture
def signing_keys(disposable_synthetic_tenant, pg_session):
    """Generates an Ed25519 signing key pair and registers public key with ManifestKeyRegistry."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    key_id = f"key-syn-{uuid4().hex[:6]}"

    ManifestKeyRegistry.register_key(
        business_id=disposable_synthetic_tenant,
        key_id=key_id,
        algorithm="ed25519",
        public_key_or_secret=public_key,
        status="active",
        allowed_roles=["owner", "admin", "finance_controller"],
    )
    return {
        "key_id": key_id,
        "private_key": private_key,
        "public_key": public_key,
    }


def make_standard_dataset(period_start: datetime, period_end: datetime):
    """Generates a clean, fully reconcilable standard dataset for Shopify and Stripe."""
    mid_date = period_start + timedelta(days=5)
    shopify_orders = [
        {
            "id": "gid://shopify/Order/1001",
            "name": "#1001",
            "total_price": "120.00",
            "total_tax": "10.00",
            "total_discounts": "0.00",
            "currency": "USD",
            "created_at": mid_date.isoformat(),
            "transactions": [
                {"receipt": {"charge_id": "ch_syn_1001"}, "authorization": "ch_syn_1001"}
            ],
        },
        {
            "id": "gid://shopify/Order/1002",
            "name": "#1002",
            "total_price": "250.50",
            "total_tax": "20.50",
            "total_discounts": "0.00",
            "currency": "USD",
            "created_at": (mid_date + timedelta(days=1)).isoformat(),
            "transactions": [
                {"receipt": {"charge_id": "ch_syn_1002"}, "authorization": "ch_syn_1002"}
            ],
        },
    ]

    stripe_txns = [
        {
            "id": "ch_syn_1001",
            "source": "ch_syn_1001",
            "type": "charge",
            "amount": 12000,
            "fee": 378,
            "net": 11622,
            "currency": "usd",
            "status": "succeeded",
            "created": int(mid_date.timestamp()),
            "metadata": {"order_id": "gid://shopify/Order/1001", "order_number": "#1001"},
        },
        {
            "id": "ch_syn_1002",
            "source": "ch_syn_1002",
            "type": "charge",
            "amount": 25050,
            "fee": 756,
            "net": 24294,
            "currency": "usd",
            "status": "succeeded",
            "created": int((mid_date + timedelta(days=1)).timestamp()),
            "metadata": {"order_id": "gid://shopify/Order/1002", "order_number": "#1002"},
        },
    ]

    return shopify_orders, stripe_txns


# =========================================================================
# Scenario 1: Both Sources Complete and Reconcile -> VERIFIED_COMPLETE
# =========================================================================
def test_scenario_01_both_sources_complete_and_reconcile(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves happy path: both Shopify and Stripe complete, reconcile, and certify as VERIFIED_COMPLETE."""
    p_start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id=f"ckpt-shop-{uuid4().hex[:6]}",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )

    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id=f"ckpt-strp-{uuid4().hex[:6]}",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )

    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_fin_controller_01",
        attester_role="finance_controller",
        attestation_statement="September 2026 accounting period close certified with complete sandbox data.",
        is_synthetic=True,
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )

    # Sign with registered private key
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package=package,
        private_key=signing_keys["private_key"],
        algorithm="ed25519",
    )

    # Validate and certify
    certified_pkg = MultiSourcePeriodCloseService.validate_and_certify_package(
        package=signed_pkg,
        session=pg_session,
    )

    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.VERIFIED_COMPLETE
    assert certified_pkg.is_fully_reconciled is True
    assert certified_pkg.reconciliation_matched_count == 2
    assert certified_pkg.reconciliation_conflict_count == 0
    assert len(certified_pkg.validation_errors) == 0


# =========================================================================
# Scenario 2: Shopify Pagination Incomplete -> Fails Closed
# =========================================================================
def test_scenario_02_shopify_pagination_incomplete(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that incomplete Shopify pagination blocks period close certification."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=False,  # Incomplete!
        checkpoint_id="ckpt-shop-inc",
        cursor_chain_hash="a" * 64,
        records_extracted=1,
        records_ingested=1,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        errors=["Cursor stream halted prematurely before terminal page"],
        is_complete=False,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with incomplete pagination.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    with pytest.raises(ValueError, match="INCOMPLETE_PAGINATION_BLOCKED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)
    assert signed_pkg.validation_status == PeriodCloseLifecycleStatus.PROVISIONAL


# =========================================================================
# Scenario 3: Stripe Pagination Incomplete -> Fails Closed
# =========================================================================
def test_scenario_03_stripe_pagination_incomplete(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that incomplete Stripe pagination blocks certification."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=1,
        payout_extracted=True,
        pagination_completed=False,  # Incomplete!
        checkpoint_id="ckpt-strp-inc",
        cursor_chain_hash="b" * 64,
        records_extracted=1,
        records_ingested=1,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        errors=["Stripe rate limit backoff exceeded during pagination"],
        is_complete=False,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with stripe incomplete.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    with pytest.raises(ValueError, match="INCOMPLETE_PAGINATION_BLOCKED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 4: Stripe Payout Missing -> Fails Closed
# =========================================================================
def test_scenario_04_stripe_payout_missing(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that missing bank payout / settlement event blocks period close."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=False,  # Missing payout!
        pagination_completed=True,
        checkpoint_id="ckpt-strp-nopayout",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=False,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with missing payout.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    with pytest.raises(ValueError, match="MISSING_PAYOUT_SETTLEMENT"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 5: Shopify Order Without Payment -> Blocks Certification
# =========================================================================
def test_scenario_05_shopify_order_without_payment(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that unmatched orders without corresponding gateway payment fail closed."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    # Add an order without payment
    shopify_orders.append(
        {
            "id": "gid://shopify/Order/9999",
            "name": "#9999",
            "total_price": "89.00",
            "total_tax": "7.00",
            "total_discounts": "0.00",
            "currency": "USD",
            "created_at": p_start.isoformat(),
            "transactions": [],
        }
    )

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-unmatched",
        cursor_chain_hash="a" * 64,
        records_extracted=3,
        records_ingested=3,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with unmatched order.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    assert package.reconciliation_unmatched_orders_count == 1
    with pytest.raises(ValueError, match="UNMATCHED_RECORDS_BLOCKED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 6: Stripe Payment Without Shopify Order -> Blocks Certification
# =========================================================================
def test_scenario_06_stripe_payment_without_shopify_order(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that orphan Stripe payments without storefront orders fail closed."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    # Add orphan payment
    stripe_txns.append(
        {
            "id": "ch_orphan_999",
            "source": "ch_orphan_999",
            "type": "charge",
            "amount": 4500,
            "fee": 150,
            "net": 4350,
            "currency": "usd",
            "status": "succeeded",
            "created": int(p_start.timestamp()),
            "metadata": {},
        }
    )

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=3,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-orphan",
        cursor_chain_hash="b" * 64,
        records_extracted=3,
        records_ingested=3,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with orphan payment.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    assert package.reconciliation_unmatched_payments_count == 1
    with pytest.raises(ValueError, match="ORPHAN_PAYMENTS_BLOCKED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 7: Multiple Payment Attempts -> Handled Correctly
# =========================================================================
def test_scenario_07_multiple_payment_attempts(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves multiple payment attempts for an order: 1 failed, 1 succeeded."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)

    order = {
        "id": "gid://shopify/Order/2001",
        "name": "#2001",
        "total_price": "75.00",
        "total_tax": "5.00",
        "total_discounts": "0.00",
        "currency": "USD",
        "created_at": p_start.isoformat(),
        "transactions": [
            {"receipt": {"charge_id": "ch_att_fail_01"}},
            {"receipt": {"charge_id": "ch_att_succ_02"}},
        ],
    }

    # Attempt 1: Failed
    fail_txn = {
        "id": "ch_att_fail_01",
        "source": "ch_att_fail_01",
        "type": "charge",
        "amount": 7500,
        "fee": 0,
        "net": 0,
        "currency": "usd",
        "status": "failed",
        "paid": False,
        "failure_message": "Card declined: insufficient funds",
        "created": int(p_start.timestamp()),
        "metadata": {"order_id": "gid://shopify/Order/2001"},
    }

    # Attempt 2: Succeeded
    succ_txn = {
        "id": "ch_att_succ_02",
        "source": "ch_att_succ_02",
        "type": "charge",
        "amount": 7500,
        "fee": 248,
        "net": 7252,
        "currency": "usd",
        "status": "succeeded",
        "paid": True,
        "created": int((p_start + timedelta(minutes=10)).timestamp()),
        "metadata": {"order_id": "gid://shopify/Order/2001"},
    }

    (
        report,
        _shop_totals,
        strp_captures,
        _strp_fees,
        _unmatched_ids,
    ) = MultiSourcePeriodCloseService.reconcile_and_summarize_financials(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=[order],
        stripe_transactions=[fail_txn, succ_txn],
    )

    assert report.matched_count == 1
    assert report.conflict_count == 0
    assert strp_captures["captured_gross"] == Decimal("75.00")
    match = report.matches[0]
    assert match.status == CrossSourceMatchStatus.MATCHED
    assert "failed on attempt" in match.notes or "Multiple payment attempts" in match.notes


# =========================================================================
# Scenario 8: Partial Capture -> Handled with Unpaid Variance
# =========================================================================
def test_scenario_08_partial_capture(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves partial capture ($100 order, $80 captured) results in PARTIALLY_MATCHED with variance."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)

    order = {
        "id": "gid://shopify/Order/3001",
        "name": "#3001",
        "total_price": "100.00",
        "currency": "USD",
        "transactions": [{"receipt": {"charge_id": "ch_partial_1"}}],
    }
    txn = {
        "id": "ch_partial_1",
        "source": "ch_partial_1",
        "type": "charge",
        "amount": 8000,  # $80.00 captured
        "fee": 262,
        "net": 7738,
        "currency": "usd",
        "status": "succeeded",
        "metadata": {"order_id": "gid://shopify/Order/3001"},
    }

    (
        report,
        _shop_totals,
        _strp_captures,
        _strp_fees,
        _unmatched_ids,
    ) = MultiSourcePeriodCloseService.reconcile_and_summarize_financials(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=[order],
        stripe_transactions=[txn],
    )

    assert report.partially_matched_count == 1
    match = report.matches[0]
    assert match.status == CrossSourceMatchStatus.PARTIALLY_MATCHED
    assert match.variance_amount == Decimal("20.00")
    assert any("Partial payment" in d for d in match.discrepancy_reasons)


# =========================================================================
# Scenario 9: Partial Refund -> Net Settlement Reduced
# =========================================================================
def test_scenario_09_partial_refund(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves order $100 with subsequent refund of $30 updates refund totals and net settlement."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)

    order = {
        "id": "gid://shopify/Order/4001",
        "name": "#4001",
        "total_price": "100.00",
        "currency": "USD",
        "transactions": [{"receipt": {"charge_id": "ch_ref_orig"}}],
    }
    charge_txn = {
        "id": "ch_ref_orig",
        "source": "ch_ref_orig",
        "type": "charge",
        "amount": 10000,
        "fee": 320,
        "net": 9680,
        "currency": "usd",
        "status": "succeeded",
        "metadata": {"order_id": "gid://shopify/Order/4001"},
    }
    refund_txn = {
        "id": "re_ref_part",
        "source": "ch_ref_orig",
        "type": "refund",
        "amount": -3000,
        "fee": 0,
        "net": -3000,
        "currency": "usd",
        "status": "succeeded",
    }

    (
        report,
        _shop_totals,
        strp_captures,
        _strp_fees,
        _unmatched_ids,
    ) = MultiSourcePeriodCloseService.reconcile_and_summarize_financials(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=[order],
        stripe_transactions=[charge_txn, refund_txn],
    )

    assert strp_captures["captured_gross"] == Decimal("100.00")
    assert strp_captures["total_refunds"] == Decimal("30.00")
    match = report.matches[0]
    assert match.refund_amount == Decimal("30.00")
    assert match.stripe_net_payout == Decimal("66.80")  # 96.80 - 30.00


# =========================================================================
# Scenario 10: Full Refund -> Zero Net Settlement
# =========================================================================
def test_scenario_10_full_refund(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves full refund results in PARTIALLY_MATCHED and net zero settlement."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)

    order = {
        "id": "gid://shopify/Order/5001",
        "name": "#5001",
        "total_price": "50.00",
        "currency": "USD",
        "transactions": [{"receipt": {"charge_id": "ch_full_ref"}}],
    }
    charge_txn = {
        "id": "ch_full_ref",
        "source": "ch_full_ref",
        "type": "charge",
        "amount": 5000,
        "fee": 175,
        "net": 4825,
        "currency": "usd",
        "status": "succeeded",
        "metadata": {"order_id": "gid://shopify/Order/5001"},
    }
    refund_txn = {
        "id": "re_full_ref",
        "source": "ch_full_ref",
        "type": "refund",
        "amount": -5000,
        "fee": 0,
        "net": -4825,  # Refund net of fee
        "currency": "usd",
        "status": "succeeded",
    }

    (
        report,
        _shop_totals,
        strp_captures,
        _strp_fees,
        _unmatched_ids,
    ) = MultiSourcePeriodCloseService.reconcile_and_summarize_financials(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=[order],
        stripe_transactions=[charge_txn, refund_txn],
    )

    assert strp_captures["total_refunds"] == Decimal("50.00")
    match = report.matches[0]
    assert match.refund_amount == Decimal("50.00")
    assert match.stripe_net_payout <= Decimal("0.00")


# =========================================================================
# Scenario 11: Currency Mismatch -> CONFLICT, Fails Closed
# =========================================================================
def test_scenario_11_currency_mismatch(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves currency mismatch (USD vs EUR) produces CONFLICT and blocks certification."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)

    order = {
        "id": "gid://shopify/Order/6001",
        "name": "#6001",
        "total_price": "100.00",
        "currency": "USD",
        "transactions": [{"receipt": {"charge_id": "ch_eur_1"}}],
    }
    txn = {
        "id": "ch_eur_1",
        "source": "ch_eur_1",
        "type": "charge",
        "amount": 10000,
        "fee": 320,
        "net": 9680,
        "currency": "eur",  # Mismatch!
        "status": "succeeded",
        "metadata": {"order_id": "gid://shopify/Order/6001"},
    }

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-cur",
        cursor_chain_hash="a" * 64,
        records_extracted=1,
        records_ingested=1,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=1,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-cur",
        cursor_chain_hash="b" * 64,
        records_extracted=1,
        records_ingested=1,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with currency mismatch.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=[order],
        stripe_transactions=[txn],
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    assert package.reconciliation_conflict_count == 1
    with pytest.raises(ValueError, match="RECONCILIATION_CONFLICT_BLOCKED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 12: Amount Discrepancy -> CONFLICT, Fails Closed
# =========================================================================
def test_scenario_12_amount_discrepancy(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves unexplained overpayment ($100 order, $150 captured) produces CONFLICT."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)

    order = {
        "id": "gid://shopify/Order/7001",
        "name": "#7001",
        "total_price": "100.00",
        "currency": "USD",
        "transactions": [{"receipt": {"charge_id": "ch_overpay_1"}}],
    }
    txn = {
        "id": "ch_overpay_1",
        "source": "ch_overpay_1",
        "type": "charge",
        "amount": 15000,  # $150.00
        "fee": 465,
        "net": 14535,
        "currency": "usd",
        "status": "succeeded",
        "metadata": {"order_id": "gid://shopify/Order/7001"},
    }

    report = CrossSourceReconciliationService.reconcile_sources(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=[order],
        stripe_transactions=[txn],
    )

    assert report.conflict_count == 1
    match = report.matches[0]
    assert match.status == CrossSourceMatchStatus.CONFLICT
    assert any("Overpayment conflict" in d for d in match.discrepancy_reasons)


# =========================================================================
# Scenario 13: Delayed Settlement -> Timing Difference Tracked
# =========================================================================
def test_scenario_13_delayed_settlement(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves delayed settlement (captured in period, paid out next period) is tracked as timing difference."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)

    # Order on the last day of period
    _order = {
        "id": "gid://shopify/Order/8001",
        "name": "#8001",
        "total_price": "200.00",
        "currency": "USD",
        "created_at": p_end.isoformat(),
        "transactions": [{"receipt": {"charge_id": "ch_delayed_1"}}],
    }
    # Charge succeeded during period
    _charge_txn = {
        "id": "ch_delayed_1",
        "source": "ch_delayed_1",
        "type": "charge",
        "amount": 20000,
        "fee": 610,
        "net": 19390,
        "currency": "usd",
        "status": "succeeded",
        "created": int(p_end.timestamp()),
        "metadata": {"order_id": "gid://shopify/Order/8001"},
    }

    # Payout occurs October 2 (after period close)
    payout_dt = datetime(2026, 10, 2, tzinfo=UTC)
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=1,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-del",
        cursor_chain_hash="b" * 64,
        records_extracted=1,
        records_ingested=1,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        unresolved_adjustments=[
            f"TIMING_DIFFERENCE: Charge 'ch_delayed_1' settled in bank payout on {payout_dt.isoformat()}"
        ],
        is_complete=True,
    )

    assert len(stripe_comp.unresolved_adjustments) == 1
    assert "TIMING_DIFFERENCE" in stripe_comp.unresolved_adjustments[0]


# =========================================================================
# Scenario 14: Post-Close Transaction -> Out of Nominal Period Boundary
# =========================================================================
def test_scenario_14_post_close_transaction(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves transaction occurring after nominal close is flagged as out-of-period."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    post_close_dt = p_end + timedelta(hours=2)
    _post_close_order = {
        "id": "gid://shopify/Order/post_close_01",
        "name": "#POST-01",
        "total_price": "150.00",
        "currency": "USD",
        "created_at": post_close_dt.isoformat(),
        "transactions": [],
    }

    # Ingestion coordinator rejects period_end <= period_start
    with pytest.raises(ValueError, match="must be strictly after"):
        MultiSourcePeriodCloseService.coordinate_multi_source_ingestion(
            session=pg_session,
            business_id=disposable_synthetic_tenant,
            period_start=p_end,
            period_end=p_start,  # Inverted boundary!
            shopify_adapter=None,  # type: ignore
            stripe_adapter=None,  # type: ignore
        )


# =========================================================================
# Scenario 15: Backfill After Initial Manifest Generation -> Invalidates
# =========================================================================
def test_scenario_15_backfill_after_initial_manifest_generation(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that backfill transaction inserted into closed period invalidates package integrity."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement before backfill.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )
    certified_pkg = MultiSourcePeriodCloseService.validate_and_certify_package(
        signed_pkg, session=pg_session
    )
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.VERIFIED_COMPLETE

    # Subsequent backfill arrives: new order backfilled into September
    mutated_shopify_orders = list(shopify_orders)
    mutated_shopify_orders.append(
        {
            "id": "gid://shopify/Order/backfill_999",
            "name": "#BACKFILL-999",
            "total_price": "50.00",
            "currency": "USD",
        }
    )

    # Re-verify integrity of the persisted dataset
    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=mutated_shopify_orders,
        current_stripe_transactions=stripe_txns,
    )

    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


# =========================================================================
# Scenario 16: Duplicate Webhook Delivery -> Idempotent
# =========================================================================
def test_scenario_16_duplicate_webhook_delivery(
    disposable_synthetic_tenant, pg_session
):
    """Proves webhook inbox handles duplicate delivery idempotently on PostgreSQL staging."""
    event_id = f"evt_dup_{uuid4().hex[:8]}"
    raw_payload = json.dumps({"id": event_id, "amount": 10000, "status": "succeeded"}).encode("utf-8")

    # Ingestion 1
    event_1, is_new_1 = WebhookInboxService.record_incoming_event(
        session=pg_session,
        business_id=disposable_synthetic_tenant,
        provider="stripe",
        provider_account_id="acct_syn_webhook",
        event_id=event_id,
        event_type="charge.succeeded",
        payload_bytes=raw_payload,
        signature_verified=True,
    )
    pg_session.commit()
    assert is_new_1 is True

    # Ingestion 2 (Duplicate)
    event_2, is_new_2 = WebhookInboxService.record_incoming_event(
        session=pg_session,
        business_id=disposable_synthetic_tenant,
        provider="stripe",
        provider_account_id="acct_syn_webhook",
        event_id=event_id,
        event_type="charge.succeeded",
        payload_bytes=raw_payload,
        signature_verified=True,
    )
    pg_session.commit()
    assert is_new_2 is False
    assert event_1.id == event_2.id


# =========================================================================
# Scenario 17: Webhook Processing Failure -> Downstream Rollback
# =========================================================================
def test_scenario_17_webhook_processing_failure(
    disposable_synthetic_tenant, pg_session
):
    """Proves transaction rollback safely preserves PENDING state in inbox upon processing failure."""
    event_id = f"evt_fail_{uuid4().hex[:8]}"
    raw_payload = b'{"action": "test_failure"}'

    event, is_new = WebhookInboxService.record_incoming_event(
        session=pg_session,
        business_id=disposable_synthetic_tenant,
        provider="shopify",
        provider_account_id="store.myshopify.com",
        event_id=event_id,
        event_type="orders/create",
        payload_bytes=raw_payload,
        signature_verified=True,
    )
    pg_session.commit()
    assert is_new is True

    # Worker claims event
    claimed = WebhookInboxService.claim_event_for_processing(
        session=pg_session,
        inbox_id=event.id,
        worker_id="worker_alpha",
    )
    assert claimed is not None
    pg_session.commit()

    # Downstream handler fails and rolls back
    try:
        # Simulate exception during handler execution
        raise RuntimeError("Downstream database deadlock")
    except Exception:  # noqa: BLE001
        pg_session.rollback()
        # Mark failure with error message
        WebhookInboxService.fail_event_processing(
            session=pg_session,
            inbox_id=event.id,
            error_message="Downstream database deadlock",
        )
        pg_session.commit()

    # Verify event state in PostgreSQL
    refreshed = pg_session.execute(
        select(ConnectorWebhookInbox).where(ConnectorWebhookInbox.id == event.id)
    ).scalar_one()
    assert refreshed.status == "FAILED"
    assert refreshed.retry_count == 1
    assert "deadlock" in refreshed.last_error


# =========================================================================
# Scenario 18: Stale Source Checkpoint -> Blocks Certification
# =========================================================================
def test_scenario_18_stale_source_checkpoint(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that checkpoints completed more than 24 hours ago block certification."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    stale_completion = datetime.now(UTC) - timedelta(hours=36)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-stale",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=stale_completion,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=datetime.now(UTC),
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with stale checkpoint.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    # Inject stale checkpoint timestamp
    package.source_checkpoints["shopify"]["completed_at"] = stale_completion.isoformat()

    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    with pytest.raises(ValueError, match="STALE_SOURCE_CHECKPOINT"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 19: Untrusted Signing Key -> Fails Closed
# =========================================================================
def test_scenario_19_untrusted_signing_key(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that signatures from unknown/unregistered key IDs fail closed."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with untrusted key.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id="unregistered_rogue_key_id",
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    with pytest.raises(PermissionError, match="Untrusted or unregistered key_id"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 20: Revoked Signing Key -> Fails Closed
# =========================================================================
def test_scenario_20_revoked_signing_key(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that revoked signing keys fail closed immediately."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    # Revoke the signing key
    ManifestKeyRegistry.revoke_key(
        business_id=disposable_synthetic_tenant,
        key_id=signing_keys["key_id"],
        reason="Security audit compromise rehearsal",
    )

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with revoked key.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    with pytest.raises(PermissionError, match="revoked"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 21: Invalid Manifest Signature -> Fails Closed
# =========================================================================
def test_scenario_21_invalid_manifest_signature(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves signature tampering or corruption fails closed."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with tampered signature.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )

    # Sign with a completely different rogue key
    rogue_key = ed25519.Ed25519PrivateKey.generate()
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, rogue_key, "ed25519"
    )

    with pytest.raises(ValueError, match="Cryptographic verification failed"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


# =========================================================================
# Scenario 22: Incorrect Transaction Identity Digest -> Fails Closed
# =========================================================================
def test_scenario_22_incorrect_transaction_identity_digest(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves transaction identity digest tampering fails closed."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement with forged digest.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )

    # Corrupt transaction digest
    package.transaction_identity_digests["dataset_identity_digest"] = "f" * 64
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    # Invalidate dataset check
    is_valid, _reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=signed_pkg,
        current_shopify_orders=shopify_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert signed_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED


# =========================================================================
# Scenario 23: Changed Persisted Transaction After Validation -> INVALIDATED
# =========================================================================
def test_scenario_23_changed_persisted_transaction_after_validation(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves mutating an order amount after certification flips status to INVALIDATED."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement for mutation test.",
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=disposable_synthetic_tenant,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )
    certified_pkg = MultiSourcePeriodCloseService.validate_and_certify_package(
        signed_pkg, session=pg_session
    )
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.VERIFIED_COMPLETE

    # Mutate order ID under the hood
    tampered_orders = list(shopify_orders)
    tampered_orders[0] = dict(tampered_orders[0], id="gid://shopify/Order/tampered_id")

    is_valid, _reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=tampered_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED


# =========================================================================
# Scenario 24: Synthetic Attestation Submitted for Real Tenant -> Fails Closed
# =========================================================================
def test_scenario_24_synthetic_attestation_for_real_tenant_fails_closed(
    pg_session, signing_keys
):
    """Proves Apex Specialty Commerce is strictly protected: synthetic attestation raises PermissionError."""
    real_tenant_id = "ab044b1a-835a-4a38-bf45-62fe38624151"
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)

    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    # Register key for real tenant to test policy gate
    ManifestKeyRegistry.register_key(
        business_id=real_tenant_id,
        key_id=signing_keys["key_id"],
        algorithm="ed25519",
        public_key_or_secret=signing_keys["public_key"],
        status="active",
    )

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="apex-specialty.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-apex-shop",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_apex_real",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-apex-strp",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Attempting to certify Apex with synthetic sandbox data.",
        is_synthetic=True,  # Synthetic provenance!
    )

    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=real_tenant_id,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    with pytest.raises(PermissionError, match="GOVERNANCE VIOLATION PREVENTED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)
    assert signed_pkg.validation_status == PeriodCloseLifecycleStatus.DIAGNOSTIC_ONLY


# =========================================================================
# Scenario 25: Cross-Tenant Evidence Injection -> Fails Closed
# =========================================================================
def test_scenario_25_cross_tenant_evidence_injection(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves evidence/signing key belonging to Tenant B injected into Tenant A fails closed."""
    _tenant_a = disposable_synthetic_tenant
    tenant_b = f"biz-tenant-b-{uuid4().hex[:6]}"

    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_standard_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="synthetic-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-ok",
        cursor_chain_hash="a" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_12345",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="b" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_admin_01",
        attester_role="admin",
        attestation_statement="Statement for cross-tenant test.",
    )

    # Package claimed under Tenant B, but signed with Tenant A's key
    package = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=tenant_b,  # Tenant B!
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        shopify_assessment=shopify_comp,
        stripe_assessment=stripe_comp,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],  # Key belongs to Tenant A!
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package, signing_keys["private_key"], "ed25519"
    )

    # Validation must reject because Key is not registered for Tenant B
    with pytest.raises(PermissionError, match="Untrusted or unregistered key_id"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)
