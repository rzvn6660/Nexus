"""Create ingestion_jobs table and add content_hash to uploaded_datasets (Phase 16).

Revision ID: 006_phase16_data_gateway_ingestion
Revises: 005_phase15_saas_multi_tenancy
Create Date: 2026-09-27 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "006_phase16_data_gateway_ingestion"
down_revision: Union[str, None] = "005_phase15_saas_multi_tenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add content_hash column and index to uploaded_datasets
    op.add_column(
        "uploaded_datasets",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_uploaded_datasets_content_hash",
        "uploaded_datasets",
        ["content_hash"],
    )

    # 2. Create ingestion_jobs table for persistent lifecycle tracking
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("target_entity", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["uploaded_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_jobs_organization_id", "ingestion_jobs", ["organization_id"])
    op.create_index("ix_ingestion_jobs_business_id", "ingestion_jobs", ["business_id"])
    op.create_index("ix_ingestion_jobs_dataset_id", "ingestion_jobs", ["dataset_id"])
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_status", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_dataset_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_business_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_organization_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_uploaded_datasets_content_hash", table_name="uploaded_datasets")
    op.drop_column("uploaded_datasets", "content_hash")
