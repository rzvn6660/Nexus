"""Pydantic schemas for the Knowledge Base and RAG API endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.rag.retrieval.models import RAGEvidence, RetrievedChunk


class DocumentTextIngestRequest(BaseModel):
    """Payload for directly ingesting raw markdown or plain text business documents."""
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    document_type: str = Field(default="markdown", description="'markdown' or 'txt'")
    business_domain: str = Field(default="general", max_length=50)
    version: str = Field(default="1.0", max_length=20)
    source: str | None = Field(default="direct_api", max_length=255)
    tags: list[str] = Field(default_factory=list)


class DocumentUploadResponse(BaseModel):
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


class ChunkResponse(BaseModel):
    """Chunk details for inspectability."""
    chunk_id: str
    chunk_index: int
    title: str | None = None
    content: str
    business_domain: str
    tags: list[str] | None = None


class DocumentSummaryResponse(BaseModel):
    """Summary representation of a registered knowledge document."""
    document_id: str
    title: str
    source: str
    document_type: str
    business_domain: str
    version: str
    status: str
    chunks_count: int
    created_at: datetime


class DocumentDetailResponse(BaseModel):
    """Detailed view of a knowledge document including child semantic chunks."""
    document_id: str
    title: str
    source: str
    document_type: str
    business_domain: str
    version: str
    status: str
    created_at: datetime
    chunks: list[ChunkResponse] = Field(default_factory=list)


class KnowledgeSearchRequest(BaseModel):
    """Payload for executing hybrid semantic search over business documents."""
    query: str = Field(..., min_length=1, max_length=1000)
    business_domain: str | None = None
    top_k: int = Field(default=3, ge=1, le=20)
    similarity_threshold: float = Field(default=0.3, ge=0.0, le=1.0)


class KnowledgeSearchResponse(BaseModel):
    """Grounded hybrid search response with provenance records."""
    query: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    evidence: list[RAGEvidence] = Field(default_factory=list)
    resolved_kpi_canonical: str | None = None
    retrieval_method: str = "none"
    has_conflict: bool = False
    conflict_description: str | None = None
    context_text: str = ""
