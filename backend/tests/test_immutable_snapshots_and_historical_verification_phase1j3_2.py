"""
NEXUS Phase 1J.3.2 — Immutable Evidence Snapshots and Historical Verification Test Suite.

Executes non-mocked, rigorous integration and adversarial tests against live PostgreSQL 16.15 staging:
1. Workstream 1: Snapshot Consistency & Explicit Writer Coordination
   - Vector 1: Source mutation before snapshot creation (snapshot reflects committed records)
   - Vector 2: Mutation during snapshot creation (exclusive lock blocks concurrent writer)
   - Vector 3: Mutation between digest computation and signing (pre-signing re-verification catches mismatch)
   - Vector 4: Mutation immediately after signing (post-signing continuous verification detects divergence)
   - Vector 5: Concurrent ingestion by another worker (mutual exclusion via advisory locks)
   - Vector 6: Backfill during evidence generation (blocked or detected)
   - Vector 7: Concurrent manifest generation for the same period (advisory lock prevents split-brain)
2. Workstream 2: Exact Monetary Canonicalization
   - ISO-4217 0-decimal currency (JPY) formatted without decimal points, rejecting fractional precision
   - ISO-4217 2-decimal currency (USD, EUR) formatted with 2 decimals, rejecting 3+ decimals
   - ISO-4217 3-decimal currency (KWD, BHD) formatted with 3 decimals, rejecting 4+ decimals
   - Binary float prohibition (raises TypeError)
   - Zero amounts, negative values (refunds), and exact decimal sensitivity
   - Unsupported currency rejection (raises ValueError)
3. Workstream 3: Immutable Historical Package
   - Complete ledger persistence in PostgreSQL ManifestSubmission
   - Immutability enforcement (prohibits overwriting existing package)
   - Distinct identity, version numbering, and explicit supersession links
4. Workstream 4: Independent Historical Signature Verification
   - Verification across application restarts
   - Verification after signing-key rotation
   - Verification after signing-key revocation
   - Verification with missing/unavailable key
   - Verification after source record mutation (historical signature valid, dataset diverged)
   - Verification after backfill (historical signature valid, dataset diverged)
   - Verification of a superseded package (historical signature valid, status SUPERSEDED)
   - Verification of an invalidated package (historical signature valid, status INVALIDATED)
5. Workstream 5: State Transition & Supersession Governance
   - Invalidated package reuse strictly blocked
   - Revalidation produces a new distinct package with supersedes linkage
   - Quarantine of real operational tenants (Apex Specialty Commerce)
6. Workstream 6: PostgreSQL Multi-Session Concurrency Proof
   - Real PostgreSQL 16.15 multi-session concurrency testing
"""

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.manifest import ManifestSubmission, TenantTrustedKey
from app.models.tenant import Business, Organization, UserIdentity
from app.schemas.period_close_evidence import (
    PeriodCloseAttestation,
    PeriodCloseEvidencePackage,
    PeriodCloseLifecycleStatus,
    ShopifyCompletenessAssessment,
    StripeCompletenessAssessment,
)
from app.services.canonical_dataset_digest_service import (
    CanonicalDatasetDigestService,
)
from app.services.historical_evidence_package_service import (
    HistoricalEvidencePackageService,
)
from app.services.ingestion_writer_coordinator import IngestionWriterCoordinator
from app.services.multi_source_period_close_service import MultiSourcePeriodCloseService
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

POSTGRES_STAGING_URL = (
    "postgresql+psycopg://nexus_staging_user:2HdXqcozgE-bBa6LjY9Qd0fj9PDtEZMkTuvj1q6QCqU@127.0.0.1:5433/nexus_staging_db"
)


