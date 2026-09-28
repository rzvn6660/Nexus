"""Deterministic statistical hypothesis testing between sample distributions."""

from typing import List, Dict, Any, Optional
import numpy as np
from scipy import stats
from app.analytics.core.types import HypothesisTestType, EffectSizeMagnitude
from app.analytics.core.models import (
    StatisticalTestResult,
    ConfidenceInterval,
    EffectSizeResult,
    AnovaResult,
    AnovaGroupSummary,
    AnovaPostHocComparison,
    ChiSquareContingencyResult,
    TwoProportionResult,
)
from app.analytics.core.exceptions import InsufficientDataError


def _classify_cohens_d(d: float) -> EffectSizeMagnitude:
    """Classify Cohen's d effect size magnitude."""
    abs_d = abs(d)
    if abs_d < 0.2:
        return EffectSizeMagnitude.NEGLIGIBLE
    elif abs_d < 0.5:
        return EffectSizeMagnitude.SMALL
    elif abs_d < 0.8:
        return EffectSizeMagnitude.MEDIUM
    return EffectSizeMagnitude.LARGE


def _classify_cramers_v(v: float) -> EffectSizeMagnitude:
    """Classify Cramér's V effect size magnitude."""
    if v < 0.1:
        return EffectSizeMagnitude.NEGLIGIBLE
    elif v < 0.3:
        return EffectSizeMagnitude.SMALL
    elif v < 0.5:
        return EffectSizeMagnitude.MEDIUM
    return EffectSizeMagnitude.LARGE


def _classify_eta_squared(eta2: float) -> EffectSizeMagnitude:
    """Classify Eta-squared effect size magnitude for ANOVA."""
    if eta2 < 0.01:
        return EffectSizeMagnitude.NEGLIGIBLE
    elif eta2 < 0.06:
        return EffectSizeMagnitude.SMALL
    elif eta2 < 0.14:
        return EffectSizeMagnitude.MEDIUM
    return EffectSizeMagnitude.LARGE


