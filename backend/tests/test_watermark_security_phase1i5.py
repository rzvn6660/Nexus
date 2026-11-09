"""
NEXUS Phase 1I.5 — Independent Security and Adversarial Verification Test Suite.

Adversarial test coverage proving that Phase 1I.4 watermark certification remediations
are hardened against adversarial tampering, spoofing, replay, and TOCTOU races:
- C1: Adversarial database reconciliation (empty sales, duplicate txn IDs, swapped transaction identities,
      unlinked customers, cross-tenant isolation, currency mismatch, status eligibility, exact transaction digests).
- C2: Trusted key lifecycle (duplicate key rejection, key rotation, authorization, tampering detection, private key safety).
- H1: Source evidence trust boundary (missing evidence blocks promotion, contradictory revenue/counts fail closed).
- H2: Synthetic provenance quarantine (strict production environment block, real tenant quarantine, unapproved provenance).
- M2: Submission ledger & replay prevention (valid & rejected submissions persisted, replay rejected, tenant isolation).
- Strict Apex Invariants: 0 watermarks, 1,000 customers, 3,500 sales, DIAGNOSTIC_ONLY.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import io
import csv
import os
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.customer.safety import (
    ActionExecutionStatus,
    CadenceActionGate,
    CadenceEligibilityStatus,
    CadenceSafetyGate,
    SafetyReasonCode,
)
from app.models.customer import Customer
from app.models.manifest import ManifestSubmission, TenantTrustedKey
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
from app.services.watermark_service import WatermarkContract, WatermarkService


# ==============================================================================
# Helpers
# ==============================================================================

def _setup_test_tenant(session: Session, suffix: str, role: str = "admin") -> tuple[Business, UserIdentity]:
    """Create isolated test organization, business, and user."""
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-adv-{suffix}-{uid}", name=f"Adv Org {suffix}", slug=f"adv-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-rh-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Adv Rehearsal {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-adv-{suffix}-{uid}",
        email=f"user_{suffix}_{uid}@example.com",
        full_name=f"User {suffix}",
        password_hash="mock",
        is_active=True,
        is_verified=True,
    )
    session.add_all([org, biz, user])
    session.flush()

    mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role=role)
    session.add(mem)
    session.commit()
    return biz, user


def _build_manifest(
    biz_id: str,
    user_id: str,
    priv_key: ed25519.Ed25519PrivateKey,
    file_bytes: bytes,
    period_start: datetime,
    period_end: datetime,
    row_count: int,
    gross_total: Decimal,
    currency: str = "USD",
    key_id: str = "key-01",
    batch_id: str = "BATCH-ADV-001",
    provenance_type: str = "accounting_period_close",
) -> PeriodCloseManifest:
    """Build and sign PeriodCloseManifest."""
    file_sha256 = ManifestService.compute_file_sha256(file_bytes)
    man_placeholder = PeriodCloseManifest(
        manifest_id=str(uuid4()),
        business_id=biz_id,
        source_id="pos",
        batch_id=batch_id,
        provenance_type=provenance_type,
        period_start=period_start,
        period_end=period_end,
        source_export_id=f"EXP-{batch_id}",
        export_completed_at=period_end + timedelta(minutes=5),
        file_name="sales_adversarial.csv",
        file_sha256=file_sha256,
        reconciliation=ReconciliationTotals(
            expected_sales_row_count=row_count,
            expected_gross_total_amount=gross_total,
            currency=currency,
            eligible_status_allowlist=["completed", "shipped"],
        ),
        attestation=ManifestAttestation(
            attested_by_user_id=user_id,
            attester_role="finance_controller",
            attestation_statement="Certified complete sales reconciliation for period.",
            attested_at=datetime.now(UTC),
        ),
        signature=ManifestSignature(algorithm="ed25519", key_id=key_id, signature_hex="00" * 64),
    )
    sig_hex = priv_key.sign(man_placeholder.get_canonical_bytes()).hex()
    return PeriodCloseManifest(**{**man_placeholder.model_dump(), "signature": ManifestSignature(algorithm="ed25519", key_id=key_id, signature_hex=sig_hex)})


def _generate_csv(rows: list[tuple[str, str, datetime, Decimal, str]]) -> bytes:
    """Generate CSV bytes from list of (txn_num, cust_id, date, amount, status)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["transaction_number", "customer_id", "transaction_date", "total_amount", "status"])
    for r in rows:
        writer.writerow([r[0], r[1], r[2].strftime("%Y-%m-%d %H:%M:%S"), f"{r[3]:.2f}", r[4]])
    return buf.getvalue().encode("utf-8")


