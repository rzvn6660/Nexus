"""Pydantic schemas for deterministic tool inputs and structured execution outputs."""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class BaseToolInput(BaseModel):
    """Common temporal parameters for analytical tools."""
    date_from: date | None = Field(default=None, description="Start date of primary analysis interval (YYYY-MM-DD)")
    date_to: date | None = Field(default=None, description="End date of primary analysis interval (YYYY-MM-DD)")
    comparison_date_from: date | None = Field(default=None, description="Start date of comparison baseline (YYYY-MM-DD)")
    comparison_date_to: date | None = Field(default=None, description="End date of comparison baseline (YYYY-MM-DD)")


class FinancialSummaryToolInput(BaseToolInput):
    """Input for calculating the 12-metric financial summary scorecard."""
    customer_ids: list[int] | None = Field(default=None, description="Optional customer ID filter")
    product_ids: list[int] | None = Field(default=None, description="Optional product ID filter")
    categories: list[str] | None = Field(default=None, description="Optional product category filter")


class RevenueTimeseriesToolInput(BaseToolInput):
    """Input for chronological metric time series aggregation."""
    metric: str = Field(default="revenue", description="Metric to aggregate ('revenue', 'orders', 'units', 'profit')")
    granularity: str = Field(default="monthly", description="Aggregation bucket ('daily', 'weekly', 'monthly', 'quarterly')")


class ProductRankingsToolInput(BaseToolInput):
    """Input for deterministic product rankings."""
    ranking_metric: str = Field(default="revenue", description="Ranking metric ('revenue', 'units', 'orders', 'profit', 'margin')")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of items to return")
    sort_order: str = Field(default="desc", description="Sort direction ('asc' or 'desc')")


class CategoryBreakdownToolInput(BaseToolInput):
    """Input for product category distribution."""
    metric: str = Field(default="revenue", description="Breakdown metric ('revenue', 'units', 'profit', 'margin')")


class CustomerSegmentsToolInput(BaseToolInput):
    """Input for customer segment breakdown."""


class RFMAnalysisToolInput(BaseToolInput):
    """Input for customer RFM quintile segmentation."""
    quantile_bins: int = Field(default=5, ge=3, le=10, description="Number of quantile buckets (default: 5)")
    limit_top: int = Field(default=50, ge=1, le=200, description="Maximum individual customer scores to return")


class CohortAnalysisToolInput(BaseToolInput):
    """Input for customer cohort retention analysis."""
    max_periods: int = Field(default=12, ge=1, le=36, description="Max progression periods (months) to evaluate")


class RepeatPurchaseToolInput(BaseToolInput):
    """Input for repeat customer purchase analysis."""


class InventoryOverviewToolInput(BaseModel):
    """Input for current inventory health and valuation."""
    warehouse: str | None = Field(default=None, description="Optional warehouse filter")
    category: str | None = Field(default=None, description="Optional product category filter")


class InventoryTurnoverToolInput(BaseToolInput):
    """Input for inventory turnover and days sales of inventory."""


class InventoryVelocityToolInput(BaseToolInput):
    """Input for daily product sales velocity."""


class ExpenseAnalyticsToolInput(BaseToolInput):
    """Input for operating expense breakdown and recurring shares."""


class VarianceAnalysisToolInput(BaseToolInput):
    """Input for diagnosing metric variance between two periods."""
    dimension: str = Field(default="product", description="Dissection dimension ('product', 'category', 'customer_segment')")


class PriceVolumeMixToolInput(BaseToolInput):
    """Input for decomposing revenue changes into price, volume, and mix effects."""


class CorrelationToolInput(BaseToolInput):
    """Input for bivariate correlation analysis."""
    variable_x: str = Field(default="quantity", description="First order-level variable ('subtotal', 'quantity', 'discount_amount', 'total_amount')")
    variable_y: str = Field(default="discount_amount", description="Second order-level variable ('subtotal', 'quantity', 'discount_amount', 'total_amount')")
    method: str = Field(default="pearson", description="Correlation method ('pearson' or 'spearman')")


class HypothesisTestToolInput(BaseToolInput):
    """Input for two-sample hypothesis testing between customer segments."""
    group1_segment: str = Field(description="First customer segment name (e.g. 'VIP', 'Wholesale')")
    group2_segment: str = Field(description="Second customer segment name (e.g. 'Standard', 'Retail')")
    metric: str = Field(default="order_value", description="Metric to compare")
    test_type: str = Field(default="two_sample_ttest", description="Statistical test method ('two_sample_ttest')")


class ForecastMetricToolInput(BaseToolInput):
    """Input for Phase 7 deterministic time-series forecasting."""
    target_metric: str = Field(default="revenue", description="Target metric: 'revenue', 'net_revenue', 'gross_sales', 'units_sold', 'order_volume', 'product_demand'")
    entity_type: str | None = Field(default=None, description="Optional entity scope ('product', 'category')")
    entity_id: str | None = Field(default=None, description="Entity identifier (e.g. SKU code)")
    forecast_horizon: int = Field(default=3, ge=1, le=12, description="Periods into the future to forecast (1-12)")
    frequency: str = Field(default="monthly", description="Frequency: 'daily', 'weekly', or 'monthly'")
    model_policy: str = Field(default="validated_best", description="Policy: 'validated_best', 'baseline_only', 'specific_model'")
    specific_model: str | None = Field(default=None, description="Specific model name if model_policy is 'specific_model'")
    confidence_level: float = Field(default=0.95, ge=0.5, le=0.99, description="Coverage probability for prediction intervals")


class ToolExecutionResult(BaseModel):
    """Standardized deterministic execution payload returned by every agent tool."""
    tool: str = Field(description="Name of the executed tool")
    status: str = Field(default="success", description="Status: 'success' or 'error'")
    result: dict[str, Any] = Field(default_factory=dict, description="Raw structured analytical result")
    evidence: dict[str, Any] | None = Field(default=None, description="Serialized EvidenceRecord")
    assumptions: list[str] = Field(default_factory=list, description="Explicit modeling assumptions")
    limitations: list[str] = Field(default_factory=list, description="Analytical limitations / caveats")
    execution_time_ms: float = Field(default=0.0, description="Tool execution duration in milliseconds")
    error_message: str | None = Field(default=None, description="Detailed error message if execution failed")
