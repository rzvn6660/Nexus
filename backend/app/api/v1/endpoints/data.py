"""Data Layer API endpoints for table management, profiling, quality audits, and CSV ingestion."""

import io
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, UploadFile, File, Form, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.auth import get_current_user, verify_user_business_access
from app.models.tenant import Business, OrganizationMembership, UserIdentity
from app.data.profiling.profiler import DataProfiler, MODEL_REGISTRY
from app.data.quality.checker import DataQualityChecker
from app.data.ingestion.csv_ingestion import CSVIngestionService
from app.schemas.profiling import DatasetProfile, TableSummary
from app.schemas.quality import QualityReport
from app.schemas.ingestion import IngestionResult

router = APIRouter()


def _resolve_tenant_business_id(
    db: Session,
    current_user: UserIdentity,
    x_business_id: Optional[str] = None,
) -> Optional[str]:
    """Resolve and authorize tenant business workspace ID with IDOR protection."""
    if x_business_id:
        biz = verify_user_business_access(
            db, current_user, x_business_id, action="access data of"
        )
        return biz.id

    user_org_ids = db.execute(
        select(OrganizationMembership.organization_id).where(
            OrganizationMembership.user_id == current_user.id
        )
    ).scalars().all()
    if user_org_ids:
        biz = db.execute(
            select(Business).where(Business.organization_id.in_(user_org_ids))
        ).scalars().first()
        if biz:
            return biz.id
    return None


@router.get("/health", summary="Data Layer Readiness Health Check")
def get_data_health(
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Returns data layer status, registered entities, and database table availability scoped by tenant.
    """
    biz_id = _resolve_tenant_business_id(db, current_user, x_business_id)
    profiler = DataProfiler(db=db, business_id=biz_id or "__none__")
    try:
        summaries = profiler.get_table_summaries()
        total_records = sum(s.row_count for s in summaries)
        return {
            "status": "ready",
            "layer": "data_layer",
            "registered_models": len(MODEL_REGISTRY),
            "tables": [s.table_name for s in summaries],
            "total_records": total_records,
        }
    except Exception as exc:
        return {
            "status": "degraded",
            "layer": "data_layer",
            "error": str(exc),
            "registered_models": len(MODEL_REGISTRY),
        }


@router.get("/tables", response_model=List[TableSummary], summary="List Registered Database Tables")
def list_tables(
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> List[TableSummary]:
    """
    List all business domain tables, their row counts, and structural schemas scoped by tenant.
    """
    biz_id = _resolve_tenant_business_id(db, current_user, x_business_id)
    profiler = DataProfiler(db=db, business_id=biz_id or "__none__")
    try:
        return profiler.get_table_summaries()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to query table metadata: {str(exc)}")


@router.get("/profile/{dataset}", response_model=DatasetProfile, summary="Profile a Dataset / Table")
def profile_dataset(
    dataset: str,
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> DatasetProfile:
    """
    Generate comprehensive statistical, null, uniqueness, and distribution profile
    for a specific business domain table scoped by tenant.
    """
    key = dataset.lower().strip()
    if key not in MODEL_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{dataset}' not found. Supported tables: {list(MODEL_REGISTRY.keys())}",
        )

    biz_id = _resolve_tenant_business_id(db, current_user, x_business_id)
    profiler = DataProfiler(db=db, business_id=biz_id or "__none__")
    try:
        return profiler.profile_table(key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Profiling failed: {str(exc)}")


@router.get("/quality/{dataset}", response_model=QualityReport, summary="Audit Dataset Data Quality")
def audit_dataset_quality(
    dataset: str,
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> QualityReport:
    """
    Execute deterministic business validation rules and referential checks on a dataset,
    returning an auditable quality scorecard scoped by tenant.
    """
    key = dataset.lower().strip()
    if key not in MODEL_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{dataset}' not found. Supported tables: {list(MODEL_REGISTRY.keys())}",
        )

    biz_id = _resolve_tenant_business_id(db, current_user, x_business_id)
    checker = DataQualityChecker(db=db, business_id=biz_id or "__none__")
    try:
        return checker.check_table(key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Quality audit failed: {str(exc)}")


from app.core.config import settings


@router.post("/ingest/csv", response_model=IngestionResult, summary="Ingest CSV Data File")
async def ingest_csv(
    dataset: str = Form(..., description="Target dataset name: customers, products, inventory, expenses"),
    file: UploadFile = File(..., description="CSV file to ingest"),
    persist: bool = Form(False, description="Whether to persist validated records into database"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> IngestionResult:
    """
    Validate and optionally ingest a CSV file against target domain contract schemas.
    Provides row-level error reporting, format whitelist checking, and file size limits.
    """
    target_key = dataset.lower().strip()
    if target_key not in MODEL_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Target dataset '{dataset}' not supported. Supported: {list(MODEL_REGISTRY.keys())}",
        )

    if persist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Direct CSV persistence via /api/v1/data/ingest/csv is disabled for tenant security. Use the tenant-isolated /api/v1/gateway/upload endpoint for persistent ingestion.",
        )

    # Validate and sanitize file name
    from app.security import sanitize_filename
    filename = sanitize_filename(file.filename)
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format for '{filename}'. Only .csv files are supported.",
        )

    content = await file.read()

    # Enforce upload size limits
    if len(content) > settings.MAX_DOCUMENT_SIZE_BYTES:
        max_mb = settings.MAX_DOCUMENT_SIZE_BYTES / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"CSV file size ({len(content)} bytes) exceeds the maximum limit of {max_mb:.1f}MB.",
        )

    string_io = io.StringIO(content.decode("utf-8", errors="replace"))

    ingestion_service = CSVIngestionService(db=db)
    result = ingestion_service.ingest_csv(
        dataset=target_key,
        source=string_io,
        filename=filename,
        persist=persist,
    )
    return result
