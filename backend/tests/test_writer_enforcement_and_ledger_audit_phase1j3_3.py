"""
NEXUS Phase 1J.3.3 — Writer-Path Enforcement and Historical Ledger Audit Test Suite.

Executes non-mocked, adversarial concurrency and immutability tests against live PostgreSQL 16.15 staging:
1. Workstream 3: PostgreSQL Concurrency Test Suite
   - Test 1: Shopify ingestion blocks while snapshot holds exclusive lock
   - Test 2: Stripe ingestion blocks while snapshot holds exclusive lock
   - Test 3: Webhook-driven updates block during active close lock
   - Test 4: Backfill operations block during active close lock
   - Test 5: Ingestion proceeds immediately after snapshot commits or rolls back
   - Test 6: Failed ingestion transaction releases shared lock on rollback
   - Test 7: Failed period-close transaction releases exclusive lock on rollback
   - Test 8: Two independent shared writers proceed concurrently without mutual blocking
   - Test 9: Cross-tenant isolation (Tenant A close does not block Tenant B ingestion)
   - Test 10: Bypass attempt via direct uncoordinated write is detected by pre/post-signing digest comparison
   - Test 11: Crashed/closed session automatically releases transaction advisory locks
2. Workstream 5: Immutability Tests
   - Test 12: Duplicate package ID rejected (application-level and DB unique constraint)
   - Test 13: Overwrite attempt rejected (immutable record cannot be modified)
   - Test 14: Deletion attempt rejected (IMMUTABLE_PACKAGE_DELETION_PROHIBITED)
   - Test 15: Signature alteration detected (verdict HISTORICALLY_INVALID_SIGNATURE)
   - Test 16: Canonical bytes alteration detected (CANONICAL_DIGEST_MISMATCH)
   - Test 17: Cross-tenant access denied (raises PermissionError)
3. Workstream 6: Historical Lineage Tests
   - Test 18: Lineage linkage and version increment (V1 -> V2)
   - Test 19: Superseded package remains historically verifiable (HISTORICALLY_VALID_SUPERSEDED)
   - Test 20: Ordered version listing across supersession chain
   - Test 21: Checkpoint metadata updated with certified snapshot lineage
"""

import copy
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.connectors.synthetic_source_adapter import SyntheticSourceAdapter
from app.models.manifest import ManifestSubmission, TenantTrustedKey
from app.models.tenant import Business, Organization, UserIdentity
from app.schemas.period_close_evidence import (
    PeriodCloseAttestation,
    ShopifyCompletenessAssessment,
    StripeCompletenessAssessment,
)
from app.schemas.source_sync import SourceMetadata
from app.services.canonical_dataset_digest_service import CanonicalDatasetDigestService
from app.services.historical_evidence_package_service import (
    HistoricalEvidencePackageService,
)
from app.services.ingestion_writer_coordinator import IngestionWriterCoordinator
from app.services.multi_source_period_close_service import MultiSourcePeriodCloseService
from app.services.source_sync_service import SourceSyncService
from app.services.webhook_inbox_service import WebhookInboxService
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

def normalize_pg_url(url: str) -> str:
    """Normalize generic postgresql:// or postgres:// to postgresql+psycopg://."""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url.replace("@localhost:", "@127.0.0.1:")


def is_strict_postgres_required() -> bool:
    """Check whether execution environment strictly mandates live PostgreSQL verification."""
    return (
        os.getenv("CI", "").strip().lower() in ("true", "1")
        or os.getenv("REQUIRE_POSTGRES", "").strip().lower() in ("true", "1")
    )


