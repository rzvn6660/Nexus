"""Standardized Failure Taxonomy for NEXUS Evaluation & Benchmarking."""

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class FailureCategory(str, Enum):
    """Standardized failure categories spanning the entire intelligence pipeline."""
    INTENT_ERROR = "INTENT_ERROR"
    SEMANTIC_ERROR = "SEMANTIC_ERROR"
    RETRIEVAL_ERROR = "RETRIEVAL_ERROR"
    TOOL_SELECTION_ERROR = "TOOL_SELECTION_ERROR"
    QUERY_ERROR = "QUERY_ERROR"
    NUMERICAL_ERROR = "NUMERICAL_ERROR"
    ANALYTICAL_ERROR = "ANALYTICAL_ERROR"
    EVIDENCE_ERROR = "EVIDENCE_ERROR"
    GROUNDING_ERROR = "GROUNDING_ERROR"
    HALLUCINATION = "HALLUCINATION"
    CAUSALITY_ERROR = "CAUSALITY_ERROR"
    FORECAST_ERROR = "FORECAST_ERROR"
    DATA_QUALITY_ERROR = "DATA_QUALITY_ERROR"
    TIME_INTERPRETATION_ERROR = "TIME_INTERPRETATION_ERROR"
    SECURITY_ERROR = "SECURITY_ERROR"
    LATENCY_ERROR = "LATENCY_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class FailureSeverity(str, Enum):
    """Severity classification for benchmark and evaluation regressions."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EvaluationFailure(BaseModel):
    """Individual captured failure record with diagnostics."""
    case_id: str
    category: FailureCategory
    severity: FailureSeverity
    stage: str
    expected: Any
    actual: Any
    message: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "stage": self.stage,
            "expected": str(self.expected),
            "actual": str(self.actual),
            "message": self.message,
            "timestamp": self.timestamp,
        }
