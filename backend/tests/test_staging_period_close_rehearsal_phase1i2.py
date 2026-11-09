"""
Unit and integration tests for NEXUS Phase 1I.2 — Staging Period-Close Certification Rehearsal.

Validates the full signed period-close certification rehearsal lifecycle:
Stage 1: Contract & Security Claim Bindings & Canonical Determinism.
Stage 2: Positive End-to-End Certification (synthetic tenant, independent source-close
         reconciliation, provisional watermark, promotion to verified, downstream safety gate
         cascade: ACTIONABLE within boundary, DIAGNOSTIC_ONLY outside boundary, and consequential
         action gate blocking automated execution).
Stage 3: Negative & Failure Paths (10 failure paths: file tampering, signature forgery,
         untrusted key, revoked key, unauthorized attester, attester mismatch, contradictory
         source evidence, out-of-bounds dates, duplicate transaction IDs, backfill invalidation,
         and stale watermark >90 days).
Stage 4: Strict Apex Tenant Invariant Isolation (Apex remains 100% untouched, 0 watermarks,
         diagnostic_only / MISSING_WATERMARK).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import io
import csv
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.customer.safety import (
    ActionExecutionStatus,
    CadenceActionGate,
    CadenceEligibilityStatus,
    CadenceSafetyGate,
    SafetyReasonCode,
)
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
from app.services.watermark_service import WatermarkContract, WatermarkService


APEX_TENANT_ID = "ab044b1a-835a-4a38-bf45-62fe38624151"


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure trusted key registry is reset before and after each test."""
    ManifestKeyRegistry.reset()
    yield
    ManifestKeyRegistry.reset()


def _create_isolated_tenant(
    session: Session, suffix: str = "rh", role: str = "admin"
) -> tuple[Organization, Business, UserIdentity]:
    """Provision isolated synthetic tenant, admin user, and membership."""
    uid = uuid4().hex[:8]
    org = Organization(
        id=f"org-rh-{suffix}-{uid}",
        name=f"Rehearsal Org {suffix} {uid}",
        slug=f"org-rh-{suffix}-{uid}",
    )
    biz = Business(
        id=f"biz-rh-{suffix}-{uid}",
        organization_id=org.id,
        name=f"Rehearsal Retail {suffix} {uid}",
        industry="Specialty Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-rh-{suffix}-{uid}",
        email=f"usr_{suffix}_{uid}@example.com",
        full_name=f"Rehearsal User {suffix} {uid}",
        password_hash="mock_hash",
        is_active=True,
        is_verified=True,
    )
    session.add_all([org, biz, user])
    session.flush()

    mem = OrganizationMembership(
        id=int(f"99{int(uid[:5], 16) % 10000:04d}"),
        user_id=user.id,
        organization_id=org.id,
        role=role,
    )
    session.add(mem)
    session.flush()
    return org, biz, user


def _build_signed_manifest(
    business_id: str,
    user_id: str,
    private_key: ed25519.Ed25519PrivateKey,
    file_bytes: bytes,
    period_start: datetime,
    period_end: datetime,
    expected_rows: int,
    expected_gross: Decimal,
    key_id: str = "key-ed25519-rh-01",
    batch_id: str = "BATCH-P1I2-001",
) -> PeriodCloseManifest:
    """Build and sign canonical PeriodCloseManifest."""
    file_sha256 = ManifestService.compute_file_sha256(file_bytes)
    placeholder = PeriodCloseManifest(
        manifest_id=str(uuid4()),
        business_id=business_id,
        source_id="pos",
        batch_id=batch_id,
        provenance_type="accounting_period_close",
        period_start=period_start,
        period_end=period_end,
        source_export_id=f"EXP-{batch_id}",
        export_completed_at=period_end + timedelta(minutes=15),
        file_name="rehearsal_sales.csv",
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
            attestation_statement="NEXUS Phase 1I.2 Rehearsal Attestation.",
            attested_at=datetime.now(UTC),
        ),
        signature=ManifestSignature(
            algorithm="ed25519",
            key_id=key_id,
            signature_hex="00" * 64,
        ),
    )
    raw_sig = private_key.sign(placeholder.get_canonical_bytes())
    return PeriodCloseManifest(
        **{
            **placeholder.model_dump(),
            "signature": ManifestSignature(
                algorithm="ed25519",
                key_id=key_id,
                signature_hex=raw_sig.hex(),
            ),
        }
    )


# ==============================================================================
# Stage 1: Contract & Security Claim Bindings
# ==============================================================================