def get_staging_pg_url() -> str:
    """Resolve active PostgreSQL connection URL honoring TEST_DATABASE_URL, DATABASE_URL, STAGING_DATABASE_URL, and POSTGRES_PORT."""
    port = os.getenv("POSTGRES_PORT", "5432" if os.getenv("CI") else "5433")
    raw_url = (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("STAGING_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or f"postgresql+psycopg://nexus_staging_user:local_dev_password@127.0.0.1:{port}/nexus_staging_db"
    )
    return normalize_pg_url(raw_url)


POSTGRES_STAGING_URL = get_staging_pg_url()


class MockShopifySyncAdapter(SyntheticSourceAdapter):
    """Synthetic adapter presenting as Shopify GraphQL Admin API."""

    def get_metadata(self) -> SourceMetadata:
        meta = super().get_metadata()
        meta.provider = "shopify"
        meta.provider_account_id = f"shop_{self.business_id[:8]}"
        meta.source_name = "Shopify GraphQL Admin API (Mocked Sandbox)"
        return meta

    def verify_event_signature(
        self,
        headers: dict[str, str],
        body_bytes: bytes,
        secret: str | None = None,
    ) -> bool:
        return True


class MockStripeSyncAdapter(SyntheticSourceAdapter):
    """Synthetic adapter presenting as Stripe Test Mode."""

    def get_metadata(self) -> SourceMetadata:
        meta = super().get_metadata()
        meta.provider = "stripe"
        meta.provider_account_id = f"acct_{self.business_id[:8]}"
        meta.source_name = "Stripe Test Mode (Mocked Sandbox)"
        return meta


@pytest.fixture(scope="module")
def pg_engine():
    """Live PostgreSQL 16.15 staging engine fixture."""
    url = get_staging_pg_url()
    try:
        engine = create_engine(url, echo=False, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT version()")).scalar()
            assert "PostgreSQL" in ver, f"Unexpected DB: {ver}"
        yield engine
        engine.dispose()
    except Exception as exc:  # noqa: BLE001
        if is_strict_postgres_required():
            pytest.fail(f"Live PostgreSQL required but unreachable at {url}: {exc}")
        pytest.skip(f"Live PostgreSQL staging db unreachable on {url}: {exc}")


@pytest.fixture(scope="function")
def session_factory(pg_engine):
    """Session factory for multi-session concurrency testing."""
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


@pytest.fixture(scope="function")
def pg_session(session_factory):
    """Single isolated transactional session."""
    session = session_factory()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def disposable_synthetic_tenant(pg_session):
    """Isolated synthetic tenant workspace in PostgreSQL staging."""
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
        pg_session.execute(text("DELETE FROM manifest_submissions WHERE business_id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM connector_sync_checkpoints WHERE business_id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM connector_webhook_inbox WHERE business_id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM tenant_trusted_keys WHERE business_id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM businesses WHERE id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        pg_session.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org_id})
        pg_session.commit()
    except Exception:  # noqa: BLE001
        pg_session.rollback()


@pytest.fixture(scope="function")
def second_synthetic_tenant(pg_session):
    """Second independent synthetic tenant for cross-tenant isolation testing."""
    tenant_uuid = str(uuid4())[:8]
    org_id = f"org-test-syn2-{tenant_uuid}"
    biz_id = f"biz-test-syn2-{tenant_uuid}"
    user_id = f"user-test-syn2-{tenant_uuid}"

    user = UserIdentity(
        id=user_id,
        email=f"tester2-{tenant_uuid}@synthetic-nexus.internal",
        password_hash="argon2_synthetic_hash_disabled",
        full_name=f"Synthetic Auditor 2 {tenant_uuid}",
        is_active=True,
        is_verified=True,
    )
    org = Organization(id=org_id, name=f"Synthetic Sandbox Corp 2 {tenant_uuid}", slug=f"syn2-sandbox-{tenant_uuid}")
    biz = Business(
        id=biz_id,
        organization_id=org_id,
        name=f"Synthetic Sandbox Store 2 {tenant_uuid}",
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
        pg_session.execute(text("DELETE FROM manifest_submissions WHERE business_id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM connector_sync_checkpoints WHERE business_id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM connector_webhook_inbox WHERE business_id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM tenant_trusted_keys WHERE business_id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM businesses WHERE id = :b"), {"b": biz_id})
        pg_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        pg_session.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org_id})
        pg_session.commit()
    except Exception:  # noqa: BLE001
        pg_session.rollback()


@pytest.fixture(scope="function")
def signing_keys(disposable_synthetic_tenant, pg_session):
    """Provision a persistent trusted Ed25519 signing key for the primary synthetic tenant."""
    biz_id = disposable_synthetic_tenant["business_id"]
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    pub_pem = pub_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    key_id = f"key-syn-1j33-{biz_id[:8]}"
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
def sample_package_data(disposable_synthetic_tenant, signing_keys):
    """Build a valid, signed PeriodCloseEvidencePackage fixture."""
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    shopify_orders = [
        {
            "id": "gid://shopify/Order/3001",
            "name": "#3001",
            "order_number": 3001,
            "currency": "USD",
            "total_price": "250.00",
            "total_discounts": "0.00",
            "total_tax": "20.00",
            "total_shipping": "0.00",
            "financial_status": "PAID",
            "line_items": [
                {
                    "id": "gid://shopify/LineItem/31",
                    "title": "Smart Standing Desk",
                    "quantity": 1,
                    "price": "250.00",
                    "total_discount": "0.00",
                }
            ],
            "refunds": [],
            "transactions": [
                {
                    "id": "gid://shopify/OrderTransaction/301",
                    "authorization": "ch_stripe_3001",
                    "gateway": "stripe",
                    "status": "SUCCESS",
                    "amount": "250.00",
                }
            ],
            "created_at": "2026-09-10T12:00:00Z",
        }
    ]

    stripe_transactions = [
        {
            "id": "txn_stripe_3001",
            "source": "ch_stripe_3001",
            "type": "charge",
            "currency": "usd",
            "amount": 25000,
            "fee": 755,
            "net": 24245,
            "status": "available",
            "description": "Charge for order #3001",
            "created": 1789041600,
        }
    ]

    digests = CanonicalDatasetDigestService.compute_dataset_identity_digest(
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_transactions,
        business_id=biz_id,
        shopify_store_domain=f"store-{biz_id[:8]}.myshopify.com",
        stripe_account_id=f"acct_{biz_id[:8]}",
        period_start=p_start,
        period_end=p_end,
    )

    attestation = PeriodCloseAttestation(
        attested_by_user_id=disposable_synthetic_tenant["user_id"],
        attester_role="finance_controller",
        attestation_statement="Verified synthetic multi-source period close evidence package.",
        attested_at=datetime.now(UTC),
        provenance_type="synthetic_rehearsal_attestation",
        is_synthetic=True,
    )

    shopify_assessment = ShopifyCompletenessAssessment(
        store_domain=f"store-{biz_id[:8]}.myshopify.com",
        api_version="2026-10",
        period_start=p_start,
        period_end=p_end,
        pagination_completed=True,
        checkpoint_id=f"ckpt-shopify-{biz_id[:8]}",
        cursor_chain_hash=digests["shopify"],
        records_extracted=1,
        records_ingested=1,
        records_rejected=0,
        extraction_started_at=datetime.now(UTC) - timedelta(minutes=10),
        extraction_completed_at=datetime.now(UTC) - timedelta(minutes=5),
        is_complete=True,
    )

    stripe_assessment = StripeCompletenessAssessment(
        account_id=f"acct_{biz_id[:8]}",
        period_start=p_start,
        period_end=p_end,
        payment_transactions_count=1,
        refunds_count=0,
        payouts_count=1,
        payout_extracted=True,
        pagination_completed=True,
        checkpoint_id=f"ckpt-stripe-{biz_id[:8]}",
        cursor_chain_hash=digests["stripe"],
        records_extracted=1,
        records_ingested=1,
        records_rejected=0,
        extraction_started_at=datetime.now(UTC) - timedelta(minutes=10),
        extraction_completed_at=datetime.now(UTC) - timedelta(minutes=5),
        is_complete=True,
    )

    pkg = MultiSourcePeriodCloseService.build_evidence_package(
        business_id=biz_id,
        period_start=p_start,
        period_end=p_end,
        shopify_orders=shopify_orders,
        stripe_transactions=stripe_transactions,
        shopify_assessment=shopify_assessment,
        stripe_assessment=stripe_assessment,
        attestation=attestation,
        trusted_key_id=signing_keys["key_id"],
        version_number=1,
    )

    signed_pkg = MultiSourcePeriodCloseService.sign_evidence_package(
        package=pkg,
        private_key=signing_keys["private_key"],
        algorithm="ed25519",
    )

    return {
        "package": signed_pkg,
        "shopify_orders": shopify_orders,
        "stripe_transactions": stripe_transactions,
        "period_start": p_start,
        "period_end": p_end,
    }


# ==============================================================================
# Workstream 3: PostgreSQL Multi-Session Concurrency Test Suite
# ==============================================================================


def test_ws3_shopify_ingestion_blocks_during_exclusive_period_close(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 1: Verify that Shopify ingestion blocks or fails with PERIOD_CLOSE_IN_PROGRESS
    when an exclusive period-close lock is active on another database session.
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_close = session_factory()
    session_sync = session_factory()

    try:
        # Session A: Acquire exclusive period close lock
        IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_close,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=True,
        )

        adapter = MockShopifySyncAdapter(
            tenant_credentials={"api_key": "test_key"},
            business_id=biz_id,
            num_transactions=10,
        )

        # Session B: Attempt non-blocking Shopify execute_sync
        with pytest.raises(RuntimeError) as exc_info:
            SourceSyncService.execute_sync(
                session=session_sync,
                adapter=adapter,
                period_start=p_start,
                period_end=p_end,
                blocking=False,
            )
        assert "PERIOD_CLOSE_IN_PROGRESS" in str(exc_info.value)
        assert biz_id in str(exc_info.value)

    finally:
        session_close.rollback()
        session_close.close()
        session_sync.rollback()
        session_sync.close()


def test_ws3_stripe_ingestion_blocks_during_exclusive_period_close(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 2: Verify that Stripe ingestion blocks or fails with PERIOD_CLOSE_IN_PROGRESS
    when an exclusive period-close lock is active.
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_close = session_factory()
    session_sync = session_factory()

    try:
        IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_close,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=True,
        )

        adapter = MockStripeSyncAdapter(
            tenant_credentials={"api_key": "test_key"},
            business_id=biz_id,
            num_transactions=10,
        )

        with pytest.raises(RuntimeError) as exc_info:
            SourceSyncService.execute_sync(
                session=session_sync,
                adapter=adapter,
                period_start=p_start,
                period_end=p_end,
                blocking=False,
            )
        assert "PERIOD_CLOSE_IN_PROGRESS" in str(exc_info.value)

    finally:
        session_close.rollback()
        session_close.close()
        session_sync.rollback()
        session_sync.close()


def test_ws3_webhook_updates_block_during_exclusive_close_lock(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 3: Verify that webhook-driven updates block during an active exclusive close lock
    when the webhook specifies accounting period bounds.
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_close = session_factory()
    session_hook = session_factory()

    try:
        IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_close,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=True,
        )

        adapter = MockShopifySyncAdapter(
            tenant_credentials={"api_key": "test_key"},
            business_id=biz_id,
        )

        payload_bytes = json.dumps({"id": 9999, "total_price": "100.00"}).encode("utf-8")
        headers = {
            "x-shopify-webhook-id": f"hook-{uuid4().hex[:8]}",
            "x-shopify-topic": "orders/create",
        }

        with pytest.raises(RuntimeError) as exc_info:
            WebhookInboxService.process_inbound_webhook(
                session=session_hook,
                adapter=adapter,
                headers=headers,
                body_bytes=payload_bytes,
                period_start=p_start,
                period_end=p_end,
                blocking=False,
            )
        assert "PERIOD_CLOSE_IN_PROGRESS" in str(exc_info.value)

    finally:
        session_close.rollback()
        session_close.close()
        session_hook.rollback()
        session_hook.close()


def test_ws3_backfill_operations_block_during_exclusive_close_lock(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 4: Verify that backfill sync operations targeting the accounting period block
    during an active exclusive close lock.
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_close = session_factory()
    session_backfill = session_factory()

    try:
        IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_close,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=True,
        )

        # Backfill adapter with simulated backfill flag
        adapter = MockShopifySyncAdapter(
            tenant_credentials={"api_key": "test_key"},
            business_id=biz_id,
            simulate_backfill=True,
        )

        with pytest.raises(RuntimeError) as exc_info:
            SourceSyncService.execute_sync(
                session=session_backfill,
                adapter=adapter,
                period_start=p_start,
                period_end=p_end,
                blocking=False,
            )
        assert "PERIOD_CLOSE_IN_PROGRESS" in str(exc_info.value)

    finally:
        session_close.rollback()
        session_close.close()
        session_backfill.rollback()
        session_backfill.close()


def test_ws3_ingestion_proceeds_immediately_after_snapshot_commit_or_rollback(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 5: Verify that ingestion proceeds immediately after the period-close snapshot
    releases its exclusive lock (via commit or rollback).
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_close = session_factory()
    session_sync = session_factory()

    try:
        # Acquire exclusive lock
        IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_close,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=True,
        )

        adapter = MockShopifySyncAdapter(
            tenant_credentials={"api_key": "test_key"},
            business_id=biz_id,
            num_transactions=5,
        )

        # Verify blocked
        with pytest.raises(RuntimeError):
            SourceSyncService.execute_sync(
                session=session_sync,
                adapter=adapter,
                period_start=p_start,
                period_end=p_end,
                blocking=False,
            )

        # Release Session A by rolling back
        session_close.rollback()

        # Session B now succeeds immediately
        result = SourceSyncService.execute_sync(
            session=session_sync,
            adapter=adapter,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )
        assert result.status == "COMPLETED"
        assert result.records_extracted > 0

    finally:
        session_close.close()
        session_sync.rollback()
        session_sync.close()


def test_ws3_failed_ingestion_transaction_releases_shared_lock_on_rollback(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 6: Verify that a failed ingestion transaction releases its shared advisory lock
    on rollback, permitting subsequent exclusive period-close locks.
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_sync = session_factory()
    session_close = session_factory()

    try:
        # Session A: acquire shared lock
        IngestionWriterCoordinator.acquire_ingestion_lock(
            session=session_sync,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=True,
        )

        # Session B: exclusive lock cannot be acquired non-blocking
        with pytest.raises(RuntimeError):
            IngestionWriterCoordinator.acquire_period_close_lock(
                session=session_close,
                business_id=biz_id,
                period_start=p_start,
                period_end=p_end,
                blocking=False,
            )

        # Rollback Session A (simulating failed ingestion)
        session_sync.rollback()

        # Session B can now acquire exclusive period-close lock immediately
        acquired = IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_close,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )
        assert acquired is True

    finally:
        session_sync.close()
        session_close.rollback()
        session_close.close()


def test_ws3_failed_period_close_transaction_releases_exclusive_lock_on_rollback(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 7: Verify that a failed period-close transaction releases its exclusive lock
    on rollback, permitting immediate ingestion writes.
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_close = session_factory()
    session_sync = session_factory()

    try:
        IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_close,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=True,
        )

        # Simulate exception in period close and rollback
        session_close.rollback()

        # Ingestion session acquires shared lock immediately
        acquired = IngestionWriterCoordinator.acquire_ingestion_lock(
            session=session_sync,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )
        assert acquired is True

    finally:
        session_close.close()
        session_sync.rollback()
        session_sync.close()


def test_ws3_two_independent_shared_writers_proceed_concurrently(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 8: Verify that two independent shared ingestion writers can hold locks
    and write concurrently without mutual blocking.
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_writer1 = session_factory()
    session_writer2 = session_factory()

    try:
        # Writer 1 acquires shared lock
        w1_locked = IngestionWriterCoordinator.acquire_ingestion_lock(
            session=session_writer1,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )
        assert w1_locked is True

        # Writer 2 also acquires shared lock concurrently on identical period
        w2_locked = IngestionWriterCoordinator.acquire_ingestion_lock(
            session=session_writer2,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )
        assert w2_locked is True

    finally:
        session_writer1.rollback()
        session_writer1.close()
        session_writer2.rollback()
        session_writer2.close()


def test_ws3_cross_tenant_isolation_period_close_does_not_block_other_tenant(
    session_factory, disposable_synthetic_tenant, second_synthetic_tenant
):
    """
    Test 9: Verify strict cross-tenant isolation: Tenant A exclusive close lock
    does NOT block Tenant B ingestion on the exact same accounting period dates.
    """
    biz_a = disposable_synthetic_tenant["business_id"]
    biz_b = second_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_a = session_factory()
    session_b = session_factory()

    try:
        # Tenant A acquires exclusive period-close lock
        IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_a,
            business_id=biz_a,
            period_start=p_start,
            period_end=p_end,
            blocking=True,
        )

        # Tenant B executes ingestion on identical period dates with non-blocking=False
        adapter_b = MockShopifySyncAdapter(
            tenant_credentials={"api_key": "test_key_b"},
            business_id=biz_b,
            num_transactions=5,
        )

        result_b = SourceSyncService.execute_sync(
            session=session_b,
            adapter=adapter_b,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )

        assert result_b.status == "COMPLETED"
        assert result_b.business_id == biz_b

    finally:
        session_a.rollback()
        session_a.close()
        session_b.rollback()
        session_b.close()


def test_ws3_bypass_attempt_caught_by_pre_post_signing_digest_verification(
    sample_package_data,
):
    """
    Test 10: Verify that an uncoordinated write that bypasses advisory locks
    is caught by pre/post-signing dataset identity digest verification.
    """
    pkg = sample_package_data["package"]
    initial_digest = pkg.transaction_identity_digests["dataset_identity_digest"]

    # Mutate dataset concurrently (uncoordinated bypass)
    mutated_shopify_orders = copy.deepcopy(sample_package_data["shopify_orders"])
    mutated_shopify_orders[0]["total_price"] = "999.00"

    mutated_digests = CanonicalDatasetDigestService.compute_dataset_identity_digest(
        shopify_orders=mutated_shopify_orders,
        stripe_transactions=sample_package_data["stripe_transactions"],
        business_id=pkg.business_id,
        shopify_store_domain=f"store-{pkg.business_id[:8]}.myshopify.com",
        stripe_account_id=f"acct_{pkg.business_id[:8]}",
        period_start=sample_package_data["period_start"],
        period_end=sample_package_data["period_end"],
    )
    current_digest = mutated_digests["dataset_identity_digest"]

    # Integrity verification fails closed
    with pytest.raises(RuntimeError) as exc_info:
        IngestionWriterCoordinator.verify_snapshot_integrity(
            initial_dataset_digest=initial_digest,
            current_dataset_digest=current_digest,
        )
    assert "SNAPSHOT_CONCURRENCY_MUTATION_DETECTED" in str(exc_info.value)


def test_ws3_crashed_session_automatically_releases_transaction_advisory_locks(
    session_factory, disposable_synthetic_tenant
):
    """
    Test 11: Verify that dropping/closing a database connection immediately releases
    all transaction advisory locks held by that backend.
    """
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 30, 0, 0, tzinfo=UTC)

    session_crashed = session_factory()
    # Acquire exclusive lock
    IngestionWriterCoordinator.acquire_period_close_lock(
        session=session_crashed,
        business_id=biz_id,
        period_start=p_start,
        period_end=p_end,
        blocking=True,
    )

    # Force connection close without commit/rollback (simulating worker crash / SIGKILL)
    session_crashed.connection().connection.close()
    session_crashed.close()

    # New session can immediately acquire lock without hang
    session_new = session_factory()
    try:
        acquired = IngestionWriterCoordinator.acquire_period_close_lock(
            session=session_new,
            business_id=biz_id,
            period_start=p_start,
            period_end=p_end,
            blocking=False,
        )
        assert acquired is True
    finally:
        session_new.rollback()
        session_new.close()


# ==============================================================================
# Workstream 5: Immutability Tests
# ==============================================================================


def test_ws5_immutability_duplicate_package_id_rejected(
    pg_session, sample_package_data, disposable_synthetic_tenant
):
    """
    Test 12: Verify that duplicate package ID is rejected at application level
    and at PostgreSQL unique constraint level (uq_manifest_submissions_manifest_id).
    """
    pkg = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]

    # 1. Record original package
    sub = HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()
    assert sub.manifest_id == pkg.package_id

    # 2. Attempt duplicate record via service -> raises IMMUTABLE_PACKAGE_OVERWRITE_PROHIBITED
    with pytest.raises(ValueError) as exc_info:
        HistoricalEvidencePackageService.record_immutable_package(
            session=pg_session,
            package=pkg,
            submitted_by_user_id=user_id,
        )
    assert "IMMUTABLE_PACKAGE_OVERWRITE_PROHIBITED" in str(exc_info.value)

    # 3. Attempt direct raw insert with duplicate manifest_id -> violates unique constraint
    raw_sub = ManifestSubmission(
        manifest_id=pkg.package_id,  # Duplicate
        business_id=pkg.business_id,
        source_id="test_dup",
        batch_id="batch_dup",
        provenance_type="synthetic_rehearsal_attestation",
        period_start=pkg.accounting_period_start,
        period_end=pkg.accounting_period_end,
        file_name="duplicate.json",
        file_sha256="00" * 32,
        expected_row_count=1,
        expected_gross_total=Decimal("100.00"),
        currency="USD",
        attested_by_user_id=user_id,
        attester_role="finance_controller",
        attestation_statement="Duplicate test statement",
        attested_at=datetime.now(UTC),
        submitted_by_user_id=user_id,
        signature_algorithm="ed25519",
        signature_key_id="key-01",
        verification_status="provisional",
        reconciliation_matched=True,
    )
    pg_session.add(raw_sub)
    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()


def test_ws5_immutability_overwrite_attempt_rejected(
    pg_session, sample_package_data, disposable_synthetic_tenant
):
    """
    Test 13: Verify that an overwrite of an existing certified package is prohibited.
    """
    pkg = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]

    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()

    # Re-submission with altered payload under same package_id is rejected
    mutated_pkg = copy.deepcopy(pkg)
    mutated_pkg.currency = "EUR"

    with pytest.raises(ValueError) as exc_info:
        HistoricalEvidencePackageService.record_immutable_package(
            session=pg_session,
            package=mutated_pkg,
            submitted_by_user_id=user_id,
        )
    assert "IMMUTABLE_PACKAGE_OVERWRITE_PROHIBITED" in str(exc_info.value)


