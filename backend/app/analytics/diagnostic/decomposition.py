"""Deterministic Price / Volume / Mix (PVM) revenue variance decomposition."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.product import Product
from app.analytics.core.context import AnalysisContext
from app.analytics.core.exceptions import InvalidContextError, DecompositionError
from app.analytics.core.models import PriceVolumeMixDecomposition


class PriceVolumeMixAnalyzer:
    """Decomposes revenue variance into Volume Effect, Price Effect, and Mix Effect."""

    @classmethod
    def decompose(
        cls, session: Session, context: AnalysisContext
    ) -> PriceVolumeMixDecomposition:
        """
        Decompose ΔRevenue into:
        1. Volume Effect: (Total_Units_Curr - Total_Units_Prior) * Prior_Portfolio_Avg_Price
        2. Price Effect: Sum_i [ Units_Curr_i * (Avg_Price_Curr_i - Avg_Price_Prior_i) ]
        3. Mix Effect: Total_Variance - (Volume_Effect + Price_Effect)
        """
        if not context.has_comparison:
            raise InvalidContextError(
                "Price/Volume/Mix decomposition requires comparison_date_from and comparison_date_to."
            )

        # Helper to query product level quantity and revenue
        def _get_product_metrics(d_from, d_to) -> Dict[int, Dict[str, Any]]:
            clauses = [
                Sale.status.in_(context.statuses if context.statuses else ["completed", "shipped"])
            ]
            if d_from:
                clauses.append(Sale.transaction_date >= d_from)
            if d_to:
                clauses.append(Sale.transaction_date <= d_to)

            stmt = (
                select(
                    Product.id.label("product_id"),
                    Product.sku.label("sku"),
                    Product.selling_price.label("catalog_price"),
                    func.coalesce(func.sum(SaleItem.quantity), 0).label("units"),
                    func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("revenue"),
                )
                .join(SaleItem, Product.id == SaleItem.product_id)
                .join(Sale, SaleItem.sale_id == Sale.id)
                .where(and_(*clauses))
                .group_by(Product.id)
            )

            res: Dict[int, Dict[str, Any]] = {}
            for r in session.execute(stmt).all():
                q = int(r.units)
                rev = Decimal(str(r.revenue)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                cat_p = Decimal(str(r.catalog_price))
                avg_p = (
                    (rev / Decimal(q)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    if q > 0
                    else cat_p
                )
                res[r.product_id] = {
                    "sku": r.sku,
                    "units": q,
                    "revenue": rev,
                    "avg_price": avg_p,
                    "catalog_price": cat_p,
                }
            return res

        curr_p = _get_product_metrics(context.date_from, context.date_to)
        prior_p = _get_product_metrics(context.comparison_date_from, context.comparison_date_to)

        tot_units_curr = sum((v["units"] for v in curr_p.values()), 0)
        tot_units_prior = sum((v["units"] for v in prior_p.values()), 0)

        tot_rev_curr = sum((v["revenue"] for v in curr_p.values()), Decimal("0.00"))
        tot_rev_prior = sum((v["revenue"] for v in prior_p.values()), Decimal("0.00"))
        total_var = tot_rev_curr - tot_rev_prior

        if tot_units_prior == 0 or tot_units_curr == 0:
            return PriceVolumeMixDecomposition(
                prior_revenue=tot_rev_prior,
                current_revenue=tot_rev_curr,
                total_variance=total_var,
                volume_effect=total_var,
                price_effect=Decimal("0.00"),
                mix_effect=Decimal("0.00"),
                volume_effect_pct=100.0 if total_var != 0 else 0.0,
                price_effect_pct=0.0,
                mix_effect_pct=0.0,
                reconciled=True,
                methodology="Baseline or current period had zero unit volume. All variance assigned to Volume Effect.",
                limitations=[
                    "Cannot compute independent price or mix effects when one interval has zero volume."
                ],
            )

        prior_portfolio_avg_price = tot_rev_prior / Decimal(tot_units_prior)

        # 1. Volume Effect: (Q1 - Q0) * P0
        units_diff = Decimal(tot_units_curr - tot_units_prior)
        volume_effect = (units_diff * prior_portfolio_avg_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # 2. Price Effect: sum_i [ Q1_i * (P1_i - P0_i) ]
        price_effect = Decimal("0.00")
        for pid, c_data in curr_p.items():
            q1 = Decimal(c_data["units"])
            p1 = c_data["avg_price"]
            # If product sold in prior period, use prior avg price; otherwise prior catalog price
            if pid in prior_p:
                p0 = prior_p[pid]["avg_price"]
            else:
                p0 = c_data["catalog_price"]
            price_effect += q1 * (p1 - p0)

        price_effect = price_effect.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # 3. Mix Effect: Total_Variance - (Volume_Effect + Price_Effect)
        mix_effect = (total_var - volume_effect - price_effect).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        vol_pct = (
            round(float((volume_effect / abs(total_var)) * Decimal("100.0")), 2)
            if total_var != 0
            else 0.0
        )
        price_pct = (
            round(float((price_effect / abs(total_var)) * Decimal("100.0")), 2)
            if total_var != 0
            else 0.0
        )
        mix_pct = (
            round(float((mix_effect / abs(total_var)) * Decimal("100.0")), 2)
            if total_var != 0
            else 0.0
        )

        reconciled = (volume_effect + price_effect + mix_effect) == total_var

        return PriceVolumeMixDecomposition(
            prior_revenue=tot_rev_prior,
            current_revenue=tot_rev_curr,
            total_variance=total_var,
            volume_effect=volume_effect,
            price_effect=price_effect,
            mix_effect=mix_effect,
            volume_effect_pct=vol_pct,
            price_effect_pct=price_pct,
            mix_effect_pct=mix_pct,
            reconciled=reconciled,
            methodology=(
                "Decomposed revenue variance into: "
                "1. Volume Effect = (Q1 - Q0) * P0_portfolio_avg; "
                "2. Price Effect = sum_i [ Q1_i * (P1_i - P0_i) ]; "
                "3. Mix Effect = Total_Variance - (Volume + Price). "
                "Mathematically guaranteed to reconcile 100% with Total Variance."
            ),
            limitations=[
                "For newly introduced products without prior sales, prior catalog price is used as baseline.",
                "Mix effect reflects portfolio shifts between higher and lower unit price categories.",
            ],
        )
