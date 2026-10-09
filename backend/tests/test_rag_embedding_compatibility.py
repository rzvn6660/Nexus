"""Focused regression tests for Phase 25C.1: Embedding Compatibility and Tenant-Scope Hardening.

Covers:
1. Strict model, provider, dimension, and version compatibility enforcement.
2. Strict exclusion of legacy chunks with missing (NULL) compatibility metadata.
3. Dimension mismatch pre-validation and actionable errors.
4. Cross-tenant isolation and global document tenant-chunk leakage prevention (GAP-06).
5. Unscoped query protection against private tenant data.
6. Re-embedding workflow for legacy/incompatible chunks.
7. Full provenance retention in RetrievedChunk and RAGEvidence.
"""

from unittest.mock import MagicMock

import pytest
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from app.rag.retrieval.retriever import HybridRetriever
from sqlalchemy.orm import Session


def test_strict_embedding_model_compatibility(db_session: Session):
    """Verify that chunks with mismatched or legacy NULL embedding_model cannot participate in ranking."""
    provider = get_embedding_provider()
    doc = KnowledgeDocument(
        document_id="doc_compat_test",
        business_id="biz_compat_1",
        title="Compatibility Test Doc",
        source="compat.md",
        document_type="markdown",
        content_hash="hash_compat_1",
        status="active",
        version="1.0",
    )
    db_session.add(doc)
    db_session.flush()

    # 1. Matching model chunk
    c_match = KnowledgeChunk(
        document_id=doc.id,
        chunk_id="chk_match",
        chunk_index=0,
        title="Matching Chunk",
        content="Active verified refund policy covers 30 days.",
        embedding=provider.get_embedding("Active verified refund policy covers 30 days."),
        business_id="biz_compat_1",
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        embedding_version=provider.version,
    )
    # 2. Mismatched model chunk (e.g. legacy model)
    c_mismatched = KnowledgeChunk(
        document_id=doc.id,
        chunk_id="chk_mismatched",
        chunk_index=1,
        title="Mismatched Model Chunk",
        content="Old refund policy covers 14 days under legacy model.",
        embedding=provider.get_embedding("Old refund policy covers 14 days under legacy model."),
        business_id="biz_compat_1",
        embedding_provider=provider.provider_name,
        embedding_model="legacy-unsupported-model-v0",
        embedding_dimension=provider.dimension,
        embedding_version=provider.version,
    )
    # 3. Legacy chunk with NULL model (simulating pre-010 migration state)
    c_null_model = KnowledgeChunk(
        document_id=doc.id,
        chunk_id="chk_null_model",
        chunk_index=2,
        title="Legacy Null Model Chunk",
        content="Ancient refund policy with missing model metadata.",
        embedding=provider.get_embedding("Ancient refund policy with missing model metadata."),
        business_id="biz_compat_1",
        embedding_provider=None,
        embedding_model=None,
        embedding_dimension=None,
        embedding_version=None,
    )

    db_session.add_all([c_match, c_mismatched, c_null_model])
    db_session.commit()

    retriever = HybridRetriever(db_session, embedding_provider=provider)
    res = retriever.retrieve("refund policy covers", business_id="biz_compat_1", top_k=5)

    chunk_ids = [c.chunk_id for c in res.chunks]
    assert "chk_match" in chunk_ids
    assert "chk_mismatched" not in chunk_ids
    assert "chk_null_model" not in chunk_ids
    assert res.stale_vectors_excluded >= 2


def test_strict_embedding_provider_and_version_compatibility(db_session: Session):
    """Verify chunks with mismatched provider or version are excluded from similarity ranking."""
    provider = get_embedding_provider()
    doc = KnowledgeDocument(
        document_id="doc_prov_test",
        business_id="biz_prov_1",
        title="Provider Test Doc",
        source="prov.md",
        document_type="markdown",
        content_hash="hash_prov_1",
        status="active",
        version="1.0",
    )
    db_session.add(doc)
    db_session.flush()

    # Mismatched provider
    c_wrong_prov = KnowledgeChunk(
        document_id=doc.id,
        chunk_id="chk_wrong_prov",
        chunk_index=0,
        title="Wrong Provider Chunk",
        content="Wrong provider credit term is strictly 45 days.",
        embedding=provider.get_embedding("Wrong provider credit term is strictly 45 days."),
        business_id="biz_prov_1",
        embedding_provider="foreign_unsupported_provider",
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        embedding_version=provider.version,
    )
    # Mismatched version
    c_wrong_ver = KnowledgeChunk(
        document_id=doc.id,
        chunk_id="chk_wrong_ver",
        chunk_index=1,
        title="Wrong Version Chunk",
        content="Wrong version credit term is strictly 60 days.",
        embedding=provider.get_embedding("Wrong version credit term is strictly 60 days."),
        business_id="biz_prov_1",
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        embedding_version="v0-deprecated",
    )

    db_session.add_all([c_wrong_prov, c_wrong_ver])
    db_session.commit()

    retriever = HybridRetriever(db_session, embedding_provider=provider)
    res = retriever.retrieve("credit term", business_id="biz_prov_1", top_k=5)

    chunk_ids = [c.chunk_id for c in res.chunks]
    assert "chk_wrong_prov" not in chunk_ids
    assert "chk_wrong_ver" not in chunk_ids
    assert res.stale_vectors_excluded >= 2


