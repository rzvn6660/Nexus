"""Add metadata columns, lineage, and HNSW index to knowledge_chunks (Phase 25B).

Revision ID: 010_phase25b_knowledge_chunk_metadata_and_hnsw
Revises: 009_phase23_ingestion_job_timestamps
Create Date: 2026-10-09 01:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_phase25b_knowledge_chunk_metadata_and_hnsw"
down_revision: Union[str, None] = "009_phase23_ingestion_job_timestamps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = (
        {c["name"] for c in insp.get_columns("knowledge_chunks")}
        if insp.has_table("knowledge_chunks")
        else set()
    )

    with op.batch_alter_table("knowledge_chunks") as batch_op:
        if "business_id" not in existing_cols:
            batch_op.add_column(sa.Column("business_id", sa.String(length=36), nullable=True))
        if "chunk_hash" not in existing_cols:
            batch_op.add_column(sa.Column("chunk_hash", sa.String(length=64), nullable=True))
        if "embedding_provider" not in existing_cols:
            batch_op.add_column(sa.Column("embedding_provider", sa.String(length=32), nullable=True))
        if "embedding_model" not in existing_cols:
            batch_op.add_column(sa.Column("embedding_model", sa.String(length=64), nullable=True))
        if "embedding_dimension" not in existing_cols:
            batch_op.add_column(sa.Column("embedding_dimension", sa.Integer(), nullable=True))
        if "embedding_version" not in existing_cols:
            batch_op.add_column(sa.Column("embedding_version", sa.String(length=16), nullable=True))
        if "updated_at" not in existing_cols:
            batch_op.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                    server_default=sa.func.now(),
                )
            )

    # Create indexes if they do not exist
    existing_indices = (
        {idx["name"] for idx in insp.get_indexes("knowledge_chunks")}
        if insp.has_table("knowledge_chunks")
        else set()
    )

    if "ix_knowledge_chunks_business_id" not in existing_indices:
        op.create_index(
            "ix_knowledge_chunks_business_id",
            "knowledge_chunks",
            ["business_id"],
        )
    if "ix_knowledge_chunks_chunk_hash" not in existing_indices:
        op.create_index(
            "ix_knowledge_chunks_chunk_hash",
            "knowledge_chunks",
            ["chunk_hash"],
        )

    # Backfill business_id from owning knowledge_documents
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
                WHERE business_id IS NULL
                """
            )
        )

    # Create PostgreSQL HNSW index if on PostgreSQL
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hnsw 
            ON knowledge_chunks 
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw;")

    insp = sa.inspect(bind)
    existing_indices = (
        {idx["name"] for idx in insp.get_indexes("knowledge_chunks")}
        if insp.has_table("knowledge_chunks")
        else set()
    )

    if "ix_knowledge_chunks_chunk_hash" in existing_indices:
        op.drop_index("ix_knowledge_chunks_chunk_hash", table_name="knowledge_chunks")
    if "ix_knowledge_chunks_business_id" in existing_indices:
        op.drop_index("ix_knowledge_chunks_business_id", table_name="knowledge_chunks")

    with op.batch_alter_table("knowledge_chunks") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("embedding_version")
        batch_op.drop_column("embedding_dimension")
        batch_op.drop_column("embedding_model")
        batch_op.drop_column("embedding_provider")
        batch_op.drop_column("chunk_hash")
        batch_op.drop_column("business_id")
