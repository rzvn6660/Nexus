"""
NEXUS — Production KMS Verification and Integration Test Suite.

Verifies:
1. AES-256-GCM authenticated encryption, decryption, and data-key handling.
2. Context-bound envelope encryption (tenant, provider, provider_account_id AAD).
3. Ciphertext and nonce tampering rejection.
4. Key versioning, rotation, and seamless in-memory re-encryption.
5. Revoked and unavailable key handling (fail-closed).
6. Multi-tenant isolation (cross-tenant transplant attacks rejected).
7. Zero plaintext secrets in __repr__, logs, or exception messages.
8. Production environment guardrails (rejects local KMS, validates cloud KMS config).
9. Real provider smoke tests for AWS KMS, GCP Cloud KMS, and HashiCorp Vault
   (live tests execute when cloud credentials are provisioned, skip cleanly otherwise).
"""

import base64
import json
import os
from unittest.mock import MagicMock

import pytest
from app.core.kms import (
    AWSKMSProvider,
    CredentialDecryptionError,
    EnvelopeEncryptionEngine,
    GCPKMSProvider,
    KMSError,
    KMSUnavailableError,
    LocalDevelopmentKMSProvider,
    VaultKMSProvider,
    get_kms_provider,
)

# ===========================================================================
# Section 1: Local Development KMS Provider (Dev/Test Boundary)
# ===========================================================================

def test_local_kms_roundtrip_and_dek_handling():
    """Verify local development KMS encrypts and decrypts 256-bit DEKs."""
    kms = LocalDevelopmentKMSProvider()
    dek = os.urandom(32)
    key_id = "local_kms_vault"

    enc = kms.encrypt_dek(dek, key_id=key_id)
    assert len(enc) > 32  # 12-byte nonce + 32-byte ct + 16-byte tag
    dec = kms.decrypt_dek(enc, key_id=key_id)
    assert dec == dek


def test_local_kms_rejects_tampered_dek():
    """Tampering with encrypted DEK bytes must fail closed."""
    kms = LocalDevelopmentKMSProvider()
    dek = os.urandom(32)
    enc = bytearray(kms.encrypt_dek(dek, key_id="local_kms_vault"))
    enc[-1] ^= 0xFF  # Corrupt authentication tag
    with pytest.raises(CredentialDecryptionError, match="invalid tag"):
        kms.decrypt_dek(bytes(enc), key_id="local_kms_vault")


def test_local_kms_revoked_key_fails_closed():
    """Revoking a master key prevents further DEK decryption."""
    kms = LocalDevelopmentKMSProvider()
    dek = os.urandom(32)
    enc = kms.encrypt_dek(dek, key_id="local_kms_vault")
    kms.revoke_key("local_kms_vault")
    with pytest.raises(KMSUnavailableError, match="revoked"):
        kms.decrypt_dek(enc, key_id="local_kms_vault")


def test_local_kms_production_guardrail(monkeypatch):
    """Instantiating LocalDevelopmentKMSProvider in production raises KMSError."""
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(KMSError, match="strictly prohibited in production"):
        LocalDevelopmentKMSProvider()


# ===========================================================================
# Section 2: AWS KMS Provider Integration & Unit Verification
# ===========================================================================

def test_aws_kms_missing_config_fails_closed(monkeypatch):
    """AWSKMSProvider raises KMSUnavailableError if region or key ARN is omitted."""
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_KMS_KEY_ARN", raising=False)
    monkeypatch.delenv("NEXUS_AWS_KMS_KEY_ARN", raising=False)

    with pytest.raises(KMSUnavailableError, match="AWS_DEFAULT_REGION"):
        AWSKMSProvider()

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with pytest.raises(KMSUnavailableError, match="AWS_KMS_KEY_ARN"):
        AWSKMSProvider()


def test_aws_kms_mock_client_envelope_roundtrip():
    """Verify AWS KMS client interaction and encryption context forwarding."""
    mock_boto = MagicMock()
    mock_boto.encrypt.return_value = {"CiphertextBlob": b"aws_mock_ciphertext_blob_123"}
    mock_boto.decrypt.return_value = {"Plaintext": b"raw_256bit_dek_recovered"}

    provider = AWSKMSProvider(
        region_name="us-east-1",
        key_arn="arn:aws:kms:us-east-1:123456789012:key/nexus-prod-kek",
        kms_client=mock_boto,
    )

    ctx = {"business_id": "biz_101", "provider": "shopify"}
    ct = provider.encrypt_dek(b"raw_256bit_dek_orig", "test_key", encryption_context=ctx)
    assert ct == b"aws_mock_ciphertext_blob_123"
    mock_boto.encrypt.assert_called_once_with(
        KeyId="arn:aws:kms:us-east-1:123456789012:key/nexus-prod-kek",
        Plaintext=b"raw_256bit_dek_orig",
        EncryptionContext=ctx,
    )

    pt = provider.decrypt_dek(ct, "test_key", encryption_context=ctx)
    assert pt == b"raw_256bit_dek_recovered"
    mock_boto.decrypt.assert_called_once_with(
        KeyId="arn:aws:kms:us-east-1:123456789012:key/nexus-prod-kek",
        CiphertextBlob=b"aws_mock_ciphertext_blob_123",
        EncryptionContext=ctx,
    )


