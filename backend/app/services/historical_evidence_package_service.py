"""
NEXUS Phase 1J.3.2 — Immutable Historical Evidence Package Service.

Provides durable, immutable ledger storage and independent historical signature
verification for period-close evidence packages.

Key Guarantees:
1. Immutability:
   Package records are append-only. Overwrites of previously recorded packages
   are strictly prohibited (raises IMMUTABLE_PACKAGE_OVERWRITE_PROHIBITED).
2. Explicit Lineage and Supersession:
   Newer packages for the same accounting period receive a distinct package ID,
   incremented version_number, and explicit link to the prior package
   (supersedes_package_id and superseded_by_package_id).
3. Independent Historical Signature Verification:
   Decouples historical cryptographic authenticity from current source completeness.
   A historical package remains verifiable across application restarts, key rotations,
   and key revocations (if the key was valid at signing time), even if subsequent
   source mutations or backfills have invalidated current tenant certification.
"""

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connector import ConnectorSyncCheckpoint
from app.models.manifest import ManifestSubmission, TenantTrustedKey
from app.models.tenant import UserIdentity
from app.schemas.period_close_evidence import (
    PeriodCloseEvidencePackage,
    PeriodCloseLifecycleStatus,
)
from app.services.canonical_dataset_digest_service import CanonicalDatasetDigestService

logger = logging.getLogger(__name__)


@dataclass
class HistoricalVerificationResult:
    """
    Comprehensive audit outcome of an independent historical package verification.
    """
    package_id: str
    version_number: int
    historical_signature_valid: bool
    signing_key_id: str
    key_valid_at_signing: bool
    key_status_at_signing: str
    current_key_status: str
    canonical_digest_matches: bool
    current_dataset_diverged: bool
    lifecycle_status_at_signing: str
    current_lifecycle_status: str
    is_superseded: bool
    supersedes_package_id: str | None = None
    superseded_by_package_id: str | None = None
    verification_verdict: str = "HISTORICALLY_VALID"
    diagnostics: list[str] = field(default_factory=list)