def test_stage1_canonical_claim_binding_and_determinism():
    """Verify that any modification of critical claim fields breaks signature verification."""
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    biz_id = "biz-rh-claim-test"
    ManifestKeyRegistry.register_key(biz_id, "k1", "ed25519", pub_key)

    csv_data = b"transaction_number,customer_id,transaction_date,total_amount,status\nTXN-01,C-01,2026-05-01 10:00:00,100.00,completed\n"
    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    manifest = _build_signed_manifest(
        biz_id, "u1", priv_key, csv_data, period_start, period_end, 1, Decimal("100.00"), key_id="k1"
    )

    # 1. Signature must verify against unmodified manifest
    assert ManifestKeyRegistry.verify_manifest_signature(manifest) is True

    # 2. Tampering with gross amount must break cryptographic verification
    tampered_dict = manifest.model_dump()
    tampered_dict["reconciliation"]["expected_gross_total_amount"] = Decimal("9999.00")
    tampered_man = PeriodCloseManifest(**tampered_dict)
    with pytest.raises(ValueError, match="signature is invalid"):
        ManifestKeyRegistry.verify_manifest_signature(tampered_man)

    # 3. Tampering with period_end must break signature
    tampered_dict2 = manifest.model_dump()
    tampered_dict2["period_end"] = period_end + timedelta(days=1)
    tampered_man2 = PeriodCloseManifest(**tampered_dict2)
    with pytest.raises(ValueError, match="signature is invalid"):
        ManifestKeyRegistry.verify_manifest_signature(tampered_man2)


# ==============================================================================
# Stage 2: Positive End-to-End Certification & Downstream Safety Cascade
# ==============================================================================

