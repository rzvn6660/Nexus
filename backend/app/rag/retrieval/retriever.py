"""Hybrid Retrieval Engine combining deterministic KPI ontology, dense vector search, and lexical search."""

import logging
import math
import re
import time
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.rerank.base import BaseRerankProvider
from app.rag.rerank.factory import get_rerank_provider
from app.rag.retrieval.models import (
    RAGEvidence,
    RetrievalDiagnostics,
    RetrievedChunk,
    RetrievedContext,
)
from app.rag.semantic.ontology import SemanticResolver, semantic_resolver

logger = logging.getLogger(__name__)


def _is_zero_vector(vec: Sequence[float] | None) -> bool:
    """Detect uninitialized, degenerate, or placeholder all-zeros vectors."""
    if not vec:
        return True
    return all(abs(x) < 1e-9 for x in vec)


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_prod = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a, b in zip(vec_a, vec_b)))
    norm_b = math.sqrt(sum(b * b for a, b in zip(vec_b, vec_b)))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_prod / (norm_a * norm_b)


def _tokenize_lexical(text: str) -> list[str]:
    """
    Extract lexical tokens from text supporting English words, alphanumeric SKUs,
    Malayalam unicode characters, and Manglish terms.
    """
    if not text:
        return []
    raw = text.lower()
    # Extract unicode word tokens (including hyphenated strings like SKU-XYZ-90210)
    tokens = re.findall(r"[\w\-]+", raw)
    expanded: list[str] = []
    for t in tokens:
        expanded.append(t)
        if "-" in t or "_" in t:
            # Also extract constituent subcomponents
            for sub in re.split(r"[-_]", t):
                if sub and sub != t:
                    expanded.append(sub)
    return expanded


def _bm25_rank(
    query: str,
    candidates: list[tuple[KnowledgeChunk, KnowledgeDocument]],
    k1: float = 1.2,
    b: float = 0.75,
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float]]:
    """
    Deterministic in-memory Okapi BM25 scoring for candidate chunks.
    Ensures safe, bounded execution in SQLite/test environments or when PostgreSQL FTS is unavailable.
    """
    q_tokens = _tokenize_lexical(query)
    if not q_tokens or not candidates:
        return []

    N = len(candidates)
    doc_token_counts: list[dict[str, int]] = []
    doc_lens: list[int] = []
    df: dict[str, int] = {}

    for chunk, _ in candidates:
        chunk_text = f"{chunk.title or ''} {chunk.content}"
        tokens = _tokenize_lexical(chunk_text)
        doc_lens.append(len(tokens))

        counts: dict[str, int] = {}
        seen: set[str] = set()
        for tok in tokens:
            counts[tok] = counts.get(tok, 0) + 1
            if tok not in seen:
                seen.add(tok)
                df[tok] = df.get(tok, 0) + 1
        doc_token_counts.append(counts)

    avgdl = sum(doc_lens) / max(N, 1)

    # Standard BM25 IDF: ln((N - n + 0.5) / (n + 0.5) + 1.0)
    idfs: dict[str, float] = {}
    for qt in set(q_tokens):
        n = df.get(qt, 0)
        if n > 0:
            idfs[qt] = math.log((N - n + 0.5) / (n + 0.5) + 1.0)

    scored: list[tuple[KnowledgeChunk, KnowledgeDocument, float]] = []
    for idx, (chunk, doc) in enumerate(candidates):
        counts = doc_token_counts[idx]
        dl = doc_lens[idx]
        score = 0.0

        for qt in q_tokens:
            if qt in counts and qt in idfs:
                tf = counts[qt]
                idf = idfs[qt]
                denom = tf + k1 * (1.0 - b + b * (dl / max(avgdl, 1e-6)))
                score += idf * (tf * (k1 + 1.0)) / max(denom, 1e-6)

        if score > 0.0:
            scored.append((chunk, doc, score))

    scored.sort(
        key=lambda x: (
            -x[2],
            x[1].document_id,
            x[0].chunk_index if x[0].chunk_index is not None else 0,
        )
    )
    return scored


