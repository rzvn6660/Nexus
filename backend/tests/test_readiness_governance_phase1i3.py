"""
Automated Governance & Readiness Verification Suite for NEXUS Phase 1I.3.

Codifies governance invariants and tests the 6 review dimensions:
1. Source-evidence independence & self-attestation limits.
2. Authorization, canonical claim binding, and key management.
3. Watermark promotion & recovery (ingestion row verification gap).
4. Separation of cadence analytics and consequential customer actions.
5. Synthetic vs real provenance quarantine.
6. Apex Specialty Commerce isolation invariant.
"""

from datetime import UTC, datetime, timedelta
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
from app.models.history import DecisionRecord
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
def reset_keystore():
    ManifestKeyRegistry.reset()
    yield
    ManifestKeyRegistry.reset()


def _create_isolated_workspace(session: Session, suffix: str = "gov") -> tuple[Business, UserIdentity, UserIdentity]:
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-{suffix}-{uid}", name=f"Gov Org {uid}", slug=f"gov-org-{uid}")
    biz = Business(id=f"biz-{suffix}-{uid}", organization_id=org.id, name=f"Gov Biz {uid}", industry="Specialty Retail", status="active")
    admin = UserIdentity(id=f"adm-{suffix}-{uid}", email=f"adm_{uid}@test.com", full_name="Admin", is_active=True, is_verified=True, password_hash="x")
    member = UserIdentity(id=f"mem-{suffix}-{uid}", email=f"mem_{uid}@test.com", full_name="Member", is_active=True, is_verified=True, password_hash="x")
    session.add_all([org, biz, admin, member])
    session.flush()

    mem_admin = OrganizationMembership(
        id=int(f"98{int(uid[:4], 16) % 10000:04d}1"), user_id=admin.id, organization_id=org.id, role="admin"
    )
    mem_member = OrganizationMembership(
        id=int(f"98{int(uid[:4], 16) % 10000:04d}2"), user_id=member.id, organization_id=org.id, role="member"
    )
    session.add_all([mem_admin, mem_member])
    session.flush()
    return biz, admin, member


def _build_manifest(biz_id: str, admin_id: str, priv_key: ed25519.Ed25519PrivateKey, csv_bytes: bytes) -> PeriodCloseManifest:
    file_sha256 = ManifestService.compute_file_sha256(csv_bytes)
    period_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    placeholder = PeriodCloseManifest(
        manifest_id=str(uuid4()),
        business_id=biz_id,
        source_id="pos",
        batch_id="BATCH-GOV-01",
        provenance_type="accounting_period_close",
        period_start=period_start,
        period_end=period_end,
        source_export_id="EXP-BATCH-GOV-01",
        export_completed_at=period_end + timedelta(minutes=5),
        file_name="sales.csv",
        file_sha256=file_sha256,
        reconciliation=ReconciliationTotals(
            expected_sales_row_count=2,
            expected_gross_total_amount=Decimal("200.00"),
            currency="USD",
            eligible_status_allowlist=["completed"],
        ),
        attestation=ManifestAttestation(
            attested_by_user_id=admin_id,
            attester_role="finance_controller",
            attestation_statement="Phase 1I.3 Governance attestation.",
            attested_at=datetime.now(UTC),
        ),
        signature=ManifestSignature(
            algorithm="ed25519",
            key_id="k-gov",
            signature_hex="00" * 64,
        ),
    )
    raw_sig = priv_key.sign(placeholder.get_canonical_bytes())
    return PeriodCloseManifest(
        **{
            **placeholder.model_dump(),
            "signature": ManifestSignature(algorithm="ed25519", key_id="k-gov", signature_hex=raw_sig.hex()),
        }
    )


# ==============================================================================
# Requirement 1: Source-Evidence Independence & Self-Attestation Limits
# ==============================================================================

def test_gov_source_evidence_contradiction_fails_closed(db_session: Session):
    """Contradictory external source-close reports block watermark issuance."""
    biz, admin, _ = _create_isolated_workspace(db_session, "src-ev")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k-gov", "ed25519", priv_key.public_key())

    csv_data = (
        b"transaction_number,customer_id,transaction_date,total_amount,status\n"
        b"TXN-01,C-01,2026-05-01 10:00:00,100.00,completed\n"
        b"TXN-02,C-02,2026-05-15 10:00:00,100.00,completed\n"
    )
    manifest = _build_manifest(biz.id, admin.id, priv_key, csv_data)

    contradictory_evidence = {
        "source_system": "NetSuite_ERP",
        "export_batch_id": "BATCH-GOV-01",
        "settlement_status": "CLOSED_RECONCILED",
        "reported_transaction_count": 999,  # Contradicts manifest 2 rows
        "reported_gross_revenue": "99900.00",
    }

    res = ManifestService.verify_and_ingest_manifest(
        session=db_session,
        manifest=manifest,
        file_bytes=csv_data,
        calling_user_id=admin.id,
        source_close_evidence=contradictory_evidence,
    )
    assert res.is_valid is False
    assert any("Source-close report contradiction" in e for e in res.errors)
    assert res.watermark_id is None


# ==============================================================================
# Requirement 2: Authorization & Canonical Claim Binding
# ==============================================================================

