"""Deterministic diagnostic variance analysis dissecting metric movements across dimensions."""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.analytics.core.context import AnalysisContext
from app.analytics.core.types import TrendDirection
from app.analytics.core.exceptions import InvalidContextError
from app.analytics.core.models import (
    VarianceContributor,
    VarianceAnalysisResult,
)


class VarianceDiagnosticAnalyzer:
    """Diagnoses drivers of metric change between two periods without asserting causality."""

    @classmethod
    def analyze_revenue_variance(
        cls,
        session: Session,
        context: AnalysisContext,
        dimension: str = "product",  # 'product', 'category', or 'customer_segment'
        top_n: int = 5,
    ) -> VarianceAnalysisResult:
        """
        Dissect revenue change between current and baseline comparison period
        into top positive and negative contributing entities.
        """
        if not context.has_comparison:
            raise InvalidContextError(
                "Variance analysis requires comparison_date_from and comparison_date_to."
            )

        # Helper to query revenue by dimension
        def _get_dim_revenue(d_from, d_to) -> Dict[str, Dict[str, Any]]:
            clauses = [
                Sale.status.in_(context.statuses if context.statuses else ["completed", "shipped"])
            ]
            if d_from:
                clauses.append(Sale.transaction_date >= d_from)
            if d_to:
                clauses.append(Sale.transaction_date <= d_to)

            dim_key = dimension.lower()
            if dim_key == "category":
                stmt = (
                    select(
                        Product.category.label("entity_id"),
                        Product.category.label("entity_name"),
                        func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("rev"),
                    )
                    .join(SaleItem, Product.id == SaleItem.product_id)
                    .join(Sale, SaleItem.sale_id == Sale.id)
                    .where(and_(*clauses))
                    .group_by(Product.category)
                )
            elif dim_key in ("customer_segment", "segment"):
                stmt = (
                    select(
                        Customer.customer_segment.label("entity_id"),
                        Customer.customer_segment.label("entity_name"),
                        func.coalesce(
                            func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")
                        ).label("rev"),
                    )
                    .join(Sale, Customer.id == Sale.customer_id)
                    .where(and_(*clauses))
                    .group_by(Customer.customer_segment)
                )
            else:  # default 'product'
                stmt = (
                    select(
                        Product.sku.label("entity_id"),
                        Product.name.label("entity_name"),
                        func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("rev"),
                    )
                    .join(SaleItem, Product.id == SaleItem.product_id)
                    .join(Sale, SaleItem.sale_id == Sale.id)
                    .where(and_(*clauses))
                    .group_by(Product.sku, Product.name)
                )

            res: Dict[str, Dict[str, Any]] = {}
            for r in session.execute(stmt).all():
                res[r.entity_id] = {
                    "name": r.entity_name,
                    "revenue": Decimal(str(r.rev)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                }
            return res

        curr_data = _get_dim_revenue(context.date_from, context.date_to)
        prior_data = _get_dim_revenue(context.comparison_date_from, context.comparison_date_to)

        all_keys = set(curr_data.keys()).union(prior_data.keys())

        total_curr = sum((v["revenue"] for v in curr_data.values()), Decimal("0.00"))
        total_prior = sum((v["revenue"] for v in prior_data.values()), Decimal("0.00"))
        total_var = total_curr - total_prior

        pct_change: Optional[float] = None
        if total_prior > Decimal("0.00"):
            pct_change = round(float((total_var / total_prior) * Decimal("100.0")), 2)

        if total_var > 0:
            overall_direction = TrendDirection.INCREASE
        elif total_var < 0:
            overall_direction = TrendDirection.DECREASE
        else:
            overall_direction = TrendDirection.UNCHANGED

        contributors: List[VarianceContributor] = []
        for key in all_keys:
            c_val = curr_data.get(key, {}).get("revenue", Decimal("0.00"))
            p_val = prior_data.get(key, {}).get("revenue", Decimal("0.00"))
            name = (
                curr_data.get(key, {}).get("name")
                or prior_data.get(key, {}).get("name")
                or key
            )
            diff = c_val - p_val

            contrib_pct = (
                round(float((diff / abs(total_var)) * Decimal("100.0")), 2)
                if total_var != 0
                else 0.0
            )

            if diff > 0:
                dir_ = TrendDirection.INCREASE
            elif diff < 0:
                dir_ = TrendDirection.DECREASE
            else:
                dir_ = TrendDirection.UNCHANGED

            contributors.append(
                VarianceContributor(
                    entity_id=key,
                    entity_name=name,
                    prior_value=p_val,
                    current_value=c_val,
                    absolute_change=diff,
                    contribution_to_change_pct=contrib_pct,
                    direction=dir_,
                )
            )

        # Sort positive contributors (highest positive change first)
        pos = [c for c in contributors if c.absolute_change > 0]
        pos.sort(key=lambda x: x.absolute_change, reverse=True)

        # Sort negative contributors (most negative change first)
        neg = [c for c in contributors if c.absolute_change < 0]
        neg.sort(key=lambda x: x.absolute_change, reverse=False)

        return VarianceAnalysisResult(
            metric="revenue",
            prior_period_value=total_prior,
            current_period_value=total_curr,
            total_variance=total_var,
            percentage_change=pct_change,
            direction=overall_direction,
            dimension=dimension,
            top_positive_contributors=pos[:top_n],
            top_negative_contributors=neg[:top_n],
        )
