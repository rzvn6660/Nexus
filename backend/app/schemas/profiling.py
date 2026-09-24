"""Pydantic schemas for data profiling results and dataset statistics."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field



class NumericStats(BaseModel):
    """Statistical summary for numeric columns."""

    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    std_dev: Optional[float] = None
    sum_value: Optional[float] = None


class DateRangeStats(BaseModel):
    """Temporal range summary for date and timestamp columns."""

    min_date: Optional[str] = None
    max_date: Optional[str] = None
    duration_days: Optional[int] = None


class CategoricalValueCount(BaseModel):
    """Frequency count for a distinct categorical value."""

    value: str
    count: int
    percentage: float


class ColumnProfile(BaseModel):
    """In-depth statistical and quality profile for an individual column."""

    column_name: str
    inferred_type: str
    total_count: int
    null_count: int
    null_percentage: float
    unique_count: int
    is_unique: bool = False
    numeric_stats: Optional[NumericStats] = None
    date_stats: Optional[DateRangeStats] = None
    top_categories: Optional[List[CategoricalValueCount]] = None


class DatasetProfile(BaseModel):
    """Comprehensive profiling report for a table or ingested dataset."""

    table_name: str
    total_rows: int
    total_columns: int
    duplicate_rows: int
    columns: Dict[str, ColumnProfile]
    profiled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



class TableSummary(BaseModel):
    """High-level summary of a registered database table."""

    table_name: str
    row_count: int
    column_count: int
    columns: List[str]