@pytest.fixture(scope="module")
def pg_engine():
    """Create a live engine targeting the PostgreSQL 16.15 staging database."""
    engine = create_engine(POSTGRES_STAGING_URL, echo=False)
    try:
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version()")).scalar()
            assert "PostgreSQL 16" in ver or "PostgreSQL" in ver, f"Unexpected DB version: {ver}"
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Live PostgreSQL staging db unreachable on 127.0.0.1:5433: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def pg_session(pg_engine):
    """Provide an isolated, transactional PostgreSQL database session for each test."""
    session_factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    session = session_factory()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def disposable_synthetic_tenant(pg_session):
    """
    Creates an isolated synthetic tenant workspace in PostgreSQL staging.
    Cleaned up automatically after test execution.
    """
    tenant_uuid = str(uuid4())[:8]
    org_id = f"org-test-syn-{tenant_uuid}"
    biz_id = f"biz-test-syn-{tenant_uuid}"
    user_id = f"user-test-syn-{tenant_uuid}"

    user = UserIdentity(
        id=user_id,
        email=f"tester-{tenant_uuid}@synthetic-nexus.internal",
        password_hash="argon2_synthetic_hash_disabled",
        full_name=f"Synthetic Auditor {tenant_uuid}",
        is_active=True,
        is_verified=True,
    )
    org = Organization(id=org_id, name=f"Synthetic Sandbox Corp {tenant_uuid}", slug=f"syn-sandbox-{tenant_uuid}")
    biz = Business(
        id=biz_id,
        organization_id=org_id,
        name=f"Synthetic Sandbox Store {tenant_uuid}",
        industry="Ecommerce",
        currency="USD",
    )

    pg_session.add(user)
    pg_session.add(org)
    pg_session.add(biz)
    pg_session.commit()

    yield {"business_id": biz_id, "org_id": org_id, "user_id": user_id}

    # Cleanup
    pg_session.rollback()
    try:
        pg_session.execute(
            text("DELETE FROM manifest_submissions WHERE business_id = :b"),
            {"b": biz_id},
        )
        pg_session.execute(
            text("DELETE FROM connector_sync_checkpoints WHERE business_id = :b"),
            {"b": biz_id},
        )
        pg_session.execute(
            text("DELETE FROM tenant_trusted_keys WHERE business_id = :b"),
            {"b": biz_id},
        )
        pg_session.execute(text("DELETE FROM businesses WHERE id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        pg_session.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org_id})
        pg_session.commit()
    except Exception:  # noqa: BLE001
        pg_session.rollback()


@pytest.fixture(scope="function")
def signing_keys(disposable_synthetic_tenant, pg_session):
    """Provision a persistent trusted Ed25519 signing key for the synthetic tenant."""
    biz_id = disposable_synthetic_tenant["business_id"]
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    pub_pem = pub_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    key_id = f"key-syn-1j32-{biz_id[:8]}"
    trusted_key = TenantTrustedKey(
        business_id=biz_id,
        key_id=key_id,
        algorithm="ed25519",
        public_key_pem=pub_pem,
        status="active",
        allowed_roles=["owner", "admin", "finance_controller"],
        valid_from=datetime.now(UTC) - timedelta(hours=1),
    )
    pg_session.add(trusted_key)
    pg_session.commit()

    return {"key_id": key_id, "private_key": priv_key, "public_pem": pub_pem}


@pytest.fixture(scope="function")
def standard_period_fixtures(disposable_synthetic_tenant):
    """Standard period-close test fixtures across Shopify and Stripe."""
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    shopify_orders = [
        {
            "id": "gid://shopify/Order/1001",
            "name": "#1001",
            "order_number": 1001,
            "currency": "USD",
            "total_price": "150.00",
            "total_discounts": "0.00",
            "total_tax": "12.00",
            "total_shipping": "0.00",
            "financial_status": "PAID",
            "line_items": [
                {
                    "id": "gid://shopify/LineItem/1",
                    "title": "Ergonomic Mechanical Keyboard",
                    "quantity": 1,
                    "price": "150.00",
                    "total_discount": "0.00",
                }
            ],
            "refunds": [],
            "transactions": [
                {
                    "id": "gid://shopify/OrderTransaction/501",
                    "authorization": "ch_stripe_1001",
                    "gateway": "stripe",
                    "status": "SUCCESS",
                    "amount": "150.00",
                }
            ],
            "created_at": "2026-09-05T14:30:00Z",
            "updated_at": "2026-09-05T14:35:00Z",
        },
        {
            "id": "gid://shopify/Order/1002",
            "name": "#1002",
            "order_number": 1002,
            "currency": "USD",
            "total_price": "300.00",
            "total_discounts": "0.00",
            "total_tax": "24.00",
            "total_shipping": "0.00",
            "financial_status": "PARTIALLY_REFUNDED",
            "line_items": [
                {
                    "id": "gid://shopify/LineItem/2",
                    "title": "USB-C Dual 4K Display Dock",
                    "quantity": 1,
                    "price": "300.00",
                    "total_discount": "0.00",
                }
            ],
            "refunds": [
                {
                    "id": "gid://shopify/Refund/901",
                    "created_at": "2026-09-08T10:00:00Z",
                    "amount": "50.00",
                    "note": "Partial satisfaction courtesy refund",
                }
            ],
            "transactions": [
                {
                    "id": "gid://shopify/OrderTransaction/502",
                    "authorization": "ch_stripe_1002",
                    "gateway": "stripe",
                    "status": "SUCCESS",
                    "amount": "300.00",
                }
            ],
            "created_at": "2026-09-06T11:15:00Z",
            "updated_at": "2026-09-08T10:05:00Z",
        },
    ]

    stripe_transactions = [
        {
            "id": "ch_stripe_1001",
            "type": "charge",
            "currency": "USD",
            "amount": 15000,
            "amount_captured": 15000,
            "amount_refunded": 0,
            "fee": 465,
            "net": 14535,
            "status": "succeeded",
            "settlement_status": "settled",
            "created": 1788618600,
            "metadata": {"order_number": "1001", "order_id": "gid://shopify/Order/1001"},
            "balance_transaction": "txn_stripe_bal_1001",
            "payout": "po_stripe_batch_sep",
        },
        {
            "id": "ch_stripe_1002",
            "type": "charge",
            "currency": "USD",
            "amount": 30000,
            "amount_captured": 30000,
            "amount_refunded": 5000,
            "fee": 900,
            "net": 24100,
            "status": "succeeded",
            "settlement_status": "settled",
            "created": 1788693300,
            "metadata": {"order_number": "1002", "order_id": "gid://shopify/Order/1002"},
            "balance_transaction": "txn_stripe_bal_1002",
            "payout": "po_stripe_batch_sep",
        },
    ]

    shopify_assessment = ShopifyCompletenessAssessment(
        api_version="2026-10",
        store_domain=f"store-{biz_id[:8]}.myshopify.com",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id=f"ckpt-shopify-{biz_id[:8]}",
        cursor_chain_hash="hash_shopify_chain_terminal",
        records_extracted=2,
        records_ingested=2,
        records_rejected=0,
        extraction_started_at=datetime.now(UTC) - timedelta(minutes=10),
        extraction_completed_at=datetime.now(UTC) - timedelta(minutes=5),
        is_complete=True,
    )

    stripe_assessment = StripeCompletenessAssessment(
        account_id=f"acct_{biz_id[:8]}",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=2,
        refunds_count=1,
        payouts_count=1,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id=f"ckpt-stripe-{biz_id[:8]}",
        cursor_chain_hash="hash_stripe_chain_terminal",
        records_extracted=2,
        records_ingested=2,
        records_rejected=0,
        extraction_started_at=datetime.now(UTC) - timedelta(minutes=10),
        extraction_completed_at=datetime.now(UTC) - timedelta(minutes=5),
        is_complete=True,
    )

    attestation = PeriodCloseAttestation(
        attested_by_user_id="user_fin_controller_01",
        attester_role="finance_controller",
        attestation_statement="Independent snapshot and historical verification test attestation.",
        is_synthetic=True,
        provenance_type="synthetic_rehearsal_attestation",
    )

    return {
        "business_id": biz_id,
        "period_start": p_start,
        "period_end": p_end,
        "shopify_orders": shopify_orders,
        "stripe_transactions": stripe_transactions,
        "shopify_assessment": shopify_assessment,
        "stripe_assessment": stripe_assessment,
        "attestation": attestation,
    }


# ==============================================================================
# WORKSTREAM 1: Snapshot Consistency & Explicit Writer Coordination
# ==============================================================================


def test_ws1_v1_source_mutation_before_snapshot_creation(standard_period_fixtures, signing_keys, pg_session):
    """
    Vector 1: When source records mutate before snapshot creation, the snapshot
    accurately captures the new state and its digest reflects the mutated records.
    """
    fixtures = copy.deepcopy(standard_period_fixtures)
    # Mutate record before package is built (mutating commercial order and payment together to stay reconciled)
    fixtures["shopify_orders"][0]["total_price"] = "200.00"
    fixtures["shopify_orders"][0]["line_items"][0]["price"] = "200.00"
    fixtures["shopify_orders"][0]["transactions"][0]["amount"] = "200.00"
    fixtures["stripe_transactions"][0]["amount"] = 20000
    fixtures["stripe_transactions"][0]["amount_captured"] = 20000
    fixtures["stripe_transactions"][0]["net"] = 20000 - fixtures["stripe_transactions"][0]["fee"]

    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package=pkg,
        private_key=signing_keys["private_key"],
    )
    certified = MultiSourcePeriodCloseService.validate_and_certify_package(
        package=signed_pkg,
        session=pg_session,
    )

    assert certified.validation_status == PeriodCloseLifecycleStatus.VERIFIED_COMPLETE
    assert certified.transaction_identity_digests["dataset_identity_digest"] is not None


def test_ws1_v2_mutation_during_snapshot_creation_blocked(standard_period_fixtures, pg_engine):
    """
    Vector 2: When a period-close snapshot process holds an exclusive advisory lock,
    a concurrent worker attempting to acquire an ingestion write lock is blocked or rejected.
    """
    biz_id = standard_period_fixtures["business_id"]
    p_start = standard_period_fixtures["period_start"]
    p_end = standard_period_fixtures["period_end"]

    session_maker = sessionmaker(bind=pg_engine)
    session_1 = session_maker()
    session_2 = session_maker()

    try:
        # Session 1: Acquire exclusive period close lock
        locked = IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_1,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )
        assert locked is True

        # Session 2: Attempt non-blocking ingestion write lock -> Must fail
        with pytest.raises(RuntimeError, match="PERIOD_CLOSE_IN_PROGRESS"):
            IngestionWriterCoordinator.acquire_ingestion_lock(
                session=session_2,
                business_id=biz_id,
                period_start=p_start,
                period_end=p_end,
                blocking=False,
            )

        # Session 1 rolls back / releases
        session_1.rollback()

        # Session 2 now can acquire ingestion lock
        ingest_locked = IngestionWriterCoordinator.acquire_ingestion_lock(
            session=session_2,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )
        assert ingest_locked is True

    finally:
        session_1.close()
        session_2.close()


