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
