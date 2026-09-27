"""Pydantic schemas for Analysis History, Decision Records, and Reports.

Phase 19 additions:
- AnalysisRunSummary and AnalysisRunDetail expose semantic_revision_id, semantic_version,
  dataset_id, dataset_content_hash, ingestion_job_id, dataset_date_coverage
- These fields allow the UI to show the exact semantic version and dataset used per run
"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class DecisionRecordResponse(BaseModel):
    """Output schema for Human-in-the-Loop decision record."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int | None = None
    recommendation_text: str
    status: str = Field(description="PENDING, APPROVED, REJECTED, MODIFIED")
    reviewer_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DecisionCreateRequest(BaseModel):
    """Input schema for creating a human decision record."""
    analysis_id: int | None = None
    recommendation_text: str = Field(..., min_length=3, description="Action or recommendation to track")
    reviewer_notes: str | None = None


class DecisionUpdateRequest(BaseModel):
    """Input schema for updating an existing decision record (approve/reject/modify)."""
    status: str = Field(..., description="PENDING, APPROVED, REJECTED, MODIFIED")
    reviewer_notes: str | None = None
    reviewed_by: str | None = Field(None, description="Identifier of the human reviewer")


class AnalysisRunSummary(BaseModel):
    """Summary schema for listing historical analytical executions.

    Includes Phase 19 immutable snapshots so the history list can show
    which semantic version and dataset were used without fetching full detail.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str
    query: str
    intent: str | None = None
    status: str
    explanation_level: str
    execution_time_ms: float | None = None
    created_at: datetime

    # Phase 19: Semantic snapshot (immutable — reflects state at run time)
    semantic_revision_id: str | None = Field(
        default=None,
        description="ID of the TenantSemanticModel revision active at run creation time."
    )
    semantic_version: int | None = Field(
        default=None,
        description="Semantic model version number used by this run."
    )

    # Phase 19: Dataset snapshot (immutable — reflects state at run time)
    dataset_id: str | None = Field(
        default=None,
        description="ID of the dataset that was active for this business at run time."
    )
    dataset_content_hash: str | None = Field(
        default=None,
        description="SHA-256 fingerprint of the dataset at run time."
    )
    ingestion_job_id: str | None = Field(
        default=None,
        description="Latest completed ingestion job ID at run time."
    )
    dataset_date_coverage: dict[str, Any] | None = Field(
        default=None,
        description="Date coverage metadata (start, end, days) captured at run time."
    )


class AnalysisRunDetail(AnalysisRunSummary):
    """Detailed schema for a complete historical analysis run."""
    model_config = ConfigDict(from_attributes=True)

    answer: str
    tools_used: list[str] | None = None
    calculations: list[dict[str, Any]] | None = None
    assumptions: list[str] | None = None
    limitations: list[str] | None = None
    evidence_records: list[dict[str, Any]] | None = None
    rag_citations: list[dict[str, Any]] | None = None
    decisions: list[DecisionRecordResponse] = []


class ReportExportResponse(BaseModel):
    """Response schema for exportable analysis dossier."""
    report_id: str
    analysis_id: int
    title: str
    format: str = "markdown"
    generated_at: datetime
    content: str
