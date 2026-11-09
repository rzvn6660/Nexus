"""Family G: Commercial and Financial Analytics Analyst Skills."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.analyst.base import BaseAnalystSkill
from app.analytics.analyst.models import (
    ExecutionContext,
    SkillDomain,
    SkillExecutionResult,
    SkillMetadata,
)
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business


class RevenuePerformanceSkill(BaseAnalystSkill):
    """Calculates comprehensive commercial top-line metrics: net revenue, gross sales, discounts."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="revenue_performance",
                name="Revenue Performance Analyst",
                description="Audits top-line commercial revenue: gross sales, discounts, taxes, and final net billed total.",
                domain=SkillDomain.COMMERCIAL,
                version="1.0.0",
                activation_conditions=["Revenue performance", "How much did we make?", "Top line revenue"],
                required_input_data=["sales"],
                methodology="Exact relational aggregation across completed commercial transactions.",
                confidence_methodology="Deterministic exact financial arithmetic.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        stats = db.execute(
            select(
                func.count(Sale.id),
                func.sum(Sale.subtotal),
                func.sum(Sale.discount_amount),
                func.sum(Sale.tax_amount),
                func.sum(Sale.total_amount),
            ).where(Sale.business_id == biz_id, Sale.status == "completed")
        ).first()

        order_count = (stats[0] or 0) if stats else 0
        subtotal = float(stats[1] or 0) if stats else 0.0
        discounts = float(stats[2] or 0) if stats else 0.0
        taxes = float(stats[3] or 0) if stats else 0.0
        net_revenue = float(stats[4] or 0) if stats else 0.0
        aov = (net_revenue / order_count) if order_count else 0.0

        findings = [
            f"Net billed revenue: ${net_revenue:,.2f} across {order_count:,} completed orders.",
            f"Gross subtotal: ${subtotal:,.2f} less ${discounts:,.2f} discounts plus ${taxes:,.2f} tax.",
            f"Average Order Value (AOV): ${aov:.2f}.",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "order_count": order_count,
                "gross_subtotal": round(subtotal, 2),
                "discounts": round(discounts, 2),
                "taxes": round(taxes, 2),
                "net_revenue": round(net_revenue, 2),
                "aov": round(aov, 2),
            },
            calculations=[
                {"formula": "net_revenue = subtotal - discounts + taxes", "result": f"${net_revenue:,.2f}"},
                {"formula": "AOV = net_revenue / order_count", "result": f"${aov:.2f}"},
            ],
            findings=findings,
            confidence_score=1.0,
        )


