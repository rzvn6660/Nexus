"""
ORM models for NEXUS Phase 1I.4 — Trusted Keys and Manifest Submissions.

Implements persistent storage for:
1. TenantTrustedKey: persistent tenant-scoped trusted keys (replaces in-memory registry, C2).
2. ManifestSubmission: persistent tamper-evident audit ledger for period-close submissions (M2).
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
    from app.models.tenant import Business, UserIdentity
    from app.models.watermark import TenantIngestionWatermark


class TenantTrustedKey(Base, TimestampMixin):
    """
    Tenant-scoped persistent trusted key entry for period-close manifest verification.

    Stores public key material only (Ed25519 public key / HMAC shared key reference).
    Plaintext private keys are strictly prohibited in the database.
    """

    __tablename__ = "tenant_trusted_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Tenant business workspace ownership",
    )
    key_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Key identifier unique within the tenant business",
    )
    algorithm: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Algorithm: ed25519 or hmac-sha256",
    )
    public_key_pem: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Public key material in standard PEM or hex format; private keys strictly prohibited",
    )
    key_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Optional external KMS key ARN or Vault path for operational tracking",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        nullable=False,
        doc="Key status: active, revoked, expired, rotated",
    )
    allowed_roles: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: ["owner", "admin"],
        nullable=False,
        doc="List of organization roles permitted to sign with this key",
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Key validity start timestamp in UTC",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Key expiration timestamp in UTC",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when key was revoked",
    )
    revoked_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Operational reason for key revocation",
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who provisioned this key",
    )

    # Relationships
    business: Mapped["Business"] = relationship("Business", lazy="selectin")
    created_by_user: Mapped["UserIdentity | None"] = relationship("UserIdentity", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("business_id", "key_id", name="uq_tenant_trusted_keys_business_key"),
        Index("ix_tenant_trusted_keys_status", "business_id", "status"),
    )


class ManifestSubmission(Base, TimestampMixin):
    """
    Persistent audit ledger of period-close manifest submissions.

    Preserves successful and failed submission attempts with tamper-evident claims,
    file SHA-256 hashes, reconciliation telemetry, and DB reconciliation status.
    """

    __tablename__ = "manifest_submissions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    manifest_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        doc="Unique manifest identifier (UUIDv4) preventing replay",
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Tenant business workspace ownership",
    )
    source_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Source system identifier (pos, netsuite, shopify)",
    )
    batch_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Source export batch ID",
    )
    provenance_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Provenance type: accounting_period_close, batch_file",
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Certified period start timestamp in UTC",
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Certified period end boundary timestamp in UTC",
    )
    source_export_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="Upstream source export ID",
    )
    export_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Upstream generation completion timestamp in UTC",
    )
    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Original export file name",
    )
    file_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Hex-encoded SHA-256 digest of received file",
    )
    expected_row_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Expected sales row count declared in manifest",
    )
    expected_gross_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        doc="Expected gross monetary total declared in manifest",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="USD",
        nullable=False,
        doc="ISO-4217 currency code",
    )
    attested_by_user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="User ID claimed in attestation signature (untrusted uploader claim)",
    )
    attester_role: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Role claimed in attestation (owner, admin, finance_controller)",
    )
    attestation_statement: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Legal/operational attestation declaration text",
    )
    attested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Timestamp of attestation in UTC",
    )
    submitted_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Authenticated user ID who executed the upload API call",
    )
    signature_algorithm: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Signature algorithm used (ed25519, hmac-sha256)",
    )
    signature_key_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Trusted key identifier used for verification",
    )
    verification_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Result: provisional, verified, failed, rejected",
    )
    reconciliation_matched: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether tabular parsing matched expected totals",
    )
    reconciliation_breakdown_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Breakdown of actual row counts, gross sums, refunds, cancellations",
    )
    source_close_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="External corroborating source-close report telemetry",
    )
    db_reconciled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether persisted PostgreSQL sales rows match manifest claims",
    )
    db_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of successful database row-level reconciliation",
    )
    db_persisted_row_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Observed row count in PostgreSQL sales table at promotion",
    )
    db_persisted_gross_total: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
        doc="Observed gross revenue sum in PostgreSQL sales table at promotion",
    )
    watermark_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("tenant_ingestion_watermarks.id", ondelete="SET NULL"),
        nullable=True,
        doc="Associated watermark record if created",
    )
    error_details_json: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="List of rejection or failure error messages if failed",
    )

    # Relationships
    business: Mapped["Business"] = relationship("Business", lazy="selectin")
    submitted_by_user: Mapped["UserIdentity"] = relationship(
        "UserIdentity", foreign_keys=[submitted_by_user_id], lazy="selectin"
    )
    watermark: Mapped["TenantIngestionWatermark | None"] = relationship(
        "TenantIngestionWatermark", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_manifest_submissions_biz_batch", "business_id", "batch_id"),
        Index("ix_manifest_submissions_biz_period", "business_id", "period_end"),
    )
