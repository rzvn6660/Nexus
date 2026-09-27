"""Add tenant-aware run lifecycle snapshot columns to analysis_runs (Phase 19).

Adds semantic snapshot (revision_id, version) and dataset snapshot (dataset_id,
content_hash, ingestion_job_id, date_coverage) so every AnalysisRun permanently
references the exact semantic model version and dataset state used at execution time.

Revision ID: 008_phase19_run_lifecycle_snapshots
Revises: 007_phase17_business_understanding_semantic
Create Date: 2026-09-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "008_phase19_run_lifecycle_snapshots"
down_revision: Union[str, None] = "007_phase17_business_understanding_semantic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Semantic snapshot columns on analysis_runs
    # -----------------------------------------------------------------------
    op.add_column(
        "analysis_runs",
        sa.Column(
            "semantic_revision_id",
            sa.String(length=36),
            nullable=True,
            comment="FK to tenant_semantic_models.id at the moment the run was created",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "semantic_version",
            sa.Integer(),
            nullable=True,
            comment="Immutable snapshot of TenantSemanticModel.version used by this run",
        ),
    )

    # -----------------------------------------------------------------------
    # 2. Dataset snapshot columns on analysis_runs
    # -----------------------------------------------------------------------
    op.add_column(
        "analysis_runs",
        sa.Column(
            "dataset_id",
            sa.String(length=36),
            nullable=True,
            comment="FK to uploaded_datasets.id at run creation time",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "dataset_content_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 content fingerprint of the dataset at run creation time",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "ingestion_job_id",
            sa.String(length=36),
            nullable=True,
            comment="Latest completed IngestionJob.id at run creation time",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "dataset_date_coverage",
            sa.JSON(),
            nullable=True,
            comment="Date coverage metadata dict (start, end, days) captured at run time",
        ),
    )

    # -----------------------------------------------------------------------
    # 3. Supporting indexes for efficient history queries
    # -----------------------------------------------------------------------
    op.create_index(
        "ix_analysis_runs_semantic_revision_id",
        "analysis_runs",
        ["semantic_revision_id"],
    )
    op.create_index(
        "ix_analysis_runs_dataset_id",
        "analysis_runs",
        ["dataset_id"],
    )
    op.create_index(
        "ix_analysis_runs_business_status",
        "analysis_runs",
        ["business_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_business_status", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_dataset_id", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_semantic_revision_id", table_name="analysis_runs")
    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.drop_column("dataset_date_coverage")
        batch_op.drop_column("ingestion_job_id")
        batch_op.drop_column("dataset_content_hash")
        batch_op.drop_column("dataset_id")
        batch_op.drop_column("semantic_version")
        batch_op.drop_column("semantic_revision_id")
