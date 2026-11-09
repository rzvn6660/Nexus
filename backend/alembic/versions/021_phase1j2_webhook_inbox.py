"""NEXUS Phase 1J.2.2 — Durable Provider-Neutral Webhook Event Inbox.

Revision ID: 021_phase1j2_webhook_inbox
Revises: 020_phase1j1_connector_persistence_and_checkpoints
Create Date: 2026-10-31

Creates:
1. connector_webhook_inbox: Durable, multi-worker safe webhook event inbox with
   unique (provider, provider_account_id, event_id) constraint, atomic claiming,
   retry tracking, payload SHA-256 digest, and auditability.
   Shared across Stripe, Shopify, and all future upstream connectors.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "021_phase1j2_webhook_inbox"
down_revision: Union[str, None] = "020_phase1j1_connector_persistence_and_checkpoints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    if "connector_webhook_inbox" not in existing_tables:
        op.create_table(
            "connector_webhook_inbox",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("provider_account_id", sa.String(length=255), nullable=False),
            sa.Column("event_id", sa.String(length=255), nullable=False),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("event_created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "signature_verified",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                server_default="PENDING",
                nullable=False,
            ),
            sa.Column(
                "retry_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            ),
            sa.Column("payload_digest", sa.String(length=64), nullable=False),
            sa.Column("claimed_by", sa.String(length=128), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "provider", "provider_account_id", "event_id",
                name="uq_connector_webhook_inbox_event"
            ),
        )

        op.create_index(
            "ix_connector_webhook_inbox_business_id",
            "connector_webhook_inbox",
            ["business_id"],
        )
        op.create_index(
            "ix_connector_webhook_inbox_provider",
            "connector_webhook_inbox",
            ["provider"],
        )
        op.create_index(
            "ix_connector_webhook_inbox_status",
            "connector_webhook_inbox",
            ["status"],
        )
        op.create_index(
            "ix_connector_webhook_inbox_event_type",
            "connector_webhook_inbox",
            ["event_type"],
        )
        op.create_index(
            "ix_connector_webhook_status",
            "connector_webhook_inbox",
            ["business_id", "provider", "status"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    if "connector_webhook_inbox" in existing_tables:
        op.drop_index("ix_connector_webhook_status", table_name="connector_webhook_inbox")
        op.drop_index("ix_connector_webhook_inbox_event_type", table_name="connector_webhook_inbox")
        op.drop_index("ix_connector_webhook_inbox_status", table_name="connector_webhook_inbox")
        op.drop_index("ix_connector_webhook_inbox_provider", table_name="connector_webhook_inbox")
        op.drop_index("ix_connector_webhook_inbox_business_id", table_name="connector_webhook_inbox")
        op.drop_table("connector_webhook_inbox")
