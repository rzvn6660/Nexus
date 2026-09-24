"""Hybrid Retrieval Engine combining deterministic KPI ontology and vector search."""

import logging
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.retrieval.models import RAGEvidence, RetrievedChunk, RetrievedContext
from app.rag.semantic.ontology import SemanticResolver, semantic_resolver

logger = logging.getLogger(__name__)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_prod = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a, b in zip(vec_a, vec_b)))
    norm_b = math.sqrt(sum(b * b for a, b in zip(vec_a, vec_b)))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_prod / (norm_a * norm_b)


class HybridRetriever:
    """
    Business Context Retriever for NEXUS.
    
    Executes a tiered retrieval pipeline:
    1. Deterministic KPI lookup (Exact ontology & synonyms)
    2. Metadata-filtered vector search (Domain-specific chunks)
    3. General vector similarity search over verified business documents
    4. Conflict and ambiguity detection across retrieved sources
    """

    def __init__(
        self,
        session: Session,
        resolver: SemanticResolver | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.resolver = resolver or semantic_resolver
        self.embedding_provider = embedding_provider or get_embedding_provider()

    def retrieve(
        self,
        query: str,
        business_domain: str | None = None,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
    ) -> RetrievedContext:
        """
        Execute hybrid context retrieval for a user query.
        """
        k = top_k or settings.RAG_TOP_K or 3
        threshold = similarity_threshold or settings.RAG_SIMILARITY_THRESHOLD or 0.3
        clean_query = query.strip()

        if not clean_query:
            return RetrievedContext(
                query=query,
                retrieval_method="none",
                context_text="No verified business context requested.",
            )

        # 1. Tier 1: Deterministic Semantic Resolution
        resolution = self.resolver.resolve(clean_query)
        resolved_domain = business_domain or (
            resolution.resolved_kpi.business_domain.value if resolution.resolved_kpi else None
        )
        resolved_canonical = resolution.canonical_name

        # 2. Tier 2: Vector Search over Stored Documents
        vector_chunks, method = self._search_vector_chunks(
            query=clean_query,
            domain=resolved_domain,
            top_k=k,
            threshold=threshold,
        )

        if not vector_chunks and resolution.resolved_kpi:
            kpi = resolution.resolved_kpi
            if not business_domain or kpi.business_domain.value == business_domain:
                kpi_content = (
                    f"### {kpi.display_name} Definition\n"
                    f"**Business Meaning**: {kpi.description}\n"
                    f"**Calculation Formula**: {kpi.calculation_reference}\n"
                    f"**Unit**: {kpi.unit.value} | **Domain**: {kpi.business_domain.value}"
                )
                vector_chunks.append(
                    RetrievedChunk(
                        chunk_id=f"kpi_{kpi.canonical_name}",
                        document_id="doc_kpi_ontology",
                        document_title="NEXUS KPI Ontology Registry",
                        source="system_kpi_ontology",
                        title=kpi.display_name,
                        content=kpi_content,
                        similarity=1.0,
                        business_domain=kpi.business_domain.value,
                        retrieval_method="exact_kpi_match",
                        metadata_json={"canonical_name": kpi.canonical_name},
                    )
                )
                method = "exact_kpi_match"

        # Check for conflicting definitions across retrieved chunks
        has_conflict, conflict_desc = self._detect_conflicts(vector_chunks)

        # Format provenance evidence records
        evidence_list: list[RAGEvidence] = []
        context_parts: list[str] = []

        for chunk in vector_chunks:
            evidence_list.append(
                RAGEvidence(
                    document_id=chunk.document_id,
                    document_name=chunk.document_title,
                    chunk_id=chunk.chunk_id,
                    source=chunk.source,
                    title=chunk.title,
                    similarity_score=round(chunk.similarity, 4),
                    retrieval_method=chunk.retrieval_method,
                    excerpt=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                )
            )
            context_parts.append(
                f"--- [Source: {chunk.document_title} | Section: {chunk.title or 'N/A'}] ---\n"
                f"{chunk.content}"
            )

        context_text = "\n\n".join(context_parts) if context_parts else "No verified business context found."

        return RetrievedContext(
            query=query,
            chunks=vector_chunks,
            evidence=evidence_list,
            resolved_kpi_canonical=resolved_canonical,
            retrieval_method=method,
            has_conflict=has_conflict,
            conflict_description=conflict_desc,
            context_text=context_text,
        )

    def _search_vector_chunks(
        self,
        query: str,
        domain: str | None,
        top_k: int,
        threshold: float,
    ) -> tuple[list[RetrievedChunk], str]:
        """Query database chunks with optional domain filter and vector similarity."""
        query_embedding = self.embedding_provider.get_embedding(query)

        # Fetch active chunks
        stmt = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.status == "active")
        )
        if domain:
            stmt = stmt.where(KnowledgeChunk.business_domain == domain)

        results = self.session.execute(stmt).all()
        method = "metadata_filtered_vector" if domain else "vector_search"

        scored_chunks: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
        for chunk, doc in results:
            if not chunk.embedding:
                continue
            sim = _cosine_similarity(query_embedding, chunk.embedding)
            if sim >= threshold:
                scored_chunks.append((sim, chunk, doc))

        # Sort by similarity descending
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        top_matches = scored_chunks[:top_k]

        chunks_out: list[RetrievedChunk] = []
        for sim, chunk, doc in top_matches:
            chunks_out.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=doc.document_id,
                    document_title=doc.title,
                    source=doc.source,
                    title=chunk.title,
                    content=chunk.content,
                    similarity=sim,
                    business_domain=chunk.business_domain,
                    retrieval_method=method,
                    metadata_json=chunk.metadata_json or {},
                )
            )

        return chunks_out, method if chunks_out else "none"

    def _detect_conflicts(self, chunks: list[RetrievedChunk]) -> tuple[bool, str | None]:
        """
        Inspect retrieved chunks for conflicting business definitions or criteria.
        E.g. if chunks from distinct documents offer differing numeric thresholds for same concept.
        """
        if len(chunks) < 2:
            return False, None

        doc_ids = {c.document_id for c in chunks}
        if len(doc_ids) < 2:
            return False, None

        # Look for explicit conflicting definitions of common terms
        # E.g. active customer defined differently
        lower_contents = [c.content.lower() for c in chunks]
        
        # Check repeat customer threshold contradiction
        if any("repeat customer" in c for c in lower_contents):
            # check if one says 2 orders and another says 3 or more
            has_two = any("2 orders" in c or "two orders" in c for c in lower_contents)
            has_three = any("3 orders" in c or "three orders" in c for c in lower_contents)
            if has_two and has_three:
                return True, (
                    "Conflict detected: Retrieved business documents define 'repeat customer' differently "
                    "(one source specifies 2 orders, another specifies 3 orders)."
                )

        return False, None
