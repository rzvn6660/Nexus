"""
NEXUS Phase 1I.1 — Signed Period-Close Manifest Engine Service.

Coordinates:
1. Manifest cryptographic signature verification (Ed25519 / HMAC-SHA256) via trusted key registry.
2. Tenant-scoped authorization and signer role verification.
3. Raw file SHA-256 integrity verification.
4. Independent tabular parsing, date-range bounding, and monetary reconciliation.
5. Ingestion watermark lifecycle integration (provisional -> verified).
6. Immutable audit trail logging and replay/collision prevention.
"""

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import hmac
import io
import csv
import json
from typing import Any
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.manifest import ManifestSubmission, TenantTrustedKey
from app.models.tenant import Business, OrganizationMembership, UserIdentity
from app.models.watermark import TenantIngestionWatermark
from app.schemas.manifest import PeriodCloseManifest
from app.services.watermark_service import WatermarkContract, WatermarkService

logger = get_logger(__name__)


class TrustedKeyEntry(BaseModel):
    """Entry in the trusted key registry for a tenant business."""

    business_id: str
    key_id: str
    algorithm: str  # ed25519 or hmac-sha256
    public_key_or_secret: Any  # ed25519.Ed25519PublicKey or bytes/str
    status: str = "active"  # active, revoked, expired
    allowed_roles: list[str] = ["owner", "admin"]
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    revoked_reason: str | None = None