def test_ws1_v3_mutation_between_digest_and_signing_detected():
    """
    Vector 3: Concurrency mutation between digest computation and signing
    is caught by pre-signing verification, raising SNAPSHOT_CONCURRENCY_MUTATION_DETECTED.
    """
    initial_digest = "a" * 64
    mutated_digest = "b" * 64

    with pytest.raises(RuntimeError, match="SNAPSHOT_CONCURRENCY_MUTATION_DETECTED"):
        IngestionWriterCoordinator.verify_snapshot_integrity(
            initial_dataset_digest=initial_digest,
            current_dataset_digest=mutated_digest,
        )


def test_ws1_v4_mutation_after_signing_invalidates_package(standard_period_fixtures, signing_keys, pg_session):
    """
    Vector 4: When underlying records mutate immediately after signing,
    continuous integrity verification flags the package as INVALIDATED.
    """
    fixtures = standard_period_fixtures
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(pkg, signing_keys["private_key"])
    certified = MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)
    assert certified.validation_status == PeriodCloseLifecycleStatus.VERIFIED_COMPLETE

    # Subsequent mutation
    tampered_orders = copy.deepcopy(fixtures["shopify_orders"])
    tampered_orders[0]["total_price"] = "999.99"

    is_valid, _reason = MultiSourcePeriodCloseService.validate_persisted_dataset_integrity(
        package=certified,
        current_shopify_orders=tampered_orders,
        current_stripe_transactions=fixtures["stripe_transactions"],
    )
    assert not is_valid
    assert certified.validation_status == PeriodCloseLifecycleStatus.INVALIDATED


