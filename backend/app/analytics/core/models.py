"""Typed analytical result schemas for the NEXUS Analytics Engine."""

from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.analytics.core.types import (
    PeriodGranularity,
    MetricUnit,
    TrendDirection,
    StatisticalMethod,
    HypothesisTestType,
    EffectSizeMagnitude,
    DistributionType,
    OutlierMethod,
    AnalyticalQuestionType,
    ChartType,
)


class MetricValue(BaseModel):
    """Encapsulates a single computed metric value with units and formatting."""
    name: str = Field(description="Internal metric key / name")
    value: Optional[Decimal] = Field(default=None, description="Exact computed decimal or integer value")
    formatted: str = Field(description="Formatted human-readable string (e.g. '$12,450.00', '18.4%')")
    unit: MetricUnit = Field(description="Unit of measurement")
    description: Optional[str] = Field(default=None, description="Brief business definition")


class ComparisonResult(BaseModel):
    """Represents a period-over-period comparison with absolute change and growth rate."""
    current_value: Optional[Decimal] = Field(default=None, description="Primary period metric value")
    previous_value: Optional[Decimal] = Field(default=None, description="Baseline comparison period metric value")
    absolute_change: Optional[Decimal] = Field(default=None, description="Difference: current - previous")
    percentage_change: Optional[float] = Field(
        default=None,
        description="Percentage growth: ((current - previous) / previous) * 100. Undefined if previous is 0."
    )
    direction: TrendDirection = Field(
        default=TrendDirection.UNDEFINED,
        description="Direction of change: increase, decrease, unchanged, or undefined"
    )
    note: Optional[str] = Field(default=None, description="Explaining notes (e.g. 'Baseline period had 0 revenue')")


class BreakdownItem(BaseModel):
    """Item within a dimensional breakdown."""
    key: str = Field(description="Dimension key (e.g. category name, customer segment, SKU)")
    label: str = Field(description="Display label")
    value: Decimal = Field(description="Metric value for this slice")
    formatted_value: str = Field(description="Formatted string")
    percentage_of_total: Optional[float] = Field(default=None, description="Share of aggregate total (0-100%)")
    count: Optional[int] = Field(default=None, description="Frequency or transaction count in slice")
    secondary_value: Optional[Decimal] = Field(default=None, description="Optional secondary metric (e.g. profit)")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional dimensional attributes")

    # Contract compatibility fields matching frontend expectations
    dimension_value: Optional[str] = Field(default=None, description="Dimension name / slice value")
    metric_value: Optional[Decimal] = Field(default=None, description="Primary aggregated metric value")
    order_count: Optional[int] = Field(default=None, description="Order transaction count")

    model_config = ConfigDict(populate_by_name=True)

    def model_post_init(self, __context: Any) -> None:
        if self.dimension_value is None:
            self.dimension_value = self.label or self.key
        if self.metric_value is None:
            self.metric_value = self.value
        if self.order_count is None and self.count is not None:
            self.order_count = self.count


class BreakdownResult(BaseModel):
    """Aggregate result of slicing a metric across a categorical dimension."""
    dimension: str = Field(description="Dimension name (e.g. 'category', 'customer_segment', 'warehouse')")
    metric: str = Field(description="Metric aggregated")
    total_value: Decimal = Field(description="Sum total across all categories")
    items: List[BreakdownItem] = Field(default_factory=list, description="Ranked breakdown elements")


class TimeSeriesPoint(BaseModel):
    """Single temporal bucket within a time series analysis."""
    period_start: str = Field(description="Bucket start date / timestamp (ISO 8601 string)")
    period_end: str = Field(description="Bucket end date / timestamp (ISO 8601 string)")
    period_label: str = Field(description="Human label (e.g. '2025-01', '2025-W12', '2025-01-15')")
    value: Decimal = Field(description="Primary metric value for the bucket")
    secondary_value: Optional[Decimal] = Field(default=None, description="Secondary metric (e.g. COGS or profit)")
    orders: Optional[int] = Field(default=None, description="Transaction count in bucket")
    units: Optional[int] = Field(default=None, description="Units sold in bucket")
    growth_rate: Optional[float] = Field(default=None, description="Period-over-period growth vs immediate prior bucket")