class GrossMarginAnalysisSkill(BaseAnalystSkill):
    """Calculates gross profit dollars and gross margin percentage."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="gross_margin_analysis",
                name="Gross Margin Financial Analyst",
                description="Calculates gross profit dollars and gross margin percentage by subtracting COGS from revenue.",
                domain=SkillDomain.COMMERCIAL,
                version="1.0.0",
                activation_conditions=["Gross margin", "Profitability", "COGS analysis"],
                required_input_data=["sales", "sale_items", "products"],
                methodology="Item line revenue minus item quantity * unit_cost.",
                confidence_methodology="Exact product catalog COGS subtraction.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        # Query itemized sales lines with linked product catalog data
        items = db.execute(
            select(
                SaleItem.id,
                SaleItem.line_total,
                SaleItem.quantity,
                Product.unit_cost,
                Product.selling_price,
                Product.name,
            )
            .join(Sale, SaleItem.sale_id == Sale.id)
            .join(Product, SaleItem.product_id == Product.id)
            .where(Sale.business_id == biz_id, Sale.status == "completed")
        ).all()

        # Query total aggregate sales in case itemized lines are absent
        sale_stats = db.execute(
            select(func.sum(Sale.total_amount), func.count(Sale.id))
            .where(Sale.business_id == biz_id, Sale.status == "completed")
        ).first()
        total_sale_rev = float(sale_stats[0] or 0.0) if sale_stats else 0.0

        # Query product catalog to determine verified cost presence
        catalog_prods = db.execute(
            select(Product.selling_price, Product.unit_cost, Product.name)
            .where(Product.business_id == biz_id)
        ).all()

        verified_catalog_prods = [
            p for p in catalog_prods
            if p.unit_cost and p.unit_cost > Decimal("0.00") and not (p.name or "").startswith("Uncataloged Product")
        ]

        # Calculate catalog average markup/cost ratio if available
        ratios = [
            float(p.unit_cost / p.selling_price)
            for p in verified_catalog_prods
            if p.selling_price and p.selling_price > Decimal("0.00")
        ]
        avg_cost_ratio = float(np.mean(ratios)) if ratios else None

        rev = sum(float(i.line_total or 0.0) for i in items) if items else total_sale_rev
        if rev == 0.0 and total_sale_rev > 0.0:
            rev = total_sale_rev

        if rev == 0.0:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="SUCCESS",
                data={
                    "item_revenue": 0.0,
                    "cogs": 0.0,
                    "gross_profit": 0.0,
                    "gross_margin_pct": 0.0,
                    "cost_classification": "UNAVAILABLE",
                    "estimation_method": None,
                },
                calculations=[{"metric": "gross_margin", "value": "0.0%"}],
                findings=["No completed sales found in current workspace."],
                confidence_score=1.0,
            )

        # Classify cost availability and compute gross profit
        if items:
            verified_items = [
                i for i in items
                if i.unit_cost and i.unit_cost > Decimal("0.00") and not (i.name or "").startswith("Uncataloged Product")
            ]

            is_sandbox = False
            biz = db.execute(select(Business).where(Business.id == biz_id)).scalar_one_or_none()
            if biz:
                if any(x in (biz.name or "").lower() for x in ["sandbox", "synthetic", "pilot"]):
                    is_sandbox = True
                biz_meta = getattr(biz, "metadata_json", None) or {}
                if isinstance(biz_meta, dict) and (
                    biz_meta.get("is_sandbox") or biz_meta.get("tenant_type") == "sandbox"
                ):
                    is_sandbox = True

            if len(verified_items) == len(items) and len(items) > 0 and not is_sandbox:
                # 1. ACTUAL PROFITABILITY: All sold items have verified catalog unit cost on non-sandbox tenant
                cost_classification = "ACTUAL"
                estimation_method = None
                cogs = sum(float(i.quantity * i.unit_cost) for i in items)
                gross_profit = rev - cogs
                margin_pct = (gross_profit / rev * 100.0) if rev else 0.0
                confidence = 0.98
                findings = [
                    "Cost classification: ACTUAL (derived from verified product catalog unit costs).",
                    f"Gross profit: ${gross_profit:,.2f} on ${rev:,.2f} itemized sales.",
                    f"Gross margin percentage: {margin_pct:.1f}% (Total COGS: ${cogs:,.2f}).",
                ]
                calculations = [
                    {"formula": "gross_profit = revenue - COGS", "result": f"${gross_profit:,.2f}"},
                    {"formula": "gross_margin_pct = (gross_profit / revenue) * 100", "result": f"{margin_pct:.1f}%"},
                ]
            elif len(verified_items) == len(items) and len(items) > 0 and is_sandbox:
                # 1B. SYNTHETIC DEMONSTRATION PROFITABILITY: Costs are synthetic, must be labeled ESTIMATED
                cost_classification = "ESTIMATED"
                estimation_method = "synthetic_labeled_costs"
                cogs = sum(float(i.quantity * i.unit_cost) for i in items)
                gross_profit = rev - cogs
                margin_pct = (gross_profit / rev * 100.0) if rev else 0.0
                confidence = 0.85
                findings = [
                    "Cost classification: ESTIMATED (synthetic demonstration unit costs — never presented as actual audited COGS).",
                    f"Estimated Gross profit: ${gross_profit:,.2f} on ${rev:,.2f} itemized sales.",
                    f"Estimated Gross margin percentage: {margin_pct:.1f}% (Synthetic COGS: ${cogs:,.2f}).",
                    "Demonstration Notice: Unit costs are synthetic benchmark figures; actual merchant margin requires verified vendor invoices.",
                ]
                calculations = [
                    {"formula": "estimated_gross_profit = revenue - synthetic_COGS", "result": f"${gross_profit:,.2f}"},
                    {"formula": "estimated_gross_margin_pct = (estimated_gross_profit / revenue) * 100", "result": f"{margin_pct:.1f}%"},
                ]
            elif avg_cost_ratio is not None:
                # 2. ESTIMATED PROFITABILITY: Some or all items lack cost, but catalog has verified cost baseline
                cost_classification = "ESTIMATED"
                estimation_method = "catalog_average_markup"
                cogs = 0.0
                for i in items:
                    if i in verified_items:
                        cogs += float(i.quantity * i.unit_cost)
                    else:
                        cogs += float(i.line_total or 0.0) * avg_cost_ratio
                gross_profit = rev - cogs
                margin_pct = (gross_profit / rev * 100.0) if rev else 0.0
                confidence = 0.72
                findings = [
                    "Cost classification: ESTIMATED (method: catalog_average_markup).",
                    f"Estimated Gross profit: ${gross_profit:,.2f} on ${rev:,.2f} sales.",
                    f"Estimated Gross margin percentage: {margin_pct:.1f}% (Estimated COGS: ${cogs:,.2f}).",
                    f"Notice: Cost data estimated using catalog average cost ratio ({avg_cost_ratio * 100:.1f}% of price); uncataloged items do not have verified vendor cost.",
                ]
                calculations = [
                    {"formula": f"estimated_cogs = revenue * catalog_ratio ({avg_cost_ratio:.2f})", "result": f"${cogs:,.2f}"},
                    {"formula": "estimated_gross_profit = revenue - estimated_cogs", "result": f"${gross_profit:,.2f}"},
                ]
            else:
                # 3. PROFITABILITY UNAVAILABLE: No catalog cost evidence exists
                cost_classification = "UNAVAILABLE"
                estimation_method = None
                cogs = None
                gross_profit = None
                margin_pct = None
                confidence = 0.0
                findings = [
                    "Cost classification: UNAVAILABLE.",
                    f"Total sales revenue is ${rev:,.2f}, but product cost data is completely missing.",
                    "Gross margin cannot be calculated without verified product costs or catalog markup rates.",
                    "NEXUS refuses to fabricate artificial product margins without cost evidence.",
                ]
                calculations = [
                    {"metric": "cost_classification", "value": "UNAVAILABLE"},
                    {"metric": "total_revenue", "value": f"${rev:,.2f}"},
                ]
        else:
            # Fallback when itemized lines are absent
            if avg_cost_ratio is not None:
                cost_classification = "ESTIMATED"
                estimation_method = "catalog_average_markup"
                cogs = round(rev * avg_cost_ratio, 2)
                gross_profit = rev - cogs
                margin_pct = (gross_profit / rev * 100.0) if rev else 0.0
                confidence = 0.65
                findings = [
                    "Cost classification: ESTIMATED (method: catalog_average_markup).",
                    f"Estimated Gross profit: ${gross_profit:,.2f} on ${rev:,.2f} aggregate sales.",
                    f"Estimated Gross margin percentage: {margin_pct:.1f}% (Estimated COGS: ${cogs:,.2f}).",
                    f"Notice: Itemized lines missing; COGS estimated from catalog average cost ratio ({avg_cost_ratio * 100:.1f}%).",
                ]
                calculations = [
                    {"formula": f"estimated_cogs = revenue * catalog_ratio ({avg_cost_ratio:.2f})", "result": f"${cogs:,.2f}"},
                ]
            else:
                cost_classification = "UNAVAILABLE"
                estimation_method = None
                cogs = None
                gross_profit = None
                margin_pct = None
                confidence = 0.0
                findings = [
                    "Cost classification: UNAVAILABLE.",
                    f"Total sales revenue is ${rev:,.2f}, but product cost data is completely missing.",
                    "Gross margin cannot be calculated without verified product costs or catalog markup rates.",
                ]
                calculations = [{"metric": "cost_classification", "value": "UNAVAILABLE"}]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "item_revenue": round(rev, 2),
                "cogs": round(cogs, 2) if cogs is not None else None,
                "gross_profit": round(gross_profit, 2) if gross_profit is not None else None,
                "gross_margin_pct": round(margin_pct, 1) if margin_pct is not None else None,
                "cost_classification": cost_classification,
                "estimation_method": estimation_method,
            },
            calculations=calculations,
            findings=findings,
            confidence_score=confidence,
        )


class SalesTrendAnalysisSkill(BaseAnalystSkill):
    """Calculates period-over-period revenue growth rates."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="sales_trend_analysis",
                name="Sales Trend & Growth Analyst",
                description="Measures period-over-period sales growth rates and velocity across equal sequential windows.",
                domain=SkillDomain.COMMERCIAL,
                version="1.0.0",
                activation_conditions=["Sales growth", "Revenue trends", "Are sales increasing?"],
                required_input_data=["sales"],
                methodology="Sequential 30-day window delta comparisons.",
                confidence_methodology="Exact arithmetic period comparison.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id
        now = datetime.now(UTC)

        p1_sales = db.execute(
            select(func.sum(Sale.total_amount))
            .where(Sale.business_id == biz_id, Sale.status == "completed", Sale.transaction_date >= now - timedelta(days=60), Sale.transaction_date < now - timedelta(days=30))
        ).scalar() or 0

        p2_sales = db.execute(
            select(func.sum(Sale.total_amount))
            .where(Sale.business_id == biz_id, Sale.status == "completed", Sale.transaction_date >= now - timedelta(days=30), Sale.transaction_date <= now)
        ).scalar() or 0

        r1 = float(p1_sales)
        r2 = float(p2_sales)
        growth_pct = ((r2 - r1) / r1 * 100) if r1 else 0.0

        findings = [
            f"30-day sequential revenue growth: {growth_pct:+.1f}% (${r2:,.2f} vs prior ${r1:,.2f}).",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "prior_30d_revenue": round(r1, 2),
                "recent_30d_revenue": round(r2, 2),
                "growth_pct": round(growth_pct, 1),
            },
            calculations=[
                {"formula": "(recent - prior) / prior", "result": f"{growth_pct:+.1f}%"},
            ],
            findings=findings,
            confidence_score=0.95,
        )


