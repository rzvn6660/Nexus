"""Fluent builder for constructing consistent EvidenceRecord instances."""

import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import uuid4
from app.analytics.core.context import AnalysisContext
from app.analytics.evidence.models import EvidenceRecord


class EvidenceBuilder:
    """
    Fluent builder to construct traceable EvidenceRecords for metrics and diagnostic operations.
    """

    def __init__(self, metric: str, context: Optional[AnalysisContext] = None) -> None:
        self._metric = metric
        self._context = context
        self._source_tables: List[str] = []
        self._source_columns: List[str] = []
        self._supporting_sources: List[str] = []
        self._filters: Dict[str, Any] = context.to_filter_dict() if context else {}
        self._date_range: Dict[str, Optional[str]] = {
            "start": context.date_from.isoformat() if context and context.date_from else None,
            "end": context.date_to.isoformat() if context and context.date_to else None,
        }
        self._comparison_period: Optional[Dict[str, Optional[str]]] = None
        if context and context.has_comparison:
            self._comparison_period = {
                "start": context.comparison_date_from.isoformat() if context.comparison_date_from else None,
                "end": context.comparison_date_to.isoformat() if context.comparison_date_to else None,
            }
        self._calculation = ""
        self._mathematical_formula: Optional[str] = None
        self._method = "deterministic_sql_aggregation"
        self._assumptions: List[str] = []
        self._data_quality_status = "verified"
        self._limitations: List[str] = []
        self._result_summary: Dict[str, Any] = {}
        self._row_count: Optional[int] = None
        self._execution_time_ms: Optional[float] = None
        self._checksum: Optional[str] = None

    @classmethod
    def create(cls, metric: str, context: Optional[AnalysisContext] = None) -> "EvidenceBuilder":
        """Instantiate a new EvidenceBuilder."""
        return cls(metric=metric, context=context)

    def with_sources(
        self,
        tables: List[str],
        columns: List[str],
        supporting_sources: Optional[List[str]] = None,
    ) -> "EvidenceBuilder":
        """Add database table and column sources, optionally noting ancillary data-availability probes."""
        self._source_tables.extend([t for t in tables if t not in self._source_tables])
        self._source_columns.extend([c for c in columns if c not in self._source_columns])
        if supporting_sources:
            self._supporting_sources.extend([s for s in supporting_sources if s not in self._supporting_sources])
        return self

    def with_supporting_sources(self, sources: List[str]) -> "EvidenceBuilder":
        """Add ancillary/data-availability probe sources that did not contribute rows."""
        self._supporting_sources.extend([s for s in sources if s not in self._supporting_sources])
        return self

    def with_calculation(
        self,
        calculation: str,
        method: str = "deterministic_sql_aggregation",
        mathematical_formula: Optional[str] = None,
    ) -> "EvidenceBuilder":
        """Specify human-readable formula and execution method."""
        self._calculation = calculation
        self._method = method
        self._mathematical_formula = mathematical_formula or calculation
        return self

    def with_assumptions(self, assumptions: List[str]) -> "EvidenceBuilder":
        """Attach domain and business assumptions."""
        self._assumptions.extend(assumptions)
        return self

    def with_limitations(self, limitations: List[str]) -> "EvidenceBuilder":
        """Attach analytical caveats and limitations."""
        self._limitations.extend(limitations)
        return self

    def with_data_quality_status(self, status: str) -> "EvidenceBuilder":
        """Set data quality confidence status."""
        self._data_quality_status = status
        return self

    def with_result_summary(self, summary: Dict[str, Any]) -> "EvidenceBuilder":
        """Attach key numerical results."""
        self._result_summary.update(summary)
        return self

    def with_row_count(self, count: Optional[int]) -> "EvidenceBuilder":
        """Specify evaluated row count."""
        self._row_count = count
        return self

    def with_execution_time_ms(self, ms: Optional[float]) -> "EvidenceBuilder":
        """Specify execution latency in milliseconds."""
        self._execution_time_ms = ms
        return self

    def with_checksum(self, checksum: Optional[str]) -> "EvidenceBuilder":
        """Attach cryptographic checksum."""
        self._checksum = checksum
        return self

    def build(self) -> EvidenceRecord:
        """Construct the finalized EvidenceRecord."""
        resolved_row_count = self._row_count
        if resolved_row_count is None:
            if "row_count" in self._result_summary and isinstance(self._result_summary["row_count"], (int, float)):
                resolved_row_count = int(self._result_summary["row_count"])
            elif "count" in self._result_summary and isinstance(self._result_summary["count"], (int, float)):
                resolved_row_count = int(self._result_summary["count"])
            elif "orders" in self._result_summary and isinstance(self._result_summary["orders"], (int, float)):
                resolved_row_count = int(self._result_summary["orders"])

        resolved_checksum = self._checksum
        if not resolved_checksum:
            fingerprint_material = (
                f"{self._metric}|{self._method}|{self._calculation}|"
                f"{sorted(self._source_tables)}|"
                f"{sorted(str(k) + ':' + str(v) for k, v in self._filters.items())}|"
                f"{sorted(str(k) + ':' + str(v) for k, v in self._result_summary.items())}"
            )
            resolved_checksum = hashlib.sha256(fingerprint_material.encode("utf-8")).hexdigest()

        return EvidenceRecord(
            analysis_id=str(uuid4()),
            metric=self._metric,
            source_tables=self._source_tables,
            source_columns=self._source_columns,
            supporting_sources=self._supporting_sources,
            filters=self._filters,
            date_range=self._date_range,
            comparison_period=self._comparison_period,
            calculation=self._calculation,
            mathematical_formula=self._mathematical_formula or self._calculation,
            method=self._method,
            assumptions=self._assumptions,
            data_quality_status=self._data_quality_status,
            limitations=self._limitations,
            result_summary=self._result_summary,
            row_count=resolved_row_count,
            execution_time_ms=self._execution_time_ms,
            checksum=resolved_checksum,
            generated_at=datetime.now(timezone.utc),
        )
