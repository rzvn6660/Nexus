"""Comprehensive regression and integration tests for Phase 25C.2: Hybrid Retrieval & Rank Fusion.

Covers:
1. Independent dense and lexical candidate generation (lexical discovery of non-dense candidates).
2. Exact alphanumeric SKU and acronym retrieval where lexical search excels.
3. Paraphrased semantic query retrieval where dense search excels.
4. Reciprocal Rank Fusion (RRF) score computation and rank promotion.
5. Deterministic tie-breaking.
6. Tenant and business scope isolation in lexical and fused candidate paths (zero cross-tenant leakage).
7. Empty, whitespace, punctuation-heavy, and no-match query safety.
8. Multilingual evaluation: English, Malayalam native script, Manglish transliteration, and mixed language.
9. Structured diagnostics telemetry and lack of sensitive business content leakage.
10. Fallback mechanics when PostgreSQL FTS or lexical search triggers error recovery.
"""

from unittest.mock import MagicMock

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from app.rag.retrieval.models import RetrievedContext
from app.rag.retrieval.retriever import HybridRetriever
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def test_independent_lexical_candidate_generation_discovers_sku(db_session: Session):
    """
    Verify that an exact alphanumeric SKU (e.g., 'SKU-ELECTRO-8842-X') is discovered
    via lexical search even if its dense embedding vector score is low.
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()

    meta = DocumentMetadata(
        title="Warehouse Inventory Sheet",
        business_domain="inventory",
        source="warehouse_inv.md",
    )
    service.ingest_text(
        "## Industrial Motor Assembly\nModel SKU-ELECTRO-8842-X has a critical restock threshold of 12 units.",
        doc_type="markdown",
        metadata=meta,
        business_id="biz_sku_test",
    )

    retriever = HybridRetriever(db_session, embedding_provider=provider)
    res = retriever.retrieve("SKU-ELECTRO-8842-X", business_id="biz_sku_test", top_k=3)

    assert len(res.chunks) >= 1
    found_chunk = res.chunks[0]
    assert "SKU-ELECTRO-8842-X" in found_chunk.content
    assert found_chunk.retrieval_method in ("hybrid_rrf", "lexical_only")
    assert found_chunk.metadata_json.get("lexical_rank") == 1
    assert res.diagnostics.lexical_candidates_count >= 1


def test_paraphrased_semantic_query_retrieval(db_session: Session):
    """
    Verify that a paraphrased semantic question where exact lexical words do not match
    is successfully discovered via dense vector search.
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()

    meta = DocumentMetadata(
        title="Commercial Contracts Guideline",
        business_domain="sales",
        source="contracts.md",
    )
    service.ingest_text(
        "## Client Cancellation Window\nClients may revoke purchase agreements within thirty solar days without pecuniary forfeiture.",
        doc_type="markdown",
        metadata=meta,
        business_id="biz_semantic_test",
    )

    retriever = HybridRetriever(db_session, embedding_provider=provider)
    res = retriever.retrieve(
        "What is the allowable period to back out of a deal?",
        business_id="biz_semantic_test",
        top_k=3,
        similarity_threshold=0.01,
    )

    assert len(res.chunks) >= 1
    assert "thirty solar days" in res.chunks[0].content


