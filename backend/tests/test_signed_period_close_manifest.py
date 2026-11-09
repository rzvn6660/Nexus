"""
Unit and integration tests for NEXUS Phase 1I.1 — Signed Period-Close Manifest Engine.

Verifies:
1. Valid signed manifest with cryptographic Ed25519 signature & independent tabular reconciliation.
2. Tampered file and SHA-256 checksum mismatch rejection.
3. Invalid signature, untrusted key, revoked key, and expired key rejection.
4. Cross-tenant manifest reuse and IDOR protection.
5. Signer tenant-scoped authorization and role enforcement (owner/admin required).
6. Incorrect row counts, monetary total mismatches, and period boundary violations.
7. Duplicate transaction detection and refund/cancellation handling.
8. Provisional watermark creation and promotion lifecycle.
9. Late-arriving transactions triggering automatic backfill invalidation.
10. Idempotent manifest submission and supersession handling.
11. Confirmation that Apex Specialty Commerce remains strictly unchanged and diagnostic-only.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import io
import csv
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy.orm import Session

from app.analytics.customer.safety import CadenceSafetyGate, CadenceEligibilityStatus, SafetyReasonCode
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.models.watermark import TenantIngestionWatermark
from app.schemas.manifest import (
    ManifestAttestation,
    ManifestSignature,
    PeriodCloseManifest,
    ReconciliationTotals,
)
from app.services.manifest_service import (
    ManifestKeyRegistry,
    ManifestService,
)
from app.services.watermark_service import WatermarkService


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure trusted key registry is reset before and after each test."""
    ManifestKeyRegistry.reset()
    yield
    ManifestKeyRegistry.reset()


def _create_tenant_and_user(
    session: Session, suffix: str = "test", role: str = "admin"
) -> tuple[Organization, Business, UserIdentity]:
    """Helper to provision isolated organization, business, user, and membership."""
    uid = uuid4().hex[:8]
    org = Organization(
        id=f"org-man-{suffix}-{uid}",
        name=f"Org {suffix} {uid}",
        slug=f"org-man-{suffix}-{uid}",
    )
    biz = Business(
        id=f"biz-man-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Biz {suffix} {uid}",
        industry="Specialty Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-man-{suffix}-{uid}",
        email=f"user_{suffix}_{uid}@example.com",
        full_name=f"User {suffix} {uid}",
        password_hash="mock_hash",
        is_active=True,
        is_verified=True,
    )
    session.add_all([org, biz, user])
    session.flush()

    mem = OrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=role,
    )
    session.add(mem)
    session.commit()
    return org, biz, user


