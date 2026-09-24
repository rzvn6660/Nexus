"""Pydantic schemas and data classes for Document Ingestion in NEXUS."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Metadata attributes for business documents."""
    title: str = Field(..., max_length=255)
    business_domain: str = Field(default="general", max_length=50)
    version: str = Field(default="1.0", max_length=20)
    source: str | None = Field(default="direct_upload", max_length=255)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkData(BaseModel):
    """Normalized text chunk with provenance coordinates."""
    chunk_id: str
    chunk_index: int
    title: str | None = None
    content: str
    business_domain: str = "general"
    tags: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    """Structured report returned upon document ingestion."""
    document_id: str
    title: str
    chunks_created: int
    content_hash: str
    business_domain: str
    version: str
    status: str
    is_duplicate: bool = False
    message: str = "Document ingested successfully"