def test_dimension_validation_rejects_incompatible_query_vector(db_session: Session):
    """Verify dimension mismatch raises an actionable ValueError before database similarity execution."""
    mock_provider = MagicMock()
    mock_provider.dimension = 1536
    mock_provider.provider_name = "mock"
    mock_provider.model_name = "mock-sha256"
    mock_provider.version = "v1"
    # Returns 512 dimensions instead of configured 1536
    mock_provider.get_embedding.return_value = [0.1] * 512

    retriever = HybridRetriever(db_session, embedding_provider=mock_provider)
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        retriever.retrieve("What is our margin?", business_id="biz_1")


def test_dimension_validation_rejects_empty_query_vector(db_session: Session):
    """Verify empty embedding vector raises a controlled ValueError."""
    mock_provider = MagicMock()
    mock_provider.dimension = 1536
    mock_provider.provider_name = "mock"
    mock_provider.model_name = "mock-sha256"
    mock_provider.version = "v1"
    mock_provider.get_embedding.return_value = []

    retriever = HybridRetriever(db_session, embedding_provider=mock_provider)
    with pytest.raises(ValueError, match="Generated query embedding is empty"):
        retriever.retrieve("What is our margin?", business_id="biz_1")


def test_ingestion_dimension_validation(db_session: Session):
    """Verify ingestion service rejects vectors whose dimension does not match active provider."""
    mock_provider = MagicMock()
    mock_provider.dimension = 1536
    mock_provider.provider_name = "mock"
    mock_provider.model_name = "mock-sha256"
    mock_provider.version = "v1"
    # Returns 768-dim embeddings instead of 1536
    mock_provider.get_embeddings.return_value = [[0.05] * 768]

    service = DocumentIngestionService(db_session)
    service.embedding_provider = mock_provider

    meta = DocumentMetadata(title="Test Dim Doc", business_domain="finance", source="dim.md")
    with pytest.raises(ValueError, match="Embedding dimension mismatch during ingestion"):
        service.ingest_text("## Rule\nSome text.", "markdown", meta, business_id="biz_dim")