def test_reciprocal_rank_fusion_score_calculation_and_promotion(db_session: Session):
    """
    Verify that a chunk matching both dense and lexical modalities receives an RRF score
    that is strictly higher than single-modality chunks, promoting it to top rank.
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()

    # Doc 1: Matches both dense context and exact keyword
    service.ingest_text(
        "## High Value Refund Protocol\nEmergency refunds for VIP corporate accounts must be wired within 4 hours.",
        doc_type="markdown",
        metadata=DocumentMetadata(title="VIP Policy", business_domain="finance"),
        business_id="biz_rrf_1",
    )
    # Doc 2: Generic refund policy
    service.ingest_text(
        "## Standard Policy\nRegular retail refunds require proof of receipt within 30 days.",
        doc_type="markdown",
        metadata=DocumentMetadata(title="Retail Policy", business_domain="finance"),
        business_id="biz_rrf_1",
    )

    retriever = HybridRetriever(db_session, embedding_provider=provider)
    res = retriever.retrieve("VIP corporate accounts refunds", business_id="biz_rrf_1", top_k=2)

    assert len(res.chunks) >= 2
    top_chunk = res.chunks[0]
    assert "VIP corporate accounts" in top_chunk.content
    assert top_chunk.retrieval_method == "hybrid_rrf"
    assert top_chunk.metadata_json["dense_rank"] is not None
    assert top_chunk.metadata_json["lexical_rank"] is not None
    assert top_chunk.similarity > 0.0


def test_deterministic_tie_breaking_order(db_session: Session):
    """
    Verify that when two candidate chunks have identical RRF scores, deterministic tie-breaking
    orders by (-rrf_score, -dense_score, -lexical_score, doc.document_id, chunk.chunk_index).
    """
    doc_a = KnowledgeDocument(
        document_id="doc_tie_aaa",
        business_id="biz_tie",
        title="Document A",
        source="a.md",
        document_type="markdown",
        content_hash="hash_a",
        status="active",
        version="1.0",
    )
    doc_b = KnowledgeDocument(
        document_id="doc_tie_bbb",
        business_id="biz_tie",
        title="Document B",
        source="b.md",
        document_type="markdown",
        content_hash="hash_b",
        status="active",
        version="1.0",
    )
    db_session.add_all([doc_a, doc_b])
    db_session.flush()

    provider = get_embedding_provider()
    shared_vector = provider.get_embedding("Deterministic tie breaking identical content")

    chunk_a = KnowledgeChunk(
        document_id=doc_a.id,
        chunk_id="chk_tie_1",
        chunk_index=0,
        title="Section A",
        content="Deterministic tie breaking identical content for chunk A.",
        embedding=shared_vector,
        business_id="biz_tie",
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        embedding_version=provider.version,
    )
    chunk_b = KnowledgeChunk(
        document_id=doc_b.id,
        chunk_id="chk_tie_2",
        chunk_index=0,
        title="Section B",
        content="Deterministic tie breaking identical content for chunk B.",
        embedding=shared_vector,
        business_id="biz_tie",
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        embedding_version=provider.version,
    )
    db_session.add_all([chunk_a, chunk_b])
    db_session.commit()

    retriever = HybridRetriever(db_session, embedding_provider=provider)
    res1 = retriever.retrieve("Deterministic tie breaking", business_id="biz_tie", top_k=2)
    res2 = retriever.retrieve("Deterministic tie breaking", business_id="biz_tie", top_k=2)

    # Both executions must yield identical ordering
    chunk_ids_1 = [c.chunk_id for c in res1.chunks]
    chunk_ids_2 = [c.chunk_id for c in res2.chunks]
    assert chunk_ids_1 == chunk_ids_2
    assert chunk_ids_1[0] == "chk_tie_1"  # doc_tie_aaa < doc_tie_bbb alphabetically


def test_lexical_and_fused_cross_tenant_isolation(db_session: Session):
    """
    Verify that tenant B can NEVER retrieve tenant A's private SKU or text,
    even when performing exact keyword lexical queries.
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()

    # Ingest confidential SKU for Tenant A
    service.ingest_text(
        "## Proprietary Formula\nSecret reactant CODE-RED-SECRET-99 is restricted to Tenant A operations.",
        doc_type="markdown",
        metadata=DocumentMetadata(title="Tenant A Secret", business_domain="finance"),
        business_id="tenant_alpha_01",
    )

    retriever = HybridRetriever(db_session, embedding_provider=provider)

    # Tenant B queries exact code
    res_b = retriever.retrieve("CODE-RED-SECRET-99", business_id="tenant_beta_02", top_k=5)
    assert len(res_b.chunks) == 0
    assert len(res_b.evidence) == 0

    # Unscoped query queries exact code
    res_unscoped = retriever.retrieve("CODE-RED-SECRET-99", business_id=None, top_k=5)
    assert len(res_unscoped.chunks) == 0

    # Tenant A queries exact code and succeeds
    res_a = retriever.retrieve("CODE-RED-SECRET-99", business_id="tenant_alpha_01", top_k=5)
    assert len(res_a.chunks) == 1
    assert res_a.chunks[0].business_id == "tenant_alpha_01"


def test_punctuation_heavy_and_empty_query_safety(db_session: Session):
    """
    Verify that empty queries, whitespace, punctuation-only queries, and no-match queries
    are handled safely without crashing.
    """
    retriever = HybridRetriever(db_session)

    # 1. Whitespace / empty query
    res_empty = retriever.retrieve("   ")
    assert isinstance(res_empty, RetrievedContext)
    assert res_empty.retrieval_method == "none"
    assert len(res_empty.chunks) == 0

    # 2. Punctuation-heavy query
    res_punct = retriever.retrieve("!@#$%^&*()_+-=[]{}|;':,.<>?/")
    assert isinstance(res_punct, RetrievedContext)

    # 3. No match query
    res_nomatch = retriever.retrieve(
        "Quantum mechanics astrophysics dark matter singularity 99999999",
        business_id="biz_none",
        top_k=3,
    )
    assert len(res_nomatch.chunks) == 0
    assert res_nomatch.retrieval_method == "none"