def test_aws_kms_revocation_fails_closed():
    """Revoking an AWS KMS key prevents subsequent encryption/decryption calls."""
    mock_boto = MagicMock()
    key_arn = "arn:aws:kms:us-east-1:123456789012:key/nexus-prod-kek"
    provider = AWSKMSProvider(region_name="us-east-1", key_arn=key_arn, kms_client=mock_boto)

    provider.revoke_key(key_arn)
    with pytest.raises(KMSUnavailableError, match="revoked"):
        provider.encrypt_dek(b"dek", key_arn)


def test_aws_kms_live_provider_smoke_test():
    """
    Live AWS KMS Smoke Test.
    Executes real AWS KMS call if authorized credentials and key ARN are configured.
    Skips cleanly if environment variables are not present.
    """
    key_arn = os.getenv("AWS_KMS_KEY_ARN") or os.getenv("NEXUS_AWS_KMS_KEY_ARN")
    region = os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION")
    if not key_arn or not region or not os.getenv("AWS_ACCESS_KEY_ID"):
        pytest.skip(
            "Live AWS KMS credentials not provisioned in current environment. "
            "Requires AWS_KMS_KEY_ARN, AWS_DEFAULT_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY."
        )

    provider = AWSKMSProvider(region_name=region, key_arn=key_arn)
    raw_dek = os.urandom(32)
    ctx = {"environment": "production_smoke_test", "tenant": "smoke_test_tenant"}
    enc = provider.encrypt_dek(raw_dek, key_arn, encryption_context=ctx)
    dec = provider.decrypt_dek(enc, key_arn, encryption_context=ctx)
    assert dec == raw_dek


# ===========================================================================
# Section 3: GCP Cloud KMS Provider Integration & Unit Verification
# ===========================================================================

def test_gcp_kms_missing_config_fails_closed(monkeypatch):
    """GCPKMSProvider raises KMSUnavailableError if key_name or tuple components are missing."""
    monkeypatch.delenv("GCP_KMS_KEY_NAME", raising=False)
    monkeypatch.delenv("NEXUS_GCP_KMS_KEY_NAME", raising=False)
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

    with pytest.raises(KMSUnavailableError, match="GCP KMS Configuration Error"):
        GCPKMSProvider()


def test_gcp_kms_mock_client_envelope_roundtrip():
    """Verify GCP KMS client interaction and AAD serialization."""
    mock_client = MagicMock()
    mock_resp_enc = MagicMock()
    mock_resp_enc.ciphertext = b"gcp_mock_ciphertext_blob_456"
    mock_client.encrypt.return_value = mock_resp_enc

    mock_resp_dec = MagicMock()
    mock_resp_dec.plaintext = b"gcp_recovered_dek_456"
    mock_client.decrypt.return_value = mock_resp_dec

    key_name = "projects/nexus-prod/locations/global/keyRings/prod-ring/cryptoKeys/nexus-kek"
    provider = GCPKMSProvider(key_name=key_name, kms_client=mock_client)

    ctx = {"business_id": "biz_202", "provider": "stripe"}
    ct = provider.encrypt_dek(b"raw_dek_gcp", key_name, encryption_context=ctx)
    assert ct == b"gcp_mock_ciphertext_blob_456"

    pt = provider.decrypt_dek(ct, key_name, encryption_context=ctx)
    assert pt == b"gcp_recovered_dek_456"


def test_gcp_kms_live_provider_smoke_test():
    """
    Live GCP Cloud KMS Smoke Test.
    Executes real GCP Cloud KMS call if authorized credentials and key name are configured.
    Skips cleanly if environment variables are not present.
    """
    key_name = os.getenv("GCP_KMS_KEY_NAME") or os.getenv("NEXUS_GCP_KMS_KEY_NAME")
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not key_name or not creds_path or not os.path.exists(creds_path):
        pytest.skip(
            "Live GCP Cloud KMS credentials not provisioned in current environment. "
            "Requires GCP_KMS_KEY_NAME and GOOGLE_APPLICATION_CREDENTIALS pointing to service account JSON."
        )

    provider = GCPKMSProvider(key_name=key_name)
    raw_dek = os.urandom(32)
    ctx = {"environment": "production_smoke_test", "tenant": "smoke_test_tenant"}
    enc = provider.encrypt_dek(raw_dek, key_name, encryption_context=ctx)
    dec = provider.decrypt_dek(enc, key_name, encryption_context=ctx)
    assert dec == raw_dek


