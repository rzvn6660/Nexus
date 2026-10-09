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
    retrieval_method: str = (
        "vector_search"  # "exact_kpi_match", "vector_search", "metadata_filtered"
    )
    excerpt: str
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None
    chunk_hash: str | None = None
    document_version: str | None = None
    business_id: str | None = None
    chunk_index: int | None = None
    rerank_score: float | None = None


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
    chunk_hash: str | None = None
    chunk_index: int | None = None
    document_version: str | None = None
    business_id: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None


class RetrievalDiagnostics(BaseModel):
    """Structured retrieval telemetry for candidate generation and rank fusion."""

    dense_candidates_count: int = 0
    lexical_candidates_count: int = 0
    fused_candidates_count: int = 0
    fusion_method: str = "rrf"  # "rrf" | "linear" | "exact_kpi_match" | "none"
    lexical_engine: str = (
        "sqlite_bm25_fallback"  # "postgresql_fts" | "sqlite_bm25_fallback" | "none"
    )
    is_lexical_fallback: bool = False
    fallback_used: bool = False
    database_error: str | None = None
    dense_latency_ms: float = 0.0
    lexical_latency_ms: float = 0.0
    fusion_latency_ms: float = 0.0
    stale_vectors_excluded: int = 0
    rerank_enabled: bool = False
    rerank_provider: str | None = None
    rerank_latency_ms: float = 0.0
    irrelevant_candidates_filtered: int = 0


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
    embedding_provider: str | None = None
    embedding_model: str | None = None
    retrieval_mode: str = "standard"  # "pgvector_native", "sqlite_fallback", "exact_kpi_match"
    stale_vectors_excluded: int = 0
    has_sufficient_context: bool = True
    confidence_score: float = 1.0
    confidence_level: str = "sufficient"  # "sufficient" | "low" | "none"
    execution_time_ms: float = 0.0
    diagnostics: RetrievalDiagnostics = Field(default_factory=RetrievalDiagnostics)
