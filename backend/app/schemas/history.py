"""Pydantic schemas for Analysis History, Decision Records, and Reports."""

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
    """Summary schema for listing historical analytical executions."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str
    query: str
    intent: str | None = None
    status: str
    explanation_level: str
    execution_time_ms: float | None = None
    created_at: datetime


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
