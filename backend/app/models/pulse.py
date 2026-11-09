"""SQLAlchemy ORM models for NEXUS Pulse: Management Intelligence & Automated Reporting.

Provides durable tracking for:
1. PulseReportSchedule: Automated recurring reporting schedules and manager preferences.
2. PulseGeneratedReport: Immutable snapshot of generated executive business intelligence reports.
3. PulseDeliveryLog: Multi-channel dispatch audit trail (WhatsApp, Telegram, Email).
4. PulseRecipientPreference: Authorized recipient contacts, channel routing, and opt-in/opt-out status.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class PulseReportSchedule(Base, TimestampMixin):
    """
    Manager-configured automated reporting schedule.
    Controls recurring delivery of executive monthly, weekly management, or custom intelligence reports.
    """
    __tablename__ = "pulse_report_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    report_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="MONTHLY_EXECUTIVE"
    )  # MONTHLY_EXECUTIVE, WEEKLY_MANAGEMENT, CUSTOM
    frequency: Mapped[str] = mapped_column(
        String(32), nullable=False, default="MONTHLY"
    )  # MONTHLY, WEEKLY, DAILY, EVENT_DRIVEN
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-31
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=Monday, 6=Sunday
    time_of_day: Mapped[str] = mapped_column(String(8), nullable=False, default="09:00")  # HH:MM
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    channel_types: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["WHATSAPP"]
    )  # ["WHATSAPP", "TELEGRAM", "EMAIL"]
    recipients_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )  # [{"name": "Jane", "channel": "WHATSAPP", "destination": "+15551234567", "role": "Owner"}]
    kpi_categories: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["FINANCIAL", "CUSTOMER", "CHURN", "RETENTION", "PRODUCT", "OPERATIONAL"]
    )
    alert_triggers: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=lambda: {
            "critical_churn_spike": True,
            "revenue_anomaly": True,
            "watermark_invalid": True,
            "retention_attention_required": True,
        }
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Relationships
    reports: Mapped[list["PulseGeneratedReport"]] = relationship(
        "PulseGeneratedReport", back_populates="schedule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_pulse_schedules_biz_active", "business_id", "is_enabled"),
        Index("ix_pulse_schedules_next_run", "is_enabled", "next_run_at"),
    )


class PulseGeneratedReport(Base, TimestampMixin):
    """
    Durable, immutable record of an executive business intelligence report.
    Contains full KPI snapshots, generated insights, executive prose, messaging summary,
    and references to the generated PDF.
    """
    __tablename__ = "pulse_generated_reports"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pulse_report_schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    report_title: Mapped[str] = mapped_column(String(255), nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False)  # MONTHLY_EXECUTIVE, WEEKLY_MANAGEMENT, CUSTOM
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    comparison_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comparison_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Structured Payloads
    kpi_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    insights_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    messaging_summary: Mapped[str] = mapped_column(Text, nullable=False)  # WhatsApp/Telegram markdown text

    # PDF Storage & Verification
    pdf_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_file_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Data Provenance & Safety
    watermark_status: Mapped[str] = mapped_column(String(64), nullable=False, default="verified_complete")
    data_provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Secure Token for Expiring Web/Public Viewing
    access_token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, default=lambda: uuid4().hex
    )
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    schedule: Mapped["PulseReportSchedule | None"] = relationship(
        "PulseReportSchedule", back_populates="reports"
    )
    deliveries: Mapped[list["PulseDeliveryLog"]] = relationship(
        "PulseDeliveryLog", back_populates="report", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_pulse_reports_biz_created", "business_id", "created_at"),
        Index("ix_pulse_reports_token_expiry", "access_token", "token_expires_at"),
    )


class PulseDeliveryLog(Base, TimestampMixin):
    """
    Append-only audit trail of multi-channel notification dispatches.
    Records recipient, channel, delivery status, provider message IDs, and failure reasons.
    """
    __tablename__ = "pulse_delivery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pulse_generated_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # WHATSAPP, TELEGRAM, EMAIL
    recipient_destination: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # Masked/Normalized destination (phone, chat_id, email)
    recipient_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PENDING", index=True
    )  # PENDING, SENT, DELIVERED, FAILED, MOCKED
    external_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    report: Mapped["PulseGeneratedReport"] = relationship(
        "PulseGeneratedReport", back_populates="deliveries"
    )

    __table_args__ = (
        Index("ix_pulse_deliveries_biz_status", "business_id", "status"),
        Index("ix_pulse_deliveries_report_channel", "report_id", "channel"),
    )


class PulseRecipientPreference(Base, TimestampMixin):
    """
    Tenant-scoped recipient registry with verified channel destinations and opt-in/opt-out status.
    Ensures that WhatsApp, Telegram, or Email notifications are never dispatched to opted-out parties.
    """
    __tablename__ = "pulse_recipient_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_name: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)  # WHATSAPP, TELEGRAM, EMAIL
    destination: Mapped[str] = mapped_column(String(255), nullable=False)  # Phone number, Chat ID, Email
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="Executive")
    opt_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="OPTED_IN", index=True
    )  # OPTED_IN, OPTED_OUT, PENDING_CONFIRMATION
    opted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    opt_out_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("uq_pulse_recipient_biz_channel_dest", "business_id", "channel", "destination", unique=True),
    )
