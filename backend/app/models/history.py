"""SQLAlchemy ORM models for Analysis Runs and Human-in-the-Loop Decision Records."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AnalysisRun(Base, TimestampMixin):
    """
    Persistent audit ledger of agentic analytical executions.
    Stores the user query, resolved intent, computational output, tool telemetry,
    and associated proof packet for historical accountability.

    Phase 19 additions:
    - semantic_revision_id / semantic_version: immutable snapshot of the TenantSemanticModel
      used at execution time. These never change even if a newer ACTIVE version is published.
    - dataset_id / dataset_content_hash / ingestion_job_id / dataset_date_coverage:
      dataset state snapshot at run creation time. Enables historical reproducibility.
    """
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
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

    # --- Phase 19: Semantic Snapshot ---
    # Captured once at run creation. Immutable. Survives semantic model upgrades.
    semantic_revision_id: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True,
        doc="TenantSemanticModel.id that was ACTIVE when this run was created."
    )
    semantic_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        doc="Snapshot of TenantSemanticModel.version used at execution time."
    )

    # --- Phase 19: Dataset Snapshot ---
    # Captured once at run creation. References what data was available to the agent.
    dataset_id: Mapped[str | None] = mapped_column(
        String(36), index=True, nullable=True,
        doc="UploadedDataset.id that was active for this business at run time."
    )
    dataset_content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        doc="SHA-256 fingerprint of the dataset at run creation time."
    )
    ingestion_job_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
        doc="Latest completed IngestionJob.id at run creation time."
    )
    dataset_date_coverage: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        doc="Date coverage metadata (start, end, days) captured from dataset at run time."
    )

    # Relationships
    decisions: Mapped[list["DecisionRecord"]] = relationship(
        "DecisionRecord",
        back_populates="analysis",
        cascade="save-update, merge",
    )

    __table_args__ = (
        Index("ix_analysis_runs_business_status", "business_id", "status"),
    )


class DecisionRecord(Base, TimestampMixin):
    """
    Human-in-the-Loop (HITL) review and authorization ledger.
    Tracks recommendations proposed by NEXUS and their human review status:
    PENDING -> APPROVED / REJECTED / MODIFIED / DEFERRED.

    Phase 28 additions:
    - recommendation_type / action_target_type / action_target_id: categorization and targets.
    - recommendation_payload: immutable snapshot of prescriptive recommendation facts,
      forecasts, bounds, assumptions, and limitations at creation time.
    - baseline_metrics_snapshot: pre-decision operational baselines and metric definitions.
    - current_revision: integer tracking latest revision in the append-only audit event stream.
    """
    __tablename__ = "decision_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    analysis_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Phase 28 snapshot and revision tracking
    recommendation_type: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    action_target_type: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    action_target_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    recommendation_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    baseline_metrics_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=30)

    # Relationships
    analysis: Mapped["AnalysisRun | None"] = relationship(
        "AnalysisRun",
        back_populates="decisions",
    )
    audit_events: Mapped[list["DecisionAuditEvent"]] = relationship(
        "DecisionAuditEvent",
        back_populates="decision",
        order_by="DecisionAuditEvent.revision.asc()",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    outcome_observations: Mapped[list["DecisionOutcomeObservation"]] = relationship(
        "DecisionOutcomeObservation",
        back_populates="decision",
        order_by="DecisionOutcomeObservation.period_start.asc()",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_decision_records_business_status", "business_id", "status"),
        Index("ix_decision_records_action_target", "action_target_type", "action_target_id"),
    )


class DecisionAuditEvent(Base, TimestampMixin):
    """
    Append-only cryptographically chained audit ledger for decisions (Phase 28).

    Tracks recommendation creation (genesis r=0), human reviews (APPROVED, REJECTED,
    MODIFIED, DEFERRED), parameter corrections, and execution events.

    Invariants:
    - Revisions strictly sequence: 0, 1, 2, ...
    - prev_event_hash links to prior event's event_hash (or '0'*64 for genesis).
    - event_hash is SHA-256 over RFC 8785 canonical JSON bytes.
    - Idempotency key guarantees safe retries with payload conflict detection.
    - Foreign key to decision_records enforces ON DELETE RESTRICT.
    - Database triggers and ORM listeners reject UPDATE and DELETE operations.
    """
    __tablename__ = "decision_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("decision_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    business_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(64), nullable=False, default="analyst")
    prev_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Relationships
    decision: Mapped["DecisionRecord"] = relationship(
        "DecisionRecord",
        back_populates="audit_events",
    )

    __table_args__ = (
        UniqueConstraint("decision_id", "revision", name="uq_audit_event_decision_rev"),
        UniqueConstraint("decision_id", "idempotency_key", name="uq_audit_event_decision_idemp"),
        Index("ix_audit_events_decision_rev", "decision_id", "revision"),
        Index("ix_audit_events_biz_created", "business_id", "created_at"),
    )


class DecisionOutcomeObservation(Base, TimestampMixin):
    """
    Observed performance evidence captured following a decision (Phase 28 Stage 2).

    Captures empirical metrics (revenue, units sold, stockout days, margin) over
    specified observation periods. Used for outcome-window maturity tracking and
    evidence quality evaluation.

    Invariants:
    - Multi-tenant isolation: bound strictly to business_id and organization_id.
    - Audit preservation: recording an observation automatically emits an
      immutable event in DecisionAuditEvent.
    - Idempotency: business_id + idempotency_key uniqueness prevents duplicate insertions.
    """
    __tablename__ = "decision_outcome_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("decision_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    business_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    decision: Mapped["DecisionRecord"] = relationship(
        "DecisionRecord",
        back_populates="outcome_observations",
    )

    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_outcome_obs_biz_idemp"),
        Index("ix_outcome_obs_decision_metric", "decision_id", "metric_name"),
        Index("ix_outcome_obs_period", "period_start", "period_end"),
    )


class AuditLedgerImmutabilityError(RuntimeError):
    """Raised when an attempt is made to mutate or delete append-only audit ledger events."""


# ORM-level immutability protections
@event.listens_for(DecisionAuditEvent, "before_update")
def _deny_audit_event_update(mapper, connection, target):
    raise AuditLedgerImmutabilityError(
        f"Audit ledger is strictly append-only. UPDATE operations are forbidden on DecisionAuditEvent #{target.id}."
    )


@event.listens_for(DecisionAuditEvent, "before_delete")
def _deny_audit_event_delete(mapper, connection, target):
    raise AuditLedgerImmutabilityError(
        f"Audit ledger is strictly append-only. DELETE operations are forbidden on DecisionAuditEvent #{target.id}."
    )


@event.listens_for(DecisionOutcomeObservation, "before_update")
def _deny_outcome_obs_update(mapper, connection, target):
    raise AuditLedgerImmutabilityError(
        f"Outcome evidence is strictly immutable. UPDATE operations are forbidden on DecisionOutcomeObservation #{target.id}."
    )


@event.listens_for(DecisionOutcomeObservation, "before_delete")
def _deny_outcome_obs_delete(mapper, connection, target):
    raise AuditLedgerImmutabilityError(
        f"Outcome evidence is strictly immutable. DELETE operations are forbidden on DecisionOutcomeObservation #{target.id}."
    )


def install_audit_triggers(connection_or_engine) -> None:
    """Install engine-level UPDATE/DELETE triggers for decision_audit_events."""
    from sqlalchemy.engine import Connection, Engine

    if isinstance(connection_or_engine, Engine):
        with connection_or_engine.begin() as conn:
            _install_triggers_on_conn(conn)
    elif isinstance(connection_or_engine, Connection):
        _install_triggers_on_conn(connection_or_engine)
    else:
        # Session or other connection-like object
        _install_triggers_on_conn(connection_or_engine)


def _install_triggers_on_conn(conn) -> None:
    dialect = conn.dialect.name
    if dialect == "postgresql":
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION trg_deny_audit_mutation() RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Nexus audit ledger is append-only: UPDATE and DELETE operations are strictly forbidden on decision_audit_events.';
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(text("DROP TRIGGER IF EXISTS trg_protect_audit_events ON decision_audit_events;"))
        conn.execute(text("""
            CREATE TRIGGER trg_protect_audit_events
            BEFORE UPDATE OR DELETE ON decision_audit_events
            FOR EACH ROW EXECUTE FUNCTION trg_deny_audit_mutation();
        """))
    elif dialect == "sqlite":
        conn.execute(text("DROP TRIGGER IF EXISTS trg_deny_audit_update;"))
        conn.execute(text("""
            CREATE TRIGGER trg_deny_audit_update
            BEFORE UPDATE ON decision_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit ledger is append-only: UPDATE forbidden on decision_audit_events');
            END;
        """))
        conn.execute(text("DROP TRIGGER IF EXISTS trg_deny_audit_delete;"))
        conn.execute(text("""
            CREATE TRIGGER trg_deny_audit_delete
            BEFORE DELETE ON decision_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit ledger is append-only: DELETE forbidden on decision_audit_events');
            END;
        """))


def drop_audit_triggers(connection_or_engine) -> None:
    """Remove engine-level triggers (e.g. for teardown in migration rollback)."""
    from sqlalchemy.engine import Connection, Engine

    if isinstance(connection_or_engine, Engine):
        with connection_or_engine.begin() as conn:
            _drop_triggers_on_conn(conn)
    elif isinstance(connection_or_engine, Connection):
        _drop_triggers_on_conn(connection_or_engine)
    else:
        _drop_triggers_on_conn(connection_or_engine)


def _drop_triggers_on_conn(conn) -> None:
    dialect = conn.dialect.name
    if dialect == "postgresql":
        conn.execute(text("DROP TRIGGER IF EXISTS trg_protect_audit_events ON decision_audit_events;"))
        conn.execute(text("DROP FUNCTION IF EXISTS trg_deny_audit_mutation();"))
    elif dialect == "sqlite":
        conn.execute(text("DROP TRIGGER IF EXISTS trg_deny_audit_update;"))
        conn.execute(text("DROP TRIGGER IF EXISTS trg_deny_audit_delete;"))

