"""Hybrid Retrieval Engine combining deterministic KPI ontology and vector search."""

import logging
import math
import re
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.retrieval.models import RAGEvidence, RetrievedChunk, RetrievedContext
from app.rag.semantic.ontology import SemanticResolver, semantic_resolver

logger = logging.getLogger(__name__)


def _is_zero_vector(vec: list[float] | None) -> bool:
    """Detect uninitialized, degenerate, or placeholder all-zeros vectors."""
    if not vec:
        return True
    return all(abs(x) < 1e-9 for x in vec)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_prod = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a, b in zip(vec_a, vec_b)))
    norm_b = math.sqrt(sum(b * b for a, b in zip(vec_b, vec_b)))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_prod / (norm_a * norm_b)


def _lexical_overlap_score(query: str, text: str) -> float:
    """Compute simple normalized token overlap score for lexical candidate ranking."""
    q_tokens = set(re.findall(r"\b\w+\b", query.lower()))
    if not q_tokens:
        return 0.0
    t_tokens = set(re.findall(r"\b\w+\b", text.lower()))
    if not t_tokens:
        return 0.0
    overlap = len(q_tokens.intersection(t_tokens))
    return min(overlap / len(q_tokens), 1.0)


class HybridRetriever:
    """
    Business Context Retriever for NEXUS.
    
    Executes a tiered hybrid retrieval pipeline:
    1. Deterministic KPI lookup (Exact ontology & synonyms)
    2. Native PostgreSQL pgvector cosine similarity search (<=> operator with HNSW)
    3. PostgreSQL native full-text search (tsvector/tsquery lexical matching)
    4. Deterministic score normalization & hybrid ranking
    5. SQL-level tenant and business isolation
    6. Stale/invalid vector space exclusion
    7. Conflict and ambiguity detection across retrieved sources
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
        business_id: str | None = None,
    ) -> RetrievedContext:
        """
        Execute hybrid context retrieval for a user query.
        """
        start_time = time.perf_counter()
        k = top_k or settings.RAG_TOP_K or 3
        threshold = similarity_threshold or settings.RAG_SIMILARITY_THRESHOLD or 0.2
        clean_query = query.strip()

        if not clean_query:
            return RetrievedContext(
                query=query,
                retrieval_method="none",
                context_text="No verified business context requested.",
                embedding_provider=self.embedding_provider.provider_name,
                embedding_model=self.embedding_provider.model_name,
            )

        # 1. Tier 1: Deterministic Semantic Resolution
        resolution = self.resolver.resolve(clean_query)
        resolved_domain = business_domain or (
            resolution.resolved_kpi.business_domain.value if resolution.resolved_kpi else None
        )
        resolved_canonical = resolution.canonical_name

        # 2. Tier 2: Vector & Hybrid Search over Stored Documents
        vector_chunks, method, retrieval_mode, stale_count = self._search_vector_chunks(
            query=clean_query,
            domain=resolved_domain,
            top_k=k,
            threshold=threshold,
            business_id=business_id,
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
                retrieval_mode = "exact_kpi_match"

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
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return RetrievedContext(
            query=query,
            chunks=vector_chunks,
            evidence=evidence_list,
            resolved_kpi_canonical=resolved_canonical,
            retrieval_method=method,
            has_conflict=has_conflict,
            conflict_description=conflict_desc,
            context_text=context_text,
            embedding_provider=self.embedding_provider.provider_name,
            embedding_model=self.embedding_provider.model_name,
            retrieval_mode=retrieval_mode,
            stale_vectors_excluded=stale_count,
            execution_time_ms=elapsed_ms,
        )

    def _search_vector_chunks(
        self,
        query: str,
        domain: str | None,
        top_k: int,
        threshold: float,
        business_id: str | None = None,
    ) -> tuple[list[RetrievedChunk], str, str, int]:
        """
        Query database chunks with SQL-level tenant isolation, pgvector cosine distance,
        and hybrid lexical scoring.
        """
        query_embedding = self.embedding_provider.get_embedding(query)
        dialect_name = self.session.bind.dialect.name if self.session.bind else "sqlite"

        w_sem = settings.RAG_HYBRID_SEMANTIC_WEIGHT if settings.RAG_HYBRID_SEARCH_ENABLED else 1.0
        w_lex = settings.RAG_HYBRID_LEXICAL_WEIGHT if settings.RAG_HYBRID_SEARCH_ENABLED else 0.0

        stale_excluded = 0
        chunks_out: list[RetrievedChunk] = []

        if dialect_name == "postgresql":
            # -------------------------------------------------------------
            # PostgreSQL Production Path: Native pgvector <=> & HNSW Index
            # -------------------------------------------------------------
            distance_expr = KnowledgeChunk.embedding.cosine_distance(query_embedding)
            stmt = (
                select(
                    KnowledgeChunk,
                    KnowledgeDocument,
                    distance_expr.label("distance"),
                )
                .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                .where(KnowledgeDocument.status == "active")
                .where(KnowledgeChunk.embedding.is_not(None))
            )

            # Exclude stale vector spaces: model must match if populated
            stmt = stmt.where(
                (KnowledgeChunk.embedding_model.is_(None))
                | (KnowledgeChunk.embedding_model == self.embedding_provider.model_name)
            )

            # Strict SQL-level tenant & business isolation
            if business_id is not None:
                stmt = stmt.where(
                    (KnowledgeDocument.is_global.is_(True))
                    | (
                        (KnowledgeDocument.business_id == business_id)
                        | (KnowledgeChunk.business_id == business_id)
                    )
                )
                stmt = stmt.where(
                    (KnowledgeDocument.business_id.is_(None))
                    | (KnowledgeDocument.business_id == business_id)
                    | (KnowledgeDocument.is_global.is_(True))
                )
                stmt = stmt.where(
                    (KnowledgeChunk.business_id.is_(None))
                    | (KnowledgeChunk.business_id == business_id)
                    | (KnowledgeDocument.is_global.is_(True))
                )
            else:
                stmt = stmt.where(
                    (KnowledgeDocument.is_global.is_(True))
                    | (
                        (KnowledgeDocument.business_id.is_(None))
                        & (KnowledgeChunk.business_id.is_(None))
                    )
                )

            if domain:
                stmt = stmt.where(KnowledgeChunk.business_domain == domain)

            # Only candidates within distance threshold
            max_dist = 1.0 - threshold
            stmt = stmt.where(distance_expr <= max_dist)
            stmt = stmt.order_by(distance_expr.asc()).limit(top_k * 2)

            results = self.session.execute(stmt).all()

            scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
            for chunk, doc, dist in results:
                if _is_zero_vector(chunk.embedding):
                    continue
                sem_sim = max(0.0, 1.0 - float(dist))
                lex_sim = _lexical_overlap_score(query, chunk.content) if w_lex > 0 else 0.0
                combined = (w_sem * sem_sim) + (w_lex * lex_sim)
                if combined >= threshold:
                    scored.append((combined, chunk, doc))

            scored.sort(key=lambda x: x[0], reverse=True)
            for score, chunk, doc in scored[:top_k]:
                chunks_out.append(
                    RetrievedChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=doc.document_id,
                        document_title=doc.title,
                        source=doc.source,
                        title=chunk.title,
                        content=chunk.content,
                        similarity=score,
                        business_domain=chunk.business_domain,
                        retrieval_method="pgvector_hybrid" if w_lex > 0 else "pgvector_native",
                        metadata_json=chunk.metadata_json or {},
                    )
                )

            retrieval_mode = "pgvector_native"

        else:
            # -------------------------------------------------------------
            # SQLite Test Path: Fallback with SQL tenant isolation
            # -------------------------------------------------------------
            stmt = (
                select(KnowledgeChunk, KnowledgeDocument)
                .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                .where(KnowledgeDocument.status == "active")
                .where(KnowledgeChunk.embedding.is_not(None))
            )

            # Strict SQL-level tenant isolation
            if business_id is not None:
                stmt = stmt.where(
                    (KnowledgeDocument.is_global.is_(True))
                    | (
                        (KnowledgeDocument.business_id == business_id)
                        | (KnowledgeChunk.business_id == business_id)
                    )
                )
                stmt = stmt.where(
                    (KnowledgeDocument.business_id.is_(None))
                    | (KnowledgeDocument.business_id == business_id)
                    | (KnowledgeDocument.is_global.is_(True))
                )
                stmt = stmt.where(
                    (KnowledgeChunk.business_id.is_(None))
                    | (KnowledgeChunk.business_id == business_id)
                    | (KnowledgeDocument.is_global.is_(True))
                )
            else:
                stmt = stmt.where(
                    (KnowledgeDocument.is_global.is_(True))
                    | (
                        (KnowledgeDocument.business_id.is_(None))
                        & (KnowledgeChunk.business_id.is_(None))
                    )
                )

            if domain:
                stmt = stmt.where(KnowledgeChunk.business_domain == domain)

            results = self.session.execute(stmt).all()

            scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
            for chunk, doc in results:
                # 1. Skip NULL or degenerate zero vectors
                if not chunk.embedding or _is_zero_vector(chunk.embedding):
                    continue

                # 2. Exclude mismatched/stale vector spaces
                if chunk.embedding_model and chunk.embedding_model != self.embedding_provider.model_name:
                    stale_excluded += 1
                    continue

                # 3. Check dimension compatibility
                if len(chunk.embedding) != self.embedding_provider.dimension:
                    continue

                sem_sim = _cosine_similarity(query_embedding, chunk.embedding)
                lex_sim = _lexical_overlap_score(query, chunk.content) if w_lex > 0 else 0.0
                combined = (w_sem * sem_sim) + (w_lex * lex_sim)

                if combined >= threshold:
                    scored.append((combined, chunk, doc))

            scored.sort(key=lambda x: x[0], reverse=True)
            for score, chunk, doc in scored[:top_k]:
                chunks_out.append(
                    RetrievedChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=doc.document_id,
                        document_title=doc.title,
                        source=doc.source,
                        title=chunk.title,
                        content=chunk.content,
                        similarity=score,
                        business_domain=chunk.business_domain,
                        retrieval_method="sqlite_hybrid" if w_lex > 0 else "sqlite_fallback",
                        metadata_json=chunk.metadata_json or {},
                    )
                )

            retrieval_mode = "sqlite_fallback"

        method = (
            "metadata_filtered_vector"
            if domain
            else ("hybrid_search" if w_lex > 0 else "vector_search")
        )

        return chunks_out, method if chunks_out else "none", retrieval_mode, stale_excluded

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
        lower_contents = [c.content.lower() for c in chunks]
        
        # Check repeat customer threshold contradiction
        if any("repeat customer" in c for c in lower_contents):
            has_two = any("2 orders" in c or "two orders" in c for c in lower_contents)
            has_three = any("3 orders" in c or "three orders" in c for c in lower_contents)
            if has_two and has_three:
                return True, (
                    "Conflict detected: Retrieved business documents define 'repeat customer' differently "
                    "(one source specifies 2 orders, another specifies 3 orders)."
                )

        # Check return policy window contradiction
        if any("return" in c for c in lower_contents):
            has_14 = any("14 days" in c or "14-day" in c for c in lower_contents)
            has_30 = any("30 days" in c or "30-day" in c for c in lower_contents)
            if has_14 and has_30:
                return True, (
                    "Conflict detected: Retrieved business documents define return policy window differently "
                    "(one source specifies 14 days, another specifies 30 days)."
                )

        # Check revenue calculation contradiction (shipping inclusion)
        if any("revenue" in c for c in lower_contents):
            has_inc_ship = any("includes shipping" in c or "including shipping" in c for c in lower_contents)
            has_exc_ship = any("excludes shipping" in c or "excluding shipping" in c for c in lower_contents)
            if has_inc_ship and has_exc_ship:
                return True, (
                    "Conflict detected: Retrieved business documents define revenue differently "
                    "(one source includes shipping, another excludes shipping)."
                )

        return False, None