def _reciprocal_rank_fusion(
    dense_candidates: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
    lexical_candidates: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
    k_rrf: int = 60,
    w_dense: float = 1.0,
    w_lex: float = 1.0,
    top_k: int = 3,
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float, dict[str, Any]]]:
    """
    Reciprocal Rank Fusion (RRF) combining dense and lexical candidate lists.
    Implements duplicate suppression, rank interpolation, and deterministic tie-breaking.
    """
    fused: dict[str, dict[str, Any]] = {}

    for rank_idx, (chunk, doc, score) in enumerate(dense_candidates, start=1):
        cid = chunk.chunk_id or str(chunk.id)
        if cid not in fused:
            fused[cid] = {
                "chunk": chunk,
                "doc": doc,
                "dense_rank": rank_idx,
                "dense_score": score,
                "lexical_rank": None,
                "lexical_score": 0.0,
                "rrf_score": 0.0,
            }
        else:
            fused[cid]["dense_rank"] = rank_idx
            fused[cid]["dense_score"] = score
        fused[cid]["rrf_score"] += w_dense / (k_rrf + rank_idx)

    for rank_idx, (chunk, doc, score) in enumerate(lexical_candidates, start=1):
        cid = chunk.chunk_id or str(chunk.id)
        if cid not in fused:
            fused[cid] = {
                "chunk": chunk,
                "doc": doc,
                "dense_rank": None,
                "dense_score": 0.0,
                "lexical_rank": rank_idx,
                "lexical_score": score,
                "rrf_score": 0.0,
            }
        else:
            fused[cid]["lexical_rank"] = rank_idx
            fused[cid]["lexical_score"] = score
        fused[cid]["rrf_score"] += w_lex / (k_rrf + rank_idx)

    # Deterministic tie-breaking:
    # 1. -rrf_score (highest rank score)
    # 2. -dense_score
    # 3. -lexical_score
    # 4. doc.document_id (alphabetical)
    # 5. chunk.chunk_index (sequential)
    sorted_entries = sorted(
        fused.values(),
        key=lambda x: (
            -x["rrf_score"],
            -x["dense_score"],
            -x["lexical_score"],
            x["doc"].document_id,
            x["chunk"].chunk_index if x["chunk"].chunk_index is not None else 0,
        ),
    )

    results: list[tuple[KnowledgeChunk, KnowledgeDocument, float, dict[str, Any]]] = []
    for item in sorted_entries[:top_k]:
        meta = {
            "dense_rank": item["dense_rank"],
            "dense_score": round(item["dense_score"], 4),
            "lexical_rank": item["lexical_rank"],
            "lexical_score": round(item["lexical_score"], 4),
            "rrf_score": round(item["rrf_score"], 6),
        }
        results.append((item["chunk"], item["doc"], item["rrf_score"], meta))
    return results


def _linear_score_fusion(
    dense_candidates: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
    lexical_candidates: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
    w_dense: float = 0.7,
    w_lex: float = 0.3,
    top_k: int = 3,
) -> list[tuple[KnowledgeChunk, KnowledgeDocument, float, dict[str, Any]]]:
    """Optional linear score blending combining normalized dense and lexical scores."""
    fused: dict[str, dict[str, Any]] = {}

    max_lex = max([s for _, _, s in lexical_candidates], default=1.0)
    if max_lex <= 0.0:
        max_lex = 1.0

    for rank_idx, (chunk, doc, score) in enumerate(dense_candidates, start=1):
        cid = chunk.chunk_id or str(chunk.id)
        fused[cid] = {
            "chunk": chunk,
            "doc": doc,
            "dense_rank": rank_idx,
            "dense_score": score,
            "lexical_rank": None,
            "lexical_score": 0.0,
        }

    for rank_idx, (chunk, doc, score) in enumerate(lexical_candidates, start=1):
        cid = chunk.chunk_id or str(chunk.id)
        if cid not in fused:
            fused[cid] = {
                "chunk": chunk,
                "doc": doc,
                "dense_rank": None,
                "dense_score": 0.0,
                "lexical_rank": rank_idx,
                "lexical_score": score,
            }
        else:
            fused[cid]["lexical_rank"] = rank_idx
            fused[cid]["lexical_score"] = score

    for item in fused.values():
        norm_lex = item["lexical_score"] / max_lex
        norm_dense = max(0.0, min(1.0, item["dense_score"]))
        item["linear_score"] = (w_dense * norm_dense) + (w_lex * norm_lex)

    sorted_entries = sorted(
        fused.values(),
        key=lambda x: (
            -x["linear_score"],
            -x["dense_score"],
            -x["lexical_score"],
            x["doc"].document_id,
            x["chunk"].chunk_index if x["chunk"].chunk_index is not None else 0,
        ),
    )

    results: list[tuple[KnowledgeChunk, KnowledgeDocument, float, dict[str, Any]]] = []
    for item in sorted_entries[:top_k]:
        meta = {
            "dense_rank": item["dense_rank"],
            "dense_score": round(item["dense_score"], 4),
            "lexical_rank": item["lexical_rank"],
            "lexical_score": round(item["lexical_score"], 4),
            "linear_score": round(item["linear_score"], 6),
        }
        results.append((item["chunk"], item["doc"], item["linear_score"], meta))
    return results