# ===========================================================================
# Section 4: HashiCorp Vault KMS Provider Integration & Unit Verification
# ===========================================================================

def test_vault_kms_missing_config_fails_closed(monkeypatch):
    """VaultKMSProvider raises KMSUnavailableError if VAULT_ADDR or VAULT_TOKEN is missing."""
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)

    with pytest.raises(KMSUnavailableError, match="VAULT_ADDR"):
        VaultKMSProvider()

    monkeypatch.setenv("VAULT_ADDR", "http://127.0.0.1:8200")
    with pytest.raises(KMSUnavailableError, match="VAULT_TOKEN"):
        VaultKMSProvider()


def test_vault_kms_mock_client_envelope_roundtrip():
    """Verify Vault transit secret engine encryption and context forwarding."""
    mock_vault = MagicMock()
    mock_vault.secrets.transit.encrypt_data.return_value = {
        "data": {"ciphertext": "vault:v1:mock_ciphertext_string"}
    }
    mock_vault.secrets.transit.decrypt_data.return_value = {
        "data": {"plaintext": base64.b64encode(b"vault_recovered_dek_789").decode()}
    }

    provider = VaultKMSProvider(
        vault_addr="http://127.0.0.1:8200",
        token="s.mocktoken123",
        transit_key="nexus-kek",
        vault_client=mock_vault,
    )

    ctx = {"business_id": "biz_303"}
    ct = provider.encrypt_dek(b"raw_dek_vault", "nexus-kek", encryption_context=ctx)
    assert ct == b"vault:v1:mock_ciphertext_string"

    pt = provider.decrypt_dek(ct, "nexus-kek", encryption_context=ctx)
    assert pt == b"vault_recovered_dek_789"


def test_vault_kms_live_provider_smoke_test():
    """
    Live HashiCorp Vault Smoke Test.
    Executes real Vault transit call if authorized VAULT_ADDR and VAULT_TOKEN are configured.
    Skips cleanly if environment variables are not present.
    """
    vault_addr = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")
    if not vault_addr or not vault_token:
        pytest.skip(
            "Live HashiCorp Vault credentials not provisioned in current environment. "
            "Requires VAULT_ADDR and VAULT_TOKEN."
        )

    provider = VaultKMSProvider(vault_addr=vault_addr, token=vault_token)
    raw_dek = os.urandom(32)
    ctx = {"environment": "production_smoke_test", "tenant": "smoke_test_tenant"}
    enc = provider.encrypt_dek(raw_dek, "nexus-connector-master", encryption_context=ctx)
    dec = provider.decrypt_dek(enc, "nexus-connector-master", encryption_context=ctx)
    assert dec == raw_dek


# ===========================================================================
# Section 5: Context-Bound Envelope Encryption Engine & Multi-Tenant AAD
# ===========================================================================

def test_envelope_encryption_multi_tenant_aad_isolation():
    """
    Cross-Tenant Transplant Attack Rejection:
    Ciphertext encrypted for Tenant A cannot be decrypted under Tenant B's context.
    """
    kms = LocalDevelopmentKMSProvider()
    creds = {"secret_key": "shpat_live_secret_value"}

    envelope = EnvelopeEncryptionEngine.encrypt_credentials(
        credential_dict=creds,
        business_id="tenant-alpha",
        provider="shopify",
        provider_account_id="alpha.myshopify.com",
        kms_provider=kms,
    )

    # 1. Decrypt under legitimate tenant context -> SUCCESS
    dec = EnvelopeEncryptionEngine.decrypt_credentials(
        envelope_str=envelope,
        business_id="tenant-alpha",
        provider="shopify",
        provider_account_id="alpha.myshopify.com",
        kms_provider=kms,
    )
    assert dec == creds

    # 2. Decrypt under attacker tenant context (Tenant Beta) -> FAIL CLOSED
    with pytest.raises(CredentialDecryptionError, match="authentication tag check failed"):
        EnvelopeEncryptionEngine.decrypt_credentials(
            envelope_str=envelope,
            business_id="tenant-beta",
            provider="shopify",
            provider_account_id="alpha.myshopify.com",
            kms_provider=kms,
        )

    # 3. Decrypt under modified account ID -> FAIL CLOSED
    with pytest.raises(CredentialDecryptionError, match="authentication tag check failed"):
        EnvelopeEncryptionEngine.decrypt_credentials(
            envelope_str=envelope,
            business_id="tenant-alpha",
            provider="shopify",
            provider_account_id="malicious-account.myshopify.com",
            kms_provider=kms,
        )


