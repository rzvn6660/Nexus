"""Deterministic computation of core financial metrics and period-over-period comparisons."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.expense import Expense
from app.analytics.core.types import MetricUnit, TrendDirection
from app.analytics.core.context import AnalysisContext
from app.analytics.core.models import (
    MetricValue,
    ComparisonResult,
    FinancialSummaryResult,
)


def calculate_comparison(
    current: Optional[Decimal],
    previous: Optional[Decimal],
    unit: MetricUnit = MetricUnit.CURRENCY,
) -> ComparisonResult:
    """
    Safely compare two numerical values without floating-point errors or division-by-zero crashes.
    """
    if current is None and previous is None:
        return ComparisonResult(
            direction=TrendDirection.UNDEFINED,
            note="Both evaluation and baseline periods had no data",
        )
    if previous is None:
        return ComparisonResult(
            current_value=current,
            previous_value=None,
            direction=TrendDirection.UNDEFINED,
            note="No baseline comparison data available",
        )
    if current is None:
        return ComparisonResult(
            current_value=None,
            previous_value=previous,
            direction=TrendDirection.UNDEFINED,
            note="No current period data available",
        )

    abs_diff = current - previous

    # Handle zero denominator
    if previous == Decimal("0"):
        if current == Decimal("0"):
            return ComparisonResult(
                current_value=current,
                previous_value=previous,
                absolute_change=Decimal("0.00"),
                percentage_change=0.0,
                direction=TrendDirection.UNCHANGED,
            )
        direction = TrendDirection.INCREASE if current > 0 else TrendDirection.DECREASE
        return ComparisonResult(
            current_value=current,
            previous_value=previous,
            absolute_change=abs_diff,
            percentage_change=None,
            direction=direction,
            note="Baseline value was 0; percentage growth is mathematically undefined",
        )

    # Standard percentage change
    pct = float((abs_diff / abs(previous)) * Decimal("100.0"))
    if abs_diff > 0:
        direction = TrendDirection.INCREASE
    elif abs_diff < 0:
        direction = TrendDirection.DECREASE
    else:
        direction = TrendDirection.UNCHANGED

    return ComparisonResult(
        current_value=current,
        previous_value=previous,
        absolute_change=abs_diff,
        percentage_change=round(pct, 4),
        direction=direction,
    )


def _format_value(val: Optional[Decimal], unit: MetricUnit) -> str:
    """Format decimal value into human-friendly string."""
    if val is None:
        return "N/A"
    if unit == MetricUnit.CURRENCY:
        return f"${val:,.2f}"
    if unit == MetricUnit.PERCENTAGE:
        return f"{val:.2f}%"
    if unit == MetricUnit.COUNT or unit == MetricUnit.UNITS:
        return f"{int(val):,}"
    if unit == MetricUnit.RATIO:
        return f"{val:.2f}x"
    return f"{val}"


class FinancialMetricsCalculator:
    """Deterministic calculator for the 12 core financial metrics."""

    @staticmethod
    def _apply_sale_filters(query, context: AnalysisContext, date_col):
        """Apply date range, status, and dimensional filters to Sale queries."""
        clauses = []
        if context.date_from:
            clauses.append(date_col >= context.date_from)
        if context.date_to:
            clauses.append(date_col <= context.date_to)
        if context.statuses:
            clauses.append(Sale.status.in_(context.statuses))
        if context.customer_ids:
            clauses.append(Sale.customer_id.in_(context.customer_ids))
        if context.customer_segments:
            query = query.join(Customer, Sale.customer_id == Customer.id)
            clauses.append(Customer.customer_segment.in_(context.customer_segments))
        if clauses:
            query = query.where(and_(*clauses))
        return query

    @classmethod
    def compute_sales_aggregates(
        cls, session: Session, context: AnalysisContext, is_comparison: bool = False
    ) -> Dict[str, Decimal]:
        """
        Compute Gross Sales, Discounts, Net Sales (Revenue), and Orders.
        """
        d_from = context.comparison_date_from if is_comparison else context.date_from
        d_to = context.comparison_date_to if is_comparison else context.date_to

        temp_ctx = context.model_copy(update={"date_from": d_from, "date_to": d_to})

        # Slicing with product/category requires SaleItem join
        has_product_filter = bool(temp_ctx.product_ids or temp_ctx.categories or temp_ctx.subcategories)

        if not has_product_filter:
            stmt = select(
                func.coalesce(func.sum(Sale.subtotal), Decimal("0.00")).label("gross_sales"),
                func.coalesce(func.sum(Sale.discount_amount), Decimal("0.00")).label("discounts"),
                func.coalesce(
                    func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")
                ).label("net_sales"),
                func.count(Sale.id).label("orders"),
            )
            stmt = cls._apply_sale_filters(stmt, temp_ctx, Sale.transaction_date)
            row = session.execute(stmt).one()
            gross_sales = Decimal(str(row.gross_sales))
            discounts = Decimal(str(row.discounts))
            net_sales = Decimal(str(row.net_sales))
            orders = Decimal(str(row.orders))
        else:
            # Join SaleItem and Product
            stmt = (
                select(
                    func.coalesce(
                        func.sum(SaleItem.quantity * SaleItem.unit_price), Decimal("0.00")
                    ).label("gross_sales"),
                    func.coalesce(func.sum(SaleItem.discount_amount), Decimal("0.00")).label("discounts"),
                    func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("net_sales"),
                    func.count(func.distinct(Sale.id)).label("orders"),
                )
                .join(Sale, SaleItem.sale_id == Sale.id)
                .join(Product, SaleItem.product_id == Product.id)
            )
            stmt = cls._apply_sale_filters(stmt, temp_ctx, Sale.transaction_date)
            clauses = []
            if temp_ctx.product_ids:
                clauses.append(SaleItem.product_id.in_(temp_ctx.product_ids))
            if temp_ctx.categories:
                clauses.append(Product.category.in_(temp_ctx.categories))
            if temp_ctx.subcategories:
                clauses.append(Product.subcategory.in_(temp_ctx.subcategories))
            if clauses:
                stmt = stmt.where(and_(*clauses))
            row = session.execute(stmt).one()
            gross_sales = Decimal(str(row.gross_sales))
            discounts = Decimal(str(row.discounts))
            net_sales = Decimal(str(row.net_sales))
            orders = Decimal(str(row.orders))

        aov = (net_sales / orders) if orders > 0 else Decimal("0.00")
        aov = aov.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return {
            "gross_sales": gross_sales,
            "discounts": discounts,
            "net_sales": net_sales,
            "orders": orders,
            "aov": aov,
        }

    @classmethod
    def compute_units_and_cogs(
        cls, session: Session, context: AnalysisContext, is_comparison: bool = False
    ) -> Dict[str, Decimal]:
        """
        Compute total physical Units Sold and COGS (Cost of Goods Sold).
        COGS = sum(quantity * product.unit_cost)
        """
        d_from = context.comparison_date_from if is_comparison else context.date_from
        d_to = context.comparison_date_to if is_comparison else context.date_to
        temp_ctx = context.model_copy(update={"date_from": d_from, "date_to": d_to})

        stmt = (
            select(
                func.coalesce(func.sum(SaleItem.quantity), 0).label("units_sold"),
                func.coalesce(
                    func.sum(SaleItem.quantity * Product.unit_cost), Decimal("0.00")
                ).label("cogs"),
            )
            .join(Sale, SaleItem.sale_id == Sale.id)
            .join(Product, SaleItem.product_id == Product.id)
        )
        stmt = cls._apply_sale_filters(stmt, temp_ctx, Sale.transaction_date)

        clauses = []
        if temp_ctx.product_ids:
            clauses.append(SaleItem.product_id.in_(temp_ctx.product_ids))
        if temp_ctx.categories:
            clauses.append(Product.category.in_(temp_ctx.categories))
        if temp_ctx.subcategories:
            clauses.append(Product.subcategory.in_(temp_ctx.subcategories))
        if clauses:
            stmt = stmt.where(and_(*clauses))

        row = session.execute(stmt).one()
        units_sold = Decimal(str(row.units_sold))
        cogs = Decimal(str(row.cogs)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {"units_sold": units_sold, "cogs": cogs}

    @classmethod
    def compute_operating_expenses(
        cls, session: Session, context: AnalysisContext, is_comparison: bool = False
    ) -> Decimal:
        """Compute sum of operating expenses for the interval."""
        d_from = context.comparison_date_from if is_comparison else context.date_from
        d_to = context.comparison_date_to if is_comparison else context.date_to

        stmt = select(func.coalesce(func.sum(Expense.amount), Decimal("0.00")).label("opex"))
        clauses = []
        if d_from:
            clauses.append(Expense.expense_date >= d_from.date())
        if d_to:
            clauses.append(Expense.expense_date <= d_to.date())
        if clauses:
            stmt = stmt.where(and_(*clauses))

        val = session.execute(stmt).scalar_one()
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def evaluate_summary(
        cls, session: Session, context: AnalysisContext
    ) -> FinancialSummaryResult:
        """
        Evaluate full 12-metric financial summary with optional period-over-period comparison.
        """
        # Primary evaluation
        s_agg = cls.compute_sales_aggregates(session, context, is_comparison=False)
        u_agg = cls.compute_units_and_cogs(session, context, is_comparison=False)
        opex = cls.compute_operating_expenses(session, context, is_comparison=False)

        gross_sales = s_agg["gross_sales"]
        discounts = s_agg["discounts"]
        net_sales = s_agg["net_sales"]
        orders = s_agg["orders"]
        aov = s_agg["aov"]
        units_sold = u_agg["units_sold"]
        cogs = u_agg["cogs"]

        gross_profit = (net_sales - cogs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        gross_margin = (
            ((gross_profit / net_sales) * Decimal("100.0")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if net_sales > 0
            else Decimal("0.00")
        )

        net_profit = (gross_profit - opex).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        net_margin = (
            ((net_profit / net_sales) * Decimal("100.0")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if net_sales > 0
            else Decimal("0.00")
        )

        # Baseline evaluation if comparison requested
        comparisons: Optional[Dict[str, ComparisonResult]] = None
        if context.has_comparison:
            prev_s = cls.compute_sales_aggregates(session, context, is_comparison=True)
            prev_u = cls.compute_units_and_cogs(session, context, is_comparison=True)
            prev_opex = cls.compute_operating_expenses(session, context, is_comparison=True)

            prev_gs = prev_s["gross_sales"]
            prev_disc = prev_s["discounts"]
            prev_ns = prev_s["net_sales"]
            prev_ord = prev_s["orders"]
            prev_aov = prev_s["aov"]
            prev_units = prev_u["units_sold"]
            prev_cogs = prev_u["cogs"]
            prev_gp = (prev_ns - prev_cogs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            prev_gm = (
                ((prev_gp / prev_ns) * Decimal("100.0")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if prev_ns > 0
                else Decimal("0.00")
            )
            prev_np = (prev_gp - prev_opex).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            prev_nm = (
                ((prev_np / prev_ns) * Decimal("100.0")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if prev_ns > 0
                else Decimal("0.00")
            )

            comparisons = {
                "gross_sales": calculate_comparison(gross_sales, prev_gs, MetricUnit.CURRENCY),
                "discounts": calculate_comparison(discounts, prev_disc, MetricUnit.CURRENCY),
                "net_sales": calculate_comparison(net_sales, prev_ns, MetricUnit.CURRENCY),
                "units_sold": calculate_comparison(units_sold, prev_units, MetricUnit.UNITS),
                "orders": calculate_comparison(orders, prev_ord, MetricUnit.COUNT),
                "average_order_value": calculate_comparison(aov, prev_aov, MetricUnit.CURRENCY),
                "cogs": calculate_comparison(cogs, prev_cogs, MetricUnit.CURRENCY),
                "gross_profit": calculate_comparison(gross_profit, prev_gp, MetricUnit.CURRENCY),
                "gross_margin": calculate_comparison(gross_margin, prev_gm, MetricUnit.PERCENTAGE),
                "operating_expenses": calculate_comparison(opex, prev_opex, MetricUnit.CURRENCY),
                "net_profit": calculate_comparison(net_profit, prev_np, MetricUnit.CURRENCY),
                "net_margin": calculate_comparison(net_margin, prev_nm, MetricUnit.PERCENTAGE),
            }

        return FinancialSummaryResult(
            gross_sales=MetricValue(
                name="gross_sales",
                value=gross_sales,
                formatted=_format_value(gross_sales, MetricUnit.CURRENCY),
                unit=MetricUnit.CURRENCY,
                description="Total pre-discount transaction value",
            ),
            discounts=MetricValue(
                name="discounts",
                value=discounts,
                formatted=_format_value(discounts, MetricUnit.CURRENCY),
                unit=MetricUnit.CURRENCY,
                description="Order-level promotional discount reductions",
            ),
            net_sales=MetricValue(
                name="net_sales",
                value=net_sales,
                formatted=_format_value(net_sales, MetricUnit.CURRENCY),
                unit=MetricUnit.CURRENCY,
                description="Realized commercial revenue excluding tax",
            ),
            units_sold=MetricValue(
                name="units_sold",
                value=units_sold,
                formatted=_format_value(units_sold, MetricUnit.UNITS),
                unit=MetricUnit.UNITS,
                description="Physical count of items sold",
            ),
            orders=MetricValue(
                name="orders",
                value=orders,
                formatted=_format_value(orders, MetricUnit.COUNT),
                unit=MetricUnit.COUNT,
                description="Distinct transaction orders fulfilled",
            ),
            average_order_value=MetricValue(
                name="average_order_value",
                value=aov,
                formatted=_format_value(aov, MetricUnit.CURRENCY),
                unit=MetricUnit.CURRENCY,
                description="Mean revenue per transaction",
            ),
            cogs=MetricValue(
                name="cogs",
                value=cogs,
                formatted=_format_value(cogs, MetricUnit.CURRENCY),
                unit=MetricUnit.CURRENCY,
                description="Cost of Goods Sold based on unit costs",
            ),
            gross_profit=MetricValue(
                name="gross_profit",
                value=gross_profit,
                formatted=_format_value(gross_profit, MetricUnit.CURRENCY),
                unit=MetricUnit.CURRENCY,
                description="Net Sales minus COGS",
            ),
            gross_margin=MetricValue(
                name="gross_margin",
                value=gross_margin,
                formatted=_format_value(gross_margin, MetricUnit.PERCENTAGE),
                unit=MetricUnit.PERCENTAGE,
                description="Gross Profit as percentage of Net Sales",
            ),
            operating_expenses=MetricValue(
                name="operating_expenses",
                value=opex,
                formatted=_format_value(opex, MetricUnit.CURRENCY),
                unit=MetricUnit.CURRENCY,
                description="Total operational overhead expenses",
            ),
            net_profit=MetricValue(
                name="net_profit",
                value=net_profit,
                formatted=_format_value(net_profit, MetricUnit.CURRENCY),
                unit=MetricUnit.CURRENCY,
                description="Gross Profit minus Operating Expenses",
            ),
            net_margin=MetricValue(
                name="net_margin",
                value=net_margin,
                formatted=_format_value(net_margin, MetricUnit.PERCENTAGE),
                unit=MetricUnit.PERCENTAGE,
                description="Net Profit as percentage of Net Sales",
            ),
            comparison=comparisons,
        )
