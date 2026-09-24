"""Deterministic statistical hypothesis testing between sample distributions."""

from typing import List, Optional
import numpy as np
from scipy import stats
from app.analytics.core.types import HypothesisTestType
from app.analytics.core.models import StatisticalTestResult
from app.analytics.core.exceptions import InsufficientDataError


class HypothesisTestRunner:
    """Executes statistical significance tests between two independent sample groups."""

    @classmethod
    def compare_two_samples(
        cls,
        sample1: List[float],
        sample2: List[float],
        group1_name: str = "Group 1",
        group2_name: str = "Group 2",
        metric_name: str = "order_value",
        test_type: HypothesisTestType = HypothesisTestType.TWO_SAMPLE_TTEST,
        alpha: float = 0.05,
    ) -> StatisticalTestResult:
        """
        Conduct a two-sample hypothesis test comparing sample1 against sample2.
        Default: Welch's two-sample t-test (robust against unequal variances).
        """
        arr1 = np.array(sample1, dtype=float)
        arr1 = arr1[~np.isnan(arr1)]
        arr2 = np.array(sample2, dtype=float)
        arr2 = arr2[~np.isnan(arr2)]

        n1 = len(arr1)
        n2 = len(arr2)

        if n1 < 2 or n2 < 2:
            raise InsufficientDataError(
                f"Both samples require at least 2 observations: got {n1} for {group1_name}, {n2} for {group2_name}."
            )

        mean1 = float(np.mean(arr1))
        mean2 = float(np.mean(arr2))

        # Check for zero variance in both groups
        if np.var(arr1) == 0 and np.var(arr2) == 0:
            stat_val = 0.0
            p_val = 1.0 if mean1 == mean2 else 0.0
            df = None
            test_display_name = "Welch's Two-Sample t-test (Zero Variance)"
        elif test_type == HypothesisTestType.MANN_WHITNEY_U:
            res = stats.mannwhitneyu(arr1, arr2, alternative="two-sided")
            stat_val = float(res.statistic)
            p_val = float(res.pvalue)
            df = None
            test_display_name = "Mann-Whitney U Rank-Sum Test"
        else:
            # Welch's t-test (equal_var=False)
            res = stats.ttest_ind(arr1, arr2, equal_var=False)
            stat_val = float(res.statistic)
            p_val = float(res.pvalue)
            df = getattr(res, "df", None)
            df = float(df) if df is not None else None
            test_display_name = "Welch's Two-Sample t-test (Unequal Variances)"

        is_sig = p_val < alpha

        diff = mean1 - mean2
        if is_sig:
            direction_desc = "significantly higher" if diff > 0 else "significantly lower"
            interp = (
                f"There is a statistically significant difference in {metric_name} between {group1_name} "
                f"(mean={mean1:.2f}) and {group2_name} (mean={mean2:.2f}) at alpha={alpha} (p={p_val:.4f}). "
                f"{group1_name} is {direction_desc} than {group2_name}."
            )
        else:
            interp = (
                f"The observed difference in {metric_name} between {group1_name} (mean={mean1:.2f}) "
                f"and {group2_name} (mean={mean2:.2f}) is NOT statistically significant at alpha={alpha} (p={p_val:.4f}). "
                f"The variation is consistent with random chance."
            )

        return StatisticalTestResult(
            test_type=test_type,
            test_name=test_display_name,
            metric=metric_name,
            statistic=round(stat_val, 4),
            p_value=round(p_val, 6),
            degrees_of_freedom=round(df, 2) if df is not None else None,
            sample_size_1=n1,
            sample_size_2=n2,
            mean_1=round(mean1, 4),
            mean_2=round(mean2, 4),
            is_statistically_significant=is_sig,
            alpha=alpha,
            interpretation=interp,
            assumptions_and_limitations=[
                "Welch's t-test assumes approximately normal sampling distributions or sufficient sample size by Central Limit Theorem.",
                "Statistical significance indicates association, not causality.",
            ],
        )
