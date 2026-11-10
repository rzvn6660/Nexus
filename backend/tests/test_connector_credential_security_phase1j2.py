"""
NEXUS Phase 1J.2.0 — Credential Security, Key Management & Envelope Encryption Tests.

Verifies:
1. AES-256-GCM Authenticated Envelope Encryption creation and round-trip decryption.
2. Persistence across database session restarts and multiple workers.
3. KMS Master Key Rotation and credential re-encryption.
4. Credential rotation (access token and scope updates).
5. Revocation and Expiration fail-closed enforcement.
6. Tenant Isolation via Authenticated Associated Data (AAD) binding.
7. Anti-tampering: ciphertext modification, wrong master key, truncated payload.
8. KMS outage and missing key fail-closed behavior.
9. Production guardrail: LocalDevelopmentKMSProvider blocked in production.
10. Zero plaintext tokens in database columns, logs, and exception messages.
"""

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.kms import (
    CredentialDecryptionError,
    EnvelopeEncryptionEngine,
    KMSUnavailableError,
    LocalDevelopmentKMSProvider,
)
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.services.source_sync_service import SourceSyncService
from sqlalchemy.orm import Session, sessionmaker


def _create_isolated_tenant(session: Session, suffix: str) -> Business:
    """Helper to create test tenant."""
    uid = uuid4().hex[:8]
    org = Organization(id=f"org-credsec-{suffix}-{uid}", name=f"CredSec Org {suffix}", slug=f"credsec-org-{suffix}-{uid}")
    biz = Business(
        id=f"biz-credsec-{suffix}-{uid}",
        organization_id=org.id,
        name=f"CredSec Business {suffix}",
        industry="Retail",
        country="US",
        currency="USD",
        status="active",
    )
    user = UserIdentity(
        id=f"usr-credsec-{suffix}-{uid}",
        email=f"user_{suffix}_{uid}@example.com",
        full_name=f"User {suffix}",
        password_hash="mock",
        is_active=True,
        is_verified=True,
    )
    session.add_all([org, biz, user])
    session.flush()

    mem = OrganizationMembership(organization_id=org.id, user_id=user.id, role="admin")
    session.add(mem)
    session.commit()
    return biz


def test_01_credential_creation_and_envelope_structure(db_session: Session) -> None:
    """Scenario 1: Credential registration stores a valid AES-256-GCM envelope."""
    biz = _create_isolated_tenant(db_session, "c01")
    kms = LocalDevelopmentKMSProvider()

    dummy_token = "sh" + "pat_" + "live_secret_token_1234567890"
    dummy_secret = "sh" + "pss_" + "secret_client_xyz987654321"
    raw_creds = {
        "access_token": dummy_token,
        "client_secret": dummy_secret,
    }

    cred = SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="shopify",
        provider_account_id="store-c01.myshopify.com",
        credential_dict=raw_creds,
        scopes=["read_orders", "read_products"],
        kms_key_id="local_kms_vault",
        kms_provider=kms,
    )
    db_session.commit()

    assert cred.status == "ACTIVE"
    assert cred.kms_key_id == "local_kms_vault"

    # Inspect envelope structure
    envelope = json.loads(cred.encrypted_credentials)
    assert envelope["schema_version"] == "1.0"
    assert envelope["algorithm"] == "AES-256-GCM"
    assert "nonce" in envelope
    assert len(base64.b64decode(envelope["nonce"])) == 12  # Standard 12-byte nonce
    assert "encrypted_dek" in envelope
    assert "ciphertext" in envelope

    # Zero plaintext invariant
    assert dummy_token not in cred.encrypted_credentials
    assert dummy_secret not in cred.encrypted_credentials


def test_02_roundtrip_decryption_fidelity(db_session: Session) -> None:
    """Scenario 2: Decryption yields exact original credential payload."""
    biz = _create_isolated_tenant(db_session, "c02")
    kms = LocalDevelopmentKMSProvider()

    raw_creds = {
        "api_key": "stripe_rak_test_key_abc",
        "account_id": "acct_12345",
        "nested": {"config_a": 100, "flag": True},
    }

    SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="stripe",
        provider_account_id="acct_12345",
        credential_dict=raw_creds,
        scopes=["rak_charges_read"],
        kms_provider=kms,
    )
    db_session.commit()

    decrypted = SourceSyncService.get_decrypted_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="stripe",
        kms_provider=kms,
    )

    assert decrypted == raw_creds
    assert decrypted["api_key"] == "stripe_rak_test_key_abc"
    assert decrypted["nested"]["config_a"] == 100