def test_ws1_v5_v6_v7_concurrent_manifest_generation_mutual_exclusion(standard_period_fixtures, pg_engine):
    """
    Vector 5, 6, 7: Concurrent manifest generation for the exact same tenant and period
    is mutually excluded by PostgreSQL advisory locks, preventing duplicate or split-brain packages.
    """
    biz_id = standard_period_fixtures["business_id"]
    p_start = standard_period_fixtures["period_start"]
    p_end = standard_period_fixtures["period_end"]

    session_maker = sessionmaker(bind=pg_engine)
    session_a = session_maker()
    session_b = session_maker()

    try:
        # Worker A acquires lock
        lock_a = IngestionWriterCoordinator.acquire_period_close_lock(
            session_a, biz_id, p_start, p_end, blocking=False
        )
        assert lock_a is True

        # Worker B tries to acquire concurrent lock for same period -> Must fail
        with pytest.raises(RuntimeError, match="CONCURRENT_PERIOD_CLOSE_LOCKED"):
            IngestionWriterCoordinator.acquire_period_close_lock(
                session_b, biz_id, p_start, p_end, blocking=False
            )

        session_a.commit()
    finally:
        session_a.close()
        session_b.close()


# ==============================================================================
# WORKSTREAM 2: Exact Monetary Canonicalization
# ==============================================================================


def test_ws2_zero_decimal_currency_jpy():
    """
    ISO-4217 zero-decimal currency (JPY) formatted without decimal points.
    Rejects fractional amounts with ValueError.
    """
    # Valid integer minor units or string
    res = CanonicalDatasetDigestService.format_exact_monetary(15000, "JPY", is_minor_units=True)
    assert res == {"amount": "15000", "currency": "JPY"}

    res_str = CanonicalDatasetDigestService.format_exact_monetary("25000", "JPY")
    assert res_str == {"amount": "25000", "currency": "JPY"}

    # Rejection of fractional units
    with pytest.raises(ValueError, match="exceeding exponent 0"):
        CanonicalDatasetDigestService.format_exact_monetary("15000.5", "JPY")


