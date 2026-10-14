"""SQLAlchemy ORM models for Continuous Intelligence (Phase 29).

Tracks proactive business metric observations, anomaly detections,
finding lifecycles, user feedback, and linkage to human decision records.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class FindingScanRun(Base, TimestampMixin):
    """
    Execution audit ledger for continuous intelligence detection scans.
    Records scan telemetry, triggers, runtime, and finding counts.
    """
    __tablename__ = "continuous_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    metrics_scanned: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    findings_detected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    findings: Mapped[list["ContinuousFinding"]] = relationship(
        "ContinuousFinding",
        back_populates="scan_run",
        cascade="save-update, merge",
    )

    __table_args__ = (
        Index("ix_continuous_scan_runs_biz_created", "business_id", "created_at"),
    )


class ContinuousFinding(Base, TimestampMixin):
    """
    Proactively surfaced business finding or metric anomaly.

    Invariants:
    - Multi-tenant isolation: Bound strictly to business_id and organization_id.
    - Idempotency & Deduplication: fingerprint uniquely identifies the metric shift.
      Active unresolved findings with matching fingerprints are updated in place
      rather than spawning duplicate alert notifications.
    - Observational evidence only: Does not execute autonomous changes or assert
      unsubstantiated causal claims.
    """
    __tablename__ = "continuous_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    scan_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("continuous_scan_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("decision_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    metric_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, default="business")
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False, default="all")
    entity_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="MEDIUM", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_value: Mapped[float] = mapped_column(Float, nullable=False)
    delta_value: Mapped[float] = mapped_column(Float, nullable=False)
    relative_change_pct: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    baseline_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    baseline_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    business_impact_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    urgency_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    evidence_quality: Mapped[str] = mapped_column(String(32), nullable=False, default="MEDIUM")
    calculation_details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Relationships
    scan_run: Mapped["FindingScanRun | None"] = relationship(
        "FindingScanRun", back_populates="findings"
    )
    feedback_entries: Mapped[list["FindingFeedback"]] = relationship(
        "FindingFeedback",
        back_populates="finding",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_continuous_findings_open_fingerprint",
            "business_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("status IN ('ACTIVE', 'ACKNOWLEDGED')"),
            sqlite_where=text("status IN ('ACTIVE', 'ACKNOWLEDGED')"),
        ),
        Index("ix_continuous_findings_biz_status", "business_id", "status"),
        Index("ix_continuous_findings_biz_fingerprint", "business_id", "fingerprint"),
        Index("ix_continuous_findings_biz_metric", "business_id", "metric_key", "entity_type"),
    )


class FindingFeedback(Base, TimestampMixin):
    """
    Human analyst and executive feedback on a continuous intelligence finding.
    Enables tracking helpfulness, false positives, and tuning future prioritization.
    """
    __tablename__ = "continuous_finding_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("continuous_findings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)  # HELPFUL, UNHELPFUL, FALSE_POSITIVE, IGNORED
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    finding: Mapped["ContinuousFinding"] = relationship(
        "ContinuousFinding", back_populates="feedback_entries"
    )

    __table_args__ = (
        Index("ix_finding_feedback_biz_finding", "business_id", "finding_id"),
    )
