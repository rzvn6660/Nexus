"""Regression tests for Document Version Lifecycle, Transactional Chunk Purging, and Reranking (Phase 25C.3)."""

from unittest.mock import patch

import pytest
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from app.rag.rerank.factory import get_rerank_provider
from app.rag.rerank.providers.cross_scorer import LocalCrossScorerRerankProvider
from app.rag.rerank.providers.noop import NoOpRerankProvider
from app.rag.retrieval.models import RetrievedChunk
from app.rag.retrieval.retriever import HybridRetriever, _sanitize_db_error
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def test_version_advancement_on_document_modification(db_session: Session):
    """
    Verify that when an existing document source and title is re-ingested with modified content,
    the version auto-increments (1.0 -> 1.1), the previous document is marked 'superseded',
    and the new document is marked 'active'.
    """
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(
        title="Procurement Policy",
        business_domain="operations",
        version="1.0",
        source="procurement_policy.md",
    )

    # 1. Ingest initial document (v1.0)
    v1_text = "## Purchase Orders\nPurchase orders over $500 require departmental director sign-off."
    res1 = service.ingest_text(v1_text, doc_type="markdown", metadata=meta, business_id="biz_proc_1")
    assert res1.version == "1.0"
    assert res1.status == "active"
    doc1 = db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.document_id == res1.document_id)
    ).scalar_one()
    assert doc1.status == "active"

    # 2. Re-ingest with modified threshold
    v2_text = "## Purchase Orders\nPurchase orders over $1000 require departmental director sign-off."
    res2 = service.ingest_text(v2_text, doc_type="markdown", metadata=meta, business_id="biz_proc_1")
    assert res2.version == "1.1"
    assert res2.status == "active"
    assert res2.document_id != res1.document_id

    # Verify previous document is superseded
    db_session.refresh(doc1)
    assert doc1.status == "superseded"


class _EmbeddingProviderSpy:
    """Wrapper spy tracking invocations of get_embeddings while delegating to real provider."""

    def __init__(self, base_provider):
        self._base = base_provider
        self.call_count = 0
        self.recorded_calls = []

    @property
    def provider_name(self) -> str:
        return self._base.provider_name

    @property
    def model_name(self) -> str:
        return self._base.model_name

    @property
    def dimension(self) -> int:
        return self._base.dimension

    @property
    def version(self) -> str:
        return self._base.version

    def get_embedding(self, text: str):
        return self._base.get_embedding(text)

    def get_embeddings(self, texts: list[str]):
        self.call_count += 1
        self.recorded_calls.append(list(texts))
        return self._base.get_embeddings(texts)


def test_identical_document_deduplication_no_reembedding(db_session: Session):
    """
    Verify that ingesting identical text detects the content hash match,
    returns is_duplicate=True, reuses the existing record, and skips calling get_embeddings.
    """
    spy = _EmbeddingProviderSpy(get_embedding_provider())
    service = DocumentIngestionService(db_session, embedding_provider=spy)

    doc_text = "## Holiday Policy\nOffice closure calendar observed for all retail locations."
    meta = DocumentMetadata(
        title="Holiday Calendar",
        business_domain="operations",
        source="holiday.md",
    )

    # 1. First ingestion (calls provider)
    res1 = service.ingest_text(doc_text, doc_type="markdown", metadata=meta, business_id="biz_holiday_1")
    assert res1.is_duplicate is False
    assert spy.call_count == 1

    # 2. Second ingestion with identical content
    res2 = service.ingest_text(doc_text, doc_type="markdown", metadata=meta, business_id="biz_holiday_1")
    assert res2.is_duplicate is True
    assert res2.document_id == res1.document_id
    # Ensure zero fresh embedding calls were made on duplicate
    assert spy.call_count == 1