def test_cross_tenant_isolation_global_document_tenant_chunk_leak_blocked(db_session: Session):
    """
    CRITICAL SECURITY REGRESSION TEST (GAP-06):
    If a document is marked is_global=True, but a chunk within it is tagged with a tenant business_id,
    another tenant querying the system must NEVER be able to retrieve that tenant chunk.
    """
    provider = get_embedding_provider()

    # 1. Global Document
    doc_global = KnowledgeDocument(
        document_id="doc_global_governance",
        title="Global Enterprise Governance Framework",
        source="governance.md",
        document_type="markdown",
        business_domain="finance",
        business_id=None,
        is_global=True,
        content_hash="hash_global_gov",
        status="active",
        version="1.0",
    )
    db_session.add(doc_global)
    db_session.flush()

    # 2. Chunk A: Belongs to victim tenant (e.g. injected or corrupted under global doc)
    content_victim = "Alpha Corp confidential executive bonus pool is capped at 12%."
    chunk_victim = KnowledgeChunk(
        document_id=doc_global.id,
        chunk_id="chk_victim_bonus",
        chunk_index=0,
        title="Bonus Pool Cap",
        content=content_victim,
        embedding=provider.get_embedding(content_victim),
        business_id="biz_victim_corp",
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        embedding_version=provider.version,
    )

    # 3. Chunk B: Genuinely public global chunk
    content_public = "Standard retail fiscal year runs from February 1 to January 31."
    chunk_public = KnowledgeChunk(
        document_id=doc_global.id,
        chunk_id="chk_public_fiscal",
        chunk_index=1,
        title="Fiscal Year Standard",
        content=content_public,
        embedding=provider.get_embedding(content_public),
        business_id=None,
        embedding_provider=provider.provider_name,
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        embedding_version=provider.version,
    )

    db_session.add_all([chunk_victim, chunk_public])
    db_session.commit()

    retriever = HybridRetriever(db_session, embedding_provider=provider)

    # Attacker queries with their own business_id
    attacker_res = retriever.retrieve(
        "executive bonus pool cap",
        business_id="biz_attacker_corp",
        top_k=5,
    )

    attacker_chunk_ids = [c.chunk_id for c in attacker_res.chunks]
    # Attacker must NOT retrieve the victim's chunk, even though the parent document is is_global=True!
    assert "chk_victim_bonus" not in attacker_chunk_ids
    assert "bonus pool" not in attacker_res.context_text.lower()

    # But victim CAN retrieve their own chunk
    victim_res = retriever.retrieve(
        "executive bonus pool cap",
        business_id="biz_victim_corp",
        top_k=5,
    )
    victim_chunk_ids = [c.chunk_id for c in victim_res.chunks]
    assert "chk_victim_bonus" in victim_chunk_ids
    assert "bonus pool" in victim_res.context_text.lower()

    # Attacker CAN retrieve genuinely public global chunk
    public_res = retriever.retrieve(
        "standard retail fiscal year",
        business_id="biz_attacker_corp",
        top_k=5,
    )
    public_chunk_ids = [c.chunk_id for c in public_res.chunks]
    assert "chk_public_fiscal" in public_chunk_ids


def test_unscoped_query_cannot_see_private_tenant_chunks(db_session: Session):
    """Verify unscoped query (business_id=None) cannot access private tenant knowledge."""
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(title="Secret Strategy", business_domain="finance", source="secret.md")
    service.ingest_text(
        "## Top Secret\nOur secret acquisition target is Company XYZ for $5M.",
        "markdown",
        meta,
        business_id="biz_private_acq",
    )

    retriever = HybridRetriever(db_session)
    unscoped_res = retriever.retrieve("secret acquisition target", business_id=None, top_k=5)

    assert len(unscoped_res.chunks) == 0
    assert "Company XYZ" not in unscoped_res.context_text


def test_reembed_incompatible_chunks_workflow(db_session: Session):
    """Verify reembed_incompatible_chunks brings legacy or mismatched chunks into active compliance."""
    provider = get_embedding_provider()
    doc = KnowledgeDocument(
        document_id="doc_reembed_test",
        business_id="biz_reembed_1",
        title="Re-embedding Test Document",
        source="reembed.md",
        document_type="markdown",
        content_hash="hash_reembed_1",
        status="active",
        version="1.0",
    )
    db_session.add(doc)
    db_session.flush()

    # Legacy chunk with missing model metadata
    chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_id="chk_reembed_target",
        chunk_index=0,
        title="Warranty Policy",
        content="Standard commercial warranty covers defects for 24 months nationwide.",
        embedding=[0.01] * provider.dimension,
        business_id="biz_reembed_1",
        embedding_provider=None,
        embedding_model=None,
        embedding_dimension=None,
        embedding_version=None,
    )
    db_session.add(chunk)
    db_session.commit()

    retriever = HybridRetriever(db_session, embedding_provider=provider)

    # 1. Before re-embedding: chunk is excluded because metadata is missing
    res_before = retriever.retrieve(
        "commercial warranty defects", business_id="biz_reembed_1", top_k=3
    )
    assert len(res_before.chunks) == 0
    assert res_before.stale_vectors_excluded >= 1

    # 2. Run re-embedding service
    ingestion_service = DocumentIngestionService(db_session)
    report = ingestion_service.reembed_incompatible_chunks(business_id="biz_reembed_1")
    assert report["reembedded"] >= 1
    assert report["model"] == provider.model_name

    # 3. After re-embedding: chunk has active metadata and is successfully retrieved
    res_after = retriever.retrieve(
        "commercial warranty defects", business_id="biz_reembed_1", top_k=3
    )
    assert len(res_after.chunks) >= 1
    assert res_after.chunks[0].chunk_id == "chk_reembed_target"
    assert "24 months" in res_after.context_text