class TimeSeriesResult(BaseModel):
    """Collection of time series points for trend evaluation."""
    metric: str = Field(description="Metric analyzed over time")
    granularity: PeriodGranularity = Field(description="Time bucket granularity")
    points: List[TimeSeriesPoint] = Field(default_factory=list, description="Chronological data points")
    total: Decimal = Field(description="Total across all points")
    average: Decimal = Field(description="Average per point")
    min_value: Optional[Decimal] = Field(default=None, description="Minimum bucket value")
    max_value: Optional[Decimal] = Field(default=None, description="Maximum bucket value")
    is_order_level_fallback: bool = Field(
        default=False, description="True if aggregated from order headers rather than item lines"
    )


class FinancialSummaryResult(BaseModel):
    """Complete executive financial scorecard containing all 12 core metrics."""
    gross_sales: MetricValue
    discounts: MetricValue
    net_sales: MetricValue  # Revenue
    units_sold: MetricValue
    orders: MetricValue
    average_order_value: MetricValue
    cogs: MetricValue
    gross_profit: MetricValue
    gross_margin: MetricValue
    operating_expenses: MetricValue
    net_profit: MetricValue
    net_margin: MetricValue
    currency: str = Field(default="USD", description="Currency code (e.g. USD, INR)")
    currency_symbol: str = Field(default="$", description="Currency display symbol (e.g. $, ₹)")
    comparison: Optional[Dict[str, ComparisonResult]] = Field(
        default=None,
        description="Period comparisons if comparison range is provided"
    )


class ProductPerformanceItem(BaseModel):
    """Product performance summary record."""
    product_id: int
    sku: str
    name: str
    category: str
    subcategory: str
    units_sold: int
    order_count: int
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Optional[float]
    revenue_contribution_pct: Optional[float]
    velocity_units_per_day: Optional[float]
    rank: int


class CustomerRFMRecord(BaseModel):
    """Customer RFM scores and metrics."""
    customer_id: int
    customer_code: str
    name: str
    segment: str
    recency_days: int
    frequency_orders: int
    monetary_revenue: Decimal
    r_score: int
    f_score: int
    m_score: int
    rfm_score: str
    rfm_segment: str


class CohortCell(BaseModel):
    """Activity measurement for a cohort in a subsequent period."""
    period_index: int = Field(description="0 for cohort formation period, 1 for next period, etc.")
    period_label: str
    active_customers: int
    retention_rate: float
    total_spend: Decimal
    average_spend_per_active: Decimal


class CohortRow(BaseModel):
    """Single cohort group defined by acquisition or first purchase period."""
    cohort_period: str = Field(description="Acquisition period (e.g. '2024-01')")
    cohort_size: int = Field(description="Initial customer count in cohort")
    periods: List[CohortCell] = Field(default_factory=list)


class RepeatPurchaseResult(BaseModel):
    """Customer repeat purchase behavior metrics."""
    total_customers_with_orders: int
    one_time_customers: int
    repeat_customers: int
    repeat_purchase_rate: float
    average_orders_per_customer: float
    orders_distribution: Dict[str, int]  # e.g. {"1": 450, "2": 180, "3-5": 90, "6+": 25}


class PriceVolumeMixDecomposition(BaseModel):
    """
    Deterministic decomposition of revenue variance:
    ΔRevenue = Volume Effect + Price Effect + Mix Effect.
    """
    prior_revenue: Decimal
    current_revenue: Decimal
    total_variance: Decimal
    volume_effect: Decimal
    price_effect: Decimal
    mix_effect: Decimal
    volume_effect_pct: Optional[float] = None
    price_effect_pct: Optional[float] = None
    mix_effect_pct: Optional[float] = None
    reconciled: bool = Field(
        description="True if Volume + Price + Mix exactly equals Total Variance within tolerance"
    )
    methodology: str = Field(description="Mathematical explanation of decomposition algorithm")
    limitations: List[str] = Field(description="Applicability constraints and assumptions")


class VarianceContributor(BaseModel):
    """Dimension item contributing to a metric variance."""
    entity_id: str
    entity_name: str
    prior_value: Decimal
    current_value: Decimal
    absolute_change: Decimal
    contribution_to_change_pct: float
    direction: TrendDirection


