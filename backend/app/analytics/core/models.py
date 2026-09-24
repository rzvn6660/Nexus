"""Typed analytical result schemas for the NEXUS Analytics Engine."""

from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.analytics.core.types import (
    PeriodGranularity,
    MetricUnit,
    TrendDirection,
    StatisticalMethod,
    HypothesisTestType,
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


class StatisticalTestResult(BaseModel):
    """Result of a formal hypothesis test between two sample distributions."""
    test_type: HypothesisTestType
    test_name: str
    metric: str
    statistic: float
    p_value: float
    degrees_of_freedom: Optional[float] = None
    sample_size_1: int
    sample_size_2: int
    mean_1: float
    mean_2: float
    is_statistically_significant: bool = Field(description="True if p_value < alpha (default 0.05)")
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
