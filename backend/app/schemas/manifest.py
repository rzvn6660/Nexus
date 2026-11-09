"""
NEXUS Phase 1I.1 — Signed Period-Close Manifest Schema.

Defines the cryptographically signable, auditable period-close manifest contract
used to establish authoritative ingestion completeness boundaries.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import re
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator

ALLOWED_ALGORITHMS: set[str] = {"ed25519", "hmac-sha256"}
ALLOWED_CURRENCIES: set[str] = {"USD", "EUR", "GBP", "CAD", "AUD"}
ALLOWED_MANIFEST_PROVENANCE: set[str] = {"accounting_period_close", "batch_file"}
SHA256_HEX_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


class ManifestAttestation(BaseModel):
    """Authorized human or service attestation metadata."""

    attested_by_user_id: str = Field(min_length=1, max_length=64, description="User ID of the attesting finance controller or owner.")
    attester_role: str = Field(min_length=1, max_length=64, description="Role: owner, admin, finance_controller.")
    attestation_statement: str = Field(min_length=10, max_length=1000, description="Formal close certification statement.")
    attested_at: datetime = Field(description="Timestamp when the attestation was executed (UTC).")

    @field_validator("attested_at")
    @classmethod
    def validate_attested_at(cls, v: datetime) -> datetime:
        utc_dt = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        utc_dt = utc_dt.astimezone(UTC)
        now_skew = datetime.now(UTC) + timedelta(minutes=5)
        if utc_dt > now_skew:
            raise ValueError(f"attested_at cannot be in the future (timestamp={utc_dt.isoformat()})")
        if utc_dt.year < 2000:
            raise ValueError(f"attested_at cannot be before year 2000: {utc_dt.isoformat()}")
        return utc_dt


class ManifestSignature(BaseModel):
    """Cryptographic signature metadata for tamper-evident verification."""

    algorithm: str = Field(description="Signing algorithm: ed25519 or hmac-sha256.")
    key_id: str = Field(min_length=1, max_length=64, description="Identifier of the trusted key configured for this tenant.")
    signature_hex: str = Field(min_length=32, description="Hex-encoded signature bytes over the canonical manifest.")

    @field_validator("algorithm")
    @classmethod
    def validate_algorithm(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ALLOWED_ALGORITHMS:
            raise ValueError(f"Unsupported signing algorithm '{v}'. Allowed: {sorted(ALLOWED_ALGORITHMS)}")
        return clean

    @field_validator("signature_hex")
    @classmethod
    def validate_signature_hex(cls, v: str) -> str:
        clean = v.strip()
        try:
            bytes.fromhex(clean)
        except ValueError:
            raise ValueError("signature_hex must be valid hexadecimal encoding")
        return clean


class ReconciliationTotals(BaseModel):
    """Independent source reconciliation expectations for row counts and gross volume."""

    expected_sales_row_count: int = Field(ge=1, description="Expected total number of sales records in the export file.")
    expected_gross_total_amount: Decimal = Field(ge=0, description="Expected sum of gross total_amount for eligible completed orders.")
    expected_net_total_amount: Decimal | None = Field(default=None, ge=0, description="Optional expected net total amount after refunds/discounts.")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="ISO-4217 3-letter currency code.")
    eligible_status_allowlist: list[str] = Field(
        default=["completed", "shipped"],
        description="Transaction statuses considered valid completed orders.",
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in ALLOWED_CURRENCIES:
            raise ValueError(f"Unsupported currency '{v}'. Allowed: {sorted(ALLOWED_CURRENCIES)}")
        return clean

    @field_validator("eligible_status_allowlist")
    @classmethod
    def validate_status_allowlist(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("eligible_status_allowlist cannot be empty")
        return [s.strip().lower() for s in v]


class PeriodCloseManifest(BaseModel):
    """
    Formal, cryptographically signable period-close manifest for authoritative data completeness.
    """

    schema_version: str = Field(default="1.0", description="Manifest contract version.")
    manifest_id: str = Field(min_length=1, max_length=64, description="Unique manifest UUID or identifier.")
    business_id: str = Field(min_length=1, max_length=36, description="Target tenant business UUID.")
    source_id: str = Field(default="default", min_length=1, max_length=64, description="Source system identifier (pos, ecommerce, accounting).")
    batch_id: str = Field(min_length=1, max_length=64, description="Unique source export batch ID.")
    provenance_type: str = Field(default="accounting_period_close", description="Provenance type: accounting_period_close or batch_file.")
    period_start: datetime = Field(description="Beginning of the certified period (inclusive, UTC).")
    period_end: datetime = Field(description="Certified complete-through boundary (inclusive, UTC).")
    source_export_id: str | None = Field(default=None, max_length=64, description="External source system export reference ID.")
    export_completed_at: datetime | None = Field(default=None, description="When the upstream source system finished generating the export.")
    file_name: str = Field(min_length=1, max_length=255, description="Associated file name (e.g. sales_2026Q2.csv).")
    file_sha256: str = Field(min_length=64, max_length=64, description="Hex-encoded SHA-256 hash of the received export file.")
    reconciliation: ReconciliationTotals
    attestation: ManifestAttestation
    signature: ManifestSignature

    @field_validator("file_sha256")
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        clean = v.strip().lower()
        if not SHA256_HEX_PATTERN.match(clean):
            raise ValueError("file_sha256 must be a valid 64-character lowercase hex SHA-256 checksum")
        return clean

    @field_validator("provenance_type")
    @classmethod
    def validate_provenance_type(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ALLOWED_MANIFEST_PROVENANCE:
            raise ValueError(f"Invalid manifest provenance_type '{v}'. Allowed: {sorted(ALLOWED_MANIFEST_PROVENANCE)}")
        return clean

    @field_validator("period_start", "period_end")
    @classmethod
    def validate_period_timestamps(cls, v: datetime) -> datetime:
        utc_dt = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        utc_dt = utc_dt.astimezone(UTC)
        if utc_dt.year < 2000:
            raise ValueError(f"Period timestamp cannot be before year 2000: {utc_dt.isoformat()}")
        now_skew = datetime.now(UTC) + timedelta(minutes=5)
        if utc_dt > now_skew:
            raise ValueError(f"Period timestamp cannot be in the future: {utc_dt.isoformat()}")
        return utc_dt

    @model_validator(mode="after")
    def validate_boundary_integrity(self) -> "PeriodCloseManifest":
        if self.period_end <= self.period_start:
            raise ValueError(
                f"period_end ({self.period_end.isoformat()}) must be strictly after period_start ({self.period_start.isoformat()})"
            )
        return self

    def get_canonical_dict(self) -> dict[str, Any]:
        """
        Produce a deterministic canonical dictionary of manifest claims for signature verification.
        Excludes the signature hex itself to prevent circularity.
        """
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "business_id": self.business_id,
            "source_id": self.source_id,
            "batch_id": self.batch_id,
            "provenance_type": self.provenance_type,
            "period_start": self.period_start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "period_end": self.period_end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_export_id": self.source_export_id,
            "export_completed_at": (
                self.export_completed_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                if self.export_completed_at else None
            ),
            "file_name": self.file_name,
            "file_sha256": self.file_sha256.lower(),
            "reconciliation": {
                "expected_sales_row_count": self.reconciliation.expected_sales_row_count,
                "expected_gross_total_amount": f"{self.reconciliation.expected_gross_total_amount:.2f}",
                "expected_net_total_amount": (
                    f"{self.reconciliation.expected_net_total_amount:.2f}"
                    if self.reconciliation.expected_net_total_amount is not None else None
                ),
                "currency": self.reconciliation.currency,
                "eligible_status_allowlist": sorted(self.reconciliation.eligible_status_allowlist),
            },
            "attestation": {
                "attested_by_user_id": self.attestation.attested_by_user_id,
                "attester_role": self.attestation.attester_role,
                "attestation_statement": self.attestation.attestation_statement,
                "attested_at": self.attestation.attested_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "signature_meta": {
                "algorithm": self.signature.algorithm,
                "key_id": self.signature.key_id,
            },
        }

    def get_canonical_bytes(self) -> bytes:
        """Serialize canonical dictionary to RFC-8785 compatible deterministic UTF-8 JSON bytes."""
        canonical_dict = self.get_canonical_dict()
        canonical_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return canonical_str.encode("utf-8")
