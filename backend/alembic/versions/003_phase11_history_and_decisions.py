"""Create analysis_runs and decision_records tables for Phase 11 V1 audit and HITL ledger.

Revision ID: 003_phase11_history_and_decisions
Revises: 002_phase5_knowledge_schema
Create Date: 2026-09-26 02:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_phase11_history_and_decisions"
down_revision: Union[str, None] = "002_phase5_knowledge_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Analysis Runs Table
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("explanation_level", sa.String(length=32), nullable=False, server_default="manager"),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("execution_time_ms", sa.Float(), nullable=True),
        sa.Column("tools_used", sa.JSON(), nullable=True),
        sa.Column("calculations", sa.JSON(), nullable=True),
        sa.Column("assumptions", sa.JSON(), nullable=True),
        sa.Column("limitations", sa.JSON(), nullable=True),
        sa.Column("evidence_records", sa.JSON(), nullable=True),
        sa.Column("rag_citations", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_analysis_runs_request_id", "analysis_runs", ["request_id"])
    op.create_index("ix_analysis_runs_intent", "analysis_runs", ["intent"])
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"])
    op.create_index("ix_analysis_runs_created_at", "analysis_runs", ["created_at"])

    # 2. Decision Records Table (Human-in-the-Loop)
    op.create_table(
        "decision_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=True),
        sa.Column("recommendation_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analysis_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_records_analysis_id", "decision_records", ["analysis_id"])
    op.create_index("ix_decision_records_status", "decision_records", ["status"])
    op.create_index("ix_decision_records_created_at", "decision_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_decision_records_created_at", table_name="decision_records")
    op.drop_index("ix_decision_records_status", table_name="decision_records")
    op.drop_index("ix_decision_records_analysis_id", table_name="decision_records")
    op.drop_table("decision_records")

    op.drop_index("ix_analysis_runs_created_at", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_status", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_intent", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_request_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