class ProductProfitabilitySkill(BaseAnalystSkill):
    """Ranks catalog SKUs by profit contribution and unit profitability."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="product_profitability",
                name="Product Profitability Analyst",
                description="Evaluates individual SKU profit margins to pinpoint highest margin and profit-eroding products.",
                domain=SkillDomain.COMMERCIAL,
                version="1.0.0",
                activation_conditions=["Which products are most profitable?", "Product profitability", "SKU margin analysis"],
                required_input_data=["products", "sale_items"],
                methodology="Line revenue minus line COGS grouped by SKU.",
                confidence_methodology="Exact itemized product pricing.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        skus = db.execute(
            select(
                Product.name,
                func.sum(SaleItem.line_total).label("rev"),
                func.sum(SaleItem.quantity * Product.unit_cost).label("cogs"),
            )
            .join(SaleItem, Product.id == SaleItem.product_id)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.business_id == biz_id)
            .group_by(Product.name)
            .order_by((func.sum(SaleItem.line_total) - func.sum(SaleItem.quantity * Product.unit_cost)).desc())
            .limit(5)
        ).all()

        sku_profits = []
        for r in skus:
            rev = float(r.rev or 0)
            cogs = float(r.cogs or 0)
            profit = rev - cogs
            sku_profits.append({
                "product": r.name,
                "revenue": round(rev, 2),
                "profit": round(profit, 2),
                "margin_pct": round((profit / rev * 100), 1) if rev else 0.0,
            })

        findings = []
        if sku_profits:
            top_p = sku_profits[0]
            findings.append(f"Most profitable SKU is '{top_p['product']}' generating ${top_p['profit']:,.2f} in gross profit ({top_p['margin_pct']}% margin).")

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={"top_profitable_products": sku_profits},
            findings=findings,
            confidence_score=0.94,
        )


class KPIDecompositionSkill(BaseAnalystSkill):
    """Decomposes top-line revenue into Buyers * Frequency * AOV (DuPont style)."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="kpi_decomposition",
                name="DuPont KPI Decomposition Analyst",
                description="Deconstructs revenue into three constituent levers: Active Buyers × Purchase Frequency × AOV.",
                domain=SkillDomain.COMMERCIAL,
                version="1.0.0",
                activation_conditions=["KPI decomposition", "Why did revenue change?", "Sales formula decomposition"],
                required_input_data=["sales"],
                methodology="Multiplicative equation: Total Revenue = Active Customers × (Orders / Customer) × (Revenue / Order).",
                confidence_methodology="Exact arithmetic identity.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        stats = db.execute(
            select(
                func.count(Sale.id),
                func.count(func.distinct(Sale.customer_id)),
                func.sum(Sale.total_amount),
            ).where(Sale.business_id == biz_id, Sale.status == "completed")
        ).first()

        orders = (stats[0] or 0) if stats else 0
        buyers = (stats[1] or 0) if stats else 0
        revenue = float(stats[2] or 0) if stats else 0.0

        freq = (orders / buyers) if buyers else 0.0
        aov = (revenue / orders) if orders else 0.0

        findings = [
            f"Revenue Equation: {buyers:,} Buyers × {freq:.2f} Orders/Buyer × ${aov:.2f} AOV = ${revenue:,.2f}.",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "buyers": buyers,
                "frequency": round(freq, 2),
                "aov": round(aov, 2),
                "total_revenue": round(revenue, 2),
            },
            calculations=[
                {"formula": "Revenue = Buyers * Frequency * AOV", "result": f"${revenue:,.2f}"},
            ],
            findings=findings,
            confidence_score=1.0,
        )