def test_multilingual_malayalam_manglish_and_mixed_content(db_session: Session):
    """
    Verify lexical search and BM25 tokenization behavior for:
    - English
    - Malayalam native script (ലാഭം)
    - Manglish transliteration (labham)
    - Mixed-language phrases
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()

    # 1. Malayalam native script document
    service.ingest_text(
        "## ലാഭം കണക്കാക്കൽ\nറീട്ടെയിൽ ബിസിനസ്സിൽ ലാഭം കണക്കാക്കുന്നത് മൊത്തം വില്പനയിൽ നിന്നും ചെലവ് കുറച്ചാണ്.",
        doc_type="markdown",
        metadata=DocumentMetadata(title="Malayalam Doc", business_domain="finance"),
        business_id="biz_multi_1",
    )

    # 2. Manglish transliteration document
    service.ingest_text(
        "## Vilpana Niyamangal\nVilpana kooduthal ulla masangalil minimum profit margin 35 percent aayirikkum.",
        doc_type="markdown",
        metadata=DocumentMetadata(title="Manglish Doc", business_domain="sales"),
        business_id="biz_multi_1",
    )

    # 3. Mixed language document
    service.ingest_text(
        "## Hybrid Policy SKU-KL-402\nRetail Margin (ലാഭം) for product SKU-KL-402 is strictly monitored.",
        doc_type="markdown",
        metadata=DocumentMetadata(title="Mixed Doc", business_domain="finance"),
        business_id="biz_multi_1",
    )

    retriever = HybridRetriever(db_session, embedding_provider=provider)

    # Query 1: Malayalam native term
    res_ml = retriever.retrieve("ലാഭം", business_id="biz_multi_1", top_k=2)
    assert len(res_ml.chunks) >= 1
    assert any("ലാഭം" in c.content for c in res_ml.chunks)

    # Query 2: Manglish term
    res_manglish = retriever.retrieve("vilpana", business_id="biz_multi_1", top_k=2)
    assert len(res_manglish.chunks) >= 1
    assert any("vilpana" in c.content.lower() for c in res_manglish.chunks)

    # Query 3: Mixed term with SKU
    res_mixed = retriever.retrieve("SKU-KL-402", business_id="biz_multi_1", top_k=2)
    assert len(res_mixed.chunks) >= 1
    assert any("SKU-KL-402" in c.content for c in res_mixed.chunks)


def test_structured_retrieval_diagnostics_no_sensitive_leakage(db_session: Session):
    """
    Verify structured retrieval diagnostics provide telemetry counts and latencies
    without logging or recording sensitive business text passages.
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()

    service.ingest_text(
        "## Classified Financial Vault\nSecret dividend formula D_VAL_883 equals 15 percent of quarterly earnings.",
        doc_type="markdown",
        metadata=DocumentMetadata(title="Vault", business_domain="finance"),
        business_id="biz_diag_test",
    )

    retriever = HybridRetriever(db_session, embedding_provider=provider)
    res = retriever.retrieve("dividend formula D_VAL_883", business_id="biz_diag_test", top_k=1)

    diag = res.diagnostics
    assert diag is not None
    assert diag.dense_candidates_count >= 1
    assert diag.lexical_candidates_count >= 1
    assert diag.fused_candidates_count >= 1
    assert diag.fusion_method in ("rrf", "linear")
    assert diag.lexical_engine in ("postgresql_fts", "sqlite_bm25_fallback")
    assert diag.dense_latency_ms >= 0.0
    assert diag.lexical_latency_ms >= 0.0
    assert diag.fusion_latency_ms >= 0.0

    # Ensure no confidential business tokens in diagnostics
    diag_str = str(diag.model_dump())
    assert "D_VAL_883" not in diag_str
    assert "Classified Financial Vault" not in diag_str


def test_lexical_fallback_recovery_on_database_error(db_session: Session):
    """
    Verify that if lexical PostgreSQL execution raises an operational error,
    the retriever safely recovers via fallback without crashing the query.
    """
    service = DocumentIngestionService(db_session)
    provider = get_embedding_provider()

    service.ingest_text(
        "## Operational Resilience Policy\nDisaster recovery protocols execute in under 15 minutes.",
        doc_type="markdown",
        metadata=DocumentMetadata(title="Disaster Recovery", business_domain="operations"),
        business_id="biz_fallback_test",
    )

    retriever = HybridRetriever(db_session, embedding_provider=provider)

    # Simulate dialect = postgresql with broken session execute to trigger OperationalError
    mock_session = MagicMock()
    mock_session.bind.dialect.name = "postgresql"
    # First call is dense/FTS query which fails with OperationalError; subsequent calls fallback to db_session
    mock_session.execute.side_effect = [
        OperationalError("syntax error in tsquery", {}, None),
        db_session.execute(
            select(KnowledgeChunk, KnowledgeDocument).join(
                KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id
            )
        ),
    ]

    retriever.session = mock_session
    _candidates, _engine, is_fallback, latency, db_error = (
        retriever._generate_lexical_candidates(
            query="Disaster recovery protocols",
            domain=None,
            candidate_k=5,
            business_id="biz_fallback_test",
        )
    )

    # Should safely isolate, rollback the aborted transaction, and record the error
    assert is_fallback is True
    assert mock_session.rollback.called is True
    assert db_error is not None
    assert "syntax error" in db_error
    assert latency >= 0.0
