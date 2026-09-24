"""Core Analytics Service Layer facade coordinating deterministic queries, metrics, and evidence generation."""

from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.customer import Customer
from app.models.product import Product
from app.analytics.core.context import AnalysisContext
from app.analytics.core.types import CorrelationMethod, HypothesisTestType, SortOrder
from app.analytics.core.models import (
    FinancialSummaryResult,
    ProductPerformanceItem,
    BreakdownResult,
    TimeSeriesResult,
    RepeatPurchaseResult,
    VarianceAnalysisResult,
    PriceVolumeMixDecomposition,
    StatisticalTestResult,
    CorrelationResult,
)
from app.analytics.evidence.models import EvidenceRecord
from app.analytics.evidence.builder import EvidenceBuilder
from app.analytics.metrics.definitions import get_metric_definition
from app.analytics.metrics.financial import FinancialMetricsCalculator
from app.analytics.metrics.expenses import (
    ExpenseAnalyticsCalculator,
    ExpenseAnalysisResult,
)
from app.analytics.product.performance import ProductAnalyticsService
from app.analytics.product.velocity import (
    ProductVelocityCalculator,
    VelocityAnalysisResult,
)
from app.analytics.customer.rfm import RFMAnalyzer, RFMAnalysisSummary
from app.analytics.customer.cohorts import (
    CustomerCohortAnalyzer,
    CohortAnalysisResult,
)
from app.analytics.customer.repeat_purchase import (
    RepeatPurchaseAnalyzer,
)
from app.analytics.inventory.stock import (
    InventoryStockAnalyzer,
    InventoryOverviewResult,
)
from app.analytics.inventory.turnover import (
    InventoryTurnoverCalculator,
    InventoryTurnoverResult,
)
from app.analytics.descriptive.time_series import TimeSeriesAnalyzer
from app.analytics.descriptive.segmentation import SegmentationAnalyzer
from app.analytics.diagnostic.variance import VarianceDiagnosticAnalyzer
from app.analytics.diagnostic.decomposition import PriceVolumeMixAnalyzer
from app.analytics.statistics.correlation import CorrelationAnalyzer
from app.analytics.statistics.hypothesis import HypothesisTestRunner


