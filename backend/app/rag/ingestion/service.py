import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings.base import BaseEmbeddingProvider
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.ingestion.chunking import TextChunker
from app.rag.ingestion.extractors import DocumentExtractor, sanitize_filename
from app.rag.ingestion.models import DocumentMetadata, IngestionResult

logger = logging.getLogger(__name__)


def _compute_next_version(prev_version: str | None, requested_version: str | None) -> str:
    """
    Deterministically advance document semantic version when re-ingested with changed content.
    Examples:
      - prev="1.0", requested="1.0" or None -> "1.1"
      - prev="1.0", requested="2.0" -> "2.0"
      - prev="2", requested=None -> "3"
      - prev=None, requested=None -> "1.0"
    """
    if not prev_version:
        return requested_version or "1.0"
    if requested_version and requested_version != prev_version and requested_version != "1.0":
        return requested_version

    parts = prev_version.split(".")
    if len(parts) == 1 and parts[0].isdigit():
        return str(int(parts[0]) + 1)
    elif len(parts) >= 2 and parts[-1].isdigit():
        minor = int(parts[-1]) + 1
        return ".".join(parts[:-1] + [str(minor)])
    return f"{prev_version}.1"


class DocumentIngestionService:
    """
    Transactional service handling the ingestion of business context documents.
    Enforces deduplication, schema validation, chunking, and dense vector generation.
    """

    def __init__(
        self,
        session: Session,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.chunker = TextChunker()
        self.embedding_provider = embedding_provider or get_embedding_provider()

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
                    and (
                        old_c.embedding_provider is None
                        or old_c.embedding_provider == self.embedding_provider.provider_name
                    )
                    and (
                        old_c.embedding_version is None
                        or old_c.embedding_version == self.embedding_provider.version
                    )
                    and (
                        old_c.embedding_dimension is None
                        or old_c.embedding_dimension == self.embedding_provider.dimension
                    )
                    and len(old_c.embedding) == self.embedding_provider.dimension
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

        # Batch embed only new or modified chunks before mutating database
        if to_embed_texts:
            fresh_embeddings = self.embedding_provider.get_embeddings(to_embed_texts)
            for list_idx, emb in enumerate(fresh_embeddings):
                target_idx = to_embed_indices[list_idx]
                final_embeddings[target_idx] = emb

        target_version = _compute_next_version(
            prev_doc.version if prev_doc else None, metadata.version
        )

        try:
            # If a previous document version existed, mark it as superseded
            # and purge obsolete chunks so they never appear in retrieval
            if prev_doc:
                prev_doc.status = "superseded"
                prev_doc.updated_at = datetime.now(UTC)
                self.session.execute(
                    delete(KnowledgeChunk).where(KnowledgeChunk.document_id == prev_doc.id)
                )
                logger.info(
                    "Marked previous document id=%s as superseded (v%s) by new version (v%s) and purged %d obsolete chunks",
                    prev_doc.document_id,
                    prev_doc.version,
                    target_version,
                    len(prev_doc.chunks),
                )

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
                version=target_version,
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
                if (
                    chunk_embedding is not None
                    and len(chunk_embedding) != self.embedding_provider.dimension
                ):
                    raise ValueError(
                        f"Embedding dimension mismatch during ingestion: Provider '{self.embedding_provider.provider_name}' "
                        f"produced {len(chunk_embedding)}-dimensional vector, expected {self.embedding_provider.dimension}."
                    )

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
        except Exception:
            self.session.rollback()
            raise

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
            version=doc_record.version,
            status="active",
            is_duplicate=False,
            message="Document successfully processed and indexed.",
        )

    def reembed_incompatible_chunks(
        self,
        business_id: str | None = None,
        batch_size: int = 64,
    ) -> dict[str, Any]:
        """
        Scan and re-embed legacy chunks with missing or incompatible embedding metadata.

        Brings legacy chunks into compliance with the active embedding provider and model space.
        Excludes soft-deleted or superseded document chunks.

        Returns:
            Dict summarizing scanned, re-embedded, and committed chunk counts.
        """
        stmt = (
            select(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.status == "active")
            .where(
                (KnowledgeChunk.embedding_model.is_(None))
                | (KnowledgeChunk.embedding_model != self.embedding_provider.model_name)
                | (KnowledgeChunk.embedding_provider.is_(None))
                | (KnowledgeChunk.embedding_provider != self.embedding_provider.provider_name)
                | (KnowledgeChunk.embedding_version.is_(None))
                | (KnowledgeChunk.embedding_version != self.embedding_provider.version)
                | (KnowledgeChunk.embedding_dimension.is_(None))
                | (KnowledgeChunk.embedding_dimension != self.embedding_provider.dimension)
            )
        )
        if business_id is not None:
            stmt = stmt.where(
                (KnowledgeChunk.business_id == business_id)
                | (KnowledgeDocument.business_id == business_id)
            )

        chunks_to_update = self.session.execute(stmt).scalars().all()
        total_found = len(chunks_to_update)
        if total_found == 0:
            return {
                "scanned": 0,
                "reembedded": 0,
                "provider": self.embedding_provider.provider_name,
                "model": self.embedding_provider.model_name,
                "version": self.embedding_provider.version,
            }

        updated_count = 0
        for i in range(0, total_found, batch_size):
            batch = chunks_to_update[i : i + batch_size]
            texts = [c.content for c in batch]
            fresh_embeddings = self.embedding_provider.get_embeddings(texts)

            for chunk, emb in zip(batch, fresh_embeddings):
                chunk.embedding = emb
                chunk.embedding_provider = self.embedding_provider.provider_name
                chunk.embedding_model = self.embedding_provider.model_name
                chunk.embedding_dimension = self.embedding_provider.dimension
                chunk.embedding_version = self.embedding_provider.version
                chunk.chunk_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
                chunk.updated_at = datetime.now(UTC)
                updated_count += 1

            self.session.flush()

        self.session.commit()
        logger.info(
            "Re-embedded %d legacy/incompatible chunks to active model '%s' (%s, v%s)",
            updated_count,
            self.embedding_provider.model_name,
            self.embedding_provider.provider_name,
            self.embedding_provider.version,
        )
        return {
            "scanned": total_found,
            "reembedded": updated_count,
            "provider": self.embedding_provider.provider_name,
            "model": self.embedding_provider.model_name,
            "version": self.embedding_provider.version,
        }

    def cleanup_orphaned_chunks(self, business_id: str | None = None) -> int:
        """
        Purge any orphaned or obsolete knowledge chunks whose parent document
        does not exist or is marked as superseded or inactive.

        Returns:
            Count of deleted orphaned chunks.
        """
        active_doc_ids_subq = select(KnowledgeDocument.id).where(
            KnowledgeDocument.status == "active"
        )
        stmt = delete(KnowledgeChunk).where(~KnowledgeChunk.document_id.in_(active_doc_ids_subq))
        if business_id is not None:
            stmt = stmt.where(KnowledgeChunk.business_id == business_id)

        res = self.session.execute(stmt)
        self.session.commit()
        purged = res.rowcount or 0
        if purged > 0:
            logger.info("Cleaned up %d orphaned/superseded chunks from knowledge store", purged)
        return purged
