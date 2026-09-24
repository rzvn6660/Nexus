"""Tests for Hybrid Retrieval, Provenance Evidence, and Conflict Detection."""

from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from app.rag.retrieval.models import RetrievedContext
from app.rag.retrieval.retriever import HybridRetriever
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_hybrid_retrieval_exact_kpi_match(db_session: Session):
    """Verify retriever provides verified definition from KPI ontology when no docs are stored."""
    retriever = HybridRetriever(db_session)
    result = retriever.retrieve("What does gross margin mean?")

    assert isinstance(result, RetrievedContext)
    assert result.resolved_kpi_canonical == "gross_margin"
    assert result.retrieval_method == "exact_kpi_match"
    assert len(result.evidence) >= 1
    assert result.evidence[0].source == "system_kpi_ontology"
    assert "Gross Margin" in result.context_text


def test_hybrid_retrieval_vector_search_over_documents(db_session: Session):
    """Verify retriever finds relevant document chunks via vector similarity."""
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(
        title="Sales Policy Manual",
        business_domain="sales",
        version="1.0",
        source="sales_policy.md",
    )
    service.ingest_text(
        "## Return Policy\nReturns must be processed within 30 days to adjust recognized net sales.",
        doc_type="markdown",
        metadata=meta,
    )

    retriever = HybridRetriever(db_session)
    res = retriever.retrieve("What is the return policy window?", top_k=2)

    assert len(res.chunks) >= 1
    assert any("Return Policy" in c.title for c in res.chunks if c.title)
    assert len(res.evidence) >= 1
    assert res.evidence[0].similarity_score > 0.0


def test_retrieval_metadata_domain_filtering(db_session: Session):
    """Verify domain filter restricts retrieval to specified business domain."""
    service = DocumentIngestionService(db_session)

    meta_fin = DocumentMetadata(title="Finance Doc", business_domain="finance")
    service.ingest_text("## OPEX Rules\nOperating expenses include administrative and logistics costs.", "markdown", meta_fin)

    meta_inv = DocumentMetadata(title="Inventory Doc", business_domain="inventory")
    service.ingest_text("## Safety Stock\nMinimum safety stock is maintained at 50 units.", "markdown", meta_inv)

    retriever = HybridRetriever(db_session)

    # Search with inventory domain filter
    res_inv = retriever.retrieve("operating expenses and safety stock", business_domain="inventory")
    for chunk in res_inv.chunks:
        assert chunk.business_domain == "inventory"


def test_conflict_detection_across_documents(db_session: Session):
    """Verify conflict detection surfaces when two active documents define thresholds differently."""
    service = DocumentIngestionService(db_session)

    meta1 = DocumentMetadata(title="Old Customer Guide", business_domain="customer")
    service.ingest_text("## Repeat Customer\nA repeat customer is defined as having at least 2 orders.", "markdown", meta1)

    meta2 = DocumentMetadata(title="New Enterprise Policy", business_domain="customer")
    service.ingest_text("## Repeat Customer Tier\nA repeat customer is defined as having 3 orders or more.", "markdown", meta2)

    retriever = HybridRetriever(db_session)
    res = retriever.retrieve("repeat customer definition")

    assert res.has_conflict is True
    assert res.conflict_description is not None
    assert "differently" in res.conflict_description.lower()


def test_empty_query_handling(db_session: Session):
    """Verify empty or whitespace query returns graceful empty context."""
    retriever = HybridRetriever(db_session)
    res = retriever.retrieve("   ")
    assert res.retrieval_method == "none"
    assert len(res.chunks) == 0
    assert len(res.evidence) == 0


def test_api_knowledge_search(api_client: TestClient):
    """Test POST /api/v1/knowledge/search endpoint."""
    resp = api_client.post(
        "/api/v1/knowledge/search",
        json={"query": "gross revenue definition", "top_k": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "query" in data
    assert "chunks" in data
    assert "evidence" in data