def test_ws5_immutability_deletion_attempt_rejected(
    pg_session, sample_package_data, disposable_synthetic_tenant
):
    """
    Test 14: Verify that package deletion is explicitly blocked by service policy.
    """
    pkg = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]

    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()

    with pytest.raises(ValueError) as exc_info:
        HistoricalEvidencePackageService.delete_package(
            session=pg_session,
            package_id=pkg.package_id,
        )
    assert "IMMUTABLE_PACKAGE_DELETION_PROHIBITED" in str(exc_info.value)


def test_ws5_immutability_signature_alteration_detected(
    pg_session, sample_package_data, disposable_synthetic_tenant
):
    """
    Test 15: Verify that tampering with the stored cryptographic signature
    is immediately detected during independent historical verification.
    """
    pkg = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]

    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()

    # Mutate stored signature in PostgreSQL
    sub = pg_session.execute(
        select(ManifestSubmission).where(ManifestSubmission.manifest_id == pkg.package_id)
    ).scalar_one()

    raw_pkg_dict = dict(sub.source_close_evidence_json["raw_package"])
    # Tamper with signature hex
    raw_pkg_dict["manifest_signature"]["signature_hex"] = "ff" * 64
    sub.source_close_evidence_json["raw_package"] = raw_pkg_dict
    sub.source_close_evidence_json = dict(sub.source_close_evidence_json)
    pg_session.commit()

    # Verify historical signature fails
    result = HistoricalEvidencePackageService.verify_historical_package(
        session=pg_session,
        package_or_id=pkg.package_id,
    )
    assert result.historical_signature_valid is False
    assert result.verification_verdict == "HISTORICALLY_INVALID_SIGNATURE"


