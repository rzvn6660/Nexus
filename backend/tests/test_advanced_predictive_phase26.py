"""Comprehensive test suite for Phase 26 Advanced Predictive Intelligence.

Validates:
1. Croston / Syntetos-Boylan (SBA) intermittent demand forecasting.
2. Holt-Winters Triple Exponential Smoothing (additive and multiplicative seasonality).
3. Ridge Lagged Autoregressive forecaster (leakage-safe, deterministic L2 regularized).
4. Principle of Parsimony: baseline retention when advanced improvement < 3.0%.
5. Expanding-window chronological backtesting without future lookahead.
6. Honest uncertainty reporting and non-negative prediction intervals.
7. Demand pattern classification and data sufficiency gates.
8. End-to-end service execution, provenance evidence, and multi-tenant isolation.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import numpy as np
import pytest
from app.models.base import Base
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business
from app.predictive.data.quality import TimeSeriesQualityGate
from app.predictive.evaluation.backtesting import ExpandingWindowBacktester
from app.predictive.models.croston import CrostonForecaster
from app.predictive.models.exponential_smoothing import ExponentialSmoothingForecaster
from app.predictive.models.holt_winters import HoltWintersForecaster
from app.predictive.models.naive import NaiveForecaster
from app.predictive.models.ridge_lagged import RidgeLaggedForecaster
from app.predictive.registry.model_registry import ModelRegistry
from app.predictive.schemas import (
    DataQualityStatus,
    ForecastRequest,
    ForecastStatus,
    ModelPolicy,
)
from app.predictive.services.forecasting_service import ForecastingService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def sqlite_session():
    """In-memory SQLite database session fixture."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    from app.models.tenant import Organization

    org = Organization(id="org-001", name="Retail Org", slug="retail-org")
    session.add(org)
    session.flush()

    # Create test tenant business workspaces
    biz = Business(
        id="biz-retail-001",
        organization_id="org-001",
        name="Retail Alpha Co",
    )
    biz_b = Business(
        id="biz-retail-002",
        organization_id="org-001",
        name="Retail Beta Co",
    )
    session.add_all([biz, biz_b])
    session.commit()

    yield session
    session.close()


# -----------------------------------------------------------------------------
# 1. Croston's Intermittent Demand Forecasting Tests
# -----------------------------------------------------------------------------

def test_croston_intermittent_demand_syntetos_boylan():
    """Verify Croston SBA method on sporadic retail/distribution order series."""
    # Series with ~50% zero-demand intervals
    intermittent_series = np.array([0.0, 10.0, 0.0, 0.0, 15.0, 0.0, 12.0, 0.0, 0.0, 20.0, 0.0, 14.0])
    forecaster = CrostonForecaster(alpha=0.1, variant="sba")
    forecaster.fit(intermittent_series)

    assert forecaster._fitted is True
    assert forecaster.name == "croston"
    assert forecaster._params["variant"] == "sba"
    assert forecaster._params["non_zero_count"] == 5
    assert forecaster._params["zero_ratio"] > 0.40

    # Predictions must be positive and flat demand rate
    preds = forecaster.predict(3)
    assert len(preds) == 3
    assert np.all(preds > 0.0)
    assert preds[0] == preds[1] == preds[2]

    # Prediction intervals: lower bound >= 0.0, upper bound >= point forecast
    lower, upper = forecaster.get_prediction_intervals(3, confidence_level=0.95)
    assert len(lower) == 3
    assert np.all(lower >= 0.0)
    assert np.all(upper >= preds)


def test_croston_insufficient_non_zero_observations():
    """Verify Croston handling of series with zero positive demand observations."""
    all_zeros = np.array([0.0, 0.0, 0.0, 0.0])
    forecaster = CrostonForecaster()
    with pytest.raises(ValueError, match="at least 1 non-zero"):
        forecaster.fit(all_zeros)


def test_croston_single_non_zero_observation_degradation():
    """Verify Croston handles a single positive transaction gracefully."""
    single_positive = np.array([0.0, 0.0, 50.0, 0.0, 0.0])
    forecaster = CrostonForecaster()
    forecaster.fit(single_positive)
    assert forecaster._fitted is True
    preds = forecaster.predict(2)
    assert np.all(preds > 0.0)
    assert round(preds[0], 2) == round(50.0 / 5.0, 2)