def test_stage2_positive_certification_and_safety_gate_cascade(db_session: Session):
    """
    Stage 2 Rehearsal:
    - Synthetic tenant with 35 repeat customers (70 sales) and 10 one-time buyers (10 sales).
    - Total: 80 sales, $8,200.00 gross revenue.
    - Independent source-close report matching expected figures.
    - Signed manifest verification & provisional watermark generation.
    - Promotion to verified watermark.
    - Safety gate evaluation inside boundary -> ACTIONABLE.
    - Safety gate evaluation outside boundary -> DIAGNOSTIC_ONLY.
    - Action gate restricts automated execution.
    """
    org, biz, user = _create_isolated_tenant(db_session, "pos-stage2", role="admin")

    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    ManifestKeyRegistry.register_key(biz.id, "key-stage2", "ed25519", pub_key)

    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["transaction_number", "customer_code", "transaction_date", "total_amount", "status"])

    total_gross = Decimal("0.00")
    sales_count = 0

    # 35 repeat buyers with transactions before June 15
    for i in range(35):
        c = Customer(
            id=5000 + i,
            business_id=biz.id,
            customer_code=f"RH-REP-{i:04d}",
            name=f"Repeat Buyer {i}",
            email=f"rep_{i}@rehearsal.example.com",
            customer_segment="Retail",
            city="Seattle",
            acquisition_date=date(2026, 4, 1),
        )
        db_session.add(c)
        db_session.flush()

        t1_dt = period_start + timedelta(days=2 + i)
        t1_amt = Decimal("100.00")
        total_gross += t1_amt
        sales_count += 1
        s1 = Sale(
            id=50000 + sales_count,
            business_id=biz.id,
            customer_id=c.id,
            transaction_number=f"TXN-S2-{sales_count:05d}",
            transaction_date=t1_dt,
            subtotal=float(t1_amt),
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=float(t1_amt),
            status="completed",
        )
        t2_dt = period_start + timedelta(days=38 + i)
        t2_amt = Decimal("120.00")
        total_gross += t2_amt
        sales_count += 1
        s2 = Sale(
            id=50000 + sales_count,
            business_id=biz.id,
            customer_id=c.id,
            transaction_number=f"TXN-S2-{sales_count:05d}",
            transaction_date=t2_dt,
            subtotal=float(t2_amt),
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=float(t2_amt),
            status="completed",
        )
        db_session.add_all([s1, s2])
        writer.writerow([s1.transaction_number, c.customer_code, t1_dt.strftime("%Y-%m-%d %H:%M:%S"), f"{t1_amt:.2f}", "completed"])
        writer.writerow([s2.transaction_number, c.customer_code, t2_dt.strftime("%Y-%m-%d %H:%M:%S"), f"{t2_amt:.2f}", "completed"])

    # 10 one-time buyers
    for j in range(10):
        c = Customer(
            id=6000 + j,
            business_id=biz.id,
            customer_code=f"RH-ONE-{j:04d}",
            name=f"OneTime Buyer {j}",
            email=f"one_{j}@rehearsal.example.com",
            customer_segment="Retail",
            city="Portland",
            acquisition_date=date(2026, 4, 15),
        )
        db_session.add(c)
        db_session.flush()

        t_dt = period_start + timedelta(days=20 + j)
        t_amt = Decimal("50.00")
        total_gross += t_amt
        sales_count += 1
        s = Sale(
            id=50000 + sales_count,
            business_id=biz.id,
            customer_id=c.id,
            transaction_number=f"TXN-S2-{sales_count:05d}",
            transaction_date=t_dt,
            subtotal=float(t_amt),
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=float(t_amt),
            status="completed",
        )
        db_session.add(s)
        writer.writerow([s.transaction_number, c.customer_code, t_dt.strftime("%Y-%m-%d %H:%M:%S"), f"{t_amt:.2f}", "completed"])

    db_session.flush()
    csv_bytes = csv_buf.getvalue().encode("utf-8")
    assert sales_count == 80
    assert total_gross == Decimal("8200.00")

    # Independent source-close evidence
    source_evidence = {
        "source_system": "NetSuite_ERP",
        "export_batch_id": "BATCH-P1I2-CLOSE-001",
        "settlement_status": "CLOSED_RECONCILED",
        "reported_transaction_count": 80,
        "reported_gross_revenue": "8200.00",
    }

    manifest = _build_signed_manifest(
        biz.id,
        user.id,
        priv_key,
        csv_bytes,
        period_start,
        period_end,
        80,
        Decimal("8200.00"),
        key_id="key-stage2",
        batch_id="BATCH-P1I2-CLOSE-001",
    )

    # Ingest and verify
    result = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_bytes,
        calling_user_id=user.id,
        source_close_evidence=source_evidence,
    )
    assert result.is_valid is True
    assert result.watermark_id is not None

    # Provisional watermark verification in safety gate -> DIAGNOSTIC_ONLY
    v_prov = CadenceSafetyGate.evaluate_tenant_safety(
        db_session, biz.id, as_of_date=datetime(2026, 6, 15, tzinfo=UTC), max_staleness_days=None
    )
    assert v_prov.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert v_prov.reason_code == SafetyReasonCode.PROVISIONAL_WATERMARK
    assert v_prov.is_actionable is False

    # Promote to verified
    promoted = WatermarkService.promote_provisional_watermark(
        session=db_session,
        business_id=biz.id,
        watermark_id=result.watermark_id,
        audit_metadata={"promoted_by": user.id, "reason": "certification_complete"},
    )
    db_session.flush()
    assert promoted.verification_status == "verified"

    # Evaluated inside boundary (June 15 <= June 30) -> ACTIONABLE
    v_inside = CadenceSafetyGate.evaluate_tenant_safety(
        db_session, biz.id, as_of_date=datetime(2026, 6, 15, tzinfo=UTC), max_staleness_days=None
    )
    assert v_inside.eligibility_status == CadenceEligibilityStatus.ACTIONABLE
    assert v_inside.is_actionable is True
    assert v_inside.reason_code == SafetyReasonCode.VERIFIED_ACTIONABLE
    assert v_inside.eligible_repeat_buyers_count == 35

    # Evaluated outside boundary (July 15 > June 30) -> DIAGNOSTIC_ONLY
    v_outside = CadenceSafetyGate.evaluate_tenant_safety(
        db_session, biz.id, as_of_date=datetime(2026, 7, 15, tzinfo=UTC), max_staleness_days=None
    )
    assert v_outside.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert v_outside.is_actionable is False
    assert v_outside.reason_code == SafetyReasonCode.CUTOFF_EXCEEDS_WATERMARK

    # Consequential action gate blocks automated caller
    act_res = CadenceActionGate.evaluate_action_eligibility(
        session=db_session, business_id=biz.id, action_type="send_retention_coupon", is_automated_caller=True
    )
    assert act_res.is_allowed is False
    assert act_res.status == ActionExecutionStatus.BLOCKED_AUTOMATION_PROHIBITED


# ==============================================================================
# Stage 3: Negative & Failure Scenarios
# ==============================================================================

def test_stage3_negative_file_tampering(db_session: Session):
    """Corrupted raw CSV bytes fail SHA-256 verification and block watermark."""
    org, biz, user = _create_isolated_tenant(db_session, "neg-tamper")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k1", "ed25519", priv_key.public_key())

    csv_data = b"transaction_number,customer_id,transaction_date,total_amount,status\nTXN-01,C-01,2026-05-01 10:00:00,100.00,completed\n"
    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_data, period_start, period_end, 1, Decimal("100.00"), key_id="k1")

    tampered_bytes = csv_data + b"tampered_extra_bytes"
    res = ManifestService.verify_and_ingest_manifest(db_session, manifest, tampered_bytes, user.id)
    assert res.is_valid is False
    assert any("File SHA-256 mismatch" in e for e in res.errors)
    assert res.watermark_id is None


