"""Pydantic schemas for the NEXUS Production Data Gateway (Phase 16).

Defines deterministic data structures for:
- Column profiling & classification
- Data quality audits & transparent scoring
- Schema mapping proposals (Customer, Product, Sale, Inventory, Expense)
- Data readiness evaluations
- Data preview sample records
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    """Deterministic profile telemetry for a single tabular column."""
    name: str
    data_type: str  # integer, float, datetime, string, boolean
    null_count: int
    null_percentage: float
    unique_count: int
    uniqueness_ratio: float
    sample_values: List[Any] = Field(default_factory=list)
    role: str = "dimension"  # identifier, date, measure, dimension
    suspicious_format: Optional[str] = None


class DateCoverage(BaseModel):
    """Temporal range and coverage metrics."""
    column: str
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    total_valid_dates: int = 0
    estimated_granularity: str = "unknown"  # daily, monthly, irregular


class QualityCheckItem(BaseModel):
    """Single deterministic quality audit finding."""
    check_name: str
    severity: str  # PASS, WARNING, ERROR
    message: str
    deducted_points: int = 0


class SchemaMappingProposal(BaseModel):
    """Rule-based entity and field mapping recommendation."""
    target_entity: str  # Customer, Product, Sale, Inventory, Expense
    field_mappings: Dict[str, str]  # source_column -> target_field
    confidence_score: float  # 0.0 to 1.0
    status: str  # MAPPED, REQUIRES_REVIEW, UNMAPPED
    missing_required_fields: List[str] = Field(default_factory=list)
    unmapped_columns: List[str] = Field(default_factory=list)


class DataReadinessSummary(BaseModel):
    """Transparent, deterministic data readiness evaluation across 6 governance dimensions."""
    overall_status: str  # READY, READY_WITH_WARNINGS, REQUIRES_REVIEW, INSUFFICIENT_DATA
    readiness_score: int = Field(..., ge=0, le=100)
    dimensions: Dict[str, str] = Field(default_factory=dict)
    score_breakdown: List[QualityCheckItem] = Field(default_factory=list)
    can_open_workspace: bool = False
    action_items: List[str] = Field(default_factory=list)


class DatasetDetailResponse(BaseModel):
    """Full metadata, telemetry, and readiness status for an uploaded dataset."""
    id: str
    business_id: str
    organization_id: str
    filename: str
    file_type: str
    file_size_bytes: int
    row_count: int
    column_count: int
    content_hash: Optional[str] = None
    ingestion_status: str  # PENDING, PROCESSING, COMPLETED, FAILED, REQUIRES_REVIEW
    readiness_status: str  # READY, READY_WITH_WARNINGS, REQUIRES_REVIEW, INSUFFICIENT_DATA
    readiness_score: int
    date_coverage: Optional[DateCoverage] = None
    column_profiles: List[ColumnProfile] = Field(default_factory=list)
    mapping_proposal: Optional[SchemaMappingProposal] = None
    readiness_summary: DataReadinessSummary
    created_at: str


class DataPreviewResponse(BaseModel):
    """Sanitized data preview for customer inspection."""
    dataset_id: str
    filename: str
    row_count: int
    total_rows: int = 0
    column_count: int
    columns: List[str]
    inferred_types: Dict[str, str]
    column_roles: Dict[str, str]
    sample_rows: List[Dict[str, Any]]
    readiness_status: str
    readiness_score: int
    detected_entity: Optional[str] = None


class DatasetIngestRequest(BaseModel):
    """Request to commit mapped tabular data into unified NEXUS domain models."""
    target_entity: Optional[str] = None
    column_overrides: Optional[Dict[str, str]] = None
    persist_records: bool = True
