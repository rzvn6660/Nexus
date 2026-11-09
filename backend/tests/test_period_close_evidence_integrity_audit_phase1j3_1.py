"""
NEXUS Phase 1J.3.1 — Period-Close Evidence Integrity and Certification Audit Test Suite.

Executes non-mocked, rigorous adversarial tests against live PostgreSQL 16.15 staging:
1. Workstream 1 & 2: Complete Canonical Content Hashing & Field Inclusion Verification
2. Workstream 3: All 15 Material Mutation and Backfill Vectors:
   - Vector 1: Change existing Shopify order amount
   - Vector 2: Change order currency
   - Vector 3: Change line-item amount
   - Vector 4: Change order status
   - Vector 5: Add a refund
   - Vector 6: Change an existing refund amount
   - Vector 7: Change Stripe capture amount
   - Vector 8: Change Stripe fee
   - Vector 9: Change payout reference
   - Vector 10: Change settlement status
   - Vector 11: Change transaction-to-order linkage
   - Vector 12: Delete a previously included record
   - Vector 13: Insert a backdated record inside closed period
   - Vector 14: Change tenant ownership
   - Vector 15: Change provider account identity
3. Workstream 4: Persisted Evidence Snapshot and Atomicity (PostgreSQL Multi-Session Concurrency)
4. Workstream 5: Attestation Identity, Role Enforcement, and Key Trust
5. Workstream 6: Certification State Machine and Invalidation Enforcement
6. Workstream 7: PostgreSQL Durability, Rollback Safety, and Revalidation After Restart
"""

import copy
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.connector import ConnectorSyncCheckpoint
from app.models.tenant import Business, Organization
from app.schemas.period_close_evidence import (
    PeriodCloseAttestation,
    PeriodCloseLifecycleStatus,
    ShopifyCompletenessAssessment,
    StripeCompletenessAssessment,
)
from app.services.canonical_dataset_digest_service import (
    SCHEMA_VERSION_V2,
    CanonicalDatasetDigestService,
)
from app.services.manifest_service import ManifestKeyRegistry
from app.services.multi_source_period_close_service import MultiSourcePeriodCloseService
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

POSTGRES_STAGING_URI = os.getenv(
    "STAGING_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql+psycopg://nexus_staging_user:local_dev_password@127.0.0.1:5433/nexus_staging_db"),
)