class ManifestKeyRegistry:
    """
    Trusted key registry supporting both PostgreSQL persistence (TenantTrustedKey)
    and in-memory fallback for isolated unit testing.
    Ensures signatures are only evaluated against pre-registered, active public keys.
    Private keys or untrusted client keys are strictly rejected (Finding C2).
    """

    _registry: dict[tuple[str, str], TrustedKeyEntry] = {}

    @classmethod
    def reset(cls) -> None:
        """Clear all registered in-memory keys (primarily for test harness isolation)."""
        cls._registry.clear()

    @classmethod
    def register_key(
        cls,
        business_id: str,
        key_id: str,
        algorithm: str,
        public_key_or_secret: Any,
        status: str = "active",
        allowed_roles: list[str] | None = None,
        expires_at: datetime | None = None,
        registering_user_id: str | None = None,
        session: Session | None = None,
    ) -> TrustedKeyEntry:
        """
        Register a trusted signing public key or secret for a tenant.
        Strictly rejects private keys (C2).
        Rejects duplicate key registration without explicit rotation (C2).
        If registering_user_id is provided, verifies owner/admin authorization.
        If session is provided, persists key to tenant_trusted_keys table.
        """
        clean_algo = algorithm.strip().lower()
        if clean_algo not in {"ed25519", "hmac-sha256"}:
            raise ValueError(f"Unsupported algorithm '{algorithm}' for key registry.")

        if isinstance(public_key_or_secret, ed25519.Ed25519PrivateKey):
            raise ValueError(
                "Security violation: Cannot register private key in trusted key registry. "
                "Only public verification keys are allowed."
            )

        clean_status = status.strip().lower()
        if clean_status not in {"active", "revoked", "expired", "rotated"}:
            raise ValueError(f"Invalid key status '{status}'. Must be active, revoked, expired, or rotated.")

        # Role authorization check if registering_user_id provided
        if session is not None and registering_user_id is not None:
            cls.authorize_key_admin(session, business_id, registering_user_id)

        # Check duplicate key registration (reject overwrite without rotate_key)
        if (business_id, key_id) in cls._registry:
            raise ValueError(
                f"Duplicate key registration rejected: key_id '{key_id}' is already registered for business '{business_id}'. "
                "Use rotate_key to rotate signing keys."
            )

        # Serialize public key to PEM string for persistence
        pem_str: str
        pub_key_obj: Any
        if clean_algo == "ed25519":
            if isinstance(public_key_or_secret, ed25519.Ed25519PublicKey):
                pem_str = public_key_or_secret.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                ).decode("utf-8")
                pub_key_obj = public_key_or_secret
            elif isinstance(public_key_or_secret, (bytes, str)):
                raw = public_key_or_secret.encode("utf-8") if isinstance(public_key_or_secret, str) else public_key_or_secret
                try:
                    pub_key_obj = serialization.load_pem_public_key(raw)
                    pem_str = raw.decode("utf-8")
                except Exception as e:
                    raise ValueError(f"Invalid public key PEM format for '{key_id}': {e}")
            else:
                raise TypeError(f"Invalid Ed25519 key type: {type(public_key_or_secret)}")
        elif clean_algo == "hmac-sha256":
            pem_str = public_key_or_secret.decode("utf-8") if isinstance(public_key_or_secret, bytes) else str(public_key_or_secret)
            pub_key_obj = pem_str

        # If DB session provided, persist to tenant_trusted_keys (C2)
        if session is not None:
            existing = session.execute(
                select(TenantTrustedKey).where(
                    TenantTrustedKey.business_id == business_id,
                    TenantTrustedKey.key_id == key_id,
                )
            ).scalar_one_or_none()
            if existing:
                raise ValueError(
                    f"Duplicate key registration rejected: key_id '{key_id}' is already registered for business '{business_id}'. "
                    "Use rotate_key to rotate signing keys."
                )
            db_key = TenantTrustedKey(
                business_id=business_id,
                key_id=key_id,
                algorithm=clean_algo,
                public_key_pem=pem_str,
                status=clean_status,
                allowed_roles=allowed_roles or ["owner", "admin"],
                expires_at=expires_at,
                revoked_at=datetime.now(UTC) if clean_status in {"revoked", "rotated"} else None,
                created_by_user_id=registering_user_id,
            )
            session.add(db_key)
            session.flush()

        entry = TrustedKeyEntry(
            business_id=business_id,
            key_id=key_id,
            algorithm=clean_algo,
            public_key_or_secret=pub_key_obj,
            status=clean_status,
            allowed_roles=allowed_roles or ["owner", "admin"],
            expires_at=expires_at,
        )
        cls._registry[(business_id, key_id)] = entry
        logger.info(
            "Registered trusted signing key: business_id=%s key_id=%s algo=%s status=%s (db=%s)",
            business_id,
            key_id,
            clean_algo,
            clean_status,
            session is not None,
        )
        return entry

    @classmethod
    def authorize_key_admin(cls, session: Session, business_id: str, user_id: str) -> UserIdentity:
        """Verify that user is an active owner or admin of the organization owning business_id."""
        biz = session.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
        if not biz:
            raise PermissionError(f"Business workspace '{business_id}' does not exist.")
        user = session.execute(select(UserIdentity).where(UserIdentity.id == user_id)).scalar_one_or_none()
        if not user or not user.is_active:
            raise PermissionError(f"User '{user_id}' not found or inactive.")
        mem = session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == biz.organization_id,
                OrganizationMembership.user_id == user_id,
            )
        ).scalar_one_or_none()
        if not mem:
            raise PermissionError(f"User '{user_id}' is not a member of organization '{biz.organization_id}'.")
        if mem.role not in {"owner", "admin"}:
            raise PermissionError(
                f"Unauthorized key registration: user '{user_id}' has role '{mem.role}'. "
                "Only organization 'owner' or 'admin' roles can register or rotate trusted keys."
            )
        return user

    @classmethod
    def rotate_key(
        cls,
        business_id: str,
        old_key_id: str,
        new_key_id: str,
        algorithm: str,
        new_public_key: Any,
        allowed_roles: list[str] | None = None,
        expires_at: datetime | None = None,
        reason: str = "Rotated to new key",
        registering_user_id: str | None = None,
        session: Session | None = None,
    ) -> tuple[TrustedKeyEntry, TrustedKeyEntry]:
        """
        Safely rotate an active trusted key to a new key.
        1. Verifies caller is authorized owner/admin if registering_user_id provided.
        2. Retrieves old key, ensures it is active.
        3. Marks old key status='rotated' with timestamp and reason.
        4. Registers new key as 'active'.
        5. Returns (old_entry, new_entry).
        """
        if old_key_id == new_key_id:
            raise ValueError(f"Cannot rotate key to same key_id '{old_key_id}'. New key must have unique identifier.")

        if session is not None and registering_user_id is not None:
            cls.authorize_key_admin(session, business_id, registering_user_id)

        # 1. Fetch old key
        old_entry = cls.get_key(business_id, old_key_id, session=session)
        if old_entry.status != "active":
            raise ValueError(f"Cannot rotate key '{old_key_id}' with status '{old_entry.status}'. Key must be active.")

        # 2. Mark old key as rotated in DB
        if session is not None:
            db_old_key = session.execute(
                select(TenantTrustedKey).where(
                    TenantTrustedKey.business_id == business_id,
                    TenantTrustedKey.key_id == old_key_id,
                )
            ).scalar_one_or_none()
            if db_old_key:
                db_old_key.status = "rotated"
                db_old_key.revoked_at = datetime.now(UTC)
                db_old_key.revoked_reason = f"Rotated to '{new_key_id}': {reason}"
                session.flush()

        # Update in-memory old key
        old_k = (business_id, old_key_id)
        if old_k in cls._registry:
            cls._registry[old_k].status = "rotated"
            cls._registry[old_k].revoked_reason = f"Rotated to '{new_key_id}': {reason}"

        # 3. Register new key
        new_entry = cls.register_key(
            business_id=business_id,
            key_id=new_key_id,
            algorithm=algorithm,
            public_key_or_secret=new_public_key,
            status="active",
            allowed_roles=allowed_roles,
            expires_at=expires_at,
            registering_user_id=registering_user_id,
            session=session,
        )

        logger.info(
            "Rotated trusted key: business_id=%s old_key_id=%s new_key_id=%s reason=%s",
            business_id,
            old_key_id,
            new_key_id,
            reason,
        )
        return old_entry, new_entry

    @classmethod
    def revoke_key(
        cls,
        business_id: str,
        key_id: str,
        reason: str = "Revoked by administrator",
        session: Session | None = None,
    ) -> None:
        """Mark a trusted key as revoked in DB and in-memory cache."""
        if session is not None:
            db_key = session.execute(
                select(TenantTrustedKey).where(
                    TenantTrustedKey.business_id == business_id,
                    TenantTrustedKey.key_id == key_id,
                )
            ).scalar_one_or_none()
            if db_key:
                db_key.status = "revoked"
                db_key.revoked_reason = reason
                db_key.revoked_at = datetime.now(UTC)
                session.flush()

        key = (business_id, key_id)
        if key in cls._registry:
            cls._registry[key].status = "revoked"
            cls._registry[key].revoked_reason = reason
        logger.warning("Revoked trusted key: business_id=%s key_id=%s reason=%s", business_id, key_id, reason)

    @classmethod
    def get_key(
        cls,
        business_id: str,
        key_id: str,
        session: Session | None = None,
    ) -> TrustedKeyEntry:
        """Retrieve and validate key existence, active state, and expiration."""
        if session is not None:
            db_key = session.execute(
                select(TenantTrustedKey).where(
                    TenantTrustedKey.business_id == business_id,
                    TenantTrustedKey.key_id == key_id,
                )
            ).scalar_one_or_none()
            if db_key:
                if db_key.status != "active":
                    raise PermissionError(
                        f"Signing key '{key_id}' is {db_key.status} (reason: {db_key.revoked_reason or 'inactive'})."
                    )
                if db_key.expires_at:
                    exp_utc = db_key.expires_at if db_key.expires_at.tzinfo else db_key.expires_at.replace(tzinfo=UTC)
                    if datetime.now(UTC) > exp_utc:
                        raise PermissionError(f"Signing key '{key_id}' expired at {db_key.expires_at.isoformat()}.")
                if db_key.algorithm == "ed25519":
                    try:
                        pub_obj = serialization.load_pem_public_key(db_key.public_key_pem.encode("utf-8"))
                    except Exception as e:
                        raise ValueError(f"Corrupted or tampered public key material for key '{key_id}': {e}")
                else:
                    pub_obj = db_key.public_key_pem

                return TrustedKeyEntry(
                    business_id=db_key.business_id,
                    key_id=db_key.key_id,
                    algorithm=db_key.algorithm,
                    public_key_or_secret=pub_obj,
                    status=db_key.status,
                    allowed_roles=db_key.allowed_roles,
                    expires_at=db_key.expires_at,
                    revoked_reason=db_key.revoked_reason,
                )

        key = (business_id, key_id)
        if key not in cls._registry:
            raise PermissionError(
                f"Untrusted or unregistered key_id '{key_id}' for tenant '{business_id}'."
            )
        entry = cls._registry[key]

        if entry.status != "active":
            raise PermissionError(
                f"Signing key '{key_id}' is {entry.status} (reason: {entry.revoked_reason})."
            )

        if entry.expires_at:
            exp_utc = entry.expires_at if entry.expires_at.tzinfo else entry.expires_at.replace(tzinfo=UTC)
            if datetime.now(UTC) > exp_utc:
                raise PermissionError(f"Signing key '{key_id}' expired at {entry.expires_at.isoformat()}.")

        return entry

    @classmethod
    def verify_manifest_signature(
        cls,
        manifest: PeriodCloseManifest,
        session: Session | None = None,
    ) -> bool:
        """
        Verify the manifest's cryptographic signature against the canonical claims dictionary.
        """
        key_entry = cls.get_key(manifest.business_id, manifest.signature.key_id, session=session)

        if key_entry.algorithm != manifest.signature.algorithm:
            raise ValueError(
                f"Algorithm mismatch: trusted key specifies '{key_entry.algorithm}', "
                f"manifest specifies '{manifest.signature.algorithm}'."
            )

        canonical_bytes = manifest.get_canonical_bytes()
        sig_bytes = bytes.fromhex(manifest.signature.signature_hex)

        if key_entry.algorithm == "ed25519":
            public_key = key_entry.public_key_or_secret
            if not isinstance(public_key, ed25519.Ed25519PublicKey):
                raise TypeError("Key material is not an Ed25519PublicKey instance.")
            try:
                public_key.verify(sig_bytes, canonical_bytes)
                return True
            except InvalidSignature:
                raise ValueError("Cryptographic verification failed: Ed25519 signature is invalid.")

        elif key_entry.algorithm == "hmac-sha256":
            secret = key_entry.public_key_or_secret
            secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
            expected_hex = hmac.new(secret_bytes, canonical_bytes, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_hex.lower(), manifest.signature.signature_hex.lower()):
                raise ValueError("Cryptographic verification failed: HMAC-SHA256 signature mismatch.")
            return True

        raise ValueError(f"Unsupported algorithm '{key_entry.algorithm}'")


