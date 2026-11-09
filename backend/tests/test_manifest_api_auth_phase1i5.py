"""
NEXUS Phase 1I.5 — Manifest API Authentication & Authorization Test Suite (Finding M1).

Validates API boundary security for period-close manifest submission:
1. Unauthenticated requests return 401 Unauthorized.
2. Caller attempting to attest for another user returns 403 Forbidden.
3. Caller from Tenant A attempting to submit for Tenant B returns 403 Forbidden.
4. Member with non-admin role returns 403 Forbidden.
5. Valid owner/admin submission succeeds with 200 OK and records submitted_by_user_id.
6. Replaying the same manifest_id returns 400 Bad Request with replay rejection.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import io
import csv
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, get_db_session
from app.main import app
from app.models.manifest import ManifestSubmission
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.schemas.manifest import (
    ManifestAttestation,
    ManifestSignature,
    PeriodCloseManifest,
    ReconciliationTotals,
)
from app.services.auth_service import AuthService
from app.services.manifest_service import ManifestKeyRegistry, ManifestService


# ==============================================================================
# Helpers
# ==============================================================================

def _create_tenant_and_user(
    session: Session, suffix: str, role: str = "admin"
) -> tuple[Business, UserIdentity, str]:
    """Create tenant org, business, user, and return (business, user, jwt_token)."""
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-api-{suffix}-{uid}", name=f"API Org {suffix}", slug=f"api-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-rh-{suffix}-{uid}",
        organization_id=org.id,
        name=f"API Rehearsal {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-api-{suffix}-{uid}",
        email=f"api_{suffix}_{uid}@example.com",
        full_name=f"API User {suffix}",
        password_hash="mock_hash",
        is_active=True,
        is_verified=True,
    )
    session.add_all([org, biz, user])
    session.flush()

    mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role=role)
    session.add(mem)
    session.commit()

    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        organization_id=org.id,
        business_id=biz.id,
    )
    return biz, user, token


def _build_manifest(
    biz_id: str,
    user_id: str,
    priv_key: ed25519.Ed25519PrivateKey,
    file_bytes: bytes,
    period_start: datetime,
    period_end: datetime,
    row_count: int,
    gross_total: Decimal,
    key_id: str = "key-api-01",
) -> PeriodCloseManifest:
    """Build and sign PeriodCloseManifest."""
    file_sha256 = ManifestService.compute_file_sha256(file_bytes)
    man_placeholder = PeriodCloseManifest(
        manifest_id=str(uuid4()),
        business_id=biz_id,
        source_id="pos",
        batch_id="BATCH-API-001",
        provenance_type="accounting_period_close",
        period_start=period_start,
        period_end=period_end,
        source_export_id="EXP-API-001",
        export_completed_at=period_end + timedelta(minutes=5),
        file_name="sales_api.csv",
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


def _generate_csv(rows: list[tuple[str, str, datetime, Decimal, str]]) -> str:
    """Generate CSV text string from rows."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["transaction_number", "customer_id", "transaction_date", "total_amount", "status"])
    for r in rows:
        writer.writerow([r[0], r[1], r[2].strftime("%Y-%m-%d %H:%M:%S"), f"{r[3]:.2f}", r[4]])
    return buf.getvalue()


# ==============================================================================
# API Auth Tests (M1)
# ==============================================================================

