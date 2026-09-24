"""Pydantic schemas for deterministic data quality checks and reporting."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field



class QualitySeverity(str, Enum):
    """Severity classification for a data quality violation."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class QualityStatus(str, Enum):
    """Overall dataset validation status based on check outcomes."""

    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"


class QualityCheckResult(BaseModel):
    """Detailed result for an individual deterministic quality rule."""

    check_name: str
    rule_description: str
    severity: QualitySeverity
    passed: bool
    affected_rows_count: int = 0
    sample_affected_ids: Optional[List[Any]] = None
    message: str


class QualityReport(BaseModel):
    """Comprehensive data quality scorecard for a dataset/table."""

    dataset_name: str
    total_rows: int
    checks_executed: int
    checks_passed: int
    checks_failed: int
    warnings_count: int
    errors_count: int
    status: QualityStatus
    checks: List[QualityCheckResult]
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