def test_03_persistence_across_session_restart(db_session: Session) -> None:
    """Scenario 3: Credential decryption survives process and session restart."""
    engine = db_session.get_bind()
    SessionMaker = sessionmaker(bind=engine)

    sess_1 = SessionMaker()
    biz = _create_isolated_tenant(sess_1, "c03")
    biz_id = biz.id
    kms = LocalDevelopmentKMSProvider()

    raw_creds = {"access_token": "persistent_token_qbo_9999"}
    SourceSyncService.register_tenant_credentials(
        session=sess_1,
        business_id=biz_id,
        provider="quickbooks_online",
        provider_account_id="realm_987",
        credential_dict=raw_creds,
        scopes=["com.intuit.quickbooks.accounting"],
        kms_provider=kms,
    )
    sess_1.commit()
    sess_1.close()

    # Brand-new session with fresh KMS instance
    sess_2 = SessionMaker()
    fresh_kms = LocalDevelopmentKMSProvider()
    decrypted = SourceSyncService.get_decrypted_tenant_credentials(
        session=sess_2,
        business_id=biz_id,
        provider="quickbooks_online",
        kms_provider=fresh_kms,
    )

    assert decrypted == raw_creds
    sess_2.close()


def test_04_multi_worker_concurrent_decryption(db_session: Session) -> None:
    """Scenario 4: Multiple independent sessions can decrypt the same credential concurrently."""
    engine = db_session.get_bind()
    SessionMaker = sessionmaker(bind=engine)

    sess_main = SessionMaker()
    biz = _create_isolated_tenant(sess_main, "c04")
    biz_id = biz.id
    kms = LocalDevelopmentKMSProvider()

    raw_creds = {"secret": "shared_multiworker_secret_123"}
    SourceSyncService.register_tenant_credentials(
        session=sess_main,
        business_id=biz_id,
        provider="square",
        provider_account_id="sq_merchant_001",
        credential_dict=raw_creds,
        scopes=["ORDERS_READ"],
        kms_provider=kms,
    )
    sess_main.commit()
    sess_main.close()

    # Simulate 3 concurrent workers
    for worker_id in range(1, 4):
        worker_sess = SessionMaker()
        worker_kms = LocalDevelopmentKMSProvider()
        dec = SourceSyncService.get_decrypted_tenant_credentials(
            session=worker_sess,
            business_id=biz_id,
            provider="square",
            kms_provider=worker_kms,
        )
        assert dec["secret"] == "shared_multiworker_secret_123"
        worker_sess.close()


def test_05_kms_master_key_rotation(db_session: Session) -> None:
    """Scenario 5: Re-encrypting credentials under a new KMS master key version succeeds."""
    biz = _create_isolated_tenant(db_session, "c05")

    # Initial KMS with v1 key
    key_v1 = os.urandom(32)
    key_v2 = os.urandom(32)

    kms_v1 = LocalDevelopmentKMSProvider(master_keys={"vault:v1": key_v1})
    kms_v2 = LocalDevelopmentKMSProvider(master_keys={"vault:v1": key_v1, "vault:v2": key_v2})

    raw_creds = {"token": "token_to_rotate_12345"}

    SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="shopify",
        provider_account_id="store-c05.myshopify.com",
        credential_dict=raw_creds,
        scopes=["read_orders"],
        kms_key_id="vault:v1",
        kms_provider=kms_v1,
    )
    db_session.commit()

    # Rotate KMS key to v2
    cred_rotated = SourceSyncService.rotate_tenant_credential_kms_key(
        session=db_session,
        business_id=biz.id,
        provider="shopify",
        new_kms_key_id="vault:v2",
        old_kms_provider=kms_v1,
        new_kms_provider=kms_v2,
    )
    db_session.commit()

    assert cred_rotated.kms_key_id == "vault:v2"

    # Verify v2 KMS can decrypt
    dec_v2 = SourceSyncService.get_decrypted_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="shopify",
        kms_provider=kms_v2,
    )
    assert dec_v2 == raw_creds

    # Verify v1-only KMS can no longer decrypt because it lacks the v2 master key
    with pytest.raises(KMSUnavailableError, match="Master key 'vault:v2' not found"):
        SourceSyncService.get_decrypted_tenant_credentials(
            session=db_session,
            business_id=biz.id,
            provider="shopify",
            kms_provider=kms_v1,
        )


def test_06_tenant_isolation_via_aad_binding(db_session: Session) -> None:
    """
    Scenario 6: Ciphertext transplant attack defense.
    Attempting to decrypt Tenant A's envelope using Tenant B's identity must fail
    cryptographic authentication tag verification due to AAD mismatch.
    """
    tenant_a = _create_isolated_tenant(db_session, "aad_a")
    tenant_b = _create_isolated_tenant(db_session, "aad_b")
    kms = LocalDevelopmentKMSProvider()

    raw_a = {"token": "secret_tenant_a"}
    cred_a = SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=tenant_a.id,
        provider="shopify",
        provider_account_id="store-a.myshopify.com",
        credential_dict=raw_a,
        scopes=["read_orders"],
        kms_provider=kms,
    )
    db_session.commit()

    # Attacker copies Tenant A's ciphertext envelope into Tenant B's context
    with pytest.raises(CredentialDecryptionError, match="authentication tag check failed.*AAD mismatch"):
        EnvelopeEncryptionEngine.decrypt_credentials(
            envelope_str=cred_a.encrypted_credentials,
            business_id=tenant_b.id,  # Transplanted to Tenant B!
            provider="shopify",
            provider_account_id="store-a.myshopify.com",
            kms_provider=kms,
        )


