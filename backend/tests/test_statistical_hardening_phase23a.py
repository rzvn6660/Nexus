"""Comprehensive tests for Phase 23A Statistical Hardening.

Covers:
1. Unified normality evaluation across sample sizes and edge cases.
2. Deterministic multiple testing corrections (Holm, Benjamini-Hochberg FDR, Bonferroni).
3. Method selector guardrails: assumption validation, pairing checks, no test solely on n >= 30.
4. Regression diagnostics: rank deficiency, Breusch-Pagan heteroskedasticity, Durbin-Watson autocorrelation, Cook's distance.
5. ANOVA post-hoc analysis with Holm adjustment.
6. Chi-Square Cochran expected cell frequency validation & Fisher's exact test.
7. Numerical edge cases: near-zero mean CV, zero variance, singular matrices, tiny samples.
8. Chart suitability validation (box plot minimum sample, non-linear scatter trendline).
9. Statistical vs business significance separation in interpretations.
10. Evidence records preserving all hardened diagnostic attributes.
"""

import numpy as np
import pytest
from app.analytics.core.types import (
    AnalyticalQuestionType,
    ChartType,
    HypothesisTestType,
    CorrelationMethod,
)
from app.analytics.core.models import (
    AnovaResult,
    ChiSquareContingencyResult,
    RegressionAnalysisResult,
    StatisticalTestResult,
)
from app.analytics.core.exceptions import InsufficientDataError
from app.analytics.statistics.normality import evaluate_normality
from app.analytics.statistics.multiple_testing import MultipleTestingCorrector
from app.analytics.statistics.descriptive import DescriptiveStatistics
from app.analytics.statistics.correlation import CorrelationAnalyzer
from app.analytics.statistics.hypothesis import HypothesisTestRunner
from app.analytics.statistics.regression import RegressionAnalyzer
from app.analytics.statistics.selector import AnalyticalMethodSelector
from app.analytics.statistics.visual_analytics import ChartAdvisor


# ---------------------------------------------------------------------------
# 1. Unified Normality Evaluation
# ---------------------------------------------------------------------------

def test_normality_small_sample_and_zero_variance():
    # n < 3
    res_small = evaluate_normality([1.0, 2.0])
    assert res_small.is_normal is False
    assert res_small.test_used == "insufficient_sample"
    assert res_small.p_value is None

    # Zero variance
    res_zero_var = evaluate_normality([5.0, 5.0, 5.0, 5.0, 5.0])
    assert res_zero_var.is_normal is False
    assert res_zero_var.test_used == "zero_variance"
    assert "zero variance" in res_zero_var.warning


def test_normality_standard_normal_vs_extreme_skew():
    np.random.seed(42)
    normal_data = np.random.normal(loc=100.0, scale=15.0, size=100).tolist()
    res_normal = evaluate_normality(normal_data)
    assert res_normal.is_normal is True
    assert res_normal.p_value > 0.05
    assert res_normal.test_used == "shapiro_wilk"

    # Heavily skewed Pareto / lognormal data
    skewed_data = np.random.lognormal(mean=2.0, sigma=1.8, size=150).tolist()
    res_skewed = evaluate_normality(skewed_data)
    assert res_skewed.is_normal is False
    assert res_skewed.p_value < 0.05


def test_normality_large_sample_uses_dagostino():
    np.random.seed(42)
    large_normal = np.random.normal(loc=50.0, scale=5.0, size=5500).tolist()
    res = evaluate_normality(large_normal)
    assert res.test_used == "dagostino_k2"
    assert res.sample_size == 5500


# ---------------------------------------------------------------------------
# 2. Multiple Testing Corrections
# ---------------------------------------------------------------------------

def test_multiple_testing_corrector_holm():
    raw_p = [0.005, 0.02, 0.03, 0.08]
    res = MultipleTestingCorrector.adjust_p_values(raw_p, method="holm", alpha=0.05)
    assert res.method == "holm"
    assert res.family_wise_error_rate_controlled is True
    assert len(res.adjusted_p_values) == 4
    # Smallest p (0.005) adjusted by 4 -> 0.02
    assert res.adjusted_p_values[0] == pytest.approx(0.02, abs=1e-4)
    # Monotonicity check
    sorted_adj = sorted(res.adjusted_p_values)
    for i in range(len(sorted_adj) - 1):
        assert sorted_adj[i] <= sorted_adj[i + 1]


def test_multiple_testing_corrector_benjamini_hochberg():
    raw_p = [0.001, 0.015, 0.035, 0.09]
    res = MultipleTestingCorrector.adjust_p_values(raw_p, method="benjamini_hochberg", alpha=0.05)
    assert res.method == "benjamini_hochberg"
    assert res.false_discovery_rate_controlled is True
    assert res.num_rejected >= 1