# -----------------------------------------------------------------------------
# 2. Holt-Winters Triple Exponential Smoothing Tests
# -----------------------------------------------------------------------------

def test_holt_winters_additive_seasonality_and_trend():
    """Verify Holt-Winters on synthetic seasonal series with linear growth."""
    # 24 months: linear trend + 12-month seasonality
    t = np.arange(24)
    seasonal_pattern = np.array([10, -5, -8, 2, 4, 15, 20, 18, 5, -2, -10, 15] * 2)
    series = 100.0 + 2.5 * t + seasonal_pattern

    hw = HoltWintersForecaster(season_length=12, seasonal_type="additive")
    hw.fit(series)

    assert hw._fitted is True
    assert hw.name == "holt_winters"
    assert "alpha" in hw.parameters
    assert "beta" in hw.parameters
    assert "gamma" in hw.parameters
    assert hw.parameters["cycle_count"] == 2.0

    # Point predictions for next 3 months
    preds = hw.predict(3)
    assert len(preds) == 3
    assert np.all(preds > 0.0)
    # Month 25 (index 0 of seasonal cycle) should be higher than month 24
    assert preds[0] > 100.0

    # Prediction intervals expanding with horizon
    lower, upper = hw.get_prediction_intervals(3, confidence_level=0.95)
    assert np.all(lower >= 0.0)
    assert np.all(upper >= preds)
    assert np.all(lower <= preds)


def test_holt_winters_multiplicative_seasonality():
    """Verify multiplicative seasonality fitting on positive series."""
    t = np.arange(24)
    multipliers = np.array([1.2, 0.9, 0.8, 1.0, 1.1, 1.3, 1.4, 1.2, 1.0, 0.9, 0.8, 1.3] * 2)
    series = (50.0 + 1.5 * t) * multipliers

    hw = HoltWintersForecaster(season_length=12, seasonal_type="multiplicative")
    hw.fit(series)

    assert hw._fitted is True
    assert hw.parameters["seasonal_type"] == "multiplicative"
    preds = hw.predict(2)
    assert len(preds) == 2
    assert np.all(preds > 0.0)


def test_holt_winters_insufficient_cycles_error():
    """Verify Holt-Winters raises informative error when series is shorter than 1 seasonal cycle."""
    short_series = np.array([10.0, 12.0, 14.0, 16.0])
    hw = HoltWintersForecaster(season_length=12)
    with pytest.raises(ValueError, match="at least one full seasonal cycle"):
        hw.fit(short_series)


# -----------------------------------------------------------------------------
# 3. Ridge Lagged Autoregressive Forecaster Tests
# -----------------------------------------------------------------------------

def test_ridge_lagged_autoregressive_forecaster():
    """Verify L2-penalized autoregressive forecaster with cyclical features."""
    # Autoregressive series: y_t = 0.6 * y_{t-1} + 0.2 * y_{t-2} + 5.0
    series = [20.0, 22.0]
    for _ in range(20):
        val = 0.6 * series[-1] + 0.2 * series[-2] + 5.0
        series.append(val)
    arr = np.array(series)

    ridge = RidgeLaggedForecaster(max_lags=2, l2_penalty=1.0)
    ridge.fit(arr)

    assert ridge._fitted is True
    assert ridge.name == "ridge_lagged"
    assert ridge.parameters["lags"] == 2
    assert ridge.parameters["l2_penalty"] == 1.0
    assert len(ridge.parameters["weights"]) > 0

    preds = ridge.predict(3)
    assert len(preds) == 3
    assert np.all(preds > 0.0)

    # Determinism: identical input yields identical output
    ridge_2 = RidgeLaggedForecaster(max_lags=2, l2_penalty=1.0).fit(arr)
    preds_2 = ridge_2.predict(3)
    np.testing.assert_array_almost_equal(preds, preds_2)


