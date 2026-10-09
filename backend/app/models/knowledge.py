"""SQLAlchemy ORM models for Business Context Knowledge Documents and Chunks."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import FetchedValue
from sqlalchemy.types import TypeDecorator

from app.core.config import settings
from app.models.base import Base, TimestampMixin


class TSVectorType(TypeDecorator):
    """PostgreSQL TSVECTOR type with safe fallback to Text for SQLite/tests."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import TSVECTOR

            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(Text())


class KnowledgeDocument(Base, TimestampMixin):
    """
    Business-context document metadata registry.
    Stores governance, versioning, source provenance, domain categorization,
    and tenant business ownership.
    """

    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)  # markdown, txt, pdf
    business_domain: Mapped[str] = mapped_column(
        String(50), nullable=False, default="general", index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="KnowledgeChunk.chunk_index",
    )


class KnowledgeChunk(Base):
    """
    Granular text chunk with vector embeddings and business domain tags.
    Preserves strict provenance mapping back to parent KnowledgeDocument.
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIMENSION), nullable=True
    )
    business_domain: Mapped[str] = mapped_column(
        String(50), nullable=False, default="general", index=True
    )
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    business_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    chunk_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tsv_content: Mapped[Any | None] = mapped_column(
        TSVectorType, server_default=FetchedValue(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    document: Mapped["KnowledgeDocument"] = relationship(
        "KnowledgeDocument", back_populates="chunks"
    )

    __table_args__ = (
        Index("ix_knowledge_chunks_doc_idx", "document_id", "chunk_index"),
        Index("ix_knowledge_chunks_tenant_model", "business_id", "embedding_model"),
    )