def test_multiple_testing_corrector_bonferroni():
    raw_p = [0.01, 0.02, 0.10]
    res = MultipleTestingCorrector.adjust_p_values(raw_p, method="bonferroni", alpha=0.05)
    assert res.adjusted_p_values[0] == pytest.approx(0.03, abs=1e-4)
    assert res.adjusted_p_values[1] == pytest.approx(0.06, abs=1e-4)
    assert res.rejected == [True, False, False]


# ---------------------------------------------------------------------------
# 3. Method Selection Hardening
# ---------------------------------------------------------------------------

def test_method_selector_never_picks_parametric_solely_on_n_ge_30():
    np.random.seed(42)
    # n=50 per group, but extreme lognormal skew
    s1 = np.random.lognormal(mean=1.0, sigma=2.0, size=50).tolist()
    s2 = np.random.lognormal(mean=1.5, sigma=2.0, size=50).tolist()

    rec = AnalyticalMethodSelector.recommend_method(
        question_type=AnalyticalQuestionType.GROUP_COMPARISON,
        data={"g1": s1, "g2": s2},
    )
    # Must recommend non-parametric Mann-Whitney U despite n=50
    assert rec.recommended_method == HypothesisTestType.MANN_WHITNEY_U.value
    assert "skewed or heavy-tailed" in rec.rationale or "deviate from normality" in rec.rationale


def test_method_selector_validates_pairing_and_difference_normality():
    np.random.seed(42)
    # Paired differences that are continuous normal
    diffs = np.random.normal(loc=2.0, scale=1.0, size=30)
    b = np.linspace(10.0, 50.0, 30)
    a = b + diffs

    rec = AnalyticalMethodSelector.recommend_method(
        question_type=AnalyticalQuestionType.GROUP_COMPARISON,
        data={"before": b.tolist(), "after": a.tolist()},
        is_paired=True,
    )
    # Rerouted from independent group comparison to paired comparison
    assert rec.question_type == AnalyticalQuestionType.PAIRED_COMPARISON
    assert rec.recommended_method == HypothesisTestType.PAIRED_TTEST.value

    # Heavily skewed paired differences -> Wilcoxon recommendation
    diffs_skewed = np.random.lognormal(mean=1.0, sigma=1.8, size=30)
    a_skewed = b + diffs_skewed
    rec_skewed = AnalyticalMethodSelector.recommend_method(
        question_type=AnalyticalQuestionType.PAIRED_COMPARISON,
        data={"before": b.tolist(), "after": a_skewed.tolist()},
    )
    assert rec_skewed.recommended_method == HypothesisTestType.WILCOXON_SIGNED_RANK.value


# ---------------------------------------------------------------------------
# 4. Regression Diagnostics Hardening
# ---------------------------------------------------------------------------

def test_regression_rank_deficiency_detection():
    # Exactly collinear predictors: X2 = 2 * X1
    y = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    x1 = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    x2 = [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0]

    res = RegressionAnalyzer.fit(y, {"x1": x1, "x2": x2}, dependent_variable_name="y")
    assert res.is_rank_deficient is True
    assert res.matrix_rank < 3  # (intercept + 2 predictors = 3, but rank is 2)
    assert any("rank-deficient" in lim for lim in res.limitations)


def test_regression_heteroskedasticity_breusch_pagan():
    np.random.seed(42)
    n = 100
    x = np.linspace(1.0, 50.0, n)
    # Errors expand with x (heteroskedasticity)
    noise = np.random.normal(0, scale=0.5 * x)
    y = 2.0 * x + noise

    res = RegressionAnalyzer.fit(y.tolist(), {"x": x.tolist()}, dependent_variable_name="y")
    assert res.breusch_pagan_statistic > 0
    assert res.heteroskedasticity_warning is True
    assert res.robust_standard_errors_recommended is True
    assert any("Residual heteroskedasticity detected" in lim for lim in res.limitations)


def test_regression_residual_autocorrelation_durbin_watson():
    # Residuals with severe positive serial correlation (e_t = 0.9 * e_{t-1} + u_t)
    np.random.seed(42)
    n = 60
    x = np.linspace(1.0, 60.0, n)
    e = np.zeros(n)
    for t in range(1, n):
        e[t] = 0.92 * e[t - 1] + np.random.normal(0, 1.0)
    y = 3.0 * x + e

    res = RegressionAnalyzer.fit(y.tolist(), {"x": x.tolist()}, dependent_variable_name="y")
    # DW should be significantly < 1.5 for positive autocorrelation
    assert res.durbin_watson_statistic < 1.5
    assert res.residual_autocorrelation_warning is True
    assert any("Residual autocorrelation detected" in lim for lim in res.limitations)


def test_regression_cooks_distance_and_influential_points():
    np.random.seed(42)
    n = 30
    x = np.linspace(1.0, 30.0, n)
    y = 2.0 * x + np.random.normal(0, 1.0, n)
    # Inject high leverage extreme outlier
    x[-1] = 100.0
    y[-1] = -50.0

    res = RegressionAnalyzer.fit(y.tolist(), {"x": x.tolist()}, dependent_variable_name="y")
    assert res.influential_observations_count >= 1
    assert res.max_cooks_distance > 4.0 / n
    assert any("influential observation(s)" in lim for lim in res.limitations)