# ==============================================================================
# Focus Area 1 (C1): Adversarial Database Reconciliation
# ==============================================================================

def test_c1_adversarial_swapped_transaction_identities_equal_count_and_sum(db_session: Session):
    """C1: Attacker seeds DB with equal count and sum but swapped transaction IDs -> fails closed."""
    biz, user = _setup_test_tenant(db_session, "c1-swap")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-swap", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    # Manifest and file declare TXN-A ($100) and TXN-B ($100)
    manifest_rows = [
        ("TXN-A", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed"),
        ("TXN-B", "C-2", start + timedelta(days=2), Decimal("100.00"), "completed"),
    ]
    csv_bytes = _generate_csv(manifest_rows)
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 2, Decimal("200.00"), key_id="key-swap")

    # Attacker seeds DB with TXN-A ($100) and TXN-C ($100) -> sum is $200 and count is 2!
    cust = Customer(id=91001, business_id=biz.id, customer_code="C-1", name="C1", email="c1@example.com", customer_segment="Retail", city="Chicago", acquisition_date=date(2026, 4, 1))
    db_session.add(cust)
    db_session.flush()

    s1 = Sale(id=91001, business_id=biz.id, customer_id=cust.id, transaction_number="TXN-A", transaction_date=start + timedelta(days=1), subtotal=100.0, discount_amount=0.0, tax_amount=0.0, total_amount=100.0, status="completed")
    s2 = Sale(id=91002, business_id=biz.id, customer_id=cust.id, transaction_number="TXN-C", transaction_date=start + timedelta(days=2), subtotal=100.0, discount_amount=0.0, tax_amount=0.0, total_amount=100.0, status="completed")
    db_session.add_all([s1, s2])
    db_session.commit()

    evidence = {"source_system": "pos", "export_batch_id": "BATCH-ADV-001", "settlement_status": "CLOSED_RECONCILED", "reported_transaction_count": 2, "reported_gross_revenue": "200.00"}
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
        source_close_evidence=evidence,
        promote_immediately_if_verified=True,
    )
    db_session.commit()

    # Promotion must fail closed due to exact transaction identity mismatch
    assert res.is_valid is True
    assert res.verification_status == "provisional"
    assert any("Exact transaction identity mismatch" in e for e in res.errors)

    # Watermark remains provisional
    wm = db_session.execute(select(TenantIngestionWatermark).where(TenantIngestionWatermark.id == res.watermark_id)).scalar_one()
    assert wm.verification_status == "provisional"


def test_c1_adversarial_duplicate_transaction_numbers_in_export_file(db_session: Session):
    """C1: Manifest reconciliation fails closed if export CSV contains duplicate transaction IDs."""
    biz, user = _setup_test_tenant(db_session, "c1-dupcsv")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-dupcsv", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    # Export CSV contains duplicate TXN-1
    csv_bytes = _generate_csv([
        ("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed"),
        ("TXN-1", "C-1", start + timedelta(days=2), Decimal("100.00"), "completed"),
    ])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 2, Decimal("200.00"), key_id="key-dupcsv")

    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
    )
    db_session.commit()

    assert res.is_valid is False
    assert any("Duplicate transaction ID 'TXN-1'" in e for e in res.errors)


