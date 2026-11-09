"""
NEXUS Phase 1 End-to-End Production Readiness — Key Management Service and Envelope Encryption Boundary.

Provides:
1. KMSProvider (ABC): Contract for master key management outside PostgreSQL.
2. LocalDevelopmentKMSProvider: Isolated testing & local development KMS (strictly prohibited in production).
3. AWSKMSProvider: Production AWS Key Management Service (AWS KMS) integration driver.
4. GCPKMSProvider: Production Google Cloud KMS integration driver.
5. VaultKMSProvider: Production HashiCorp Vault transit secrets engine integration driver.
6. get_kms_provider(): Factory enforcing fail-closed cloud KMS requirement in production.
7. EnvelopeEncryptionEngine: Authenticated AES-256-GCM envelope encryption with 12-byte random nonces,
   tenant-scoped Authenticated Associated Data (AAD) binding, and key rotation/re-encryption.
"""

import base64
import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


class KMSError(RuntimeError):
    """Base exception for Key Management Service operations."""


class KMSUnavailableError(KMSError):
    """Raised when the KMS service is unreachable, unconfigured, or key is missing."""


class CredentialDecryptionError(KMSError):
    """Raised when ciphertext cannot be authenticated or decrypted."""


class KMSProvider(ABC):
    """
    Abstract Base Class for Master Key Management outside PostgreSQL.
    """

    @abstractmethod
    def encrypt_dek(
        self,
        plaintext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        """
        Encrypt a 256-bit Data Encryption Key (DEK) using the specified master key.
        """

    @abstractmethod
    def decrypt_dek(
        self,
        ciphertext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        """
        Decrypt a Data Encryption Key (DEK) using the specified master key.
        """

    @abstractmethod
    def get_active_key_version(self, key_id: str) -> str:
        """
        Return the current active version string for the given key_id.
        """

    def revoke_key(self, key_id: str) -> None:
        """Revoke a master key version so subsequent decryptions fail closed."""


class LocalDevelopmentKMSProvider(KMSProvider):
    """
    Local testing & development KMS implementation.
    STRICTLY PROHIBITED in production environments (enforced fail-closed guard).
    """

    def __init__(self, master_keys: dict[str, bytes] | None = None):
        app_env = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
        if app_env in ("production", "prod"):
            raise KMSError(
                "Security Violation: LocalDevelopmentKMSProvider is strictly prohibited in production. "
                "A managed cloud KMS provider (AWS KMS, GCP KMS, or Vault) must be configured."
            )

        self._revoked_keys: set[str] = set()

        # In-memory dictionary of key_id -> 256-bit AES master key
        if master_keys:
            self._keys = dict(master_keys)
        else:
            default_key = os.getenv("NEXUS_DEV_KMS_MASTER_KEY")
            if default_key:
                try:
                    key_bytes = base64.b64decode(default_key)
                    if len(key_bytes) != 32:
                        key_bytes = hashlib.sha256(key_bytes).digest()
                except Exception:  # noqa: BLE001
                    key_bytes = hashlib.sha256(default_key.encode("utf-8")).digest()
            else:
                key_bytes = hashlib.sha256(b"nexus_dev_master_key_seed_256bits").digest()

            self._keys = {
                "local_kms_vault": key_bytes,
                "local_kms_vault:v1": key_bytes,
            }

        self.is_available = True

    def encrypt_dek(
        self,
        plaintext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        if not self.is_available:
            raise KMSUnavailableError("KMS service unavailable: connection refused to key vault.")

        if key_id in self._revoked_keys or key_id.split(":")[0] in self._revoked_keys:
            raise KMSUnavailableError(f"Master key '{key_id}' has been revoked.")

        raw_key = self._keys.get(key_id) or self._keys.get(key_id.split(":")[0])
        if not raw_key:
            raise KMSUnavailableError(f"Master key '{key_id}' not found in KMS provider.")

        aes = AESGCM(raw_key)
        nonce = os.urandom(12)
        ct = aes.encrypt(nonce, plaintext_dek, key_id.encode("utf-8"))
        # Prepend 12-byte nonce
        return nonce + ct

    def decrypt_dek(
        self,
        ciphertext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        if not self.is_available:
            raise KMSUnavailableError("KMS service unavailable: connection refused to key vault.")

        if key_id in self._revoked_keys or key_id.split(":")[0] in self._revoked_keys:
            raise KMSUnavailableError(f"Master key '{key_id}' has been revoked.")

        raw_key = self._keys.get(key_id) or self._keys.get(key_id.split(":")[0])
        if not raw_key:
            raise KMSUnavailableError(f"Master key '{key_id}' not found in KMS provider.")

        if len(ciphertext_dek) < 28:
            raise CredentialDecryptionError("Ciphertext DEK payload is truncated or corrupted.")

        nonce = ciphertext_dek[:12]
        ct = ciphertext_dek[12:]
        aes = AESGCM(raw_key)
        try:
            return aes.decrypt(nonce, ct, key_id.encode("utf-8"))
        except InvalidTag:
            raise CredentialDecryptionError(f"Failed to decrypt DEK: invalid tag or wrong master key for '{key_id}'.")

    def get_active_key_version(self, key_id: str) -> str:
        if ":" in key_id:
            return key_id
        matching_keys = [k for k in self._keys if k.startswith(f"{key_id}:")]
        if matching_keys:
            return max(matching_keys)
        return f"{key_id}:v1"

    def register_key(self, key_id: str, key_bytes: bytes) -> None:
        """Register or rotate a key version for testing."""
        if len(key_bytes) != 32:
            raise ValueError("Master key must be exactly 32 bytes (256 bits).")
        self._keys[key_id] = key_bytes

    def revoke_key(self, key_id: str) -> None:
        """Revoke a master key version."""
        self._revoked_keys.add(key_id)

    def __repr__(self) -> str:
        keys_summary = sorted(self._keys.keys())
        return f"<LocalDevelopmentKMSProvider active_keys={keys_summary} revoked={sorted(self._revoked_keys)} (raw secrets redacted)>"


class AWSKMSProvider(KMSProvider):
    """
    Production AWS Key Management Service (AWS KMS) Provider.
    Delegates master key envelope operations to AWS KMS via boto3.
    """

    def __init__(
        self,
        region_name: str | None = None,
        key_arn: str | None = None,
        kms_client: Any = None,
    ):
        self.region_name = region_name or os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION")
        self.key_arn = key_arn or os.getenv("AWS_KMS_KEY_ARN") or os.getenv("NEXUS_AWS_KMS_KEY_ARN")
        self._client = kms_client
        self._revoked_keys: set[str] = set()

        if not self.region_name:
            raise KMSUnavailableError(
                "AWS KMS Configuration Error: 'AWS_DEFAULT_REGION' or 'AWS_REGION' is required."
            )
        if not self.key_arn:
            raise KMSUnavailableError(
                "AWS KMS Configuration Error: 'AWS_KMS_KEY_ARN' or 'NEXUS_AWS_KMS_KEY_ARN' is required."
            )

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client("kms", region_name=self.region_name)
            except ImportError:
                raise KMSUnavailableError("boto3 package is required for AWSKMSProvider.")
            except Exception as e:  # noqa: BLE001
                raise KMSUnavailableError(f"Failed to initialize AWS KMS client: {e}")
        return self._client

    def encrypt_dek(
        self,
        plaintext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        target_key = key_id if key_id and "arn:aws:kms" in key_id else self.key_arn
        if target_key in self._revoked_keys or key_id in self._revoked_keys:
            raise KMSUnavailableError(f"AWS KMS key '{key_id}' is revoked.")
        kwargs: dict[str, Any] = {"KeyId": target_key, "Plaintext": plaintext_dek}
        if encryption_context:
            kwargs["EncryptionContext"] = encryption_context
        try:
            response = self.client.encrypt(**kwargs)
            return response["CiphertextBlob"]
        except Exception as e:  # noqa: BLE001
            raise KMSUnavailableError(f"AWS KMS encrypt_dek failed for '{key_id}': {e}")

    def decrypt_dek(
        self,
        ciphertext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        target_key = key_id if key_id and "arn:aws:kms" in key_id else self.key_arn
        if target_key in self._revoked_keys or key_id in self._revoked_keys:
            raise KMSUnavailableError(f"AWS KMS key '{key_id}' is revoked.")
        kwargs: dict[str, Any] = {"CiphertextBlob": ciphertext_dek, "KeyId": target_key}
        if encryption_context:
            kwargs["EncryptionContext"] = encryption_context
        try:
            response = self.client.decrypt(**kwargs)
            return response["Plaintext"]
        except Exception as e:  # noqa: BLE001
            raise CredentialDecryptionError(f"AWS KMS decrypt_dek failed for '{key_id}': {e}")

    def get_active_key_version(self, key_id: str) -> str:
        return key_id or self.key_arn

    def revoke_key(self, key_id: str) -> None:
        self._revoked_keys.add(key_id)

    def __repr__(self) -> str:
        masked_arn = f"{self.key_arn[:25]}...***" if self.key_arn and len(self.key_arn) > 25 else "***"
        return f"<AWSKMSProvider region={self.region_name} key_arn={masked_arn} (credentials redacted)>"


class GCPKMSProvider(KMSProvider):
    """
    Production Google Cloud KMS Provider.
    Delegates master key operations to Cloud KMS KeyManagementServiceClient.
    """

    def __init__(
        self,
        project_id: str | None = None,
        location_id: str | None = None,
        key_ring_id: str | None = None,
        key_id: str | None = None,
        key_name: str | None = None,
        kms_client: Any = None,
    ):
        self.key_name = key_name or os.getenv("GCP_KMS_KEY_NAME") or os.getenv("NEXUS_GCP_KMS_KEY_NAME")
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.location_id = location_id or os.getenv("GCP_LOCATION_ID")
        self.key_ring_id = key_ring_id or os.getenv("GCP_KEY_RING_ID")
        self.key_id = key_id or os.getenv("GCP_KEY_ID")
        self._client = kms_client
        self._revoked_keys: set[str] = set()

        if not self.key_name:
            if not all([self.project_id, self.location_id, self.key_ring_id, self.key_id]):
                raise KMSUnavailableError(
                    "GCP KMS Configuration Error: 'GCP_KMS_KEY_NAME' or (project_id, location_id, key_ring_id, key_id) is required."
                )
            self.key_name = f"projects/{self.project_id}/locations/{self.location_id}/keyRings/{self.key_ring_id}/cryptoKeys/{self.key_id}"

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import kms_v1
                self._client = kms_v1.KeyManagementServiceClient()
            except ImportError:
                raise KMSUnavailableError("google-cloud-kms package is required for GCPKMSProvider.")
            except Exception as e:  # noqa: BLE001
                raise KMSUnavailableError(f"Failed to initialize GCP KMS client: {e}")
        return self._client

    def encrypt_dek(
        self,
        plaintext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        target_name = key_id if "projects/" in key_id else self.key_name
        if target_name in self._revoked_keys or key_id in self._revoked_keys:
            raise KMSUnavailableError(f"GCP KMS key '{key_id}' is revoked.")
        aad = json.dumps(encryption_context, sort_keys=True).encode() if encryption_context else None
        try:
            req: dict[str, Any] = {"name": target_name, "plaintext": plaintext_dek}
            if aad:
                req["additional_authenticated_data"] = aad
            response = self.client.encrypt(request=req)
            return response.ciphertext
        except Exception as e:  # noqa: BLE001
            raise KMSUnavailableError(f"GCP KMS encrypt_dek failed for '{key_id}': {e}")

    def decrypt_dek(
        self,
        ciphertext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        target_name = key_id if "projects/" in key_id else self.key_name
        if target_name in self._revoked_keys or key_id in self._revoked_keys:
            raise KMSUnavailableError(f"GCP KMS key '{key_id}' is revoked.")
        aad = json.dumps(encryption_context, sort_keys=True).encode() if encryption_context else None
        try:
            req: dict[str, Any] = {"name": target_name, "ciphertext": ciphertext_dek}
            if aad:
                req["additional_authenticated_data"] = aad
            response = self.client.decrypt(request=req)
            return response.plaintext
        except Exception as e:  # noqa: BLE001
            raise CredentialDecryptionError(f"GCP KMS decrypt_dek failed for '{key_id}': {e}")

    def get_active_key_version(self, key_id: str) -> str:
        return key_id or self.key_name

    def revoke_key(self, key_id: str) -> None:
        self._revoked_keys.add(key_id)

    def __repr__(self) -> str:
        masked_name = f"{self.key_name[:30]}...***" if self.key_name and len(self.key_name) > 30 else "***"
        return f"<GCPKMSProvider key_name={masked_name} (credentials redacted)>"


class VaultKMSProvider(KMSProvider):
    """
    Production HashiCorp Vault Transit Engine KMS Provider.
    Uses Vault's transit secrets engine for cryptographic operations.
    """

    def __init__(
        self,
        vault_addr: str | None = None,
        token: str | None = None,
        transit_key: str | None = None,
        vault_client: Any = None,
    ):
        self.vault_addr = vault_addr or os.getenv("VAULT_ADDR")
        self._token = token or os.getenv("VAULT_TOKEN")
        self.transit_key = transit_key or os.getenv("VAULT_TRANSIT_KEY") or "nexus-connector-master"
        self._client = vault_client
        self._revoked_keys: set[str] = set()

        if not self.vault_addr:
            raise KMSUnavailableError("Vault KMS Configuration Error: 'VAULT_ADDR' is required.")
        if not self._token:
            raise KMSUnavailableError("Vault KMS Configuration Error: 'VAULT_TOKEN' is required.")

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import hvac
                self._client = hvac.Client(url=self.vault_addr, token=self._token)
            except ImportError:
                raise KMSUnavailableError("hvac package is required for VaultKMSProvider.")
            except Exception as e:  # noqa: BLE001
                raise KMSUnavailableError(f"Failed to initialize Vault client: {e}")
        return self._client

    def encrypt_dek(
        self,
        plaintext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        target_key = key_id or self.transit_key
        if target_key in self._revoked_keys:
            raise KMSUnavailableError(f"Vault transit key '{target_key}' is revoked.")
        context_b64 = (
            base64.b64encode(json.dumps(encryption_context, sort_keys=True).encode()).decode()
            if encryption_context
            else None
        )
        try:
            pt_b64 = base64.b64encode(plaintext_dek).decode()
            kwargs: dict[str, Any] = {"name": target_key, "plaintext": pt_b64}
            if context_b64:
                kwargs["context"] = context_b64
            res = self.client.secrets.transit.encrypt_data(**kwargs)
            return res["data"]["ciphertext"].encode("utf-8")
        except Exception as e:  # noqa: BLE001
            raise KMSUnavailableError(f"Vault encrypt_dek failed for '{key_id}': {e}")

    def decrypt_dek(
        self,
        ciphertext_dek: bytes,
        key_id: str,
        encryption_context: dict[str, str] | None = None,
    ) -> bytes:
        target_key = key_id or self.transit_key
        if target_key in self._revoked_keys:
            raise KMSUnavailableError(f"Vault transit key '{target_key}' is revoked.")
        context_b64 = (
            base64.b64encode(json.dumps(encryption_context, sort_keys=True).encode()).decode()
            if encryption_context
            else None
        )
        try:
            ct_str = ciphertext_dek.decode("utf-8")
            kwargs: dict[str, Any] = {"name": target_key, "ciphertext": ct_str}
            if context_b64:
                kwargs["context"] = context_b64
            res = self.client.secrets.transit.decrypt_data(**kwargs)
            return base64.b64decode(res["data"]["plaintext"])
        except Exception as e:  # noqa: BLE001
            raise CredentialDecryptionError(f"Vault decrypt_dek failed for '{key_id}': {e}")

    def get_active_key_version(self, key_id: str) -> str:
        return key_id or self.transit_key

    def revoke_key(self, key_id: str) -> None:
        self._revoked_keys.add(key_id)

    def __repr__(self) -> str:
        return f"<VaultKMSProvider vault_addr={self.vault_addr} transit_key={self.transit_key} (token redacted)>"


def get_kms_provider(
    provider_name: str | None = None,
    app_env: str | None = None,
) -> KMSProvider:
    """
    Factory resolving active Key Management Service provider.
    Enforces strict fail-closed boundary:
    1. If APP_ENV or ENVIRONMENT is 'production':
       - LocalDevelopmentKMSProvider is strictly prohibited.
       - If no cloud provider or 'local_dev' is specified, raises KMSError.
       - Selected cloud provider must be valid and authenticated.
    2. In non-production environments:
       - Defaults to LocalDevelopmentKMSProvider.
       - Allows cloud KMS if explicitly configured.
    """
    env = (app_env or os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development").strip().lower()
    is_production = env in ("production", "prod")

    requested = (provider_name or os.getenv("NEXUS_KMS_PROVIDER") or "").strip().lower()

    if is_production:
        if not requested or requested in ("local", "local_dev", "development"):
            raise KMSError(
                "CRITICAL SECURITY VIOLATION: Production environment requires an authenticated managed cloud KMS provider "
                "('aws', 'gcp', or 'vault'). LocalDevelopmentKMSProvider is strictly prohibited in production."
            )

        if requested == "aws":
            return AWSKMSProvider()
        elif requested == "gcp":
            return GCPKMSProvider()
        elif requested == "vault":
            return VaultKMSProvider()
        else:
            raise KMSError(
                f"Unsupported production KMS provider '{requested}'. Supported: 'aws', 'gcp', 'vault'."
            )

    # Non-production environments (development, test, staging)
    if requested == "aws":
        return AWSKMSProvider()
    elif requested == "gcp":
        return GCPKMSProvider()
    elif requested == "vault":
        return VaultKMSProvider()

    # Default to LocalDevelopmentKMSProvider for dev/test
    return LocalDevelopmentKMSProvider()


class EnvelopeEncryptionEngine:
    """
    Authenticated AES-256-GCM Envelope Encryption Engine.

    Features:
    1. Authenticated Encryption: AES-256-GCM with 128-bit authentication tag.
    2. Unique Nonces: 12-byte cryptographically secure random nonces per encryption call.
    3. Tenant & Account AAD Binding: Authenticated Associated Data binds:
       business_id || provider || provider_account_id || key_version
       This prevents ciphertext transplant attacks across tenants or providers.
    4. Master-Key Context Binding: Passes encryption context to KMS provider for defense-in-depth.
    5. Key Versioning & Seamless In-Memory Re-encryption: Tracks versions and enables zero-leak rotation.
    """

    @classmethod
    def compute_aad(
        cls,
        business_id: str,
        provider: str,
        provider_account_id: str,
        key_version: str,
    ) -> bytes:
        """
        Compute deterministic Authenticated Associated Data (AAD) for the encryption envelope.
        """
        aad_str = f"{business_id}|{provider}|{provider_account_id}|{key_version}"
        return aad_str.encode("utf-8")

    @classmethod
    def encrypt_credentials(
        cls,
        credential_dict: dict[str, Any],
        business_id: str,
        provider: str,
        provider_account_id: str,
        kms_provider: KMSProvider,
        kms_key_id: str = "local_kms_vault",
    ) -> str:
        """
        Encrypt tenant credentials using authenticated AES-256-GCM envelope encryption.
        Returns a JSON envelope string safe for database storage.
        """
        # 1. Generate ephemeral 256-bit Data Encryption Key (DEK)
        dek = AESGCM.generate_key(bit_length=256)

        # 2. Encrypt DEK using KMS provider with encryption context
        key_version = kms_provider.get_active_key_version(kms_key_id)
        encryption_context = {
            "business_id": business_id,
            "provider": provider,
            "provider_account_id": provider_account_id,
            "key_version": key_version,
        }
        try:
            encrypted_dek = kms_provider.encrypt_dek(
                plaintext_dek=dek,
                key_id=key_version,
                encryption_context=encryption_context,
            )
        except TypeError:
            encrypted_dek = kms_provider.encrypt_dek(
                plaintext_dek=dek,
                key_id=key_version,
            )

        # 3. Encrypt payload using AES-256-GCM with random 12-byte nonce and AAD binding
        aesgcm = AESGCM(dek)
        nonce = os.urandom(12)
        aad = cls.compute_aad(business_id, provider, provider_account_id, key_version)

        payload_bytes = json.dumps(credential_dict, sort_keys=True).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, payload_bytes, aad)

        # 4. Assemble envelope
        envelope = {
            "schema_version": "1.0",
            "algorithm": "AES-256-GCM",
            "kms_key_id": kms_key_id,
            "key_version": key_version,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "encrypted_dek": base64.b64encode(encrypted_dek).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

        return json.dumps(envelope, sort_keys=True)

    @classmethod
    def decrypt_credentials(
        cls,
        envelope_str: str,
        business_id: str,
        provider: str,
        provider_account_id: str,
        kms_provider: KMSProvider,
    ) -> dict[str, Any]:
        """
        Decrypt tenant credentials from JSON envelope string.
        Validates authentication tag and AAD binding; fails closed on tampering or cross-tenant transplant.
        """
        try:
            envelope = json.loads(envelope_str)
        except Exception as e:  # noqa: BLE001
            raise CredentialDecryptionError(f"Malformed credential envelope JSON: {e}")

        # Schema and algorithm verification
        if envelope.get("algorithm") != "AES-256-GCM":
            raise CredentialDecryptionError(f"Unsupported algorithm '{envelope.get('algorithm')}'. Expected AES-256-GCM.")

        kms_key_id = envelope.get("kms_key_id")
        key_version = envelope.get("key_version") or kms_key_id

        try:
            nonce = base64.b64decode(envelope["nonce"])
            encrypted_dek = base64.b64decode(envelope["encrypted_dek"])
            ciphertext = base64.b64decode(envelope["ciphertext"])
        except Exception as e:  # noqa: BLE001
            raise CredentialDecryptionError(f"Invalid base64 payload in credential envelope: {e}")

        # 1. Decrypt DEK via KMS with encryption context verification
        encryption_context = {
            "business_id": business_id,
            "provider": provider,
            "provider_account_id": provider_account_id,
            "key_version": key_version,
        }
        try:
            dek = kms_provider.decrypt_dek(
                ciphertext_dek=encrypted_dek,
                key_id=key_version,
                encryption_context=encryption_context,
            )
        except TypeError:
            dek = kms_provider.decrypt_dek(
                ciphertext_dek=encrypted_dek,
                key_id=key_version,
            )

        # 2. Recompute expected AAD
        aad = cls.compute_aad(business_id, provider, provider_account_id, key_version)

        # 3. Authenticate and decrypt ciphertext
        aesgcm = AESGCM(dek)
        try:
            plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, aad)
        except InvalidTag:
            raise CredentialDecryptionError(
                "Credential authentication tag check failed: ciphertext tampered or tenant AAD mismatch."
            )

        try:
            return json.loads(plaintext_bytes.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise CredentialDecryptionError(f"Corrupted plaintext credential JSON: {e}")

    @classmethod
    def reencrypt_credentials(
        cls,
        envelope_str: str,
        business_id: str,
        provider: str,
        provider_account_id: str,
        current_kms: KMSProvider,
        new_kms: KMSProvider,
        new_kms_key_id: str,
    ) -> str:
        """
        Re-encrypt tenant credentials under a new KMS master key or key version
        without exposing or leaking plaintext outside memory.
        """
        decrypted = cls.decrypt_credentials(
            envelope_str=envelope_str,
            business_id=business_id,
            provider=provider,
            provider_account_id=provider_account_id,
            kms_provider=current_kms,
        )
        return cls.encrypt_credentials(
            credential_dict=decrypted,
            business_id=business_id,
            provider=provider,
            provider_account_id=provider_account_id,
            kms_provider=new_kms,
            kms_key_id=new_kms_key_id,
        )