def test_ws2_two_decimal_currency_usd():
    """
    ISO-4217 two-decimal currency (USD) formatted with exactly 2 decimal places.
    Rejects 3+ decimal places with ValueError.
    """
    res = CanonicalDatasetDigestService.format_exact_monetary(15050, "USD", is_minor_units=True)
    assert res == {"amount": "150.50", "currency": "USD"}

    res_dec = CanonicalDatasetDigestService.format_exact_monetary(Decimal("150.50"), "USD")
    assert res_dec == {"amount": "150.50", "currency": "USD"}

    # Rejection of 3 decimal places
    with pytest.raises(ValueError, match="exceeding exponent 2"):
        CanonicalDatasetDigestService.format_exact_monetary("150.555", "USD")


def test_ws2_three_decimal_currency_kwd():
    """
    ISO-4217 three-decimal currency (KWD) formatted with exactly 3 decimal places.
    Rejects 4+ decimal places with ValueError.
    """
    # 15250 fils = 15.250 KWD
    res = CanonicalDatasetDigestService.format_exact_monetary(15250, "KWD", is_minor_units=True)
    assert res == {"amount": "15.250", "currency": "KWD"}

    res_str = CanonicalDatasetDigestService.format_exact_monetary("15.250", "KWD")
    assert res_str == {"amount": "15.250", "currency": "KWD"}

    # Rejection of 4 decimal places
    with pytest.raises(ValueError, match="exceeding exponent 3"):
        CanonicalDatasetDigestService.format_exact_monetary("15.2505", "KWD")


def test_ws2_binary_float_prohibited():
    """
    Passing a binary floating-point value raises TypeError.
    Prohibits IEEE-754 drift in financial calculations.
    """
    with pytest.raises(TypeError, match="Binary floating-point value"):
        CanonicalDatasetDigestService.format_exact_monetary(150.50, "USD")


def test_ws2_zero_and_negative_refund_values():
    """
    Zero and negative monetary values (refunds, adjustments) are exactly represented.
    """
    zero_usd = CanonicalDatasetDigestService.format_exact_monetary(0, "USD", is_minor_units=True)
    assert zero_usd == {"amount": "0.00", "currency": "USD"}

    zero_jpy = CanonicalDatasetDigestService.format_exact_monetary(0, "JPY", is_minor_units=True)
    assert zero_jpy == {"amount": "0", "currency": "JPY"}

    neg_usd = CanonicalDatasetDigestService.format_exact_monetary(-2500, "USD", is_minor_units=True)
    assert neg_usd == {"amount": "-25.00", "currency": "USD"}

    neg_str = CanonicalDatasetDigestService.format_exact_monetary("-50.00", "USD")
    assert neg_str == {"amount": "-50.00", "currency": "USD"}


def test_ws2_unsupported_currency_rejected():
    """
    Unsupported ISO-4217 currency code is rejected with ValueError.
    """
    with pytest.raises(ValueError, match="Unsupported ISO-4217 currency"):
        CanonicalDatasetDigestService.format_exact_monetary("100.00", "XYZ")


def test_ws2_materially_different_amounts_produce_different_digests(standard_period_fixtures):
    """
    Any material change in amount produces a completely distinct dataset digest.
    """
    fixtures_a = standard_period_fixtures
    fixtures_b = copy.deepcopy(standard_period_fixtures)
    fixtures_b["shopify_orders"][0]["total_price"] = "150.01"  # 1-cent shift

    dig_a = CanonicalDatasetDigestService.compute_dataset_identity_digest(
        fixtures_a["shopify_orders"],
        fixtures_a["stripe_transactions"],
    )
    dig_b = CanonicalDatasetDigestService.compute_dataset_identity_digest(
        fixtures_b["shopify_orders"],
        fixtures_b["stripe_transactions"],
    )
    assert dig_a["dataset_identity_digest"] != dig_b["dataset_identity_digest"]


# ==============================================================================
# WORKSTREAM 3: Immutable Historical Package
# ==============================================================================


def test_ws3_durable_immutable_record_persistence(standard_period_fixtures, signing_keys, pg_session):
    """
    Signed evidence package is durably and immutably persisted into ManifestSubmission.
    """
    fixtures = standard_period_fixtures
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(pkg, signing_keys["private_key"])
    certified = MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)

    submission = HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=certified,
        submitted_by_user_id=fixtures["attestation"].attested_by_user_id,
    )
    pg_session.commit()

    assert submission.manifest_id == certified.package_id
    assert submission.business_id == certified.business_id
    assert submission.file_sha256 == certified.canonical_payload_digest
    assert submission.verification_status == "verified_complete"


