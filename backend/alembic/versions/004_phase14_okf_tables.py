"""Create okf_bundles and okf_items tables for Phase 14 OKF architecture.

Revision ID: 004_phase14_okf_tables
Revises: 003_phase11_history_and_decisions
Create Date: 2026-09-26 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "004_phase14_okf_tables"
down_revision: Union[str, None] = "003_phase11_history_and_decisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. OKF Bundles Table
    op.create_table(
        "okf_bundles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bundle_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="verified"),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bundle_id"),
    )
    op.create_index("ix_okf_bundles_bundle_id", "okf_bundles", ["bundle_id"])
    op.create_index("ix_okf_bundles_status", "okf_bundles", ["status"])

    # 2. OKF Items Table
    op.create_table(
        "okf_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bundle_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="verified"),
        sa.Column("domain", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=True),
        sa.Column("verified_by", sa.String(length=128), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("formula", sa.String(length=512), nullable=True),
        sa.Column("synonyms", sa.JSON(), nullable=True),
        sa.Column("canonical_intent", sa.String(length=64), nullable=True),
        sa.Column("analytics_tool", sa.String(length=64), nullable=True),
        sa.Column("metric_field", sa.String(length=64), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("target_direction", sa.String(length=32), nullable=True),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=128), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True, server_default="100"),
        sa.Column("related_ids", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["okf_bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bundle_id", "item_id", name="uq_okf_bundle_item"),
    )
    op.create_index("ix_okf_items_bundle_item", "okf_items", ["bundle_id", "item_id"])
    op.create_index("ix_okf_items_item_id", "okf_items", ["item_id"])
    op.create_index("ix_okf_items_item_type", "okf_items", ["item_type"])
    op.create_index("ix_okf_items_domain_type", "okf_items", ["domain", "item_type"])
    op.create_index("ix_okf_items_status", "okf_items", ["status"])


def downgrade() -> None:
    op.drop_table("okf_items")
    op.drop_table("okf_bundles")
