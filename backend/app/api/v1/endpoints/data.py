"""Data Layer API endpoints for table management, profiling, quality audits, and CSV ingestion."""

import io
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.data.profiling.profiler import DataProfiler, MODEL_REGISTRY
from app.data.quality.checker import DataQualityChecker
from app.data.ingestion.csv_ingestion import CSVIngestionService
from app.schemas.profiling import DatasetProfile, TableSummary
from app.schemas.quality import QualityReport
from app.schemas.ingestion import IngestionResult

router = APIRouter()


@router.get("/health", summary="Data Layer Readiness Health Check")
def get_data_health(db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    """
    Returns data layer status, registered entities, and database table availability.
    """
    profiler = DataProfiler(db=db)
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
def list_tables(db: Session = Depends(get_db_session)) -> List[TableSummary]:
    """
    List all business domain tables, their row counts, and structural schemas.
    """
    profiler = DataProfiler(db=db)
    try:
        return profiler.get_table_summaries()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to query table metadata: {str(exc)}")


@router.get("/profile/{dataset}", response_model=DatasetProfile, summary="Profile a Dataset / Table")
def profile_dataset(
    dataset: str,
    db: Session = Depends(get_db_session),
) -> DatasetProfile:
    """
    Generate comprehensive statistical, null, uniqueness, and distribution profile
    for a specific business domain table.
    """
    key = dataset.lower().strip()
    if key not in MODEL_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{dataset}' not found. Supported tables: {list(MODEL_REGISTRY.keys())}",
        )

    profiler = DataProfiler(db=db)
    try:
        return profiler.profile_table(key)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Profiling failed: {str(exc)}")


@router.get("/quality/{dataset}", response_model=QualityReport, summary="Audit Dataset Data Quality")
def audit_dataset_quality(
    dataset: str,
    db: Session = Depends(get_db_session),
) -> QualityReport:
    """
    Execute deterministic business validation rules and referential checks on a dataset,
    returning an auditable quality scorecard.
    """
    key = dataset.lower().strip()
    if key not in MODEL_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{dataset}' not found. Supported tables: {list(MODEL_REGISTRY.keys())}",
        )

    checker = DataQualityChecker(db=db)
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

    # Validate file extension
    filename = file.filename or "upload.csv"
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
