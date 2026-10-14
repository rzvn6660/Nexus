"""Add Decision Record snapshot columns, DecisionAuditEvent append-only ledger, and engine triggers (Phase 28 Stage 1).

Revision ID: 013_phase28_decision_memory_foundation
Revises: 012_phase25c2_postgresql_fts
Create Date: 2026-10-12 21:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013_phase28_decision_memory_foundation"
down_revision: str | None = "012_phase25c2_postgresql_fts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect_name = bind.dialect.name

    # 1. Extend decision_records with snapshot and revision tracking
    if insp.has_table("decision_records"):
        existing_cols = {c["name"] for c in insp.get_columns("decision_records")}
        if "recommendation_type" not in existing_cols:
            op.add_column("decision_records", sa.Column("recommendation_type", sa.String(length=64), nullable=True))
            op.create_index("ix_decision_records_recommendation_type", "decision_records", ["recommendation_type"])

        if "action_target_type" not in existing_cols:
            op.add_column("decision_records", sa.Column("action_target_type", sa.String(length=32), nullable=True))

        if "action_target_id" not in existing_cols:
            op.add_column("decision_records", sa.Column("action_target_id", sa.String(length=128), nullable=True))

        if "action_target_type" in existing_cols or "action_target_id" in existing_cols or "action_target_type" not in existing_cols:
            existing_indices = {idx["name"] for idx in insp.get_indexes("decision_records")}
            if "ix_decision_records_action_target" not in existing_indices:
                op.create_index("ix_decision_records_action_target", "decision_records", ["action_target_type", "action_target_id"])

        if "recommendation_payload" not in existing_cols:
            op.add_column("decision_records", sa.Column("recommendation_payload", sa.JSON(), nullable=True))

        if "baseline_metrics_snapshot" not in existing_cols:
            op.add_column("decision_records", sa.Column("baseline_metrics_snapshot", sa.JSON(), nullable=True))

        if "current_revision" not in existing_cols:
            op.add_column("decision_records", sa.Column("current_revision", sa.Integer(), nullable=False, server_default="0"))

    # 2. Create decision_audit_events table
    if not insp.has_table("decision_audit_events"):
        op.create_table(
            "decision_audit_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("decision_id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("actor_id", sa.String(length=128), nullable=False),
            sa.Column("actor_role", sa.String(length=64), nullable=False, server_default="analyst"),
            sa.Column("prev_event_hash", sa.String(length=64), nullable=False),
            sa.Column("event_hash", sa.String(length=64), nullable=False),
            sa.Column("canonical_payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["decision_id"], ["decision_records.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("decision_id", "revision", name="uq_audit_event_decision_rev"),
            sa.UniqueConstraint("decision_id", "idempotency_key", name="uq_audit_event_decision_idemp"),
        )
        op.create_index("ix_decision_audit_events_decision_id", "decision_audit_events", ["decision_id"])
        op.create_index("ix_decision_audit_events_business_id", "decision_audit_events", ["business_id"])
        op.create_index("ix_decision_audit_events_event_type", "decision_audit_events", ["event_type"])
        op.create_index("ix_decision_audit_events_created_at", "decision_audit_events", ["created_at"])
        op.create_index("ix_decision_audit_events_decision_rev", "decision_audit_events", ["decision_id", "revision"])
        op.create_index("ix_decision_audit_events_biz_created", "decision_audit_events", ["business_id", "created_at"])

    # 3. Database engine-specific append-only triggers
    if dialect_name == "postgresql":
        op.execute(sa.text("""
            CREATE OR REPLACE FUNCTION trg_deny_audit_mutation() RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Nexus audit ledger is append-only: UPDATE and DELETE operations are strictly forbidden on decision_audit_events.';
            END;
            $$ LANGUAGE plpgsql;
        """))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_protect_audit_events ON decision_audit_events;"))
        op.execute(sa.text("""
            CREATE TRIGGER trg_protect_audit_events
            BEFORE UPDATE OR DELETE ON decision_audit_events
            FOR EACH ROW EXECUTE FUNCTION trg_deny_audit_mutation();
        """))
    elif dialect_name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_deny_audit_update;"))
        op.execute(sa.text("""
            CREATE TRIGGER trg_deny_audit_update
            BEFORE UPDATE ON decision_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit ledger is append-only: UPDATE forbidden on decision_audit_events');
            END;
        """))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_deny_audit_delete;"))
        op.execute(sa.text("""
            CREATE TRIGGER trg_deny_audit_delete
            BEFORE DELETE ON decision_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit ledger is append-only: DELETE forbidden on decision_audit_events');
            END;
        """))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect_name = bind.dialect.name

    if dialect_name == "postgresql":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_protect_audit_events ON decision_audit_events;"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS trg_deny_audit_mutation();"))
    elif dialect_name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_deny_audit_update;"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_deny_audit_delete;"))

    if insp.has_table("decision_audit_events"):
        op.drop_table("decision_audit_events")

    if insp.has_table("decision_records"):
        existing_cols = {c["name"] for c in insp.get_columns("decision_records")}
        if "current_revision" in existing_cols:
            op.drop_column("decision_records", "current_revision")
        if "baseline_metrics_snapshot" in existing_cols:
            op.drop_column("decision_records", "baseline_metrics_snapshot")
        if "recommendation_payload" in existing_cols:
            op.drop_column("decision_records", "recommendation_payload")
        if "action_target_id" in existing_cols:
            op.drop_column("decision_records", "action_target_id")
        if "action_target_type" in existing_cols:
            op.drop_column("decision_records", "action_target_type")
        if "recommendation_type" in existing_cols:
            op.drop_column("decision_records", "recommendation_type")
