"""Deterministic computation of core financial metrics and period-over-period comparisons."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Tuple, Any
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
    GrossToNetStep,
    GrossToNetWaterfallResult,
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


def _format_value(
    val: Optional[Decimal],
    unit: MetricUnit,
    fallback: str = "N/A",
    currency_symbol: str = "$",
) -> str:
    """Format decimal value into human-friendly string."""
    if val is None:
        return fallback
    if unit == MetricUnit.CURRENCY:
        return f"{currency_symbol}{val:,.2f}"
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
        if context.business_id:
            clauses.append(Sale.business_id == context.business_id)
        if context.date_from:
            clauses.append(date_col >= context.date_from)
        if context.date_to:
            clauses.append(date_col <= context.date_to)
        statuses = context.statuses if context.statuses is not None else ["completed", "shipped"]
        if statuses:
            clauses.append(Sale.status.in_(statuses))
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
        Compute Gross Sales, Discounts, Net Sales (Revenue), Orders, Tax, and Billed Totals.
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
                func.count(func.distinct(Sale.id)).label("orders"),
                func.coalesce(func.sum(Sale.tax_amount), Decimal("0.00")).label("tax_amount"),
                func.coalesce(func.sum(Sale.total_amount), Decimal("0.00")).label("total_billed"),
            )
            stmt = cls._apply_sale_filters(stmt, temp_ctx, Sale.transaction_date)
            row = session.execute(stmt).one()
            gross_sales = Decimal(str(row.gross_sales))
            order_discounts = Decimal(str(row.discounts))
            discounts = order_discounts
            net_sales = Decimal(str(row.net_sales))
            orders = Decimal(str(row.orders))
            tax_amount = Decimal(str(row.tax_amount))
            total_billed = Decimal(str(row.total_billed))

            # Query line item discounts if items exist
            line_disc_stmt = (
                select(func.coalesce(func.sum(SaleItem.discount_amount), Decimal("0.00")))
                .join(Sale, SaleItem.sale_id == Sale.id)
            )
            line_disc_stmt = cls._apply_sale_filters(line_disc_stmt, temp_ctx, Sale.transaction_date)
            line_discounts = Decimal(str(session.execute(line_disc_stmt).scalar() or Decimal("0.00")))
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
            line_discounts = Decimal(str(row.discounts))
            discounts = line_discounts
            order_discounts = Decimal("0.00")
            net_sales = Decimal(str(row.net_sales))
            orders = Decimal(str(row.orders))
            tax_amount = Decimal("0.00")
            total_billed = net_sales

        # Query refunded orders (status == 'refunded')
        refund_ctx = temp_ctx.model_copy(update={"statuses": ["refunded"]})
        if has_product_filter:
            refund_stmt = (
                select(
                    func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("returns_amount"),
                    func.count(func.distinct(Sale.id)).label("returns_count"),
                )
                .join(Sale, SaleItem.sale_id == Sale.id)
                .join(Product, SaleItem.product_id == Product.id)
            )
            refund_stmt = cls._apply_sale_filters(refund_stmt, refund_ctx, Sale.transaction_date)
            clauses = []
            if temp_ctx.product_ids:
                clauses.append(SaleItem.product_id.in_(temp_ctx.product_ids))
            if temp_ctx.categories:
                clauses.append(Product.category.in_(temp_ctx.categories))
            if temp_ctx.subcategories:
                clauses.append(Product.subcategory.in_(temp_ctx.subcategories))
            if clauses:
                refund_stmt = refund_stmt.where(and_(*clauses))
        else:
            refund_stmt = select(
                func.coalesce(func.sum(Sale.subtotal), Decimal("0.00")).label("returns_amount"),
                func.count(func.distinct(Sale.id)).label("returns_count"),
            )
            refund_stmt = cls._apply_sale_filters(refund_stmt, refund_ctx, Sale.transaction_date)
        ref_row = session.execute(refund_stmt).one()
        returns_amount = Decimal(str(ref_row.returns_amount))
        returns_count = Decimal(str(ref_row.returns_count))

        aov = (net_sales / orders) if orders > 0 else Decimal("0.00")
        aov = aov.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return {
            "gross_sales": gross_sales,
            "discounts": discounts,
            "net_sales": net_sales,
            "orders": orders,
            "aov": aov,
            "tax_amount": tax_amount,
            "total_billed": total_billed,
            "order_discounts": order_discounts,
            "line_discounts": line_discounts,
            "returns_amount": returns_amount,
            "returns_count": returns_count,
        }

    @classmethod
    def compute_units_and_cogs(
        cls,
        session: Session,
        context: AnalysisContext,
        is_comparison: bool = False,
        net_sales: Optional[Decimal] = None,
        orders: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """
        Compute total physical Units Sold and COGS (Cost of Goods Sold).
        COGS = sum(quantity * product.unit_cost)
        
        If sales exist but required product catalog or unit-cost data is missing,
        COGS is NOT fabricated as zero; it is returned as None so gross margin/profit
        metrics are accurately marked incomplete or unavailable.
        """
        d_from = context.comparison_date_from if is_comparison else context.date_from
        d_to = context.comparison_date_to if is_comparison else context.date_to
        temp_ctx = context.model_copy(update={"date_from": d_from, "date_to": d_to})

        # 1. Total units from SaleItem (if items exist)
        units_stmt = (
            select(func.coalesce(func.sum(SaleItem.quantity), 0))
            .join(Sale, SaleItem.sale_id == Sale.id)
        )
        units_stmt = cls._apply_sale_filters(units_stmt, temp_ctx, Sale.transaction_date)
        if temp_ctx.product_ids:
            units_stmt = units_stmt.where(SaleItem.product_id.in_(temp_ctx.product_ids))
        total_units = session.execute(units_stmt).scalar() or 0
        units_sold = Decimal(str(total_units))

        # 2. Check if product catalog costs exist
        prod_cost_stmt = select(func.count(Product.id)).where(Product.unit_cost.isnot(None))
        if temp_ctx.business_id:
            prod_cost_stmt = prod_cost_stmt.where(Product.business_id == temp_ctx.business_id)
        if temp_ctx.product_ids:
            prod_cost_stmt = prod_cost_stmt.where(Product.id.in_(temp_ctx.product_ids))
        if temp_ctx.categories:
            prod_cost_stmt = prod_cost_stmt.where(Product.category.in_(temp_ctx.categories))
        if temp_ctx.subcategories:
            prod_cost_stmt = prod_cost_stmt.where(Product.subcategory.in_(temp_ctx.subcategories))
        products_with_cost_count = session.execute(prod_cost_stmt).scalar() or 0

        # 3. Check costed sale items (SaleItem joined to Product with unit_cost)
        cogs_stmt = (
            select(
                func.count(SaleItem.id).label("costed_items_count"),
                func.sum(SaleItem.quantity * Product.unit_cost).label("cogs"),
            )
            .join(Sale, SaleItem.sale_id == Sale.id)
            .join(Product, SaleItem.product_id == Product.id)
        )
        cogs_stmt = cls._apply_sale_filters(cogs_stmt, temp_ctx, Sale.transaction_date)
        clauses = []
        if temp_ctx.product_ids:
            clauses.append(SaleItem.product_id.in_(temp_ctx.product_ids))
        if temp_ctx.categories:
            clauses.append(Product.category.in_(temp_ctx.categories))
        if temp_ctx.subcategories:
            clauses.append(Product.subcategory.in_(temp_ctx.subcategories))
        if clauses:
            cogs_stmt = cogs_stmt.where(and_(*clauses))
        cogs_row = session.execute(cogs_stmt).one()
        costed_items_count = cogs_row.costed_items_count or 0
        raw_cogs = cogs_row.cogs

        # Resolve sales existence if not provided
        if net_sales is None and orders is None:
            s_check = cls.compute_sales_aggregates(session, context, is_comparison=is_comparison)
            net_sales = s_check["net_sales"]
            orders = s_check["orders"]

        has_sales = (orders is not None and orders > Decimal("0")) or (
            net_sales is not None and net_sales > Decimal("0.00")
        )

        if not has_sales:
            cogs = Decimal("0.00")
            cogs_available = True
        elif products_with_cost_count == 0 or costed_items_count == 0:
            cogs = None
            cogs_available = False
        else:
            cogs = Decimal(str(raw_cogs or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            cogs_available = True

        return {"units_sold": units_sold, "cogs": cogs, "cogs_available": cogs_available}

    @classmethod
    def compute_operating_expenses(
        cls, session: Session, context: AnalysisContext, is_comparison: bool = False
    ) -> Decimal:
        """Compute sum of operating expenses for the interval."""
        d_from = context.comparison_date_from if is_comparison else context.date_from
        d_to = context.comparison_date_to if is_comparison else context.date_to

        stmt = select(func.coalesce(func.sum(Expense.amount), Decimal("0.00")).label("opex"))
        clauses = []
        if context.business_id:
            clauses.append(Expense.business_id == context.business_id)
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
        u_agg = cls.compute_units_and_cogs(
            session, context, is_comparison=False, net_sales=s_agg["net_sales"], orders=s_agg["orders"]
        )
        opex = cls.compute_operating_expenses(session, context, is_comparison=False)

        gross_sales = s_agg["gross_sales"]
        discounts = s_agg["discounts"]
        net_sales = s_agg["net_sales"]
        orders = s_agg["orders"]
        aov = s_agg["aov"]
        units_sold = u_agg["units_sold"]
        cogs = u_agg["cogs"]

        if cogs is not None:
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
        else:
            # Missing product costs / COGS: do NOT fabricate or assume zero COGS
            gross_profit = None
            gross_margin = None
            net_profit = None
            net_margin = None

        # Baseline evaluation if comparison requested
        comparisons: Optional[Dict[str, ComparisonResult]] = None
        if context.has_comparison:
            prev_s = cls.compute_sales_aggregates(session, context, is_comparison=True)
            prev_u = cls.compute_units_and_cogs(
                session, context, is_comparison=True, net_sales=prev_s["net_sales"], orders=prev_s["orders"]
            )
            prev_opex = cls.compute_operating_expenses(session, context, is_comparison=True)

            prev_gs = prev_s["gross_sales"]
            prev_disc = prev_s["discounts"]
            prev_ns = prev_s["net_sales"]
            prev_ord = prev_s["orders"]
            prev_aov = prev_s["aov"]
            prev_units = prev_u["units_sold"]
            prev_cogs = prev_u["cogs"]

            if prev_cogs is not None:
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
            else:
                prev_gp = None
                prev_gm = None
                prev_np = None
                prev_nm = None

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

        sym = context.currency_symbol or "$"

        return FinancialSummaryResult(
            currency=context.currency or "USD",
            currency_symbol=sym,
            gross_sales=MetricValue(
                name="gross_sales",
                value=gross_sales,
                formatted=_format_value(gross_sales, MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Total pre-discount transaction value",
            ),
            discounts=MetricValue(
                name="discounts",
                value=discounts,
                formatted=_format_value(discounts, MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Order-level promotional discount reductions",
            ),
            net_sales=MetricValue(
                name="net_sales",
                value=net_sales,
                formatted=_format_value(net_sales, MetricUnit.CURRENCY, currency_symbol=sym),
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
                formatted=_format_value(aov, MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Mean revenue per transaction",
            ),
            cogs=MetricValue(
                name="cogs",
                value=cogs,
                formatted=_format_value(cogs, MetricUnit.CURRENCY, fallback="Incomplete", currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description=(
                    "Cost of Goods Sold based on unit costs"
                    if cogs is not None
                    else "Cost of Goods Sold unavailable: catalog product unit costs are missing"
                ),
            ),
            gross_profit=MetricValue(
                name="gross_profit",
                value=gross_profit,
                formatted=_format_value(gross_profit, MetricUnit.CURRENCY, fallback="Incomplete", currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description=(
                    "Net Sales minus COGS"
                    if gross_profit is not None
                    else "Gross Profit unavailable: missing required product cost data"
                ),
            ),
            gross_margin=MetricValue(
                name="gross_margin",
                value=gross_margin,
                formatted=_format_value(gross_margin, MetricUnit.PERCENTAGE, fallback="Incomplete"),
                unit=MetricUnit.PERCENTAGE,
                description=(
                    "Gross Profit as percentage of Net Sales"
                    if gross_margin is not None
                    else "Gross Margin unavailable: missing required product cost data"
                ),
            ),
            operating_expenses=MetricValue(
                name="operating_expenses",
                value=opex,
                formatted=_format_value(opex, MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Total operational overhead expenses",
            ),
            net_profit=MetricValue(
                name="net_profit",
                value=net_profit,
                formatted=_format_value(net_profit, MetricUnit.CURRENCY, fallback="Incomplete", currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description=(
                    "Gross Profit minus Operating Expenses"
                    if net_profit is not None
                    else "Net Profit unavailable: depends on missing Gross Profit / COGS data"
                ),
            ),
            net_margin=MetricValue(
                name="net_margin",
                value=net_margin,
                formatted=_format_value(net_margin, MetricUnit.PERCENTAGE, fallback="Incomplete"),
                unit=MetricUnit.PERCENTAGE,
                description=(
                    "Net Profit as percentage of Net Sales"
                    if net_margin is not None
                    else "Net Margin unavailable: depends on missing Gross Profit / COGS data"
                ),
            ),
            comparison=comparisons,
            tax_amount=MetricValue(
                name="tax_amount",
                value=s_agg["tax_amount"],
                formatted=_format_value(s_agg["tax_amount"], MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Sales tax / VAT collected (balance sheet liability)",
            ),
            total_billed=MetricValue(
                name="total_billed",
                value=s_agg["total_billed"],
                formatted=_format_value(s_agg["total_billed"], MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Total billed amount: Net Sales + Tax",
            ),
            order_discounts=MetricValue(
                name="order_discounts",
                value=s_agg["order_discounts"],
                formatted=_format_value(s_agg["order_discounts"], MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Order-level promotional checkout discounts",
            ),
            line_discounts=MetricValue(
                name="line_discounts",
                value=s_agg["line_discounts"],
                formatted=_format_value(s_agg["line_discounts"], MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Line-item trade discounts",
            ),
            returns_amount=MetricValue(
                name="returns_amount",
                value=s_agg["returns_amount"],
                formatted=_format_value(s_agg["returns_amount"], MetricUnit.CURRENCY, currency_symbol=sym),
                unit=MetricUnit.CURRENCY,
                description="Total value of refunded transactions",
            ),
            returns_count=MetricValue(
                name="returns_count",
                value=s_agg["returns_count"],
                formatted=_format_value(s_agg["returns_count"], MetricUnit.COUNT),
                unit=MetricUnit.COUNT,
                description="Count of refunded transactions",
            ),
        )

    @classmethod
    def evaluate_gross_to_net_waterfall(
        cls, session: Session, context: AnalysisContext
    ) -> GrossToNetWaterfallResult:
        """
        Evaluate complete commercial gross-to-net waterfall:
        Gross Line Sales -> Line Discounts -> Order Subtotal -> Order Discounts -> Net Sales -> Sales Tax -> Total Billed.
        Also tracks Refunds and Net Revenue After Returns.
        """
        sym = context.currency_symbol or "$"
        s_agg = cls.compute_sales_aggregates(session, context, is_comparison=False)

        has_product_filter = bool(context.product_ids or context.categories or context.subcategories)

        if has_product_filter:
            gross_sales = s_agg["gross_sales"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            line_discounts = s_agg["line_discounts"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            order_subtotal = (gross_sales - line_discounts).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            order_discounts = Decimal("0.00")
            total_discounts = line_discounts
            net_sales = s_agg["net_sales"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax_amount = Decimal("0.00")
            total_billed = net_sales
        else:
            # Check if line items exist for gross list price calculation across all products
            gross_item_stmt = (
                select(func.coalesce(func.sum(SaleItem.quantity * SaleItem.unit_price), Decimal("0.00")))
                .join(Sale, SaleItem.sale_id == Sale.id)
            )
            gross_item_stmt = cls._apply_sale_filters(gross_item_stmt, context, Sale.transaction_date)
            raw_gross_items = session.execute(gross_item_stmt).scalar()

            if raw_gross_items and Decimal(str(raw_gross_items)) > Decimal("0.00"):
                gross_sales = Decimal(str(raw_gross_items)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                line_discounts = s_agg["line_discounts"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                line_discounts = Decimal("0.00")
                gross_sales = s_agg["gross_sales"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            order_subtotal = (gross_sales - line_discounts).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            order_discounts = s_agg["order_discounts"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_discounts = (line_discounts + order_discounts).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            net_sales = (order_subtotal - order_discounts).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax_amount = s_agg["tax_amount"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_billed = (net_sales + tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        refunds_amount = s_agg["returns_amount"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        refunds_count = int(s_agg["returns_count"])
        # Because refunded orders in the schema are independent terminal transactions already excluded
        # from completed sales (statuses=['completed', 'shipped']), net_sales is the true commercial net sales.
        # We do not subtract independent refund transaction rows from completed sales a second time.
        net_revenue_after_returns = net_sales

        steps = [
            GrossToNetStep(
                key="gross_sales",
                name="Gross Sales (List Price)",
                amount=gross_sales,
                formatted=_format_value(gross_sales, MetricUnit.CURRENCY, currency_symbol=sym),
                impact="positive",
                description="Total pre-discount merchandise value at catalog unit prices",
            ),
            GrossToNetStep(
                key="line_discounts",
                name="Line-Item Discounts",
                amount=-line_discounts,
                formatted=_format_value(line_discounts, MetricUnit.CURRENCY, currency_symbol=sym),
                impact="negative",
                description="Trade promotions and item-level price reductions",
            ),
            GrossToNetStep(
                key="order_subtotal",
                name="Order Subtotal",
                amount=order_subtotal,
                formatted=_format_value(order_subtotal, MetricUnit.CURRENCY, currency_symbol=sym),
                impact="subtotal",
                description="Merchandise value before checkout / cart-level discounts",
            ),
            GrossToNetStep(
                key="order_discounts",
                name="Order-Level Discounts",
                amount=-order_discounts,
                formatted=_format_value(order_discounts, MetricUnit.CURRENCY, currency_symbol=sym),
                impact="negative",
                description="Cart coupons, loyalty redemptions, and order promotional discounts",
            ),
            GrossToNetStep(
                key="net_sales",
                name="Net Sales (Commercial Revenue)",
                amount=net_sales,
                formatted=_format_value(net_sales, MetricUnit.CURRENCY, currency_symbol=sym),
                impact="subtotal",
                description="Recognized GAAP commercial revenue excluding sales tax",
            ),
            GrossToNetStep(
                key="tax_amount",
                name="Sales Tax / VAT",
                amount=tax_amount,
                formatted=_format_value(tax_amount, MetricUnit.CURRENCY, currency_symbol=sym),
                impact="positive",
                description="Sales tax / VAT collected on behalf of taxing authorities (balance sheet liability)",
            ),
            GrossToNetStep(
                key="total_billed",
                name="Total Billed Amount",
                amount=total_billed,
                formatted=_format_value(total_billed, MetricUnit.CURRENCY, currency_symbol=sym),
                impact="subtotal",
                description="Final cash / receivables charged to customers (Net Sales + Tax)",
            ),
        ]

        evidence_notes = [
            "Net Sales represents recognized commercial revenue from completed and shipped transactions.",
            f"Line-item discounts ({_format_value(line_discounts, MetricUnit.CURRENCY, currency_symbol=sym)}) and order discounts ({_format_value(order_discounts, MetricUnit.CURRENCY, currency_symbol=sym)}) are tracked separately to prevent double-counting.",
            "Sales tax is strictly segregated from commercial revenue as a balance sheet liability.",
            f"Refund transaction volume ({refunds_count} orders totalling {_format_value(refunds_amount, MetricUnit.CURRENCY, currency_symbol=sym)}) represents independent terminal-state transactions already excluded from completed net sales; it is tracked separately and not deducted a second time.",
        ]
        if has_product_filter:
            evidence_notes.append(
                "Product-level filtering reconciles line-item gross sales, line discounts, and net line total; order-level discounts and sales tax are unallocated."
            )

        return GrossToNetWaterfallResult(
            currency=context.currency or "USD",
            currency_symbol=sym,
            gross_sales=gross_sales,
            line_discounts=line_discounts,
            order_subtotal=order_subtotal,
            order_discounts=order_discounts,
            total_discounts=total_discounts,
            net_sales=net_sales,
            tax_amount=tax_amount,
            total_billed=total_billed,
            refunds_amount=refunds_amount,
            refunds_count=refunds_count,
            net_revenue_after_returns=net_revenue_after_returns,
            steps=steps,
            evidence_notes=evidence_notes,
        )
