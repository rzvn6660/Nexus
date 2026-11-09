"""
NEXUS Phase 1J.1 — Connector & Synchronization Models.

Defines persistent models for:
1. ConnectorSyncCheckpoint: Durable state tracking for paginated source syncs.
2. TenantConnectorCredential: Secure storage for encrypted tenant connector credentials.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Business


class ConnectorSyncCheckpoint(Base, TimestampMixin):
    """
    Durable checkpoint tracking background connector synchronization progress.

    Enforces idempotent resumption, pagination verification, cursor hash chaining,
    and row/volume reconciliation telemetry per tenant.
    """

    __tablename__ = "connector_sync_checkpoints"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Tenant business ownership",
    )
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Upstream provider identifier (e.g. shopify, stripe, synthetic)",
    )
    sync_mode: Mapped[str] = mapped_column(
        String(32),
        default="historical",
        nullable=False,
        doc="Sync mode: historical, incremental, cdc, webhook",
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Start timestamp of the sync period in UTC",
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="End timestamp of the sync period in UTC",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="IN_PROGRESS",
        nullable=False,
        index=True,
        doc="Status: IN_PROGRESS, COMPLETED, FAILED, INCOMPLETE, PAUSED",
    )
    is_complete: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether the period sync reached authoritative verified termination",
    )
    current_cursor: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Last successfully processed pagination cursor",
    )
    cursor_chain_hash: Mapped[str] = mapped_column(
        String(64),
        default="0" * 64,
        nullable=False,
        doc="Rolling SHA-256 hash of pagination cursors",
    )
    records_extracted: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Total records fetched from upstream API",
    )
    records_ingested: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Records persisted to NEXUS database",
    )
    records_rejected: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Records rejected due to validation failure",
    )
    records_duplicate: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Records deduplicated and skipped",
    )
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0.00"),
        nullable=False,
        doc="Gross volume extracted",
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0.00"),
        nullable=False,
        doc="Net volume after discounts and refunds",
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0.00"),
        nullable=False,
        doc="Total tax collected",
    )
    fee_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0.00"),
        nullable=False,
        doc="Payment processing fees",
    )
    transaction_set_digest: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA-256 digest of lexicographically sorted transaction IDs",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of retry attempts executed",
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Operational error traceback or summary",
    )
    last_event_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the most recent event ingested",
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Telemetry metadata (e.g. rate limit info, settlement evidence)",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when sync completed or failed",
    )

    # Relationships
    business: Mapped["Business"] = relationship("Business", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "business_id", "provider", "period_start", "period_end",
            name="uq_connector_sync_checkpoint_period"
        ),
        Index("ix_sync_checkpoint_business_status", "business_id", "status"),
    )


class TenantConnectorCredential(Base, TimestampMixin):
    """
    Tenant-scoped connector credential configuration.

    Stores encrypted access credentials (e.g. OAuth tokens, API keys).
    Plaintext secrets are strictly prohibited from being persisted.
    """

    __tablename__ = "tenant_connector_credentials"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Tenant business ownership",
    )
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Upstream provider (e.g. shopify, stripe, synthetic)",
    )
    provider_account_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Upstream account identifier (e.g. shop domain, stripe account id)",
    )
    encrypted_credentials: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="AES-256-GCM encrypted credential payload (base64 encoded)",
    )
    kms_key_id: Mapped[str] = mapped_column(
        String(255),
        default="local_kms_vault",
        nullable=False,
        doc="KMS Key ID or vault key reference used for envelope encryption",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        nullable=False,
        doc="Credential status: ACTIVE, EXPIRED, REVOKED",
    )
    scopes: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        doc="Granted OAuth/API scopes",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Access token expiration timestamp",
    )
    last_rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Timestamp of last credential rotation",
    )

    # Relationships
    business: Mapped["Business"] = relationship("Business", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "business_id", "provider",
            name="uq_tenant_connector_credentials_provider"
        ),
        Index("ix_tenant_connector_status", "business_id", "status"),
    )


class ConnectorWebhookInbox(Base, TimestampMixin):
    """
    Durable, provider-neutral webhook event inbox.

    Provides multi-worker safety, persistent deduplication, atomic claiming,
    retry tracking, payload integrity verification, and auditability.
    Shared by Stripe, Shopify, and all future commercial source connectors.
    """

    __tablename__ = "connector_webhook_inbox"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Tenant business ownership",
    )
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Upstream provider (e.g. stripe, shopify, square)",
    )
    provider_account_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Upstream account identifier (e.g. acct_123, store.myshopify.com)",
    )
    event_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Unique provider event identifier (e.g. evt_123, 891234567890)",
    )
    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Provider event name (e.g. charge.succeeded, orders/create)",
    )
    event_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp embedded in provider event header or payload",
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Timestamp event was received by NEXUS gateway",
    )
    signature_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether the webhook signature was cryptographically verified",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        nullable=False,
        index=True,
        doc="Status: PENDING, CLAIMED, PROCESSED, FAILED, DUPLICATE_IGNORED",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of processing retry attempts",
    )
    payload_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="SHA-256 digest of raw request payload bytes",
    )
    claimed_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        doc="Worker identifier currently processing the event",
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp the event was claimed by a worker",
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp event processing completed",
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error message from last failed processing attempt",
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        doc="Structured non-sensitive audit metadata (order_id, refund_id, etc.)",
    )

    # Relationships
    business: Mapped["Business"] = relationship("Business", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_account_id", "event_id",
            name="uq_connector_webhook_inbox_event"
        ),
        Index("ix_connector_webhook_status", "business_id", "provider", "status"),
    )