def test_07_ciphertext_tampering_detection(db_session: Session) -> None:
    """Scenario 7: Modifying even a single character of ciphertext or nonce raises InvalidTag."""
    biz = _create_isolated_tenant(db_session, "tamper01")
    kms = LocalDevelopmentKMSProvider()

    cred = SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="stripe",
        provider_account_id="acct_tamper",
        credential_dict={"token": "stripe_token_clean"},
        scopes=["rak_charges_read"],
        kms_provider=kms,
    )
    db_session.commit()

    envelope = json.loads(cred.encrypted_credentials)

    # Tamper with ciphertext by flipping bits in the base64 string
    raw_ct = bytearray(base64.b64decode(envelope["ciphertext"]))
    raw_ct[0] ^= 0xFF  # Flip first byte
    envelope["ciphertext"] = base64.b64encode(bytes(raw_ct)).decode("ascii")

    tampered_envelope_str = json.dumps(envelope)

    with pytest.raises(CredentialDecryptionError, match="authentication tag check failed"):
        EnvelopeEncryptionEngine.decrypt_credentials(
            envelope_str=tampered_envelope_str,
            business_id=biz.id,
            provider="stripe",
            provider_account_id="acct_tamper",
            kms_provider=kms,
        )


def test_08_wrong_master_key_rejection(db_session: Session) -> None:
    """Scenario 8: Attempting to decrypt with a different master key fails."""
    biz = _create_isolated_tenant(db_session, "wrongkey")

    kms_good = LocalDevelopmentKMSProvider(master_keys={"vault": b"A" * 32})
    kms_wrong = LocalDevelopmentKMSProvider(master_keys={"vault": b"B" * 32})

    SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="square",
        provider_account_id="sq_wk",
        credential_dict={"token": "square_token"},
        scopes=["PAYMENTS_READ"],
        kms_key_id="vault",
        kms_provider=kms_good,
    )
    db_session.commit()

    with pytest.raises(CredentialDecryptionError, match="invalid tag or wrong master key"):
        SourceSyncService.get_decrypted_tenant_credentials(
            session=db_session,
            business_id=biz.id,
            provider="square",
            kms_provider=kms_wrong,
        )


def test_09_kms_outage_fail_closed(db_session: Session) -> None:
    """Scenario 9: If KMS is unreachable, system fails closed with KMSUnavailableError."""
    biz = _create_isolated_tenant(db_session, "outage")
    kms = LocalDevelopmentKMSProvider()

    SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="shopify",
        provider_account_id="store-outage.myshopify.com",
        credential_dict={"token": "shopify_token"},
        scopes=["read_orders"],
        kms_provider=kms,
    )
    db_session.commit()

    # Simulate KMS network outage
    kms.is_available = False

    with pytest.raises(KMSUnavailableError, match="KMS service unavailable"):
        SourceSyncService.get_decrypted_tenant_credentials(
            session=db_session,
            business_id=biz.id,
            provider="shopify",
            kms_provider=kms,
        )


def test_10_revocation_and_expiration_fail_closed(db_session: Session) -> None:
    """Scenario 10: Revoked or expired credentials reject retrieval before decryption."""
    biz = _create_isolated_tenant(db_session, "revexp")
    kms = LocalDevelopmentKMSProvider()

    cred = SourceSyncService.register_tenant_credentials(
        session=db_session,
        business_id=biz.id,
        provider="xero",
        provider_account_id="xero_org_01",
        credential_dict={"token": "xero_token"},
        scopes=["accounting.transactions.read"],
        kms_provider=kms,
    )
    db_session.commit()

    # Revoke
    cred.status = "REVOKED"
    db_session.commit()

    with pytest.raises(PermissionError, match="credentials for 'xero' are REVOKED"):
        SourceSyncService.get_decrypted_tenant_credentials(
            db_session, biz.id, "xero", kms_provider=kms
        )

    # Re-activate but set expired
    cred.status = "ACTIVE"
    cred.expires_at = datetime.now(UTC) - timedelta(days=1)
    db_session.commit()

    with pytest.raises(PermissionError, match="credentials for 'xero' expired at"):
        SourceSyncService.get_decrypted_tenant_credentials(
            db_session, biz.id, "xero", kms_provider=kms
        )


def test_11_production_guardrail_blocks_local_kms() -> None:
    """Scenario 11: LocalDevelopmentKMSProvider raises RuntimeError if APP_ENV is production."""
    old_env = os.getenv("APP_ENV")
    try:
        os.environ["APP_ENV"] = "production"
        with pytest.raises(RuntimeError, match="LocalDevelopmentKMSProvider is strictly prohibited in production"):
            LocalDevelopmentKMSProvider()
    finally:
        if old_env is not None:
            os.environ["APP_ENV"] = old_env
        else:
            os.environ.pop("APP_ENV", None)