class HistoricalEvidencePackageService:
    """
    Durable ledger service for immutable evidence snapshot persistence,
    supersession management, and historical signature verification.
    """

    @classmethod
    def record_immutable_package(
        cls,
        session: Session,
        package: PeriodCloseEvidencePackage,
        submitted_by_user_id: str,
        supersedes_package_id: str | None = None,
    ) -> ManifestSubmission:
        """
        Durably record a signed period-close evidence package into the immutable manifest ledger.
        Rejects overwrite attempts with IMMUTABLE_PACKAGE_OVERWRITE_PROHIBITED.
        Maintains forward and backward supersession links.
        """
        # 1. Assert immutability: package_id must never already exist
        existing = session.execute(
            select(ManifestSubmission).where(ManifestSubmission.manifest_id == package.package_id)
        ).scalar_one_or_none()
        if existing:
            raise ValueError(
                f"IMMUTABLE_PACKAGE_OVERWRITE_PROHIBITED: Historical evidence package '{package.package_id}' "
                "already exists in the ledger and cannot be modified or overwritten."
            )

        # 2. Handle supersession if indicated
        target_supersedes = supersedes_package_id or package.supersedes_package_id
        if target_supersedes:
            prior_sub = session.execute(
                select(ManifestSubmission).where(ManifestSubmission.manifest_id == target_supersedes)
            ).scalar_one_or_none()
            if not prior_sub:
                raise ValueError(
                    f"Superseded package '{target_supersedes}' does not exist in ledger."
                )

            # Update prior submission record to mark it superseded
            prior_evidence = dict(prior_sub.source_close_evidence_json or {})
            prior_version = prior_evidence.get("version_number", 1)
            prior_evidence["superseded_by_package_id"] = package.package_id
            prior_evidence["superseded_at"] = datetime.now(UTC).isoformat()
            prior_sub.source_close_evidence_json = prior_evidence
            prior_sub.verification_status = "superseded"

            # Set new package versioning
            package.version_number = prior_version + 1
            package.supersedes_package_id = target_supersedes
            package.canonical_payload_digest = package.compute_canonical_digest()

        # 3. Assemble immutable evidence snapshot payload
        dataset_digest = package.transaction_identity_digests.get("dataset_identity_digest")
        payload_digest = package.canonical_payload_digest or package.compute_canonical_digest()

        sig_algo = package.manifest_signature.algorithm if package.manifest_signature else "none"
        sig_key_id = package.manifest_signature.key_id if package.manifest_signature else (package.trusted_key_id or "unknown")

        evidence_ledger_payload = {
            "package_id": package.package_id,
            "version_number": package.version_number,
            "supersedes_package_id": package.supersedes_package_id,
            "superseded_by_package_id": package.superseded_by_package_id,
            "superseded_at": package.superseded_at.isoformat() if package.superseded_at else None,
            "canonical_payload_digest": payload_digest,
            "dataset_identity_digest": dataset_digest,
            "canonical_bytes_hex": package.get_canonical_bytes().hex(),
            "manifest_signature": package.manifest_signature.model_dump() if package.manifest_signature else None,
            "signature_algorithm": sig_algo,
            "signature_key_id": sig_key_id,
            "signing_timestamp": package.attestation.attested_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "attested_by_user_id": package.attestation.attested_by_user_id,
            "attester_role": package.attestation.attester_role,
            "source_checkpoints": package.source_checkpoints,
            "source_record_counts": package.source_record_counts,
            "transaction_identity_digests": package.transaction_identity_digests,
            "validation_status_at_signing": package.validation_status.value,
            "raw_package": package.model_dump(mode="json"),
        }

        # 4. Total expected rows and gross amounts
        total_rows = sum(package.source_record_counts.values()) if package.source_record_counts else 0
        expected_gross = package.shopify_commercial_totals.get("gross_sales", Decimal("0.00"))

        # Ensure submitting user identity exists to satisfy foreign key constraint
        sub_user_id = submitted_by_user_id
        user = session.execute(
            select(UserIdentity).where(UserIdentity.id == sub_user_id)
        ).scalar_one_or_none()
        if not user:
            user_email = f"user_{sub_user_id[:20]}@synthetic.nexus"
            user = session.execute(
                select(UserIdentity).where(UserIdentity.email == user_email)
            ).scalar_one_or_none()
            if not user:
                clean_id = sub_user_id[:36] if len(sub_user_id) > 36 else sub_user_id
                user = UserIdentity(
                    id=clean_id,
                    email=user_email,
                    password_hash="synthetic_pwd_hash_disabled",
                    full_name=f"Attester {sub_user_id}",
                    is_active=True,
                    is_verified=True,
                )
                session.add(user)
                session.flush()
            sub_user_id = user.id

        submission = ManifestSubmission(
            manifest_id=package.package_id,
            business_id=package.business_id,
            source_id="multi_source_period_close",
            batch_id=f"close_{package.package_id[:8]}",
            provenance_type=package.attestation.provenance_type,
            period_start=package.accounting_period_start,
            period_end=package.accounting_period_end,
            file_name=f"evidence_{package.package_id}.json",
            file_sha256=payload_digest,
            expected_row_count=total_rows,
            expected_gross_total=expected_gross,
            currency=package.currency,
            attested_by_user_id=package.attestation.attested_by_user_id,
            attester_role=package.attestation.attester_role,
            attestation_statement=package.attestation.attestation_statement,
            attested_at=package.attestation.attested_at,
            submitted_by_user_id=sub_user_id,
            signature_algorithm=sig_algo,
            signature_key_id=sig_key_id,
            verification_status=package.validation_status.value.lower(),
            reconciliation_matched=package.is_fully_reconciled,
            reconciliation_breakdown_json={
                "matched_count": package.reconciliation_matched_count,
                "partial_count": package.reconciliation_partial_count,
                "unmatched_orders_count": package.reconciliation_unmatched_orders_count,
                "unmatched_payments_count": package.reconciliation_unmatched_payments_count,
                "conflict_count": package.reconciliation_conflict_count,
            },
            source_close_evidence_json=evidence_ledger_payload,
        )

        session.add(submission)

        # 5. Lock and update checkpoint metadata
        checkpoints = session.execute(
            select(ConnectorSyncCheckpoint)
            .where(
                ConnectorSyncCheckpoint.business_id == package.business_id,
                ConnectorSyncCheckpoint.period_start <= package.accounting_period_end,
                ConnectorSyncCheckpoint.period_end >= package.accounting_period_start,
            )
            .with_for_update()
        ).scalars().all()

        for ck in checkpoints:
            ck.transaction_set_digest = dataset_digest
            meta = dict(ck.metadata_json or {})
            meta["certified_snapshot"] = {
                "package_id": package.package_id,
                "version_number": package.version_number,
                "dataset_identity_digest": dataset_digest,
                "certified_at": datetime.now(UTC).isoformat(),
                "trusted_key_id": package.trusted_key_id,
            }
            ck.metadata_json = meta

        session.flush()
        return submission

    @classmethod
    def get_historical_package(
        cls,
        session: Session,
        package_id: str,
        authenticated_business_id: str | None = None,
    ) -> tuple[PeriodCloseEvidencePackage, ManifestSubmission]:
        """
        Retrieve a historical evidence package and its immutable ledger submission.
        Enforces tenant isolation: raises PermissionError if authenticated_business_id does not match.
        """
        submission = session.execute(
            select(ManifestSubmission).where(ManifestSubmission.manifest_id == package_id)
        ).scalar_one_or_none()

        if not submission:
            raise ValueError(f"Historical evidence package '{package_id}' not found in ledger.")

        if authenticated_business_id is not None and submission.business_id != authenticated_business_id:
            raise PermissionError(
                f"Cross-tenant access prohibited: caller '{authenticated_business_id}' "
                f"attempted to access package belonging to '{submission.business_id}'."
            )

        evidence_json = submission.source_close_evidence_json or {}
        raw_pkg = evidence_json.get("raw_package")
        if not raw_pkg:
            raise ValueError(f"Ledger entry for '{package_id}' missing raw package payload.")

        package = PeriodCloseEvidencePackage.model_validate(raw_pkg)
        return package, submission

    @classmethod
    def delete_package(cls, session: Session, package_id: str) -> None:
        """
        Prohibit deletion of certified immutable historical packages.
        Always fails closed to protect audit trail integrity.
        """
        raise ValueError(
            f"IMMUTABLE_PACKAGE_DELETION_PROHIBITED: Historical evidence package '{package_id}' "
            "is immutable and cannot be deleted from the manifest ledger."
        )

    @classmethod
    def list_historical_packages(
        cls,
        session: Session,
        business_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> list[dict[str, Any]]:
        """
        List all historical packages for a tenant and period, ordered by version_number ascending.
        """
        subs = session.execute(
            select(ManifestSubmission)
            .where(
                ManifestSubmission.business_id == business_id,
                ManifestSubmission.period_start <= period_end,
                ManifestSubmission.period_end >= period_start,
            )
            .order_by(ManifestSubmission.period_start.asc(), ManifestSubmission.created_at.asc())
        ).scalars().all()

        records = []
        for s in subs:
            meta = s.source_close_evidence_json or {}
            records.append(
                {
                    "package_id": s.manifest_id,
                    "version_number": meta.get("version_number", 1),
                    "supersedes_package_id": meta.get("supersedes_package_id"),
                    "superseded_by_package_id": meta.get("superseded_by_package_id"),
                    "status": s.verification_status,
                    "dataset_identity_digest": meta.get("dataset_identity_digest"),
                    "canonical_payload_digest": s.file_sha256,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "attested_by_user_id": s.attested_by_user_id,
                    "signature_key_id": s.signature_key_id,
                }
            )
        return records

    @classmethod
    def verify_historical_package(
        cls,
        session: Session,
        package_or_id: str | PeriodCloseEvidencePackage,
        current_shopify_orders: list[dict[str, Any]] | None = None,
        current_stripe_transactions: list[dict[str, Any]] | None = None,
        trusted_key_override: TenantTrustedKey | None = None,
    ) -> HistoricalVerificationResult:
        """
        Independently verify the historical cryptographic integrity, attestation validity,
        and current source completeness of a historical evidence package.

        Key policy:
        - Cryptographic validity depends on key status at the time of signing.
        - Rotation or revocation subsequent to signing does NOT invalidate historical packages.
        - Mutations or backfills subsequent to certification mark current status as INVALIDATED,
          while preserving historical signature validity.
        """
        if isinstance(package_or_id, str):
            package, submission = cls.get_historical_package(session, package_or_id)
        else:
            package = package_or_id
            submission = session.execute(
                select(ManifestSubmission).where(ManifestSubmission.manifest_id == package.package_id)
            ).scalar_one_or_none()

        diagnostics: list[str] = []
        is_superseded = False
        superseded_by = None
        supersedes_id = package.supersedes_package_id

        if submission:
            evidence_json = submission.source_close_evidence_json or {}
            superseded_by = evidence_json.get("superseded_by_package_id")
            if submission.verification_status == "superseded" or superseded_by:
                is_superseded = True

        # 1. Canonical payload digest verification
        computed_payload_digest = package.compute_canonical_digest()
        stored_payload_digest = package.canonical_payload_digest
        canonical_digest_matches = (computed_payload_digest == stored_payload_digest)
        if not canonical_digest_matches:
            diagnostics.append(
                f"CANONICAL_DIGEST_MISMATCH: Computed '{computed_payload_digest}' != Stored '{stored_payload_digest}'."
            )

        # 2. Cryptographic signature and key validity at signing time
        historical_signature_valid = False
        key_valid_at_signing = False
        key_status_at_signing = "unknown"
        current_key_status = "unknown"
        key_id = package.manifest_signature.key_id if package.manifest_signature else "unknown"

        if not package.manifest_signature:
            diagnostics.append("MISSING_SIGNATURE: Package has no manifest signature.")
        else:
            signing_time = package.attestation.attested_at
            if signing_time.tzinfo is None:
                signing_time = signing_time.replace(tzinfo=UTC)

            # Retrieve key from DB
            key_record = trusted_key_override
            if key_record is None:
                key_record = session.execute(
                    select(TenantTrustedKey).where(
                        TenantTrustedKey.business_id == package.business_id,
                        TenantTrustedKey.key_id == key_id,
                    )
                ).scalar_one_or_none()

            if not key_record:
                diagnostics.append(f"KEY_NOT_FOUND: Trusted key '{key_id}' not found in registry.")
                key_status_at_signing = "not_found"
                current_key_status = "not_found"
            else:
                current_key_status = key_record.status

                # Determine if key was valid AT SIGNING TIME
                valid_from = key_record.valid_from
                if valid_from.tzinfo is None:
                    valid_from = valid_from.replace(tzinfo=UTC)

                key_active_at_time = (signing_time >= valid_from)

                if key_record.expires_at is not None:
                    exp = key_record.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=UTC)
                    if signing_time > exp:
                        key_active_at_time = False

                if key_record.revoked_at is not None:
                    rev = key_record.revoked_at
                    if rev.tzinfo is None:
                        rev = rev.replace(tzinfo=UTC)
                    if signing_time >= rev:
                        key_active_at_time = False

                key_valid_at_signing = key_active_at_time
                key_status_at_signing = "active" if key_valid_at_signing else "revoked_or_expired_at_signing"

                if not key_valid_at_signing:
                    diagnostics.append(
                        f"KEY_INVALID_AT_SIGNING: Key '{key_id}' was not valid at signing timestamp {signing_time.isoformat()}."
                    )

                # Verify cryptographic signature against public key
                canonical_bytes = package.get_canonical_bytes()
                sig_bytes = bytes.fromhex(package.manifest_signature.signature_hex)

                if package.manifest_signature.algorithm == "ed25519":
                    try:
                        # Extract public key from PEM
                        from cryptography.hazmat.primitives.serialization import load_pem_public_key
                        pub_key = load_pem_public_key(key_record.public_key_pem.encode("utf-8"))
                        if isinstance(pub_key, ed25519.Ed25519PublicKey):
                            pub_key.verify(sig_bytes, canonical_bytes)
                            historical_signature_valid = True
                        else:
                            diagnostics.append("KEY_FORMAT_ERROR: Public key is not Ed25519.")
                    except InvalidSignature:
                        diagnostics.append("CRYPTOGRAPHIC_SIGNATURE_INVALID: Ed25519 signature verification failed.")
                    except Exception as e:  # noqa: BLE001
                        diagnostics.append(f"SIGNATURE_VERIFICATION_ERROR: {e}")
                elif package.manifest_signature.algorithm == "hmac-sha256":
                    secret = key_record.public_key_pem.encode("utf-8")
                    expected_hex = hmac.new(secret, canonical_bytes, hashlib.sha256).hexdigest()
                    if hmac.compare_digest(expected_hex.lower(), package.manifest_signature.signature_hex.lower()):
                        historical_signature_valid = True
                    else:
                        diagnostics.append("CRYPTOGRAPHIC_SIGNATURE_INVALID: HMAC-SHA256 signature mismatch.")

        # 3. Current dataset divergence check
        current_dataset_diverged = False
        current_status = package.validation_status.value

        if current_shopify_orders is not None or current_stripe_transactions is not None:
            shopify_comp = package.completeness_assessments.get("shopify", {})
            stripe_comp = package.completeness_assessments.get("stripe", {})
            shopify_store = shopify_comp.get("store_domain", "default.myshopify.com")
            stripe_acct = stripe_comp.get("account_id", "acct_default")

            orders_check = current_shopify_orders if current_shopify_orders is not None else []
            txns_check = current_stripe_transactions if current_stripe_transactions is not None else []

            recomputed_digests = CanonicalDatasetDigestService.compute_dataset_identity_digest(
                shopify_orders=orders_check,
                stripe_transactions=txns_check,
                business_id=package.business_id,
                shopify_store_domain=shopify_store,
                stripe_account_id=stripe_acct,
                period_start=package.accounting_period_start,
                period_end=package.accounting_period_end,
            )

            expected_dataset_digest = package.transaction_identity_digests.get("dataset_identity_digest")
            actual_dataset_digest = recomputed_digests.get("dataset_identity_digest")

            if expected_dataset_digest != actual_dataset_digest:
                current_dataset_diverged = True
                current_status = PeriodCloseLifecycleStatus.INVALIDATED.value
                diagnostics.append(
                    f"CURRENT_DATASET_DIVERGED: Persisted records mutated since certification. "
                    f"Certified '{expected_dataset_digest}' != Current '{actual_dataset_digest}'."
                )

        if is_superseded and current_status != PeriodCloseLifecycleStatus.INVALIDATED.value:
            current_status = PeriodCloseLifecycleStatus.SUPERSEDED.value

        # 4. Formulate overall verdict
        if not historical_signature_valid:
            verdict = "HISTORICALLY_INVALID_SIGNATURE"
        elif not key_valid_at_signing:
            verdict = "KEY_INVALID_AT_SIGNING"
        elif current_dataset_diverged:
            verdict = "HISTORICALLY_VALID_DATASET_DIVERGED"
        elif is_superseded:
            verdict = "HISTORICALLY_VALID_SUPERSEDED"
        else:
            verdict = "HISTORICALLY_VALID"

        return HistoricalVerificationResult(
            package_id=package.package_id,
            version_number=package.version_number,
            historical_signature_valid=historical_signature_valid,
            signing_key_id=key_id,
            key_valid_at_signing=key_valid_at_signing,
            key_status_at_signing=key_status_at_signing,
            current_key_status=current_key_status,
            canonical_digest_matches=canonical_digest_matches,
            current_dataset_diverged=current_dataset_diverged,
            lifecycle_status_at_signing=package.validation_status.value,
            current_lifecycle_status=current_status,
            is_superseded=is_superseded,
            supersedes_package_id=supersedes_id,
            superseded_by_package_id=superseded_by,
            verification_verdict=verdict,
            diagnostics=diagnostics,
        )
