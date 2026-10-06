"""Pydantic schemas for data profiling results and dataset statistics."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator



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
    data_type: Optional[str] = None
    total_count: int
    null_count: int
    null_percentage: float
    unique_count: int
    distinct_count: Optional[int] = None
    is_unique: bool = False
    numeric_stats: Optional[NumericStats] = None
    date_stats: Optional[DateRangeStats] = None
    top_categories: Optional[List[CategoricalValueCount]] = None

    @model_validator(mode="before")
    @classmethod
    def populate_column_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("data_type") and data.get("inferred_type"):
                data["data_type"] = data["inferred_type"]
            elif not data.get("inferred_type") and data.get("data_type"):
                data["inferred_type"] = data["data_type"]
            if data.get("distinct_count") is None and data.get("unique_count") is not None:
                data["distinct_count"] = data["unique_count"]
            elif data.get("unique_count") is None and data.get("distinct_count") is not None:
                data["unique_count"] = data["distinct_count"]
        return data


class DatasetProfile(BaseModel):
    """Comprehensive profiling report for a table or ingested dataset."""

    table_name: str
    total_rows: int
    row_count: Optional[int] = None
    total_columns: int
    column_count: Optional[int] = None
    duplicate_rows: int
    columns: Dict[str, ColumnProfile]
    profiled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def populate_row_and_column_counts(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("row_count") is None and data.get("total_rows") is not None:
                data["row_count"] = data["total_rows"]
            elif data.get("total_rows") is None and data.get("row_count") is not None:
                data["total_rows"] = data["row_count"]
            if data.get("column_count") is None and data.get("total_columns") is not None:
                data["column_count"] = data["total_columns"]
            elif data.get("total_columns") is None and data.get("column_count") is not None:
                data["total_columns"] = data["column_count"]
        return data



class TableSummary(BaseModel):
    """High-level summary of a registered database table."""

    table_name: str
    row_count: int
    column_count: int
    columns: List[str]