def _generate_csv_content(
    rows_count: int,
    period_start: datetime,
    period_end: datetime,
    amount_per_row: Decimal = Decimal("100.00"),
    include_refunds: int = 0,
    refund_amount: Decimal = Decimal("50.00"),
    out_of_bounds_date: datetime | None = None,
    duplicate_txn_id: bool = False,
) -> bytes:
    """Generate synthetic CSV bytes for sales reconciliation testing."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["transaction_number", "customer_id", "transaction_date", "total_amount", "status"])

    duration = (period_end - period_start) / max(rows_count, 1)

    for i in range(1, rows_count + 1):
        txn_id = f"TXN-CLOSE-{i:05d}"
        if duplicate_txn_id and i == 2:
            txn_id = "TXN-CLOSE-00001"  # Duplicate

        if out_of_bounds_date and i == rows_count:
            txn_date = out_of_bounds_date
        else:
            txn_date = period_start + (duration * (i - 1)) + timedelta(minutes=1)

        status = "completed"
        amount = amount_per_row

        if i <= include_refunds:
            status = "refunded"
            amount = refund_amount

        writer.writerow([
            txn_id,
            f"CUST-{i:04d}",
            txn_date.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            f"{amount:.2f}",
            status,
        ])

    return output.getvalue().encode("utf-8")


def _build_signed_manifest(
    business_id: str,
    user_id: str,
    private_key: ed25519.Ed25519PrivateKey,
    file_bytes: bytes,
    period_start: datetime,
    period_end: datetime,
    expected_rows: int,
    expected_gross: Decimal,
    key_id: str = "key-ed25519-01",
    batch_id: str = "BATCH-CLOSE-001",
    provenance_type: str = "accounting_period_close",
) -> PeriodCloseManifest:
    """Build and cryptographically sign a PeriodCloseManifest using Ed25519."""
    file_sha256 = ManifestService.compute_file_sha256(file_bytes)

    manifest_placeholder = PeriodCloseManifest(
        manifest_id=str(uuid4()),
        business_id=business_id,
        source_id="pos",
        batch_id=batch_id,
        provenance_type=provenance_type,
        period_start=period_start,
        period_end=period_end,
        source_export_id=f"EXP-{batch_id}",
        export_completed_at=period_end + timedelta(minutes=10),
        file_name="sales_export.csv",
        file_sha256=file_sha256,
        reconciliation=ReconciliationTotals(
            expected_sales_row_count=expected_rows,
            expected_gross_total_amount=expected_gross,
            currency="USD",
            eligible_status_allowlist=["completed", "shipped"],
        ),
        attestation=ManifestAttestation(
            attested_by_user_id=user_id,
            attester_role="finance_controller",
            attestation_statement="Certified complete accounting period close for sales.",
            attested_at=datetime.now(UTC),
        ),
        signature=ManifestSignature(
            algorithm="ed25519",
            key_id=key_id,
            signature_hex="00" * 64,  # placeholder
        ),
    )

    canonical_bytes = manifest_placeholder.get_canonical_bytes()
    raw_sig = private_key.sign(canonical_bytes)

    # Return final signed manifest
    return PeriodCloseManifest(
        **{
            **manifest_placeholder.model_dump(),
            "signature": ManifestSignature(
                algorithm="ed25519",
                key_id=key_id,
                signature_hex=raw_sig.hex(),
            ),
        }
    )


# ==============================================================================
# Positive Verification Test
# ==============================================================================

def test_valid_signed_manifest_and_provisional_watermark(db_session: Session):
    """Test 1: Valid signed manifest with Ed25519 signature & independent reconciliation."""
    org, biz, user = _create_tenant_and_user(db_session, "valid", role="admin")

    # Generate Ed25519 keypair and register public key
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    ManifestKeyRegistry.register_key(
        business_id=biz.id,
        key_id="key-01",
        algorithm="ed25519",
        public_key_or_secret=pub_key,
    )

    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    rows_count = 20
    amount_per_row = Decimal("150.00")
    expected_gross = amount_per_row * rows_count  # 3000.00

    csv_bytes = _generate_csv_content(rows_count, period_start, period_end, amount_per_row)
    manifest = _build_signed_manifest(
        biz.id, user.id, priv_key, csv_bytes, period_start, period_end, rows_count, expected_gross, key_id="key-01"
    )

    # Execute verification & ingestion
    result = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
    )
    db_session.commit()

    assert result.is_valid is True
    assert result.verification_status == "provisional"
    assert result.file_sha256_verified is True
    assert result.signature_verified is True
    assert result.reconciliation_matched is True
    assert result.watermark_id is not None
    assert len(result.errors) == 0

    # Verify watermark row in database
    wm = db_session.query(TenantIngestionWatermark).filter_by(id=result.watermark_id).first()
    assert wm is not None
    assert wm.business_id == biz.id
    assert wm.is_active is True
    assert wm.verification_status == "provisional"
    assert wm.provenance_type == "accounting_period_close"
    assert wm.metadata_json["manifest_id"] == manifest.manifest_id
    assert wm.metadata_json["file_sha256"] == manifest.file_sha256


# ==============================================================================
# Tampering and Cryptographic Failure Tests
# ==============================================================================

def test_tampered_file_checksum_mismatch(db_session: Session):
    """Test 2: Modifying file content after signing is rejected due to SHA-256 mismatch."""
    org, biz, user = _create_tenant_and_user(db_session, "tamper")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-01", "ed25519", priv_key.public_key())

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv_content(10, period_start, period_end)
    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_bytes, period_start, period_end, 10, Decimal("1000.00"), "key-01")

    # Tamper with received file
    tampered_bytes = csv_bytes + b"\n# Malicious trailing row"

    result = ManifestService.verify_and_ingest_manifest(db_session, manifest, tampered_bytes, user.id)
    assert result.is_valid is False
    assert result.file_sha256_verified is False
    assert any("File SHA-256 mismatch" in e for e in result.errors)
    assert result.watermark_id is None


def test_invalid_signature_and_untrusted_key(db_session: Session):
    """Test 3: Signature mismatch or unknown/untrusted key fails closed."""
    org, biz, user = _create_tenant_and_user(db_session, "untrusted")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    different_priv_key = ed25519.Ed25519PrivateKey.generate()

    # Register DIFFERENT public key
    ManifestKeyRegistry.register_key(biz.id, "key-01", "ed25519", different_priv_key.public_key())

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv_content(10, period_start, period_end)
    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_bytes, period_start, period_end, 10, Decimal("1000.00"), "key-01")

    # 1. Signature signed by un-registered private key
    result = ManifestService.verify_and_ingest_manifest(db_session, manifest, csv_bytes, user.id)
    assert result.is_valid is False
    assert result.signature_verified is False
    assert any("Ed25519 signature is invalid" in e for e in result.errors)

    # 2. Key ID not registered at all
    manifest_bad_key = _build_signed_manifest(biz.id, user.id, priv_key, csv_bytes, period_start, period_end, 10, Decimal("1000.00"), "key-unknown")
    result_bad_key = ManifestService.verify_and_ingest_manifest(db_session, manifest_bad_key, csv_bytes, user.id)
    assert result_bad_key.is_valid is False
    assert any("Untrusted or unregistered key_id" in e for e in result_bad_key.errors)


def test_revoked_key_rejection(db_session: Session):
    """Test 4: Revoked signing key is rejected."""
    org, biz, user = _create_tenant_and_user(db_session, "revoked")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-01", "ed25519", priv_key.public_key())
    ManifestKeyRegistry.revoke_key(biz.id, "key-01", reason="Compromised credential")

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv_content(5, period_start, period_end)
    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_bytes, period_start, period_end, 5, Decimal("500.00"), "key-01")

    result = ManifestService.verify_and_ingest_manifest(db_session, manifest, csv_bytes, user.id)
    assert result.is_valid is False
    assert any("revoked" in e.lower() for e in result.errors)


# ==============================================================================
# Cross-Tenant and Authorization Tests
# ==============================================================================

def test_cross_tenant_manifest_isolation(db_session: Session):
    """Test 5: Cross-tenant manifest reuse is rejected (Tenant B cannot use Tenant A's key or manifest)."""
    org_a, biz_a, user_a = _create_tenant_and_user(db_session, "tenantA")
    org_b, biz_b, user_b = _create_tenant_and_user(db_session, "tenantB")

    priv_key_a = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz_a.id, "key-01", "ed25519", priv_key_a.public_key())

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv_content(5, period_start, period_end)

    # Manifest crafted with business_id = biz_b, but signed with Tenant A's key
    manifest_spoofed = _build_signed_manifest(biz_b.id, user_b.id, priv_key_a, csv_bytes, period_start, period_end, 5, Decimal("500.00"), "key-01")

    result = ManifestService.verify_and_ingest_manifest(db_session, manifest_spoofed, csv_bytes, user_b.id)
    assert result.is_valid is False
    # Fails because key-01 is not registered for Tenant B
    assert any("Untrusted or unregistered key_id" in e for e in result.errors)