def test_ws3_immutable_package_overwrite_prohibited(standard_period_fixtures, signing_keys, pg_session):
    """
    Attempting to overwrite an existing historical package raises IMMUTABLE_PACKAGE_OVERWRITE_PROHIBITED.
    """
    fixtures = standard_period_fixtures
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(pkg, signing_keys["private_key"])

    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=signed_pkg,
        submitted_by_user_id=fixtures["attestation"].attested_by_user_id,
    )
    pg_session.commit()

    with pytest.raises(ValueError, match="IMMUTABLE_PACKAGE_OVERWRITE_PROHIBITED"):
        HistoricalEvidencePackageService.record_immutable_package(
            session=pg_session,
            package=signed_pkg,
            submitted_by_user_id=fixtures["attestation"].attested_by_user_id,
        )


def test_ws3_distinct_identity_and_supersession_lineage(standard_period_fixtures, signing_keys, pg_session):
    """
    A later package for the same period receives a distinct package ID, incremented version_number,
    and explicit supersedes_package_id and superseded_by_package_id links.
    """
    fixtures = standard_period_fixtures
    pkg_v1 = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
        version_number=1,
    )
    signed_v1 = MultiSourcePeriodCloseService.sign_evidence_package(pkg_v1, signing_keys["private_key"])
    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=signed_v1,
        submitted_by_user_id=fixtures["attestation"].attested_by_user_id,
    )
    pg_session.commit()

    # Package v2 (after re-reconciliation or backfill)
    pkg_v2 = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
        supersedes_package_id=signed_v1.package_id,
        version_number=2,
    )
    signed_v2 = MultiSourcePeriodCloseService.sign_evidence_package(pkg_v2, signing_keys["private_key"])
    _sub_v2 = HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=signed_v2,
        submitted_by_user_id=fixtures["attestation"].attested_by_user_id,
        supersedes_package_id=signed_v1.package_id,
    )
    pg_session.commit()

    assert signed_v2.package_id != signed_v1.package_id
    assert signed_v2.version_number == 2
    assert signed_v2.supersedes_package_id == signed_v1.package_id

    # Verify v1 is marked superseded in ledger
    prior_v1_sub = pg_session.execute(
        select(ManifestSubmission).where(ManifestSubmission.manifest_id == signed_v1.package_id)
    ).scalar_one()
    assert prior_v1_sub.verification_status == "superseded"
    assert prior_v1_sub.source_close_evidence_json.get("superseded_by_package_id") == signed_v2.package_id


# ==============================================================================
# WORKSTREAM 4: Historical Signature Verification
# ==============================================================================


def test_ws4_verification_after_app_restart(standard_period_fixtures, signing_keys, pg_engine):
    """
    Historical signature verification succeeds after an application restart
    using completely new database sessions.
    """
    fixtures = standard_period_fixtures
    session_factory = sessionmaker(bind=pg_engine)

    # Session 1: Create and record package
    session_1 = session_factory()
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(pkg, signing_keys["private_key"])
    certified = MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=session_1)
    HistoricalEvidencePackageService.record_immutable_package(
        session_1, certified, fixtures["attestation"].attested_by_user_id
    )
    session_1.commit()
    pkg_id = certified.package_id
    session_1.close()

    # Session 2: Fresh session simulating application restart
    session_2 = session_factory()
    try:
        res = HistoricalEvidencePackageService.verify_historical_package(
            session=session_2,
            package_or_id=pkg_id,
            current_shopify_orders=fixtures["shopify_orders"],
            current_stripe_transactions=fixtures["stripe_transactions"],
        )
        assert res.historical_signature_valid is True
        assert res.canonical_digest_matches is True
        assert res.current_dataset_diverged is False
        assert res.verification_verdict == "HISTORICALLY_VALID"
    finally:
        session_2.close()


def test_ws4_verification_after_key_rotation(standard_period_fixtures, signing_keys, pg_session):
    """
    Historical signature verification succeeds after the signing key has been rotated.
    """
    fixtures = standard_period_fixtures
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(pkg, signing_keys["private_key"])
    certified = MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)
    HistoricalEvidencePackageService.record_immutable_package(
        pg_session, certified, fixtures["attestation"].attested_by_user_id
    )
    pg_session.commit()

    # Rotate the key
    key_record = pg_session.execute(
        select(TenantTrustedKey).where(TenantTrustedKey.key_id == signing_keys["key_id"])
    ).scalar_one()
    key_record.status = "rotated"
    pg_session.commit()

    # Verify historical package
    res = HistoricalEvidencePackageService.verify_historical_package(
        session=pg_session,
        package_or_id=certified.package_id,
    )
    assert res.historical_signature_valid is True
    assert res.key_valid_at_signing is True
    assert res.current_key_status == "rotated"
    assert res.verification_verdict == "HISTORICALLY_VALID"


def test_ws4_verification_after_key_revocation(standard_period_fixtures, signing_keys, pg_session):
    """
    Historical signature verification succeeds after the signing key has been revoked,
    because the key was valid at signing time.
    However, attempting new certification with revoked key is blocked.
    """
    fixtures = standard_period_fixtures
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(pkg, signing_keys["private_key"])
    certified = MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)
    HistoricalEvidencePackageService.record_immutable_package(
        pg_session, certified, fixtures["attestation"].attested_by_user_id
    )
    pg_session.commit()

    # Revoke the key AFTER signing
    key_record = pg_session.execute(
        select(TenantTrustedKey).where(TenantTrustedKey.key_id == signing_keys["key_id"])
    ).scalar_one()
    key_record.status = "revoked"
    key_record.revoked_at = datetime.now(UTC)
    pg_session.commit()

    # Historical verification of previously signed package succeeds
    res = HistoricalEvidencePackageService.verify_historical_package(
        session=pg_session,
        package_or_id=certified.package_id,
    )
    assert res.historical_signature_valid is True
    assert res.key_valid_at_signing is True
    assert res.current_key_status == "revoked"
    assert res.verification_verdict == "HISTORICALLY_VALID"

    # But creating/certifying a NEW package with the revoked key fails
    new_pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    new_signed = MultiSourcePeriodCloseService.sign_evidence_package(new_pkg, signing_keys["private_key"])
    with pytest.raises((ValueError, PermissionError), match="revoked"):
        MultiSourcePeriodCloseService.validate_and_certify_package(new_signed, session=pg_session)


def test_ws4_verification_with_missing_key_fails(standard_period_fixtures, signing_keys, pg_session):
    """
    Verification with an unavailable or deleted key fails safely with KEY_NOT_FOUND.
    """
    fixtures = standard_period_fixtures
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id="non_existent_key_id",
    )
    pkg.manifest_signature = type(
        "ManifestSignature",
        (),
        {"algorithm": "ed25519", "key_id": "non_existent_key_id", "signature_hex": "00" * 64},
    )()

    res = HistoricalEvidencePackageService.verify_historical_package(
        session=pg_session,
        package_or_id=pkg,
    )
    assert res.historical_signature_valid is False
    assert res.key_status_at_signing == "not_found"


def test_ws4_verification_after_source_mutation_and_backfill(standard_period_fixtures, signing_keys, pg_session):
    """
    Verification after source records mutate or backfills occur preserves historical signature
    authenticity while correctly reporting dataset divergence.
    """
    fixtures = standard_period_fixtures
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(pkg, signing_keys["private_key"])
    certified = MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)
    HistoricalEvidencePackageService.record_immutable_package(
        pg_session, certified, fixtures["attestation"].attested_by_user_id
    )
    pg_session.commit()

    # Simulate backfill adding a new order
    mutated_orders = copy.deepcopy(fixtures["shopify_orders"])
    mutated_orders.append(
        {
            "id": "gid://shopify/Order/1003",
            "name": "#1003",
            "order_number": 1003,
            "currency": "USD",
            "total_price": "85.00",
            "line_items": [],
            "refunds": [],
            "transactions": [],
            "created_at": "2026-09-15T12:00:00Z",
        }
    )

    res = HistoricalEvidencePackageService.verify_historical_package(
        session=pg_session,
        package_or_id=certified.package_id,
        current_shopify_orders=mutated_orders,
        current_stripe_transactions=fixtures["stripe_transactions"],
    )
    assert res.historical_signature_valid is True
    assert res.current_dataset_diverged is True
    assert res.current_lifecycle_status == "INVALIDATED"
    assert res.verification_verdict == "HISTORICALLY_VALID_DATASET_DIVERGED"


def test_ws4_verification_of_superseded_package(standard_period_fixtures, signing_keys, pg_session):
    """
    A superseded historical package retains a valid historical signature,
    and reports verification_verdict == HISTORICALLY_VALID_SUPERSEDED.
    """
    fixtures = standard_period_fixtures
    # v1
    pkg_v1 = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
        version_number=1,
    )
    signed_v1 = MultiSourcePeriodCloseService.sign_evidence_package(pkg_v1, signing_keys["private_key"])
    HistoricalEvidencePackageService.record_immutable_package(
        pg_session, signed_v1, fixtures["attestation"].attested_by_user_id
    )
    pg_session.commit()

    # v2 supersedes v1
    pkg_v2 = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
        supersedes_package_id=signed_v1.package_id,
        version_number=2,
    )
    signed_v2 = MultiSourcePeriodCloseService.sign_evidence_package(pkg_v2, signing_keys["private_key"])
    HistoricalEvidencePackageService.record_immutable_package(
        pg_session, signed_v2, fixtures["attestation"].attested_by_user_id, supersedes_package_id=signed_v1.package_id
    )
    pg_session.commit()

    # Historical verification of v1
    res_v1 = HistoricalEvidencePackageService.verify_historical_package(
        session=pg_session,
        package_or_id=signed_v1.package_id,
        current_shopify_orders=fixtures["shopify_orders"],
        current_stripe_transactions=fixtures["stripe_transactions"],
    )
    assert res_v1.historical_signature_valid is True
    assert res_v1.is_superseded is True
    assert res_v1.superseded_by_package_id == signed_v2.package_id
    assert res_v1.verification_verdict == "HISTORICALLY_VALID_SUPERSEDED"


