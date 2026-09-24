"""Data models for RAG context retrieval and provenance evidence."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class RAGEvidence(BaseModel):
    """
    Provenance record proving the business context source.
    Complements Phase 3 Analytics EvidenceRecord without altering numerical calculations.
    """
    document_id: str
    document_name: str
    chunk_id: str
    source: str
    title: str | None = None
    similarity_score: float
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retrieval_method: str = "vector_search"  # "exact_kpi_match", "vector_search", "metadata_filtered"
    excerpt: str


class RetrievedChunk(BaseModel):
    """Individual retrieved text passage with relevance metrics."""
    chunk_id: str
    document_id: str
    document_title: str
    source: str
    title: str | None = None
    content: str
    similarity: float
    business_domain: str
    retrieval_method: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RetrievedContext(BaseModel):
    """Aggregated context bundle provided to planning and explanation layers."""
    query: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    evidence: list[RAGEvidence] = Field(default_factory=list)
    resolved_kpi_canonical: str | None = None
    retrieval_method: str = "none"
    has_conflict: bool = False
    conflict_description: str | None = None
    context_text: str = ""
