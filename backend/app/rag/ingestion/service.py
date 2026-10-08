"""Document Ingestion Service orchestrating text extraction, chunking, embedding, and storage."""

import hashlib
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.ingestion.chunking import TextChunker
from app.rag.ingestion.extractors import DocumentExtractor, sanitize_filename
from app.rag.ingestion.models import DocumentMetadata, IngestionResult

logger = logging.getLogger(__name__)


class DocumentIngestionService:
    """
    Transactional service handling the ingestion of business context documents.
    Enforces deduplication, schema validation, chunking, and dense vector generation.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.chunker = TextChunker()
        self.embedding_provider = get_embedding_provider()

    def ingest_file(
        self,
        file_bytes: bytes,
        filename: str,
        metadata: DocumentMetadata,
        business_id: str | None = None,
        is_global: bool = False,
    ) -> IngestionResult:
        """Extract text from file upload, validate constraints, and ingest."""
        clean_name = sanitize_filename(filename)
        text, doc_type = DocumentExtractor.extract_text_and_type(file_bytes, clean_name)
        return self._process_and_store(
            text=text,
            doc_type=doc_type,
            source=metadata.source or clean_name,
            metadata=metadata,
            business_id=business_id,
            is_global=is_global,
        )

    def ingest_text(
        self,
        text: str,
        doc_type: str,
        metadata: DocumentMetadata,
        business_id: str | None = None,
        is_global: bool = False,
    ) -> IngestionResult:
        """Ingest plain text or raw markdown string directly."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Document content cannot be empty.")
        return self._process_and_store(
            text=clean_text,
            doc_type=doc_type.lower(),
            source=metadata.source or "api_upload",
            metadata=metadata,
            business_id=business_id,
            is_global=is_global,
        )

    def _process_and_store(
        self,
        text: str,
        doc_type: str,
        source: str,
        metadata: DocumentMetadata,
        business_id: str | None = None,
        is_global: bool = False,
    ) -> IngestionResult:
        """Internal worker executing hashing, deduplication, chunking, and embedding."""
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # Check for existing document with identical content hash within the same tenant scope
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.content_hash == content_hash,
            KnowledgeDocument.status == "active",
        )
        if business_id is not None:
            stmt = stmt.where(KnowledgeDocument.business_id == business_id)
        existing = self.session.execute(stmt).scalars().first()
        if existing:
            logger.info(
                "Document with identical content hash %s already exists as doc_id=%s. Skipping re-indexing.",
                content_hash,
                existing.document_id,
            )
            chunk_count = len(existing.chunks)
            return IngestionResult(
                document_id=existing.document_id,
                title=existing.title,
                chunks_created=chunk_count,
                content_hash=content_hash,
                business_domain=existing.business_domain,
                version=existing.version,
                status=existing.status,
                is_duplicate=True,
                message="Identical document already ingested. Existing record reused.",
            )

        # Split into semantic chunks
        if doc_type == "markdown":
            chunks = self.chunker.chunk_markdown(
                text=text,
                business_domain=metadata.business_domain,
                tags=metadata.tags,
            )
        else:
            chunks = self.chunker.chunk_text(
                text=text,
                title=metadata.title,
                business_domain=metadata.business_domain,
                tags=metadata.tags,
            )

        if not chunks:
            raise ValueError("Document yielded no valid semantic chunks.")

        # Differential Ingestion: Look for previous version of document with same source & title in this business scope
        prev_doc = None
        if source:
            prev_doc_stmt = select(KnowledgeDocument).where(
                KnowledgeDocument.source == source,
                KnowledgeDocument.title == metadata.title,
                KnowledgeDocument.status == "active",
            )
            if business_id is not None:
                prev_doc_stmt = prev_doc_stmt.where(KnowledgeDocument.business_id == business_id)
            else:
                prev_doc_stmt = prev_doc_stmt.where(KnowledgeDocument.business_id.is_(None))
            prev_doc = self.session.execute(prev_doc_stmt).scalars().first()

        cached_embeddings: dict[str, list[float]] = {}
        if prev_doc:
            for old_c in prev_doc.chunks:
                if (
                    old_c.chunk_hash
                    and old_c.embedding
                    and old_c.embedding_model == self.embedding_provider.model_name
                ):
                    cached_embeddings[old_c.chunk_hash] = old_c.embedding

        # Compute hash for each chunk and identify which chunks need fresh embeddings
        chunk_hashes: list[str] = [
            hashlib.sha256(c.content.encode("utf-8")).hexdigest() for c in chunks
        ]
        to_embed_indices: list[int] = []
        to_embed_texts: list[str] = []
        final_embeddings: list[list[float] | None] = [None] * len(chunks)

        for idx, (chunk_data, chash) in enumerate(zip(chunks, chunk_hashes)):
            if chash in cached_embeddings:
                final_embeddings[idx] = cached_embeddings[chash]
            else:
                to_embed_indices.append(idx)
                to_embed_texts.append(chunk_data.content)

        # Batch embed only new or modified chunks
        if to_embed_texts:
            fresh_embeddings = self.embedding_provider.get_embeddings(to_embed_texts)
            for list_idx, emb in enumerate(fresh_embeddings):
                target_idx = to_embed_indices[list_idx]
                final_embeddings[target_idx] = emb

        # If a previous document version existed, mark it as superseded
        if prev_doc:
            prev_doc.status = "superseded"
            logger.info("Marked previous document id=%s as superseded by new version", prev_doc.document_id)

        # Create KnowledgeDocument record
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        doc_record = KnowledgeDocument(
            document_id=doc_id,
            business_id=business_id,
            is_global=is_global,
            title=metadata.title,
            source=source,
            document_type=doc_type,
            business_domain=metadata.business_domain,
            content_hash=content_hash,
            version=metadata.version,
            effective_from=metadata.effective_from,
            effective_to=metadata.effective_to,
            status="active",
            metadata_json=metadata.custom_metadata,
        )
        self.session.add(doc_record)
        self.session.flush()  # populate doc_record.id

        # Create KnowledgeChunk records with full lineage and tenant metadata
        for i, chunk_data in enumerate(chunks):
            chunk_embedding = final_embeddings[i]
            chunk_record = KnowledgeChunk(
                document_id=doc_record.id,
                chunk_id=chunk_data.chunk_id,
                chunk_index=chunk_data.chunk_index,
                title=chunk_data.title,
                content=chunk_data.content,
                embedding=chunk_embedding,
                business_id=business_id,
                chunk_hash=chunk_hashes[i],
                embedding_provider=self.embedding_provider.provider_name,
                embedding_model=self.embedding_provider.model_name,
                embedding_dimension=self.embedding_provider.dimension,
                embedding_version=self.embedding_provider.version,
                business_domain=chunk_data.business_domain,
                tags=chunk_data.tags,
                metadata_json=chunk_data.metadata_json,
            )
            self.session.add(chunk_record)

        self.session.commit()
        reused_count = len(chunks) - len(to_embed_texts)
        logger.info(
            "Successfully ingested document id=%s, title='%s', chunks=%d (reused %d, fresh embedded %d), provider=%s",
            doc_id,
            metadata.title,
            len(chunks),
            reused_count,
            len(to_embed_texts),
            self.embedding_provider.model_name,
        )

        return IngestionResult(
            document_id=doc_id,
            title=metadata.title,
            chunks_created=len(chunks),
            content_hash=content_hash,
            business_domain=metadata.business_domain,
            version=metadata.version,
            status="active",
            is_duplicate=False,
            message="Document successfully processed and indexed.",
        )