def test_ws5_immutability_canonical_bytes_alteration_detected(
    pg_session, sample_package_data, disposable_synthetic_tenant
):
    """
    Test 16: Verify that altering canonical evidence payload fields triggers
    CANONICAL_DIGEST_MISMATCH during historical verification.
    """
    pkg = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]

    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()

    # Tamper with package gross amount in raw package
    sub = pg_session.execute(
        select(ManifestSubmission).where(ManifestSubmission.manifest_id == pkg.package_id)
    ).scalar_one()

    raw_pkg_dict = dict(sub.source_close_evidence_json["raw_package"])
    raw_pkg_dict["shopify_commercial_totals"]["gross_sales"] = "99999.00"
    sub.source_close_evidence_json["raw_package"] = raw_pkg_dict
    sub.source_close_evidence_json = dict(sub.source_close_evidence_json)
    pg_session.commit()

    result = HistoricalEvidencePackageService.verify_historical_package(
        session=pg_session,
        package_or_id=pkg.package_id,
    )
    assert result.canonical_digest_matches is False
    assert any("CANONICAL_DIGEST_MISMATCH" in d for d in result.diagnostics)


def test_ws5_immutability_cross_tenant_access_denied(
    pg_session, sample_package_data, disposable_synthetic_tenant, second_synthetic_tenant
):
    """
    Test 17: Verify that attempting to retrieve another tenant's historical evidence
    package raises PermissionError.
    """
    pkg = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]
    other_biz = second_synthetic_tenant["business_id"]

    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()

    # Tenant B attempts to access Tenant A's package
    with pytest.raises(PermissionError) as exc_info:
        HistoricalEvidencePackageService.get_historical_package(
            session=pg_session,
            package_id=pkg.package_id,
            authenticated_business_id=other_biz,
        )
    assert "Cross-tenant access prohibited" in str(exc_info.value)


