"""Add embedding metadata indexes and backfill business_id (Phase 25C.1).

Revision ID: 011_phase25c1_embedding_compatibility_and_scope
Revises: 010_phase25b_knowledge_chunk_metadata_and_hnsw
Create Date: 2026-10-09 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_phase25c1_embedding_compatibility_and_scope"
down_revision: str | None = "010_phase25b_knowledge_chunk_metadata_and_hnsw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("knowledge_chunks"):
        existing_indices = {idx["name"] for idx in insp.get_indexes("knowledge_chunks")}

        if "ix_knowledge_chunks_embedding_model" not in existing_indices:
            op.create_index(
                "ix_knowledge_chunks_embedding_model",
                "knowledge_chunks",
                ["embedding_model"],
            )
        if "ix_knowledge_chunks_embedding_provider" not in existing_indices:
            op.create_index(
                "ix_knowledge_chunks_embedding_provider",
                "knowledge_chunks",
                ["embedding_provider"],
            )
        if "ix_knowledge_chunks_tenant_model" not in existing_indices:
            op.create_index(
                "ix_knowledge_chunks_tenant_model",
                "knowledge_chunks",
                ["business_id", "embedding_model"],
            )

    # Backfill business_id from owning knowledge_documents if null
    if insp.has_table("knowledge_chunks") and insp.has_table("knowledge_documents"):
        op.execute(
            sa.text(
                """
                UPDATE knowledge_chunks
                SET business_id = (
                    SELECT knowledge_documents.business_id 
                    FROM knowledge_documents 
                    WHERE knowledge_documents.id = knowledge_chunks.document_id
                )
                WHERE business_id IS NULL AND EXISTS (
                    SELECT 1 FROM knowledge_documents WHERE knowledge_documents.id = knowledge_chunks.document_id
                )
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("knowledge_chunks"):
        existing_indices = {idx["name"] for idx in insp.get_indexes("knowledge_chunks")}

        if "ix_knowledge_chunks_tenant_model" in existing_indices:
            op.drop_index("ix_knowledge_chunks_tenant_model", table_name="knowledge_chunks")
        if "ix_knowledge_chunks_embedding_provider" in existing_indices:
            op.drop_index("ix_knowledge_chunks_embedding_provider", table_name="knowledge_chunks")
        if "ix_knowledge_chunks_embedding_model" in existing_indices:
            op.drop_index("ix_knowledge_chunks_embedding_model", table_name="knowledge_chunks")