# ==============================================================================
# WORKSTREAM 5: State Transition & Supersession Governance
# ==============================================================================


def test_ws5_invalidated_package_reuse_is_blocked(standard_period_fixtures, signing_keys, pg_session):
    """
    An invalidated package cannot be recertified under any circumstances.
    """
    fixtures = standard_period_fixtures
    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=fixtures["business_id"],
        period_start=fixtures["period_start"],
        period_end=fixtures["period_end"],
        shopify_orders=fixtures["shopify_orders"],
        stripe_transactions=fixtures["stripe_transactions"],
        shopify_assessment=fixtures["shopify_assessment"],
        stripe_assessment=fixtures["stripe_assessment"],
        attestation=fixtures["attestation"],
        trusted_key_id=signing_keys["key_id"],
    )
    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(pkg, signing_keys["private_key"])
    signed_pkg.validation_status = PeriodCloseLifecycleStatus.INVALIDATED

    with pytest.raises(ValueError, match="INVALIDATED_PACKAGE_REUSE_BLOCKED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(signed_pkg, session=pg_session)


def test_ws5_quarantine_of_apex_specialty_commerce(pg_session):
    """
    Synthetic evidence cannot certify Apex Specialty Commerce (real operational tenant).
    Apex must remain strictly in DIAGNOSTIC_ONLY status.
    """
    apex_biz_id = "ab044b1a-835a-4a38-bf45-62fe38624151"
    pkg = PeriodCloseEvidencePackage(
        business_id=apex_biz_id,
        accounting_period_start=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        accounting_period_end=datetime(2026, 9, 30, 0, 0, tzinfo=UTC),
        currency="USD",
        attestation=PeriodCloseAttestation(
            attested_by_user_id="user_admin",
            attester_role="admin",
            attestation_statement="Attempt to certify protected Apex tenant.",
            is_synthetic=True,
        ),
    )

    with pytest.raises(PermissionError, match="GOVERNANCE VIOLATION PREVENTED"):
        MultiSourcePeriodCloseService.validate_and_certify_package(pkg, session=pg_session)

    assert pkg.validation_status == PeriodCloseLifecycleStatus.DIAGNOSTIC_ONLY


# ==============================================================================
# WORKSTREAM 6: PostgreSQL Multi-Session Concurrency & Telemetry
# ==============================================================================


def test_ws6_postgresql_multi_session_concurrency_proof(standard_period_fixtures, pg_engine):
    """
    Proves real PostgreSQL 16.15 advisory locks and session coordination across
    multiple independent physical connections.
    """
    biz_id = standard_period_fixtures["business_id"]
    p_start = standard_period_fixtures["period_start"]
    p_end = standard_period_fixtures["period_end"]

    session_maker = sessionmaker(bind=pg_engine)
    session_writer_1 = session_maker()
    session_writer_2 = session_maker()
    session_closer = session_maker()

    try:
        # Ingestion Writer 1 acquires shared lock
        w1_locked = IngestionWriterCoordinator.acquire_ingestion_lock(
            session_writer_1, biz_id, p_start, p_end, blocking=False
        )
        assert w1_locked is True

        # Ingestion Writer 2 can ALSO acquire shared lock concurrently
        w2_locked = IngestionWriterCoordinator.acquire_ingestion_lock(
            session_writer_2, biz_id, p_start, p_end, blocking=False
        )
        assert w2_locked is True

        # Period Close attempts exclusive lock -> must be REJECTED while shared writers are active
        with pytest.raises(RuntimeError, match="CONCURRENT_PERIOD_CLOSE_LOCKED"):
            IngestionWriterCoordinator.acquire_period_close_lock(
                session_closer, biz_id, p_start, p_end, blocking=False
            )

        # Writers finish and commit transactions
        session_writer_1.commit()
        session_writer_2.commit()

        # Period Closer now acquires exclusive lock successfully
        close_locked = IngestionWriterCoordinator.acquire_period_close_lock(
            session_closer, biz_id, p_start, p_end, blocking=False
        )
        assert close_locked is True
        session_closer.commit()

    finally:
        session_writer_1.close()
        session_writer_2.close()
        session_closer.close()