class VarianceAnalysisResult(BaseModel):
    """Diagnostic variance analysis dissecting changes between two periods."""
    metric: str
    prior_period_value: Decimal
    current_period_value: Decimal
    total_variance: Decimal
    percentage_change: Optional[float]
    direction: TrendDirection
    dimension: str
    top_positive_contributors: List[VarianceContributor]
    top_negative_contributors: List[VarianceContributor]


class ConfidenceInterval(BaseModel):
    """Parametric or non-parametric confidence interval for an estimate."""
    point_estimate: float = Field(description="Sample estimate (mean, difference, proportion)")
    lower_bound: float = Field(description="Lower bound of interval")
    upper_bound: float = Field(description="Upper bound of interval")
    confidence_level: float = Field(default=0.95, description="Confidence level (e.g. 0.95 for 95% CI)")
    margin_of_error: float = Field(description="Half-width margin of error")


class OutlierResult(BaseModel):
    """Detection results for anomalous or extreme observations."""
    method: OutlierMethod
    count: int = Field(description="Total count of detected outliers")
    percentage: float = Field(description="Percentage of sample detected as outliers")
    lower_fence: Optional[float] = Field(default=None, description="Lower cutoff fence if applicable")
    upper_fence: Optional[float] = Field(default=None, description="Upper cutoff fence if applicable")
    outlier_indices: List[int] = Field(default_factory=list, description="0-based indices of outliers")
    outlier_values: List[float] = Field(default_factory=list, description="Values identified as outliers")


class DescriptiveExtendedStats(BaseModel):
    """Comprehensive parametric and non-parametric distribution metrics."""
    variable_name: str
    count: int
    sum: float
    mean: float
    median: float
    mode: Optional[float] = None
    std_dev: float
    variance: float
    coefficient_of_variation: Optional[float] = Field(
        default=None, description="CV = std_dev / mean. Measures relative dispersion."
    )
    min: float
    max: float
    range: float
    iqr: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float
    skewness: float = Field(description="Fisher-Pearson skewness: >0 right/positive, <0 left/negative")
    kurtosis: float = Field(description="Excess kurtosis: >0 leptokurtic/heavy-tailed, <0 platykurtic/light-tailed")
    distribution_type: DistributionType
    is_normally_distributed: bool = Field(description="Evaluated via normality test (Shapiro-Wilk / D'Agostino)")
    normality_p_value: Optional[float] = None
    confidence_interval_95: Optional[ConfidenceInterval] = None
    outliers_tukey: Optional[OutlierResult] = None
    outliers_zscore: Optional[OutlierResult] = None


class EffectSizeResult(BaseModel):
    """Standardized effect size quantify substantive practical magnitude."""
    metric_name: str = Field(description="Name of effect size metric (e.g. 'cohens_d', 'cramers_v', 'eta_squared')")
    value: float = Field(description="Numeric effect size value")
    magnitude: EffectSizeMagnitude = Field(description="Qualitative label: negligible, small, medium, large")
    interpretation: str = Field(description="Plain-English explanation of practical significance")


class StatisticalTestResult(BaseModel):
    """Result of a formal hypothesis test between sample distributions."""
    test_type: HypothesisTestType
    test_name: str
    metric: str
    statistic: float
    p_value: float
    degrees_of_freedom: Optional[float] = None
    sample_size_1: int
    sample_size_2: Optional[int] = None
    mean_1: float
    mean_2: Optional[float] = None
    is_statistically_significant: bool = Field(description="True if p_value < alpha (default 0.05)")
    alpha: float = 0.05
    confidence_interval: Optional[ConfidenceInterval] = None
    effect_size: Optional[EffectSizeResult] = None
    practical_significance: Optional[str] = Field(
        default=None, description="Distinction between p-value significance and business meaningfulness"
    )
    interpretation: str
    assumptions_and_limitations: List[str]


class AnovaGroupSummary(BaseModel):
    """Group-level summary metrics for ANOVA / Kruskal-Wallis."""
    group_name: str
    sample_size: int
    mean: float
    std_dev: float
    median: float


class AnovaPostHocComparison(BaseModel):
    """Pairwise post-hoc comparison between groups following significant omnibus ANOVA."""
    group_1: str
    group_2: str
    mean_difference: float
    statistic: float
    p_value_raw: float
    p_value_adjusted: float
    correction_method: str = "holm"
    is_statistically_significant: bool
    confidence_interval: Optional[ConfidenceInterval] = None
    effect_size: Optional[EffectSizeResult] = None