def test_ridge_lagged_insufficient_points_error():
    """Verify Ridge forecaster rejects series with fewer points than required lags + 2."""
    tiny_series = np.array([10.0, 12.0])
    ridge = RidgeLaggedForecaster(max_lags=3)
    with pytest.raises(ValueError, match="requires at least"):
        ridge.fit(tiny_series)


# -----------------------------------------------------------------------------
# 4. Principle of Parsimony & Model Selection Tests
# -----------------------------------------------------------------------------

def test_parsimony_rule_retains_simpler_baseline_when_improvement_below_threshold():
    """
    Verify Principle of Parsimony: when an advanced model beats a simpler baseline
    by less than 3.0%, the simpler baseline must be retained.
    """
    from app.predictive.schemas import EvaluationMetrics
    registry = ModelRegistry()

    # Advanced Tier 2 model (ridge_lagged) beats Tier 0 baseline (naive) by only 1.5% (< 3.0%)
    candidate_evals = {
        "naive": EvaluationMetrics(mae=10.0, rmse=12.0, smape=10.0),
        "ridge_lagged": EvaluationMetrics(mae=9.85, rmse=11.9, smape=9.85),
    }
    candidate_models = {
        "naive": NaiveForecaster(),
        "ridge_lagged": RidgeLaggedForecaster(),
    }

    selected_m, _selected_eval, meta = registry._apply_parsimony_selection(
        candidate_evals=candidate_evals,
        candidate_models=candidate_models,
        ranking_metric="mae",
    )

    # Parsimony rule must retain the simpler baseline 'naive'
    assert selected_m.name == "naive"
    assert meta.name == "naive"
    assert "retained parsimonious baseline" in meta.selection_reason.lower()
    assert "improvement threshold" in meta.selection_reason.lower()


def test_parsimony_rule_selects_advanced_when_improvement_is_significant():
    """
    Verify that an advanced model IS selected when out-of-sample improvement exceeds 3.0%.
    """
    from app.predictive.schemas import EvaluationMetrics
    registry = ModelRegistry()

    # Advanced Tier 2 model (ridge_lagged) beats Tier 0 baseline (naive) by 25.0% (>= 3.0%)
    candidate_evals = {
        "naive": EvaluationMetrics(mae=10.0, rmse=12.0, smape=10.0),
        "ridge_lagged": EvaluationMetrics(mae=7.5, rmse=9.0, smape=7.5),
    }
    candidate_models = {
        "naive": NaiveForecaster(),
        "ridge_lagged": RidgeLaggedForecaster(),
    }

    selected_m, _selected_eval, meta = registry._apply_parsimony_selection(
        candidate_evals=candidate_evals,
        candidate_models=candidate_models,
        ranking_metric="mae",
    )

    # Advanced model demonstrated significant improvement (> 3%) and is selected
    assert selected_m.name == "ridge_lagged"
    assert meta.name == "ridge_lagged"
    assert "outperformed" in meta.selection_reason.lower()


def test_parsimony_on_empirical_trend_series():
    """Verify on synthetic trend data that an advanced trend-tracking model beats naive."""
    registry = ModelRegistry()
    y = np.array([10.0 * i for i in range(1, 20)])
    naive = NaiveForecaster()
    es = ExponentialSmoothingForecaster()

    selected_m, selected_eval, _meta = registry.evaluate_and_select(
        series=y,
        candidates=[naive, es],
        ranking_metric="mae",
    )
    assert selected_m.name == "exponential_smoothing"
    assert selected_eval.mae < 1.0


def test_model_registry_baseline_only_policy():
    """Verify BASELINE_ONLY policy excludes Tier 2 advanced models."""
    registry = ModelRegistry()
    factories = registry.get_candidate_factories(policy=ModelPolicy.BASELINE_ONLY)
    assert "naive" in factories
    assert "moving_average" in factories
    assert "exponential_smoothing" in factories
    assert "croston" in factories
    assert "holt_winters" not in factories
    assert "ridge_lagged" not in factories
    assert "arima" not in factories


# -----------------------------------------------------------------------------
# 5. Chronological Backtesting & Zero Data Leakage Tests
# -----------------------------------------------------------------------------

