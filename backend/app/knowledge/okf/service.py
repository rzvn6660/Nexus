"""OKF Service for Bundle Ingestion, Persistence, RAG Synchronization, and Export (Phase 14D, 14E, 14H).

Provides:
- Secure import & parsing of OKF bundles
- Deterministic pre-persistence validation
- Transactional database persistence in PostgreSQL/SQLite
- Seamless synchronization into RAG KnowledgeDocument & KnowledgeChunks
- Deterministic, lossless bundle export
"""

import logging
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.okf.models import (
    OKFBundle,
    OKFItem,
    OKFItemType,
    OKFStatus,
    OKFValidationReport,
)
from app.knowledge.okf.parser import OKFExporter, OKFParser
from app.knowledge.okf.security import OKFSecurityError, OKFSecurityFilter
from app.knowledge.okf.validator import OKFValidator
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.okf import OKFBundleModel, OKFItemModel

logger = logging.getLogger(__name__)


class OKFServiceError(Exception):
    """General OKF service error."""
    pass


class OKFValidationErrorException(OKFServiceError):
    """Raised when bundle validation fails prior to persistence."""
    def __init__(self, report: OKFValidationReport) -> None:
        self.report = report
        super().__init__(f"OKF validation failed with {len(report.errors)} errors.")


class OKFService:
    """Service orchestrating OKF lifecycle, validation, database persistence, and RAG sync."""

    @classmethod
    def import_bundle(
        cls,
        bundle_text: str,
        session: Session,
        sync_rag: bool = True,
        business_id: str | None = None,
    ) -> tuple[OKFBundleModel, OKFValidationReport]:
        """
        Validate, normalize, persist, and optionally index an OKF bundle.
        
        Guarantees:
        - Security checks performed first (prompt injection, size limits, code execution)
        - Validation is deterministic: malformed bundles fail safely without touching DB
        - Transactional persistence
        - RAG chunks tagged clearly as business definitions, NOT empirical analytics evidence
        - Tenant boundary isolated via business_id
        """
        # 1. Security scan
        OKFSecurityFilter.validate_raw_bundle_text(bundle_text)

        # 2. Parse bundle
        bundle_dto = OKFParser.parse_bundle(bundle_text)

        # 3. Deterministic validation
        report = OKFValidator.validate_bundle(bundle_dto)
        if not report.is_valid:
            logger.warning("OKF bundle '%s' failed validation: %s", bundle_dto.id, report.errors)
            raise OKFValidationErrorException(report)

        # 4. Persistence into OKF database models
        # Check if bundle already exists (upsert behavior)
        stmt = select(OKFBundleModel).where(OKFBundleModel.bundle_id == bundle_dto.id)
        if business_id is not None:
            stmt = stmt.where(OKFBundleModel.business_id == business_id)
        bundle_model = session.execute(stmt).scalar_one_or_none()

        if bundle_model:
            bundle_model.name = bundle_dto.name
            bundle_model.version = bundle_dto.version
            bundle_model.status = bundle_dto.status.value
            bundle_model.author = bundle_dto.author
            bundle_model.description = bundle_dto.description
            bundle_model.metadata_json = bundle_dto.metadata
            if business_id is not None:
                bundle_model.business_id = business_id
            # Remove old items to ensure clean state
            session.query(OKFItemModel).filter(OKFItemModel.bundle_id == bundle_model.id).delete()
        else:
            bundle_model = OKFBundleModel(
                bundle_id=bundle_dto.id,
                business_id=business_id,
                name=bundle_dto.name,
                version=bundle_dto.version,
                status=bundle_dto.status.value,
                author=bundle_dto.author,
                description=bundle_dto.description,
                metadata_json=bundle_dto.metadata,
            )
            session.add(bundle_model)
            session.flush()

        # Add items
        for it in bundle_dto.items:
            ef_dt = datetime.combine(it.effective_from, datetime.min.time(), tzinfo=timezone.utc) if isinstance(it.effective_from, type(datetime.now().date())) else it.effective_from
            et_dt = datetime.combine(it.effective_to, datetime.min.time(), tzinfo=timezone.utc) if isinstance(it.effective_to, type(datetime.now().date())) else it.effective_to

            item_model = OKFItemModel(
                bundle_id=bundle_model.id,
                business_id=business_id,
                item_id=it.id,
                name=it.name,
                item_type=it.type.value,
                version=it.version,
                status=it.status.value,
                domain=it.domain,
                source=it.source,
                author=it.author,
                verified_by=it.verified_by,
                effective_from=ef_dt,
                effective_to=et_dt,
                formula=it.formula,
                synonyms=it.synonyms,
                canonical_intent=it.canonical_intent,
                analytics_tool=it.analytics_tool,
                metric_field=it.metric_field,
                unit=it.unit,
                target_direction=it.target_direction,
                condition=it.condition,
                action=it.action,
                scope=it.scope,
                priority=it.priority,
                related_ids=it.related_to,
                tags=it.tags,
                content_markdown=it.description,
                metadata_json=it.metadata,
            )
            session.add(item_model)

        session.commit()
        session.refresh(bundle_model)

        # 5. Sync to RAG if requested
        if sync_rag:
            cls._sync_bundle_to_rag(bundle_dto, session, business_id=business_id)

        return bundle_model, report

    @classmethod
    def _sync_bundle_to_rag(cls, bundle: OKFBundle, session: Session, business_id: str | None = None) -> None:
        """
        Synchronize OKF items into KnowledgeDocument and KnowledgeChunks.
        Allows HybridRetriever to query verified business context while marking
        content explicitly as a business definition.
        """
        doc_id = f"okf_{business_id}_{bundle.id}" if business_id else f"okf_{bundle.id}"
        # Remove existing document and chunks if present
        existing_doc = session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.document_id == doc_id,
                KnowledgeDocument.business_id == business_id,
            )
        ).scalar_one_or_none()

        if existing_doc:
            session.delete(existing_doc)
            session.flush()

        import hashlib
        content_hash = hashlib.sha256(f"{business_id}_{bundle.id}".encode("utf-8")).hexdigest()

        doc = KnowledgeDocument(
            document_id=doc_id,
            business_id=business_id,
            title=bundle.name,
            source=f"okf:{bundle.author}",
            document_type="markdown",
            business_domain="business_context",
            content_hash=content_hash,
            version=str(bundle.version),
            status="active" if bundle.status == OKFStatus.VERIFIED else "draft",
            metadata_json={"bundle_id": bundle.id, "source_type": "okf"},
        )
        session.add(doc)
        session.flush()

        from app.rag.embeddings.factory import get_embedding_provider
        embedding_provider = get_embedding_provider()

        # Format texts for all items
        chunk_texts: list[str] = []
        for it in bundle.items:
            chunk_content_lines = [
                f"[Business Context Definition: {it.name}]",
                f"**Domain**: {it.domain} | **Type**: {it.type.value} | **Status**: {it.status.value}",
                f"**Source Provenance**: {it.source}",
            ]
            if it.formula:
                chunk_content_lines.append(f"**Calculation Formula**: {it.formula}")
            if it.synonyms:
                chunk_content_lines.append(f"**Synonyms / Aliases**: {', '.join(it.synonyms)}")
            if it.description:
                chunk_content_lines.append(f"**Business Meaning / Policy**:\n{it.description}")
            chunk_texts.append("\n".join(chunk_content_lines))

        # Batch generate embeddings via active provider (no more zero vectors!)
        embeddings = embedding_provider.get_embeddings(chunk_texts) if chunk_texts else []

        for idx, it in enumerate(bundle.items):
            content_text = chunk_texts[idx]
            chunk_embedding = embeddings[idx] if idx < len(embeddings) else None
            chunk_id = f"chk_okf_{business_id}_{bundle.id}_{it.id}" if business_id else f"chk_okf_{bundle.id}_{it.id}"
            chunk_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()

            chunk = KnowledgeChunk(
                document_id=doc.id,
                chunk_id=chunk_id,
                chunk_index=idx,
                title=it.name,
                content=content_text,
                embedding=chunk_embedding,
                business_id=business_id,
                chunk_hash=chunk_hash,
                embedding_provider=embedding_provider.provider_name,
                embedding_model=embedding_provider.model_name,
                embedding_dimension=embedding_provider.dimension,
                embedding_version=embedding_provider.version,
                business_domain=it.domain if it.domain != "general" else "retail",
                tags=it.tags,
                metadata_json={
                    "okf_bundle_id": bundle.id,
                    "okf_item_id": it.id,
                    "item_type": it.type.value,
                    "is_business_definition": True,
                    "formula": it.formula,
                    "synonyms": it.synonyms,
                },
            )
            session.add(chunk)

        session.commit()

    @classmethod
    def export_bundle(cls, bundle_id: str, session: Session, business_id: str | None = None) -> str:
        """
        Retrieve persisted bundle and serialize it back to deterministic Markdown + YAML frontmatter.
        """
        bundle_model = session.execute(
            select(OKFBundleModel).where(OKFBundleModel.bundle_id == bundle_id)
        ).scalar_one_or_none()

        if not bundle_model:
            raise OKFServiceError(f"Bundle '{bundle_id}' not found in database.")

        if business_id is not None and bundle_model.business_id is not None and bundle_model.business_id != business_id:
            raise OKFServiceError(f"Access denied: Bundle '{bundle_id}' belongs to another business.")

        # Reconstruct DTO
        items: list[OKFItem] = []
        for it in bundle_model.items:
            items.append(OKFItem(
                id=it.item_id,
                name=it.name,
                type=OKFItemType(it.item_type),
                version=it.version,
                status=OKFStatus(it.status),
                domain=it.domain,
                source=it.source,
                author=it.author,
                verified_by=it.verified_by,
                effective_from=it.effective_from,
                effective_to=it.effective_to,
                formula=it.formula,
                synonyms=it.synonyms or [],
                canonical_intent=it.canonical_intent,
                analytics_tool=it.analytics_tool,
                metric_field=it.metric_field,
                unit=it.unit,
                target_direction=it.target_direction,
                condition=it.condition,
                action=it.action,
                scope=it.scope,
                priority=it.priority or 100,
                related_to=it.related_ids or [],
                tags=it.tags or [],
                description=it.content_markdown or "",
                metadata=it.metadata_json or {},
            ))

        bundle_dto = OKFBundle(
            id=bundle_model.bundle_id,
            name=bundle_model.name,
            version=bundle_model.version,
            status=OKFStatus(bundle_model.status),
            author=bundle_model.author,
            description=bundle_model.description or "",
            created_at=bundle_model.created_at,
            items=items,
            metadata=bundle_model.metadata_json or {},
        )

        return OKFExporter.export_bundle(bundle_dto)

    @classmethod
    def get_bundle(cls, bundle_id: str, session: Session) -> OKFBundle | None:
        """Retrieve bundle as a validated Pydantic model."""
        bundle_model = session.execute(
            select(OKFBundleModel).where(OKFBundleModel.bundle_id == bundle_id)
        ).scalar_one_or_none()
        if not bundle_model:
            return None

        items: list[OKFItem] = []
        for it in bundle_model.items:
            items.append(OKFItem(
                id=it.item_id,
                name=it.name,
                type=OKFItemType(it.item_type),
                version=it.version,
                status=OKFStatus(it.status),
                domain=it.domain,
                source=it.source,
                author=it.author,
                verified_by=it.verified_by,
                effective_from=it.effective_from,
                effective_to=it.effective_to,
                formula=it.formula,
                synonyms=it.synonyms or [],
                canonical_intent=it.canonical_intent,
                analytics_tool=it.analytics_tool,
                metric_field=it.metric_field,
                unit=it.unit,
                target_direction=it.target_direction,
                condition=it.condition,
                action=it.action,
                scope=it.scope,
                priority=it.priority or 100,
                related_to=it.related_ids or [],
                tags=it.tags or [],
                description=it.content_markdown or "",
                metadata=it.metadata_json or {},
            ))

        return OKFBundle(
            id=bundle_model.bundle_id,
            name=bundle_model.name,
            version=bundle_model.version,
            status=OKFStatus(bundle_model.status),
            author=bundle_model.author,
            description=bundle_model.description or "",
            created_at=bundle_model.created_at,
            items=items,
            metadata=bundle_model.metadata_json or {},
        )

    @classmethod
    def delete_bundle(cls, bundle_id: str, session: Session) -> bool:
        """Delete an OKF bundle and its synced RAG document."""
        bundle_model = session.execute(
            select(OKFBundleModel).where(OKFBundleModel.bundle_id == bundle_id)
        ).scalar_one_or_none()

        if not bundle_model:
            return False

        # Delete corresponding RAG doc
        rag_doc_id = f"okf_{bundle_model.business_id}_{bundle_id}" if bundle_model.business_id else f"okf_{bundle_id}"
        session.query(KnowledgeDocument).filter(
            KnowledgeDocument.document_id == rag_doc_id
        ).delete()

        session.delete(bundle_model)
        session.commit()
        return True