class AnovaResult(BaseModel):
    """One-Way ANOVA test across 3 or more independent groups."""
    metric_name: str
    f_statistic: float
    p_value: float
    df_between: int
    df_within: int
    eta_squared: float = Field(description="Proportion of variance explained by group membership (eta^2)")
    effect_magnitude: EffectSizeMagnitude
    is_statistically_significant: bool
    alpha: float = 0.05
    groups: List[AnovaGroupSummary]
    post_hoc_comparisons: Optional[List[AnovaPostHocComparison]] = None
    post_hoc_correction_method: Optional[str] = None
    interpretation: str
    assumptions_and_limitations: List[str]


class ChiSquareContingencyResult(BaseModel):
    """Chi-square test of independence between two categorical variables."""
    variable_x: str
    variable_y: str
    chi2_statistic: float
    p_value: float
    degrees_of_freedom: int
    cramers_v: float = Field(description="Cramér's V measure of nominal association [0, 1]")
    effect_magnitude: EffectSizeMagnitude
    is_statistically_significant: bool
    alpha: float = 0.05
    sample_size: int
    contingency_table: Dict[str, Dict[str, int]]
    expected_frequencies: Dict[str, Dict[str, float]]
    expected_frequencies_valid: bool = Field(
        default=True,
        description="True if Cochran's rule is satisfied (>=80% cells have expected freq >= 5, all >= 1)"
    )
    cells_below_five_pct: float = Field(
        default=0.0,
        description="Percentage of contingency cells with expected frequency below 5"
    )
    min_expected_frequency: float = Field(
        default=5.0,
        description="Minimum expected cell frequency across all cells"
    )
    fishers_exact_p_value: Optional[float] = Field(
        default=None,
        description="Exact p-value from Fisher's exact test for 2x2 contingency tables"
    )
    fishers_exact_odds_ratio: Optional[float] = Field(
        default=None,
        description="Exact odds ratio from Fisher's exact test for 2x2 contingency tables"
    )
    cochran_warning: Optional[str] = None
    interpretation: str
    assumptions_and_limitations: List[str]


class TwoProportionResult(BaseModel):
    """Two-proportion z-test comparing rates (conversion, retention, churn)."""
    group1_name: str
    group2_name: str
    successes_1: int
    total_1: int
    proportion_1: float
    successes_2: int
    total_2: int
    proportion_2: float
    absolute_difference: float
    relative_difference_pct: Optional[float]
    z_statistic: float
    p_value: float
    confidence_interval: ConfidenceInterval
    is_statistically_significant: bool
    alpha: float = 0.05
    interpretation: str
    assumptions_and_limitations: List[str]


class CorrelationResult(BaseModel):
    """Result of correlation analysis between two variables."""
    variable_x: str
    variable_y: str
    method: str
    correlation_coefficient: float
    p_value: Optional[float] = None
    sample_size: int
    strength: str  # strong, moderate, weak, negligible
    direction: str  # positive, negative, zero
    causation_warning: str = Field(
        default="Correlation measures statistical association only and DOES NOT imply causation."
    )
    limitations: List[str]


class RegressionCoefficient(BaseModel):
    """Estimated regression coefficient with inference statistics."""
    variable: str
    coefficient: float
    standard_error: float
    t_statistic: float
    p_value: float
    ci_lower: float
    ci_upper: float
    vif: Optional[float] = Field(default=None, description="Variance Inflation Factor for multicollinearity check")


