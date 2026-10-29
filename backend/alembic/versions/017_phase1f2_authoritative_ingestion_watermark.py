"""Tenant-scoped authoritative ingestion watermark contract (Phase 1F.2 / Phase 1G.0).

Creates the tenant_ingestion_watermarks table to track certified complete-through
event horizons per tenant data source, guaranteeing that customer cadence validation
and predictive churn models never mistake ingestion latency for customer inactivity.

Includes:
- Complete audit ledger of all watermark transitions (never deletes historical states).
- Database-level partial unique index ensuring at most one active watermark per (business_id, source_id).
- Composite indexes optimizing multi-source minimum evaluation and event horizon checks.
- Foreign key constraints to businesses and ingestion_jobs with cascade/set null rules.

Revision ID: 017_phase1f2_authoritative_ingestion_watermark
Revises: 016_phase1c2_tenant_scoped_customer_identity
Create Date: 2026-10-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017_phase1f2_authoritative_ingestion_watermark"
down_revision: str | None = "016_phase1c2_tenant_scoped_customer_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    try:
        insp = sa.inspect(bind)
    except Exception:  # noqa: BLE001
        insp = None

    is_sqlite = (
        bind.dialect.name == "sqlite"
        if bind and hasattr(bind, "dialect")
        else False
    )

    if insp is not None:
        if not insp.has_table("businesses"):
            raise RuntimeError(
                "Migration 017 failed: table 'businesses' does not exist. "
                "Ensure core multi-tenant schema (005_phase15_saas_multi_tenancy) has been applied."
            )
        has_wm_table = insp.has_table("tenant_ingestion_watermarks")
        existing_indexes = (
            {idx["name"] for idx in insp.get_indexes("tenant_ingestion_watermarks")}
            if has_wm_table
            else set()
        )
    else:
        has_wm_table = False
        existing_indexes = set()

    if not has_wm_table:
        op.create_table(
            "tenant_ingestion_watermarks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "source_id",
                sa.String(length=64),
                nullable=False,
                server_default="default",
            ),
            sa.Column(
                "complete_through_dt",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "ingestion_job_id",
                sa.String(length=36),
                sa.ForeignKey("ingestion_jobs.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "provenance_type",
                sa.String(length=64),
                nullable=False,
                server_default="manual_close",
            ),
            sa.Column(
                "verification_status",
                sa.String(length=32),
                nullable=False,
                server_default="verified",
            ),
            sa.Column(
                "invalidation_reason",
                sa.String(length=512),
                nullable=True,
            ),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true") if not is_sqlite else sa.text("1"),
            ),
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if "ix_tenant_ingestion_watermarks_business_id" not in existing_indexes:
        op.create_index(
            "ix_tenant_ingestion_watermarks_business_id",
            "tenant_ingestion_watermarks",
            ["business_id"],
            unique=False,
        )

    if "ix_tenant_ingestion_watermarks_source_id" not in existing_indexes:
        op.create_index(
            "ix_tenant_ingestion_watermarks_source_id",
            "tenant_ingestion_watermarks",
            ["source_id"],
            unique=False,
        )

    if "ix_tenant_ingestion_watermarks_ingestion_job_id" not in existing_indexes:
        op.create_index(
            "ix_tenant_ingestion_watermarks_ingestion_job_id",
            "tenant_ingestion_watermarks",
            ["ingestion_job_id"],
            unique=False,
        )

    if "ix_tenant_wm_biz_source_active" not in existing_indexes:
        op.create_index(
            "ix_tenant_wm_biz_source_active",
            "tenant_ingestion_watermarks",
            ["business_id", "source_id", "is_active"],
            unique=False,
        )

    if "ix_tenant_wm_biz_complete_dt" not in existing_indexes:
        op.create_index(
            "ix_tenant_wm_biz_complete_dt",
            "tenant_ingestion_watermarks",
            ["business_id", "complete_through_dt"],
            unique=False,
        )

    # Enforce active watermark exclusivity at database level (at most one active watermark per tenant & source)
    if "uq_tenant_watermarks_active_source" not in existing_indexes:
        op.create_index(
            "uq_tenant_watermarks_active_source",
            "tenant_ingestion_watermarks",
            ["business_id", "source_id"],
            unique=True,
            postgresql_where=sa.text("is_active = true"),
            sqlite_where=sa.text("is_active = 1"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    try:
        insp = sa.inspect(bind)
    except Exception:  # noqa: BLE001
        insp = None

    if insp is not None and not insp.has_table("tenant_ingestion_watermarks"):
        return

    existing_indexes = (
        {idx["name"] for idx in insp.get_indexes("tenant_ingestion_watermarks")}
        if insp is not None
        else set()
    )

    for idx_name in [
        "uq_tenant_watermarks_active_source",
        "ix_tenant_wm_biz_complete_dt",
        "ix_tenant_wm_biz_source_active",
        "ix_tenant_ingestion_watermarks_ingestion_job_id",
        "ix_tenant_ingestion_watermarks_source_id",
        "ix_tenant_ingestion_watermarks_business_id",
    ]:
        if insp is None or idx_name in existing_indexes:
            op.drop_index(idx_name, table_name="tenant_ingestion_watermarks")

    op.drop_table("tenant_ingestion_watermarks")