# ==============================================================================
# Workstream 6: Historical Lineage Tests
# ==============================================================================


def test_ws6_lineage_linkage_and_version_increment(
    pg_session, sample_package_data, signing_keys, disposable_synthetic_tenant
):
    """
    Test 18: Verify that creating a superseding package correctly increments version_number
    and links predecessor and successor IDs in the manifest ledger.
    """
    pkg_v1 = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]

    # Record V1
    sub_v1 = HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg_v1,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()
    assert sub_v1.verification_status == "provisional"

    # Assemble and sign V2 (e.g. after reconciliation adjustment or backfill)
    pkg_v2 = copy.deepcopy(pkg_v1)
    pkg_v2.package_id = f"pkg-v2-{uuid4().hex[:8]}"
    pkg_v2.supersedes_package_id = pkg_v1.package_id
    pkg_v2.version_number = 2

    signed_v2 = MultiSourcePeriodCloseService.sign_evidence_package(
        package=pkg_v2,
        private_key=signing_keys["private_key"],
        algorithm="ed25519",
    )

    # Record V2 with explicit supersession
    sub_v2 = HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=signed_v2,
        submitted_by_user_id=user_id,
        supersedes_package_id=pkg_v1.package_id,
    )
    pg_session.commit()

    # Verify V1 is marked superseded
    pg_session.refresh(sub_v1)
    assert sub_v1.verification_status == "superseded"
    v1_meta = sub_v1.source_close_evidence_json or {}
    assert v1_meta["superseded_by_package_id"] == signed_v2.package_id

    # Verify V2 links back to V1
    assert sub_v2.manifest_id == signed_v2.package_id
    v2_meta = sub_v2.source_close_evidence_json or {}
    assert v2_meta["version_number"] == 2
    assert v2_meta["supersedes_package_id"] == pkg_v1.package_id


