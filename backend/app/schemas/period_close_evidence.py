"""
NEXUS Phase 1J.3 — Period-Close Evidence Package and Completeness Schemas.

Defines schemas for:
1. Provider-specific completeness assessments (Shopify Admin GraphQL and Stripe Test Mode).
2. Synthetic and authenticated period-close attestations.
3. Multi-source reconciliation summaries and financial balances.
4. Cryptographically signable period-close evidence packages.
5. Fail-closed lifecycle statuses: DIAGNOSTIC_ONLY, PROVISIONAL, VERIFIED_COMPLETE, INVALIDATED, STALE.
"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.manifest import ManifestSignature

SHA256_HEX_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")

CURRENCY_EXPONENTS: dict[str, int] = {
    # 0 decimal places
    "JPY": 0, "KRW": 0, "CLP": 0, "VND": 0, "HUF": 0, "PYG": 0, "UGX": 0, "BIF": 0, "DJF": 0, "RWF": 0,
    # 2 decimal places
    "USD": 2, "EUR": 2, "GBP": 2, "CAD": 2, "AUD": 2, "CHF": 2, "SGD": 2, "HKD": 2, "NZD": 2, "SEK": 2,
    "NOK": 2, "DKK": 2, "INR": 2, "BRL": 2, "MXN": 2, "PLN": 2, "ZAR": 2,
    # 3 decimal places
    "BHD": 3, "KWD": 3, "OMR": 3, "JOD": 3, "TND": 3, "IQD": 3, "LYD": 3,
}
ALLOWED_CURRENCIES = set(CURRENCY_EXPONENTS.keys())


class PeriodCloseLifecycleStatus(str, Enum):
    """Lifecycle classification of period-close evidence packages and certifications."""
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
    PROVISIONAL = "PROVISIONAL"
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"
    INVALIDATED = "INVALIDATED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class ShopifyCompletenessAssessment(BaseModel):
    """
    Independent source-completeness evaluation for Shopify storefront extraction.
    Records API version, store identity, pagination boundaries, and API limitations.
    """
    api_version: str = Field(default="2026-10", description="Pinned Shopify GraphQL Admin API version")
    store_domain: str = Field(min_length=1, max_length=255, description="Shopify store domain / account ID")
    period_start: datetime
    period_end: datetime
    timezone: str = "UTC"
    pagination_completed: bool = Field(description="True if GraphQL cursor reached terminal page without interruption")
    checkpoint_id: str
    cursor_chain_hash: str = Field(description="Rolling SHA-256 hash of all traversed page cursors")
    current_cursor: str | None = None
    records_extracted: int = Field(ge=0)
    records_ingested: int = Field(ge=0)
    records_rejected: int = Field(default=0, ge=0)
    extraction_started_at: datetime
    extraction_completed_at: datetime
    known_api_limitations: list[str] = Field(
        default_factory=lambda: [
            "Shopify GraphQL Admin API leaky bucket quota: 1000 cost points per second",
            "Read-only historical order extraction requires read_orders and read_customers scopes",
        ]
    )
    errors: list[str] = Field(default_factory=list)
    is_complete: bool = False

    @field_validator("period_start", "period_end")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        utc_dt = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        return utc_dt.astimezone(UTC)


class StripeCompletenessAssessment(BaseModel):
    """
    Independent source-completeness evaluation for Stripe payment gateway extraction.
    Records account identity, charge and settlement counts, payout extraction, and timing differences.
    """
    account_id: str = Field(min_length=1, max_length=255, description="Stripe account identifier (e.g. acct_...)")
    period_start: datetime
    period_end: datetime
    timezone: str = "UTC"
    payment_transactions_count: int = Field(ge=0, description="Total charges and payment intents extracted")
    refunds_count: int = Field(default=0, ge=0, description="Total refund records extracted")
    payouts_count: int = Field(default=0, ge=0, description="Total payout and settlement transfers extracted")
    payout_extracted: bool = Field(
        default=False,
        description="True if authoritative bank payout / settlement event was extracted during or for period",
    )
    pagination_completed: bool = Field(description="True if Stripe auto-paging reached has_more=False")
    checkpoint_id: str
    cursor_chain_hash: str = Field(description="Rolling SHA-256 hash of pagination cursors")
    current_cursor: str | None = None
    records_extracted: int = Field(ge=0)
    records_ingested: int = Field(ge=0)
    records_rejected: int = Field(default=0, ge=0)
    extraction_started_at: datetime
    extraction_completed_at: datetime
    unresolved_adjustments: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    is_complete: bool = False

    @field_validator("period_start", "period_end")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        utc_dt = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        return utc_dt.astimezone(UTC)


class PeriodCloseAttestation(BaseModel):
    """
    Independently authenticated period-close assertion metadata.
    In synthetic rehearsal, clearly designated as synthetic attestation.
    """
    attestation_id: str = Field(default_factory=lambda: str(uuid4()))
    attested_by_user_id: str = Field(min_length=1, max_length=64)
    attester_role: str = Field(description="Role: owner, admin, finance_controller")
    attestation_statement: str = Field(min_length=10, max_length=1000)
    attested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_synthetic: bool = Field(
        default=True,
        description="Must be True during sandbox rehearsal. Prohibits certification of real tenants.",
    )
    provenance_type: str = Field(
        default="synthetic_rehearsal_attestation",
        description="Provenance classification (e.g. synthetic_rehearsal_attestation, certified_erp_close)",
    )

    @field_validator("attested_at")
    @classmethod
    def validate_attested_at(cls, v: datetime) -> datetime:
        utc_dt = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        utc_dt = utc_dt.astimezone(UTC)
        now_skew = datetime.now(UTC) + timedelta(minutes=5)
        if utc_dt > now_skew:
            raise ValueError(f"attested_at cannot be in the future: {utc_dt.isoformat()}")
        return utc_dt


class PeriodCloseEvidencePackage(BaseModel):
    """
    Comprehensive, cryptographically signable period-close evidence package.
    Binds commercial storefront evidence, payment settlement evidence, cross-source reconciliation,
    source-completeness assessments, and transaction identity digests into an immutable audit package.
    """
    package_id: str = Field(default_factory=lambda: str(uuid4()))
    business_id: str = Field(min_length=1, max_length=36, description="Tenant business UUID")
    providers: list[str] = Field(default=["shopify", "stripe"])
    accounting_period_start: datetime
    accounting_period_end: datetime
    timezone: str = "UTC"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    provider_api_versions: dict[str, str] = Field(
        default_factory=lambda: {"shopify": "2026-10", "stripe": "2024-06-20"}
    )
    source_checkpoints: dict[str, dict[str, Any]] = Field(default_factory=dict)
    source_record_counts: dict[str, int] = Field(default_factory=dict)
    transaction_identity_digests: dict[str, str] = Field(
        default_factory=dict,
        description="Provider-specific digests and combined dataset_identity_digest",
    )
    shopify_commercial_totals: dict[str, Decimal] = Field(default_factory=dict)
    stripe_capture_and_refund_totals: dict[str, Decimal] = Field(default_factory=dict)
    stripe_fee_and_settlement_totals: dict[str, Decimal] = Field(default_factory=dict)
    reconciliation_matched_count: int = 0
    reconciliation_partial_count: int = 0
    reconciliation_unmatched_orders_count: int = 0
    reconciliation_unmatched_payments_count: int = 0
    reconciliation_conflict_count: int = 0
    is_fully_reconciled: bool = False
    unmatched_or_conflicting_record_ids: list[str] = Field(default_factory=list)
    completeness_assessments: dict[str, Any] = Field(default_factory=dict)
    attestation: PeriodCloseAttestation
    manifest_signature: ManifestSignature | None = None
    canonical_payload_digest: str | None = None
    trusted_key_id: str | None = None
    validation_status: PeriodCloseLifecycleStatus = PeriodCloseLifecycleStatus.PROVISIONAL
    validation_errors: list[str] = Field(default_factory=list)
    version_number: int = Field(default=1, ge=1, description="Sequential package version for period")
    supersedes_package_id: str | None = Field(
        default=None, description="Previous package ID superseded by this package"
    )
    superseded_by_package_id: str | None = Field(
        default=None, description="Newer package ID that superseded this package"
    )
    superseded_at: datetime | None = Field(
        default=None, description="Timestamp when this package was superseded in UTC"
    )
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in ALLOWED_CURRENCIES:
            raise ValueError(f"Unsupported currency '{v}'. Allowed: {sorted(ALLOWED_CURRENCIES)}")
        return clean

    @field_validator("accounting_period_start", "accounting_period_end")
    @classmethod
    def validate_period_timestamps(cls, v: datetime) -> datetime:
        utc_dt = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        return utc_dt.astimezone(UTC)

    @model_validator(mode="after")
    def validate_period_boundaries(self) -> "PeriodCloseEvidencePackage":
        if self.accounting_period_end <= self.accounting_period_start:
            raise ValueError(
                f"accounting_period_end ({self.accounting_period_end.isoformat()}) must be strictly after "
                f"accounting_period_start ({self.accounting_period_start.isoformat()})"
            )
        return self

    def get_canonical_dict(self) -> dict[str, Any]:
        """
        Produce a deterministic canonical dictionary of the package claims for digital signing.
        Excludes manifest_signature itself to prevent circular reference.
        """
        exp = CURRENCY_EXPONENTS.get(self.currency, 2)
        fmt_str = f"{{:.{exp}f}}"
        return {
            "package_id": self.package_id,
            "version_number": self.version_number,
            "supersedes_package_id": self.supersedes_package_id,
            "business_id": self.business_id,
            "providers": sorted(self.providers),
            "accounting_period_start": self.accounting_period_start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "accounting_period_end": self.accounting_period_end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timezone": self.timezone,
            "currency": self.currency,
            "provider_api_versions": {k: self.provider_api_versions[k] for k in sorted(self.provider_api_versions)},
            "source_record_counts": {k: self.source_record_counts[k] for k in sorted(self.source_record_counts)},
            "transaction_identity_digests": {
                k: self.transaction_identity_digests[k] for k in sorted(self.transaction_identity_digests)
            },
            "shopify_commercial_totals": {
                k: fmt_str.format(self.shopify_commercial_totals[k])
                for k in sorted(self.shopify_commercial_totals)
            },
            "stripe_capture_and_refund_totals": {
                k: fmt_str.format(self.stripe_capture_and_refund_totals[k])
                for k in sorted(self.stripe_capture_and_refund_totals)
            },
            "stripe_fee_and_settlement_totals": {
                k: fmt_str.format(self.stripe_fee_and_settlement_totals[k])
                for k in sorted(self.stripe_fee_and_settlement_totals)
            },
            "reconciliation_summary": {
                "matched_count": self.reconciliation_matched_count,
                "partial_count": self.reconciliation_partial_count,
                "unmatched_orders_count": self.reconciliation_unmatched_orders_count,
                "unmatched_payments_count": self.reconciliation_unmatched_payments_count,
                "conflict_count": self.reconciliation_conflict_count,
                "is_fully_reconciled": self.is_fully_reconciled,
            },
            "attestation": {
                "attestation_id": self.attestation.attestation_id,
                "attested_by_user_id": self.attestation.attested_by_user_id,
                "attester_role": self.attestation.attester_role,
                "attestation_statement": self.attestation.attestation_statement,
                "attested_at": self.attestation.attested_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "is_synthetic": self.attestation.is_synthetic,
                "provenance_type": self.attestation.provenance_type,
            },
            "trusted_key_id": self.trusted_key_id,
        }

    def get_canonical_bytes(self) -> bytes:
        """Serialize canonical dictionary to RFC-8785 deterministic UTF-8 JSON bytes."""
        canonical_dict = self.get_canonical_dict()
        canonical_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return canonical_str.encode("utf-8")

    def compute_canonical_digest(self) -> str:
        """Compute SHA-256 hex digest of canonical JSON bytes."""
        return hashlib.sha256(self.get_canonical_bytes()).hexdigest().lower()