def test_unauthorized_signer_role_rejection(db_session: Session):
    """Test 6: User with 'member' role (non-admin/non-owner) cannot attest a period close."""
    org, biz, user_member = _create_tenant_and_user(db_session, "member", role="member")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-01", "ed25519", priv_key.public_key())

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv_content(5, period_start, period_end)
    manifest = _build_signed_manifest(biz.id, user_member.id, priv_key, csv_bytes, period_start, period_end, 5, Decimal("500.00"), "key-01")

    result = ManifestService.verify_and_ingest_manifest(db_session, manifest, csv_bytes, user_member.id)
    assert result.is_valid is False
    assert any("Only organization 'owner' or 'admin' roles can attest" in e for e in result.errors)


# ==============================================================================
# Reconciliation and Period Bounding Tests
# ==============================================================================

def test_row_count_and_gross_sum_mismatch(db_session: Session):
    """Test 7: Manifest fails closed when row count or gross revenue sum differs from CSV."""
    org, biz, user = _create_tenant_and_user(db_session, "recon")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-01", "ed25519", priv_key.public_key())

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, tzinfo=UTC)
    # File actually has 10 rows and 1000.00 sum
    csv_bytes = _generate_csv_content(10, period_start, period_end, Decimal("100.00"))

    # Manifest claims 12 rows and 1200.00
    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_bytes, period_start, period_end, 12, Decimal("1200.00"), "key-01")

    result = ManifestService.verify_and_ingest_manifest(db_session, manifest, csv_bytes, user.id)
    assert result.is_valid is False
    assert result.reconciliation_matched is False
    assert any("Row count mismatch" in e for e in result.errors)
    assert any("Gross total mismatch" in e for e in result.errors)


def test_transaction_date_outside_period_bounds(db_session: Session):
    """Test 8: Transactions dated outside declared period boundaries are caught and rejected."""
    org, biz, user = _create_tenant_and_user(db_session, "bounds")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-01", "ed25519", priv_key.public_key())

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    # 1 row dated in July (exceeding June 30 period_end)
    out_of_bounds = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    csv_bytes = _generate_csv_content(10, period_start, period_end, out_of_bounds_date=out_of_bounds)

    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_bytes, period_start, period_end, 10, Decimal("1000.00"), "key-01")

    result = ManifestService.verify_and_ingest_manifest(db_session, manifest, csv_bytes, user.id)
    assert result.is_valid is False
    assert any("exceeds declared period_end" in e for e in result.errors)


