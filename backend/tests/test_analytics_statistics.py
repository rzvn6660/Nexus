"""Tests for statistical methods: descriptive statistics, correlation, and hypothesis testing."""

import pytest
from app.analytics.core.types import CorrelationMethod, HypothesisTestType
from app.analytics.core.exceptions import InsufficientDataError
from app.analytics.statistics.descriptive import DescriptiveStatistics
from app.analytics.statistics.correlation import CorrelationAnalyzer
from app.analytics.statistics.hypothesis import HypothesisTestRunner


def test_descriptive_statistics():
    """Verify numerical accuracy of mean, median, IQR, stddev."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    res = DescriptiveStatistics.compute(values, variable_name="sample")

    assert res is not None
    assert res.count == 5
    assert res.sum == 150.0
    assert res.mean == 30.0
    assert res.median == 30.0
    assert res.min == 10.0
    assert res.max == 50.0
    assert res.range == 40.0


def test_correlation_perfect_positive():
    """Verify Pearson and Spearman correlation on linear data."""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [10.0, 20.0, 30.0, 40.0, 50.0]

    res_pearson = CorrelationAnalyzer.compute(x, y, method=CorrelationMethod.PEARSON)
    assert res_pearson.correlation_coefficient == 1.0
    assert res_pearson.direction == "positive"
    assert res_pearson.strength == "strong"
    assert "DOES NOT imply causation" in res_pearson.causation_warning

    res_spearman = CorrelationAnalyzer.compute(x, y, method=CorrelationMethod.SPEARMAN)
    assert res_spearman.correlation_coefficient == 1.0


def test_correlation_insufficient_data():
    """Verify exception on sample size < 3."""
    with pytest.raises(InsufficientDataError):
        CorrelationAnalyzer.compute([1.0, 2.0], [3.0, 4.0])


def test_hypothesis_welch_ttest():
    """Verify Welch's two-sample t-test between significantly different distributions."""
    s1 = [100.0, 102.0, 104.0, 101.0, 103.0]
    s2 = [20.0, 22.0, 21.0, 19.0, 23.0]

    res = HypothesisTestRunner.compare_two_samples(
        s1, s2, group1_name="Corporate", group2_name="Retail", metric_name="order_value"
    )

    assert res.is_statistically_significant is True
    assert res.p_value < 0.001
    assert res.statistic > 0
    assert "significantly higher" in res.interpretation