def test_partial_modification_reuses_compatible_cached_embeddings(db_session: Session):
    """
    Verify differential chunk ingestion: when a document is updated with 1 modified section
    and 1 unchanged section, the embedding provider is only invoked for the modified section,
    reusing cached embeddings for the unchanged chunk.
    """
    spy = _EmbeddingProviderSpy(get_embedding_provider())
    service = DocumentIngestionService(db_session, embedding_provider=spy)

    meta = DocumentMetadata(
        title="Shipping Guide",
        business_domain="operations",
        source="shipping_guide.md",
    )

    text_v1 = (
        "## Standard Ground Shipping\n"
        "Ground delivery transit window is estimated at 3 to 5 business days.\n\n"
        "## Express Air Courier\n"
        "Next day expedited shipping cuts transit time to 24 hours flat."
    )
    service.ingest_text(text_v1, doc_type="markdown", metadata=meta, business_id="biz_ship_1")
    assert spy.call_count == 1

    # Update: Ground Shipping unchanged, Express Air Courier modified
    text_v2 = (
        "## Standard Ground Shipping\n"
        "Ground delivery transit window is estimated at 3 to 5 business days.\n\n"
        "## Express Air Courier\n"
        "Next day expedited shipping cuts transit time to 12 hours for metro zones."
    )
    service.ingest_text(text_v2, doc_type="markdown", metadata=meta, business_id="biz_ship_1")

    # In the second ingestion, get_embeddings should have been called with ONLY 1 modified chunk
    assert spy.call_count == 2
    last_batch = spy.recorded_calls[-1]
    assert len(last_batch) == 1
    assert "12 hours for metro zones" in last_batch[0]


def test_failed_reingestion_transaction_rollback(db_session: Session):
    """
    Verify that if re-ingestion fails (e.g. embedding API error or database failure),
    the transaction rolls back and the last valid document version remains active
    with its original chunks intact.
    """
    provider = get_embedding_provider()
    service = DocumentIngestionService(db_session, embedding_provider=provider)

    meta = DocumentMetadata(
        title="Safety Guidelines",
        business_domain="operations",
        source="safety.md",
    )
    valid_text = "## Fire Safety\nEmergency exits must remain unobstructed at all operating hours."
    res1 = service.ingest_text(valid_text, doc_type="markdown", metadata=meta, business_id="biz_safe_1")
    assert res1.status == "active"

    # Verify original document and chunk exist
    orig_doc = db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.document_id == res1.document_id)
    ).scalar_one()
    orig_chunks = db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == orig_doc.id)
    ).scalars().all()
    assert orig_doc.status == "active"
    assert len(orig_chunks) >= 1

    # Simulate failing embedding provider during re-ingestion
    class FailingProvider(_EmbeddingProviderSpy):
        def get_embeddings(self, texts):
            raise RuntimeError("Embedding service connection timed out")

    failing_service = DocumentIngestionService(db_session, embedding_provider=FailingProvider(provider))

    modified_text = "## Fire Safety\nEmergency exits must remain unobstructed and illuminated."
    with pytest.raises(RuntimeError, match="Embedding service connection timed out"):
        failing_service.ingest_text(
            modified_text, doc_type="markdown", metadata=meta, business_id="biz_safe_1"
        )

    # Verify rollback: original document is STILL active and original chunks still exist
    db_session.refresh(orig_doc)
    assert orig_doc.status == "active"
    current_chunks = db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == orig_doc.id)
    ).scalars().all()
    assert len(current_chunks) == len(orig_chunks)


