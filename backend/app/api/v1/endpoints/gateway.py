"""API endpoints for the NEXUS Production Data Gateway (Phase 16).

Provides:
- Secure tenant-scoped tabular data upload (CSV / XLSX)
- Deterministic profiling, quality auditing, and schema mapping
- Data preview sample inspection
- Ingestion of validated datasets into unified analytical models
"""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.auth import (
    TenantContext,
    get_auth_context,
    get_current_user,
    get_optional_current_user,
    verify_user_business_access,
)
from app.models.tenant import Business, UploadedDataset, UserIdentity
from app.schemas.data_gateway import (
    DataPreviewResponse,
    DataReadinessSummary,
    DatasetDetailResponse,
    DatasetIngestRequest,
    DateCoverage,
    SchemaMappingProposal,
)
from app.services.data_gateway_service import DataGatewayService

router = APIRouter()


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload, profile, and audit business dataset",
    description="Accepts CSV or Excel files, saves to tenant-isolated storage, computes deterministic profiling, data quality scorecard, and schema mapping.",
)
async def upload_dataset(
    file: UploadFile = File(..., description="Tabular data file (.csv, .xlsx, .xls)"),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Upload and process tabular business dataset."""
    target_biz_id = x_business_id
    if not target_biz_id:
        # Fallback to user's first business
        from app.models.tenant import OrganizationMembership
        user_org_ids = db.execute(
            select(OrganizationMembership.organization_id).where(OrganizationMembership.user_id == current_user.id)
        ).scalars().all()
        biz = db.execute(select(Business).where(Business.organization_id.in_(user_org_ids))).scalars().first()
        if not biz:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No business workspace found for user. Please complete onboarding first.",
            )
        target_biz_id = biz.id

    biz = verify_user_business_access(db, current_user, target_biz_id, action="upload data to")
    content = await file.read()

    dataset = DataGatewayService.save_raw_dataset(
        db=db,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename=file.filename or "data.csv",
        content=content,
    )

    schema_json = dataset.schema_json or {}
    quality_json = dataset.quality_report_json or {}

    return {
        "dataset_id": dataset.id,
        "filename": dataset.filename,
        "file_type": dataset.file_type,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "readiness_status": dataset.readiness_status,
        "readiness_score": quality_json.get("readiness_score", 70),
        "target_entity": schema_json.get("mapping_proposal", {}).get("target_entity", "Sale"),
        "mapping_proposal": schema_json.get("mapping_proposal"),
        "quality_summary": quality_json,
    }


@router.get(
    "/datasets",
    summary="List uploaded datasets for workspace",
)
def list_datasets(
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List datasets belonging to the authorized business workspace."""
    target_biz_id = x_business_id
    if not target_biz_id:
        from app.models.tenant import OrganizationMembership
        user_org_ids = db.execute(
            select(OrganizationMembership.organization_id).where(OrganizationMembership.user_id == current_user.id)
        ).scalars().all()
        biz = db.execute(select(Business).where(Business.organization_id.in_(user_org_ids))).scalars().first()
        target_biz_id = biz.id if biz else None

    if not target_biz_id:
        return []

    verify_user_business_access(db, current_user, target_biz_id, action="view datasets of")

    stmt = select(UploadedDataset).where(
        UploadedDataset.business_id == target_biz_id
    ).order_by(desc(UploadedDataset.created_at))
    datasets = db.execute(stmt).scalars().all()

    results = []
    for d in datasets:
        quality = d.quality_report_json or {}
        schema = d.schema_json or {}
        mapping = schema.get("mapping_proposal", {})
        results.append({
            "id": d.id,
            "filename": d.filename,
            "file_type": d.file_type,
            "file_size_bytes": d.file_size_bytes,
            "row_count": d.row_count,
            "column_count": d.column_count,
            "readiness_status": d.readiness_status,
            "readiness_score": quality.get("readiness_score", 75),
            "target_entity": mapping.get("target_entity"),
            "ingestion_status": schema.get("ingestion_status", "COMPLETED"),
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })
    return results


@router.get(
    "/datasets/{dataset_id}",
    summary="Get detailed dataset report",
)
def get_dataset_detail(
    dataset_id: str,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve full profiling, quality audit, and schema mapping for a dataset."""
    dataset = db.execute(
        select(UploadedDataset).where(UploadedDataset.id == dataset_id)
    ).scalar_one_or_none()

    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset_id}' not found.",
        )

    verify_user_business_access(db, current_user, dataset.business_id, action="access dataset")
    if x_business_id and x_business_id != dataset.business_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Dataset belongs to another business workspace.",
        )

    schema_json = dataset.schema_json or {}
    quality_json = dataset.quality_report_json or {}

    return {
        "id": dataset.id,
        "business_id": dataset.business_id,
        "organization_id": dataset.organization_id,
        "filename": dataset.filename,
        "file_type": dataset.file_type,
        "file_size_bytes": dataset.file_size_bytes,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "content_hash": dataset.content_hash,
        "ingestion_status": schema_json.get("ingestion_status", "COMPLETED"),
        "readiness_status": dataset.readiness_status,
        "readiness_score": quality_json.get("readiness_score", 75),
        "date_coverage": schema_json.get("date_coverage"),
        "column_profiles": schema_json.get("column_profiles", []),
        "mapping_proposal": schema_json.get("mapping_proposal"),
        "quality_summary": quality_json,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
    }


@router.get(
    "/datasets/{dataset_id}/preview",
    response_model=DataPreviewResponse,
    summary="Preview raw data sample records",
)
def preview_dataset(
    dataset_id: str,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> DataPreviewResponse:
    """Retrieve top 15 sanitized sample rows and column telemetry."""
    dataset = db.execute(
        select(UploadedDataset).where(UploadedDataset.id == dataset_id)
    ).scalar_one_or_none()

    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset_id}' not found.",
        )

    verify_user_business_access(db, current_user, dataset.business_id, action="preview dataset")
    if x_business_id and x_business_id != dataset.business_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Dataset belongs to another business workspace.",
        )

    return DataGatewayService.get_dataset_preview(
        db=db,
        dataset_id=dataset_id,
        business_id=dataset.business_id,
    )


@router.post(
    "/datasets/{dataset_id}/ingest",
    summary="Ingest dataset records into core analytical models",
)
def ingest_dataset_to_core(
    dataset_id: str,
    payload: DatasetIngestRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Commit mapped tabular records into unified NEXUS domain models."""
    dataset = db.execute(
        select(UploadedDataset).where(UploadedDataset.id == dataset_id)
    ).scalar_one_or_none()

    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset_id}' not found.",
        )

    verify_user_business_access(db, current_user, dataset.business_id, action="ingest dataset")
    if x_business_id and x_business_id != dataset.business_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Dataset belongs to another business workspace.",
        )

    return DataGatewayService.ingest_into_core_models(
        db=db,
        dataset_id=dataset_id,
        business_id=dataset.business_id,
        target_entity=payload.target_entity,
        column_overrides=payload.column_overrides,
    )