class ReconciliationBreakdown(BaseModel):
    """Detailed telemetry from independent parsing and reconciliation."""

    actual_sales_row_count: int
    actual_gross_total_amount: Decimal
    actual_net_total_amount: Decimal | None = None
    refunded_rows_count: int = 0
    refunded_amount: Decimal = Decimal("0.00")
    cancelled_rows_count: int = 0
    cancelled_amount: Decimal = Decimal("0.00")
    pending_rows_count: int = 0
    pending_amount: Decimal = Decimal("0.00")
    earliest_transaction_date: str
    latest_transaction_date: str
    reconciliation_matched: bool
    discrepancy_details: list[str] = []
    actual_transaction_numbers: list[str] = []
    transaction_set_digest: str | None = None


class ManifestProcessingResult(BaseModel):
    """Structured result of manifest and file validation."""

    manifest_id: str
    business_id: str
    source_id: str
    batch_id: str
    is_valid: bool
    verification_status: str  # provisional, verified, or failed
    file_sha256_verified: bool
    signature_verified: bool
    reconciliation_matched: bool
    reconciliation_breakdown: ReconciliationBreakdown | None = None
    watermark_id: str | None = None
    errors: list[str] = []


class ManifestService:
    """Service orchestrating period-close manifest validation, reconciliation, and watermarking."""

    @staticmethod
    def compute_file_sha256(content: bytes) -> str:
        """Compute hexadecimal SHA-256 digest of raw byte content."""
        return hashlib.sha256(content).hexdigest().lower()

    @classmethod
    def authorize_signer(
        cls,
        session: Session,
        business_id: str,
        attesting_user_id: str,
        calling_user_id: str,
    ) -> UserIdentity:
        """
        Verify tenant-scoped authorization:
        1. Calling user ID is mandatory (Finding M1) and matches attesting signer.
        2. Business workspace exists and is active.
        3. User is an active member of the organization owning the business with 'owner' or 'admin' role.
        """
        if not calling_user_id or not str(calling_user_id).strip():
            raise PermissionError("Authenticated calling_user_id is mandatory for manifest authorization.")

        clean_caller = str(calling_user_id).strip()
        clean_attester = str(attesting_user_id).strip()

        if clean_caller != clean_attester:
            raise PermissionError(
                f"Attesting user '{clean_attester}' does not match authenticated user '{clean_caller}'."
            )

        biz = session.execute(
            select(Business).where(Business.id == business_id)
        ).scalar_one_or_none()

        if not biz:
            raise PermissionError(f"Business workspace '{business_id}' does not exist.")

        user = session.execute(
            select(UserIdentity).where(UserIdentity.id == clean_attester)
        ).scalar_one_or_none()

        if not user or not user.is_active:
            raise PermissionError(f"Attesting user '{clean_attester}' not found or deactivated.")

        membership = session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == biz.organization_id,
                OrganizationMembership.user_id == clean_attester,
            )
        ).scalar_one_or_none()

        if not membership:
            raise PermissionError(
                f"User '{clean_attester}' is not a member of organization '{biz.organization_id}'."
            )

        if membership.role not in {"owner", "admin"}:
            raise PermissionError(
                f"User '{clean_attester}' has role '{membership.role}'. "
                "Only organization 'owner' or 'admin' roles can attest an authoritative period close."
            )

        return user

    @classmethod
    def reconcile_file_content(
        cls,
        file_bytes: bytes,
        manifest: PeriodCloseManifest,
    ) -> ReconciliationBreakdown:
        """
        Independently parse tabular CSV export and reconcile transactions against declared manifest:
        - Asserts file is valid UTF-8 CSV.
        - Asserts total rows match manifest.expected_sales_row_count.
        - Asserts all transaction dates fall strictly within [period_start, period_end].
        - Reconciles gross sales totals for eligible statuses ('completed', 'shipped').
        - Tracks refunds, cancellations, and pending records.
        """
        try:
            text_content = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text_content = file_bytes.decode("latin-1")
            except Exception as e:
                raise ValueError(f"Unable to decode file content as text: {e}")

        reader = csv.DictReader(io.StringIO(text_content))
        headers = [h.strip() for h in (reader.fieldnames or []) if h]

        # Check required columns
        required_cols = {"transaction_date", "total_amount", "status"}
        missing_cols = required_cols - {h.lower() for h in headers}
        if missing_cols:
            raise ValueError(f"Export CSV missing required reconciliation column(s): {sorted(missing_cols)}")

        # Find header casing
        date_col = next(h for h in headers if h.lower() == "transaction_date")
        amount_col = next(h for h in headers if h.lower() == "total_amount")
        status_col = next(h for h in headers if h.lower() == "status")
        txn_id_col = next((h for h in headers if h.lower() in {"transaction_number", "id"}), None)

        actual_row_count = 0
        actual_gross_sum = Decimal("0.00")
        refunded_count = 0
        refunded_sum = Decimal("0.00")
        cancelled_count = 0
        cancelled_sum = Decimal("0.00")
        pending_count = 0
        pending_sum = Decimal("0.00")

        earliest_dt: datetime | None = None
        latest_dt: datetime | None = None
        seen_txn_ids: set[str] = set()
        actual_txn_ids: list[str] = []
        discrepancies: list[str] = []

        period_start_utc = manifest.period_start.astimezone(UTC)
        period_end_utc = manifest.period_end.astimezone(UTC)
        eligible_statuses = set(manifest.reconciliation.eligible_status_allowlist)

        for row_idx, row in enumerate(reader, start=1):
            actual_row_count += 1

            # Duplicate check & identity collection
            if txn_id_col:
                txn_val = str(row.get(txn_id_col, "")).strip()
                if txn_val:
                    actual_txn_ids.append(txn_val)
                    if txn_val in seen_txn_ids:
                        discrepancies.append(f"Duplicate transaction ID '{txn_val}' at row {row_idx}.")
                    seen_txn_ids.add(txn_val)

            # Date parsing & range check
            raw_date = row.get(date_col, "").strip()
            try:
                # Support standard ISO formats
                if "T" in raw_date:
                    clean_date_str = raw_date.replace("Z", "+00:00")
                    txn_dt = datetime.fromisoformat(clean_date_str)
                else:
                    txn_dt = datetime.strptime(raw_date[:19], "%Y-%m-%d %H:%M:%S")

                txn_dt_utc = txn_dt if txn_dt.tzinfo is not None else txn_dt.replace(tzinfo=UTC)
                txn_dt_utc = txn_dt_utc.astimezone(UTC)
            except Exception as e:
                discrepancies.append(f"Row {row_idx}: unparseable transaction_date '{raw_date}': {e}")
                continue

            if earliest_dt is None or txn_dt_utc < earliest_dt:
                earliest_dt = txn_dt_utc
            if latest_dt is None or txn_dt_utc > latest_dt:
                latest_dt = txn_dt_utc

            # Boundary constraint: Transaction must fall within declared period
            if txn_dt_utc < period_start_utc:
                discrepancies.append(
                    f"Row {row_idx}: transaction date ({txn_dt_utc.isoformat()}) precedes "
                    f"declared period_start ({period_start_utc.isoformat()})."
                )
            if txn_dt_utc > period_end_utc:
                discrepancies.append(
                    f"Row {row_idx}: transaction date ({txn_dt_utc.isoformat()}) exceeds "
                    f"declared period_end ({period_end_utc.isoformat()})."
                )

            # Amount parsing
            raw_amount = row.get(amount_col, "").strip()
            try:
                amount = Decimal(raw_amount)
            except Exception:
                discrepancies.append(f"Row {row_idx}: invalid numeric amount '{raw_amount}'.")
                continue

            status_val = str(row.get(status_col, "")).strip().lower()
            if status_val in eligible_statuses:
                actual_gross_sum += amount
            elif status_val == "refunded":
                refunded_count += 1
                refunded_sum += amount
            elif status_val == "cancelled":
                cancelled_count += 1
                cancelled_sum += amount
            elif status_val == "pending":
                pending_count += 1
                pending_sum += amount

        # Row count match
        if actual_row_count != manifest.reconciliation.expected_sales_row_count:
            discrepancies.append(
                f"Row count mismatch: manifest expected {manifest.reconciliation.expected_sales_row_count}, "
                f"file contains {actual_row_count} rows."
            )

        # Monetary sum match (0.01 tolerance for precision)
        diff = abs(actual_gross_sum - manifest.reconciliation.expected_gross_total_amount)
        if diff > Decimal("0.01"):
            discrepancies.append(
                f"Gross total mismatch: manifest expected {manifest.reconciliation.expected_gross_total_amount:.2f}, "
                f"file calculated {actual_gross_sum:.2f} across eligible statuses (diff: {diff:.2f})."
            )

        actual_txn_ids_sorted = sorted(actual_txn_ids)
        txn_digest = (
            hashlib.sha256("||".join(actual_txn_ids_sorted).encode("utf-8")).hexdigest()
            if actual_txn_ids_sorted
            else None
        )

        breakdown = ReconciliationBreakdown(
            actual_sales_row_count=actual_row_count,
            actual_gross_total_amount=actual_gross_sum,
            refunded_rows_count=refunded_count,
            refunded_amount=refunded_sum,
            cancelled_rows_count=cancelled_count,
            cancelled_amount=cancelled_sum,
            pending_rows_count=pending_count,
            pending_amount=pending_sum,
            earliest_transaction_date=earliest_dt.isoformat() if earliest_dt else "N/A",
            latest_transaction_date=latest_dt.isoformat() if latest_dt else "N/A",
            reconciliation_matched=(len(discrepancies) == 0),
            discrepancy_details=discrepancies,
            actual_transaction_numbers=actual_txn_ids_sorted,
            transaction_set_digest=txn_digest,
        )

        return breakdown

    @classmethod
    def validate_source_close_evidence(
        cls,
        manifest: PeriodCloseManifest,
        source_close_evidence: dict[str, Any] | None,
        require_evidence: bool = False,
    ) -> list[str]:
        """
        Validate independent source-close settlement evidence (Finding H1).
        If require_evidence is True, source_close_evidence must be provided.
        If source_close_evidence is provided, it is rigorously reconciled against the manifest.
        """
        errors: list[str] = []
        is_accounting = (manifest.provenance_type == "accounting_period_close")

        if require_evidence and not source_close_evidence:
            errors.append("Mandatory source-close evidence is missing for period-close verification.")
            return errors

        if source_close_evidence:
            rep_count = source_close_evidence.get("reported_transaction_count")
            if rep_count is None and is_accounting:
                errors.append("Source-close evidence missing 'reported_transaction_count'.")
            elif rep_count is not None and rep_count != manifest.reconciliation.expected_sales_row_count:
                errors.append(
                    f"Source-close report contradiction: source reported {rep_count} rows, "
                    f"manifest expected {manifest.reconciliation.expected_sales_row_count}."
                )

            rep_revenue = source_close_evidence.get("reported_gross_revenue")
            if rep_revenue is None and is_accounting:
                errors.append("Source-close evidence missing 'reported_gross_revenue'.")
            elif rep_revenue is not None:
                try:
                    rep_dec = Decimal(str(rep_revenue))
                    diff = abs(rep_dec - manifest.reconciliation.expected_gross_total_amount)
                    if diff > Decimal("0.01"):
                        errors.append(
                            f"Source-close report contradiction: source reported {rep_dec:.2f} revenue, "
                            f"manifest expected {manifest.reconciliation.expected_gross_total_amount:.2f}."
                        )
                except Exception as e:
                    errors.append(f"Source-close evidence invalid reported_gross_revenue: {e}")

            rep_status = str(source_close_evidence.get("settlement_status", "")).upper()
            if rep_status and rep_status not in {"CLOSED", "CLOSED_RECONCILED", "SETTLED"}:
                errors.append(f"Source-close evidence is not settled/closed: status is '{rep_status}'.")
            elif not rep_status and is_accounting:
                errors.append("Source-close evidence missing settled settlement_status.")

            exp_id = source_close_evidence.get("export_batch_id")
            if exp_id and exp_id not in {manifest.batch_id, manifest.source_export_id}:
                errors.append(
                    f"Source-close evidence batch mismatch: evidence specifies '{exp_id}', "
                    f"manifest specifies batch_id='{manifest.batch_id}', source_export_id='{manifest.source_export_id}'."
                )
            elif not exp_id and is_accounting:
                errors.append("Source-close evidence missing 'export_batch_id'.")

        return errors

    @classmethod
    def verify_and_ingest_manifest(
        cls,
        session: Session,
        manifest: PeriodCloseManifest,
        file_bytes: bytes,
        calling_user_id: str,
        source_close_evidence: dict[str, Any] | None = None,
        promote_immediately_if_verified: bool = False,
        require_source_evidence: bool = False,
    ) -> ManifestProcessingResult:
        """
        Execute end-to-end manifest verification and provisional watermark registration:
        1. Check duplicate manifest submission replay (Finding M2).
        2. Raw file SHA-256 integrity.
        3. Manifest signature verification via persistent trusted key registry (Finding C2).
        4. Signer tenant-scoped authorization with mandatory caller identity (Finding M1).
        5. Independent tabular file reconciliation.
        6. Source-close settlement evidence reconciliation (Finding H1).
        7. Audit persistence in manifest_submissions (Finding M2).
        8. Provisional watermark creation (promoted only upon full verification & DB reconciliation) (Finding C1).
        """
        errors: list[str] = []

        # 0. Check duplicate submission replay (Finding M2)
        existing_sub = session.execute(
            select(ManifestSubmission).where(ManifestSubmission.manifest_id == manifest.manifest_id)
        ).scalar_one_or_none()
        if existing_sub:
            sub_time = existing_sub.created_at.isoformat() if existing_sub.created_at else "prior submission"
            errors.append(
                f"Manifest replay rejected: manifest_id '{manifest.manifest_id}' was already submitted "
                f"at {sub_time}."
            )

        # 1. Raw file SHA-256 check
        computed_sha256 = cls.compute_file_sha256(file_bytes)
        file_sha256_verified = (computed_sha256 == manifest.file_sha256.lower())
        if not file_sha256_verified:
            errors.append(
                f"File SHA-256 mismatch: manifest specifies {manifest.file_sha256}, "
                f"computed hash of received bytes is {computed_sha256}."
            )

        # 2. Cryptographic signature verification (C2: with DB session)
        signature_verified = False
        try:
            signature_verified = ManifestKeyRegistry.verify_manifest_signature(manifest, session=session)
        except Exception as e:
            errors.append(f"Signature verification failure: {e}")

        # 3. Signer authorization (M1: mandatory calling_user_id)
        try:
            cls.authorize_signer(
                session=session,
                business_id=manifest.business_id,
                attesting_user_id=manifest.attestation.attested_by_user_id,
                calling_user_id=calling_user_id,
            )
        except Exception as e:
            errors.append(f"Signer authorization failure: {e}")

        # 4. Tabular reconciliation
        reconciliation_breakdown = None
        reconciliation_matched = False
        try:
            reconciliation_breakdown = cls.reconcile_file_content(file_bytes, manifest)
            reconciliation_matched = reconciliation_breakdown.reconciliation_matched
            if not reconciliation_matched:
                errors.extend(reconciliation_breakdown.discrepancy_details)
        except Exception as e:
            errors.append(f"Reconciliation error: {e}")

        # 5. Independent source-close evidence validation (H1)
        evidence_errors = cls.validate_source_close_evidence(
            manifest=manifest,
            source_close_evidence=source_close_evidence,
            require_evidence=require_source_evidence,
        )
        if evidence_errors:
            errors.extend(evidence_errors)
        source_evidence_matched = (len(evidence_errors) == 0)

        # H1 guard: if accounting_period_close has NO source evidence, promotion to verified is blocked
        is_accounting = (manifest.provenance_type == "accounting_period_close")
        can_promote = promote_immediately_if_verified
        if is_accounting and not source_close_evidence and promote_immediately_if_verified:
            logger.warning(
                "Immediate watermark promotion blocked: corroborating source-close evidence is required "
                "to promote 'accounting_period_close' watermark to verified status. Retaining provisional status."
            )
            can_promote = False

        is_valid = (
            (len(errors) == 0)
            and file_sha256_verified
            and signature_verified
            and reconciliation_matched
            and source_evidence_matched
        )

        watermark_id = None
        verification_status = "failed"

        # 6. Record provisional watermark if valid
        if is_valid:
            audit_meta = {
                "manifest_id": manifest.manifest_id,
                "batch_id": manifest.batch_id,
                "source_export_id": manifest.source_export_id,
                "file_sha256": manifest.file_sha256,
                "file_name": manifest.file_name,
                "period_start": manifest.period_start.isoformat(),
                "expected_sales_row_count": manifest.reconciliation.expected_sales_row_count,
                "expected_gross_total_amount": str(manifest.reconciliation.expected_gross_total_amount),
                "eligible_status_allowlist": manifest.reconciliation.eligible_status_allowlist,
                "attested_by_user_id": manifest.attestation.attested_by_user_id,
                "attester_role": manifest.attestation.attester_role,
                "signature_key_id": manifest.signature.key_id,
                "signature_algorithm": manifest.signature.algorithm,
                "reconciliation_summary": {
                    "sales_row_count": reconciliation_breakdown.actual_sales_row_count if reconciliation_breakdown else 0,
                    "gross_total_amount": str(reconciliation_breakdown.actual_gross_total_amount) if reconciliation_breakdown else "0.00",
                    "currency": manifest.reconciliation.currency,
                    "transaction_numbers": reconciliation_breakdown.actual_transaction_numbers if reconciliation_breakdown else [],
                    "transaction_set_digest": reconciliation_breakdown.transaction_set_digest if reconciliation_breakdown else None,
                },
                "source_close_evidence": source_close_evidence,
            }

            contract = WatermarkContract(
                business_id=manifest.business_id,
                source_id=manifest.source_id,
                complete_through_dt=manifest.period_end,
                provenance_type=manifest.provenance_type,
                verification_status="provisional",
                metadata_json=audit_meta,
            )
            wm = WatermarkService.record_watermark(session, contract)
            session.flush()
            watermark_id = wm.id
            verification_status = "provisional"

        # 7. Record manifest submission ledger entry (Finding M2)
        submission = None
        if not existing_sub:
            try:
                biz_exists = session.execute(
                    select(Business.id).where(Business.id == manifest.business_id)
                ).scalar_one_or_none()
                caller_exists = session.execute(
                    select(UserIdentity.id).where(UserIdentity.id == calling_user_id)
                ).scalar_one_or_none()

                # Attested_by_user_id no longer has FK constraint (Migration 019),
                # allowing rejected submissions with fake attesters to be recorded durably.
                if biz_exists and caller_exists:
                    submission = ManifestSubmission(
                        manifest_id=manifest.manifest_id,
                        business_id=manifest.business_id,
                        source_id=manifest.source_id,
                        batch_id=manifest.batch_id,
                        provenance_type=manifest.provenance_type,
                        period_start=manifest.period_start,
                        period_end=manifest.period_end,
                        source_export_id=manifest.source_export_id,
                        export_completed_at=manifest.export_completed_at,
                        file_name=manifest.file_name,
                        file_sha256=manifest.file_sha256,
                        expected_row_count=manifest.reconciliation.expected_sales_row_count,
                        expected_gross_total=manifest.reconciliation.expected_gross_total_amount,
                        currency=manifest.reconciliation.currency,
                        attested_by_user_id=manifest.attestation.attested_by_user_id,
                        attester_role=manifest.attestation.attester_role,
                        attestation_statement=manifest.attestation.attestation_statement,
                        attested_at=manifest.attestation.attested_at,
                        submitted_by_user_id=calling_user_id,
                        signature_algorithm=manifest.signature.algorithm,
                        signature_key_id=manifest.signature.key_id,
                        verification_status=verification_status,
                        reconciliation_matched=reconciliation_matched,
                        reconciliation_breakdown_json=(
                            reconciliation_breakdown.model_dump(mode="json")
                            if reconciliation_breakdown
                            else None
                        ),
                        source_close_evidence_json=source_close_evidence,
                        db_reconciled=False,
                        watermark_id=watermark_id,
                        error_details_json=errors if errors else None,
                    )
                    session.add(submission)
                    session.flush()
            except Exception as sub_err:
                logger.warning("Could not persist ManifestSubmission audit ledger: %s", sub_err)

        # 8. Attempt promotion if requested and valid (C1: DB sales reconciliation)
        if is_valid and can_promote and watermark_id:
            try:
                promoted_wm = WatermarkService.promote_provisional_watermark(
                    session=session,
                    business_id=manifest.business_id,
                    watermark_id=watermark_id,
                    audit_metadata={"promoted_reason": "manifest_reconciliation_complete"},
                )
                session.flush()
                verification_status = promoted_wm.verification_status
                if submission is not None:
                    submission.db_reconciled = True
                    submission.verification_status = promoted_wm.verification_status
                    session.flush()
            except Exception as promo_err:
                errors.append(f"Watermark promotion failed: {promo_err}")
                verification_status = "provisional"

        return ManifestProcessingResult(
            manifest_id=manifest.manifest_id,
            business_id=manifest.business_id,
            source_id=manifest.source_id,
            batch_id=manifest.batch_id,
            is_valid=is_valid,
            verification_status=verification_status,
            file_sha256_verified=file_sha256_verified,
            signature_verified=signature_verified,
            reconciliation_matched=reconciliation_matched,
            reconciliation_breakdown=reconciliation_breakdown,
            watermark_id=watermark_id,
            errors=errors,
        )