def test_obsolete_chunks_purged_and_retrieval_never_returns_stale_chunks(db_session: Session):
    """
    Verify that upon successful document update, obsolete chunks from previous versions
    are purged from the database, and retrieval never returns stale passages.
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()

    meta = DocumentMetadata(
        title="Operational Protocol Guide",
        business_domain="operations",
        source="protocol_guide.md",
    )

    # v1.0 contains unique obsolete code
    v1_text = "## Deprecated Workflow\nArchived procedure PROTOCOL-ALPHA-OBSOLETE-999 is expired."
    res1 = service.ingest_text(v1_text, doc_type="markdown", metadata=meta, business_id="biz_proto_1")
    doc1 = db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.document_id == res1.document_id)
    ).scalar_one()

    retriever = HybridRetriever(db_session, embedding_provider=provider)

    # Initial query finds obsolete code
    search_v1 = retriever.retrieve("PROTOCOL-ALPHA-OBSOLETE-999", business_id="biz_proto_1")
    assert len(search_v1.chunks) >= 1
    assert "PROTOCOL-ALPHA-OBSOLETE-999" in search_v1.chunks[0].content

    # v1.1 replaces clause with new standard
    v2_text = "## Modern Standard\nActive procedure PROTOCOL-BETA-CURRENT-888 is enforced."
    service.ingest_text(v2_text, doc_type="markdown", metadata=meta, business_id="biz_proto_1")

    # 1. Verify obsolete chunks for doc1 were removed from database
    doc1_chunks = db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc1.id)
    ).scalars().all()
    assert len(doc1_chunks) == 0

    # 2. Querying obsolete unique term yields 0 chunks (never returns stale data)
    search_obsolete = retriever.retrieve("ALPHA-OBSOLETE-999", business_id="biz_proto_1")
    assert len(search_obsolete.chunks) == 0

    # Querying the full old identifier never returns the stale text or doc1
    search_old_id = retriever.retrieve("PROTOCOL-ALPHA-OBSOLETE-999", business_id="biz_proto_1")
    assert not any("ALPHA-OBSOLETE-999" in c.content for c in search_old_id.chunks)
    assert not any(c.document_id == doc1.document_id for c in search_old_id.chunks)

    # 3. Querying new code succeeds with v1.1 provenance
    search_new = retriever.retrieve("PROTOCOL-BETA-CURRENT-888", business_id="biz_proto_1")
    assert len(search_new.chunks) >= 1
    assert "PROTOCOL-BETA-CURRENT-888" in search_new.chunks[0].content
    assert search_new.chunks[0].document_version == "1.1"


def test_cleanup_orphaned_chunks(db_session: Session):
    """
    Verify that cleanup_orphaned_chunks removes chunks not associated with an active document.
    """
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(title="Temporary Manual", business_domain="operations", source="temp.md")
    res = service.ingest_text("## Temp\nTemporary instruction passage.", doc_type="markdown", metadata=meta)

    doc = db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.document_id == res.document_id)
    ).scalar_one()

    # Mark document inactive/superseded manually
    doc.status = "archived"
    db_session.commit()

    # Chunks are now orphaned relative to active documents
    purged_count = service.cleanup_orphaned_chunks()
    assert purged_count >= 1

    remaining = db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
    ).scalars().all()
    assert len(remaining) == 0


def test_tenant_isolation_preserved_across_version_updates(db_session: Session):
    """
    Verify tenant isolation remains strictly enforced across document version increments:
    Tenant B cannot retrieve Tenant A's documents before or after an update.
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()
    retriever = HybridRetriever(db_session, embedding_provider=provider)

    meta_a = DocumentMetadata(title="Tenant A Financials", business_domain="finance", source="fin_a.md")
    service.ingest_text(
        "## Profit Margin\nConfidential EBITDA ratio for Tenant A is 28 percent.",
        doc_type="markdown",
        metadata=meta_a,
        business_id="tenant_secret_alpha",
    )

    # Tenant B queries Tenant A's confidential topic -> 0 results
    res_b_v1 = retriever.retrieve("Confidential EBITDA ratio", business_id="tenant_other_beta")
    assert len(res_b_v1.chunks) == 0

    # Update Tenant A document to v1.1
    service.ingest_text(
        "## Profit Margin\nConfidential EBITDA ratio for Tenant A is updated to 31 percent.",
        doc_type="markdown",
        metadata=meta_a,
        business_id="tenant_secret_alpha",
    )

    # Tenant B queries again -> still 0 results
    res_b_v2 = retriever.retrieve("Confidential EBITDA ratio", business_id="tenant_other_beta")
    assert len(res_b_v2.chunks) == 0

    # Tenant A queries -> succeeds with v1.1 content
    res_a = retriever.retrieve("Confidential EBITDA ratio", business_id="tenant_secret_alpha")
    assert len(res_a.chunks) == 1
    assert "31 percent" in res_a.chunks[0].content
    assert res_a.chunks[0].document_version == "1.1"


def test_reranking_disabled_by_default(db_session: Session):
    """
    Verify that reranking is disabled by default, uses NoOp provider,
    and returns fused candidates without extra rerank modification.
    """
    provider = get_rerank_provider()
    assert isinstance(provider, NoOpRerankProvider)
    assert provider.provider_name == "none"

    retriever = HybridRetriever(db_session)
    assert retriever.rerank_provider.provider_name == "none"


