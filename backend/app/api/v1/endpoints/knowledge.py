"""API endpoints for Business Context Knowledge Documents and Hybrid RAG retrieval."""

import json

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    get_optional_current_user,
    verify_user_business_access,
    verify_user_document_access,
)
from app.core.database import get_db
from app.models.knowledge import KnowledgeDocument
from app.models.tenant import UserIdentity
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from app.rag.retrieval.retriever import HybridRetriever
from app.schemas.knowledge import (
    ChunkResponse,
    DocumentDetailResponse,
    DocumentSummaryResponse,
    DocumentTextIngestRequest,
    DocumentUploadResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)

router = APIRouter()


@router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a business context document (Markdown, TXT, PDF)",
    description="Ingests a business document, chunks it into semantic sections, computes embeddings, and indexes for RAG.",
)
async def upload_document(
    file: UploadFile = File(..., description="Business context document file (.md, .txt, .pdf)"),
    title: str | None = Form(None, description="Human-readable title (defaults to filename)"),
    business_domain: str = Form("general", description="Functional domain (finance, sales, inventory, customer)"),
    version: str = Form("1.0", description="Document revision version"),
    tags: str | None = Form(None, description="Comma-separated or JSON list of tags"),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload and index a business context document file."""
    if x_business_id:
        verify_user_business_access(db, current_user, x_business_id, action="upload documents to")
    file_bytes = await file.read()
    from app.security import sanitize_filename
    filename = sanitize_filename(file.filename)
    doc_title = title or filename

    parsed_tags: list[str] = []
    if tags:
        try:
            parsed = json.loads(tags)
            if isinstance(parsed, list):
                parsed_tags = [str(t) for t in parsed]
            else:
                parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
        except (json.JSONDecodeError, ValueError, TypeError):
            parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

    metadata = DocumentMetadata(
        title=doc_title,
        business_domain=business_domain,
        version=version,
        source=filename,
        tags=parsed_tags,
    )

    service = DocumentIngestionService(db)
    try:
        result = service.ingest_file(
            file_bytes=file_bytes,
            filename=filename,
            metadata=metadata,
            business_id=x_business_id,
        )
        return DocumentUploadResponse.model_validate(result.model_dump())
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except (RuntimeError, OSError) as ex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document ingestion failed: {ex}",
        )


@router.post(
    "/documents/text",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest raw text or markdown business documentation",
)
def ingest_text_document(
    payload: DocumentTextIngestRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """Directly ingest a markdown or text document payload."""
    if x_business_id:
        verify_user_business_access(db, current_user, x_business_id, action="ingest text into")

    metadata = DocumentMetadata(
        title=payload.title,
        business_domain=payload.business_domain,
        version=payload.version,
        source=payload.source or "api_text",
        tags=payload.tags,
    )

    service = DocumentIngestionService(db)
    try:
        result = service.ingest_text(
            text=payload.content,
            doc_type=payload.document_type,
            metadata=metadata,
            business_id=x_business_id,
        )
        return DocumentUploadResponse.model_validate(result.model_dump())
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except (RuntimeError, OSError) as ex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Text ingestion failed: {ex}",
        )


@router.get(
    "/documents",
    response_model=list[DocumentSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List all indexed business context documents",
)
def list_documents(
    domain: str | None = None,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentSummaryResponse]:
    """Retrieve summaries of all active registered knowledge documents."""
    if x_business_id:
        verify_user_business_access(db, current_user, x_business_id, action="list documents of")

    stmt = select(KnowledgeDocument).where(KnowledgeDocument.status == "active")
    if x_business_id is not None:
        stmt = stmt.where(
            (KnowledgeDocument.business_id == x_business_id) | (KnowledgeDocument.is_global.is_(True))
        )
    if domain:
        stmt = stmt.where(KnowledgeDocument.business_domain == domain)
    stmt = stmt.order_by(KnowledgeDocument.created_at.desc())

    documents = db.execute(stmt).scalars().all()
    summaries = []
    for doc in documents:
        summaries.append(
            DocumentSummaryResponse(
                document_id=doc.document_id,
                title=doc.title,
                source=doc.source,
                document_type=doc.document_type,
                business_domain=doc.business_domain,
                version=doc.version,
                status=doc.status,
                chunks_count=len(doc.chunks),
                created_at=doc.created_at,
            )
        )
    return summaries


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get document details and semantic chunks",
)
def get_document(
    document_id: str,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    """Retrieve full document metadata and constituent semantic chunks with IDOR defense."""
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.document_id == document_id)
    doc = db.execute(stmt).scalars().first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    # Multi-tenant IDOR defense: reject unauthorized cross-tenant access to private documents
    verify_user_document_access(
        db=db,
        user=current_user,
        doc_business_id=doc.business_id,
        is_global=doc.is_global,
        requested_business_id=x_business_id,
    )

    chunk_responses = [
        ChunkResponse(
            chunk_id=c.chunk_id,
            chunk_index=c.chunk_index,
            title=c.title,
            content=c.content,
            business_domain=c.business_domain,
            tags=c.tags,
        )
        for c in doc.chunks
    ]

    return DocumentDetailResponse(
        document_id=doc.document_id,
        title=doc.title,
        source=doc.source,
        document_type=doc.document_type,
        business_domain=doc.business_domain,
        version=doc.version,
        status=doc.status,
        created_at=doc.created_at,
        chunks=chunk_responses,
    )


@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute hybrid context retrieval over business knowledge",
    description="Combines KPI ontology exact match with dense vector similarity search to return grounded context and provenance.",
)
def search_knowledge(
    payload: KnowledgeSearchRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeSearchResponse:
    """Search business context documents with provenance evidence."""
    if x_business_id:
        verify_user_business_access(db, current_user, x_business_id, action="search knowledge in")

    retriever = HybridRetriever(db)
    result = retriever.retrieve(
        query=payload.query,
        business_domain=payload.business_domain,
        top_k=payload.top_k,
        similarity_threshold=payload.similarity_threshold,
        business_id=x_business_id,
    )
    return KnowledgeSearchResponse.model_validate(result.model_dump())
