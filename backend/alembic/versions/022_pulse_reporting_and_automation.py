"""NEXUS Pulse: Management Intelligence & Automated Reporting Migration.

Revision ID: 022_pulse_reporting_and_automation
Revises: 021_phase1j2_webhook_inbox
Create Date: 2026-11-02

Creates:
1. pulse_report_schedules: Durable manager-configured reporting automation schedules.
2. pulse_generated_reports: Immutable executive business intelligence reports with KPI snapshots.
3. pulse_delivery_logs: Multi-channel dispatch audit trail (WhatsApp, Telegram, Email).
4. pulse_recipient_preferences: Authorized recipients with opt-in/opt-out status.
"""

from typing import Sequence, Union

from alembic import op, context
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "022_pulse_reporting_and_automation"
down_revision: Union[str, None] = "021_phase1j2_webhook_inbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        existing_tables = set()
    else:
        conn = op.get_bind()
        insp = sa.inspect(conn)
        existing_tables = set(insp.get_table_names())

    # 1. pulse_report_schedules
    if "pulse_report_schedules" not in existing_tables:
        op.create_table(
            "pulse_report_schedules",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "organization_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("schedule_name", sa.String(length=255), nullable=False),
            sa.Column("report_type", sa.String(length=64), nullable=False, server_default="MONTHLY_EXECUTIVE"),
            sa.Column("frequency", sa.String(length=32), nullable=False, server_default="MONTHLY"),
            sa.Column("day_of_month", sa.Integer(), nullable=True),
            sa.Column("day_of_week", sa.Integer(), nullable=True),
            sa.Column("time_of_day", sa.String(length=8), nullable=False, server_default="09:00"),
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
            sa.Column("channel_types", sa.JSON(), nullable=False),
            sa.Column("recipients_json", sa.JSON(), nullable=False),
            sa.Column("kpi_categories", sa.JSON(), nullable=False),
            sa.Column("alert_triggers", sa.JSON(), nullable=False),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True, index=True),
            sa.Column("created_by", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(
            "ix_pulse_schedules_biz_active",
            "pulse_report_schedules",
            ["business_id", "is_enabled"],
        )

    # 2. pulse_generated_reports
    if "pulse_generated_reports" not in existing_tables:
        op.create_table(
            "pulse_generated_reports",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "organization_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "schedule_id",
                sa.Integer(),
                sa.ForeignKey("pulse_report_schedules.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("report_title", sa.String(length=255), nullable=False),
            sa.Column("report_type", sa.String(length=64), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("comparison_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("comparison_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("kpi_payload", sa.JSON(), nullable=False),
            sa.Column("insights_json", sa.JSON(), nullable=False),
            sa.Column("executive_summary", sa.Text(), nullable=False),
            sa.Column("messaging_summary", sa.Text(), nullable=False),
            sa.Column("pdf_storage_key", sa.String(length=512), nullable=True),
            sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
            sa.Column("pdf_file_bytes", sa.LargeBinary(), nullable=True),
            sa.Column("watermark_status", sa.String(length=64), nullable=False, server_default="verified_complete"),
            sa.Column("data_provenance_json", sa.JSON(), nullable=False),
            sa.Column("access_token", sa.String(length=64), unique=True, index=True, nullable=False),
            sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(
            "ix_pulse_reports_biz_created",
            "pulse_generated_reports",
            ["business_id", "created_at"],
        )

    # 3. pulse_delivery_logs
    if "pulse_delivery_logs" not in existing_tables:
        op.create_table(
            "pulse_delivery_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "report_id",
                sa.String(length=36),
                sa.ForeignKey("pulse_generated_reports.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("business_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("organization_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("channel", sa.String(length=32), nullable=False, index=True),
            sa.Column("recipient_destination", sa.String(length=255), nullable=False),
            sa.Column("recipient_name", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING", index=True),
            sa.Column("external_message_id", sa.String(length=128), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(
            "ix_pulse_deliveries_biz_status",
            "pulse_delivery_logs",
            ["business_id", "status"],
        )

    # 4. pulse_recipient_preferences
    if "pulse_recipient_preferences" not in existing_tables:
        op.create_table(
            "pulse_recipient_preferences",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "organization_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("recipient_name", sa.String(length=128), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("destination", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=64), nullable=False, server_default="Executive"),
            sa.Column("opt_status", sa.String(length=32), nullable=False, server_default="OPTED_IN", index=True),
            sa.Column("opted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("opt_out_reason", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(
            "uq_pulse_recipient_biz_channel_dest",
            "pulse_recipient_preferences",
            ["business_id", "channel", "destination"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_table("pulse_recipient_preferences")
    op.drop_table("pulse_delivery_logs")
    op.drop_table("pulse_generated_reports")
    op.drop_table("pulse_report_schedules")