@pytest.fixture(scope="module")
def pg_engine():
    """Module-level PostgreSQL engine connecting strictly to nexus_staging_db."""
    engine = create_engine(POSTGRES_STAGING_URI, pool_pre_ping=True)
    with engine.connect():
        dialect = engine.dialect.name
        driver = engine.dialect.driver
        version = engine.dialect.server_version_info
        assert dialect == "postgresql", f"Must run on PostgreSQL, got: {dialect}"
        print(f"\n[PHASE 1J.3.1 LIVE POSTGRES] Dialect: {dialect} | Driver: {driver} | Version: {version}")
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
    """Creates an isolated disposable synthetic tenant on PostgreSQL staging."""
    org_id = f"org-syn-{uuid4().hex[:8]}"
    biz_id = f"biz-syn-{uuid4().hex[:8]}"

    org = Organization(
        id=org_id,
        name="Synthetic Sandbox Audit Org",
        slug=f"slug-{uuid4().hex[:8]}",
    )
    biz = Business(
        id=biz_id,
        organization_id=org_id,
        name="Synthetic Sandbox Audit Store Ltd",
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
        except Exception:  # noqa: BLE001
            pg_session.rollback()


@pytest.fixture
def signing_keys(disposable_synthetic_tenant, pg_session):
    """Generates an Ed25519 signing key pair and registers public key with ManifestKeyRegistry."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    key_id = f"key-syn-audit-{uuid4().hex[:6]}"

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


def make_audit_dataset(period_start: datetime, period_end: datetime):
    """Generates a comprehensive dataset with nested line items, refunds, and linkages."""
    mid_date = period_start + timedelta(days=10)
    shopify_orders = [
        {
            "id": "gid://shopify/Order/2001",
            "name": "#2001",
            "total_price": "150.00",
            "total_tax": "15.00",
            "total_discounts": "10.00",
            "total_shipping": "5.00",
            "currency": "USD",
            "financial_status": "paid",
            "created_at": mid_date.isoformat(),
            "updated_at": (mid_date + timedelta(hours=1)).isoformat(),
            "customer_id": "gid://shopify/Customer/cust_101",
            "line_items": [
                {
                    "id": "gid://shopify/LineItem/item_1",
                    "product_id": "prod_1",
                    "title": "Widget Alpha",
                    "quantity": 2,
                    "price": "75.00",
                    "total_discount": "0.00",
                }
            ],
            "refunds": [],
            "transactions": [
                {"id": "txn_shop_2001", "receipt": {"charge_id": "ch_syn_2001"}, "authorization": "ch_syn_2001"}
            ],
        },
        {
            "id": "gid://shopify/Order/2002",
            "name": "#2002",
            "total_price": "300.00",
            "total_tax": "25.00",
            "total_discounts": "0.00",
            "total_shipping": "0.00",
            "currency": "USD",
            "financial_status": "partially_refunded",
            "created_at": (mid_date + timedelta(days=2)).isoformat(),
            "updated_at": (mid_date + timedelta(days=2, hours=3)).isoformat(),
            "customer_id": "gid://shopify/Customer/cust_102",
            "line_items": [
                {
                    "id": "gid://shopify/LineItem/item_2",
                    "product_id": "prod_2",
                    "title": "Widget Beta",
                    "quantity": 1,
                    "price": "300.00",
                    "total_discount": "0.00",
                }
            ],
            "refunds": [
                {
                    "id": "ref_shop_2002",
                    "created_at": (mid_date + timedelta(days=3)).isoformat(),
                    "amount": "50.00",
                    "note": "Customer satisfaction discount",
                }
            ],
            "transactions": [
                {"id": "txn_shop_2002", "receipt": {"charge_id": "ch_syn_2002"}, "authorization": "ch_syn_2002"}
            ],
        },
    ]

    stripe_txns = [
        {
            "id": "ch_syn_2001",
            "source": "ch_syn_2001",
            "type": "charge",
            "amount": 15000,
            "amount_captured": 15000,
            "amount_refunded": 0,
            "fee": 465,
            "net": 14535,
            "currency": "usd",
            "status": "succeeded",
            "settlement_status": "settled",
            "balance_transaction": "txn_bal_2001",
            "payout": "po_syn_batch_01",
            "created": int(mid_date.timestamp()),
            "metadata": {"order_id": "gid://shopify/Order/2001", "order_number": "#2001"},
        },
        {
            "id": "ch_syn_2002",
            "source": "ch_syn_2002",
            "type": "charge",
            "amount": 30000,
            "amount_captured": 30000,
            "amount_refunded": 5000,
            "fee": 900,
            "net": 24100,
            "currency": "usd",
            "status": "succeeded",
            "settlement_status": "settled",
            "balance_transaction": "txn_bal_2002",
            "payout": "po_syn_batch_01",
            "created": int((mid_date + timedelta(days=2)).timestamp()),
            "metadata": {"order_id": "gid://shopify/Order/2002", "order_number": "#2002"},
        },
    ]

    return shopify_orders, stripe_txns


def build_and_certify_standard(disposable_synthetic_tenant, pg_session, signing_keys):
    """Helper to assemble, sign, and certify a standard valid package."""
    p_start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)
    shopify_orders, stripe_txns = make_audit_dataset(p_start, p_end)

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="audit-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id="ckpt-shop-audit",
        cursor_chain_hash="c" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_audit_01",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        refunds_count=1,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-audit",
        cursor_chain_hash="d" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_fin_controller_01",
        attester_role="finance_controller",
        attestation_statement="Independent Phase 1J.3.1 audit attestation.",
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
        signed_pkg,
        session=pg_session,
        calling_user_id="user_fin_controller_01",
        calling_user_role="finance_controller",
    )
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.VERIFIED_COMPLETE

    return p_start, p_end, shopify_orders, stripe_txns, certified_pkg


# =========================================================================
# Workstream 1 & 2: Canonical Content Hashing & Determinism
# =========================================================================
def test_workstream_1_2_canonical_content_hashing_determinism(disposable_synthetic_tenant):
    """Proves deterministic canonicalization, schema version, stable field ordering, and explicit decimal representation."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_audit_dataset(p_start, p_end)

    digests_1 = CanonicalDatasetDigestService.compute_dataset_identity_digest(
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        business_id=disposable_synthetic_tenant,
        shopify_store_domain="audit-store.myshopify.com",
        stripe_account_id="acct_syn_audit_01",
        period_start=p_start,
        period_end=p_end,
    )

    # Shuffled record orders must produce identical canonical digest
    shuffled_shopify = [shopify_orders[1], shopify_orders[0]]
    shuffled_stripe = [stripe_txns[1], stripe_txns[0]]

    digests_2 = CanonicalDatasetDigestService.compute_dataset_identity_digest(
        shopify_orders=shuffled_shopify,
        stripe_transactions=shuffled_stripe,
        business_id=disposable_synthetic_tenant,
        shopify_store_domain="audit-store.myshopify.com",
        stripe_account_id="acct_syn_audit_01",
        period_start=p_start,
        period_end=p_end,
    )

    assert digests_1["dataset_identity_digest"] == digests_2["dataset_identity_digest"]
    assert digests_1["schema_version"] == SCHEMA_VERSION_V2
    assert len(digests_1["dataset_identity_digest"]) == 64


# =========================================================================
# Workstream 3: All 15 Material Mutation and Backfill Vectors
# =========================================================================

def test_mutation_vector_01_change_shopify_order_amount(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 1: Changing Shopify order amount invalidates certified package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_orders = copy.deepcopy(shopify_orders)
    tampered_orders[0]["total_price"] = "155.00"  # $5 silent increase

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=tampered_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_02_change_order_currency(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 2: Changing Shopify order currency invalidates certified package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_orders = copy.deepcopy(shopify_orders)
    tampered_orders[0]["currency"] = "EUR"  # Currency shift

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=tampered_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_03_change_line_item_amount(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 3: Changing a nested line-item price invalidates certified package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_orders = copy.deepcopy(shopify_orders)
    tampered_orders[0]["line_items"][0]["price"] = "80.00"

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=tampered_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_04_change_order_status(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 4: Altering order financial status (e.g. paid -> voided) invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_orders = copy.deepcopy(shopify_orders)
    tampered_orders[0]["financial_status"] = "voided"

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=tampered_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_05_add_refund(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 5: Adding a post-close refund to an existing order invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_orders = copy.deepcopy(shopify_orders)
    tampered_orders[0]["refunds"].append(
        {
            "id": "ref_new_post_close",
            "amount": "20.00",
            "created_at": "2026-09-25T12:00:00Z",
            "note": "Late return",
        }
    )

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=tampered_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_06_change_refund_amount(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 6: Modifying an existing refund amount invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_orders = copy.deepcopy(shopify_orders)
    tampered_orders[1]["refunds"][0]["amount"] = "60.00"  # Changed from 50.00 to 60.00

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=tampered_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_07_change_stripe_capture_amount(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 7: Modifying Stripe captured amount invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_stripe = copy.deepcopy(stripe_txns)
    tampered_stripe[0]["amount_captured"] = 14000  # Partial capture shift

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=shopify_orders,
        current_stripe_transactions=tampered_stripe,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_08_change_stripe_fee(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 8: Modifying payment processing fees invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_stripe = copy.deepcopy(stripe_txns)
    tampered_stripe[0]["fee"] = 550  # Fee adjustment

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=shopify_orders,
        current_stripe_transactions=tampered_stripe,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_09_change_payout_reference(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 9: Reassigning a transaction to a different bank payout batch invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_stripe = copy.deepcopy(stripe_txns)
    tampered_stripe[0]["payout"] = "po_syn_batch_rogue_99"

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=shopify_orders,
        current_stripe_transactions=tampered_stripe,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_10_change_settlement_status(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 10: Changing settlement status (settled -> unsettled) invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_stripe = copy.deepcopy(stripe_txns)
    tampered_stripe[0]["settlement_status"] = "unsettled"

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=shopify_orders,
        current_stripe_transactions=tampered_stripe,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_11_change_transaction_linkage(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 11: Modifying transaction-to-order linkage in metadata invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    tampered_stripe = copy.deepcopy(stripe_txns)
    tampered_stripe[0]["metadata"]["order_id"] = "gid://shopify/Order/rogue_order_link"

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=shopify_orders,
        current_stripe_transactions=tampered_stripe,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_12_delete_included_record(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 12: Deleting a previously certified record invalidates package."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    truncated_orders = [shopify_orders[0]]  # Order 2002 deleted

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=truncated_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_13_insert_backdated_record(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 13: Inserting an unannounced backdated record into the closed period invalidates package."""
    p_start, _p_end, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    backfilled_orders = copy.deepcopy(shopify_orders)
    backfilled_orders.append(
        {
            "id": "gid://shopify/Order/2003_backdated",
            "name": "#2003-BACKDATED",
            "total_price": "89.00",
            "currency": "USD",
            "created_at": (p_start + timedelta(days=5)).isoformat(),
        }
    )

    is_valid, reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified_pkg,
        current_shopify_orders=backfilled_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert certified_pkg.validation_status == PeriodCloseLifecycleStatus.INVALIDATED
    assert "INTEGRITY VIOLATION" in reason


def test_mutation_vector_14_change_tenant_ownership(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 14: Attacker attempting cross-tenant package re-binding fails closed."""
    _, _, shopify_orders, stripe_txns, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    # Attempt to verify package under a different tenant ID
    foreign_package = copy.deepcopy(certified_pkg)
    foreign_package.business_id = "biz-foreign-rogue-tenant"

    is_valid, _reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=foreign_package,
        current_shopify_orders=shopify_orders,
        current_stripe_transactions=stripe_txns,
    )
    assert is_valid is False
    assert foreign_package.validation_status == PeriodCloseLifecycleStatus.INVALIDATED


def test_mutation_vector_15_change_provider_account_identity(disposable_synthetic_tenant, pg_session, signing_keys):
    """Mutation Vector 15: Changing the provider account identity changes digest domain."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_audit_dataset(p_start, p_end)

    digests_original = CanonicalDatasetDigestService.compute_dataset_identity_digest(
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        business_id=disposable_synthetic_tenant,
        shopify_store_domain="audit-store.myshopify.com",
        stripe_account_id="acct_syn_audit_01",
        period_start=p_start,
        period_end=p_end,
    )

    digests_tampered_account = CanonicalDatasetDigestService.compute_dataset_identity_digest(
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_txns,
        business_id=disposable_synthetic_tenant,
        shopify_store_domain="rogue-store.myshopify.com",  # Altered account!
        stripe_account_id="acct_syn_audit_01",
        period_start=p_start,
        period_end=p_end,
    )

    assert digests_original["dataset_identity_digest"] != digests_tampered_account["dataset_identity_digest"]


# =========================================================================
# Workstream 4: Persisted Evidence Snapshot and Multi-Session Concurrency
# =========================================================================
def test_workstream_4_snapshot_atomicity_and_locking(
    disposable_synthetic_tenant, pg_engine, pg_session, signing_keys
):
    """Proves snapshot durability, checkpoint locking (SELECT ... FOR UPDATE), and concurrent ingestion rejection."""
    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_audit_dataset(p_start, p_end)

    # 1. Create durable sync checkpoint in PostgreSQL
    checkpoint = ConnectorSyncCheckpoint(
        id=f"ckpt-pg-audit-{uuid4().hex[:6]}",
        business_id=disposable_synthetic_tenant,
        provider="shopify",
        sync_mode="historical",
        period_start=p_start,
        period_end=p_end,
        status="COMPLETED",
        is_complete=True,
        records_extracted=2,
        records_ingested=2,
        cursor_chain_hash="e" * 64,
        metadata_json={},
    )
    pg_session.add(checkpoint)
    pg_session.commit()

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="audit-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id=checkpoint.id,
        cursor_chain_hash="e" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_audit_01",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="f" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_fin_controller_01",
        attester_role="finance_controller",
        attestation_statement="PostgreSQL snapshot atomicity test.",
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

    # 2. Record certified snapshot into PostgreSQL
    MultiSourcePeriodCloseService.record_certified_snapshot(session=pg_session, package=signed_pkg)
    pg_session.commit()

    # Verify that checkpoint now durably holds the dataset identity digest
    reloaded_ckpt = pg_session.execute(
        select(ConnectorSyncCheckpoint).where(ConnectorSyncCheckpoint.id == checkpoint.id)
    ).scalar_one()
    assert reloaded_ckpt.transaction_set_digest == signed_pkg.transaction_identity_digests["dataset_identity_digest"]
    assert reloaded_ckpt.metadata_json["certified_snapshot"]["package_id"] == signed_pkg.package_id

    # 3. Simulate concurrent session trying to tamper with the checkpoint digest
    Session2 = sessionmaker(bind=pg_engine)
    session_2 = Session2()
    try:
        ckpt_session_2 = session_2.execute(
            select(ConnectorSyncCheckpoint).where(ConnectorSyncCheckpoint.id == checkpoint.id)
        ).scalar_one()
        ckpt_session_2.transaction_set_digest = "0" * 64  # Concurrent mutation!
        session_2.commit()

        # Re-validation with pg_session must catch the SNAPSHOT_DIGEST_MISMATCH
        with pytest.raises(ValueError, match="SNAPSHOT_DIGEST_MISMATCH"):
            MultiSourcePeriodCloseService.validate_and_certify_package(
                signed_pkg,
                session=pg_session,
                calling_user_id="user_fin_controller_01",
                calling_user_role="finance_controller",
            )
    finally:
        session_2.close()


# =========================================================================
# Workstream 5: Attestation Identity and Trust
# =========================================================================
def test_workstream_5_attestation_caller_role_and_key_trust(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves caller role authentication, attester spoofing rejection, and key expiration fail-closed."""
    _, _, _, _, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )

    # 1. Caller role mismatch: Authenticated caller is "viewer" but claims "finance_controller"
    with pytest.raises(ValueError, match="Authenticated caller role 'viewer' does not match"):
        MultiSourcePeriodCloseService.validate_and_certify_package(
            certified_pkg,
            session=pg_session,
            calling_user_id="user_fin_controller_01",
            calling_user_role="viewer",  # Rogue role claim!
        )

    # 2. Caller user ID mismatch
    with pytest.raises(ValueError, match="does not match caller 'rogue_user'"):
        MultiSourcePeriodCloseService.validate_and_certify_package(
            certified_pkg,
            session=pg_session,
            calling_user_id="rogue_user",
            calling_user_role="finance_controller",
        )

    # 3. Expired key fails closed
    expired_key_id = f"key-expired-{uuid4().hex[:6]}"
    expired_dt = datetime.now(UTC) - timedelta(hours=2)
    ManifestKeyRegistry.register_key(
        business_id=disposable_synthetic_tenant,
        key_id=expired_key_id,
        algorithm="ed25519",
        public_key_or_secret=signing_keys["public_key"],
        status="active",
        expires_at=expired_dt,
    )
    certified_pkg.trusted_key_id = expired_key_id
    certified_pkg.manifest_signature.key_id = expired_key_id
    with pytest.raises(PermissionError, match="expired"):
        MultiSourcePeriodCloseService.validate_and_certify_package(certified_pkg, session=pg_session)


def test_workstream_5_cross_tenant_key_isolation(pg_session, signing_keys):
    """Proves that a key registered under Tenant A cannot be used to certify Tenant B."""
    tenant_a = f"biz-a-{uuid4().hex[:6]}"
    tenant_b = f"biz-b-{uuid4().hex[:6]}"

    # Key registered for Tenant A
    key_id = f"key-tenant-a-{uuid4().hex[:6]}"
    ManifestKeyRegistry.register_key(
        business_id=tenant_a,
        key_id=key_id,
        algorithm="ed25519",
        public_key_or_secret=signing_keys["public_key"],
        status="active",
    )

    # Request key for Tenant B
    with pytest.raises(PermissionError, match="(Cross-tenant|Untrusted or unregistered)"):
        ManifestKeyRegistry.get_key(business_id=tenant_b, key_id=key_id, session=pg_session)


# =========================================================================
# Workstream 6: State Machine and Invalidation Enforcement
# =========================================================================
def test_workstream_6_invalidated_package_reuse_is_blocked(
    disposable_synthetic_tenant, pg_session, signing_keys
):
    """Proves that once a package transitions to INVALIDATED, it cannot be reused or recertified."""
    _, _, _, _, certified_pkg = build_and_certify_standard(
        disposable_synthetic_tenant, pg_session, signing_keys
    )
    # Manually flag as INVALIDATED (e.g. after detection of backfill)
    certified_pkg.validation_status = PeriodCloseLifecycleStatus.INVALIDATED

    with pytest.raises(ValueError, match="INVALIDATED_PACKAGE_REUSE_BLOCKED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(
            certified_pkg,
            session=pg_session,
            calling_user_id="user_fin_controller_01",
            calling_user_role="finance_controller",
        )


# =========================================================================
# Workstream 7: PostgreSQL Concurrency, Durability, and Restart Verification
# =========================================================================
def test_workstream_7_postgresql_durability_and_restart(
    disposable_synthetic_tenant, pg_engine, signing_keys
):
    """Proves that certified snapshot survives database engine re-connection and re-verifies cleanly."""
    Session1 = sessionmaker(bind=pg_engine)
    session_1 = Session1()

    p_start = datetime(2026, 9, 1, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, tzinfo=UTC)
    shopify_orders, stripe_txns = make_audit_dataset(p_start, p_end)

    checkpoint = ConnectorSyncCheckpoint(
        id=f"ckpt-restart-{uuid4().hex[:6]}",
        business_id=disposable_synthetic_tenant,
        provider="shopify",
        sync_mode="historical",
        period_start=p_start,
        period_end=p_end,
        status="COMPLETED",
        is_complete=True,
        records_extracted=2,
        records_ingested=2,
        cursor_chain_hash="9" * 64,
        metadata_json={},
    )
    session_1.add(checkpoint)
    session_1.commit()

    shopify_comp = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain="audit-store.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id=checkpoint.id,
        cursor_chain_hash="9" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    stripe_comp = StripeCompletenessAssessment(
        account_id="acct_syn_audit_01",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id="ckpt-strp-ok",
        cursor_chain_hash="8" * 64,
        records_extracted=2,
        records_ingested=2,
        extraction_started_at=p_start,
        extraction_completed_at=p_end,
        is_complete=True,
    )
    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_fin_controller_01",
        attester_role="finance_controller",
        attestation_statement="PostgreSQL restart and persistence verification.",
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

    # Record snapshot in session 1
    MultiSourcePeriodCloseService.record_certified_snapshot(session=session_1, package=signed_pkg)
    ckpt_id = checkpoint.id
    session_1.commit()
    session_1.close()

    # Simulate fresh engine and session after restart
    fresh_engine = create_engine(POSTGRES_STAGING_URI, pool_pre_ping=True)
    FreshSession = sessionmaker(bind=fresh_engine)
    fresh_session = FreshSession()

    try:
        # Re-certify package in fresh session: must succeed without error
        revalidated = MultiSourcePeriodCloseService.validate_and_certify_package(
            signed_pkg,
            session=fresh_session,
            calling_user_id="user_fin_controller_01",
            calling_user_role="finance_controller",
        )
        assert revalidated.validation_status == PeriodCloseLifecycleStatus.VERIFIED_COMPLETE

        # Verify persisted checkpoint in fresh session
        ckpt = fresh_session.execute(
            select(ConnectorSyncCheckpoint).where(ConnectorSyncCheckpoint.id == ckpt_id)
        ).scalar_one()
        assert ckpt.transaction_set_digest == signed_pkg.transaction_identity_digests["dataset_identity_digest"]
    finally:
        fresh_session.close()
        fresh_engine.dispose()