class CommercialForecastingSkill(BaseAnalystSkill):
    """Projects commercial cash flow and revenue trajectory from recent run-rates."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="commercial_forecasting",
                name="Commercial Run-Rate Forecaster",
                description="Projects monthly and quarterly revenue expectations based on annualized current run-rates.",
                domain=SkillDomain.COMMERCIAL,
                version="1.0.0",
                activation_conditions=["Commercial forecast", "Quarterly run-rate", "Projected sales"],
                required_input_data=["sales"],
                methodology="30-day annualized pace extrapolation.",
                confidence_methodology="Trailing revenue extrapolations.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id
        now = datetime.now(UTC)

        recent_rev = db.execute(
            select(func.sum(Sale.total_amount))
            .where(Sale.business_id == biz_id, Sale.status == "completed", Sale.transaction_date >= now - timedelta(days=30))
        ).scalar() or 0

        r30 = float(recent_rev)
        quarterly_pace = r30 * 3
        annual_pace = r30 * 12

        findings = [
            f"Trailing 30-day revenue: ${r30:,.2f}.",
            f"Annualized commercial run-rate: ${annual_pace:,.2f} (${quarterly_pace:,.2f} per quarter).",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "trailing_30d_rev": round(r30, 2),
                "quarterly_pace": round(quarterly_pace, 2),
                "annual_pace": round(annual_pace, 2),
            },
            findings=findings,
            confidence_score=0.88,
        )
