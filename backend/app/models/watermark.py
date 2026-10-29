"""Tenant-scoped Authoritative Ingestion Watermark Model (Phase 1F.2).

Tracks certified complete-through event horizons for tenant data sources,
guaranteeing historical cadence validation does not mistake missing or
delayed data for customer inactivity.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Business, IngestionJob


class TenantIngestionWatermark(Base, TimestampMixin):
    """
    Tenant-scoped authoritative ingestion watermark contract.

    Certifies that all transaction events for a specific data source up to
    `complete_through_dt` have been fully ingested and reconciled.
    """

    __tablename__ = "tenant_ingestion_watermarks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    business_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Tenant business identifier",
    )
    source_id: Mapped[str] = mapped_column(
        String(64),
        default="default",
        nullable=False,
        index=True,
        doc="Source or channel identifier: e.g. default, pos_primary, shopify, wholesale_invoices",
    )
    complete_through_dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Certified complete-through event datetime in UTC",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Timestamp when this watermark was recorded or certified",
    )
    ingestion_job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Provenance link to IngestionJob that established this watermark",
    )
    provenance_type: Mapped[str] = mapped_column(
        String(64),
        default="manual_close",
        nullable=False,
        doc="Provenance type: manual_close, batch_file, cdc_stream, pos_daily_sync, accounting_period_close, synthetic_fixture",
    )
    verification_status: Mapped[str] = mapped_column(
        String(32),
        default="verified",
        nullable=False,
        doc="Status: verified, invalidated, provisional",
    )
    invalidation_reason: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        doc="Reason why this watermark was invalidated (e.g. backfill, job failure, data correction)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        doc="Whether this is the current active watermark for the tenant and source",
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        doc="Optional metadata: source row counts, checksums, reporting batch IDs",
    )

    # Relationships
    business: Mapped["Business"] = relationship(
        "Business", foreign_keys=[business_id], lazy="selectin"
    )
    ingestion_job: Mapped["IngestionJob | None"] = relationship(
        "IngestionJob", foreign_keys=[ingestion_job_id], lazy="selectin"
    )

    __table_args__ = (
        Index("ix_tenant_wm_biz_source_active", "business_id", "source_id", "is_active"),
        Index("ix_tenant_wm_biz_complete_dt", "business_id", "complete_through_dt"),
        Index(
            "uq_tenant_watermarks_active_source",
            "business_id",
            "source_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    @property
    def complete_through_utc(self) -> datetime:
        dt = self.complete_through_dt
        if dt is None:
            return None  # type: ignore[return-value]
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    def __repr__(self) -> str:
        return (
            f"<TenantIngestionWatermark(id='{self.id}', biz='{self.business_id}', "
            f"source='{self.source_id}', complete_through='{self.complete_through_dt.isoformat()}', "
            f"status='{self.verification_status}', active={self.is_active})>"
        )

