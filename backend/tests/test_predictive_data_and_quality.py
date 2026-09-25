"""Unit tests for Phase 7 time-series data preparation and quality gate."""

import numpy as np
import pandas as pd
from app.predictive.data.quality import TimeSeriesQualityGate
from app.predictive.data.time_series import TimeSeriesPreparer
from app.predictive.schemas import DataQualityStatus, ForecastFrequency, ForecastTarget


def test_quality_gate_ready():
    """Verify quality gate marks clean, sufficient time series as READY."""
    dates = pd.date_range("2023-01-01", periods=12, freq="MS")
    values = np.array([100.0, 110.0, 105.0, 120.0, 125.0, 130.0, 135.0, 140.0, 145.0, 150.0, 155.0, 160.0])
    df = pd.DataFrame({"value": values, "is_zero": False}, index=dates)

    quality = TimeSeriesQualityGate.evaluate(df, frequency=ForecastFrequency.MONTHLY, min_observations=4)
    assert quality.status == DataQualityStatus.READY
    assert quality.observation_count == 12
    assert len(quality.blocking_reasons) == 0


def test_quality_gate_insufficient_data():
    """Verify quality gate flags series below minimum threshold as INSUFFICIENT_DATA."""
    dates = pd.date_range("2023-01-01", periods=2, freq="MS")
    df = pd.DataFrame({"value": [100.0, 110.0], "is_zero": False}, index=dates)

    quality = TimeSeriesQualityGate.evaluate(df, frequency=ForecastFrequency.MONTHLY, min_observations=4)
    assert quality.status == DataQualityStatus.INSUFFICIENT_DATA
    assert any("insufficient" in r.lower() for r in quality.blocking_reasons)


def test_quality_gate_constant_series_invalid():
    """Verify constant/zero-variance series is flagged as INVALID."""
    dates = pd.date_range("2023-01-01", periods=8, freq="MS")
    df = pd.DataFrame({"value": [50.0] * 8, "is_zero": False}, index=dates)

    quality = TimeSeriesQualityGate.evaluate(df, frequency=ForecastFrequency.MONTHLY, min_observations=4)
    assert quality.status == DataQualityStatus.INVALID
    assert any("variance" in r.lower() for r in quality.blocking_reasons)


def test_quality_gate_ready_with_warnings_outliers():
    """Verify outliers are detected via IQR and documented with warnings without dropping."""
    dates = pd.date_range("2023-01-01", periods=10, freq="MS")
    # Base 100 with an extreme outlier at 1000
    values = [100.0, 102.0, 98.0, 105.0, 1000.0, 101.0, 99.0, 103.0, 97.0, 104.0]
    df = pd.DataFrame({"value": values, "is_zero": False}, index=dates)

    quality = TimeSeriesQualityGate.evaluate(df, frequency=ForecastFrequency.MONTHLY, min_observations=4)
    assert quality.status == DataQualityStatus.READY_WITH_WARNINGS
    assert len(quality.warnings) > 0
    assert any("outlier" in w.lower() for w in quality.warnings)


def test_time_series_preparer_monthly_aggregation(predictive_db_session):
    """Verify TimeSeriesPreparer extracts and normalizes monthly revenue."""
    preparer = TimeSeriesPreparer(predictive_db_session)
    df, quality = preparer.prepare(
        target_metric=ForecastTarget.REVENUE,
        frequency=ForecastFrequency.MONTHLY,
    )

    assert quality.status in (DataQualityStatus.READY, DataQualityStatus.READY_WITH_WARNINGS)
    assert len(df) == 12
    # Check that monthly dates are aligned to month-start
    assert pd.to_datetime(df["period_start"]).dt.day.iloc[0] == 1


def test_time_series_preparer_product_entity_filter(predictive_db_session):
    """Verify TimeSeriesPreparer filters by product SKU."""
    preparer = TimeSeriesPreparer(predictive_db_session)
    df, quality = preparer.prepare(
        target_metric=ForecastTarget.PRODUCT_DEMAND,
        frequency=ForecastFrequency.MONTHLY,
        entity_type="product",
        entity_id="SKU-PROD-A",
    )

    assert quality.status in (DataQualityStatus.READY, DataQualityStatus.READY_WITH_WARNINGS)
    assert len(df) == 12
    # Verify values match base_qty_p1 from conftest (10, 12, ...)
    assert df["value"].iloc[0] == 10.0


def test_time_series_preparer_empty_series(db_session):
    """Verify empty database returns empty dataframe with INSUFFICIENT_DATA status."""
    preparer = TimeSeriesPreparer(db_session)
    df, quality = preparer.prepare(
        target_metric=ForecastTarget.REVENUE,
        frequency=ForecastFrequency.MONTHLY,
    )

    assert df.empty
    assert quality.status == DataQualityStatus.INSUFFICIENT_DATA
