"""Create multi-tenant SaaS tables and ownership columns (Phase 15).

Revision ID: 005_phase15_saas_multi_tenancy
Revises: 004_phase14_okf_tables
Create Date: 2026-09-26 23:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "005_phase15_saas_multi_tenancy"
down_revision: Union[str, None] = "004_phase14_okf_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Users Table
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # 2. Organizations Table
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])
    op.create_index("ix_organizations_status", "organizations", ["status"])

    # 3. Organization Memberships Table
    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_user_membership"),
    )
    op.create_index("ix_membership_user_org", "organization_memberships", ["user_id", "organization_id"])

    # 4. Businesses Table
    op.create_table(
        "businesses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("industry", sa.String(length=64), nullable=False, server_default="Retail & Distribution"),
        sa.Column("country", sa.String(length=32), nullable=False, server_default="US"),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="USD"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("business_type", sa.String(length=32), nullable=False, server_default="B2C"),
        sa.Column("fiscal_year_start", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("onboarding_step", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("data_readiness_status", sa.String(length=32), nullable=False, server_default="not_ready"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_businesses_organization_id", "businesses", ["organization_id"])
    op.create_index("ix_businesses_status", "businesses", ["status"])

    # 5. Uploaded Datasets Table
    op.create_table(
        "uploaded_datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("business_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_json", sa.JSON(), nullable=True),
        sa.Column("quality_report_json", sa.JSON(), nullable=True),
        sa.Column("readiness_status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uploaded_datasets_business_id", "uploaded_datasets", ["business_id"])
    op.create_index("ix_uploaded_datasets_organization_id", "uploaded_datasets", ["organization_id"])

    # 6. Add tenant ownership columns to existing domain and knowledge tables
    op.add_column("customers", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.create_index("ix_customers_business_id", "customers", ["business_id"])

    op.add_column("products", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.create_index("ix_products_business_id", "products", ["business_id"])

    op.add_column("sales", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.create_index("ix_sales_business_id", "sales", ["business_id"])

    op.add_column("expenses", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.create_index("ix_expenses_business_id", "expenses", ["business_id"])

    op.add_column("inventory", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.create_index("ix_inventory_business_id", "inventory", ["business_id"])

    op.add_column("analysis_runs", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.add_column("analysis_runs", sa.Column("organization_id", sa.String(length=36), nullable=True))
    op.create_index("ix_analysis_runs_business_id", "analysis_runs", ["business_id"])
    op.create_index("ix_analysis_runs_organization_id", "analysis_runs", ["organization_id"])

    op.add_column("decision_records", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.add_column("decision_records", sa.Column("organization_id", sa.String(length=36), nullable=True))
    op.create_index("ix_decision_records_business_id", "decision_records", ["business_id"])
    op.create_index("ix_decision_records_organization_id", "decision_records", ["organization_id"])

    op.add_column("knowledge_documents", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.add_column("knowledge_documents", sa.Column("is_global", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_knowledge_documents_business_id", "knowledge_documents", ["business_id"])
    op.create_index("ix_knowledge_documents_is_global", "knowledge_documents", ["is_global"])

    op.add_column("okf_bundles", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.create_index("ix_okf_bundles_business_id", "okf_bundles", ["business_id"])

    op.add_column("okf_items", sa.Column("business_id", sa.String(length=36), nullable=True))
    op.create_index("ix_okf_items_business_id", "okf_items", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_okf_items_business_id", table_name="okf_items")
    op.drop_column("okf_items", "business_id")
    op.drop_index("ix_okf_bundles_business_id", table_name="okf_bundles")
    op.drop_column("okf_bundles", "business_id")
    op.drop_index("ix_knowledge_documents_is_global", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_business_id", table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "is_global")
    op.drop_column("knowledge_documents", "business_id")
    op.drop_index("ix_decision_records_organization_id", table_name="decision_records")
    op.drop_index("ix_decision_records_business_id", table_name="decision_records")
    op.drop_column("decision_records", "organization_id")
    op.drop_column("decision_records", "business_id")
    op.drop_index("ix_analysis_runs_organization_id", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_business_id", table_name="analysis_runs")
    op.drop_column("analysis_runs", "organization_id")
    op.drop_column("analysis_runs", "business_id")
    op.drop_index("ix_inventory_business_id", table_name="inventory")
    op.drop_column("inventory", "business_id")
    op.drop_index("ix_expenses_business_id", table_name="expenses")
    op.drop_column("expenses", "business_id")
    op.drop_index("ix_sales_business_id", table_name="sales")
    op.drop_column("sales", "business_id")
    op.drop_index("ix_products_business_id", table_name="products")
    op.drop_column("products", "business_id")
    op.drop_index("ix_customers_business_id", table_name="customers")
    op.drop_column("customers", "business_id")
    op.drop_table("uploaded_datasets")
    op.drop_table("businesses")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    op.drop_table("users")
