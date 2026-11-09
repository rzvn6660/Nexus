"""Persistent tenant-scoped trusted keys and manifest submission history (Phase 1I.4).

Remediates Phase 1I.3 findings:
- C2: Persistent tenant_trusted_keys table replacing process-local in-memory registry.
- M2: Persistent manifest_submissions table providing an immutable audit ledger of period-close attempts.

Revision ID: 018_phase1i4_trusted_keys_and_manifest_history
Revises: 017_phase1f2_authoritative_ingestion_watermark
Create Date: 2026-10-30 00:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018_phase1i4_trusted_keys_and_manifest_history"
down_revision: str | None = "017_phase1f2_authoritative_ingestion_watermark"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    try:
        insp = sa.inspect(bind)
    except Exception:  # noqa: BLE001
        insp = None

    if insp is not None:
        if not insp.has_table("businesses"):
            raise RuntimeError(
                "Migration 018 failed: table 'businesses' does not exist."
            )
        has_keys_table = insp.has_table("tenant_trusted_keys")
        has_manifest_table = insp.has_table("manifest_submissions")
    else:
        has_keys_table = False
        has_manifest_table = False

    # 1. Create tenant_trusted_keys
    if not has_keys_table:
        op.create_table(
            "tenant_trusted_keys",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("key_id", sa.String(length=64), nullable=False),
            sa.Column("algorithm", sa.String(length=32), nullable=False),
            sa.Column("public_key_pem", sa.Text(), nullable=False),
            sa.Column("key_reference", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
            sa.Column("allowed_roles", sa.JSON(), nullable=False),
            sa.Column(
                "valid_from",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_reason", sa.Text(), nullable=True),
            sa.Column(
                "created_by_user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
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
                "business_id", "key_id", name="uq_tenant_trusted_keys_business_key"
            ),
        )
        op.create_index(
            "ix_tenant_trusted_keys_business_id", "tenant_trusted_keys", ["business_id"]
        )
        op.create_index(
            "ix_tenant_trusted_keys_key_id", "tenant_trusted_keys", ["key_id"]
        )
        op.create_index(
            "ix_tenant_trusted_keys_status", "tenant_trusted_keys", ["business_id", "status"]
        )

    # 2. Create manifest_submissions
    if not has_manifest_table:
        op.create_table(
            "manifest_submissions",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("manifest_id", sa.String(length=64), nullable=False),
            sa.Column(
                "business_id",
                sa.String(length=36),
                sa.ForeignKey("businesses.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source_id", sa.String(length=64), nullable=False),
            sa.Column("batch_id", sa.String(length=64), nullable=False),
            sa.Column("provenance_type", sa.String(length=64), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_export_id", sa.String(length=64), nullable=True),
            sa.Column("export_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("file_sha256", sa.String(length=64), nullable=False),
            sa.Column("expected_row_count", sa.Integer(), nullable=False),
            sa.Column("expected_gross_total", sa.Numeric(precision=14, scale=2), nullable=False),
            sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
            sa.Column(
                "attested_by_user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("attester_role", sa.String(length=64), nullable=False),
            sa.Column("attestation_statement", sa.Text(), nullable=False),
            sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "submitted_by_user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("signature_algorithm", sa.String(length=32), nullable=False),
            sa.Column("signature_key_id", sa.String(length=64), nullable=False),
            sa.Column("verification_status", sa.String(length=32), nullable=False),
            sa.Column("reconciliation_matched", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("reconciliation_breakdown_json", sa.JSON(), nullable=True),
            sa.Column("source_close_evidence_json", sa.JSON(), nullable=True),
            sa.Column("db_reconciled", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("db_reconciled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("db_persisted_row_count", sa.Integer(), nullable=True),
            sa.Column("db_persisted_gross_total", sa.Numeric(precision=14, scale=2), nullable=True),
            sa.Column(
                "watermark_id",
                sa.String(length=36),
                sa.ForeignKey("tenant_ingestion_watermarks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("error_details_json", sa.JSON(), nullable=True),
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
                "manifest_id", name="uq_manifest_submissions_manifest_id"
            ),
        )
        op.create_index(
            "ix_manifest_submissions_manifest_id", "manifest_submissions", ["manifest_id"]
        )
        op.create_index(
            "ix_manifest_submissions_business_id", "manifest_submissions", ["business_id"]
        )
        op.create_index(
            "ix_manifest_submissions_source_id", "manifest_submissions", ["source_id"]
        )
        op.create_index(
            "ix_manifest_submissions_batch_id", "manifest_submissions", ["batch_id"]
        )
        op.create_index(
            "ix_manifest_submissions_file_sha256", "manifest_submissions", ["file_sha256"]
        )
        op.create_index(
            "ix_manifest_submissions_biz_batch", "manifest_submissions", ["business_id", "batch_id"]
        )
        op.create_index(
            "ix_manifest_submissions_biz_period", "manifest_submissions", ["business_id", "period_end"]
        )


def downgrade() -> None:
    op.drop_table("manifest_submissions")
    op.drop_table("tenant_trusted_keys")
