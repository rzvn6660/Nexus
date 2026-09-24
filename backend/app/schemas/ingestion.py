"""Pydantic schemas for data ingestion contracts and ingestion statistics."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IngestionRowError(BaseModel):
    """Detailed error diagnostics for a malformed or invalid row."""

    row_number: int
    column_name: Optional[str] = None
    raw_value: Optional[Any] = None
    error_type: str
    message: str


class IngestionResult(BaseModel):
    """Execution summary and error report for an ingestion job."""

    dataset_name: str
    filename: Optional[str] = None
    rows_read: int
    rows_valid: int
    rows_failed: int
    errors: List[IngestionRowError] = Field(default_factory=list)
    success: bool
    ingestion_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