def test_reranker_scoring_and_provenance_preservation(db_session: Session):
    """
    Verify that LocalCrossScorer promotes candidates with exact query phrase matching,
    enriches chunks with rerank_score and rerank_rank, and preserves all provenance fields.
    """
    scorer = LocalCrossScorerRerankProvider()
    assert scorer.provider_name == "local"

    candidates = [
        RetrievedChunk(
            chunk_id="chunk_broad",
            document_id="doc_1",
            document_title="General Catalog",
            source="catalog.md",
            title="General Specs",
            content="Industrial parts for mechanical automation and robotics.",
            similarity=0.85,
            business_domain="inventory",
            retrieval_method="hybrid_rrf",
            chunk_hash="hash_broad_123",
            chunk_index=0,
            document_version="1.2",
            business_id="tenant_x",
            embedding_provider="mock",
            embedding_model="text-embedding-3-small",
            embedding_version="v1",
        ),
        RetrievedChunk(
            chunk_id="chunk_exact",
            document_id="doc_2",
            document_title="Servo Motor Spec",
            source="motors.md",
            title="High Torque Servo",
            content="Specification for Model SKU-SERVO-9000-X high torque servo motor.",
            similarity=0.65,
            business_domain="inventory",
            retrieval_method="hybrid_rrf",
            chunk_hash="hash_exact_456",
            chunk_index=1,
            document_version="2.0",
            business_id="tenant_x",
            embedding_provider="mock",
            embedding_model="text-embedding-3-small",
            embedding_version="v1",
        ),
    ]

    # Query with exact SKU matching the second chunk
    reranked = scorer.rerank("SKU-SERVO-9000-X high torque servo", candidates, top_k=2)
    assert len(reranked) == 2

    # The second chunk should be promoted to rank 1 due to exact SKU + phrase matching
    top_chunk = reranked[0]
    assert top_chunk.chunk_id == "chunk_exact"
    assert top_chunk.rerank_rank == 1
    assert top_chunk.rerank_score is not None
    assert top_chunk.rerank_score > reranked[1].rerank_score

    # Complete provenance preserved
    assert top_chunk.document_id == "doc_2"
    assert top_chunk.document_version == "2.0"
    assert top_chunk.chunk_hash == "hash_exact_456"
    assert top_chunk.business_id == "tenant_x"
    assert top_chunk.embedding_provider == "mock"
    assert top_chunk.embedding_model == "text-embedding-3-small"
    assert top_chunk.embedding_version == "v1"


def test_reranker_deterministic_tie_breaking():
    """
    Verify that when candidate chunks share equal scores, the reranker
    tie-breaks deterministically by (-similarity, document_id, chunk_index).
    """
    scorer = LocalCrossScorerRerankProvider()
    candidates = [
        RetrievedChunk(
            chunk_id="chunk_b",
            document_id="doc_beta",
            document_title="Beta Doc",
            source="beta.md",
            content="Identical matching content passage for tie breaking test.",
            similarity=0.70,
            business_domain="general",
            retrieval_method="hybrid_rrf",
            chunk_index=2,
        ),
        RetrievedChunk(
            chunk_id="chunk_a",
            document_id="doc_alpha",
            document_title="Alpha Doc",
            source="alpha.md",
            content="Identical matching content passage for tie breaking test.",
            similarity=0.70,
            business_domain="general",
            retrieval_method="hybrid_rrf",
            chunk_index=1,
        ),
    ]

    res = scorer.rerank("Identical matching content", candidates, top_k=2)
    assert len(res) == 2
    # doc_alpha should precede doc_beta alphabetically when scores and similarities match
    assert res[0].document_id == "doc_alpha"
    assert res[1].document_id == "doc_beta"


