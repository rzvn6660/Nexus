"""Create tenant_semantic_models table and add semantic_status to businesses (Phase 17).

Revision ID: 007_phase17_business_understanding_semantic
Revises: 006_phase16_data_gateway_ingestion
Create Date: 2026-09-27 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "007_phase17_business_understanding_semantic"
down_revision: Union[str, None] = "006_phase16_data_gateway_ingestion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add semantic_status column to businesses table
    op.add_column(
        "businesses",
        sa.Column("semantic_status", sa.String(length=32), nullable=False, server_default="NOT_ACTIVATED"),
    )

    # 2. Create tenant_semantic_models table for persistent tenant-specific business understanding
    op.create_table(
        "tenant_semantic_models",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("source_dataset_id", sa.String(length=36), nullable=True),
        sa.Column("entities_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("dimensions_json", sa.JSON(), nullable=False),
        sa.Column("synonyms_json", sa.JSON(), nullable=False),
        sa.Column("ambiguous_terms_json", sa.JSON(), nullable=False),
        sa.Column("business_summary_json", sa.JSON(), nullable=False),
        sa.Column("conflicts_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_dataset_id"], ["uploaded_datasets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "version", name="uq_business_semantic_version"),
    )
    op.create_index("ix_tenant_semantic_models_organization_id", "tenant_semantic_models", ["organization_id"])
    op.create_index("ix_tenant_semantic_models_business_id", "tenant_semantic_models", ["business_id"])
    op.create_index("ix_tenant_semantic_models_source_dataset_id", "tenant_semantic_models", ["source_dataset_id"])
    op.create_index("ix_tenant_semantic_models_status", "tenant_semantic_models", ["status"])
    op.create_index("ix_tenant_semantic_business_status", "tenant_semantic_models", ["business_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_tenant_semantic_business_status", table_name="tenant_semantic_models")
    op.drop_index("ix_tenant_semantic_models_status", table_name="tenant_semantic_models")
    op.drop_index("ix_tenant_semantic_models_source_dataset_id", table_name="tenant_semantic_models")
    op.drop_index("ix_tenant_semantic_models_business_id", table_name="tenant_semantic_models")
    op.drop_index("ix_tenant_semantic_models_organization_id", table_name="tenant_semantic_models")
    op.drop_table("tenant_semantic_models")
    with op.batch_alter_table("businesses") as batch_op:
        batch_op.drop_column("semantic_status")
