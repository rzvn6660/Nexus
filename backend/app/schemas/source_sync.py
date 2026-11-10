"""
NEXUS Phase 1J.1 — Typed Source Synchronization Schemas.

Defines provider-neutral schemas for upstream source connectors, synchronization checkpoints,
extracted commercial transactions, period-close evidence, and completeness contracts.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import re
from typing import Any, List, Optional
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator, model_validator

SHA256_HEX_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
ALLOWED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD"}
ALLOWED_SYNC_MODES = {"historical", "incremental", "cdc", "webhook"}
ALLOWED_CHECKPOINT_STATUSES = {"IN_PROGRESS", "COMPLETED", "FAILED", "INCOMPLETE", "PAUSED"}
ALLOWED_PROVENANCE_LEVELS = {
    "tier1_uploader_assertion",
    "tier2_app_metadata",
    "tier3_source_evidence",
}


class ConnectorAuthStatus(BaseModel):
    """Authentication and scope verification status for an upstream source."""

    is_authenticated: bool
    auth_type: str = Field(description="Authentication mechanism: oauth2, api_key, synthetic, mutual_tls")
    account_id: Optional[str] = Field(default=None, description="Remote upstream account/shop identifier")
    scopes: List[str] = Field(default_factory=list, description="Granted permission scopes")
    expires_at: Optional[datetime] = Field(default=None, description="Token expiration timestamp in UTC")
    last_verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_message: Optional[str] = None


class SourceMetadata(BaseModel):
    """Discovery metadata for an upstream data source platform."""

    provider: str = Field(min_length=1, max_length=64, description="Provider identifier (e.g., shopify, stripe, square, synthetic)")
    provider_account_id: str = Field(min_length=1, max_length=255, description="Tenant account ID on the upstream platform")
    source_name: str = Field(min_length=1, max_length=128)
    supported_sync_modes: List[str] = Field(default=["historical", "incremental"])
    supports_period_close: bool = Field(default=True, description="Whether the source native platform provides settlement/period locks")
    settlement_type: Optional[str] = Field(default=None, description="Settlement type: payout, closing_date, settlement_batch, none")
    default_currency: str = Field(default="USD", min_length=3, max_length=3)
    timezone: str = Field(default="UTC", description="IANA standard timezone string")
    rate_limit_info: Optional[dict[str, Any]] = None

    @field_validator("default_currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in ALLOWED_CURRENCIES:
            raise ValueError(f"Unsupported currency '{v}'. Allowed: {sorted(ALLOWED_CURRENCIES)}")
        return clean


class ConnectionHealth(BaseModel):
    """Health check response for an active source connector."""

    is_healthy: bool
    latency_ms: float = Field(ge=0.0)
    quota_remaining: Optional[int] = None
    error_classification: str = Field(default="OK", description="Classification: OK, RATE_LIMITED, AUTH_EXPIRED, NETWORK_TIMEOUT, UNREACHABLE")
    message: str = "Connection healthy"
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExtractedLineItem(BaseModel):
    """Item-level transaction detail extracted from upstream."""

    line_item_id: str
    sku: Optional[str] = None
    title: str
    quantity: int = Field(ge=1)
    unit_price: Decimal = Field(ge=Decimal("0.00"))
    total_amount: Decimal = Field(ge=Decimal("0.00"))
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))


class ExtractedRecord(BaseModel):
    """Normalized commercial transaction extracted from an upstream provider."""

    source_transaction_id: str = Field(min_length=1, max_length=255)
    transaction_number: Optional[str] = None
    customer_source_id: Optional[str] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    transaction_date: datetime
    status: str = Field(description="Order/transaction status: completed, pending, refunded, partially_refunded, cancelled")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    gross_amount: Decimal = Field(ge=Decimal("0.00"))
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    net_amount: Decimal
    fee_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    line_items: List[ExtractedLineItem] = Field(default_factory=list)
    raw_payload_hash: str = Field(description="SHA-256 hash of raw upstream payload")
    provenance_type: str = Field(default="synthetic_sandbox", description="Data provenance: synthetic_sandbox, shopify, stripe, etc.")
    event_type: str = Field(default="transaction.completed")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in ALLOWED_CURRENCIES:
            raise ValueError(f"Unsupported currency '{v}'. Allowed: {sorted(ALLOWED_CURRENCIES)}")
        return clean

    @field_validator("transaction_date")
    @classmethod
    def validate_txn_date(cls, v: datetime) -> datetime:
        utc_dt = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        return utc_dt.astimezone(UTC)


class ExtractionPage(BaseModel):
    """A paginated batch of extracted records along with cursor pagination metadata."""

    records: List[ExtractedRecord]
    page_number: int = Field(ge=1)
    has_more: bool
    next_cursor: Optional[str] = None
    cursor_chain_hash: str = Field(description="Rolling SHA-256 hash of pagination cursors")
    page_records_count: int
    gross_page_sum: Decimal


class PeriodCloseEvidence(BaseModel):
    """
    Independently authenticated period-close or settlement evidence from an upstream platform.
    Represents Tier 3 Source Evidence under the Authoritative Source Completeness Contract.
    """

    provider: str = Field(min_length=1, max_length=64)
    settlement_id: str = Field(min_length=1, max_length=255, description="External settlement/payout/lock identifier")
    settlement_status: str = Field(description="Settlement status: paid, locked, settled, closed")
    settlement_date: datetime
    period_start: datetime
    period_end: datetime
    currency: str = Field(default="USD", min_length=3, max_length=3)
    gross_amount: Decimal = Field(ge=Decimal("0.00"))
    net_amount: Decimal = Field(ge=Decimal("0.00"))
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    fee_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    transaction_count: int = Field(ge=0)
    transaction_id_list_hash: str = Field(description="SHA-256 digest of lexicographically sorted transaction IDs")
    provider_signature: Optional[str] = Field(default=None, description="Cryptographic HMAC or digital signature from upstream platform")
    raw_evidence: dict[str, Any] = Field(default_factory=dict)
    provenance_type: str = Field(default="synthetic_sandbox")
    trust_tier: str = Field(default="tier3_source_evidence")

    @field_validator("trust_tier")
    @classmethod
    def validate_trust_tier(cls, v: str) -> str:
        if v not in ALLOWED_PROVENANCE_LEVELS:
            raise ValueError(f"Invalid trust_tier '{v}'. Allowed: {sorted(ALLOWED_PROVENANCE_LEVELS)}")
        return v


class SyncCheckpoint(BaseModel):
    """Durable state tracking an active or completed synchronization run."""

    checkpoint_id: str = Field(default_factory=lambda: str(uuid4()))
    business_id: str
    provider: str
    sync_mode: str = Field(default="historical")
    period_start: datetime
    period_end: datetime
    status: str = Field(default="IN_PROGRESS")
    is_complete: bool = False
    current_cursor: Optional[str] = None
    cursor_chain_hash: str = Field(default="0" * 64)
    records_extracted: int = 0
    records_ingested: int = 0
    records_rejected: int = 0
    records_duplicate: int = 0
    gross_amount: Decimal = Decimal("0.00")
    net_amount: Decimal = Decimal("0.00")
    tax_amount: Decimal = Decimal("0.00")
    fee_amount: Decimal = Decimal("0.00")
    transaction_set_digest: Optional[str] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    last_event_timestamp: Optional[datetime] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: Optional[datetime] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in ALLOWED_CHECKPOINT_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Allowed: {sorted(ALLOWED_CHECKPOINT_STATUSES)}")
        return clean


class SyncResult(BaseModel):
    """Final output of an executed synchronization run."""

    sync_run_id: str = Field(default_factory=lambda: str(uuid4()))
    business_id: str
    provider: str
    period_start: datetime
    period_end: datetime
    status: str
    is_complete: bool
    records_extracted: int
    records_ingested: int
    records_rejected: int
    records_duplicate: int
    cursor_chain_hash: str
    transaction_set_digest: str
    reported_gross: Decimal
    reported_net: Decimal
    reported_tax: Decimal
    reported_fee: Decimal
    provenance_type: str
    errors: List[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime
    period_close_evidence: Optional[PeriodCloseEvidence] = None