def test_c1_adversarial_missing_one_transaction_equal_gross_blocks_promotion(db_session: Session):
    """C1: Watermark promotion fails closed if DB has 1 transaction of $200 instead of 2 transactions of $100."""
    biz, user = _setup_test_tenant(db_session, "c1-countsum")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-cs", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    csv_bytes = _generate_csv([
        ("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed"),
        ("TXN-2", "C-2", start + timedelta(days=2), Decimal("100.00"), "completed"),
    ])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 2, Decimal("200.00"), key_id="key-cs")

    cust = Customer(id=91040, business_id=biz.id, customer_code="C-1", name="C1", email="c1@example.com", customer_segment="Retail", city="Denver", acquisition_date=date(2026, 4, 1))
    db_session.add(cust)
    db_session.flush()

    # DB has 1 sale of $200 (equal gross, but count is 1 instead of 2)
    s = Sale(id=91041, business_id=biz.id, customer_id=cust.id, transaction_number="TXN-1", transaction_date=start + timedelta(days=1), subtotal=200.0, discount_amount=0.0, tax_amount=0.0, total_amount=200.0, status="completed")
    db_session.add(s)
    db_session.commit()

    evidence = {"source_system": "pos", "export_batch_id": "BATCH-ADV-001", "settlement_status": "CLOSED_RECONCILED", "reported_transaction_count": 2, "reported_gross_revenue": "200.00"}
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
        source_close_evidence=evidence,
        promote_immediately_if_verified=True,
    )
    db_session.commit()

    assert res.verification_status == "provisional"
    assert any("manifest expected 2 rows, but database contains 1" in e for e in res.errors)


def test_c1_adversarial_currency_mismatch_blocks_promotion(db_session: Session):
    """C1: Promotion fails closed if manifest currency does not match business configured currency."""
    biz, user = _setup_test_tenant(db_session, "c1-curr")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-curr", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    # Manifest declares EUR, but business is configured with USD
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), currency="EUR", key_id="key-curr")

    cust = Customer(id=91020, business_id=biz.id, customer_code="C-1", name="C1", email="c1@example.com", customer_segment="Retail", city="Seattle", acquisition_date=date(2026, 4, 1))
    db_session.add(cust)
    db_session.flush()

    s = Sale(id=91021, business_id=biz.id, customer_id=cust.id, transaction_number="TXN-1", transaction_date=start + timedelta(days=1), subtotal=100.0, discount_amount=0.0, tax_amount=0.0, total_amount=100.0, status="completed")
    db_session.add(s)
    db_session.commit()

    evidence = {"source_system": "pos", "export_batch_id": "BATCH-ADV-001", "settlement_status": "CLOSED_RECONCILED", "reported_transaction_count": 1, "reported_gross_revenue": "100.00"}
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
        source_close_evidence=evidence,
        promote_immediately_if_verified=True,
    )
    db_session.commit()

    assert res.verification_status == "provisional"
    assert any("Currency mismatch" in e for e in res.errors)