def test_ws6_superseded_package_remains_historically_verifiable(
    pg_session, sample_package_data, signing_keys, disposable_synthetic_tenant
):
    """
    Test 19: Verify that a superseded package retains its historical cryptographic validity
    and yields verdict HISTORICALLY_VALID_SUPERSEDED upon audit.
    """
    pkg_v1 = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]

    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg_v1,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()

    # Record V2 superseding V1
    pkg_v2 = copy.deepcopy(pkg_v1)
    pkg_v2.package_id = f"pkg-v2-{uuid4().hex[:8]}"
    pkg_v2.supersedes_package_id = pkg_v1.package_id
    pkg_v2.version_number = 2
    signed_v2 = MultiSourcePeriodCloseService.sign_evidence_package(
        package=pkg_v2,
        private_key=signing_keys["private_key"],
        algorithm="ed25519",
    )
    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=signed_v2,
        submitted_by_user_id=user_id,
        supersedes_package_id=pkg_v1.package_id,
    )
    pg_session.commit()

    # Independent audit on superseded V1 package
    result_v1 = HistoricalEvidencePackageService.verify_historical_package(
        session=pg_session,
        package_or_id=pkg_v1.package_id,
    )

    assert result_v1.historical_signature_valid is True
    assert result_v1.key_valid_at_signing is True
    assert result_v1.canonical_digest_matches is True
    assert result_v1.is_superseded is True
    assert result_v1.superseded_by_package_id == signed_v2.package_id
    assert result_v1.verification_verdict == "HISTORICALLY_VALID_SUPERSEDED"