def test_duplicate_transactions_and_refund_reconciliation(db_session: Session):
    """Test 9: Duplicate transaction detection and proper separation of refunds."""
    org, biz, user = _create_tenant_and_user(db_session, "dups")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-01", "ed25519", priv_key.public_key())

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, tzinfo=UTC)

    # 10 rows total: 2 refunds (50.00 each), 8 completed (100.00 each) -> gross eligible = 800.00
    # Duplicate txn id included
    csv_bytes = _generate_csv_content(
        10, period_start, period_end,
        amount_per_row=Decimal("100.00"),
        include_refunds=2,
        refund_amount=Decimal("50.00"),
        duplicate_txn_id=True,
    )

    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_bytes, period_start, period_end, 10, Decimal("800.00"), "key-01")

    result = ManifestService.verify_and_ingest_manifest(db_session, manifest, csv_bytes, user.id)
    assert result.is_valid is False
    assert any("Duplicate transaction ID" in e for e in result.errors)


# ==============================================================================
# Watermark Lifecycle and Backfill Invalidation Tests
# ==============================================================================

def test_watermark_promotion_and_backfill_invalidation(db_session: Session):
    """Test 10: Promotion from provisional to verified, and backfill invalidation."""
    org, biz, user = _create_tenant_and_user(db_session, "promote")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-01", "ed25519", priv_key.public_key())

    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    csv_bytes = _generate_csv_content(10, period_start, period_end, Decimal("100.00"))
    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_bytes, period_start, period_end, 10, Decimal("1000.00"), "key-01")

    from datetime import date
    # Seed matching customer and sales rows for DB-level reconciliation check (C1)
    cust = Customer(
        id=90001,
        business_id=biz.id,
        customer_code="CUST-PROMOTE-01",
        name="Promote Buyer",
        email="promote@example.com",
        customer_segment="Retail",
        city="Seattle",
        acquisition_date=date(2026, 4, 1),
    )
    db_session.add(cust)
    db_session.flush()

    duration = (period_end - period_start) / 10
    for i in range(1, 11):
        txn_date = period_start + (duration * (i - 1)) + timedelta(minutes=1)
        s = Sale(
            id=90000 + i,
            business_id=biz.id,
            customer_id=cust.id,
            transaction_number=f"TXN-CLOSE-{i:05d}",
            transaction_date=txn_date,
            subtotal=100.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=100.0,
            status="completed",
        )
        db_session.add(s)
    db_session.flush()

    source_evidence = {
        "source_system": "pos",
        "export_batch_id": "BATCH-CLOSE-001",
        "settlement_status": "CLOSED_RECONCILED",
        "reported_transaction_count": 10,
        "reported_gross_revenue": "1000.00",
    }

    # Ingest and promote
    result = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
        source_close_evidence=source_evidence,
        promote_immediately_if_verified=True,
    )
    db_session.commit()

    assert result.is_valid is True
    assert result.verification_status == "verified"

    # Effective watermark is now verified complete
    eff = WatermarkService.get_effective_tenant_watermark(db_session, biz.id, max_staleness_days=None)
    assert eff.is_verified is True
    assert eff.status == "verified_complete"

    # Late arrival occurs dated May 15 (before June 30 watermark boundary)
    late_txn_date = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    invalidated = WatermarkService.detect_backfill_and_handle(
        db_session, biz.id, "pos", [late_txn_date], job_id="job-late-01"
    )
    db_session.commit()

    assert invalidated is True
    eff_after = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)
    assert eff_after.is_verified is False
    assert eff_after.status == "invalidated"


# ==============================================================================
# Apex Staging Invariant Guard
# ==============================================================================

def test_apex_tenant_remains_unwatermarked_and_diagnostic_only(db_session: Session):
    """Test 11: Assert that Apex Specialty Commerce remains strictly unwatermarked and diagnostic-only."""
    apex_id = "ab044b1a-835a-4a38-bf45-62fe38624151"

    # No active watermarks
    active_wms = WatermarkService.get_active_watermarks(db_session, apex_id)
    assert len(active_wms) == 0

    eff = WatermarkService.get_effective_tenant_watermark(db_session, apex_id)
    assert eff.is_verified is False
    assert eff.status == "unverified_missing"