def test_expanding_window_backtest_strict_temporal_ordering():
    """Verify expanding window backtesting respects chronological ordering without lookahead."""
    y = np.array([10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0])
    result = ExpandingWindowBacktester.evaluate(
        forecaster_factory=lambda: ExponentialSmoothingForecaster(),
        y=y,
        horizon=1,
        min_train_size=4,
        max_splits=4,
    )

    assert result.splits_count > 0
    assert result.validation_points == result.splits_count
    assert len(result.predictions) == len(result.actuals)
    assert result.metrics.mae >= 0.0
    assert result.metrics.rmse >= 0.0


# -----------------------------------------------------------------------------
# 6. Data Quality Gate & Demand Pattern Classification Tests
# -----------------------------------------------------------------------------

def test_quality_gate_classifies_smooth_vs_intermittent_demand():
    """Verify TimeSeriesQualityGate accurately classifies smooth vs intermittent demand patterns."""
    import pandas as pd

    # Smooth series (0% zeros)
    smooth_df = pd.DataFrame({
        "period_start": [f"2024-{m:02d}-01" for m in range(1, 13)],
        "value": [100.0 + m * 5 for m in range(1, 13)],
    })
    q_smooth, is_ready = TimeSeriesQualityGate.evaluate(smooth_df, frequency="monthly", min_observations=4)
    assert is_ready is True
    assert q_smooth.demand_pattern == "smooth"
    assert q_smooth.zero_demand_ratio == 0.0

    # Intermittent series (50% zeros)
    intermittent_df = pd.DataFrame({
        "period_start": [f"2024-{m:02d}-01" for m in range(1, 13)],
        "value": [100.0 if m % 2 == 0 else 0.0 for m in range(1, 13)],
    })
    q_intermittent, is_ready_2 = TimeSeriesQualityGate.evaluate(intermittent_df, frequency="monthly", min_observations=4)
    assert is_ready_2 is True
    assert q_intermittent.demand_pattern == "intermittent"
    assert q_intermittent.zero_demand_ratio == 0.50
    assert any("intermittent demand" in w.lower() for w in q_intermittent.warnings)


def test_quality_gate_zero_variance_blocking():
    """Verify constant series (zero variance) is blocked."""
    import pandas as pd
    constant_df = pd.DataFrame({
        "period_start": [f"2024-{m:02d}-01" for m in range(1, 7)],
        "value": [50.0] * 6,
    })
    q, is_ready = TimeSeriesQualityGate.evaluate(constant_df, frequency="monthly", min_observations=4)
    assert is_ready is False
    assert q.status == DataQualityStatus.INVALID
    assert any("zero variance" in r.lower() for r in q.blocking_reasons)


# -----------------------------------------------------------------------------
# 7. End-to-End ForecastingService Retail Demand & Tenant Isolation Tests
# -----------------------------------------------------------------------------

