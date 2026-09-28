"""Deterministic analytical method selection layer and statistical guardrails."""

from typing import List, Dict, Any, Optional
import numpy as np
from scipy import stats

from app.analytics.core.types import (
    AnalyticalQuestionType,
    ChartType,
    HypothesisTestType,
    CorrelationMethod,
)
from app.analytics.core.models import (
    AnalyticalMethodRecommendation,
)
from app.analytics.statistics.visual_analytics import ChartAdvisor


class AnalyticalMethodSelector:
    """
    Deterministic statistical decision layer.

    Given an analytical question archetype and underlying data series, this layer:
    1. Evaluates sample sufficiency and missingness guardrails
    2. Validates statistical assumptions (normality, homoskedasticity, zero variance)
    3. Recommends the appropriate statistical test or non-parametric fallback
    4. Pairs the recommendation with an analytical, non-decorative chart recommendation
    """

    @classmethod
    def recommend_method(
        cls,
        question_type: AnalyticalQuestionType,
        data: Optional[Dict[str, List[Any]]] = None,
        is_paired: bool = False,
        alpha: float = 0.05,
    ) -> AnalyticalMethodRecommendation:
        """
        Evaluate data suitability and deterministically select the valid statistical method.
        """
        warnings: List[str] = []
        assumptions_evaluated: List[str] = []
        fallback: Optional[str] = None
        sufficiency = "sufficient"
        data = data or {}

        # 1. Evaluate missingness and sample sizes across provided series
        series_info: Dict[str, Dict[str, Any]] = {}
        for key, vals in data.items():
            total_count = len(vals)
            valid_vals = [
                float(v) for v in vals
                if v is not None and not np.isnan(float(v)) and not np.isinf(float(v))
            ]
            valid_count = len(valid_vals)
            missing_count = total_count - valid_count
            missing_pct = (missing_count / total_count * 100.0) if total_count > 0 else 100.0

            if missing_pct > 80.0:
                warnings.append(f"Series '{key}' has excessive missingness ({missing_pct:.1f}%); statistical inference may be invalid.")
                sufficiency = "insufficient"
            elif missing_pct > 20.0:
                warnings.append(f"Series '{key}' has {missing_pct:.1f}% missing values; non-response/attrition bias may be present.")
                if sufficiency != "insufficient":
                    sufficiency = "marginal"

            # Check zero variance
            has_zero_var = (valid_count > 1 and np.var(valid_vals) == 0.0)
            if has_zero_var:
                warnings.append(f"Series '{key}' exhibits zero variance (all {valid_count} values identical).")

            series_info[key] = {
                "valid": valid_vals,
                "n": valid_count,
                "has_zero_var": has_zero_var,
            }

        from app.analytics.statistics.normality import evaluate_normality

        # Explicit validation for paired observation vs independent group comparison
        if is_paired and question_type == AnalyticalQuestionType.GROUP_COMPARISON:
            question_type = AnalyticalQuestionType.PAIRED_COMPARISON
            warnings.append(
                "Paired observation structure detected; rerouting from independent group comparison to paired difference analysis "
                "to prevent violation of observation independence."
            )

        # 2. Select Method based on Question Type and Assumption Checks
        if question_type == AnalyticalQuestionType.GROUP_COMPARISON:
            keys = list(series_info.keys())
            chart = ChartAdvisor.recommend_for_question(question_type).chart_type

            if len(keys) == 2:
                s1, s2 = series_info[keys[0]]["valid"], series_info[keys[1]]["valid"]
                n1, n2 = len(s1), len(s2)

                if n1 < 2 or n2 < 2:
                    return AnalyticalMethodRecommendation(
                        question_type=question_type,
                        recommended_method=HypothesisTestType.TWO_SAMPLE_TTEST.value,
                        recommended_chart=chart,
                        sample_sufficiency="insufficient",
                        data_quality_warnings=warnings + [f"Two-sample comparison requires at least 2 observations per group (got {n1}, {n2})."],
                        assumptions_evaluated=["Sample size threshold check: FAILED."],
                        fallback_recommended=None,
                        rationale="Insufficient observations to compute parametric or non-parametric group statistics.",
                    )

                # Unified Normality Evaluation across both groups
                norm1 = evaluate_normality(s1, alpha=alpha)
                norm2 = evaluate_normality(s2, alpha=alpha)
                is_normal = norm1.is_normal and norm2.is_normal
                assumptions_evaluated.append(
                    f"Normality check (unified): group1 ({norm1.test_used}) p={norm1.p_value}, "
                    f"group2 ({norm2.test_used}) p={norm2.p_value} -> {'Normal' if is_normal else 'Non-normal'}."
                )

                # Never select a parametric test solely because n >= 30 when data violates normality
                if not is_normal:
                    return AnalyticalMethodRecommendation(
                        question_type=question_type,
                        recommended_method=HypothesisTestType.MANN_WHITNEY_U.value,
                        recommended_chart=chart,
                        sample_sufficiency="sufficient" if n1 >= 5 and n2 >= 5 else "marginal",
                        data_quality_warnings=warnings,
                        assumptions_evaluated=assumptions_evaluated,
                        fallback_recommended=HypothesisTestType.TWO_SAMPLE_TTEST.value,
                        rationale=(
                            "Non-parametric Mann-Whitney U test recommended because sample distributions deviate from normality. "
                            "Parametric tests are not recommended solely based on sample size when distributional shape is skewed or heavy-tailed."
                        ),
                    )

                # Check Variance Homogeneity (Levene's test)
                p_levene = 1.0
                try:
                    if not series_info[keys[0]]["has_zero_var"] and not series_info[keys[1]]["has_zero_var"]:
                        _, p_levene = stats.levene(s1, s2)
                except Exception:
                    p_levene = 0.0

                assumptions_evaluated.append(f"Homogeneity of variance (Levene's test): p={p_levene:.4f}.")

                if p_levene < alpha:
                    assumptions_evaluated.append("Unequal group variances confirmed; Welch's t-test mandatory over standard Student's t-test.")
                    return AnalyticalMethodRecommendation(
                        question_type=question_type,
                        recommended_method=HypothesisTestType.TWO_SAMPLE_TTEST.value,
                        recommended_chart=chart,
                        sample_sufficiency=sufficiency,
                        data_quality_warnings=warnings,
                        assumptions_evaluated=assumptions_evaluated,
                        fallback_recommended=HypothesisTestType.MANN_WHITNEY_U.value,
                        rationale="Welch's Two-Sample t-test selected: robust against unequal group variances without requiring homoskedasticity.",
                    )
                else:
                    return AnalyticalMethodRecommendation(
                        question_type=question_type,
                        recommended_method=HypothesisTestType.TWO_SAMPLE_TTEST.value,
                        recommended_chart=chart,
                        sample_sufficiency=sufficiency,
                        data_quality_warnings=warnings,
                        assumptions_evaluated=assumptions_evaluated,
                        fallback_recommended=HypothesisTestType.MANN_WHITNEY_U.value,
                        rationale="Welch's Two-Sample t-test selected as the conservative standard for independent continuous comparisons.",
                    )

            elif len(keys) >= 3:
                # 3+ groups: ANOVA or Kruskal-Wallis
                assumptions_evaluated.append(f"Multi-group comparison with {len(keys)} groups.")
                all_normal = True
                for k in keys:
                    arr = series_info[k]["valid"]
                    norm_k = evaluate_normality(arr, alpha=alpha)
                    if not norm_k.is_normal:
                        all_normal = False
                        assumptions_evaluated.append(f"Group '{k}' violated normality ({norm_k.test_used}, p={norm_k.p_value}).")

                if not all_normal:
                    return AnalyticalMethodRecommendation(
                        question_type=question_type,
                        recommended_method=HypothesisTestType.KRUSKAL_WALLIS.value,
                        recommended_chart=chart,
                        sample_sufficiency=sufficiency,
                        data_quality_warnings=warnings,
                        assumptions_evaluated=assumptions_evaluated,
                        fallback_recommended=HypothesisTestType.ONE_WAY_ANOVA.value,
                        rationale="Kruskal-Wallis non-parametric ANOVA recommended due to distributional deviations in sample groups.",
                    )
                else:
                    return AnalyticalMethodRecommendation(
                        question_type=question_type,
                        recommended_method=HypothesisTestType.ONE_WAY_ANOVA.value,
                        recommended_chart=chart,
                        sample_sufficiency=sufficiency,
                        data_quality_warnings=warnings,
                        assumptions_evaluated=assumptions_evaluated + ["Group distributions satisfy normality requirements."],
                        fallback_recommended=HypothesisTestType.KRUSKAL_WALLIS.value,
                        rationale="One-Way ANOVA recommended for testing equality of means across 3+ independent groups.",
                    )

        elif question_type == AnalyticalQuestionType.PAIRED_COMPARISON:
            chart = ChartAdvisor.recommend_for_question(question_type).chart_type
            keys = list(series_info.keys())
            if len(keys) == 2:
                s1, s2 = series_info[keys[0]]["valid"], series_info[keys[1]]["valid"]
                if len(s1) != len(s2):
                    warnings.append(f"Paired comparison requires equal observation lengths (got {len(s1)} and {len(s2)}).")
                    sufficiency = "insufficient"
                elif len(s1) >= 3:
                    diffs = [v1 - v2 for v1, v2 in zip(s1, s2)]
                    diff_norm = evaluate_normality(diffs, alpha=alpha)
                    assumptions_evaluated.append(
                        f"Difference normality ({diff_norm.test_used}): p={diff_norm.p_value} -> {'Normal' if diff_norm.is_normal else 'Non-normal'}."
                    )
                    if not diff_norm.is_normal:
                        return AnalyticalMethodRecommendation(
                            question_type=question_type,
                            recommended_method=HypothesisTestType.WILCOXON_SIGNED_RANK.value,
                            recommended_chart=chart,
                            sample_sufficiency=sufficiency,
                            data_quality_warnings=warnings,
                            assumptions_evaluated=assumptions_evaluated,
                            fallback_recommended=HypothesisTestType.PAIRED_TTEST.value,
                            rationale="Wilcoxon signed-rank test recommended because paired differences deviate significantly from normality.",
                        )

            return AnalyticalMethodRecommendation(
                question_type=question_type,
                recommended_method=HypothesisTestType.PAIRED_TTEST.value,
                recommended_chart=chart,
                sample_sufficiency=sufficiency,
                data_quality_warnings=warnings,
                assumptions_evaluated=assumptions_evaluated + ["Paired observation alignment confirmed."],
                fallback_recommended=HypothesisTestType.WILCOXON_SIGNED_RANK.value,
                rationale="Paired Student's t-test evaluates mean within-subject or before-and-after change when differences are approximately normal.",
            )

        elif question_type == AnalyticalQuestionType.BIVARIATE_CORRELATION:
            chart = ChartAdvisor.recommend_for_question(question_type).chart_type
            keys = list(series_info.keys())
            if len(keys) >= 2:
                s1, s2 = series_info[keys[0]]["valid"], series_info[keys[1]]["valid"]
                from app.analytics.statistics.correlation import CorrelationAnalyzer
                recommended_corr, reason = CorrelationAnalyzer.select_method(s1, s2)
                return AnalyticalMethodRecommendation(
                    question_type=question_type,
                    recommended_method=recommended_corr.value,
                    recommended_chart=chart,
                    sample_sufficiency=sufficiency,
                    data_quality_warnings=warnings,
                    assumptions_evaluated=[reason],
                    fallback_recommended=CorrelationMethod.SPEARMAN.value if recommended_corr == CorrelationMethod.PEARSON else CorrelationMethod.PEARSON.value,
                    rationale=f"Selected {recommended_corr.value.title()} correlation: {reason}",
                )

        elif question_type == AnalyticalQuestionType.MULTIVARIATE_REGRESSION:
            chart = ChartAdvisor.recommend_for_question(question_type).chart_type
            k_predictors = max(1, len(series_info) - 1)
            n_obs = min([info["n"] for info in series_info.values()]) if series_info else 0

            if n_obs < k_predictors + 2:
                sufficiency = "insufficient"
                warnings.append(f"Insufficient observations ({n_obs}) for {k_predictors} predictors; need at least {k_predictors + 2}.")
            elif n_obs < 5 * k_predictors:
                sufficiency = "marginal"
                warnings.append(f"Observations ({n_obs}) to predictors ({k_predictors}) ratio is under 5:1; high risk of overfitting.")

            return AnalyticalMethodRecommendation(
                question_type=question_type,
                recommended_method="ordinary_least_squares_regression",
                recommended_chart=chart,
                sample_sufficiency=sufficiency,
                data_quality_warnings=warnings,
                assumptions_evaluated=[
                    f"Sample-to-predictor ratio: {n_obs}:{k_predictors}",
                    "Multicollinearity evaluation (VIF / Condition Number)",
                    "Residual homoskedasticity and normality",
                ],
                fallback_recommended="bivariate_correlation",
                rationale="OLS Multiple Regression models simultaneous driver elasticities while controlling for covariates.",
            )

        elif question_type in [AnalyticalQuestionType.TIME_SERIES_TREND, AnalyticalQuestionType.TIME_SERIES_SEASONALITY]:
            chart = ChartAdvisor.recommend_for_question(question_type).chart_type
            n_obs = list(series_info.values())[0]["n"] if series_info else 0
            if n_obs < 4:
                sufficiency = "insufficient"
                warnings.append(f"Time series diagnostics require at least 4 observations, got {n_obs}.")

            return AnalyticalMethodRecommendation(
                question_type=question_type,
                recommended_method="time_series_diagnostic_battery",
                recommended_chart=chart,
                sample_sufficiency=sufficiency,
                data_quality_warnings=warnings,
                assumptions_evaluated=[
                    "Chronological sequence order",
                    "Stationarity (Augmented Dickey-Fuller)",
                    "Autocorrelation structure (ACF)",
                ],
                fallback_recommended="descriptive_summary",
                rationale="Comprehensive time series diagnostics detect linear slope, cyclical seasonality, and localized anomalies.",
            )

        elif question_type == AnalyticalQuestionType.PARETO_CONCENTRATION:
            chart = ChartAdvisor.recommend_for_question(question_type).chart_type
            return AnalyticalMethodRecommendation(
                question_type=question_type,
                recommended_method="pareto_80_20_and_gini_analysis",
                recommended_chart=chart,
                sample_sufficiency=sufficiency,
                data_quality_warnings=warnings,
                assumptions_evaluated=["Non-negative metric values", "Entity aggregation completeness"],
                fallback_recommended=None,
                rationale="Evaluates concentration inequality, 80/20 rule compliance, and Gini coefficient.",
            )

        # Default / Descriptive
        chart = ChartAdvisor.recommend_for_question(AnalyticalQuestionType.DESCRIPTIVE_SUMMARY).chart_type
        return AnalyticalMethodRecommendation(
            question_type=AnalyticalQuestionType.DESCRIPTIVE_SUMMARY,
            recommended_method="extended_descriptive_statistics",
            recommended_chart=chart,
            sample_sufficiency=sufficiency,
            data_quality_warnings=warnings,
            assumptions_evaluated=["Parametric vs non-parametric distribution shape"],
            fallback_recommended=None,
            rationale="Calculates comprehensive distribution metrics including central tendency, IQR, skewness, kurtosis, and outliers.",
        )
