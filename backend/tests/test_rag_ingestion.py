"""Tests for Document Ingestion, Chunking, Extraction, and Deduplication."""

import pytest
from app.models.knowledge import KnowledgeDocument
from app.rag.ingestion.chunking import TextChunker
from app.rag.ingestion.extractors import DocumentExtractor, sanitize_filename
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_markdown_header_aware_chunking():
    """Verify chunker extracts sections based on markdown headers."""
    sample_md = """# Business Policy Overview
This is introductory content.

## Gross Margin Definition
Gross margin is calculated as (Gross Profit / Net Revenue) * 100.
It reflects core product efficiency.

## Reorder Policy
Safety stock reorder threshold is triggered at 20 units.
"""
    chunker = TextChunker(chunk_size=500)
    chunks = chunker.chunk_markdown(sample_md, business_domain="finance")

    assert len(chunks) >= 2
    titles = [c.title for c in chunks]
    assert any("Gross Margin Definition" in t for t in titles)
    assert any("Reorder Policy" in t for t in titles)


def test_plain_text_chunking():
    """Verify chunker handles unstructured plain text."""
    sample_text = "Paragraph 1 describing customer tiers.\n\nParagraph 2 describing retention rules."
    chunker = TextChunker(chunk_size=100)
    chunks = chunker.chunk_text(sample_text, title="Customer Guide", business_domain="customer")
    assert len(chunks) >= 1
    assert all(c.business_domain == "customer" for c in chunks)


def test_document_extractor_and_filename_sanitizer():
    """Verify safe filename sanitization and text extraction."""
    # Test path traversal sanitization
    dirty_name = "../../../var/secret/sales_policy.md"
    clean = sanitize_filename(dirty_name)
    assert "/" not in clean and "\\" not in clean
    assert ".." not in clean
    assert clean == "sales_policy.md"

    # Test markdown extraction
    md_bytes = b"# Sample Policy\nThis is sample content."
    text, doc_type = DocumentExtractor.extract_text_and_type(md_bytes, "policy.md")
    assert doc_type == "markdown"
    assert "Sample Policy" in text

    # Test unsupported extension rejection
    with pytest.raises(ValueError, match="Unsupported document format"):
        DocumentExtractor.extract_text_and_type(b"binary", "malicious.exe")


def test_document_ingestion_service_and_deduplication(db_session: Session):
    """Verify transactional document ingestion and content-hash deduplication."""
    service = DocumentIngestionService(db_session)
    meta = DocumentMetadata(
        title="Sample Retail Guide",
        business_domain="finance",
        version="1.0",
        source="test_runner",
        tags=["retail", "finance"],
    )

    doc_text = """## Revenue Policy
Net revenue is gross sales less promotional discounts and customer returns.

## COGS Definition
Direct unit acquisition cost evaluated across inventory items.
"""
    # 1. Ingest first time
    result1 = service.ingest_text(doc_text, doc_type="markdown", metadata=meta)
    assert result1.is_duplicate is False
    assert result1.chunks_created >= 2
    assert result1.document_id.startswith("doc_")

    # Verify database records
    doc_record = db_session.query(KnowledgeDocument).filter_by(document_id=result1.document_id).first()
    assert doc_record is not None
    assert len(doc_record.chunks) == result1.chunks_created

    # 2. Ingest duplicate identical text
    result2 = service.ingest_text(doc_text, doc_type="markdown", metadata=meta)
    assert result2.is_duplicate is True
    assert result2.document_id == result1.document_id
    assert result2.content_hash == result1.content_hash


def test_api_knowledge_endpoints(api_client: TestClient):
    """Test Knowledge REST API ingestion, listing, and retrieval."""
    # Ingest text document
    payload = {
        "title": "Inventory Management Standard",
        "content": "## Reorder Level\nItems below reorder point are flagged immediately for replenishment.",
        "document_type": "markdown",
        "business_domain": "inventory",
        "version": "1.1",
        "tags": ["stock", "warehouse"],
    }
    resp = api_client.post("/api/v1/knowledge/documents/text", json=payload)
    assert resp.status_code == 201
    doc_data = resp.json()
    doc_id = doc_data["document_id"]
    assert doc_data["title"] == "Inventory Management Standard"

    # List documents
    resp_list = api_client.get("/api/v1/knowledge/documents")
    assert resp_list.status_code == 200
    docs = resp_list.json()
    assert any(d["document_id"] == doc_id for d in docs)

    # Get single document with chunks
    resp_single = api_client.get(f"/api/v1/knowledge/documents/{doc_id}")
    assert resp_single.status_code == 200
    detail = resp_single.json()
    assert detail["document_id"] == doc_id
    assert len(detail["chunks"]) >= 1
