"""Deterministic analytical chart selection and visual intelligence grounding."""

from typing import Dict, Any, List, Optional
from app.analytics.core.types import ChartType, AnalyticalQuestionType
from app.analytics.core.models import ChartRecommendation


class ChartAdvisor:
    """
    Recommends analytical, interpretable chart configurations strictly tied to evidence.
    Enforces no decorative charts: every chart recommendation maps directly to an analytical question archetype.
    """

    @classmethod
    def recommend_for_question(
        cls,
        question_type: AnalyticalQuestionType,
        metric_name: str = "Metric",
        dimension_name: Optional[str] = None,
        x_key: str = "key",
        y_key: str = "value",
    ) -> ChartRecommendation:
        """
        Derive the statistically optimal chart representation for an analytical question type.
        """
        if question_type in [AnalyticalQuestionType.TIME_SERIES_TREND, AnalyticalQuestionType.TIME_SERIES_SEASONALITY]:
            return ChartRecommendation(
                chart_type=ChartType.LINE,
                title=f"{metric_name.replace('_', ' ').title()} Over Time",
                x_axis_key="period_label",
                y_axis_key="value",
                series_keys=["value"],
                x_axis_label="Period",
                y_axis_label=metric_name.replace("_", " ").title(),
                rationale="Line charts are the canonical analytical representation for sequential temporal trends and seasonality.",
            )

        elif question_type == AnalyticalQuestionType.GROUP_COMPARISON:
            dim_label = (dimension_name or "Group").replace("_", " ").title()
            return ChartRecommendation(
                chart_type=ChartType.BOX_PLOT,
                title=f"{metric_name.replace('_', ' ').title()} Distribution by {dim_label}",
                x_axis_key="group_name",
                y_axis_key="mean",
                series_keys=["median", "p25", "p75", "min", "max"],
                x_axis_label=dim_label,
                y_axis_label=metric_name.replace("_", " ").title(),
                rationale="Box plots effectively visualize median, IQR dispersion, and potential skewness across comparison groups.",
            )

        elif question_type == AnalyticalQuestionType.DESCRIPTIVE_SUMMARY:
            return ChartRecommendation(
                chart_type=ChartType.HISTOGRAM,
                title=f"{metric_name.replace('_', ' ').title()} Distribution & Spread",
                x_axis_key="bin_label",
                y_axis_key="frequency",
                series_keys=["frequency"],
                x_axis_label=metric_name.replace("_", " ").title(),
                y_axis_label="Count / Frequency",
                rationale="Histograms reveal distribution shape, central tendency, multimodality, and tail behavior.",
            )

        elif question_type in [AnalyticalQuestionType.BIVARIATE_CORRELATION, AnalyticalQuestionType.MULTIVARIATE_REGRESSION]:
            return ChartRecommendation(
                chart_type=ChartType.SCATTER,
                title=f"{metric_name.replace('_', ' ').title()} vs Driver Analysis",
                x_axis_key="variable_x",
                y_axis_key="variable_y",
                series_keys=["trendline", "observations"],
                x_axis_label="Independent Variable (X)",
                y_axis_label="Dependent Metric (Y)",
                rationale="Scatter plots directly display bivariate association, heteroskedasticity, and outlier leverage.",
            )

        elif question_type == AnalyticalQuestionType.VARIANCE_DECOMPOSITION:
            return ChartRecommendation(
                chart_type=ChartType.WATERFALL,
                title=f"{metric_name.replace('_', ' ').title()} Variance Decomposition",
                x_axis_key="factor",
                y_axis_key="effect",
                series_keys=["effect"],
                x_axis_label="Variance Driver",
                y_axis_label="Variance Impact ($)",
                rationale="Waterfall charts clearly show bridge reconciliation from baseline to current period across drivers.",
            )

        elif question_type == AnalyticalQuestionType.COHORT_RETENTION:
            return ChartRecommendation(
                chart_type=ChartType.COHORT_MATRIX,
                title="Customer Cohort Retention Rate Matrix",
                x_axis_key="period_index",
                y_axis_key="cohort_period",
                series_keys=["retention_rate"],
                x_axis_label="Periods Since Acquisition",
                y_axis_label="Cohort Inception",
                rationale="Cohort retention matrices reveal decay curves and vintage performance shifts over customer lifecycles.",
            )

        elif question_type == AnalyticalQuestionType.PARETO_CONCENTRATION:
            dim_label = (dimension_name or "Entities").replace("_", " ").title()
            return ChartRecommendation(
                chart_type=ChartType.LINE,
                title=f"Lorenz Concentration Curve: {metric_name.replace('_', ' ').title()} by {dim_label}",
                x_axis_key="entity_percentile",
                y_axis_key="cumulative_metric_share",
                series_keys=["cumulative_metric_share", "equality_line"],
                x_axis_label=f"Cumulative % of {dim_label}",
                y_axis_label=f"Cumulative % of {metric_name.replace('_', ' ').title()}",
                rationale="The Lorenz curve visualizes inequality gap relative to the 45-degree line of perfect equality.",
            )

        # Default fallback
        return ChartRecommendation(
            chart_type=ChartType.BAR,
            title=f"{metric_name.replace('_', ' ').title()} Breakdown",
            x_axis_key=x_key,
            y_axis_key=y_key,
            series_keys=[y_key],
            x_axis_label="Category",
            y_axis_label=metric_name.replace("_", " ").title(),
            rationale="Bar charts provide transparent, deterministic category comparison without misleading area distortion.",
        )

    @classmethod
    def validate_chart_suitability(
        cls,
        chart_type: ChartType,
        sample_size: int,
        group_sample_sizes: Optional[Dict[str, int]] = None,
        is_linear_relationship: Optional[bool] = None,
        is_temporally_ordered: Optional[bool] = None,
    ) -> tuple[bool, Optional[str], Optional[ChartType]]:
        """
        Validate whether the selected chart is statistically appropriate for the data characteristics.
        Prevents misleading or deceptive visual artifacts.

        Returns:
            (is_suitable, warning_message, suggested_fallback_chart)
        """
        if chart_type == ChartType.BOX_PLOT:
            # Box plots require at least 5 points per group to compute min, Q1, median, Q3, max
            if group_sample_sizes:
                too_small = [g for g, n in group_sample_sizes.items() if n < 5]
                if too_small:
                    return (
                        False,
                        f"Groups {too_small} have fewer than 5 observations. Box plots are statistically invalid for small samples; bar chart recommended.",
                        ChartType.BAR,
                    )
            elif sample_size < 5:
                return (
                    False,
                    f"Sample size ({sample_size}) < 5 is insufficient for 5-number box plot summary.",
                    ChartType.BAR,
                )

        elif chart_type == ChartType.SCATTER:
            if is_linear_relationship is False:
                return (
                    True,
                    "Scatter plot recommended without trendline: relationship does not satisfy linear fit criteria; fitted trendline would imply unsupported linearity.",
                    None,
                )

        elif chart_type == ChartType.LINE:
            if is_temporally_ordered is False:
                return (
                    False,
                    "Line chart inappropriate for unordered categorical data; implies false continuity.",
                    ChartType.BAR,
                )
            if sample_size < 2:
                return (
                    False,
                    f"Line charts require at least 2 points to establish continuity, got {sample_size}.",
                    ChartType.BAR,
                )

        return True, None, None
