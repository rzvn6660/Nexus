"""SQLAlchemy ORM models for Analysis Runs and Human-in-the-Loop Decision Records."""

from datetime import datetime, timezone
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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AnalysisRun(Base, TimestampMixin):
    """
    Persistent audit ledger of agentic analytical executions.
    Stores the user query, resolved intent, computational output, tool telemetry,
    and associated proof packet for historical accountability.
    """
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    explanation_level: Mapped[str] = mapped_column(String(32), default="manager")
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    execution_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tools_used: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    calculations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    assumptions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    limitations: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    evidence_records: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    rag_citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    decisions: Mapped[list["DecisionRecord"]] = relationship(
        "DecisionRecord",
        back_populates="analysis",
        cascade="all, delete-orphan",
    )


class DecisionRecord(Base, TimestampMixin):
    """
    Human-in-the-Loop (HITL) review and authorization ledger.
    Tracks recommendations proposed by NEXUS and their human review status:
    PENDING -> APPROVED / REJECTED / MODIFIED.
    """
    __tablename__ = "decision_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    analysis: Mapped["AnalysisRun | None"] = relationship(
        "AnalysisRun",
        back_populates="decisions",
    )