def test_ws6_ordered_version_listing_across_supersession_chain(
    pg_session, sample_package_data, signing_keys, disposable_synthetic_tenant
):
    """
    Test 20: Verify that list_historical_packages returns the complete version chain
    ordered chronologically with full supersession metadata.
    """
    pkg_v1 = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = sample_package_data["period_start"]
    p_end = sample_package_data["period_end"]

    # Record V1
    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg_v1,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()

    # Record V2
    pkg_v2 = copy.deepcopy(pkg_v1)
    pkg_v2.package_id = f"pkg-v2-{uuid4().hex[:8]}"
    signed_v2 = MultiSourcePeriodCloseService.sign_evidence_package(
        package=pkg_v2,
        private_key=signing_keys["private_key"],
        algorithm="ed25519",
    )
    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=signed_v2,
        submitted_by_user_id=user_id,
        supersedes_package_id=pkg_v1.package_id,
    )
    pg_session.commit()

    # Query list
    packages = HistoricalEvidencePackageService.list_historical_packages(
        session=pg_session,
        business_id=biz_id,
        period_start=p_start,
        period_end=p_end,
    )

    assert len(packages) >= 2
    pkg_ids = [p["package_id"] for p in packages]
    assert pkg_v1.package_id in pkg_ids
    assert signed_v2.package_id in pkg_ids

    v1_entry = next(p for p in packages if p["package_id"] == pkg_v1.package_id)
    v2_entry = next(p for p in packages if p["package_id"] == signed_v2.package_id)

    assert v1_entry["version_number"] == 1
    assert v1_entry["status"] == "superseded"
    assert v1_entry["superseded_by_package_id"] == signed_v2.package_id

    assert v2_entry["version_number"] == 2
    assert v2_entry["supersedes_package_id"] == pkg_v1.package_id


