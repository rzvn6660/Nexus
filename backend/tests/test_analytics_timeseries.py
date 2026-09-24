"""Tests for time-series analysis and period rollups."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.analytics.core.types import PeriodGranularity
from app.analytics.core.context import AnalysisContext
from app.analytics.descriptive.time_series import TimeSeriesAnalyzer


def test_monthly_timeseries_aggregation(multi_period_db: Session):
    """Verify monthly bucket aggregation and growth rate."""
    context = AnalysisContext(
        date_from=datetime(2023, 5, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, tzinfo=timezone.utc),
        granularity=PeriodGranularity.MONTHLY,
    )
    result = TimeSeriesAnalyzer.evaluate(multi_period_db, context, metric="revenue")

    assert len(result.points) == 2
    may_pt = result.points[0]
    june_pt = result.points[1]

    assert may_pt.period_label == "2023-05"
    assert may_pt.value == Decimal("155.00")
    assert may_pt.growth_rate is None  # First point has no predecessor

    assert june_pt.period_label == "2023-06"
    assert june_pt.value == Decimal("340.00")
    # Growth = (340 - 155) / 155 * 100 = 119.35%
    assert june_pt.growth_rate == 119.35

    assert result.total == Decimal("495.00")
    assert result.average == Decimal("247.50")


def test_empty_timeseries_returns_empty_points(multi_period_db: Session):
    """Verify clean response when no sales exist in interval."""
    context = AnalysisContext(
        date_from=datetime(2022, 1, 1, tzinfo=timezone.utc),
        date_to=datetime(2022, 1, 31, tzinfo=timezone.utc),
    )
    result = TimeSeriesAnalyzer.evaluate(multi_period_db, context, metric="revenue")

    assert len(result.points) == 0
    assert result.total == Decimal("0.00")
    assert result.average == Decimal("0.00")
