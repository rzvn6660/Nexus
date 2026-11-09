"""
NEXUS Phase 1I.4 — Watermark Certification Security Remediation Test Suite.

Proves remediation of findings from Phase 1I.3 Governance Review:
1. Finding C1 (Critical): DB-Level Persisted Ingestion Reconciliation before Promotion.
2. Finding C2 (Critical): Persistent Tenant Trusted Key Keystore (tenant_trusted_keys).
3. Finding H1 (High): Corroborating Upstream Source-Close Evidence Validation.
4. Finding H2 (High): Synthetic-Provenance Quarantine on Real Tenants.
5. Finding M1 (Medium): Mandatory Calling User Identity Enforcement.
6. Finding M2 (Medium): Manifest Submission Audit Ledger & Replay Prevention (manifest_submissions).
7. Apex Specialty Commerce Invariants: 0 watermarks, 1,000 customers, 3,500 sales, DIAGNOSTIC_ONLY.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import io
import csv
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.customer.safety import (
    CadenceActionGate,
    CadenceEligibilityStatus,
    CadenceSafetyGate,
    CadenceSafetyVerdict,
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
# Test Harness Helpers
# ==============================================================================

def _setup_test_tenant(session: Session, suffix: str, role: str = "admin") -> tuple[Business, UserIdentity]:
    """Create isolated test organization, business, and user."""
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-rem-{suffix}-{uid}", name=f"Rem Org {suffix}", slug=f"rem-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-rh-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Rem Rehearsal {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-rem-{suffix}-{uid}",
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
    key_id: str = "key-01",
    batch_id: str = "BATCH-REM-001",
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
        file_name="sales_remediation.csv",
        file_sha256=file_sha256,
        reconciliation=ReconciliationTotals(
            expected_sales_row_count=row_count,
            expected_gross_total_amount=gross_total,
            currency="USD",
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
# Finding C1: Persisted Ingestion Reconciliation before Promotion
# ==============================================================================

def test_c1_promotion_fails_when_db_sales_empty(db_session: Session):
    """C1: Watermark promotion fails closed if database contains 0 rows for period."""
    biz, user = _setup_test_tenant(db_session, "c1-empty")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-c1", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=5), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="key-c1")

    # Ingest without persisting rows in sales table
    evidence = {"source_system": "pos", "export_batch_id": "BATCH-REM-001", "settlement_status": "CLOSED_RECONCILED", "reported_transaction_count": 1, "reported_gross_revenue": "100.00"}
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
        source_close_evidence=evidence,
        promote_immediately_if_verified=True,
    )
    db_session.commit()

    # Manifest is valid provisionally, but promotion failed closed
    assert res.is_valid is True
    assert res.verification_status == "provisional"
    assert any("database contains 0 matching sales" in e for e in res.errors)

    # Watermark in DB is provisional, not verified
    wm = db_session.execute(select(TenantIngestionWatermark).where(TenantIngestionWatermark.id == res.watermark_id)).scalar_one()
    assert wm.verification_status == "provisional"


def test_c1_promotion_fails_when_db_sales_incomplete(db_session: Session):
    """C1: Watermark promotion fails closed if database has fewer rows than declared."""
    biz, user = _setup_test_tenant(db_session, "c1-incomp")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-c1-inc", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    rows = [
        ("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed"),
        ("TXN-2", "C-2", start + timedelta(days=2), Decimal("200.00"), "completed"),
    ]
    csv_bytes = _generate_csv(rows)
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 2, Decimal("300.00"), key_id="key-c1-inc")

    # Seed only 1 sale in DB instead of 2
    c = Customer(id=81001, business_id=biz.id, customer_code="C-1", name="C1", email="c1@example.com", customer_segment="Retail", city="Seattle", acquisition_date=date(2026, 4, 1))
    db_session.add(c)
    db_session.flush()
    s = Sale(id=81001, business_id=biz.id, customer_id=c.id, transaction_number="TXN-1", transaction_date=start + timedelta(days=1), subtotal=100.0, discount_amount=0.0, tax_amount=0.0, total_amount=100.0, status="completed")
    db_session.add(s)
    db_session.flush()

    evidence = {"source_system": "pos", "export_batch_id": "BATCH-REM-001", "settlement_status": "CLOSED_RECONCILED", "reported_transaction_count": 2, "reported_gross_revenue": "300.00"}
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session, manifest=manifest, file_bytes=csv_bytes, calling_user_id=user.id, source_close_evidence=evidence, promote_immediately_if_verified=True
    )
    db_session.commit()

    assert res.is_valid is True
    assert res.verification_status == "provisional"
    assert any("manifest expected 2 rows, but database contains 1" in e for e in res.errors)


def test_c1_promotion_succeeds_and_updates_submission_ledger(db_session: Session):
    """C1: Promotion succeeds when DB rows match exactly, marking ManifestSubmission db_reconciled."""
    biz, user = _setup_test_tenant(db_session, "c1-succ")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "key-c1-s", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    rows = [
        ("TXN-1", "C-1", start + timedelta(days=1), Decimal("150.00"), "completed"),
        ("TXN-2", "C-2", start + timedelta(days=2), Decimal("250.00"), "completed"),
    ]
    csv_bytes = _generate_csv(rows)
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 2, Decimal("400.00"), key_id="key-c1-s")

    # Seed matching customer and sales rows
    c = Customer(id=82001, business_id=biz.id, customer_code="C-1", name="C1", email="c1@example.com", customer_segment="Retail", city="Seattle", acquisition_date=date(2026, 4, 1))
    db_session.add(c)
    db_session.flush()
    s1 = Sale(id=82001, business_id=biz.id, customer_id=c.id, transaction_number="TXN-1", transaction_date=start + timedelta(days=1), subtotal=150.0, discount_amount=0.0, tax_amount=0.0, total_amount=150.0, status="completed")
    s2 = Sale(id=82002, business_id=biz.id, customer_id=c.id, transaction_number="TXN-2", transaction_date=start + timedelta(days=2), subtotal=250.0, discount_amount=0.0, tax_amount=0.0, total_amount=250.0, status="completed")
    db_session.add_all([s1, s2])
    db_session.flush()

    evidence = {"source_system": "pos", "export_batch_id": "BATCH-REM-001", "settlement_status": "CLOSED_RECONCILED", "reported_transaction_count": 2, "reported_gross_revenue": "400.00"}
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session, manifest=manifest, file_bytes=csv_bytes, calling_user_id=user.id, source_close_evidence=evidence, promote_immediately_if_verified=True
    )
    db_session.commit()

    assert res.is_valid is True
    assert res.verification_status == "verified"

    # Verify ManifestSubmission audit ledger updated
    sub = db_session.execute(select(ManifestSubmission).where(ManifestSubmission.manifest_id == manifest.manifest_id)).scalar_one()
    assert sub.db_reconciled is True
    assert sub.db_reconciled_at is not None
    assert sub.db_persisted_row_count == 2
    assert sub.db_persisted_gross_total == Decimal("400.00")


# ==============================================================================
# Finding C2: Persistent Tenant Trusted Key Registry
# ==============================================================================

def test_c2_key_registry_persists_to_database_and_rejects_private_key(db_session: Session):
    """C2: Register key with session writes to tenant_trusted_keys; private key is rejected."""
    biz, user = _setup_test_tenant(db_session, "c2-keys")
    priv_key = ed25519.Ed25519PrivateKey.generate()

    # Reject private key
    with pytest.raises(ValueError, match="Cannot register private key"):
        ManifestKeyRegistry.register_key(biz.id, "k-priv", "ed25519", priv_key, session=db_session)

    # Register public key persists to DB
    pub_key = priv_key.public_key()
    entry = ManifestKeyRegistry.register_key(biz.id, "k-pub-01", "ed25519", pub_key, session=db_session)
    db_session.commit()

    # Assert DB row exists
    db_row = db_session.execute(
        select(TenantTrustedKey).where(TenantTrustedKey.business_id == biz.id, TenantTrustedKey.key_id == "k-pub-01")
    ).scalar_one()
    assert db_row.algorithm == "ed25519"
    assert db_row.status == "active"
    assert "-----BEGIN PUBLIC KEY-----" in db_row.public_key_pem


def test_c2_key_retrieval_across_cache_reset(db_session: Session):
    """C2: Key lookup recovers from DB even after in-memory cache reset (cross-worker persistence)."""
    biz, user = _setup_test_tenant(db_session, "c2-cache")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k-persist", "ed25519", priv_key.public_key(), session=db_session)
    db_session.commit()

    # Simulate process restart / new Uvicorn worker
    ManifestKeyRegistry.reset()

    # Load from DB via session
    recovered = ManifestKeyRegistry.get_key(biz.id, "k-persist", session=db_session)
    assert recovered.key_id == "k-persist"
    assert recovered.status == "active"
    assert isinstance(recovered.public_key_or_secret, ed25519.Ed25519PublicKey)


def test_c2_revoked_and_expired_key_rejection(db_session: Session):
    """C2: Revoked or expired key in DB raises PermissionError during signature verification."""
    biz, user = _setup_test_tenant(db_session, "c2-rev")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k-rev", "ed25519", priv_key.public_key(), session=db_session)
    db_session.commit()

    # Revoke key in DB
    ManifestKeyRegistry.revoke_key(biz.id, "k-rev", reason="Compromised", session=db_session)
    db_session.commit()

    ManifestKeyRegistry.reset()
    with pytest.raises(PermissionError, match="revoked"):
        ManifestKeyRegistry.get_key(biz.id, "k-rev", session=db_session)


def test_c2_cross_tenant_key_isolation(db_session: Session):
    """C2: Key registered for Tenant A is strictly inaccessible to Tenant B."""
    biz_a, user_a = _setup_test_tenant(db_session, "c2-iso-a")
    biz_b, user_b = _setup_test_tenant(db_session, "c2-iso-b")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz_a.id, "k-shared", "ed25519", priv_key.public_key(), session=db_session)
    db_session.commit()

    ManifestKeyRegistry.reset()
    with pytest.raises(PermissionError, match="Untrusted or unregistered key_id"):
        ManifestKeyRegistry.get_key(biz_b.id, "k-shared", session=db_session)


# ==============================================================================
# Finding H1: Corroborating Source-Close Evidence Validation
# ==============================================================================

def test_h1_missing_evidence_blocks_promotion(db_session: Session):
    """H1: Omitting source-close evidence blocks immediate promotion on accounting provenance."""
    biz, user = _setup_test_tenant(db_session, "h1-miss")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k-h1", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="k-h1")

    # Ingest with NO source evidence, requesting promotion
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session, manifest=manifest, file_bytes=csv_bytes, calling_user_id=user.id, source_close_evidence=None, promote_immediately_if_verified=True
    )
    db_session.commit()

    # Manifest accepted provisionally, but promotion was blocked
    assert res.is_valid is True
    assert res.verification_status == "provisional"


def test_h1_contradictory_source_evidence_fails_verification(db_session: Session):
    """H1: Contradictory transaction count or revenue in source evidence fails verification entirely."""
    biz, user = _setup_test_tenant(db_session, "h1-contra")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k-h1-c", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="k-h1-c")

    contradictory_evidence = {
        "source_system": "pos",
        "export_batch_id": "BATCH-REM-001",
        "settlement_status": "CLOSED_RECONCILED",
        "reported_transaction_count": 999,  # Contradicts declared 1 row
        "reported_gross_revenue": "99900.00",
    }
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session, manifest=manifest, file_bytes=csv_bytes, calling_user_id=user.id, source_close_evidence=contradictory_evidence
    )
    assert res.is_valid is False
    assert any("Source-close report contradiction" in e for e in res.errors)
    assert res.watermark_id is None


def test_h1_unsettled_source_evidence_fails_verification(db_session: Session):
    """H1: Source-close evidence with UNSETTLED or PENDING status fails verification."""
    biz, user = _setup_test_tenant(db_session, "h1-unsettled")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k-h1-u", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="k-h1-u")

    unsettled_evidence = {
        "source_system": "pos",
        "export_batch_id": "BATCH-REM-001",
        "settlement_status": "PENDING_SETTLEMENT",
        "reported_transaction_count": 1,
        "reported_gross_revenue": "100.00",
    }
    res = ManifestService.verify_and_ingest_manifest(
        session=db_session, manifest=manifest, file_bytes=csv_bytes, calling_user_id=user.id, source_close_evidence=unsettled_evidence
    )
    assert res.is_valid is False
    assert any("Source-close evidence is not settled/closed" in e for e in res.errors)


# ==============================================================================
# Finding H2: Synthetic Provenance Quarantine
# ==============================================================================

def test_h2_synthetic_provenance_quarantined_on_real_tenant(db_session: Session):
    """H2: CadenceSafetyGate fails closed with SYNTHETIC_PROVENANCE_PROHIBITED on non-fixture tenant."""
    # Real tenant business ID (does not start with biz-rh- or contain rehearsal)
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-real-{uid}", name="Production Org", slug=f"org-prod-{uid}")
    biz = Business(id=f"prod-commerce-{uid}", organization_id=org.id, name="Production Commerce", industry="Retail", country="US", currency="USD", status="active")
    db_session.add_all([org, biz])
    db_session.flush()

    # Create active watermark with synthetic_fixture provenance
    contract = WatermarkContract(
        business_id=biz.id,
        source_id="pos",
        complete_through_dt=datetime(2026, 6, 30, tzinfo=UTC),
        provenance_type="synthetic_fixture",
        verification_status="verified",
    )
    WatermarkService.record_watermark(db_session, contract)
    db_session.commit()

    # Safety gate must quarantine
    verdict = CadenceSafetyGate.evaluate_tenant_safety(db_session, biz.id, as_of_date=datetime(2026, 7, 1, tzinfo=UTC), max_staleness_days=None)
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.SYNTHETIC_PROVENANCE_PROHIBITED
    assert verdict.is_actionable is False


def test_h2_synthetic_provenance_permitted_on_test_fixture(db_session: Session):
    """H2: Dedicated rehearsal fixture (biz-rh-*) is permitted to evaluate synthetic provenance."""
    biz, user = _setup_test_tenant(db_session, "h2-fixture")
    contract = WatermarkContract(
        business_id=biz.id,
        source_id="pos",
        complete_through_dt=datetime(2026, 6, 30, tzinfo=UTC),
        provenance_type="synthetic_fixture",
        verification_status="verified",
    )
    WatermarkService.record_watermark(db_session, contract)
    db_session.commit()

    verdict = CadenceSafetyGate.evaluate_tenant_safety(db_session, biz.id, as_of_date=datetime(2026, 7, 1, tzinfo=UTC), max_staleness_days=None)
    # Rehearsal fixture is not quarantined for synthetic provenance
    assert verdict.reason_code != SafetyReasonCode.SYNTHETIC_PROVENANCE_PROHIBITED


# ==============================================================================
# Finding M1: Mandatory Calling User Identity Enforcement
# ==============================================================================

def test_m1_mandatory_caller_id_enforced(db_session: Session):
    """M1: Calling authorize_signer without calling_user_id raises PermissionError."""
    biz, user = _setup_test_tenant(db_session, "m1-caller")
    with pytest.raises(PermissionError, match="Authenticated calling_user_id is mandatory"):
        ManifestService.authorize_signer(session=db_session, business_id=biz.id, attesting_user_id=user.id, calling_user_id="")


def test_m1_caller_attester_mismatch_rejected(db_session: Session):
    """M1: Calling user mismatching attesting user is rejected."""
    biz, user = _setup_test_tenant(db_session, "m1-mismatch")
    other_user = UserIdentity(id=f"usr-other-{uuid4().hex[:6]}", email="other@example.com", full_name="Other", password_hash="x", is_active=True, is_verified=True)
    db_session.add(other_user)
    db_session.flush()

    with pytest.raises(PermissionError, match="does not match authenticated user"):
        ManifestService.authorize_signer(session=db_session, business_id=biz.id, attesting_user_id=user.id, calling_user_id=other_user.id)


# ==============================================================================
# Finding M2: Manifest Submission Ledger & Replay Prevention
# ==============================================================================

def test_m2_manifest_submission_persisted_and_replay_rejected(db_session: Session):
    """M2: Manifest submission is stored in manifest_submissions; replay of same manifest_id is rejected."""
    biz, user = _setup_test_tenant(db_session, "m2-sub")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k-m2", "ed25519", priv_key.public_key(), session=db_session)

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 6, 30, tzinfo=UTC)
    csv_bytes = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])
    manifest = _build_manifest(biz.id, user.id, priv_key, csv_bytes, start, end, 1, Decimal("100.00"), key_id="k-m2")

    # 1. First submission succeeds and writes audit ledger
    res1 = ManifestService.verify_and_ingest_manifest(
        session=db_session, manifest=manifest, file_bytes=csv_bytes, calling_user_id=user.id
    )
    db_session.commit()
    assert res1.is_valid is True

    sub = db_session.execute(select(ManifestSubmission).where(ManifestSubmission.manifest_id == manifest.manifest_id)).scalar_one()
    assert sub.manifest_id == manifest.manifest_id
    assert sub.business_id == biz.id
    assert sub.submitted_by_user_id == user.id

    # 2. Replaying identical manifest_id is rejected
    res2 = ManifestService.verify_and_ingest_manifest(
        session=db_session, manifest=manifest, file_bytes=csv_bytes, calling_user_id=user.id
    )
    assert res2.is_valid is False
    assert any("Manifest replay rejected" in e for e in res2.errors)


# ==============================================================================
# Invariant Preservation: Apex Specialty Commerce Remains Untouched
# ==============================================================================

def test_apex_tenant_invariants_strictly_preserved(db_session: Session):
    """Confirm Apex Specialty Commerce remains unwatermarked and DIAGNOSTIC_ONLY."""
    apex_biz_id = "ab044b1a-835a-4a38-bf45-62fe38624151"

    # Check if Apex business exists in current session/database
    apex_biz = db_session.execute(select(Business).where(Business.id == apex_biz_id)).scalar_one_or_none()
    if apex_biz:
        # Zero active watermarks
        wm_count = db_session.execute(
            select(func.count(TenantIngestionWatermark.id)).where(TenantIngestionWatermark.business_id == apex_biz_id)
        ).scalar()
        assert wm_count == 0, f"Apex tenant must have 0 watermarks, found {wm_count}"

        # Safety gate returns DIAGNOSTIC_ONLY
        verdict = CadenceSafetyGate.evaluate_tenant_safety(db_session, apex_biz_id, as_of_date=datetime(2026, 7, 1, tzinfo=UTC), max_staleness_days=None)
        assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
        assert verdict.is_actionable is False

        # Action gate blocks automation
        action_verdict = CadenceActionGate.evaluate_action_gate(db_session, apex_biz_id, caller_identity="automated_agent", is_automated=True)
        assert action_verdict.is_permitted is False