class RegressionAnalysisResult(BaseModel):
    """Deterministic Ordinary Least Squares (OLS) regression analysis."""
    dependent_variable: str
    independent_variables: List[str]
    sample_size: int
    degrees_of_freedom_model: int
    degrees_of_freedom_residuals: int
    r_squared: float
    adjusted_r_squared: float
    f_statistic: float
    f_pvalue: float
    residual_standard_error: float
    coefficients: List[RegressionCoefficient]
    condition_number: float = Field(description="Matrix condition number; >30 indicates potential multicollinearity")
    multicollinearity_warning: bool
    durbin_watson_statistic: float = Field(
        default=2.0,
        description="Durbin-Watson statistic for residual autocorrelation (~2=uncorrelated, <1.5=positive, >2.5=negative)"
    )
    residual_autocorrelation_warning: bool = Field(
        default=False,
        description="True if residuals exhibit significant autocorrelation (DW < 1.5 or DW > 2.5)"
    )
    breusch_pagan_statistic: float = Field(
        default=0.0,
        description="Breusch-Pagan LM test statistic for residual heteroskedasticity"
    )
    breusch_pagan_p_value: float = Field(
        default=1.0,
        description="p-value for Breusch-Pagan test of homoskedasticity"
    )
    heteroskedasticity_warning: bool = Field(
        default=False,
        description="True if Breusch-Pagan test rejects homoskedastic errors (p < 0.05)"
    )
    robust_standard_errors_recommended: bool = Field(
        default=False,
        description="True if heteroskedasticity or non-normal residuals indicate OLS SEs may be biased"
    )
    matrix_rank: int = Field(
        default=1,
        description="Rank of predictor design matrix"
    )
    is_rank_deficient: bool = Field(
        default=False,
        description="True if predictor design matrix is rank-deficient (strictly singular)"
    )
    residuals_normal: bool = Field(
        default=True,
        description="Evaluates whether regression residuals conform to normality"
    )
    residuals_normality_p_value: Optional[float] = None
    influential_observations_count: int = Field(
        default=0,
        description="Count of observations with Cook's distance > 4/n"
    )
    max_cooks_distance: float = Field(
        default=0.0,
        description="Maximum Cook's distance observed across all sample points"
    )
    high_leverage_observations_count: int = Field(
        default=0,
        description="Count of observations with hat value > 2*(k+1)/n"
    )
    is_statistically_significant: bool
    causation_warning: str = Field(
        default="Regression models statistical associations and predictive relationships, NOT deterministic causality."
    )
    interpretation: str
    limitations: List[str]


class TimeSeriesDiagnosticResult(BaseModel):
    """Comprehensive statistical diagnostics for time series behavior."""
    metric: str
    granularity: str
    sample_size: int
    trend_slope: float
    trend_direction: TrendDirection
    trend_p_value: Optional[float] = None
    is_stationary: bool
    adf_statistic: Optional[float] = None
    adf_p_value: Optional[float] = None
    autocorrelations: Dict[int, float] = Field(description="Autocorrelation coefficients for lags 1 through k")
    seasonal_period: Optional[int] = None
    seasonal_strength: float = Field(description="Estimated seasonal index strength [0, 1]")
    anomalies_detected: int
    anomaly_indices: List[int] = Field(default_factory=list)
    anomaly_dates: List[str] = Field(default_factory=list)
    interpretation: str
    limitations: List[str]


class ParetoAnalysisResult(BaseModel):
    """Deterministic Pareto 80/20 concentration analysis and Gini inequality metrics."""
    metric_name: str
    entity_dimension: str
    total_entities: int
    total_metric_value: float
    top_20_pct_entities_count: int
    top_20_pct_metric_value: float
    top_20_pct_share: float = Field(description="Percentage of total metric generated by top 20% of entities")
    satisfies_80_20_rule: bool = Field(description="True if top 20% entities generate between 70% and 90% of metric")
    gini_coefficient: float = Field(description="Gini concentration index [0 = perfect equality, 1 = absolute monopoly]")
    concentration_classification: str = Field(description="'high', 'moderate', or 'low' concentration")
    lorenz_curve: List[Dict[str, float]] = Field(description="Lorenz curve coordinates: entity_pct vs cumulative_metric_pct")
    top_contributors: List[Dict[str, Any]] = Field(description="Top entities ranked by metric contribution")
    interpretation: str
    limitations: List[str]


class ChartRecommendation(BaseModel):
    """Analytical chart configuration strictly grounded in data characteristics."""
    chart_type: ChartType
    title: str
    x_axis_key: str
    y_axis_key: str
    series_keys: List[str] = Field(default_factory=list)
    x_axis_label: str
    y_axis_label: str
    rationale: str


class AnalyticalMethodRecommendation(BaseModel):
    """Deterministic method selection recommendation for an analytical question."""
    question_type: AnalyticalQuestionType
    recommended_method: str
    recommended_chart: ChartType
    sample_sufficiency: str = Field(description="'sufficient', 'marginal', or 'insufficient'")
    data_quality_warnings: List[str] = Field(default_factory=list)
    assumptions_evaluated: List[str] = Field(default_factory=list)
    fallback_recommended: Optional[str] = None
    rationale: str