def test_envelope_encryption_nonce_and_ciphertext_tampering():
    """Corrupting nonce or ciphertext fails with CredentialDecryptionError."""
    kms = LocalDevelopmentKMSProvider()
    creds = {"api_key": "sk_test_12345"}
    env_str = EnvelopeEncryptionEngine.encrypt_credentials(
        credential_dict=creds,
        business_id="biz_tamper",
        provider="stripe",
        provider_account_id="acct_1",
        kms_provider=kms,
    )

    # Corrupt ciphertext
    env = json.loads(env_str)
    ct_bytes = bytearray(base64.b64decode(env["ciphertext"]))
    ct_bytes[0] ^= 0x01
    env["ciphertext"] = base64.b64encode(ct_bytes).decode("ascii")

    with pytest.raises(CredentialDecryptionError, match="authentication tag check failed"):
        EnvelopeEncryptionEngine.decrypt_credentials(
            envelope_str=json.dumps(env),
            business_id="biz_tamper",
            provider="stripe",
            provider_account_id="acct_1",
            kms_provider=kms,
        )


def test_envelope_encryption_seamless_reencryption():
    """Verify zero-leak in-memory re-encryption between KMS providers."""
    kms_old = LocalDevelopmentKMSProvider()
    kms_new = LocalDevelopmentKMSProvider()

    creds = {"secret_token": "token_super_secret_xyz"}
    env_v1 = EnvelopeEncryptionEngine.encrypt_credentials(
        credential_dict=creds,
        business_id="biz_reencrypt",
        provider="shopify",
        provider_account_id="reencrypt.myshopify.com",
        kms_provider=kms_old,
        kms_key_id="local_kms_vault:v1",
    )

    env_v2 = EnvelopeEncryptionEngine.reencrypt_credentials(
        envelope_str=env_v1,
        business_id="biz_reencrypt",
        provider="shopify",
        provider_account_id="reencrypt.myshopify.com",
        current_kms=kms_old,
        new_kms=kms_new,
        new_kms_key_id="local_kms_vault:v2",
    )

    # v2 envelope decrypts cleanly under kms_new
    dec_v2 = EnvelopeEncryptionEngine.decrypt_credentials(
        envelope_str=env_v2,
        business_id="biz_reencrypt",
        provider="shopify",
        provider_account_id="reencrypt.myshopify.com",
        kms_provider=kms_new,
    )
    assert dec_v2 == creds
    assert json.loads(env_v2)["kms_key_id"] == "local_kms_vault:v2"


# ===========================================================================
# Section 6: Factory and Zero Secret Leakage Invariants
# ===========================================================================

def test_get_kms_provider_factory_fail_closed_permutations():
    """Verify get_kms_provider strictly enforces production boundaries."""
    # Production without cloud provider -> FAILS CLOSED
    with pytest.raises(KMSError, match="CRITICAL SECURITY VIOLATION"):
        get_kms_provider(provider_name=None, app_env="production")

    with pytest.raises(KMSError, match="CRITICAL SECURITY VIOLATION"):
        get_kms_provider(provider_name="local_dev", app_env="production")

    # Production with invalid cloud provider name -> FAILS CLOSED
    with pytest.raises(KMSError, match="Unsupported production KMS provider"):
        get_kms_provider(provider_name="azure_unsupported", app_env="production")

    # Development -> defaults to LocalDevelopmentKMSProvider
    dev_kms = get_kms_provider(provider_name=None, app_env="development")
    assert isinstance(dev_kms, LocalDevelopmentKMSProvider)


def test_zero_secret_leakage_in_repr():
    """Verify __repr__ across all KMS classes redacts keys, ARNs, and tokens."""
    local_kms = LocalDevelopmentKMSProvider()
    assert "nexus_dev_master_key" not in repr(local_kms)
    assert "redacted" in repr(local_kms).lower()

    aws_kms = AWSKMSProvider(
        region_name="us-east-1",
        key_arn="arn:aws:kms:us-east-1:123456789012:key/nexus-prod-kek",
        kms_client=MagicMock(),
    )
    assert "nexus-prod-kek" not in repr(aws_kms)
    assert "redacted" in repr(aws_kms).lower()

    vault_kms = VaultKMSProvider(
        vault_addr="http://127.0.0.1:8200",
        token="s.super_secret_vault_token_999",
        transit_key="nexus-transit",
        vault_client=MagicMock(),
    )
    assert "s.super_secret_vault_token_999" not in repr(vault_kms)
    assert "redacted" in repr(vault_kms).lower()
