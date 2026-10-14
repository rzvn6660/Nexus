"""Add continuous intelligence tables (Phase 29 Stage 1).

Revision ID: 015_phase29_continuous_intelligence
Revises: 014_phase28_outcome_tracking
Create Date: 2026-10-13 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "015_phase29_continuous_intelligence"
down_revision: str | None = "014_phase28_outcome_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Create continuous_scan_runs table
    if not insp.has_table("continuous_scan_runs"):
        op.create_table(
            "continuous_scan_runs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("business_id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="MANUAL"),
            sa.Column("metrics_scanned", sa.JSON(), nullable=False),
            sa.Column("findings_detected_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("findings_new_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("findings_updated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("execution_time_ms", sa.Float(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_continuous_scan_runs_business_id", "continuous_scan_runs", ["business_id"])
        op.create_index("ix_continuous_scan_runs_org_id", "continuous_scan_runs", ["organization_id"])
        op.create_index("ix_continuous_scan_runs_biz_created", "continuous_scan_runs", ["business_id", "created_at"])

    # 2. Create continuous_findings table
    if not insp.has_table("continuous_findings"):
        op.create_table(
            "continuous_findings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("business_id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("scan_run_id", sa.Integer(), nullable=True),
            sa.Column("decision_id", sa.Integer(), nullable=True),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("metric_key", sa.String(length=64), nullable=False),
            sa.Column("entity_type", sa.String(length=32), nullable=False, server_default="business"),
            sa.Column("entity_id", sa.String(length=128), nullable=False, server_default="all"),
            sa.Column("entity_name", sa.String(length=255), nullable=True),
            sa.Column("change_type", sa.String(length=32), nullable=False),
            sa.Column("severity", sa.String(length=32), nullable=False, server_default="MEDIUM"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("current_value", sa.Float(), nullable=False),
            sa.Column("baseline_value", sa.Float(), nullable=False),
            sa.Column("delta_value", sa.Float(), nullable=False),
            sa.Column("relative_change_pct", sa.Float(), nullable=False),
            sa.Column("unit", sa.String(length=32), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("baseline_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("baseline_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.8"),
            sa.Column("business_impact_score", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("urgency_score", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("evidence_quality", sa.String(length=32), nullable=False, server_default="MEDIUM"),
            sa.Column("calculation_details", sa.JSON(), nullable=False),
            sa.Column("provenance_json", sa.JSON(), nullable=False),
            sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["scan_run_id"], ["continuous_scan_runs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["decision_id"], ["decision_records.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "uq_continuous_findings_open_fingerprint",
            "continuous_findings",
            ["business_id", "fingerprint"],
            unique=True,
            postgresql_where=sa.text("status IN ('ACTIVE', 'ACKNOWLEDGED')"),
            sqlite_where=sa.text("status IN ('ACTIVE', 'ACKNOWLEDGED')"),
        )
        op.create_index("ix_continuous_findings_business_id", "continuous_findings", ["business_id"])
        op.create_index("ix_continuous_findings_org_id", "continuous_findings", ["organization_id"])
        op.create_index("ix_continuous_findings_scan_run_id", "continuous_findings", ["scan_run_id"])
        op.create_index("ix_continuous_findings_decision_id", "continuous_findings", ["decision_id"])
        op.create_index("ix_continuous_findings_fingerprint", "continuous_findings", ["fingerprint"])
        op.create_index("ix_continuous_findings_metric_key", "continuous_findings", ["metric_key"])
        op.create_index("ix_continuous_findings_status", "continuous_findings", ["status"])
        op.create_index("ix_continuous_findings_biz_status", "continuous_findings", ["business_id", "status"])
        op.create_index("ix_continuous_findings_biz_fingerprint", "continuous_findings", ["business_id", "fingerprint"])
        op.create_index("ix_continuous_findings_biz_metric", "continuous_findings", ["business_id", "metric_key", "entity_type"])

    # 3. Create continuous_finding_feedback table
    if not insp.has_table("continuous_finding_feedback"):
        op.create_table(
            "continuous_finding_feedback",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("finding_id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.String(length=36), nullable=False),
            sa.Column("organization_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("feedback_type", sa.String(length=32), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["finding_id"], ["continuous_findings.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_finding_feedback_finding_id", "continuous_finding_feedback", ["finding_id"])
        op.create_index("ix_finding_feedback_business_id", "continuous_finding_feedback", ["business_id"])
        op.create_index("ix_finding_feedback_user_id", "continuous_finding_feedback", ["user_id"])
        op.create_index("ix_finding_feedback_biz_finding", "continuous_finding_feedback", ["business_id", "finding_id"])


def downgrade() -> None:
    op.drop_table("continuous_finding_feedback")
    op.drop_table("continuous_findings")
    op.drop_table("continuous_scan_runs")