def test_forecasting_service_retail_product_demand_e2e(sqlite_session):
    """Verify end-to-end forecasting for retail SKU demand with prediction intervals."""
    cust = Customer(
        customer_code="CUST-RET-01",
        name="Retail Customer",
        email="retail_cust@example.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    sqlite_session.add(cust)
    sqlite_session.flush()

    prod = Product(
        sku="SKU-DRILL-01",
        name="Industrial Cordless Drill",
        category="Power Tools",
        subcategory="Drills",
        selling_price=Decimal("150.00"),
        unit_cost=Decimal("90.00"),
        active=True,
    )
    sqlite_session.add(prod)
    sqlite_session.flush()

    for m in range(1, 13):
        qty = 10 + m
        subtotal = Decimal(str(150.0 * qty))
        sale = Sale(
            business_id="biz-retail-001",
            transaction_number=f"TXN-DRILL-{m:02d}",
            customer_id=cust.id,
            transaction_date=datetime(2024, m, 15, 12, 0, 0, tzinfo=UTC),
            status="completed",
            subtotal=subtotal,
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=subtotal,
        )
        sqlite_session.add(sale)
        sqlite_session.flush()

        item = SaleItem(
            sale_id=sale.id,
            product_id=prod.id,
            quantity=qty,
            unit_price=Decimal("150.00"),
            line_total=subtotal,
        )
        sqlite_session.add(item)
    sqlite_session.commit()

    service = ForecastingService(sqlite_session, business_id="biz-retail-001")
    req = ForecastRequest(
        target_metric="product_demand",
        entity_type="product",
        entity_id="SKU-DRILL-01",
        forecast_horizon=3,
        frequency="monthly",
        model_policy=ModelPolicy.VALIDATED_BEST,
        confidence_level=0.95,
    )
    res = service.forecast(req)

    assert res.status == ForecastStatus.COMPLETED
    assert len(res.predictions) == 3
    for p in res.predictions:
        assert p.point_forecast > 0.0
        assert p.lower_bound >= 0.0
        assert p.upper_bound >= p.point_forecast
        assert p.interval_width == round(p.upper_bound - p.lower_bound, 2)
        assert p.uncertainty_ratio > 0.0

    # Evidence audit provenance
    assert res.evidence.telemetry_source == "item_level_product_telemetry"
    assert "SKU-DRILL-01" in str(res.evidence.source_columns) or res.entity_id == "SKU-DRILL-01"
    assert res.evidence.validation_metrics.mae >= 0.0

    # Explanation narrative contains honest uncertainty
    assert "### Uncertainty" in res.explanation
    assert "must not be treated as certainties" in res.explanation


def test_forecasting_service_tenant_isolation(sqlite_session):
    """Verify tenant isolation: queries for Tenant A cannot see Tenant B's sales."""
    cust = Customer(
        customer_code="CUST-RET-02",
        name="Tenant B Customer",
        email="tenant_b_cust@example.com",
        city="Detroit",
        customer_segment="Wholesale",
        acquisition_date=date(2023, 1, 1),
    )
    sqlite_session.add(cust)
    sqlite_session.flush()

    # Seed 6 months of sales for biz-retail-002 only
    for m in range(1, 7):
        sale = Sale(
            business_id="biz-retail-002",
            transaction_number=f"TXN-TENANT-B-{m:02d}",
            customer_id=cust.id,
            transaction_date=datetime(2024, m, 10, 10, 0, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("500.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("500.00"),
        )
        sqlite_session.add(sale)
    sqlite_session.commit()

    # Query as Tenant A (biz-retail-001, which has zero sales in this range)
    service_a = ForecastingService(sqlite_session, business_id="biz-retail-001")
    req_a = ForecastRequest(
        target_metric="revenue",
        forecast_horizon=3,
        frequency="monthly",
    )
    res_a = service_a.forecast(req_a)

    # Must be unavailable due to zero historical data for Tenant A
    assert res_a.status == ForecastStatus.UNAVAILABLE
    assert res_a.data_quality.observation_count == 0
    assert "Insufficient historical data" in res_a.limitations[0]


# -----------------------------------------------------------------------------
# 8. Correctness Audit Tests: Edge Cases, Numerical Stability & Uncertainty
# -----------------------------------------------------------------------------

def test_croston_negative_demand_rejected():
    """Verify Croston forecaster rejects negative values (returns/refunds) as invalid demand."""
    c = CrostonForecaster()
    with pytest.raises(ValueError, match="non-negative demand"):
        c.fit(np.array([10.0, -5.0, 0.0, 15.0]))


def test_uncertainty_ratio_zero_and_near_zero_handling():
    """Verify uncertainty_ratio safely bounds zero and near-zero point forecasts without division error."""
    naive = NaiveForecaster()
    naive.fit(np.array([0.0, 0.0, 0.0, 0.0]))
    # All zero inputs: residuals are 0.0, interval width is 0.0
    pts_zero = naive._points_from_raw(np.array([0.0, 0.0]), horizon=2, confidence_level=0.95)
    for p in pts_zero:
        assert p.point_forecast == 0.0
        assert p.interval_width == 0.0
        assert p.uncertainty_ratio == 0.0

    # Non-zero variance but zero point forecast: width > 0, point = 0
    naive2 = NaiveForecaster()
    naive2.fit(np.array([10.0, 0.0]))  # last point 0, but historical variance > 0
    pts_var = naive2._points_from_raw(np.array([0.0]), horizon=1, confidence_level=0.95)
    p_var = pts_var[0]
    assert p_var.point_forecast == 0.0
    assert p_var.interval_width > 0.0
    # Must flag substantial relative uncertainty (1.0), never infinite (e.g. 100,000) or 0.0
    assert p_var.uncertainty_ratio == 1.0


def test_ridge_lagged_constant_input_stability():
    """Verify Ridge forecaster with collinear/constant inputs solves deterministically without LinAlgError."""
    ridge = RidgeLaggedForecaster(max_lags=3, l2_penalty=1.0)
    y_const = np.full(10, 50.0)
    ridge.fit(y_const)
    preds = ridge.predict(3)
    assert len(preds) == 3
    assert np.all(np.isfinite(preds))
    assert np.allclose(preds, 50.0, atol=1.0)


def test_parsimony_rule_zero_baseline_score_retains_baseline():
    """Verify that when the simpler baseline achieves near-zero error, the simpler baseline is strictly retained."""
    from app.predictive.schemas import EvaluationMetrics
    registry = ModelRegistry()

    # Simpler baseline achieves MAE = 0.0; advanced model also achieves 0.0
    candidate_evals = {
        "naive": EvaluationMetrics(mae=0.0, rmse=0.0, smape=0.0),
        "ridge_lagged": EvaluationMetrics(mae=0.0, rmse=0.0, smape=0.0),
    }
    candidate_models = {
        "naive": NaiveForecaster(),
        "ridge_lagged": RidgeLaggedForecaster(),
    }

    selected_m, _selected_eval, meta = registry._apply_parsimony_selection(
        candidate_evals=candidate_evals,
        candidate_models=candidate_models,
        ranking_metric="mae",
    )
    assert selected_m.name == "naive"
    assert meta.name == "naive"


def test_parsimony_rule_handles_nan_and_ties():
    """Verify parsimony selection ignores NaN candidate scores and retains simpler model on exact ties."""
    from app.predictive.schemas import EvaluationMetrics
    registry = ModelRegistry()

    # Model A is simpler (Tier 0), Model B is advanced (Tier 2), identical MAE
    # Model C has NaN error
    candidate_evals = {
        "naive": EvaluationMetrics(mae=5.0, rmse=6.0, smape=5.0),
        "ridge_lagged": EvaluationMetrics(mae=5.0, rmse=6.0, smape=5.0),
        "arima": EvaluationMetrics(mae=float("nan"), rmse=float("nan"), smape=float("nan")),
    }
    candidate_models = {
        "naive": NaiveForecaster(),
        "ridge_lagged": RidgeLaggedForecaster(),
        "arima": NaiveForecaster(),
    }

    selected_m, _selected_eval, meta = registry._apply_parsimony_selection(
        candidate_evals=candidate_evals,
        candidate_models=candidate_models,
        ranking_metric="mae",
    )
    # On tie between Tier 0 and Tier 2, Tier 0 simpler baseline must be retained
    assert selected_m.name == "naive"
    assert meta.name == "naive"


def test_explanation_uncertainty_narrative_honesty():
    """Verify explanation explicitly communicates nominal dispersion and uncalibrated limitations."""
    from app.predictive.forecasting.explanation import ForecastExplainer
    from app.predictive.schemas import (
        EvaluationMetrics,
        ForecastDataQuality,
        ForecastPredictionPoint,
        ModelMetadata,
    )

    exp = ForecastExplainer.explain(
        target_metric="revenue",
        frequency="monthly",
        model=ModelMetadata(name="naive", model_type="baseline", is_baseline=True),
        predictions=[
            ForecastPredictionPoint(
                period="2025-01",
                point_forecast=100.0,
                lower_bound=80.0,
                upper_bound=120.0,
                confidence_level=0.95,
                interval_width=40.0,
                uncertainty_ratio=0.40,
            )
        ],
        evaluation=EvaluationMetrics(mae=5.0, rmse=6.0, smape=5.0),
        data_quality=ForecastDataQuality(
            status="ready",
            observation_count=12,
            frequency="monthly",
        ),
        training_period={"from": "2024-01-01", "to": "2024-12-01"},
    )

    assert "nominal 95% statistical dispersion" in exp
    assert "do not represent empirically calibrated probabilities" in exp
    assert "must not be treated as certainties" in exp
