"""NEXUS Phase 1I.5 — Manifest Audit Hardening and Lifecycle Security.

Revision ID: 019_phase1i5_manifest_audit_hardening
Revises: 018_phase1i4_trusted_keys_and_manifest_history
Create Date: 2026-10-30

Hardens manifest submission audit ledger:
1. Drops the foreign key constraint on manifest_submissions.attested_by_user_id
   to ensure that ALL submissions—including adversarial attempts claiming non-existent,
   forged, or malicious attester IDs—are durably preserved in the audit ledger without
   triggering a foreign key constraint violation.
2. Widens attested_by_user_id to VARCHAR(64) to support standard UUIDs, external subject
   identifiers, and untrusted claim strings up to 64 chars.
3. Preserves submitted_by_user_id FK constraint to users(id), guaranteeing the actual
   authenticated submitter is immutably recorded.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "019_phase1i5_manifest_audit_hardening"
down_revision: Union[str, None] = "018_phase1i4_trusted_keys_and_manifest_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # 1. Drop foreign key constraint on attested_by_user_id if present
    fkeys = insp.get_foreign_keys("manifest_submissions")
    fkey_name = None
    for fk in fkeys:
        if fk.get("constrained_columns") == ["attested_by_user_id"]:
            fkey_name = fk.get("name")
            break

    if fkey_name:
        op.drop_constraint(fkey_name, "manifest_submissions", type_="foreignkey")
    elif conn.dialect.name == "postgresql":
        # Check standard postgres naming if reflection didn't catch it
        op.execute(sa.text("""
            ALTER TABLE manifest_submissions
            DROP CONSTRAINT IF EXISTS manifest_submissions_attested_by_user_id_fkey;
        """))

    # 2. Widen column to VARCHAR(64)
    if conn.dialect.name == "postgresql":
        op.alter_column(
            "manifest_submissions",
            "attested_by_user_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Narrow column back to VARCHAR(36)
    if conn.dialect.name == "postgresql":
        op.alter_column(
            "manifest_submissions",
            "attested_by_user_id",
            existing_type=sa.String(length=64),
            type_=sa.String(length=36),
            existing_nullable=False,
        )
        # 2. Re-add FK constraint
        op.create_foreign_key(
            "manifest_submissions_attested_by_user_id_fkey",
            "manifest_submissions",
            "users",
            ["attested_by_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )
