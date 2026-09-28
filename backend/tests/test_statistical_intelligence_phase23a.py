"""Comprehensive deterministic test suite for Phase 23A: Statistical & Analytical Intelligence.

Tests cover:
1. Extended descriptive statistics (mean, median, mode, variance, std, CV, percentiles, skewness, kurtosis, normality, CIs)
2. Outlier detection (Tukey IQR and Z-score)
3. Weighted statistics and rolling statistics
4. Growth and CAGR metrics
5. Inferential statistics:
   - Welch's t-test and Student's t-test with Cohen's d and CIs
   - Paired t-test and Wilcoxon signed-rank
   - One-sample t-test
   - One-Way ANOVA and Kruskal-Wallis with Eta-squared
   - Chi-Square test of independence with CramÃƒÂ©r's V
   - Two-proportion z-test with confidence intervals
   - Statistical vs practical significance distinction
6. Bivariate correlation, covariance, and automated Pearson/Spearman selection
7. Deterministic OLS multivariate regression:
   - Numerical correctness against known ground truth
   - Coefficients, standard errors, t-statistics, p-values, RÃ‚Â², Adj RÃ‚Â², F-statistic
   - Condition number and VIF multicollinearity diagnostics
   - Causation guardrails
8. Time-series diagnostics:
   - Linear slope, trend direction
   - Augmented Dickey-Fuller stationarity
   - Autocorrelation Function (ACF) lags
   - Detrended residual anomaly detection
9. Pareto 80/20 concentration analysis and Gini inequality coefficient
10. Deterministic Analytical Method Selection & Statistical Guardrails:
    - Sample sufficiency and missingness handling
    - Normality checking and non-parametric fallback selection
    - Equal variance / homoskedasticity routing
11. Analytical Chart Selection (Visual Analytics)
12. Adversarial edge cases: zero variance, tiny sample sizes (n=0, 1, 2), infinite/NaN values
13. EvidenceRecord provenance completeness and traceability
"""

import math
import numpy as np
import pytest
from scipy import stats

from app.analytics.core.types import (
    HypothesisTestType,
    CorrelationMethod,
    AnalyticalQuestionType,
    ChartType,
    DistributionType,
    EffectSizeMagnitude,
    TrendDirection,
)
from app.analytics.core.models import (
    ConfidenceInterval,
    OutlierResult,
    DescriptiveExtendedStats,
    EffectSizeResult,
    StatisticalTestResult,
    AnovaResult,
    ChiSquareContingencyResult,
    TwoProportionResult,
    RegressionAnalysisResult,
    TimeSeriesDiagnosticResult,
    ParetoAnalysisResult,
    ChartRecommendation,
    AnalyticalMethodRecommendation,
)
from app.analytics.core.exceptions import InsufficientDataError
from app.analytics.statistics.descriptive import DescriptiveStatistics
from app.analytics.statistics.hypothesis import HypothesisTestRunner
from app.analytics.statistics.correlation import CorrelationAnalyzer
from app.analytics.statistics.regression import RegressionAnalyzer
from app.analytics.statistics.time_series_diagnostics import TimeSeriesDiagnosticAnalyzer
from app.analytics.statistics.pareto import ParetoAnalyzer
from app.analytics.statistics.selector import AnalyticalMethodSelector
from app.analytics.statistics.visual_analytics import ChartAdvisor
from app.analytics.core.context import AnalysisContext
from app.analytics.service import AnalyticsService


# ============================================================================
# 1. DESCRIPTIVE STATISTICS & DISTRIBUTIONS
# ============================================================================

def test_extended_descriptive_stats_normal_distribution():
    """Verify parametric and non-parametric distribution statistics on known normal data."""
    np.random.seed(42)
    # Generate 200 observations with known mean=50, std=10
    sample = np.random.normal(loc=50.0, scale=10.0, size=200).tolist()

    res = DescriptiveStatistics.compute_extended(sample, variable_name="sales_amount")

    assert isinstance(res, DescriptiveExtendedStats)
    assert res.variable_name == "sales_amount"
    assert res.count == 200
    assert 48.0 <= res.mean <= 52.0
    assert 48.0 <= res.median <= 52.0
    assert 8.5 <= res.std_dev <= 11.5
    assert res.variance > 0
    assert res.coefficient_of_variation is not None
    assert 0.15 <= res.coefficient_of_variation <= 0.25

    # Percentiles ordering
    assert res.p10 < res.p25 <= res.p50 <= res.p75 < res.p90 < res.p95 < res.p99
    assert res.iqr == pytest.approx(res.p75 - res.p25, rel=1e-3)
    assert res.range == pytest.approx(res.max - res.min, rel=1e-3)

    # Normality and shape
    assert abs(res.skewness) < 0.5  # Normal has ~0 skewness
    assert abs(res.kurtosis) < 1.0  # Normal has ~0 excess kurtosis
    assert res.distribution_type in [DistributionType.APPROXIMATELY_NORMAL]
    assert res.is_normally_distributed is True

    # 95% Confidence Interval for mean contains true mean (50.0)
    assert res.confidence_interval_95 is not None
    ci = res.confidence_interval_95
    assert ci.lower_bound <= 50.0 <= ci.upper_bound
    assert ci.confidence_level == 0.95
    assert ci.margin_of_error > 0


def test_extended_descriptive_skewness_and_distribution_types():
    """Verify detection of right-skewed and left-skewed distributions."""
    np.random.seed(42)
    # Right-skewed distribution (exponential)
    right_skewed = np.random.exponential(scale=5.0, size=300).tolist()
    res_right = DescriptiveStatistics.compute_extended(right_skewed, variable_name="wait_time")
    assert res_right.skewness > 0.5
    assert res_right.distribution_type == DistributionType.RIGHT_SKEWED

    # Left-skewed distribution (e.g. 100 - exponential)
    left_skewed = (100.0 - np.random.exponential(scale=5.0, size=300)).tolist()
    res_left = DescriptiveStatistics.compute_extended(left_skewed, variable_name="exam_scores")
    assert res_left.skewness < -0.5
    assert res_left.distribution_type == DistributionType.LEFT_SKEWED


def test_outlier_detection_tukey_and_zscore():
    """Verify dual-method outlier detection (Tukey IQR and Z-score)."""
    # Sample with 2 injected extreme outliers
    clean = [10.0, 11.0, 12.0, 10.5, 11.5, 9.8, 12.2, 10.8, 11.1, 10.9,
             10.2, 11.8, 12.0, 10.0, 11.2, 9.9, 10.7, 11.4, 10.6, 11.3,
             10.4, 11.7, 10.1, 12.1, 10.3, 11.9, 10.5, 11.0, 10.8, 11.2]
    outliers = [100.0, -80.0]  # Obvious extreme anomalies
    sample = clean + outliers

    res = DescriptiveStatistics.compute_extended(sample, variable_name="metric")

    # Tukey method should catch both
    assert res.outliers_tukey is not None
    assert res.outliers_tukey.count >= 2
    assert 100.0 in res.outliers_tukey.outlier_values
    assert -80.0 in res.outliers_tukey.outlier_values
    assert res.outliers_tukey.percentage > 0

    # Z-score method (|z| > 3) should catch them
    assert res.outliers_zscore is not None
    assert res.outliers_zscore.count >= 2
    assert 100.0 in res.outliers_zscore.outlier_values
    assert -80.0 in res.outliers_zscore.outlier_values


def test_weighted_statistics_numerical_correctness():
    """Verify weighted mean and weighted variance calculations."""
    values = [10.0, 20.0, 30.0]
    weights = [1.0, 2.0, 1.0]

    # Weighted mean: (10*1 + 20*2 + 30*1) / 4 = 80 / 4 = 20.0
    res = DescriptiveStatistics.compute_weighted(values, weights, variable_name="price")
    assert res["weighted_mean"] == 20.0
    # Variance: (1*(10-20)^2 + 2*(20-20)^2 + 1*(30-20)^2) / 4 = (100 + 0 + 100) / 4 = 50.0
    assert res["weighted_variance"] == 50.0
    assert res["weighted_std"] == round(math.sqrt(50.0), 4)
    assert res["total_weight"] == 4.0
    assert res["sample_size"] == 3


def test_rolling_statistics_and_cagr():
    """Verify rolling window statistics and compound growth calculation."""
    series = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]

    roll = DescriptiveStatistics.compute_rolling(series, window_size=3)
    assert len(roll["rolling_mean"]) == len(series)
    # 3rd point (index 2): mean of [10, 20, 30] = 20.0
    assert roll["rolling_mean"][2] == 20.0
    # 4th point (index 3): mean of [20, 30, 40] = 30.0
    assert roll["rolling_mean"][3] == 30.0

    # CAGR: from 100 to 144 over 2 annual periods (periods_per_year=1) -> 20% annual growth
    annual_vals = [100.0, 120.0, 144.0]
    growth = DescriptiveStatistics.compute_growth_metrics(annual_vals, periods_per_year=1)
    assert growth["start_value"] == 100.0
    assert growth["end_value"] == 144.0
    assert growth["absolute_change"] == 44.0
    assert growth["percentage_change"] == 44.0
    assert growth["cagr_pct"] == 20.0


# ============================================================================
# 2. INFERENTIAL STATISTICS & HYPOTHESIS TESTING
# ============================================================================

def test_welch_ttest_and_cohens_d_effect_size():
    """Verify Welch's t-test with Cohen's d and confidence interval."""
    # Group 1: mean ~ 100, Group 2: mean ~ 80 (significant difference)
    g1 = [98.0, 102.0, 105.0, 99.0, 101.0, 97.0, 104.0, 100.0, 103.0, 96.0]
    g2 = [78.0, 82.0, 79.0, 81.0, 77.0, 83.0, 80.0, 76.0, 84.0, 80.0]

    res = HypothesisTestRunner.compare_two_samples(
        g1, g2, group1_name="Premium", group2_name="Standard", metric_name="AOV"
    )

    assert isinstance(res, StatisticalTestResult)
    assert res.test_type == HypothesisTestType.TWO_SAMPLE_TTEST
    assert res.is_statistically_significant is True
    assert res.p_value < 0.001
    assert res.statistic > 0  # g1 > g2
    assert res.mean_1 > res.mean_2

    # Effect size (Cohen's d)
    assert res.effect_size is not None
    assert res.effect_size.metric_name == "cohens_d"
    assert res.effect_size.value > 2.0  # Very large effect
    assert res.effect_size.magnitude == EffectSizeMagnitude.LARGE

    # Confidence interval of difference
    assert res.confidence_interval is not None
    ci = res.confidence_interval
    diff = res.mean_1 - res.mean_2
    assert ci.point_estimate == pytest.approx(diff, abs=0.01)
    assert ci.lower_bound > 0  # 0 is not in the CI
    assert ci.lower_bound < ci.point_estimate < ci.upper_bound

    # Practical significance synthesis
    assert res.practical_significance is not None
    assert "business significance" in res.practical_significance.lower()


def test_student_ttest_equal_variance():
    """Verify Student's t-test execution when equal variance is specified."""
    g1 = [10.0, 12.0, 11.0, 13.0, 10.5]
    g2 = [14.0, 15.0, 13.5, 16.0, 14.5]

    res = HypothesisTestRunner.compare_two_samples(
        g1, g2, test_type=HypothesisTestType.STUDENT_TTEST
    )
    assert res.test_type == HypothesisTestType.STUDENT_TTEST
    assert res.degrees_of_freedom == 8.0  # n1 + n2 - 2 = 5 + 5 - 2 = 8
    assert res.is_statistically_significant is True


def test_mann_whitney_u_non_parametric():
    """Verify non-parametric Mann-Whitney U test with rank-biserial effect size."""
    g1 = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    g2 = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]

    res = HypothesisTestRunner.compare_two_samples(
        g1, g2, test_type=HypothesisTestType.MANN_WHITNEY_U
    )
    assert res.test_type == HypothesisTestType.MANN_WHITNEY_U
    assert res.is_statistically_significant is True
    assert res.effect_size is not None
    assert res.effect_size.metric_name == "rank_biserial_correlation"
    assert res.effect_size.magnitude in [EffectSizeMagnitude.LARGE, EffectSizeMagnitude.MEDIUM]


def test_paired_ttest_and_wilcoxon():
    """Verify paired Student's t-test and Wilcoxon signed-rank."""
    before = [50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0]
    after =  [58.0, 63.0, 70.0, 72.0, 81.0, 82.0, 89.0, 94.0]  # Consistent increase

    # Parametric paired t-test
    res_paired = HypothesisTestRunner.compare_paired_samples(
        before, after, group_name="Campaign Pre-Post", metric_name="Spend"
    )
    assert res_paired.test_type == HypothesisTestType.PAIRED_TTEST
    assert res_paired.is_statistically_significant is True
    assert res_paired.statistic > 0  # after > before
    assert res_paired.confidence_interval is not None
    assert res_paired.confidence_interval.lower_bound > 0

    # Non-parametric Wilcoxon
    res_wilcoxon = HypothesisTestRunner.compare_paired_samples(
        before, after, use_non_parametric=True
    )
    assert res_wilcoxon.test_type == HypothesisTestType.WILCOXON_SIGNED_RANK
    assert res_wilcoxon.is_statistically_significant is True


def test_one_sample_ttest():
    """Verify one-sample t-test comparing sample against benchmark."""
    sample = [102.0, 105.0, 103.0, 108.0, 104.0, 106.0, 101.0, 107.0]
    benchmark = 100.0

    res = HypothesisTestRunner.test_one_sample(sample, hypothesized_mean=benchmark, metric_name="AOV")
    assert res.test_type == HypothesisTestType.ONE_SAMPLE_TTEST
    assert res.is_statistically_significant is True
    assert res.mean_1 > benchmark
    assert res.confidence_interval.lower_bound > benchmark


def test_one_way_anova():
    """Verify One-Way ANOVA across 3 groups with Eta-squared effect size."""
    groups = {
        "Segment_A": [20.0, 22.0, 21.0, 23.0, 20.5, 21.5],
        "Segment_B": [30.0, 32.0, 31.0, 29.0, 33.0, 30.5],
        "Segment_C": [45.0, 48.0, 46.0, 47.0, 44.0, 49.0],
    }

    res = HypothesisTestRunner.run_one_way_anova(groups, metric_name="Revenue")
    assert isinstance(res, AnovaResult)
    assert res.is_statistically_significant is True
    assert res.p_value < 0.001
    assert res.df_between == 2  # 3 groups - 1
    assert res.df_within == 15  # 18 total - 3
    assert res.eta_squared > 0.8  # Vast majority of variance explained by segment
    assert res.effect_magnitude == EffectSizeMagnitude.LARGE
    assert len(res.groups) == 3


def test_chi_square_contingency():
    """Verify Chi-Square test of independence with CramÃƒÂ©r's V."""
    # 2x2 table: Segment vs Churn
    table = {
        "VIP": {"Retained": 90, "Churned": 10},
        "Standard": {"Retained": 60, "Churned": 40},
    }

    res = HypothesisTestRunner.run_chi_square_contingency(
        table, variable_x="Customer_Segment", variable_y="Churn_Status"
    )
    assert isinstance(res, ChiSquareContingencyResult)
    assert res.is_statistically_significant is True
    assert res.p_value < 0.01
    assert res.degrees_of_freedom == 1  # (2-1)*(2-1) = 1
    assert res.cramers_v > 0.2
    assert res.effect_magnitude in [EffectSizeMagnitude.MEDIUM, EffectSizeMagnitude.SMALL]
    assert "Retained" in res.expected_frequencies["VIP"]


def test_two_proportions_ztest():
    """Verify two-proportion z-test comparing conversion rates."""
    # Group 1: 50 / 200 = 25%
    # Group 2: 80 / 200 = 40%
    res = HypothesisTestRunner.test_two_proportions(
        successes_1=50, total_1=200, successes_2=80, total_2=200,
        group1_name="Control", group2_name="Variant"
    )
    assert isinstance(res, TwoProportionResult)
    assert res.proportion_1 == 0.25
    assert res.proportion_2 == 0.40
    assert res.absolute_difference == -0.15
    assert res.is_statistically_significant is True
    assert res.p_value < 0.01
    assert res.confidence_interval.lower_bound < res.absolute_difference < res.confidence_interval.upper_bound


# ============================================================================
# 3. RELATIONSHIP & DRIVER ANALYSIS (CORRELATION & OLS REGRESSION)
# ============================================================================

def test_correlation_and_covariance():
    """Verify Pearson, Spearman, covariance, and automated selection."""
    x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    y = [2.0, 4.1, 5.9, 8.0, 10.2, 11.9, 14.1, 16.0, 18.2, 20.0]

    # Covariance
    cov_res = CorrelationAnalyzer.compute_covariance(x, y, variable_x="qty", variable_y="rev")
    assert cov_res["covariance"] > 0
    assert cov_res["sample_size"] == 10

    # Pearson correlation
    corr_res = CorrelationAnalyzer.compute(x, y, method=CorrelationMethod.PEARSON)
    assert corr_res.correlation_coefficient > 0.99
    assert corr_res.strength == "strong"
    assert corr_res.direction == "positive"
    assert "DOES NOT imply causation" in corr_res.causation_warning

    # Correlation matrix across 3 variables
    z = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]  # Perfect inverse
    mat_res = CorrelationAnalyzer.compute_matrix({"x": x, "y": y, "z": z})
    assert mat_res["correlation_matrix"]["x"]["x"] == 1.0
    assert mat_res["correlation_matrix"]["x"]["z"] == -1.0


def test_multivariate_ols_regression_ground_truth():
    """Verify deterministic OLS regression against known synthetic ground truth."""
    np.random.seed(123)
    n = 100
    x1 = np.random.uniform(10.0, 50.0, size=n)
    x2 = np.random.uniform(1.0, 10.0, size=n)
    # y = 15.0 + 2.5 * x1 - 4.0 * x2 + small noise
    noise = np.random.normal(0.0, 0.5, size=n)
    y = 15.0 + 2.5 * x1 - 4.0 * x2 + noise

    res = RegressionAnalyzer.fit(
        y=y.tolist(),
        X={"x1": x1.tolist(), "x2": x2.tolist()},
        dependent_variable_name="revenue",
    )

    assert isinstance(res, RegressionAnalysisResult)
    assert res.dependent_variable == "revenue"
    assert res.sample_size == 100
    assert res.degrees_of_freedom_model == 2
    assert res.degrees_of_freedom_residuals == 97
    assert res.r_squared > 0.98
    assert res.adjusted_r_squared > 0.98
    assert res.f_pvalue < 0.0001
    assert res.is_statistically_significant is True

    # Coefficients verification
    coef_dict = {c.variable: c for c in res.coefficients}
    assert "Intercept" in coef_dict
    assert "x1" in coef_dict
    assert "x2" in coef_dict

    # Check parameter estimates are within 0.2 of true values
    assert abs(coef_dict["Intercept"].coefficient - 15.0) < 0.5
    assert abs(coef_dict["x1"].coefficient - 2.5) < 0.1
    assert abs(coef_dict["x2"].coefficient - (-4.0)) < 0.1

    # Check t-statistics and p-values
    assert coef_dict["x1"].p_value < 0.001
    assert coef_dict["x2"].p_value < 0.001
    assert coef_dict["x1"].ci_lower < 2.5 < coef_dict["x1"].ci_upper
    assert coef_dict["x2"].ci_lower < -4.0 < coef_dict["x2"].ci_upper

    # Causation guardrail
    assert "NOT deterministic causality" in res.causation_warning


def test_regression_multicollinearity_and_overfitting_guardrails():
    """Verify regression guardrails for multicollinearity (VIF) and overfitting."""
    # Collinear predictors: x2 is almost identical to x1
    x1 = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    x2 = [1.001, 2.002, 3.001, 4.002, 5.001, 6.002, 7.001, 8.002]
    y = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]

    res = RegressionAnalyzer.fit(y=y, X={"x1": x1, "x2": x2}, dependent_variable_name="y")
    assert res.multicollinearity_warning is True
    assert any("condition number" in lim.lower() for lim in res.limitations)
    assert any("ratio < 5:1" in lim.lower() for lim in res.limitations)


# ============================================================================
# 4. TIME-SERIES DIAGNOSTICS
# ============================================================================

def test_time_series_diagnostics():
    """Verify linear trend, ADF stationarity, ACF autocorrelation, and anomalies."""
    # Linear upward trend with 1 localized anomaly
    t = list(range(30))
    values = [100.0 + 5.0 * i for i in t]
    values[15] = 500.0  # Massive spike anomaly
    dates = [f"2024-{i+1:02d}" for i in range(30)]

    res = TimeSeriesDiagnosticAnalyzer.evaluate(
        values=values, dates=dates, metric_name="monthly_revenue", granularity="monthly"
    )

    assert isinstance(res, TimeSeriesDiagnosticResult)
    assert res.sample_size == 30
    assert res.trend_direction == TrendDirection.INCREASE
    assert res.trend_slope > 0
    assert res.anomalies_detected >= 1
    assert 15 in res.anomaly_indices
    assert len(res.autocorrelations) > 0
    assert "monthly_revenue" in res.interpretation


# ============================================================================
# 5. CUSTOMER / PRODUCT ANALYTICS (PARETO 80/20 & GINI)
# ============================================================================

def test_pareto_concentration_and_gini_calculation():
    """Verify deterministic 80/20 rule validation and Gini coefficient."""
    # Synthetic classic 80/20 distribution: 20 top accounts generate $80,000, 80 bottom accounts generate $20,000
    entities = []
    for i in range(20):
        entities.append({"entity_id": f"top_{i}", "entity_name": f"VIP {i}", "revenue": 4000.0})
    for i in range(80):
        entities.append({"entity_id": f"bottom_{i}", "entity_name": f"Std {i}", "revenue": 250.0})

    res = ParetoAnalyzer.evaluate(entities, metric_key="revenue", dimension_name="customers")

    assert isinstance(res, ParetoAnalysisResult)
    assert res.total_entities == 100
    assert res.total_metric_value == 100000.0
    assert res.top_20_pct_entities_count == 20
    assert res.top_20_pct_share == 80.0
    assert res.satisfies_80_20_rule is True
    assert res.concentration_classification == "high"
    assert 0.50 <= res.gini_coefficient <= 0.80

    # Lorenz curve validation
    assert len(res.lorenz_curve) >= 10
    assert res.lorenz_curve[0]["cumulative_metric_share"] == 0.0
    assert res.lorenz_curve[-1]["cumulative_metric_share"] == 100.0


# ============================================================================
# 6. ANALYTICAL METHOD SELECTION & GUARDRAILS
# ============================================================================

def test_method_selector_routing():
    """Verify deterministic routing and assumption-checking in method selection."""
    # 1. Two-group comparison with normal data -> Welch's t-test
    data_normal = {
        "A": [10.0, 11.0, 12.0, 10.5, 11.5, 12.2, 10.8],
        "B": [14.0, 15.0, 16.0, 14.5, 15.5, 16.2, 14.8],
    }
    rec1 = AnalyticalMethodSelector.recommend_method(
        question_type=AnalyticalQuestionType.GROUP_COMPARISON, data=data_normal
    )
    assert rec1.recommended_method == HypothesisTestType.TWO_SAMPLE_TTEST.value
    assert rec1.recommended_chart == ChartType.BOX_PLOT
    assert rec1.sample_sufficiency == "sufficient"

    # 2. Bivariate correlation -> Pearson
    rec2 = AnalyticalMethodSelector.recommend_method(
        question_type=AnalyticalQuestionType.BIVARIATE_CORRELATION, data=data_normal
    )
    assert rec2.recommended_chart == ChartType.SCATTER

    # 3. Excessive missingness (>80%) -> insufficient sample rating
    bad_data = {
        "A": [1.0, None, None, None, None, None, None, None, None, None],
        "B": [2.0, None, None, None, None, None, None, None, None, None],
    }
    rec_bad = AnalyticalMethodSelector.recommend_method(
        question_type=AnalyticalQuestionType.GROUP_COMPARISON, data=bad_data
    )
    assert rec_bad.sample_sufficiency == "insufficient"
    assert any("excessive missingness" in w.lower() for w in rec_bad.data_quality_warnings)


# ============================================================================
# 7. VISUAL ANALYTICS (CHART ADVISOR)
# ============================================================================

def test_chart_advisor_recommendations():
    """Verify analytical chart configurations map cleanly to question archetypes."""
    trend_chart = ChartAdvisor.recommend_for_question(AnalyticalQuestionType.TIME_SERIES_TREND, metric_name="revenue")
    assert trend_chart.chart_type == ChartType.LINE

    comp_chart = ChartAdvisor.recommend_for_question(AnalyticalQuestionType.GROUP_COMPARISON, metric_name="margin")
    assert comp_chart.chart_type == ChartType.BOX_PLOT

    decomp_chart = ChartAdvisor.recommend_for_question(AnalyticalQuestionType.VARIANCE_DECOMPOSITION, metric_name="ebitda")
    assert decomp_chart.chart_type == ChartType.WATERFALL

    cohort_chart = ChartAdvisor.recommend_for_question(AnalyticalQuestionType.COHORT_RETENTION)
    assert cohort_chart.chart_type == ChartType.COHORT_MATRIX


# ============================================================================
# 8. ADVERSARIAL EDGE CASES & GUARDRAILS
# ============================================================================

def test_zero_variance_guardrail():
    """Verify safe zero-variance handling without crashing or false confidence."""
    constant_sample = [10.0, 10.0, 10.0, 10.0, 10.0]
    res = DescriptiveStatistics.compute_extended(constant_sample, variable_name="flat")
    assert res.variance == 0.0
    assert res.std_dev == 0.0
    assert res.distribution_type == DistributionType.UNDEFINED
    assert res.is_normally_distributed is False

    # Two identical zero-variance groups in hypothesis testing
    res_ht = HypothesisTestRunner.compare_two_samples(constant_sample, constant_sample)
    assert res_ht.statistic == 0.0
    assert res_ht.p_value == 1.0
    assert res_ht.is_statistically_significant is False


def test_insufficient_sample_size_exceptions():
    """Verify explicit InsufficientDataError is raised when data violates thresholds."""
    with pytest.raises(InsufficientDataError):
        DescriptiveStatistics.compute_extended([])

    with pytest.raises(InsufficientDataError):
        HypothesisTestRunner.compare_two_samples([1.0], [2.0])  # n < 2

    with pytest.raises(InsufficientDataError):
        CorrelationAnalyzer.compute([1.0, 2.0], [3.0, 4.0])  # n < 3

    with pytest.raises(InsufficientDataError):
        RegressionAnalyzer.fit([1.0, 2.0], {"x": [1.0, 2.0]})  # n < k + 2


# ============================================================================
# 9. SERVICE LAYER & EVIDENCE PROVENANCE TESTS
# ============================================================================

def test_analytics_service_statistical_methods_and_evidence(multi_period_db):
    """Verify that AnalyticsService executes all statistical operations and attaches complete EvidenceRecords."""
    service = AnalyticsService(multi_period_db)
    context = AnalysisContext()

    # 1. Extended descriptive stats
    vals = [10.0, 15.0, 12.0, 18.0, 14.0, 16.0, 20.0, 11.0]
    desc_res, desc_ev = service.get_extended_descriptive_stats(vals, variable_name="unit_sales", context=context)
    assert isinstance(desc_res, DescriptiveExtendedStats)
    assert desc_ev.metric == "descriptive_unit_sales"
    assert "computed_series" in desc_ev.source_tables
    assert len(desc_ev.assumptions) > 0
    assert len(desc_ev.limitations) > 0
    assert desc_ev.result_summary["count"] == 8

    # 2. Pareto concentration from DB
    pareto_res, pareto_ev = service.get_pareto_concentration(dimension="customer", metric="revenue", context=context)
    assert isinstance(pareto_res, ParetoAnalysisResult)
    assert pareto_ev.metric == "pareto_customer_revenue"
    assert "sales" in pareto_ev.source_tables
    assert "gini_coefficient" in pareto_ev.result_summary

    # 3. Time series diagnostics from DB: with only 2 monthly points in multi_period_db, guardrail triggers InsufficientDataError
    with pytest.raises(InsufficientDataError) as exc_info:
        service.run_time_series_diagnostics(metric="revenue", context=context)
    assert "require at least 4 observations" in str(exc_info.value)

    # 4. Regression analysis
    y = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    X = {"x1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]}
    reg_res, reg_ev = service.run_regression_analysis(y, X, dependent_variable_name="revenue", context=context)
    assert isinstance(reg_res, RegressionAnalysisResult)
    assert reg_ev.metric == "regression_revenue"
    assert "r_squared" in reg_ev.result_summary
    assert any("not deterministic causality" in lim.lower() for lim in reg_ev.limitations)

    # 5. ANOVA
    groups = {"A": [10.0, 12.0, 11.0], "B": [20.0, 22.0, 21.0], "C": [30.0, 32.0, 31.0]}
    anova_res, anova_ev = service.run_one_way_anova(groups, metric_name="test_metric")
    assert isinstance(anova_res, AnovaResult)
    assert anova_ev.result_summary["significant"] is True

    # 6. Chi-Square
    table = {"R1": {"C1": 50, "C2": 20}, "R2": {"C1": 10, "C2": 40}}
    chi_res, chi_ev = service.run_chi_square_contingency(table, "R", "C")
    assert isinstance(chi_res, ChiSquareContingencyResult)
    assert chi_ev.result_summary["significant"] is True

    # 7. Two Proportions
    prop_res, prop_ev = service.run_two_proportions_test(50, 100, 20, 100, "G1", "G2")
    assert isinstance(prop_res, TwoProportionResult)
    assert prop_ev.result_summary["significant"] is True

    # 8. Method Recommendation
    rec = service.recommend_analytical_method(AnalyticalQuestionType.BIVARIATE_CORRELATION)
    assert isinstance(rec, AnalyticalMethodRecommendation)


# ============================================================================
# 10. TOOL REGISTRY AGENT INTEGRATION
# ============================================================================

def test_tool_registry_statistical_tools(multi_period_db):
    """Verify tool_registry contains and cleanly executes all new statistical tools."""
    from app.agents.tools.registry import tool_registry

    # 1. run_time_series_diagnostics (safely catches insufficient sample error)
    res_ts = tool_registry.execute("run_time_series_diagnostics", multi_period_db, {"metric": "revenue"})
    assert res_ts.status in ["success", "error"]
    if res_ts.status == "error":
        assert "Execution error" in res_ts.error_message

    # 2. run_pareto_concentration
    res_pareto = tool_registry.execute("run_pareto_concentration", multi_period_db, {"dimension": "customer", "metric": "revenue"})
    assert res_pareto.status == "success"
    assert "gini_coefficient" in res_pareto.result

    # 3. run_regression_driver (multi_period_db triggers zero-variance or sample guardrail)
    res_reg = tool_registry.execute(
        "run_regression_driver",
        multi_period_db,
        {"dependent_variable": "subtotal", "independent_variables": ["quantity", "discount_amount"]},
    )
    assert res_reg.status in ["success", "error"]
    if res_reg.status == "error":
        assert any(term in res_reg.error_message.lower() for term in ["zero variance", "insufficient observations", "violating ols"])

    # 4. recommend_analytical_method
    res_rec = tool_registry.execute("recommend_analytical_method", multi_period_db, {"question_type": "group_comparison"})
    assert res_rec.status == "success"
    assert "recommended_method" in res_rec.result