def test_provenance_preserves_full_compatibility_metadata(db_session: Session):
    """Verify that retrieved context and evidence retain complete provenance and lineage metadata."""
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(
        title="Provenance Test Doc",
        business_domain="finance",
        version="2.5",
        source="provenance.md",
    )
    ingestion_res = service.ingest_text(
        "## Inventory Depreciation\nInventory older than 180 days is depreciated by 50% quarterly.",
        "markdown",
        meta,
        business_id="biz_provenance_99",
    )
    assert ingestion_res.chunks_created == 1

    retriever = HybridRetriever(db_session)
    res = retriever.retrieve(
        "inventory depreciation older than 180 days", business_id="biz_provenance_99", top_k=1
    )

    assert len(res.chunks) == 1
    chunk = res.chunks[0]
    assert chunk.document_version == "2.5"
    assert chunk.business_id == "biz_provenance_99"
    assert chunk.embedding_provider == retriever.embedding_provider.provider_name
    assert chunk.embedding_model == retriever.embedding_provider.model_name
    assert chunk.embedding_version == retriever.embedding_provider.version
    assert chunk.chunk_hash is not None
    assert len(chunk.chunk_hash) == 64
    assert chunk.chunk_index == 0

    assert len(res.evidence) == 1
    evidence = res.evidence[0]
    assert evidence.document_version == "2.5"
    assert evidence.business_id == "biz_provenance_99"
    assert evidence.embedding_provider == retriever.embedding_provider.provider_name
    assert evidence.embedding_model == retriever.embedding_provider.model_name
    assert evidence.embedding_version == retriever.embedding_provider.version
    assert evidence.chunk_hash == chunk.chunk_hash
    assert evidence.chunk_index == 0


def test_unknown_legacy_vector_provenance_never_falsely_labeled_or_retrieved(db_session: Session):
    """Verify that unknown legacy vectors (missing model/provider) are never falsely labeled as OpenAI

    or active provider, and remain strictly excluded from retrieval until truthfully re-embedded.
    """
    provider = get_embedding_provider()
    doc = KnowledgeDocument(
        document_id="doc_legacy_unknown",
        business_id="biz_unknown_prov_1",
        title="Legacy Unknown Vector Document",
        source="legacy.md",
        document_type="markdown",
        content_hash="hash_legacy_unknown",
        status="active",
        version="1.0",
    )
    db_session.add(doc)
    db_session.flush()

    # Legacy chunk with arbitrary vector and completely unknown metadata
    chunk_legacy = KnowledgeChunk(
        document_id=doc.id,
        chunk_id="chk_legacy_unknown",
        chunk_index=0,
        title="Legacy Unlabeled Section",
        content="Arbitrary text with unrecorded embedding provider and model provenance.",
        embedding=[0.0123] * provider.dimension,
        business_id="biz_unknown_prov_1",
        embedding_provider=None,
        embedding_model=None,
        embedding_dimension=None,
        embedding_version=None,
    )
    db_session.add(chunk_legacy)
    db_session.commit()

    # Verify database state: no false labeling occurred
    db_session.refresh(chunk_legacy)
    assert chunk_legacy.embedding_provider is None
    assert chunk_legacy.embedding_model is None
    assert chunk_legacy.embedding_version is None
    assert chunk_legacy.embedding_dimension is None

    # Verify retrieval strictly excludes this unknown vector
    retriever = HybridRetriever(db_session, embedding_provider=provider)
    res = retriever.retrieve(
        "Arbitrary text unrecorded embedding",
        business_id="biz_unknown_prov_1",
        top_k=5,
    )
    assert len(res.chunks) == 0
    assert res.stale_vectors_excluded >= 1

    # Verify re-embedding legitimately updates metadata only when fresh vectors are calculated
    ingestion_service = DocumentIngestionService(db_session, embedding_provider=provider)
    reembed_report = ingestion_service.reembed_incompatible_chunks(business_id="biz_unknown_prov_1")
    assert reembed_report["scanned"] == 1
    assert reembed_report["reembedded"] == 1

    # Verify chunk now truthfully reflects the provider that calculated the fresh embeddings
    db_session.refresh(chunk_legacy)
    assert chunk_legacy.embedding_provider == provider.provider_name
    assert chunk_legacy.embedding_model == provider.model_name
    assert chunk_legacy.embedding_dimension == provider.dimension
    assert chunk_legacy.embedding_version == provider.version
    assert chunk_legacy.chunk_hash is not None
