"""Add created_at and updated_at timestamps to ingestion_jobs (Phase 23).

Revision ID: 009_phase23_ingestion_job_timestamps
Revises: 008_phase19_run_lifecycle_snapshots
Create Date: 2026-10-06 20:55:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_phase23_ingestion_job_timestamps"
down_revision: Union[str, None] = "008_phase19_run_lifecycle_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # Add created_at and updated_at timestamps to ingestion_jobs (Phase 23)
    # -----------------------------------------------------------------------
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = (
        {c["name"] for c in insp.get_columns("ingestion_jobs")}
        if insp.has_table("ingestion_jobs")
        else set()
    )

    with op.batch_alter_table("ingestion_jobs") as batch_op:
        if "created_at" not in existing_cols:
            batch_op.add_column(
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )
        if "updated_at" not in existing_cols:
            batch_op.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = (
        {c["name"] for c in insp.get_columns("ingestion_jobs")}
        if insp.has_table("ingestion_jobs")
        else set()
    )

    with op.batch_alter_table("ingestion_jobs") as batch_op:
        if "updated_at" in existing_cols:
            batch_op.drop_column("updated_at")
        if "created_at" in existing_cols:
            batch_op.drop_column("created_at")
