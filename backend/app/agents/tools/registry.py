"""Deterministic Analytics Tool Registry for the NEXUS Agent Layer.

Binds strongly-typed Pydantic input schemas to Phase 3 AnalyticsService methods,
ensuring all agent tool invocations are deterministic, audited, and strictly isolated from raw SQL/code execution.
"""

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.agents.tools.models import (
    CategoryBreakdownToolInput,
    CohortAnalysisToolInput,
    CorrelationToolInput,
    CustomerSegmentsToolInput,
    ExpenseAnalyticsToolInput,
    FinancialSummaryToolInput,
    HypothesisTestToolInput,
    InventoryOverviewToolInput,
    InventoryTurnoverToolInput,
    InventoryVelocityToolInput,
    PriceVolumeMixToolInput,
    ProductRankingsToolInput,
    RepeatPurchaseToolInput,
    RevenueTimeseriesToolInput,
    RFMAnalysisToolInput,
    ToolExecutionResult,
    VarianceAnalysisToolInput,
)
from app.analytics.core.context import AnalysisContext
from app.analytics.core.types import (
    CorrelationMethod,
    HypothesisTestType,
    PeriodGranularity,
    SortOrder,
)
from app.analytics.service import AnalyticsService


def _serialize_obj(obj: Any) -> Any:
    """Helper to convert Pydantic models, Decimals, dates, and nested structures to JSON-serializable primitives."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__dict__"):
        return {k: _serialize_obj(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_serialize_obj(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize_obj(v) for k, v in obj.items()}
    return obj


class AnalyticsTool:
    """Descriptor and execution wrapper for a registered analytics tool."""

    def __init__(
        self,
        name: str,
        description: str,
        category: str,
        input_schema: type[BaseModel],
        handler: Callable[[Session, dict[str, Any]], ToolExecutionResult],
    ) -> None:
        self.name = name
        self.description = description
        self.category = category
        self.input_schema = input_schema
        self.handler = handler

    def execute(self, session: Session, arguments: dict[str, Any]) -> ToolExecutionResult:
        start_time = time.perf_counter()
        try:
            validated_input = self.input_schema.model_validate(arguments)
            result = self.handler(session, validated_input.model_dump())
            result.execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return result
        except ValidationError as ve:
            return ToolExecutionResult(
                tool=self.name,
                status="error",
                result={},
                error_message=f"Input validation error: {ve}",
                execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
            )
        except Exception as ex:
            return ToolExecutionResult(
                tool=self.name,
                status="error",
                result={},
                error_message=f"Execution error in {self.name}: {ex!s}",
                execution_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
            )


class ToolRegistry:
    """Central registry maintaining all deterministic tools available to the LangGraph agent."""

    def __init__(self) -> None:
        self._tools: dict[str, AnalyticsTool] = {}
        self._register_default_tools()

    def register(self, tool: AnalyticsTool) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> AnalyticsTool | None:
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[dict[str, Any]]:
        """Return descriptions and parameter schemas for agent tool discovery and planning."""
        catalog = []
        for t in self._tools.values():
            catalog.append({
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "parameters": t.input_schema.model_json_schema(),
            })
        return catalog

    def execute(self, name: str, session: Session, arguments: dict[str, Any]) -> ToolExecutionResult:
        """Secure execution gateway rejecting unregistered tool calls."""
        tool = self.get_tool(name)
        if not tool:
            return ToolExecutionResult(
                tool=name,
                status="error",
                result={},
                error_message=f"Security violation: tool '{name}' is not a registered NEXUS tool.",
            )
        return tool.execute(session, arguments)

    def _register_default_tools(self) -> None:
        # 1. Financial Summary
        def _exec_financial_summary(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
                comparison_date_from=args.get("comparison_date_from"),
                comparison_date_to=args.get("comparison_date_to"),
                customer_ids=args.get("customer_ids"),
                product_ids=args.get("product_ids"),
                categories=args.get("categories"),
            )
            res, evidence = service.get_financial_summary(context)
            return ToolExecutionResult(
                tool="get_financial_summary",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_financial_summary",
            description="Calculates comprehensive 12-metric financial summary (gross sales, net revenue, profit, COGS, orders, margins) with period-over-period comparison.",
            category="financial",
            input_schema=FinancialSummaryToolInput,
            handler=_exec_financial_summary,
        ))

        # 2. Revenue / Sales Timeseries
        def _exec_timeseries(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            granularity = PeriodGranularity(args.get("granularity", "monthly"))
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
                granularity=granularity,
            )
            metric = args.get("metric", "revenue")
            res, evidence = service.get_timeseries_analytics(context, metric=metric)
            return ToolExecutionResult(
                tool="get_sales_timeseries",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_sales_timeseries",
            description="Computes chronological metric breakdown (daily, weekly, monthly, quarterly) with period-over-period growth rates.",
            category="descriptive",
            input_schema=RevenueTimeseriesToolInput,
            handler=_exec_timeseries,
        ))

        # 3. Product Rankings
        def _exec_product_rankings(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            metric = args.get("ranking_metric", "revenue")
            limit = args.get("limit", 10)
            sort_order = SortOrder.ASC if args.get("sort_order") == "asc" else SortOrder.DESC
            items, evidence = service.get_product_rankings(
                context, ranking_metric=metric, limit=limit, sort_order=sort_order
            )
            return ToolExecutionResult(
                tool="get_product_rankings",
                status="success",
                result={"ranking_metric": metric, "items": _serialize_obj(items)},
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_product_rankings",
            description="Ranks products transparently by an explicit metric ('revenue', 'units', 'orders', 'profit', 'margin').",
            category="product",
            input_schema=ProductRankingsToolInput,
            handler=_exec_product_rankings,
        ))

        # 4. Category Breakdown
        def _exec_category_breakdown(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            metric = args.get("metric", "revenue")
            res, evidence = service.get_category_breakdown(context, metric=metric)
            return ToolExecutionResult(
                tool="get_category_breakdown",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_category_breakdown",
            description="Breaks down sales and revenue contribution across product categories.",
            category="product",
            input_schema=CategoryBreakdownToolInput,
            handler=_exec_category_breakdown,
        ))

        # 5. Customer Segments
        def _exec_customer_segments(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            res, evidence = service.get_customer_segments_breakdown(context)
            return ToolExecutionResult(
                tool="get_customer_segments",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_customer_segments",
            description="Evaluates customer activity, order distribution, and revenue shares across customer segments.",
            category="customer",
            input_schema=CustomerSegmentsToolInput,
            handler=_exec_customer_segments,
        ))

        # 6. Customer RFM Analysis
        def _exec_rfm(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            bins = args.get("quantile_bins", 5)
            limit = args.get("limit_top", 50)
            res, evidence = service.get_rfm_analysis(context, quantile_bins=bins, limit_top=limit)
            return ToolExecutionResult(
                tool="get_rfm_analysis",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_rfm_analysis",
            description="Computes customer Recency, Frequency, and Monetary scores and quintile segments.",
            category="customer",
            input_schema=RFMAnalysisToolInput,
            handler=_exec_rfm,
        ))

        # 7. Customer Cohort Retention
        def _exec_cohorts(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            max_periods = args.get("max_periods", 12)
            res, evidence = service.get_cohort_analysis(context, max_periods=max_periods)
            return ToolExecutionResult(
                tool="get_cohort_analysis",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_cohort_analysis",
            description="Analyzes customer acquisition cohorts, retention rates, and cumulative spend over time.",
            category="customer",
            input_schema=CohortAnalysisToolInput,
            handler=_exec_cohorts,
        ))

        # 8. Repeat Purchase Analytics
        def _exec_repeat_purchase(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            res, evidence = service.get_repeat_purchase_metrics(context)
            return ToolExecutionResult(
                tool="get_repeat_purchase",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_repeat_purchase",
            description="Calculates customer repeat purchase rate, one-time customer ratio, and order frequency distribution.",
            category="customer",
            input_schema=RepeatPurchaseToolInput,
            handler=_exec_repeat_purchase,
        ))

        # 9. Inventory Overview
        def _exec_inventory_overview(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            res, evidence = service.get_inventory_overview(
                warehouse=args.get("warehouse"),
                category=args.get("category"),
            )
            return ToolExecutionResult(
                tool="get_inventory_overview",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_inventory_overview",
            description="Evaluates total inventory valuation, out-of-stock items, and low-stock threshold alerts.",
            category="inventory",
            input_schema=InventoryOverviewToolInput,
            handler=_exec_inventory_overview,
        ))

        # 10. Inventory Turnover
        def _exec_inventory_turnover(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            res, evidence = service.get_inventory_turnover(context)
            return ToolExecutionResult(
                tool="get_inventory_turnover",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_inventory_turnover",
            description="Computes inventory turnover ratio and days sales of inventory (DSI).",
            category="inventory",
            input_schema=InventoryTurnoverToolInput,
            handler=_exec_inventory_turnover,
        ))

        # 11. Inventory Velocity
        def _exec_inventory_velocity(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            res, evidence = service.get_inventory_velocity(context)
            return ToolExecutionResult(
                tool="get_inventory_velocity",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_inventory_velocity",
            description="Identifies fast-moving, slow-moving, and dormant inventory SKUs based on daily run rate.",
            category="inventory",
            input_schema=InventoryVelocityToolInput,
            handler=_exec_inventory_velocity,
        ))

        # 12. Operating Expenses
        def _exec_expenses(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
                comparison_date_from=args.get("comparison_date_from"),
                comparison_date_to=args.get("comparison_date_to"),
            )
            res, evidence = service.get_expense_analytics(context)
            return ToolExecutionResult(
                tool="get_expense_analytics",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="get_expense_analytics",
            description="Evaluates total operating expenses, categorical breakdowns, and recurring overhead shares.",
            category="expenses",
            input_schema=ExpenseAnalyticsToolInput,
            handler=_exec_expenses,
        ))

        # 13. Variance Analysis (Diagnostic)
        def _exec_variance(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
                comparison_date_from=args.get("comparison_date_from"),
                comparison_date_to=args.get("comparison_date_to"),
            )
            dimension = args.get("dimension", "product")
            res, evidence = service.get_variance_analysis(context, dimension=dimension)
            return ToolExecutionResult(
                tool="run_variance_analysis",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="run_variance_analysis",
            description="Diagnoses revenue change between periods and identifies top positive/negative contributing products, categories, or segments.",
            category="diagnostic",
            input_schema=VarianceAnalysisToolInput,
            handler=_exec_variance,
        ))

        # 14. Price / Volume / Mix Decomposition
        def _exec_pvm(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
                comparison_date_from=args.get("comparison_date_from"),
                comparison_date_to=args.get("comparison_date_to"),
            )
            res, evidence = service.get_pvm_decomposition(context)
            return ToolExecutionResult(
                tool="run_price_volume_mix",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="run_price_volume_mix",
            description="Performs mathematical Price/Volume/Mix decomposition reconciling period-over-period sales variance.",
            category="diagnostic",
            input_schema=PriceVolumeMixToolInput,
            handler=_exec_pvm,
        ))

        # 15. Bivariate Correlation
        def _exec_correlation(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            var_x = args.get("variable_x", "quantity")
            var_y = args.get("variable_y", "discount_amount")
            method = CorrelationMethod(args.get("method", "pearson"))
            res, evidence = service.get_bivariate_correlation(
                variable_x=var_x, variable_y=var_y, context=context, method=method
            )
            return ToolExecutionResult(
                tool="run_correlation",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="run_correlation",
            description="Evaluates Pearson or Spearman correlation coefficient and p-value between order variables.",
            category="statistics",
            input_schema=CorrelationToolInput,
            handler=_exec_correlation,
        ))

        # 16. Hypothesis Testing
        def _exec_hypothesis(session: Session, args: dict[str, Any]) -> ToolExecutionResult:
            service = AnalyticsService(session)
            context = AnalysisContext(
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            g1 = args.get("group1_segment", "VIP")
            g2 = args.get("group2_segment", "Standard")
            metric = args.get("metric", "order_value")
            test_type = HypothesisTestType(args.get("test_type", "two_sample_ttest"))
            res, evidence = service.get_hypothesis_test(
                group1_segment=g1, group2_segment=g2, metric=metric, context=context, test_type=test_type
            )
            return ToolExecutionResult(
                tool="run_hypothesis_test",
                status="success",
                result=_serialize_obj(res),
                evidence=_serialize_obj(evidence),
                assumptions=evidence.assumptions,
                limitations=evidence.limitations,
            )

        self.register(AnalyticsTool(
            name="run_hypothesis_test",
            description="Executes two-sample Welch's t-test comparing metric distributions between customer segments.",
            category="statistics",
            input_schema=HypothesisTestToolInput,
            handler=_exec_hypothesis,
        ))


# Default global tool registry instance
tool_registry = ToolRegistry()