class HypothesisTestRunner:
    """Executes deterministic statistical significance and inferential tests across business data."""

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
        Calculates test statistic, p-value, Welch-Satterthwaite degrees of freedom,
        Cohen's d effect size, 95% confidence interval on difference of means,
        and distinguishes statistical vs practical significance.
        """
        arr1 = np.array(sample1, dtype=float)
        arr1 = arr1[~np.isnan(arr1) & ~np.isinf(arr1)]
        arr2 = np.array(sample2, dtype=float)
        arr2 = arr2[~np.isnan(arr2) & ~np.isinf(arr2)]

        n1 = len(arr1)
        n2 = len(arr2)

        if n1 < 2 or n2 < 2:
            raise InsufficientDataError(
                f"Both samples require at least 2 observations: got {n1} for {group1_name}, {n2} for {group2_name}."
            )

        mean1 = float(np.mean(arr1))
        mean2 = float(np.mean(arr2))
        var1 = float(np.var(arr1, ddof=1)) if n1 > 1 else 0.0
        var2 = float(np.var(arr2, ddof=1)) if n2 > 1 else 0.0
        diff = mean1 - mean2

        # Check for zero variance in both groups
        if var1 == 0 and var2 == 0:
            stat_val = 0.0
            p_val = 1.0 if mean1 == mean2 else 0.0
            df = None
            test_display_name = "Welch's Two-Sample t-test (Zero Variance)"
            ci = ConfidenceInterval(
                point_estimate=round(diff, 4),
                lower_bound=round(diff, 4),
                upper_bound=round(diff, 4),
                confidence_level=1.0 - alpha,
                margin_of_error=0.0,
            )
            effect_result = EffectSizeResult(
                metric_name="cohens_d",
                value=0.0,
                magnitude=EffectSizeMagnitude.NEGLIGIBLE,
                interpretation="Zero variance in both groups precludes effect size calculation.",
            )
        elif test_type == HypothesisTestType.MANN_WHITNEY_U:
            res = stats.mannwhitneyu(arr1, arr2, alternative="two-sided")
            stat_val = float(res.statistic)
            p_val = float(res.pvalue)
            df = None
            test_display_name = "Mann-Whitney U Rank-Sum Test"

            # Rank-biserial correlation: r = 1 - (2U / (n1 * n2))
            u_stat = float(res.statistic)
            rank_biserial = 1.0 - (2.0 * u_stat / (n1 * n2))
            mag = _classify_cohens_d(rank_biserial)
            effect_result = EffectSizeResult(
                metric_name="rank_biserial_correlation",
                value=round(rank_biserial, 4),
                magnitude=mag,
                interpretation=f"Non-parametric effect size is {mag.value} (r_rb={rank_biserial:.3f}).",
            )
            ci = None
        elif test_type == HypothesisTestType.STUDENT_TTEST:
            res = stats.ttest_ind(arr1, arr2, equal_var=True)
            stat_val = float(res.statistic)
            p_val = float(res.pvalue)
            df = float(n1 + n2 - 2)
            test_display_name = "Student's Two-Sample t-test (Equal Variances)"

            # Pooled standard deviation
            s_pooled = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / df) if df > 0 else 0.0
            cohen_d = (diff / s_pooled) if s_pooled > 0 else 0.0
            mag = _classify_cohens_d(cohen_d)
            effect_result = EffectSizeResult(
                metric_name="cohens_d",
                value=round(cohen_d, 4),
                magnitude=mag,
                interpretation=f"Standardized mean difference is {mag.value} (Cohen's d={cohen_d:.3f}).",
            )

            # CI on difference
            se_diff = s_pooled * np.sqrt(1.0 / n1 + 1.0 / n2) if s_pooled > 0 else 0.0
            t_crit = float(stats.t.ppf(1 - alpha / 2, df=df))
            moe = t_crit * se_diff
            ci = ConfidenceInterval(
                point_estimate=round(diff, 4),
                lower_bound=round(diff - moe, 4),
                upper_bound=round(diff + moe, 4),
                confidence_level=1.0 - alpha,
                margin_of_error=round(moe, 4),
            )
        else:
            # Welch's t-test (equal_var=False) - DEFAULT
            res = stats.ttest_ind(arr1, arr2, equal_var=False)
            stat_val = float(res.statistic)
            p_val = float(res.pvalue)
            raw_df = getattr(res, "df", None)
            if raw_df is not None:
                df = float(raw_df)
            else:
                # Welch-Satterthwaite formula
                num = (var1 / n1 + var2 / n2) ** 2
                den = ((var1 / n1) ** 2) / (n1 - 1) + ((var2 / n2) ** 2) / (n2 - 1)
                df = float(num / den) if den > 0 else float(n1 + n2 - 2)
            test_display_name = "Welch's Two-Sample t-test (Unequal Variances)"

            # Cohen's d using pooled variance
            denom_pooled = (n1 - 1) * var1 + (n2 - 1) * var2
            df_pooled = n1 + n2 - 2
            s_pooled = np.sqrt(denom_pooled / df_pooled) if df_pooled > 0 else 0.0
            cohen_d = (diff / s_pooled) if s_pooled > 0 else 0.0
            mag = _classify_cohens_d(cohen_d)
            effect_result = EffectSizeResult(
                metric_name="cohens_d",
                value=round(cohen_d, 4),
                magnitude=mag,
                interpretation=f"Standardized mean difference is {mag.value} (Cohen's d={cohen_d:.3f}).",
            )

            # Welch CI on difference
            se_diff = np.sqrt(var1 / n1 + var2 / n2)
            t_crit = float(stats.t.ppf(1 - alpha / 2, df=df)) if df > 0 else 1.96
            moe = t_crit * se_diff
            ci = ConfidenceInterval(
                point_estimate=round(diff, 4),
                lower_bound=round(diff - moe, 4),
                upper_bound=round(diff + moe, 4),
                confidence_level=1.0 - alpha,
                margin_of_error=round(moe, 4),
            )

        is_sig = p_val < alpha

        # Practical vs statistical significance synthesis
        if is_sig:
            direction_desc = "significantly higher" if diff > 0 else "significantly lower"
            interp = (
                f"There is a statistically significant difference in {metric_name} between {group1_name} "
                f"(mean={mean1:.2f}) and {group2_name} (mean={mean2:.2f}) at alpha={alpha} (p={p_val:.4f}). "
                f"{group1_name} is {direction_desc} than {group2_name}."
            )
            if effect_result.magnitude == EffectSizeMagnitude.NEGLIGIBLE:
                practical_desc = (
                    "Statistically significant but practically negligible effect size. "
                    "The difference may be an artifact of sample size rather than a substantial business divergence. "
                    "Business significance is NOT automatically implied by statistical significance alone."
                )
            else:
                practical_desc = (
                    f"Statistically significant with {effect_result.magnitude.value} empirical effect size ({diff:+.2f} per unit). "
                    "Whether this translates to actionable business significance depends on commercial unit economics, "
                    "implementation costs, and domain thresholds; business significance cannot be decided from p-values alone."
                )
        else:
            interp = (
                f"The observed difference in {metric_name} between {group1_name} (mean={mean1:.2f}) "
                f"and {group2_name} (mean={mean2:.2f}) is NOT statistically significant at alpha={alpha} (p={p_val:.4f}). "
                f"The variation is consistent with random chance."
            )
            practical_desc = (
                "Insufficient evidence to claim a true difference between groups; "
                "observed variation is within expected random sampling fluctuations."
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
            confidence_interval=ci,
            effect_size=effect_result,
            practical_significance=practical_desc,
            interpretation=interp,
            assumptions_and_limitations=[
                "Welch's t-test does not assume equal variances, but assumes independence between observations.",
                "Central Limit Theorem applies for moderate/large sample sizes (n >= 30); for highly skewed small samples, consider Mann-Whitney U.",
                "Statistical significance reflects association and sampling probability, NOT causal mechanisms.",
            ],
        )

    @classmethod
    def compare_paired_samples(
        cls,
        before: List[float],
        after: List[float],
        group_name: str = "Pre vs Post",
        metric_name: str = "metric",
        alpha: float = 0.05,
        use_non_parametric: bool = False,
    ) -> StatisticalTestResult:
        """
        Conduct a paired two-sample hypothesis test (e.g. pre- vs post-intervention).
        """
        if len(before) != len(after):
            raise ValueError(f"Paired test requires equal sample lengths: before has {len(before)}, after has {len(after)}.")

        clean_pairs = [
            (b, a) for b, a in zip(before, after)
            if b is not None and a is not None
            and not np.isnan(b) and not np.isnan(a)
            and not np.isinf(b) and not np.isinf(a)
        ]
        n = len(clean_pairs)
        if n < 2:
            raise InsufficientDataError(f"Paired test requires at least 2 valid pairs, got {n}.")

        b_arr = np.array([p[0] for p in clean_pairs], dtype=float)
        a_arr = np.array([p[1] for p in clean_pairs], dtype=float)
        diffs = a_arr - b_arr
        mean_diff = float(np.mean(diffs))
        std_diff = float(np.std(diffs, ddof=1)) if n > 1 else 0.0

        if use_non_parametric:
            test_type = HypothesisTestType.WILCOXON_SIGNED_RANK
            test_name = "Wilcoxon Signed-Rank Test (Paired Non-Parametric)"
            # Check if all diffs are zero
            if np.all(diffs == 0):
                stat_val = 0.0
                p_val = 1.0
            else:
                res = stats.wilcoxon(diffs, alternative="two-sided")
                stat_val = float(res.statistic)
                p_val = float(res.pvalue)
            df = None
            ci = None
            effect_result = None
        else:
            test_type = HypothesisTestType.PAIRED_TTEST
            test_name = "Paired Student's t-test"
            if std_diff == 0:
                stat_val = 0.0
                p_val = 1.0 if mean_diff == 0 else 0.0
                df = float(n - 1)
            else:
                res = stats.ttest_rel(a_arr, b_arr)
                stat_val = float(res.statistic)
                p_val = float(res.pvalue)
                df = float(n - 1)

            # Cohen's d for paired differences: d = mean_diff / std_diff
            cohen_d = (mean_diff / std_diff) if std_diff > 0 else 0.0
            mag = _classify_cohens_d(cohen_d)
            effect_result = EffectSizeResult(
                metric_name="cohens_d_paired",
                value=round(cohen_d, 4),
                magnitude=mag,
                interpretation=f"Standardized paired change magnitude is {mag.value} (d={cohen_d:.3f}).",
            )

            # CI on mean difference
            se_diff = std_diff / np.sqrt(n) if std_diff > 0 else 0.0
            t_crit = float(stats.t.ppf(1 - alpha / 2, df=n - 1)) if n > 1 else 1.96
            moe = t_crit * se_diff
            ci = ConfidenceInterval(
                point_estimate=round(mean_diff, 4),
                lower_bound=round(mean_diff - moe, 4),
                upper_bound=round(mean_diff + moe, 4),
                confidence_level=1.0 - alpha,
                margin_of_error=round(moe, 4),
            )

        is_sig = p_val < alpha
        direction_text = "significant increase" if mean_diff > 0 else "significant decrease"
        interp = (
            f"Paired comparison of {group_name} on {metric_name} reveals a {direction_text} "
            f"(mean difference = {mean_diff:+.2f}, p={p_val:.4f}) at alpha={alpha}."
            if is_sig else
            f"Paired comparison of {group_name} on {metric_name} shows no statistically significant change "
            f"(mean difference = {mean_diff:+.2f}, p={p_val:.4f}) at alpha={alpha}."
        )

        return StatisticalTestResult(
            test_type=test_type,
            test_name=test_name,
            metric=metric_name,
            statistic=round(stat_val, 4),
            p_value=round(p_val, 6),
            degrees_of_freedom=round(df, 2) if df is not None else None,
            sample_size_1=n,
            sample_size_2=n,
            mean_1=round(float(np.mean(b_arr)), 4),
            mean_2=round(float(np.mean(a_arr)), 4),
            is_statistically_significant=is_sig,
            alpha=alpha,
            confidence_interval=ci,
            effect_size=effect_result,
            interpretation=interp,
            assumptions_and_limitations=[
                "Paired t-test assumes the paired differences are approximately normally distributed.",
                "Pairs must represent genuinely matched or before-and-after observations.",
            ],
        )

    @classmethod
    def test_one_sample(
        cls,
        sample: List[float],
        hypothesized_mean: float,
        metric_name: str = "metric",
        alpha: float = 0.05,
    ) -> StatisticalTestResult:
        """
        Conduct a one-sample Student's t-test comparing sample mean against a benchmark.
        """
        arr = np.array(sample, dtype=float)
        arr = arr[~np.isnan(arr) & ~np.isinf(arr)]
        n = len(arr)
        if n < 2:
            raise InsufficientDataError(f"One-sample t-test requires at least 2 observations, got {n}.")

        sample_mean = float(np.mean(arr))
        sample_std = float(np.std(arr, ddof=1))

        if sample_std == 0:
            stat_val = 0.0
            p_val = 1.0 if sample_mean == hypothesized_mean else 0.0
            df = float(n - 1)
        else:
            res = stats.ttest_1samp(arr, hypothesized_mean)
            stat_val = float(res.statistic)
            p_val = float(res.pvalue)
            df = float(n - 1)

        diff = sample_mean - hypothesized_mean
        cohen_d = (diff / sample_std) if sample_std > 0 else 0.0
        mag = _classify_cohens_d(cohen_d)

        se = sample_std / np.sqrt(n) if sample_std > 0 else 0.0
        t_crit = float(stats.t.ppf(1 - alpha / 2, df=n - 1))
        moe = t_crit * se
        ci = ConfidenceInterval(
            point_estimate=round(sample_mean, 4),
            lower_bound=round(sample_mean - moe, 4),
            upper_bound=round(sample_mean + moe, 4),
            confidence_level=1.0 - alpha,
            margin_of_error=round(moe, 4),
        )

        is_sig = p_val < alpha
        direction_text = "significantly higher than" if diff > 0 else "significantly lower than"
        interp = (
            f"Sample mean ({sample_mean:.2f}) is {direction_text} hypothesized benchmark ({hypothesized_mean:.2f}) "
            f"at alpha={alpha} (p={p_val:.4f})."
            if is_sig else
            f"Sample mean ({sample_mean:.2f}) does not differ significantly from benchmark ({hypothesized_mean:.2f}) "
            f"at alpha={alpha} (p={p_val:.4f})."
        )

        return StatisticalTestResult(
            test_type=HypothesisTestType.ONE_SAMPLE_TTEST,
            test_name="One-Sample Student's t-test",
            metric=metric_name,
            statistic=round(stat_val, 4),
            p_value=round(p_val, 6),
            degrees_of_freedom=round(df, 2),
            sample_size_1=n,
            sample_size_2=None,
            mean_1=round(sample_mean, 4),
            mean_2=round(hypothesized_mean, 4),
            is_statistically_significant=is_sig,
            alpha=alpha,
            confidence_interval=ci,
            effect_size=EffectSizeResult(
                metric_name="cohens_d_onesample",
                value=round(cohen_d, 4),
                magnitude=mag,
                interpretation=f"Standardized deviation from benchmark is {mag.value} (d={cohen_d:.3f}).",
            ),
            interpretation=interp,
            assumptions_and_limitations=[
                "Assumes independent and approximately normally distributed sample observations.",
            ],
        )

    @classmethod
    def run_one_way_anova(
        cls,
        groups: Dict[str, List[float]],
        metric_name: str = "metric",
        alpha: float = 0.05,
    ) -> AnovaResult:
        """
        Conduct a One-Way Analysis of Variance (ANOVA) across 3 or more groups.
        """
        if len(groups) < 3:
            raise ValueError(f"One-Way ANOVA requires at least 3 groups, got {len(groups)}.")

        clean_groups: Dict[str, np.ndarray] = {}
        group_summaries: List[AnovaGroupSummary] = []
        all_vals: List[float] = []

        for name, vals in groups.items():
            arr = np.array(vals, dtype=float)
            arr = arr[~np.isnan(arr) & ~np.isinf(arr)]
            if len(arr) < 2:
                raise InsufficientDataError(f"Each ANOVA group must have >= 2 observations, group '{name}' has {len(arr)}.")
            clean_groups[name] = arr
            all_vals.extend(arr.tolist())
            group_summaries.append(
                AnovaGroupSummary(
                    group_name=name,
                    sample_size=len(arr),
                    mean=round(float(np.mean(arr)), 4),
                    std_dev=round(float(np.std(arr, ddof=1)), 4),
                    median=round(float(np.median(arr)), 4),
                )
            )

        k = len(clean_groups)
        n_total = len(all_vals)
        df_between = k - 1
        df_within = n_total - k

        # Execute One-Way ANOVA
        arrays = list(clean_groups.values())
        res = stats.f_oneway(*arrays)
        f_stat = float(res.statistic)
        p_val = float(res.pvalue)

        # Eta-squared calculation: SS_between / SS_total
        grand_mean = np.mean(all_vals)
        ss_between = float(sum(len(arr) * ((np.mean(arr) - grand_mean) ** 2) for arr in arrays))
        ss_total = float(sum((x - grand_mean) ** 2 for x in all_vals))
        eta_squared = (ss_between / ss_total) if ss_total > 0 else 0.0
        mag = _classify_eta_squared(eta_squared)

        is_sig = p_val < alpha

        # Post-hoc pairwise analysis when omnibus test is statistically significant
        post_hoc_list: Optional[List[AnovaPostHocComparison]] = None
        post_hoc_method: Optional[str] = None

        if is_sig:
            post_hoc_list = []
            post_hoc_method = "holm"
            group_names = list(clean_groups.keys())
            pair_records = []

            for i in range(len(group_names)):
                for j in range(i + 1, len(group_names)):
                    g1, g2 = group_names[i], group_names[j]
                    a1, a2 = clean_groups[g1], clean_groups[g2]
                    m1, m2 = float(np.mean(a1)), float(np.mean(a2))
                    diff_val = m1 - m2
                    v1 = float(np.var(a1, ddof=1)) if len(a1) > 1 else 0.0
                    v2 = float(np.var(a2, ddof=1)) if len(a2) > 1 else 0.0
                    n1, n2 = len(a1), len(a2)

                    tt_res = stats.ttest_ind(a1, a2, equal_var=False)
                    t_stat = float(tt_res.statistic)
                    p_raw = float(tt_res.pvalue)

                    # Welch df and CI
                    num_df = (v1 / n1 + v2 / n2) ** 2
                    den_df = ((v1 / n1) ** 2) / (n1 - 1) + ((v2 / n2) ** 2) / (n2 - 1)
                    w_df = float(num_df / den_df) if den_df > 0 else float(n1 + n2 - 2)
                    se_d = np.sqrt(v1 / n1 + v2 / n2)
                    t_crit = float(stats.t.ppf(1 - alpha / 2, df=w_df)) if w_df > 0 else 1.96
                    moe = t_crit * se_d
                    ci = ConfidenceInterval(
                        point_estimate=round(diff_val, 4),
                        lower_bound=round(diff_val - moe, 4),
                        upper_bound=round(diff_val + moe, 4),
                        confidence_level=1.0 - alpha,
                        margin_of_error=round(moe, 4),
                    )

                    # Cohen's d
                    s_pool = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)) if (n1 + n2 > 2) else 1.0
                    cd = (diff_val / s_pool) if s_pool > 0 else 0.0
                    eff = EffectSizeResult(
                        metric_name="cohens_d",
                        value=round(cd, 4),
                        magnitude=_classify_cohens_d(cd),
                        interpretation=f"Pairwise mean difference effect size is {_classify_cohens_d(cd).value} (d={cd:.3f}).",
                    )

                    pair_records.append({
                        "g1": g1, "g2": g2, "diff": diff_val, "t_stat": t_stat,
                        "p_raw": p_raw, "ci": ci, "eff": eff,
                    })

            from app.analytics.statistics.multiple_testing import MultipleTestingCorrector
            raw_ps = [p["p_raw"] for p in pair_records]
            adj_res = MultipleTestingCorrector.adjust_p_values(raw_ps, method="holm", alpha=alpha)

            for p_rec, p_adj, rej in zip(pair_records, adj_res.adjusted_p_values, adj_res.rejected):
                post_hoc_list.append(
                    AnovaPostHocComparison(
                        group_1=p_rec["g1"],
                        group_2=p_rec["g2"],
                        mean_difference=round(p_rec["diff"], 4),
                        statistic=round(p_rec["t_stat"], 4),
                        p_value_raw=round(p_rec["p_raw"], 6),
                        p_value_adjusted=round(p_adj, 6),
                        correction_method="holm",
                        is_statistically_significant=rej,
                        confidence_interval=p_rec["ci"],
                        effect_size=p_rec["eff"],
                    )
                )

        interp = (
            f"One-Way ANOVA across {k} groups on {metric_name} reveals statistically significant variation "
            f"(F({df_between}, {df_within}) = {f_stat:.2f}, p={p_val:.4f}) at alpha={alpha}. "
            f"Group membership accounts for approximately {eta_squared * 100:.1f}% of total variance ({mag.value} effect)."
            if is_sig else
            f"One-Way ANOVA indicates no statistically significant difference among the {k} group means "
            f"(F({df_between}, {df_within}) = {f_stat:.2f}, p={p_val:.4f}) at alpha={alpha}."
        )

        return AnovaResult(
            metric_name=metric_name,
            f_statistic=round(f_stat, 4),
            p_value=round(p_val, 6),
            df_between=df_between,
            df_within=df_within,
            eta_squared=round(eta_squared, 4),
            effect_magnitude=mag,
            is_statistically_significant=is_sig,
            alpha=alpha,
            groups=group_summaries,
            post_hoc_comparisons=post_hoc_list,
            post_hoc_correction_method=post_hoc_method,
            interpretation=interp,
            assumptions_and_limitations=[
                "Assumes continuous dependent variable and independent observations across groups.",
                "Assumes homogeneity of variance across groups (homoskedasticity).",
                "Assumes approximately normal distribution within each group.",
                "Pairwise post-hoc comparisons use Welch's t-test with Holm-Bonferroni correction.",
            ],
        )

    @classmethod
    def run_chi_square_contingency(
        cls,
        contingency_table: Dict[str, Dict[str, int]],
        variable_x: str = "variable_x",
        variable_y: str = "variable_y",
        alpha: float = 0.05,
    ) -> ChiSquareContingencyResult:
        """
        Conduct a Chi-square test of independence on a 2D contingency table.
        """
        row_keys = list(contingency_table.keys())
        if len(row_keys) < 2:
            raise ValueError(f"Contingency table requires at least 2 rows, got {len(row_keys)}.")

        col_keys = list(contingency_table[row_keys[0]].keys())
        if len(col_keys) < 2:
            raise ValueError(f"Contingency table requires at least 2 columns, got {len(col_keys)}.")

        # Build matrix
        matrix: List[List[int]] = []
        for r in row_keys:
            row = [int(contingency_table[r].get(c, 0)) for c in col_keys]
            matrix.append(row)

        mat_arr = np.array(matrix, dtype=int)
        total_n = int(np.sum(mat_arr))
        if total_n < 10:
            raise InsufficientDataError(f"Chi-square test requires total sample size >= 10, got {total_n}.")

        chi2_res = stats.chi2_contingency(mat_arr)
        chi2_stat = float(chi2_res.statistic)
        p_val = float(chi2_res.pvalue)
        dof = int(chi2_res.dof)
        expected = chi2_res.expected_freq

        # Cramér's V: V = sqrt( chi2 / (n * min(r-1, c-1)) )
        min_dim = min(len(row_keys) - 1, len(col_keys) - 1)
        cramers_v = np.sqrt(chi2_stat / (total_n * min_dim)) if (total_n > 0 and min_dim > 0) else 0.0
        mag = _classify_cramers_v(cramers_v)

        expected_dict: Dict[str, Dict[str, float]] = {}
        for i, r in enumerate(row_keys):
            expected_dict[r] = {}
            for j, c in enumerate(col_keys):
                expected_dict[r][c] = round(float(expected[i, j]), 2)

        # Validate Cochran's Rule: >= 80% cells with expected freq >= 5, all >= 1
        min_expected = float(np.min(expected))
        cells_below_5 = int(np.sum(expected < 5.0))
        total_cells = int(expected.size)
        pct_below_5 = float((cells_below_5 / total_cells) * 100.0)
        cochran_valid = bool(min_expected >= 1.0 and pct_below_5 <= 20.0)

        # Fisher's exact test for 2x2 tables
        fishers_p: Optional[float] = None
        fishers_or: Optional[float] = None
        if len(row_keys) == 2 and len(col_keys) == 2:
            try:
                fo_stat, fp_val = stats.fisher_exact(mat_arr)
                fishers_p = round(float(fp_val), 6)
                fishers_or = round(float(fo_stat), 4) if not np.isinf(fo_stat) else None
            except Exception:
                pass

        cochran_warn: Optional[str] = None
        if not cochran_valid:
            cochran_warn = (
                f"Cochran's rule violated: {pct_below_5:.1f}% of cells have expected frequency < 5 "
                f"(minimum expected is {min_expected:.2f}). Chi-square asymptotic p-value may be unreliable."
            )

        is_sig = p_val < alpha
        interp = (
            f"Chi-square test demonstrates a statistically significant association between {variable_x} and {variable_y} "
            f"(chi2({dof}) = {chi2_stat:.2f}, p={p_val:.4f}, Cramér's V={cramers_v:.3f}, {mag.value} association) at alpha={alpha}."
            if is_sig else
            f"No statistically significant relationship detected between {variable_x} and {variable_y} "
            f"(chi2({dof}) = {chi2_stat:.2f}, p={p_val:.4f}). The variables are statistically independent."
        )

        limitations = [
            "Assumes mutually exclusive categories and independent observations.",
            "Standard Chi-square requires expected cell counts to be >= 5 in at least 80% of cells.",
            "Association reflects dependency, NOT direct causality.",
        ]
        if cochran_warn:
            limitations.append(cochran_warn)
            if fishers_p is not None:
                limitations.append(
                    f"Fisher's exact test computed as safe authoritative alternative for 2x2 table: p={fishers_p:.4f}."
                )

        return ChiSquareContingencyResult(
            variable_x=variable_x,
            variable_y=variable_y,
            chi2_statistic=round(chi2_stat, 4),
            p_value=round(p_val, 6),
            degrees_of_freedom=dof,
            cramers_v=round(float(cramers_v), 4),
            effect_magnitude=mag,
            is_statistically_significant=is_sig,
            alpha=alpha,
            sample_size=total_n,
            contingency_table=contingency_table,
            expected_frequencies=expected_dict,
            expected_frequencies_valid=cochran_valid,
            cells_below_five_pct=round(pct_below_5, 2),
            min_expected_frequency=round(min_expected, 2),
            fishers_exact_p_value=fishers_p,
            fishers_exact_odds_ratio=fishers_or,
            cochran_warning=cochran_warn,
            interpretation=interp,
            assumptions_and_limitations=limitations,
        )

    @classmethod
    def test_two_proportions(
        cls,
        successes_1: int,
        total_1: int,
        successes_2: int,
        total_2: int,
        group1_name: str = "Group 1",
        group2_name: str = "Group 2",
        alpha: float = 0.05,
    ) -> TwoProportionResult:
        """
        Conduct a two-proportion z-test comparing rates (e.g. conversion, retention).
        """
        if total_1 < 5 or total_2 < 5:
            raise InsufficientDataError(f"Each group requires at least 5 trials: got {total_1} and {total_2}.")

        p1 = float(successes_1 / total_1)
        p2 = float(successes_2 / total_2)
        diff = p1 - p2

        # Pooled sample proportion for standard error under null hypothesis
        p_pool = (successes_1 + successes_2) / (total_1 + total_2)
        se_pool = np.sqrt(p_pool * (1.0 - p_pool) * (1.0 / total_1 + 1.0 / total_2))

        if se_pool == 0:
            z_stat = 0.0
            p_val = 1.0 if p1 == p2 else 0.0
        else:
            z_stat = float(diff / se_pool)
            p_val = float(2.0 * (1.0 - stats.norm.cdf(abs(z_stat))))

        # Unpooled standard error for confidence interval on difference
        se_unpool = np.sqrt((p1 * (1.0 - p1) / total_1) + (p2 * (1.0 - p2) / total_2))
        z_crit = float(stats.norm.ppf(1 - alpha / 2))
        moe = z_crit * se_unpool
        ci = ConfidenceInterval(
            point_estimate=round(diff, 4),
            lower_bound=round(diff - moe, 4),
            upper_bound=round(diff + moe, 4),
            confidence_level=1.0 - alpha,
            margin_of_error=round(moe, 4),
        )

        relative_diff = ((p1 - p2) / p2 * 100.0) if p2 > 0 else None
        is_sig = p_val < alpha

        direction = "significantly higher than" if diff > 0 else "significantly lower than"
        interp = (
            f"{group1_name} proportion ({p1 * 100:.1f}%) is {direction} {group2_name} ({p2 * 100:.1f}%) "
            f"at alpha={alpha} (z={z_stat:.2f}, p={p_val:.4f}). Estimated difference: {diff * 100:+.1f}% points."
            if is_sig else
            f"The difference between {group1_name} ({p1 * 100:.1f}%) and {group2_name} ({p2 * 100:.1f}%) "
            f"is NOT statistically significant at alpha={alpha} (z={z_stat:.2f}, p={p_val:.4f})."
        )

        return TwoProportionResult(
            group1_name=group1_name,
            group2_name=group2_name,
            successes_1=successes_1,
            total_1=total_1,
            proportion_1=round(p1, 4),
            successes_2=successes_2,
            total_2=total_2,
            proportion_2=round(p2, 4),
            absolute_difference=round(diff, 4),
            relative_difference_pct=round(relative_diff, 2) if relative_diff is not None else None,
            z_statistic=round(z_stat, 4),
            p_value=round(p_val, 6),
            confidence_interval=ci,
            is_statistically_significant=is_sig,
            alpha=alpha,
            interpretation=interp,
            assumptions_and_limitations=[
                "Assumes independent trials with constant probability of success within each group.",
                "Normal approximation requires np >= 5 and n(1-p) >= 5 in both samples.",
            ],
        )