def test_api_unauthenticated_request_returns_401(db_session: Session):
    """M1: Unauthenticated request to /api/v1/gateway/manifest/submit returns 401 Unauthorized."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.post("/api/v1/gateway/manifest/submit", json={})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_api_caller_attesting_for_another_user_returns_403(db_session: Session):
    """M1: Authenticated caller attempting to attest for a different user returns 403 Forbidden."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    try:
        biz, user_caller, token = _create_tenant_and_user(db_session, "auth-diff")
        other_user = UserIdentity(
            id=f"usr-diff-{uuid4().hex[:8]}",
            email="other@example.com",
            full_name="Other User",
            password_hash="mock",
            is_active=True,
            is_verified=True,
        )
        db_session.add(other_user)
        db_session.commit()

        start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
        csv_text = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])

        priv_key = ed25519.Ed25519PrivateKey.generate()
        ManifestKeyRegistry.register_key(biz.id, "key-diff", "ed25519", priv_key.public_key(), session=db_session)

        # Manifest claims attested_by other_user, but caller is user_caller
        manifest = _build_manifest(biz.id, other_user.id, priv_key, csv_text.encode("utf-8"), start, end, 1, Decimal("100.00"), key_id="key-diff")

        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "manifest": manifest.model_dump(mode="json"),
            "file_content_text": csv_text,
        }

        response = client.post("/api/v1/gateway/manifest/submit", json=payload, headers=headers)
        assert response.status_code == 403
        assert "cannot attest on behalf of user" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_api_caller_from_other_tenant_returns_403(db_session: Session):
    """M1: Caller from Tenant A attempting to submit for Tenant B returns 403 Forbidden."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    try:
        biz_a, user_a, token_a = _create_tenant_and_user(db_session, "tenant-a")
        biz_b, user_b, token_b = _create_tenant_and_user(db_session, "tenant-b")

        start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
        csv_text = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])

        priv_key = ed25519.Ed25519PrivateKey.generate()
        ManifestKeyRegistry.register_key(biz_b.id, "key-b", "ed25519", priv_key.public_key(), session=db_session)

        # Manifest is for Tenant B, but submitted with Tenant A token
        manifest = _build_manifest(biz_b.id, user_a.id, priv_key, csv_text.encode("utf-8"), start, end, 1, Decimal("100.00"), key_id="key-b")

        headers = {"Authorization": f"Bearer {token_a}"}
        payload = {
            "manifest": manifest.model_dump(mode="json"),
            "file_content_text": csv_text,
        }

        response = client.post("/api/v1/gateway/manifest/submit", json=payload, headers=headers)
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_api_non_admin_member_returns_403(db_session: Session):
    """M1: User with role 'member' attempting to submit period-close manifest returns 403 Forbidden."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    try:
        biz, user_mem, token_mem = _create_tenant_and_user(db_session, "role-mem", role="member")

        start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
        csv_text = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])

        priv_key = ed25519.Ed25519PrivateKey.generate()
        ManifestKeyRegistry.register_key(biz.id, "key-mem", "ed25519", priv_key.public_key(), session=db_session)

        manifest = _build_manifest(biz.id, user_mem.id, priv_key, csv_text.encode("utf-8"), start, end, 1, Decimal("100.00"), key_id="key-mem")

        headers = {"Authorization": f"Bearer {token_mem}"}
        payload = {
            "manifest": manifest.model_dump(mode="json"),
            "file_content_text": csv_text,
        }

        response = client.post("/api/v1/gateway/manifest/submit", json=payload, headers=headers)
        assert response.status_code == 403
        assert "Only organization 'owner' or 'admin'" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_api_valid_admin_submission_succeeds_and_records_submitter(db_session: Session):
    """M1/M2: Valid admin submission succeeds (200 OK) and persists submitted_by_user_id."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    try:
        biz, user_admin, token_admin = _create_tenant_and_user(db_session, "valid-admin", role="admin")

        start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
        csv_text = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])

        priv_key = ed25519.Ed25519PrivateKey.generate()
        ManifestKeyRegistry.register_key(biz.id, "key-admin", "ed25519", priv_key.public_key(), session=db_session)

        manifest = _build_manifest(biz.id, user_admin.id, priv_key, csv_text.encode("utf-8"), start, end, 1, Decimal("100.00"), key_id="key-admin")

        evidence = {
            "source_system": "pos",
            "export_batch_id": "BATCH-API-001",
            "settlement_status": "CLOSED_RECONCILED",
            "reported_transaction_count": 1,
            "reported_gross_revenue": "100.00",
        }

        headers = {"Authorization": f"Bearer {token_admin}"}
        payload = {
            "manifest": manifest.model_dump(mode="json"),
            "file_content_text": csv_text,
            "source_close_evidence": evidence,
        }

        response = client.post("/api/v1/gateway/manifest/submit", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert data["verification_status"] == "provisional"

        # Check DB audit ledger: submitted_by_user_id is recorded
        sub = db_session.execute(
            select(ManifestSubmission).where(ManifestSubmission.manifest_id == manifest.manifest_id)
        ).scalar_one_or_none()
        assert sub is not None
        assert sub.submitted_by_user_id == user_admin.id
        assert sub.attested_by_user_id == user_admin.id
    finally:
        app.dependency_overrides.clear()


def test_api_replay_manifest_returns_400(db_session: Session):
    """M2: Replaying the same manifest_id returns 400 Bad Request."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_db_session] = lambda: db_session
    client = TestClient(app)

    try:
        biz, user_admin, token_admin = _create_tenant_and_user(db_session, "replay-test", role="admin")

        start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
        csv_text = _generate_csv([("TXN-1", "C-1", start + timedelta(days=1), Decimal("100.00"), "completed")])

        priv_key = ed25519.Ed25519PrivateKey.generate()
        ManifestKeyRegistry.register_key(biz.id, "key-rep-api", "ed25519", priv_key.public_key(), session=db_session)

        manifest = _build_manifest(biz.id, user_admin.id, priv_key, csv_text.encode("utf-8"), start, end, 1, Decimal("100.00"), key_id="key-rep-api")

        headers = {"Authorization": f"Bearer {token_admin}"}
        payload = {
            "manifest": manifest.model_dump(mode="json"),
            "file_content_text": csv_text,
        }

        # First submission succeeds
        res1 = client.post("/api/v1/gateway/manifest/submit", json=payload, headers=headers)
        assert res1.status_code == 200

        # Replay attempt fails with 400
        res2 = client.post("/api/v1/gateway/manifest/submit", json=payload, headers=headers)
        assert res2.status_code == 400
        assert "Manifest replay rejected" in res2.json()["detail"]
    finally:
        app.dependency_overrides.clear()