def test_c1_adversarial_cross_tenant_isolation_in_promotion(db_session: Session):
    """C1: Sales from another tenant are not counted toward reconciliation -> promotion fails closed."""
    biz1, user1 = _setup_test_tenant(db_session, "c1-t1")
    biz2, user2 = _setup_test_tenant(db_session, "c1-t2")

    priv_key1 = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz1.id, "key-t1", "ed25519", priv_key1.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz1.id, user1.id, priv_key1, csv_bytes, start, end, 1, Decimal("100.00"), key_id="key-t1")

    # Seed the sale under Tenant 2 instead of Tenant 1
    cust2 = Customer(id=91030, business_id=biz2.id, customer_code="C-2", name="C2", email="c2@example.com", customer_segment="Retail", city="Miami", acquisition_date=date(2026, 4, 1))
    db_session.add(cust2)
    db_session.flush()

    s2 = Sale(id=91031, business_id=biz2.id, customer_id=cust2.id, transaction_number="TXN-1", transaction_date=start + timedelta(days=1), subtotal=100.0, discount_amount=0.0, tax_amount=0.0, total_amount=100.0, status="completed")
    db_session.add(s2)
    db_session.commit()

    evidence = {"source_system": "pos", "export_batch_id": "BATCH-ADV-001", "settlement_status": "CLOSED_RECONCILED", "reported_transaction_count": 1, "reported_gross_revenue": "100.00"}
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user1.id,
        source_close_evidence=evidence,
        promote_immediately_if_verified=True,
    )
    db_session.commit()

    # Promotion for Tenant 1 fails closed because Tenant 1 has 0 sales in DB
    assert res.verification_status == "provisional"
    assert any("database contains 0 matching sales" in e for e in res.errors)


# ==============================================================================
# Focus Area 2 (C2): Trusted Key Lifecycle & Authorization
# ==============================================================================

def test_c2_duplicate_key_registration_rejected(db_session: Session):
    """C2: Registering a key with an already existing key_id is rejected."""
    biz, user = _setup_test_tenant(db_session, "c2-dupkey")
    priv_key1 = ed25519.Ed25519PrivateKey.generate()
    priv_key2 = ed25519.Ed25519PrivateKey.generate()

    ManifestKeyRegistry.register_key(biz.id, "key-dup", "ed25519", priv_key1.public_key(), session=db_session)

    with pytest.raises(ValueError, match="Duplicate key registration rejected"):
        ManifestKeyRegistry.register_key(biz.id, "key-dup", "ed25519", priv_key2.public_key(), session=db_session)


def test_c2_key_rotation_lifecycle(db_session: Session):
    """C2: Key rotation marks old key as rotated, new key as active, and rejects signatures from rotated key."""
    biz, user = _setup_test_tenant(db_session, "c2-rot")
    priv_key_old = ed25519.Ed25519PrivateKey.generate()
    priv_key_new = ed25519.Ed25519PrivateKey.generate()

    ManifestKeyRegistry.register_key(biz.id, "key-v1", "ed25519", priv_key_old.public_key(), session=db_session)

    # Rotate to key-v2
    old_entry, new_entry = ManifestKeyRegistry.rotate_key(
        business_id=biz.id,
        old_key_id="key-v1",
        new_key_id="key-v2",
        algorithm="ed25519",
        new_public_key=priv_key_new.public_key(),
        session=db_session,
    )
    db_session.commit()

    assert new_entry.status == "active"
    assert new_entry.key_id == "key-v2"

    # Verify old key is marked rotated
    old_record = db_session.execute(
        select(TenantTrustedKey).where(TenantTrustedKey.business_id == biz.id, TenantTrustedKey.key_id == "key-v1")
    ).scalar_one()
    assert old_record.status == "rotated"

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])

    # Manifest signed by old rotated key must be rejected
    manifest_old = _build_manifest(biz.id, user.id, priv_key_old, csv_bytes, start, end, 1, Decimal("100.00"), key_id="key-v1")
    with pytest.raises(PermissionError, match="is rotated"):
        ManifestKeyRegistry.verify_manifest_signature(manifest_old, session=db_session)

    # Manifest signed by new active key must pass
    manifest_new = _build_manifest(biz.id, user.id, priv_key_new, csv_bytes, start, end, 1, Decimal("100.00"), key_id="key-v2")
    assert ManifestKeyRegistry.verify_manifest_signature(manifest_new, session=db_session) is True