# ---------------------------------------------------------------------------
# 5. ANOVA Post-Hoc Analysis with Holm Correction
# ---------------------------------------------------------------------------

def test_anova_post_hoc_pairwise_when_significant():
    # 3 distinct groups with strong separation
    g1 = [10.0, 11.0, 12.0, 10.5, 11.5]
    g2 = [25.0, 26.0, 24.5, 25.5, 27.0]
    g3 = [50.0, 52.0, 49.0, 51.0, 53.0]

    res = HypothesisTestRunner.run_one_way_anova(
        {"low": g1, "mid": g2, "high": g3},
        metric_name="score",
    )
    assert res.is_statistically_significant is True
    assert res.post_hoc_comparisons is not None
    assert len(res.post_hoc_comparisons) == 3  # 3 pairs: (low, mid), (low, high), (mid, high)
    assert res.post_hoc_correction_method == "holm"

    # All pairs should remain significant after Holm adjustment
    for comp in res.post_hoc_comparisons:
        assert comp.is_statistically_significant is True
        assert comp.correction_method == "holm"
        assert comp.p_value_adjusted >= comp.p_value_raw


def test_anova_no_post_hoc_when_non_significant():
    # 3 groups with identical mean
    g1 = [10.0, 10.2, 9.8, 10.1]
    g2 = [10.1, 9.9, 10.0, 10.2]
    g3 = [9.9, 10.0, 10.1, 9.8]

    res = HypothesisTestRunner.run_one_way_anova(
        {"g1": g1, "g2": g2, "g3": g3},
        metric_name="score",
    )
    assert res.is_statistically_significant is False
    assert res.post_hoc_comparisons is None


# ---------------------------------------------------------------------------
# 6. Chi-Square Cochran Rule & Fisher's Exact Test
# ---------------------------------------------------------------------------

def test_chi_square_cochran_violation_and_fishers_exact():
    # Sparse 2x2 contingency table (expected cells < 5)
    sparse_table = {
        "variant_a": {"converted": 2, "not_converted": 8},
        "variant_b": {"converted": 1, "not_converted": 9},
    }

    res = HypothesisTestRunner.run_chi_square_contingency(
        sparse_table,
        variable_x="variant",
        variable_y="conversion",
    )
    assert res.expected_frequencies_valid is False
    assert res.cochran_warning is not None
    assert "Cochran's rule violated" in res.cochran_warning
    # Fisher's exact test should be computed for 2x2 table
    assert res.fishers_exact_p_value is not None
    assert 0.0 <= res.fishers_exact_p_value <= 1.0


# ---------------------------------------------------------------------------
# 7. Numerical Edge Cases & Robustness
# ---------------------------------------------------------------------------

def test_descriptive_cv_near_zero_mean_guard():
    # Mean is near zero (1e-11)
    values = [-1e-11, 1e-11, 2e-11, -2e-11]
    stats_ext = DescriptiveStatistics.compute_extended(values)
    assert stats_ext.coefficient_of_variation is None  # Guarded against division by near-zero


def test_correlation_zero_variance_handling():
    # Variable with constant values
    x = [5.0, 5.0, 5.0, 5.0, 5.0]
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    res = CorrelationAnalyzer.compute(x, y)
    assert res.correlation_coefficient == 0.0
    assert res.strength == "undefined"
    assert "zero variance" in res.limitations[0]


# ---------------------------------------------------------------------------
# 8. Chart Suitability Validation
# ---------------------------------------------------------------------------

def test_chart_advisor_suitability_validation():
    # Box plot with < 5 points per group is statistically invalid
    is_valid, warn, fallback = ChartAdvisor.validate_chart_suitability(
        chart_type=ChartType.BOX_PLOT,
        sample_size=3,
    )
    assert is_valid is False
    assert fallback == ChartType.BAR
    assert "insufficient for 5-number box plot" in warn

    # Scatter plot with non-linear relationship warns against trendline
    is_valid, warn, fallback = ChartAdvisor.validate_chart_suitability(
        chart_type=ChartType.SCATTER,
        sample_size=50,
        is_linear_relationship=False,
    )
    assert is_valid is True
    assert "without trendline" in warn


# ---------------------------------------------------------------------------
# 9. Statistical vs Business Significance Decoupling
# ---------------------------------------------------------------------------

def test_statistical_test_interpretation_decouples_business_significance():
    # Large sample with tiny effect size (p < 0.05, but small effect)
    np.random.seed(42)
    s1 = np.random.normal(100.0, 10.0, 5000).tolist()
    s2 = np.random.normal(101.0, 10.0, 5000).tolist()

    res = HypothesisTestRunner.compare_two_samples(s1, s2, metric_name="revenue")
    assert res.is_statistically_significant is True
    # Verify practical significance explicitly warns about business significance
    assert "Business significance is NOT automatically implied" in res.practical_significance