def _sanitize_db_error(error_msg: str | None) -> str | None:
    """
    Sanitize database error string so credentials, passwords, or connection URLs
    are never leaked into retrieval diagnostics or client telemetry.
    """
    if not error_msg:
        return None
    sanitized = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", str(error_msg))
    sanitized = re.sub(r"password=[^\s,]+", "password=***", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(key|secret|token)=\S+", r"\1=***", sanitized, flags=re.IGNORECASE)
    return sanitized[:250]


class HybridRetriever:
    """
    Production Hybrid Retriever for NEXUS.

    Executes a tiered hybrid retrieval pipeline:
    1. Deterministic Semantic Resolution (Exact KPI ontology lookup)
    2. Independent Dense Candidate Generation (pgvector <=> cosine distance / HNSW)
    3. Independent Lexical Candidate Generation (PostgreSQL FTS websearch_to_tsquery / BM25 fallback)
    4. Reciprocal Rank Fusion (RRF) with duplicate suppression and deterministic tie-breaking
    5. Strict SQL-level tenant, business, and global-document authorization enforcement
    6. Provenance and embedding compatibility preservation across all retrieved evidence
    7. Semantic conflict and contradiction detection across evidence passages
    """

    def __init__(
        self,
        session: Session,
        resolver: SemanticResolver | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
        rerank_provider: BaseRerankProvider | None = None,
    ) -> None:
        self.session = session
        self.resolver = resolver or semantic_resolver
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.rerank_provider = rerank_provider or get_rerank_provider()

    def _apply_tenant_isolation(self, stmt: Any, business_id: str | None) -> Any:
        """
        Apply complete multi-tenant and global-document authorization filters to any query.
        Ensures chunks tagged with a specific tenant never leak, even under global documents.
        """
        if business_id is not None:
            stmt = stmt.where(
                or_(
                    KnowledgeChunk.business_id.is_(None),
                    KnowledgeChunk.business_id == business_id,
                )
            ).where(
                or_(
                    KnowledgeDocument.business_id == business_id,
                    (
                        (KnowledgeDocument.is_global.is_(True))
                        & (
                            (KnowledgeDocument.business_id.is_(None))
                            | (KnowledgeDocument.business_id == business_id)
                        )
                    ),
                )
            )
        else:
            # Unscoped queries only see truly global documents with global chunks
            stmt = stmt.where(KnowledgeChunk.business_id.is_(None)).where(
                or_(
                    KnowledgeDocument.is_global.is_(True),
                    KnowledgeDocument.business_id.is_(None),
                )
            )
        return stmt

    def _generate_dense_candidates(
        self,
        query: str,
        domain: str | None,
        candidate_k: int,
        threshold: float,
        business_id: str | None,
    ) -> tuple[list[tuple[KnowledgeChunk, KnowledgeDocument, float]], int, float]:
        """
        Generate dense vector candidates with strict model/provider/dimension/version enforcement.
        Returns (candidates, stale_vectors_excluded, latency_ms).
        """
        t0 = time.perf_counter()
        query_embedding = self.embedding_provider.get_embedding(query)
        actual_dim = len(query_embedding) if query_embedding else 0
        if actual_dim == 0:
            raise ValueError("Generated query embedding is empty.")

        expected_dim = self.embedding_provider.dimension
        if actual_dim != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch: Active provider '{self.embedding_provider.provider_name}' "
                f"({self.embedding_provider.model_name}) produced {actual_dim}-dimensional vector, "
                f"but is configured for {expected_dim} dimensions."
            )

        target_store_dim = (
            getattr(KnowledgeChunk.embedding.type, "dim", None) or settings.EMBEDDING_DIMENSION
        )
        if actual_dim != target_store_dim:
            raise ValueError(
                f"Embedding dimension mismatch: Active provider '{self.embedding_provider.provider_name}' "
                f"({self.embedding_provider.model_name}) produced {actual_dim}-dimensional vector, "
                f"but vector store 'knowledge_chunks.embedding' is configured for {target_store_dim} dimensions. "
                f"Update EMBEDDING_DIMENSION or re-index vector store with matching dimensions."
            )

        dialect_name = self.session.bind.dialect.name if self.session.bind else "sqlite"
        candidates: list[tuple[KnowledgeChunk, KnowledgeDocument, float]] = []
        stale_excluded = 0

        if dialect_name == "postgresql":
            # Native PostgreSQL pgvector <=> cosine distance
            distance_expr = KnowledgeChunk.embedding.cosine_distance(query_embedding)
            stmt = (
                select(KnowledgeChunk, KnowledgeDocument, distance_expr.label("distance"))
                .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                .where(KnowledgeDocument.status == "active")
                .where(KnowledgeChunk.embedding.is_not(None))
            )

            # Strict embedding space compatibility filters
            stmt = stmt.where(KnowledgeChunk.embedding_model == self.embedding_provider.model_name)
            stmt = stmt.where(
                (KnowledgeChunk.embedding_provider.is_(None))
                | (KnowledgeChunk.embedding_provider == self.embedding_provider.provider_name)
            )
            stmt = stmt.where(
                (KnowledgeChunk.embedding_version.is_(None))
                | (KnowledgeChunk.embedding_version == self.embedding_provider.version)
            )
            stmt = stmt.where(
                (KnowledgeChunk.embedding_dimension.is_(None))
                | (KnowledgeChunk.embedding_dimension == self.embedding_provider.dimension)
            )

            stmt = self._apply_tenant_isolation(stmt, business_id)
            if domain:
                stmt = stmt.where(KnowledgeChunk.business_domain == domain)

            max_dist = 1.0 - threshold
            stmt = stmt.where(distance_expr <= max_dist)
            stmt = stmt.order_by(distance_expr.asc()).limit(candidate_k)

            results = self.session.execute(stmt).all()

            # Count stale/incompatible chunks in scope excluded from ranking
            stale_count_stmt = (
                select(func.count(KnowledgeChunk.id))
                .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                .where(KnowledgeDocument.status == "active")
                .where(KnowledgeChunk.embedding.is_not(None))
                .where(
                    (KnowledgeChunk.embedding_model.is_(None))
                    | (KnowledgeChunk.embedding_model != self.embedding_provider.model_name)
                    | (
                        KnowledgeChunk.embedding_provider.is_not(None)
                        & (
                            KnowledgeChunk.embedding_provider
                            != self.embedding_provider.provider_name
                        )
                    )
                    | (
                        KnowledgeChunk.embedding_version.is_not(None)
                        & (KnowledgeChunk.embedding_version != self.embedding_provider.version)
                    )
                    | (
                        KnowledgeChunk.embedding_dimension.is_not(None)
                        & (KnowledgeChunk.embedding_dimension != self.embedding_provider.dimension)
                    )
                )
            )
            stale_count_stmt = self._apply_tenant_isolation(stale_count_stmt, business_id)
            stale_excluded = self.session.execute(stale_count_stmt).scalar() or 0

            for chunk, doc, dist in results:
                if _is_zero_vector(chunk.embedding):
                    continue
                sem_sim = max(0.0, 1.0 - float(dist))
                candidates.append((chunk, doc, sem_sim))
        else:
            # SQLite / Test in-memory fallback
            stmt = (
                select(KnowledgeChunk, KnowledgeDocument)
                .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                .where(KnowledgeDocument.status == "active")
                .where(KnowledgeChunk.embedding.is_not(None))
            )
            stmt = self._apply_tenant_isolation(stmt, business_id)
            if domain:
                stmt = stmt.where(KnowledgeChunk.business_domain == domain)
            max_scan = getattr(settings, "RAG_MAX_FALLBACK_SCAN_CHUNKS", 1000)
            stmt = stmt.limit(max_scan)

            all_chunks = self.session.execute(stmt).all()
            for chunk, doc in all_chunks:
                if not chunk.embedding or _is_zero_vector(chunk.embedding):
                    continue

                is_incompatible = (
                    not chunk.embedding_model
                    or chunk.embedding_model != self.embedding_provider.model_name
                    or (
                        chunk.embedding_provider
                        and chunk.embedding_provider != self.embedding_provider.provider_name
                    )
                    or (
                        chunk.embedding_version
                        and chunk.embedding_version != self.embedding_provider.version
                    )
                    or (
                        chunk.embedding_dimension
                        and chunk.embedding_dimension != self.embedding_provider.dimension
                    )
                    or len(chunk.embedding) != self.embedding_provider.dimension
                )
                if is_incompatible:
                    stale_excluded += 1
                    continue

                sem_sim = _cosine_similarity(query_embedding, chunk.embedding)
                if sem_sim >= threshold:
                    candidates.append((chunk, doc, sem_sim))

            candidates.sort(
                key=lambda x: (
                    -x[2],
                    x[1].document_id,
                    x[0].chunk_index if x[0].chunk_index is not None else 0,
                )
            )
            candidates = candidates[:candidate_k]

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return candidates, stale_excluded, elapsed_ms

    def _generate_lexical_candidates(
        self,
        query: str,
        domain: str | None,
        candidate_k: int,
        business_id: str | None,
    ) -> tuple[
        list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
        str,
        bool,
        float,
        str | None,
    ]:
        """
        Generate sparse lexical candidates independently from vector retrieval.
        Enforces tenant isolation and embedding compatibility so unverified or stale chunks
        do not leak or participate in search before re-embedding.
        Returns (candidates, engine_name, is_fallback, latency_ms, db_error).
        """
        t0 = time.perf_counter()
        q_tokens = _tokenize_lexical(query)
        if not q_tokens:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            return [], "none", False, elapsed_ms, None

        dialect_name = self.session.bind.dialect.name if self.session.bind else "sqlite"
        candidates: list[tuple[KnowledgeChunk, KnowledgeDocument, float]] = []
        db_error: str | None = None

        if dialect_name == "postgresql":
            try:
                # PostgreSQL production full-text search path using websearch_to_tsquery
                tsquery = func.websearch_to_tsquery("english", query)
                rank_expr = func.ts_rank_cd(KnowledgeChunk.tsv_content, tsquery)

                stmt = (
                    select(KnowledgeChunk, KnowledgeDocument, rank_expr.label("lex_score"))
                    .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                    .where(KnowledgeDocument.status == "active")
                    .where(KnowledgeChunk.embedding.is_not(None))
                    .where(KnowledgeChunk.embedding_model == self.embedding_provider.model_name)
                    .where(
                        (KnowledgeChunk.embedding_provider.is_(None))
                        | (
                            KnowledgeChunk.embedding_provider
                            == self.embedding_provider.provider_name
                        )
                    )
                    .where(
                        (KnowledgeChunk.embedding_version.is_(None))
                        | (KnowledgeChunk.embedding_version == self.embedding_provider.version)
                    )
                    .where(
                        (KnowledgeChunk.embedding_dimension.is_(None))
                        | (KnowledgeChunk.embedding_dimension == self.embedding_provider.dimension)
                    )
                    .where(KnowledgeChunk.tsv_content.op("@@")(tsquery))
                )
                stmt = self._apply_tenant_isolation(stmt, business_id)
                if domain:
                    stmt = stmt.where(KnowledgeChunk.business_domain == domain)

                stmt = stmt.order_by(text("lex_score DESC")).limit(candidate_k)
                res = self.session.execute(stmt).all()

                for chunk, doc, lex_score in res:
                    if _is_zero_vector(chunk.embedding):
                        continue
                    score_val = float(lex_score) if lex_score is not None else 0.0
                    candidates.append((chunk, doc, score_val))

                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                return candidates, "postgresql_fts", False, elapsed_ms, None
            except SQLAlchemyError as e:
                # CRITICAL: Roll back the failed transaction immediately so the connection
                # is not left in an aborted state (psycopg2.errors.InFailedSqlTransaction).
                self.session.rollback()
                logger.exception(
                    "PostgreSQL FTS error during lexical candidate generation, transaction rolled back."
                )
                db_error = _sanitize_db_error(str(e))

        # SQLite / In-memory BM25 Fallback Path (strictly bounded)
        max_scan = getattr(settings, "RAG_MAX_FALLBACK_SCAN_CHUNKS", 1000)
        stmt = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.status == "active")
            .where(KnowledgeChunk.embedding.is_not(None))
        )
        stmt = self._apply_tenant_isolation(stmt, business_id)
        if domain:
            stmt = stmt.where(KnowledgeChunk.business_domain == domain)
        stmt = stmt.limit(max_scan)

        raw_chunks = self.session.execute(stmt).all()
        scoped_chunks: list[tuple[KnowledgeChunk, KnowledgeDocument]] = []
        for chunk, doc in raw_chunks:
            if not chunk.embedding or _is_zero_vector(chunk.embedding):
                continue
            is_incompatible = (
                not chunk.embedding_model
                or chunk.embedding_model != self.embedding_provider.model_name
                or (
                    chunk.embedding_provider
                    and chunk.embedding_provider != self.embedding_provider.provider_name
                )
                or (
                    chunk.embedding_version
                    and chunk.embedding_version != self.embedding_provider.version
                )
                or (
                    chunk.embedding_dimension
                    and chunk.embedding_dimension != self.embedding_provider.dimension
                )
                or len(chunk.embedding) != self.embedding_provider.dimension
            )
            if is_incompatible:
                continue
            scoped_chunks.append((chunk, doc))

        bm25_matches = _bm25_rank(query, scoped_chunks)
        candidates = bm25_matches[:candidate_k]

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        engine_name = (
            "postgresql_error_bm25_fallback"
            if dialect_name == "postgresql"
            else "sqlite_bm25_fallback"
        )
        return candidates, engine_name, True, elapsed_ms, db_error

    def _fuse_candidates(
        self,
        dense_candidates: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
        lexical_candidates: list[tuple[KnowledgeChunk, KnowledgeDocument, float]],
        top_k: int,
    ) -> tuple[list[RetrievedChunk], str, float]:
        """
        Fuse dense and lexical candidates into final ranked chunks using RRF or linear blending.
        Enriches metadata with rank diagnostics and preserves complete provenance.
        """
        t0 = time.perf_counter()
        fusion_method = getattr(settings, "RAG_FUSION_METHOD", "rrf")
        w_dense = getattr(settings, "RAG_HYBRID_SEMANTIC_WEIGHT", 0.7)
        w_lex = getattr(settings, "RAG_HYBRID_LEXICAL_WEIGHT", 0.3)
        rrf_k = getattr(settings, "RAG_RRF_K", 60)

        if fusion_method == "linear":
            fused_items = _linear_score_fusion(
                dense_candidates=dense_candidates,
                lexical_candidates=lexical_candidates,
                w_dense=w_dense,
                w_lex=w_lex,
                top_k=top_k,
            )
        else:
            fusion_method = "rrf"
            fused_items = _reciprocal_rank_fusion(
                dense_candidates=dense_candidates,
                lexical_candidates=lexical_candidates,
                k_rrf=rrf_k,
                w_dense=w_dense,
                w_lex=w_lex,
                top_k=top_k,
            )

        chunks_out: list[RetrievedChunk] = []
        for chunk, doc, sim_score, rank_meta in fused_items:
            # Determine specific method based on candidate presence
            is_in_dense = rank_meta.get("dense_rank") is not None
            is_in_lex = rank_meta.get("lexical_rank") is not None
            if is_in_dense and is_in_lex:
                chunk_method = f"hybrid_{fusion_method}"
            elif is_in_dense:
                chunk_method = "dense_only"
            else:
                chunk_method = "lexical_only"

            enriched_meta = dict(chunk.metadata_json or {})
            enriched_meta.update(rank_meta)

            chunks_out.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=doc.document_id,
                    document_title=doc.title,
                    source=doc.source,
                    title=chunk.title,
                    content=chunk.content,
                    similarity=round(sim_score, 6),
                    business_domain=chunk.business_domain,
                    retrieval_method=chunk_method,
                    metadata_json=enriched_meta,
                    chunk_hash=chunk.chunk_hash,
                    chunk_index=chunk.chunk_index,
                    document_version=doc.version,
                    business_id=chunk.business_id,
                    embedding_provider=chunk.embedding_provider,
                    embedding_model=chunk.embedding_model,
                    embedding_version=chunk.embedding_version,
                )
            )

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return chunks_out, fusion_method, elapsed_ms

    def retrieve(
        self,
        query: str,
        business_domain: str | None = None,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        business_id: str | None = None,
    ) -> RetrievedContext:
        """
        Execute production hybrid context retrieval for a query.
        Combines deterministic KPI resolution, independent dense/lexical candidate generation,
        and Reciprocal Rank Fusion.
        """
        start_time = time.perf_counter()
        k = top_k or settings.RAG_TOP_K or 3
        threshold = similarity_threshold or settings.RAG_SIMILARITY_THRESHOLD or 0.2
        candidate_k = max(k * 2, getattr(settings, "RAG_LEXICAL_TOP_K", 10))
        clean_query = query.strip()

        if not clean_query:
            return RetrievedContext(
                query=query,
                retrieval_method="none",
                context_text="No verified business context requested.",
                embedding_provider=self.embedding_provider.provider_name,
                embedding_model=self.embedding_provider.model_name,
                diagnostics=RetrievalDiagnostics(fusion_method="none", lexical_engine="none"),
            )

        # Tier 1: Deterministic Semantic KPI Resolution
        resolution = self.resolver.resolve(clean_query)
        resolved_domain = business_domain or (
            resolution.resolved_kpi.business_domain.value if resolution.resolved_kpi else None
        )
        resolved_canonical = resolution.canonical_name

        # Tier 2: Independent Dense & Lexical Candidate Generation
        dense_cands, stale_count, dense_lat = self._generate_dense_candidates(
            query=clean_query,
            domain=resolved_domain,
            candidate_k=candidate_k,
            threshold=threshold,
            business_id=business_id,
        )

        (
            lexical_cands,
            lex_engine,
            is_lex_fallback,
            lex_lat,
            db_error,
        ) = self._generate_lexical_candidates(
            query=clean_query,
            domain=resolved_domain,
            candidate_k=candidate_k,
            business_id=business_id,
        )

        # Tier 3: Reciprocal Rank Fusion / Score Blending
        fused_chunks, fusion_method, fuse_lat = self._fuse_candidates(
            dense_candidates=dense_cands,
            lexical_candidates=lexical_cands,
            top_k=k,
        )

        # Tier 4: Optional Cross-Encoder Reranking (Phase 25C.3)
        rerank_t0 = time.perf_counter()
        rerank_latency = 0.0
        rerank_applied = False
        if (
            getattr(settings, "RAG_RERANK_ENABLED", False)
            or self.rerank_provider.provider_name != "none"
        ) and fused_chunks:
            fused_chunks = self.rerank_provider.rerank(clean_query, fused_chunks, top_k=k)
            rerank_latency = round((time.perf_counter() - rerank_t0) * 1000, 2)
            rerank_applied = True

        # Determine aggregate retrieval method and mode
        dialect_name = self.session.bind.dialect.name if self.session.bind else "sqlite"
        retrieval_mode = "pgvector_native" if dialect_name == "postgresql" else "sqlite_fallback"

        if resolution.resolved_kpi and not fused_chunks:
            kpi = resolution.resolved_kpi
            if not business_domain or kpi.business_domain.value == business_domain:
                kpi_content = (
                    f"### {kpi.display_name} Definition\n"
                    f"**Business Meaning**: {kpi.description}\n"
                    f"**Calculation Formula**: {kpi.calculation_reference}\n"
                    f"**Unit**: {kpi.unit.value} | **Domain**: {kpi.business_domain.value}"
                )
                fused_chunks.append(
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
        elif any(c.retrieval_method.startswith("hybrid_") for c in fused_chunks):
            method = "hybrid_search"
        elif any(c.retrieval_method == "dense_only" for c in fused_chunks):
            method = "vector_search"
        elif any(c.retrieval_method == "lexical_only" for c in fused_chunks):
            method = "lexical_search"
        else:
            method = "none"

        # Evaluate candidate relevance and confidence threshold
        has_sufficient_context = True
        confidence_level = "sufficient"
        confidence_score = 1.0
        irrelevant_filtered = 0

        if not fused_chunks:
            has_sufficient_context = False
            confidence_level = "none"
            confidence_score = 0.0
        else:
            top_chunk = fused_chunks[0]
            if top_chunk.retrieval_method == "exact_kpi_match":
                has_sufficient_context = True
                confidence_level = "sufficient"
                confidence_score = 1.0
            else:
                top_meta = top_chunk.metadata_json or {}
                has_lexical = top_meta.get("lexical_rank") is not None
                dense_score = float(top_meta.get("dense_score", 0.0))
                semantic_floor = threshold

                if has_lexical:
                    has_sufficient_context = True
                    confidence_level = "sufficient"
                    confidence_score = max(0.85, dense_score)
                elif dense_score >= 0.35:
                    has_sufficient_context = True
                    confidence_level = "sufficient"
                    confidence_score = round(dense_score, 4)
                elif dense_score >= semantic_floor:
                    has_sufficient_context = True
                    confidence_level = "low"
                    confidence_score = round(dense_score, 4)
                else:
                    # Sub-threshold candidate: discard noise near floor with 0 lexical overlap
                    irrelevant_filtered = len(fused_chunks)
                    fused_chunks = []
                    has_sufficient_context = False
                    confidence_level = "none"
                    confidence_score = round(dense_score, 4)
                    method = "none"

        # Check for conflicting definitions across retrieved chunks
        has_conflict, conflict_desc = self._detect_conflicts(fused_chunks)

        # Format provenance evidence records
        evidence_list: list[RAGEvidence] = []
        context_parts: list[str] = []

        for chunk in fused_chunks:
            evidence_list.append(
                RAGEvidence(
                    document_id=chunk.document_id,
                    document_name=chunk.document_title,
                    chunk_id=chunk.chunk_id,
                    source=chunk.source,
                    title=chunk.title,
                    similarity_score=round(chunk.similarity, 4),
                    retrieval_method=chunk.retrieval_method,
                    excerpt=chunk.content[:200] + "..."
                    if len(chunk.content) > 200
                    else chunk.content,
                    embedding_provider=chunk.embedding_provider,
                    embedding_model=chunk.embedding_model,
                    embedding_version=chunk.embedding_version,
                    chunk_hash=chunk.chunk_hash,
                    document_version=chunk.document_version,
                    business_id=chunk.business_id,
                    chunk_index=chunk.chunk_index,
                    rerank_score=chunk.rerank_score,
                )
            )
            context_parts.append(
                f"--- [Source: {chunk.document_title} | Section: {chunk.title or 'N/A'}] ---\n"
                f"{chunk.content}"
            )

        if context_parts:
            context_text = "\n\n".join(context_parts)
        elif irrelevant_filtered > 0:
            context_text = "No verified business context found (candidates below relevance threshold)."
        else:
            context_text = "No verified business context found."

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        diagnostics = RetrievalDiagnostics(
            dense_candidates_count=len(dense_cands),
            lexical_candidates_count=len(lexical_cands),
            fused_candidates_count=len(fused_chunks),
            fusion_method=fusion_method if fused_chunks else "none",
            lexical_engine=lex_engine,
            is_lexical_fallback=is_lex_fallback,
            fallback_used=is_lex_fallback,
            database_error=db_error,
            dense_latency_ms=dense_lat,
            lexical_latency_ms=lex_lat,
            fusion_latency_ms=fuse_lat,
            stale_vectors_excluded=stale_count,
            rerank_enabled=rerank_applied,
            rerank_provider=self.rerank_provider.provider_name if rerank_applied else None,
            rerank_latency_ms=rerank_latency,
            irrelevant_candidates_filtered=irrelevant_filtered,
        )

        return RetrievedContext(
            query=query,
            chunks=fused_chunks,
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
            has_sufficient_context=has_sufficient_context,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            execution_time_ms=elapsed_ms,
            diagnostics=diagnostics,
        )

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
            has_inc_ship = any(
                "includes shipping" in c or "including shipping" in c for c in lower_contents
            )
            has_exc_ship = any(
                "excludes shipping" in c or "excluding shipping" in c for c in lower_contents
            )
            if has_inc_ship and has_exc_ship:
                return True, (
                    "Conflict detected: Retrieved business documents define revenue differently "
                    "(one source includes shipping, another excludes shipping)."
                )

        return False, None