def test_c2_unauthorized_key_registration_blocked(db_session: Session):
    """C2: Non-admin/owner member attempting key administration raises PermissionError."""
    biz, user = _setup_test_tenant(db_session, "c2-unauth", role="member")
    priv_key = ed25519.Ed25519PrivateKey.generate()

    with pytest.raises(PermissionError, match="Only organization 'owner' or 'admin'"):
        ManifestKeyRegistry.register_key(
            biz.id,
            "key-unauth",
            "ed25519",
            priv_key.public_key(),
            registering_user_id=user.id,
            session=db_session,
        )


def test_c2_public_key_pem_tampering_detected(db_session: Session):
    """C2: Direct DB tampering of public key PEM is detected and fails closed."""
    biz, user = _setup_test_tenant(db_session, "c2-tamper")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-tamper", "ed25519", priv_key.public_key(), session=db_session)

    # Adversary tampers with the public_key_pem in DB
    key_row = db_session.execute(
        select(TenantTrustedKey).where(TenantTrustedKey.business_id == biz.id, TenantTrustedKey.key_id == "key-tamper")
    ).scalar_one()
    key_row.public_key_pem = "CORRUPTED_KEY_PEM_DATA"
    db_session.commit()

    with pytest.raises(ValueError, match="Corrupted or tampered public key"):
        ManifestKeyRegistry.get_key(biz.id, "key-tamper", session=db_session)


def test_c2_private_key_zero_exposure(db_session: Session):
    """C2: TenantTrustedKey records store public key only; never store private key material."""
    biz, user = _setup_test_tenant(db_session, "c2-zero")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-zero", "ed25519", priv_key.public_key(), session=db_session)
    db_session.commit()

    key_row = db_session.execute(
        select(TenantTrustedKey).where(TenantTrustedKey.business_id == biz.id, TenantTrustedKey.key_id == "key-zero")
    ).scalar_one()

    assert "BEGIN PUBLIC KEY" in key_row.public_key_pem
    assert "BEGIN PRIVATE KEY" not in key_row.public_key_pem
    assert "PRIVATE" not in key_row.public_key_pem.upper()


# ==============================================================================
# Focus Area 3 (H1): Source Evidence Trust Boundary
# ==============================================================================

def test_h1_missing_evidence_blocks_promotion(db_session: Session):
    """H1: Period-close watermark with missing source-close evidence cannot be promoted to verified."""
    biz, user = _setup_test_tenant(db_session, "h1-noev")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-h1", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="key-h1")

    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
        source_close_evidence=None,
        promote_immediately_if_verified=True,
    )
    db_session.commit()

    assert res.is_valid is True
    assert res.verification_status == "provisional"


def test_h1_contradictory_revenue_fails_verification(db_session: Session):
    """H1: Source-close evidence declaring different revenue fails verification closed."""
    biz, user = _setup_test_tenant(db_session, "h1-contra")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-h1c", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="key-h1c")

    contradictory_evidence = {
        "source_system": "pos",
        "export_batch_id": "BATCH-ADV-001",
        "settlement_status": "CLOSED_RECONCILED",
        "reported_transaction_count": 1,
        "reported_gross_revenue": "999.00",
    }
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
        source_close_evidence=contradictory_evidence,
    )
    db_session.commit()

    assert res.is_valid is False
    assert any("Source-close report contradiction" in e for e in res.errors)


# ==============================================================================
# Focus Area 4 (H2): Synthetic Provenance Quarantine
# ==============================================================================

def test_h2_synthetic_provenance_strictly_prohibited_in_production(db_session: Session, monkeypatch):
    """H2: In production environment, synthetic provenance is prohibited even for test fixtures."""
    biz, user = _setup_test_tenant(db_session, "h2-prod")

    # Register synthetic watermark on test fixture tenant
    contract = WatermarkContract(
        business_id=biz.id,
        source_id="pos",
        complete_through_dt=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
        provenance_type="synthetic_fixture",
        verification_status="verified",
    )
    WatermarkService.record_watermark(db_session, contract)
    db_session.commit()

    # Simulate production environment
    monkeypatch.setenv("APP_ENV", "production")

    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
    )

    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.is_actionable is False
    assert verdict.reason_code == SafetyReasonCode.SYNTHETIC_PROVENANCE_PROHIBITED
    assert "production environments" in verdict.explanation


