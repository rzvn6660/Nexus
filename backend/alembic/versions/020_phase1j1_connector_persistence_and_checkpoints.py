"""NEXUS Phase 1J.1.1 — Connector Persistence, Checkpoints, and Credential Storage.

Revision ID: 020_phase1j1_connector_persistence_and_checkpoints
Revises: 019_phase1i5_manifest_audit_hardening
Create Date: 2026-10-30

Creates:
1. connector_sync_checkpoints: Durable persistence for background source synchronization,
   storing cursor state, rolling SHA-256 cursor chain hashes, extracted/ingested counts,
   volume sums, and error telemetry.
2. tenant_connector_credentials: Secure storage for encrypted tenant connector credentials
   with envelope encryption metadata, scopes, and key references.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "020_phase1j1_connector_persistence_and_checkpoints"
down_revision: Union[str, None] = "019_phase1i5_manifest_audit_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    # 1. Create connector_sync_checkpoints if not exists
    if "connector_sync_checkpoints" not in existing_tables:
        op.create_table(
            "connector_sync_checkpoints",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("sync_mode", sa.String(length=32), server_default="historical", nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=32), server_default="IN_PROGRESS", nullable=False),
            sa.Column("is_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("current_cursor", sa.Text(), nullable=True),
            sa.Column("cursor_chain_hash", sa.String(length=64), server_default="0" * 64, nullable=False),
            sa.Column("records_extracted", sa.Integer(), server_default="0", nullable=False),
            sa.Column("records_ingested", sa.Integer(), server_default="0", nullable=False),
            sa.Column("records_rejected", sa.Integer(), server_default="0", nullable=False),
            sa.Column("records_duplicate", sa.Integer(), server_default="0", nullable=False),
            sa.Column("gross_amount", sa.Numeric(precision=14, scale=2), server_default="0.00", nullable=False),
            sa.Column("net_amount", sa.Numeric(precision=14, scale=2), server_default="0.00", nullable=False),
            sa.Column("tax_amount", sa.Numeric(precision=14, scale=2), server_default="0.00", nullable=False),
            sa.Column("fee_amount", sa.Numeric(precision=14, scale=2), server_default="0.00", nullable=False),
            sa.Column("transaction_set_digest", sa.String(length=64), nullable=True),
            sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_event_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint(
                "business_id", "provider", "period_start", "period_end",
                name="uq_connector_sync_checkpoint_period"
            ),
        )
        op.create_index("ix_connector_sync_checkpoints_business_id", "connector_sync_checkpoints", ["business_id"])
        op.create_index("ix_connector_sync_checkpoints_provider", "connector_sync_checkpoints", ["provider"])
        op.create_index("ix_connector_sync_checkpoints_status", "connector_sync_checkpoints", ["status"])
        op.create_index("ix_sync_checkpoint_business_status", "connector_sync_checkpoints", ["business_id", "status"])

    # 2. Create tenant_connector_credentials if not exists
    if "tenant_connector_credentials" not in existing_tables:
        op.create_table(
            "tenant_connector_credentials",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("provider_account_id", sa.String(length=255), nullable=False),
            sa.Column("encrypted_credentials", sa.Text(), nullable=False),
            sa.Column("kms_key_id", sa.String(length=255), server_default="local_kms_vault", nullable=False),
            sa.Column("status", sa.String(length=32), server_default="ACTIVE", nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_rotated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("business_id", "provider", name="uq_tenant_connector_credentials_provider"),
        )
        op.create_index("ix_tenant_connector_credentials_business_id", "tenant_connector_credentials", ["business_id"])
        op.create_index("ix_tenant_connector_credentials_provider", "tenant_connector_credentials", ["provider"])
        op.create_index("ix_tenant_connector_status", "tenant_connector_credentials", ["business_id", "status"])


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    if "tenant_connector_credentials" in existing_tables:
        op.drop_table("tenant_connector_credentials")

    if "connector_sync_checkpoints" in existing_tables:
        op.drop_table("connector_sync_checkpoints")