class AnalyticsService:
    """
    Primary interface for deterministic business analytics.
    
    Callable directly by HTTP API endpoints and future LangGraph autonomous agents.
    Every operation returns strongly-typed results alongside traceable EvidenceRecords.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_financial_summary(
        self, context: AnalysisContext
    ) -> Tuple[FinancialSummaryResult, EvidenceRecord]:
        """Compute the full 12-metric executive scorecard with evidence."""
        summary = FinancialMetricsCalculator.evaluate_summary(self.session, context)

        builder = (
            EvidenceBuilder.create("financial_summary", context)
            .with_sources(
                ["sales", "sale_items", "products", "expenses"],
                ["subtotal", "discount_amount", "quantity", "unit_cost", "amount", "status"],
            )
            .with_calculation(
                "Evaluates 12 core GAAP-aligned retail metrics: Gross Sales, Net Sales (Revenue), "
                "Discounts, Orders, Units, AOV, COGS, Gross Profit, Gross Margin, OPEX, Net Profit, Net Margin."
            )
            .with_assumptions([
                "Sales tax is excluded from commercial revenue.",
                "COGS calculated using catalog product unit_cost.",
                "Discounts include promotional order-level reductions.",
            ])
            .with_limitations([
                "Does not incorporate non-cash depreciation or income taxes.",
                "Inventory shrinkage is not modeled in the current schema.",
            ])
            .with_result_summary({
                "net_sales": float(summary.net_sales.value or 0),
                "gross_profit": float(summary.gross_profit.value or 0),
                "net_profit": float(summary.net_profit.value or 0),
                "orders": int(summary.orders.value or 0),
            })
        )
        return summary, builder.build()

    def get_product_rankings(
        self,
        context: AnalysisContext,
        ranking_metric: str = "revenue",
        limit: int = 50,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> Tuple[List[ProductPerformanceItem], EvidenceRecord]:
        """Rank products transparently by an explicit metric."""
        items = ProductAnalyticsService.get_product_rankings(
            self.session,
            context,
            ranking_metric=ranking_metric,
            limit=limit,
            sort_order=sort_order,
        )

        builder = (
            EvidenceBuilder.create(f"product_rankings_by_{ranking_metric}", context)
            .with_sources(
                ["products", "sale_items", "sales"],
                ["sku", "name", "category", "quantity", "unit_price", "line_total", "unit_cost"],
            )
            .with_calculation(
                f"Aggregated line items per SKU and sorted deterministically by {ranking_metric}."
            )
            .with_assumptions([
                "Product velocity computed as units sold divided by days in interval.",
                "Product margin calculated as (revenue - cogs) / revenue.",
            ])
            .with_result_summary({
                "ranking_metric": ranking_metric,
                "top_product": items[0].name if items else None,
                "items_returned": len(items),
            })
        )
        return items, builder.build()

    def get_category_breakdown(
        self, context: AnalysisContext, metric: str = "revenue"
    ) -> Tuple[BreakdownResult, EvidenceRecord]:
        """Evaluate category performance breakdown."""
        result = ProductAnalyticsService.get_category_breakdown(
            self.session, context, metric=metric
        )
        builder = (
            EvidenceBuilder.create(f"category_breakdown_by_{metric}", context)
            .with_sources(
                ["products", "sale_items", "sales"],
                ["category", "line_total", "quantity", "unit_cost"],
            )
            .with_calculation(
                f"Aggregated line items grouped by product category, ranked by {metric}."
            )
            .with_result_summary({
                "total_value": float(result.total_value),
                "categories_count": len(result.items),
            })
        )
        return result, builder.build()

    def get_customer_segments_breakdown(
        self, context: AnalysisContext
    ) -> Tuple[BreakdownResult, EvidenceRecord]:
        """Break down customer activity by segment."""
        result = SegmentationAnalyzer.get_customer_segment_breakdown(self.session, context)
        builder = (
            EvidenceBuilder.create("customer_segment_breakdown", context)
            .with_sources(
                ["customers", "sales"],
                ["customer_segment", "subtotal", "discount_amount", "id"],
            )
            .with_calculation("Aggregated distinct customer orders and net revenue by customer segment.")
            .with_result_summary({
                "total_revenue": float(result.total_value),
                "segments": [i.label for i in result.items],
            })
        )
        return result, builder.build()

    def get_rfm_analysis(
        self, context: AnalysisContext, quantile_bins: int = 5, limit_top: int = 50
    ) -> Tuple[RFMAnalysisSummary, EvidenceRecord]:
        """Calculate customer RFM scores and quantile segments."""
        summary = RFMAnalyzer.evaluate(
            self.session,
            context=context,
            as_of_date=context.date_to,
            quantile_bins=quantile_bins,
            limit_top=limit_top,
        )
        builder = (
            EvidenceBuilder.create("customer_rfm_analysis", context)
            .with_sources(
                ["customers", "sales"],
                ["customer_code", "name", "customer_segment", "transaction_date", "subtotal", "discount_amount"],
            )
            .with_calculation(summary.methodology)
            .with_assumptions([
                "Recency is measured in days from transaction date to reference date.",
                "Ties in quantiles resolved via first-occurrence ranking.",
            ])
            .with_limitations(summary.limitations)
            .with_result_summary({
                "customers_analyzed": summary.total_customers_analyzed,
                "segments": summary.segment_counts,
            })
        )
        return summary, builder.build()

    def get_cohort_analysis(
        self, context: AnalysisContext, max_periods: int = 12
    ) -> Tuple[CohortAnalysisResult, EvidenceRecord]:
        """Compute customer acquisition cohort retention and spend."""
        result = CustomerCohortAnalyzer.evaluate(
            self.session, context=context, max_period_offset=max_periods
        )
        builder = (
            EvidenceBuilder.create("customer_cohort_analysis", context)
            .with_sources(
                ["customers", "sales"],
                ["acquisition_date", "transaction_date", "subtotal", "discount_amount"],
            )
            .with_calculation(result.methodology)
            .with_limitations(result.limitations)
            .with_result_summary({
                "total_cohorts": result.total_cohorts,
                "max_periods": result.max_periods,
            })
        )
        return result, builder.build()

    def get_repeat_purchase_metrics(
        self, context: AnalysisContext
    ) -> Tuple[RepeatPurchaseResult, EvidenceRecord]:
        """Compute repeat purchase rate and order frequency metrics."""
        result = RepeatPurchaseAnalyzer.evaluate(self.session, context)
        builder = (
            EvidenceBuilder.create("repeat_purchase_metrics", context)
            .with_sources(["sales"], ["customer_id", "status", "transaction_date"])
            .with_calculation(
                "Counted distinct fulfilled orders per customer; evaluated proportion with >= 2 orders."
            )
            .with_result_summary({
                "repeat_rate_pct": result.repeat_purchase_rate,
                "total_ordering_customers": result.total_customers_with_orders,
            })
        )
        return result, builder.build()

    def get_inventory_overview(
        self, warehouse: Optional[str] = None, category: Optional[str] = None
    ) -> Tuple[InventoryOverviewResult, EvidenceRecord]:
        """Evaluate inventory health, valuation, and reorder alerts."""
        result = InventoryStockAnalyzer.evaluate(
            self.session, warehouse=warehouse, category=category
        )
        builder = (
            EvidenceBuilder.create("inventory_overview")
            .with_sources(
                ["inventory", "products"],
                ["stock_quantity", "reorder_threshold", "warehouse_location", "unit_cost"],
            )
            .with_calculation(
                "Aggregated stock levels, multiplied by unit_cost for total valuation, and flagged items <= reorder_threshold."
            )
            .with_result_summary({
                "total_skus": result.total_skus,
                "total_valuation": float(result.total_inventory_valuation),
                "low_stock_count": result.low_stock_count,
                "out_of_stock_count": result.out_of_stock_count,
            })
        )
        return result, builder.build()

    def get_inventory_turnover(
        self, context: AnalysisContext
    ) -> Tuple[InventoryTurnoverResult, EvidenceRecord]:
        """Compute inventory turnover ratio and DSI."""
        result = InventoryTurnoverCalculator.evaluate(self.session, context)
        builder = (
            EvidenceBuilder.create("inventory_turnover", context)
            .with_sources(
                ["sale_items", "products", "inventory"],
                ["quantity", "unit_cost", "stock_quantity"],
            )
            .with_calculation("COGS / Inventory Valuation; DSI = (Inventory Valuation / COGS) * Days")
            .with_assumptions(result.assumptions_and_limitations)
            .with_result_summary({
                "turnover_ratio": result.turnover_ratio,
                "days_sales_of_inventory": result.days_sales_of_inventory,
            })
        )
        return result, builder.build()

    def get_inventory_velocity(
        self, context: AnalysisContext
    ) -> Tuple[VelocityAnalysisResult, EvidenceRecord]:
        """Compute sales velocity and identify slow/dormant items."""
        result = ProductVelocityCalculator.evaluate(self.session, context)
        builder = (
            EvidenceBuilder.create("inventory_velocity", context)
            .with_sources(["products", "sale_items", "sales"], ["quantity", "transaction_date"])
            .with_calculation("Daily Sales Velocity = Units Sold / Days in Period.")
            .with_result_summary({
                "high_velocity": result.high_velocity_count,
                "medium_velocity": result.medium_velocity_count,
                "slow_moving": result.slow_moving_count,
                "dormant": result.dormant_count,
            })
        )
        return result, builder.build()

    def get_expense_analytics(
        self, context: AnalysisContext
    ) -> Tuple[ExpenseAnalysisResult, EvidenceRecord]:
        """Compute operating expense metrics and recurring overhead breakdown."""
        result = ExpenseAnalyticsCalculator.evaluate(self.session, context)
        builder = (
            EvidenceBuilder.create("expense_analytics", context)
            .with_sources(["expenses"], ["amount", "category", "recurring", "expense_date"])
            .with_calculation("Summed expenses by category, partitioned into recurring and variable costs.")
            .with_result_summary({
                "total_expenses": float(result.total_expenses),
                "recurring_share_pct": result.recurring_share_pct,
            })
        )
        return result, builder.build()

    def get_timeseries_analytics(
        self, context: AnalysisContext, metric: str = "revenue"
    ) -> Tuple[TimeSeriesResult, EvidenceRecord]:
        """Aggregate chronological buckets across the evaluated timeframe."""
        result = TimeSeriesAnalyzer.evaluate(self.session, context, metric=metric)
        builder = (
            EvidenceBuilder.create(f"timeseries_{metric}_{context.granularity.value}", context)
            .with_sources(
                ["sales", "sale_items", "products"],
                ["transaction_date", "line_total", "quantity", "unit_cost"],
            )
            .with_calculation(
                f"Aggregated {metric} across chronological buckets ({context.granularity.value}) with period-over-period growth."
            )
            .with_result_summary({
                "granularity": context.granularity.value,
                "points_count": len(result.points),
                "total": float(result.total),
                "average": float(result.average),
            })
        )
        return result, builder.build()

    def get_variance_analysis(
        self, context: AnalysisContext, dimension: str = "product"
    ) -> Tuple[VarianceAnalysisResult, EvidenceRecord]:
        """Diagnose revenue variance between two periods across dimensional entities."""
        result = VarianceDiagnosticAnalyzer.analyze_revenue_variance(
            self.session, context, dimension=dimension
        )
        builder = (
            EvidenceBuilder.create(f"variance_analysis_{dimension}", context)
            .with_sources(
                ["sales", "sale_items", "products", "customers"],
                ["transaction_date", "line_total", "subtotal", "discount_amount"],
            )
            .with_calculation(
                f"Compared revenue between evaluation period and baseline period, dissected by {dimension}."
            )
            .with_assumptions([
                "Identifies statistical contributors to revenue changes without asserting causal mechanisms."
            ])
            .with_result_summary({
                "total_variance": float(result.total_variance),
                "percentage_change": result.percentage_change,
                "direction": result.direction.value,
            })
        )
        return result, builder.build()

    def get_pvm_decomposition(
        self, context: AnalysisContext
    ) -> Tuple[PriceVolumeMixDecomposition, EvidenceRecord]:
        """Decompose revenue change into Volume Effect, Price Effect, and Mix Effect."""
        result = PriceVolumeMixAnalyzer.decompose(self.session, context)
        builder = (
            EvidenceBuilder.create("price_volume_mix_decomposition", context)
            .with_sources(
                ["sales", "sale_items", "products"],
                ["transaction_date", "quantity", "line_total", "selling_price"],
            )
            .with_calculation(result.methodology)
            .with_limitations(result.limitations)
            .with_result_summary({
                "total_variance": float(result.total_variance),
                "volume_effect": float(result.volume_effect),
                "price_effect": float(result.price_effect),
                "mix_effect": float(result.mix_effect),
                "reconciled": result.reconciled,
            })
        )
        return result, builder.build()

    def get_bivariate_correlation(
        self,
        variable_x: str,
        variable_y: str,
        context: Optional[AnalysisContext] = None,
        method: CorrelationMethod = CorrelationMethod.PEARSON,
    ) -> Tuple[CorrelationResult, EvidenceRecord]:
        """
        Compute correlation between two numeric order-level variables
        (e.g. order subtotal vs quantity, or discount_amount vs quantity).
        """
        # Fetch paired observations from sales
        stmt = (
            select(
                Sale.subtotal.label("subtotal"),
                Sale.discount_amount.label("discount_amount"),
                Sale.total_amount.label("total_amount"),
                func.coalesce(func.sum(SaleItem.quantity), 0).label("quantity"),
            )
            .join(SaleItem, Sale.id == SaleItem.sale_id)
            .where(Sale.status.in_(["completed", "shipped"]))
            .group_by(Sale.id)
        )
        if context and context.date_from:
            stmt = stmt.where(Sale.transaction_date >= context.date_from)
        if context and context.date_to:
            stmt = stmt.where(Sale.transaction_date <= context.date_to)

        rows = self.session.execute(stmt).all()

        x_vals: List[float] = []
        y_vals: List[float] = []

        def _extract(col_name: str, r) -> float:
            c = col_name.lower()
            if c in ("quantity", "units"):
                return float(r.quantity)
            if c == "discount_amount" or c == "discount":
                return float(r.discount_amount)
            if c == "total_amount" or c == "total":
                return float(r.total_amount)
            return float(r.subtotal)

        for r in rows:
            x_vals.append(_extract(variable_x, r))
            y_vals.append(_extract(variable_y, r))

        result = CorrelationAnalyzer.compute(
            x_vals, y_vals, variable_x=variable_x, variable_y=variable_y, method=method
        )

        builder = (
            EvidenceBuilder.create(f"correlation_{variable_x}_{variable_y}", context)
            .with_sources(["sales", "sale_items"], [variable_x, variable_y])
            .with_calculation(f"{method.value.upper()} correlation coefficient and two-sided p-value.")
            .with_limitations(result.limitations + [result.causation_warning])
            .with_result_summary({
                "coefficient": result.correlation_coefficient,
                "p_value": result.p_value,
                "sample_size": result.sample_size,
            })
        )
        return result, builder.build()

    def get_hypothesis_test(
        self,
        group1_segment: str,
        group2_segment: str,
        metric: str = "order_value",
        context: Optional[AnalysisContext] = None,
        test_type: HypothesisTestType = HypothesisTestType.TWO_SAMPLE_TTEST,
    ) -> Tuple[StatisticalTestResult, EvidenceRecord]:
        """
        Perform a two-sample Welch's t-test comparing order value distributions between two customer segments.
        """
        stmt = (
            select(
                Customer.customer_segment.label("segment"),
                (Sale.subtotal - Sale.discount_amount).label("net_order_value"),
            )
            .join(Sale, Customer.id == Sale.customer_id)
            .where(
                and_(
                    Sale.status.in_(["completed", "shipped"]),
                    Customer.customer_segment.in_([group1_segment, group2_segment]),
                )
            )
        )
        if context and context.date_from:
            stmt = stmt.where(Sale.transaction_date >= context.date_from)
        if context and context.date_to:
            stmt = stmt.where(Sale.transaction_date <= context.date_to)

        rows = self.session.execute(stmt).all()

        s1 = [float(r.net_order_value) for r in rows if r.segment == group1_segment]
        s2 = [float(r.net_order_value) for r in rows if r.segment == group2_segment]

        result = HypothesisTestRunner.compare_two_samples(
            s1,
            s2,
            group1_name=group1_segment,
            group2_name=group2_segment,
            metric_name=metric,
            test_type=test_type,
        )

        builder = (
            EvidenceBuilder.create(f"hypothesis_test_{group1_segment}_vs_{group2_segment}", context)
            .with_sources(["customers", "sales"], ["customer_segment", "subtotal", "discount_amount"])
            .with_calculation(result.test_name)
            .with_assumptions(result.assumptions_and_limitations)
            .with_result_summary({
                "statistic": result.statistic,
                "p_value": result.p_value,
                "significant": result.is_statistically_significant,
            })
        )
        return result, builder.build()