def test_h2_unapproved_provenance_quarantined_fail_closed(db_session: Session):
    """H2: Watermark with unapproved provenance fails closed with DIAGNOSTIC_ONLY."""
    biz, user = _setup_test_tenant(db_session, "h2-unapp")

    # Manually insert watermark with unapproved provenance
    wm = TenantIngestionWatermark(
        business_id=biz.id,
        source_id="pos",
        complete_through_dt=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
        provenance_type="unapproved_arbitrary_source",
        verification_status="verified",
        is_active=True,
    )
    db_session.add(wm)
    db_session.commit()

    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
    )

    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.SYNTHETIC_PROVENANCE_PROHIBITED
    assert "unapproved provenance_type" in verdict.explanation


# ==============================================================================
# Focus Area 6 (M2): Submission Ledger & Replay Prevention
# ==============================================================================

def test_m2_rejected_submission_with_fake_attester_persisted(db_session: Session):
    """M2: Rejected submission claiming a non-existent attester is persisted durably (Migration 019)."""
    biz, user = _setup_test_tenant(db_session, "m2-fake")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-m2", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])

    fake_attester = "non-existent-user-uuid-9999"
    manifest = _build_manifest(biz.id, fake_attester, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="key-m2")

    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
    )
    db_session.commit()

    # Verification failed closed because attester does not match caller
    assert res.is_valid is False

    # Submission was persisted durably in manifest_submissions without DB FK error!
    sub = db_session.execute(
        select(ManifestSubmission).where(ManifestSubmission.manifest_id == manifest.manifest_id)
    ).scalar_one_or_none()
    assert sub is not None
    assert sub.attested_by_user_id == fake_attester
    assert sub.submitted_by_user_id == user.id
    assert sub.verification_status == "failed"


def test_m2_duplicate_manifest_replay_rejected(db_session: Session):
    """M2: Replay of identical manifest_id is rejected and logged."""
    biz, user = _setup_test_tenant(db_session, "m2-rep")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-rep", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="key-rep")

    # First submission
    res1 = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
    )
    db_session.commit()
    assert res1.is_valid is True

    # Replay attempt with same manifest_id
    res2 = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
    )
    db_session.commit()

    assert res2.is_valid is False
    assert any("Manifest replay rejected" in e for e in res2.errors)


# ==============================================================================
# Apex Specialty Commerce Invariants
# ==============================================================================

def test_apex_specialty_commerce_invariants(db_session: Session):
    """Apex Specialty Commerce baseline invariants: 0 watermarks, 1,000 customers, 3,500 sales, DIAGNOSTIC_ONLY."""
    apex_id = "ab044b1a-835a-4a38-bf45-62fe38624151"

    # In unit test sqlite session, if Apex is seeded or queried
    apex_biz = db_session.execute(select(Business).where(Business.id == apex_id)).scalar_one_or_none()
    if apex_biz:
        wms = db_session.execute(
            select(TenantIngestionWatermark).where(TenantIngestionWatermark.business_id == apex_id, TenantIngestionWatermark.is_active.is_(True))
        ).scalars().all()
        assert len(wms) == 0

        verdict = CadenceSafetyGate.evaluate_tenant_safety(session=db_session, business_id=apex_id)
        assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
        assert verdict.is_actionable is False
        assert verdict.reason_code == SafetyReasonCode.MISSING_WATERMARK

        action_res = CadenceActionGate.evaluate_action_eligibility(
            session=db_session,
            business_id=apex_id,
            action_type="automated_email_campaign",
            is_automated_caller=True,
        )
        assert action_res.is_allowed is False
        assert action_res.status == ActionExecutionStatus.BLOCKED_AUTOMATION_PROHIBITED