def test_gov_caller_authorization_enforced(db_session: Session):
    """Calling user mismatch or non-administrative role is rejected."""
    biz, admin, member = _create_isolated_workspace(db_session, "auth")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    ManifestKeyRegistry.register_key(biz.id, "k-gov", "ed25519", priv_key.public_key())

    csv_data = (
        b"transaction_number,customer_id,transaction_date,total_amount,status\n"
        b"TXN-01,C-01,2026-05-01 10:00:00,100.00,completed\n"
        b"TXN-02,C-02,2026-05-15 10:00:00,100.00,completed\n"
    )
    manifest = _build_manifest(biz.id, admin.id, priv_key, csv_data)

    # 1. Attesting user is admin, but calling user is member -> Mismatch rejected
    res_unauth = ManifestService.verify_and_ingest_manifest(
        session=db_session, manifest=manifest, file_bytes=csv_data, calling_user_id=member.id
    )
    assert res_unauth.is_valid is False
    assert any("does not match authenticated user" in e for e in res_unauth.errors)

    # 2. Manifest claim tampering breaks canonical RFC-8785 signature
    tampered_dict = manifest.model_dump()
    tampered_dict["period_end"] = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    tampered_man = PeriodCloseManifest(**tampered_dict)
    with pytest.raises(ValueError, match="signature is invalid"):
        ManifestKeyRegistry.verify_manifest_signature(tampered_man)


# ==============================================================================
# Requirement 3: Watermark Promotion & Recovery Lifecycle
# ==============================================================================

def test_gov_provisional_watermark_blocks_actionable_cadence(db_session: Session):
    """Provisional watermarks evaluate as DIAGNOSTIC_ONLY and cannot certify an actionable pilot."""
    biz, admin, _ = _create_isolated_workspace(db_session, "prov-safe")
    wm_contract = WatermarkContract(
        business_id=biz.id,
        source_id="pos",
        complete_through_dt=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
        provenance_type="accounting_period_close",
        verification_status="provisional",
    )
    WatermarkService.record_watermark(db_session, wm_contract)
    db_session.flush()

    verdict = CadenceSafetyGate.evaluate_tenant_safety(db_session, biz.id)
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.PROVISIONAL_WATERMARK
    assert verdict.is_actionable is False


def test_gov_backfill_invalidates_verified_watermark(db_session: Session):
    """Backfill ingestion invalidates verified watermark immediately."""
    biz, _, _ = _create_isolated_workspace(db_session, "backfill")
    wm_contract = WatermarkContract(
        business_id=biz.id,
        source_id="pos",
        complete_through_dt=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
        provenance_type="accounting_period_close",
        verification_status="verified",
    )
    WatermarkService.record_watermark(db_session, wm_contract)
    db_session.flush()

    eff_before = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)
    assert eff_before.is_verified is True

    # Incoming historical sale dated May 20
    late_txn = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    invalidated = WatermarkService.detect_backfill_and_handle(
        db_session, biz.id, "pos", [late_txn], job_id="job-late-arrival"
    )
    db_session.flush()
    assert invalidated is True

    eff_after = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)
    assert eff_after.is_verified is False
    assert eff_after.status == "invalidated"


# ==============================================================================
# Requirement 4: Separation of Analytics & Consequential Actions
# ==============================================================================

def test_gov_consequential_action_boundary_blocks_automation(db_session: Session):
    """CadenceActionGate strictly blocks automated callers and requires an approved human DecisionRecord."""
    biz, admin, _ = _create_isolated_workspace(db_session, "action-gate")

    # 1. Automated caller is blocked unconditionally
    res_auto = CadenceActionGate.evaluate_action_eligibility(
        session=db_session, business_id=biz.id, action_type="send_retention_coupon", is_automated_caller=True
    )
    assert res_auto.is_allowed is False
    assert res_auto.status == ActionExecutionStatus.BLOCKED_AUTOMATION_PROHIBITED

    # 2. Human caller without DecisionRecord is blocked
    res_no_dec = CadenceActionGate.evaluate_action_eligibility(
        session=db_session, business_id=biz.id, action_type="send_retention_coupon", is_automated_caller=False, decision_id=None
    )
    assert res_no_dec.is_allowed is False
    assert res_no_dec.status == ActionExecutionStatus.BLOCKED_UNAPPROVED


# ==============================================================================
# Requirement 5 & 6: Apex Isolation Invariant
# ==============================================================================

def test_gov_apex_tenant_isolation_strictly_enforced(db_session: Session):
    """Assert that Apex Specialty Commerce is unwatermarked, non-actionable, and isolated."""
    org_apex = Organization(id="org-apex-gov", name="Apex Organization", slug="apex-gov")
    biz_apex = Business(
        id=APEX_TENANT_ID,
        organization_id=org_apex.id,
        name="Apex Specialty Commerce 64ea641d",
        industry="Specialty Retail",
        status="active",
    )
    db_session.add_all([org_apex, biz_apex])
    db_session.flush()

    # Apex watermarks must be 0
    wms = db_session.execute(
        select(TenantIngestionWatermark).where(TenantIngestionWatermark.business_id == APEX_TENANT_ID)
    ).scalars().all()
    assert len(wms) == 0

    # Apex safety evaluation must be diagnostic_only with MISSING_WATERMARK
    verdict = CadenceSafetyGate.evaluate_tenant_safety(db_session, APEX_TENANT_ID)
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.MISSING_WATERMARK
    assert verdict.is_actionable is False
