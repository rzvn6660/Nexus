"""Add outcome_window_days and decision_outcome_observations table (Phase 28 Stage 2).

Revision ID: 014_phase28_outcome_tracking
Revises: 013_phase28_decision_memory_foundation
Create Date: 2026-10-12 23:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014_phase28_outcome_tracking"
down_revision: str | None = "013_phase28_decision_memory_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Extend decision_records with outcome_window_days
    if insp.has_table("decision_records"):
        existing_cols = {c["name"] for c in insp.get_columns("decision_records")}
        if "outcome_window_days" not in existing_cols:
            op.add_column(
                "decision_records",
                sa.Column("outcome_window_days", sa.Integer(), nullable=True, server_default="30"),
            )

    # 2. Create decision_outcome_observations table
    if not insp.has_table("decision_outcome_observations"):
        op.create_table(
            "decision_outcome_observations",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("decision_id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("metric_name", sa.String(length=64), nullable=False),
            sa.Column("unit", sa.String(length=32), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("observed_value", sa.Float(), nullable=False),
            sa.Column("source", sa.String(length=128), nullable=False),
            sa.Column("dataset_version", sa.String(length=64), nullable=True),
            sa.Column("coverage_pct", sa.Float(), nullable=False, server_default="100.0"),
            sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("actor_id", sa.String(length=128), nullable=False),
            sa.Column("actor_role", sa.String(length=64), nullable=False, server_default="system"),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["decision_id"], ["decision_records.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("business_id", "idempotency_key", name="uq_outcome_obs_biz_idemp"),
        )
        op.create_index("ix_outcome_obs_decision_id", "decision_outcome_observations", ["decision_id"])
        op.create_index("ix_outcome_obs_business_id", "decision_outcome_observations", ["business_id"])
        op.create_index("ix_outcome_obs_decision_metric", "decision_outcome_observations", ["decision_id", "metric_name"])
        op.create_index("ix_outcome_obs_period", "decision_outcome_observations", ["period_start", "period_end"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("decision_outcome_observations"):
        op.drop_table("decision_outcome_observations")

    if insp.has_table("decision_records"):
        existing_cols = {c["name"] for c in insp.get_columns("decision_records")}
        if "outcome_window_days" in existing_cols:
            op.drop_column("decision_records", "outcome_window_days")