def test_failed_database_write_transaction_rollback(db_session: Session):
    """
    Verify that if a database error occurs during session flush/commit while replacing a document,
    the transaction is rolled back, the previous document remains active, and its chunks remain intact.
    """
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(
        title="Warehouse Inventory SOP",
        business_domain="inventory",
        source="warehouse_sop.md",
    )
    v1_text = "## Bin Storage Allocation\nBins A1 through A10 are reserved for perishable goods."
    res1 = service.ingest_text(v1_text, doc_type="markdown", metadata=meta, business_id="biz_wh_1")
    assert res1.status == "active"

    orig_doc = db_session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.document_id == res1.document_id)
    ).scalar_one()
    orig_chunks = db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == orig_doc.id)
    ).scalars().all()
    assert orig_doc.status == "active"
    assert len(orig_chunks) >= 1

    # Simulate database error during flush of the new document version
    def failing_flush(*args, **kwargs):
        raise SQLAlchemyError("Simulated database write constraint failure")

    with patch.object(db_session, "flush", side_effect=failing_flush):
        v2_text = "## Bin Storage Allocation\nBins B1 through B10 are allocated for hazardous items."
        with pytest.raises(SQLAlchemyError, match="Simulated database write constraint failure"):
            service.ingest_text(v2_text, doc_type="markdown", metadata=meta, business_id="biz_wh_1")

    # Verify original document remains active and original chunks still exist
    db_session.refresh(orig_doc)
    assert orig_doc.status == "active"
    current_chunks = db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == orig_doc.id)
    ).scalars().all()
    assert len(current_chunks) == len(orig_chunks)


def test_concurrent_reingestion_idempotency_and_versioning(db_session: Session):
    """
    Verify that subsequent identical or concurrent re-ingestion requests are idempotent:
    detects matching content hash, avoids duplicate vector calls, and preserves single active version.
    """
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(
        title="Vendor Return Window",
        business_domain="operations",
        source="vendor_returns.md",
    )
    content = "## Vendor Claims\nDefective supplier batches must be reported within 7 business days."

    res1 = service.ingest_text(content, doc_type="markdown", metadata=meta, business_id="biz_vendor_1")
    assert res1.is_duplicate is False
    assert res1.version == "1.0"

    # Concurrent / identical second ingestion
    res2 = service.ingest_text(content, doc_type="markdown", metadata=meta, business_id="biz_vendor_1")
    assert res2.is_duplicate is True
    assert res2.document_id == res1.document_id
    assert res2.version == "1.0"

    # Exactly 1 active document exists in database
    active_docs = db_session.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.source == "vendor_returns.md")
        .where(KnowledgeDocument.business_id == "biz_vendor_1")
        .where(KnowledgeDocument.status == "active")
    ).scalars().all()
    assert len(active_docs) == 1


def test_low_relevance_and_irrelevant_query_filtering(db_session: Session):
    """
    Verify that completely out-of-domain or irrelevant queries are filtered out:
    returns 0 chunks, sets has_sufficient_context=False, confidence_level='none',
    and does not pass weak noise to the caller.
    """
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(
        title="Electronics Manual",
        business_domain="inventory",
        source="electronics.md",
    )
    service.ingest_text(
        "## Lithium Batteries\nSafety handling for 18650 rechargeable battery packs in robotics.",
        doc_type="markdown",
        metadata=meta,
        business_id="biz_elec_1",
    )

    retriever = HybridRetriever(db_session)

    # 1. Completely unrelated out-of-domain query
    irrelevant_res = retriever.retrieve(
        "Quantum gravity string theory holographic principle cosmology",
        business_id="biz_elec_1",
    )
    assert len(irrelevant_res.chunks) == 0
    assert irrelevant_res.has_sufficient_context is False
    assert irrelevant_res.confidence_level == "none"
    assert "below relevance threshold" in irrelevant_res.context_text or "No verified business context" in irrelevant_res.context_text

    # 2. Domain-relevant query
    relevant_res = retriever.retrieve(
        "Lithium batteries safety handling for robotics",
        business_id="biz_elec_1",
    )
    assert len(relevant_res.chunks) >= 1
    assert relevant_res.has_sufficient_context is True
    assert relevant_res.confidence_level == "sufficient"


def test_database_error_telemetry_and_sanitization():
    """
    Verify that database error sanitization strips secrets, passwords, and URLs
    so credentials are never leaked into diagnostics or client responses.
    """
    raw_error_with_creds = (
        "FATAL: password authentication failed for user 'admin' "
        "at postgresql://admin:SuperSecretPass123!@db.internal:5432/nexus_prod "
        "with password=SuperSecretPass123! and token=tok_abc123"
    )
    sanitized = _sanitize_db_error(raw_error_with_creds)
    assert "SuperSecretPass123!" not in sanitized
    assert "tok_abc123" not in sanitized
    assert "://admin:***@" in sanitized
    assert "password=***" in sanitized
    assert "token=***" in sanitized

