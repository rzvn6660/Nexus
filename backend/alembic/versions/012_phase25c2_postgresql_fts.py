"""Add PostgreSQL full-text search tsvector column and GIN index (Phase 25C.2).

Revision ID: 012_phase25c2_postgresql_fts
Revises: 011_phase25c1_embedding_compatibility_and_scope
Create Date: 2026-10-09 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012_phase25c2_postgresql_fts"
down_revision: str | None = "011_phase25c1_embedding_compatibility_and_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("knowledge_chunks"):
        return

    existing_cols = {c["name"] for c in insp.get_columns("knowledge_chunks")}
    existing_indices = {idx["name"] for idx in insp.get_indexes("knowledge_chunks")}

    if bind.dialect.name == "postgresql":
        # 1. Add generated tsvector column for English full-text search
        if "tsv_content" not in existing_cols:
            op.execute(
                """
                ALTER TABLE knowledge_chunks 
                ADD COLUMN tsv_content tsvector 
                GENERATED ALWAYS AS (
                    to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, ''))
                ) STORED;
                """
            )
        # 2. Add GIN index for high-performance lexical lookups
        if "ix_knowledge_chunks_tsv_content" not in existing_indices:
            op.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_tsv_content 
                ON knowledge_chunks USING gin(tsv_content);
                """
            )
    else:
        # SQLite / in-memory test fallback
        if "tsv_content" not in existing_cols:
            with op.batch_alter_table("knowledge_chunks") as batch_op:
                batch_op.add_column(sa.Column("tsv_content", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("knowledge_chunks"):
        return

    existing_cols = {c["name"] for c in insp.get_columns("knowledge_chunks")}
    existing_indices = {idx["name"] for idx in insp.get_indexes("knowledge_chunks")}

    if bind.dialect.name == "postgresql":
        if "ix_knowledge_chunks_tsv_content" in existing_indices:
            op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_tsv_content;")
        if "tsv_content" in existing_cols:
            op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS tsv_content;")
    else:
        if "tsv_content" in existing_cols:
            with op.batch_alter_table("knowledge_chunks") as batch_op:
                batch_op.drop_column("tsv_content")