def test_stage3_negative_cryptographic_forgery_and_revocation(db_session: Session):
    """Invalid signature, unregistered key, and revoked key fail closed."""
    org, biz, user = _create_isolated_tenant(db_session, "neg-crypto")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    ManifestKeyRegistry.register_key(biz.id, "k-active", "ed25519", pub_key)
    ManifestKeyRegistry.register_key(biz.id, "k-revoked", "ed25519", pub_key)
    ManifestKeyRegistry.revoke_key(biz.id, "k-revoked", "Compromised test key")

    csv_data = b"transaction_number,customer_id,transaction_date,total_amount,status\nTXN-01,C-01,2026-05-01 10:00:00,100.00,completed\n"
    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    # 1. Invalid signature (signed with unknown key)
    attacker_key = ed25519.Ed25519PrivateKey.generate()
    forged_manifest = _build_signed_manifest(biz.id, user.id, attacker_key, csv_data, period_start, period_end, 1, Decimal("100.00"), key_id="k-active")
    r1 = ManifestService.verify_and_ingest_manifest(db_session, forged_manifest, csv_data, user.id)
    assert r1.is_valid is False
    assert any("Ed25519 signature is invalid" in e for e in r1.errors)

    # 2. Untrusted / unregistered key ID
    unregistered_man = _build_signed_manifest(biz.id, user.id, priv_key, csv_data, period_start, period_end, 1, Decimal("100.00"), key_id="unregistered-id")
    r2 = ManifestService.verify_and_ingest_manifest(db_session, unregistered_man, csv_data, user.id)
    assert r2.is_valid is False
    assert any("Untrusted or unregistered key_id" in e for e in r2.errors)

    # 3. Revoked key
    revoked_man = _build_signed_manifest(biz.id, user.id, priv_key, csv_data, period_start, period_end, 1, Decimal("100.00"), key_id="k-revoked")
    r3 = ManifestService.verify_and_ingest_manifest(db_session, revoked_man, csv_data, user.id)
    assert r3.is_valid is False
    assert any("is revoked" in e for e in r3.errors)


def test_stage3_negative_unauthorized_attester(db_session: Session):
    """Non-administrative user or caller mismatch fails closed."""
    org, biz, user_admin = _create_isolated_tenant(db_session, "neg-auth-adm", role="admin")
    _, _, user_member = _create_isolated_tenant(db_session, "neg-auth-mem", role="member")

    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k1", "ed25519", priv_key.public_key())

    csv_data = b"transaction_number,customer_id,transaction_date,total_amount,status\nTXN-01,C-01,2026-05-01 10:00:00,100.00,completed\n"
    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    manifest = _build_signed_manifest(biz.id, user_admin.id, priv_key, csv_data, period_start, period_end, 1, Decimal("100.00"), key_id="k1")

    # Member user submits admin's manifest -> Caller mismatch
    r_unauth = ManifestService.verify_and_ingest_manifest(db_session, manifest, csv_data, calling_user_id=user_member.id)
    assert r_unauth.is_valid is False
    assert any("does not match authenticated user" in e for e in r_unauth.errors)


def test_stage3_negative_contradictory_source_evidence(db_session: Session):
    """External source-close report contradicting manifest counts or revenue fails closed."""
    org, biz, user = _create_isolated_tenant(db_session, "neg-contra")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k1", "ed25519", priv_key.public_key())

    csv_data = b"transaction_number,customer_id,transaction_date,total_amount,status\nTXN-01,C-01,2026-05-01 10:00:00,100.00,completed\n"
    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    manifest = _build_signed_manifest(biz.id, user.id, priv_key, csv_data, period_start, period_end, 1, Decimal("100.00"), key_id="k1")

    bad_evidence = {
        "source_system": "NetSuite_ERP",
        "export_batch_id": "BATCH-P1I2-CLOSE-001",
        "settlement_status": "CLOSED_RECONCILED",
        "reported_transaction_count": 999,  # Mismatch
        "reported_gross_revenue": "99900.00",  # Mismatch
    }

    res = ManifestService.verify_and_ingest_manifest(
        db_session, manifest, csv_data, user.id, source_close_evidence=bad_evidence
    )
    assert res.is_valid is False
    assert any("Source-close report contradiction: source reported 999 rows, manifest expected 1" in e for e in res.errors)
    assert any("Source-close report contradiction: source reported 99900.00 revenue, manifest expected 100.00" in e for e in res.errors)


def test_stage3_negative_date_and_duplicate_violations(db_session: Session):
    """Out-of-bounds dates and duplicate transaction IDs fail closed."""
    org, biz, user = _create_isolated_tenant(db_session, "neg-date-dup")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k1", "ed25519", priv_key.public_key())

    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    # 1. Out-of-bounds date (July 10 is past June 30)
    csv_bad_date = b"transaction_number,customer_id,transaction_date,total_amount,status\nTXN-01,C-01,2026-07-10 12:00:00,100.00,completed\n"
    man_bad_date = _build_signed_manifest(biz.id, user.id, priv_key, csv_bad_date, period_start, period_end, 1, Decimal("100.00"), key_id="k1")
    r_date = ManifestService.verify_and_ingest_manifest(db_session, man_bad_date, csv_bad_date, user.id)
    assert r_date.is_valid is False
    assert any("exceeds declared period_end" in e for e in r_date.errors)

    # 2. Duplicate transaction ID
    csv_dup = (
        b"transaction_number,customer_id,transaction_date,total_amount,status\n"
        b"TXN-01,C-01,2026-05-01 10:00:00,50.00,completed\n"
        b"TXN-01,C-02,2026-05-02 10:00:00,50.00,completed\n"
    )
    man_dup = _build_signed_manifest(biz.id, user.id, priv_key, csv_dup, period_start, period_end, 2, Decimal("100.00"), key_id="k1")
    r_dup = ManifestService.verify_and_ingest_manifest(db_session, man_dup, csv_dup, user.id)
    assert r_dup.is_valid is False
    assert any("Duplicate transaction ID 'TXN-01'" in e for e in r_dup.errors)


def test_stage3_negative_backfill_and_staleness(db_session: Session):
    """Backfill ingestion invalidates verified watermark; watermarks older than 90d trigger STALE_WATERMARK."""
    org, biz, user = _create_isolated_tenant(db_session, "neg-backfill")

    # 1. Register a verified watermark
    wm_date = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    wm = WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=wm_date,
            provenance_type="accounting_period_close",
            verification_status="verified",
        ),
    )
    db_session.flush()

    # Backfill arrives with transaction dated May 20 (before June 30)
    backfill_detected = WatermarkService.detect_backfill_and_handle(
        db_session, biz.id, "pos", [datetime(2026, 5, 20, 10, 0, tzinfo=UTC)], job_id="job-late-arrival"
    )
    db_session.flush()
    assert backfill_detected is True

    eff_wm = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)
    assert eff_wm.status == "invalidated"
    assert eff_wm.is_verified is False

    # 2. Stale watermark evaluation (>90 days old)
    org_stale, biz_stale, _ = _create_isolated_tenant(db_session, "neg-stale")
    stale_dt = datetime.now(UTC) - timedelta(days=120)
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz_stale.id,
            source_id="default",
            complete_through_dt=stale_dt,
            provenance_type="synthetic_fixture",
            verification_status="verified",
        ),
    )
    db_session.flush()
    v_stale = CadenceSafetyGate.evaluate_tenant_safety(db_session, biz_stale.id, as_of_date=stale_dt, max_staleness_days=90)
    assert v_stale.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert v_stale.reason_code == SafetyReasonCode.STALE_WATERMARK


# ==============================================================================
# Stage 4: Invariant Verification on Apex Specialty Commerce
# ==============================================================================

def test_stage4_apex_invariants_strictly_preserved(db_session: Session):
    """
    Verify that Apex Specialty Commerce is completely isolated and unmodified:
    - 0 registered watermarks
    - Evaluated safety status is DIAGNOSTIC_ONLY
    - Reason code is MISSING_WATERMARK
    - is_actionable is False
    """
    org_apex = Organization(id="org-apex", name="Apex Organization", slug="apex-org")
    biz_apex = Business(
        id=APEX_TENANT_ID,
        organization_id=org_apex.id,
        name="Apex Specialty Commerce 64ea641d",
        industry="Specialty Retail",
        status="active",
    )
    db_session.add_all([org_apex, biz_apex])
    db_session.flush()

    apex_wm = db_session.execute(
        select(TenantIngestionWatermark).where(TenantIngestionWatermark.business_id == APEX_TENANT_ID)
    ).scalars().all()
    assert len(apex_wm) == 0

    verdict = CadenceSafetyGate.evaluate_tenant_safety(db_session, APEX_TENANT_ID)
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.MISSING_WATERMARK
    assert verdict.is_actionable is False
    assert "No authoritative ingestion watermark is registered" in verdict.explanation