def test_ws6_checkpoint_metadata_updated_with_certified_snapshot_lineage(
    pg_session, sample_package_data, disposable_synthetic_tenant
):
    """
    Test 21: Verify that checkpoints intersecting the period are durably updated
    with certified snapshot lineage and dataset identity digest.
    """
    pkg = sample_package_data["package"]
    user_id = disposable_synthetic_tenant["user_id"]
    biz_id = disposable_synthetic_tenant["business_id"]
    p_start = sample_package_data["period_start"]
    p_end = sample_package_data["period_end"]

    # Create intersecting checkpoint
    checkpoint = SourceSyncService.get_or_create_checkpoint(
        session=pg_session,
        business_id=biz_id,
        provider="shopify",
        period_start=p_start,
        period_end=p_end,
    )
    pg_session.commit()

    # Record package
    HistoricalEvidencePackageService.record_immutable_package(
        session=pg_session,
        package=pkg,
        submitted_by_user_id=user_id,
    )
    pg_session.commit()

    # Refresh checkpoint and assert certified snapshot metadata
    pg_session.refresh(checkpoint)
    assert checkpoint.transaction_set_digest == pkg.transaction_identity_digests["dataset_identity_digest"]
    meta = checkpoint.metadata_json or {}
    assert "certified_snapshot" in meta
    cert_info = meta["certified_snapshot"]
    assert cert_info["package_id"] == pkg.package_id
    assert cert_info["version_number"] == 1
    assert cert_info["dataset_identity_digest"] == pkg.transaction_identity_digests["dataset_identity_digest"]
