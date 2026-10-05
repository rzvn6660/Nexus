"""Tests for audit traceability and EvidenceRecord construction."""

from datetime import datetime, timezone
import pytest
from app.analytics.core.context import AnalysisContext
from app.analytics.evidence.builder import EvidenceBuilder


def test_evidence_builder_structure():
    """Verify that EvidenceBuilder captures all required audit fields."""
    context = AnalysisContext(
        date_from=datetime(2023, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 1, 31, tzinfo=timezone.utc),
        categories=["Electronics"],
    )

    evidence = (
        EvidenceBuilder.create("test_metric", context)
        .with_sources(["sales", "products"], ["subtotal", "unit_cost"])
        .with_calculation("sum(subtotal) - sum(unit_cost)")
        .with_assumptions(["Tax excluded"])
        .with_limitations(["Static cost used"])
        .with_result_summary({"net_value": 1500.0})
        .build()
    )

    assert evidence.analysis_id is not None
    assert evidence.metric == "test_metric"
    assert "sales" in evidence.source_tables
    assert "subtotal" in evidence.source_columns
    assert evidence.filters["categories"] == ["Electronics"]
    assert evidence.date_range["start"] == "2023-01-01T00:00:00+00:00"
    assert evidence.date_range["end"] == "2023-01-31T00:00:00+00:00"
    assert "sum(subtotal)" in evidence.calculation
    assert "Tax excluded" in evidence.assumptions
    assert "Static cost used" in evidence.limitations
    assert evidence.result_summary["net_value"] == 1500.0
    assert evidence.generated_at is not None


def test_evidence_record_with_missing_optional_values():
    """Regression test: EvidenceRecord with missing optional numeric/date/audit values."""
    from app.analytics.evidence.models import EvidenceRecord

    # Construct EvidenceRecord with only required fields (omitting row_count, execution_time_ms, checksum)
    evidence = EvidenceRecord(
        metric="gross_margin",
        calculation="gross_profit / net_sales",
        source_tables=["sales", "sale_items"],
    )

    assert evidence.metric == "gross_margin"
    assert evidence.row_count is None
    assert evidence.execution_time_ms is None
    assert evidence.checksum is None
    assert evidence.comparison_period is None
    assert evidence.source_columns == []
    assert evidence.filters == {}
    assert evidence.data_quality_status == "verified"

    # Verify JSON serialization works seamlessly
    dumped = evidence.model_dump(mode="json")
    assert dumped["row_count"] is None
    assert dumped["execution_time_ms"] is None
    assert dumped["checksum"] is None
    assert dumped["metric"] == "gross_margin"


def test_evidence_builder_missing_and_explicit_optional_values():
    """Regression test: EvidenceBuilder handling of missing vs explicit optional values."""
    from app.analytics.evidence.builder import EvidenceBuilder

    # Case A: Minimal builder without explicit row count or latency
    minimal_ev = (
        EvidenceBuilder.create("gross_margin")
        .with_calculation("gross_margin = (revenue - cogs) / revenue")
        .build()
    )
    assert minimal_ev.metric == "gross_margin"
    assert minimal_ev.row_count is None
    assert minimal_ev.execution_time_ms is None
    # Auto-generated deterministic SHA-256 fingerprint should be present
    assert minimal_ev.checksum is not None
    assert len(minimal_ev.checksum) == 64

    # Case B: Explicit optional values
    explicit_ev = (
        EvidenceBuilder.create("gross_margin")
        .with_calculation("gross_margin = (revenue - cogs) / revenue")
        .with_row_count(4200)
        .with_execution_time_ms(18.75)
        .with_checksum("custom-sha256-hash")
        .build()
    )
    assert explicit_ev.row_count == 4200
    assert explicit_ev.execution_time_ms == 18.75
    assert explicit_ev.checksum == "custom-sha256-hash"
