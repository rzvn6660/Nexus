"""Family C: Customer and Revenue Analytics Analyst Skills."""

import itertools
from collections import Counter
from datetime import UTC, date, datetime

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


class RFMSegmentationSkill(BaseAnalystSkill):
    """Calculates Recency, Frequency, and Monetary (RFM) customer segment clusters."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="rfm_segmentation",
                name="RFM Segmentation Analyst",
                description="Scores customers across Recency, Frequency, and Monetary tiers to identify Champions, At-Risk, and Hibernating buyers.",
                domain=SkillDomain.CUSTOMER_REVENUE,
                version="1.0.0",
                activation_conditions=[
                    "Customer segmentation",
                    "RFM analysis",
                    "VIP vs at-risk classification",
                ],
                required_input_data=["sales", "customers"],
                methodology="Quintile or rule-based RFM scoring calibrated against tenant transaction recency and volume.",
                confidence_methodology="Behavioral clustering based on deterministic historical orders.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id
        now = datetime.now(UTC)

        customer_sales = db.execute(
            select(
                Sale.customer_id,
                func.count(Sale.id).label("freq"),
                func.sum(Sale.total_amount).label("monetary"),
                func.max(Sale.transaction_date).label("last_date"),
            )
            .where(Sale.business_id == biz_id, Sale.status == "completed")
            .group_by(Sale.customer_id)
        ).all()

        if not customer_sales:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="INSUFFICIENT_DATA",
                findings=["No completed customer orders available for RFM segmentation."],
                confidence_score=0.0,
            )

        segments = Counter()
        for c in customer_sales:
            freq = c.freq
            monetary = float(c.monetary or 0)
            last_dt = c.last_date
            if last_dt is not None:
                if isinstance(last_dt, str):
                    try:
                        last_dt = datetime.fromisoformat(last_dt)
                    except Exception:
                        pass
                if isinstance(last_dt, datetime):
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=UTC)
                    recency_days = (now - last_dt).days
                elif isinstance(last_dt, date):
                    recency_days = (now.date() - last_dt).days
                else:
                    recency_days = 999
            else:
                recency_days = 999

            if freq >= 4 and recency_days <= 45 and monetary >= 500:
                segments["Champions"] += 1
            elif freq >= 2 and recency_days <= 60:
                segments["Loyal Customers"] += 1
            elif freq >= 2 and recency_days > 90:
                segments["At Risk"] += 1
            elif freq == 1 and recency_days <= 30:
                segments["Promising New"] += 1
            elif recency_days > 180:
                segments["Hibernating"] += 1
            else:
                segments["Standard Active"] += 1

        total_analyzed = len(customer_sales)
        findings = [
            f"Segmented {total_analyzed} active transacting buyers into behavioral clusters.",
            f"Top clusters: {', '.join([f'{k}: {v} ({v / total_analyzed * 100:.1f}%)' for k, v in segments.most_common(3)])}.",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "total_customers_analyzed": total_analyzed,
                "segments": dict(segments),
            },
            calculations=[
                {"metric": "champions_count", "value": segments.get("Champions", 0)},
                {"metric": "at_risk_count", "value": segments.get("At Risk", 0)},
            ],
            findings=findings,
            confidence_score=0.92,
        )


class CustomerCohortSkill(BaseAnalystSkill):
    """Analyzes customer acquisition cohorts and retention decay curves."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="customer_cohort_analysis",
                name="Customer Cohort Analyst",
                description="Tracks monthly customer acquisition cohorts and their follow-on purchase retention rates over time.",
                domain=SkillDomain.CUSTOMER_REVENUE,
                version="1.0.0",
                activation_conditions=[
                    "Cohort analysis",
                    "Customer retention decay",
                    "Acquisition vintage inquiries",
                ],
                required_input_data=["customers", "sales"],
                methodology="Monthly acquisition cohort assignment with relative monthly repeat order matrices.",
                confidence_methodology="Exact cohort accounting based on first recorded transaction dates.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        # First order date per customer
        first_orders = db.execute(
            select(
                Sale.customer_id,
                func.min(Sale.transaction_date).label("first_date"),
                func.count(Sale.id).label("total_orders"),
            )
            .where(Sale.business_id == biz_id, Sale.status == "completed")
            .group_by(Sale.customer_id)
        ).all()

        if not first_orders:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="INSUFFICIENT_DATA",
                findings=["No completed orders found for cohort retention analysis."],
                confidence_score=0.0,
            )

        cohort_sizes = Counter()
        cohort_repeaters = Counter()

        for fo in first_orders:
            if fo.first_date:
                cohort_key = fo.first_date.strftime("%Y-%m")
                cohort_sizes[cohort_key] += 1
                if fo.total_orders > 1:
                    cohort_repeaters[cohort_key] += 1

        top_cohorts = sorted(cohort_sizes.keys())[-4:]
        findings: list[str] = []
        for c in top_cohorts:
            size = cohort_sizes[c]
            repeats = cohort_repeaters[c]
            pct = (repeats / size * 100) if size else 0
            findings.append(
                f"Cohort {c}: {size} acquired buyers, {pct:.1f}% returned for multiple purchases."
            )

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "cohort_sizes": dict(cohort_sizes),
                "cohort_repeaters": dict(cohort_repeaters),
            },
            findings=findings,
            confidence_score=0.90,
        )


class RepeatPurchaseSkill(BaseAnalystSkill):
    """Measures overall repeat purchase rate and repeat buyer revenue contribution."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="repeat_purchase_analysis",
                name="Repeat Purchase Rate Analyst",
                description="Quantifies repeat buyer percentage, repeat order volume, and repeat revenue share.",
                domain=SkillDomain.CUSTOMER_REVENUE,
                version="1.0.0",
                activation_conditions=[
                    "Repeat buyer inquiries",
                    "Loyalty analysis",
                    "Repurchase behavior",
                ],
                required_input_data=["sales"],
                methodology="Customer transaction count distribution (1 order vs >1 orders) and revenue decomposition.",
                confidence_methodology="Exact relational order counting.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        cust_orders = db.execute(
            select(
                Sale.customer_id,
                func.count(Sale.id).label("order_count"),
                func.sum(Sale.total_amount).label("total_spent"),
            )
            .where(Sale.business_id == biz_id, Sale.status == "completed")
            .group_by(Sale.customer_id)
        ).all()

        if not cust_orders:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="INSUFFICIENT_DATA",
                findings=["No customer purchase data available."],
                confidence_score=0.0,
            )

        total_buyers = len(cust_orders)
        repeat_buyers = sum(1 for c in cust_orders if c.order_count > 1)
        repeat_rate = (repeat_buyers / total_buyers * 100) if total_buyers else 0.0

        total_rev = sum(float(c.total_spent or 0) for c in cust_orders)
        repeat_rev = sum(float(c.total_spent or 0) for c in cust_orders if c.order_count > 1)
        repeat_rev_share = (repeat_rev / total_rev * 100) if total_rev else 0.0

        findings = [
            f"Repeat buyer rate is {repeat_rate:.1f}% ({repeat_buyers} of {total_buyers} total buyers).",
            f"Repeat buyers generate ${repeat_rev:,.2f} ({repeat_rev_share:.1f}% of total business revenue).",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "total_buyers": total_buyers,
                "repeat_buyers": repeat_buyers,
                "repeat_purchase_rate": round(repeat_rate, 2),
                "repeat_revenue_share": round(repeat_rev_share, 2),
                "total_revenue": round(total_rev, 2),
                "repeat_revenue": round(repeat_rev, 2),
            },
            calculations=[
                {"formula": "repeat_buyers / total_buyers", "result": f"{repeat_rate:.1f}%"},
                {"formula": "repeat_rev / total_rev", "result": f"{repeat_rev_share:.1f}%"},
            ],
            findings=findings,
            confidence_score=0.98,
        )


class CustomerLTVMetricSkill(BaseAnalystSkill):
    """Calculates Historical Customer Lifetime Value (LTV) and average spend per customer."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="customer_lifetime_value",
                name="Customer LTV Analyst",
                description="Calculates average historical LTV, top-tier LTV benchmarks, and revenue per transacting account.",
                domain=SkillDomain.CUSTOMER_REVENUE,
                version="1.0.0",
                activation_conditions=[
                    "Customer lifetime value",
                    "LTV inquiries",
                    "Average customer value",
                ],
                required_input_data=["sales", "customers"],
                methodology="Cumulative customer revenue divided by active customer base, with percentile distribution.",
                confidence_methodology="Exact arithmetic revenue allocation.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        ltvs = (
            db.execute(
                select(func.sum(Sale.total_amount))
                .where(Sale.business_id == biz_id, Sale.status == "completed")
                .group_by(Sale.customer_id)
            )
            .scalars()
            .all()
        )

        if not ltvs:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="INSUFFICIENT_DATA",
                findings=["No customer revenue recorded for LTV calculation."],
                confidence_score=0.0,
            )

        vals = np.array([float(x) for x in ltvs])
        mean_ltv = float(np.mean(vals))
        median_ltv = float(np.median(vals))
        p90_ltv = float(np.percentile(vals, 90))

        findings = [
            f"Mean historical Customer Lifetime Value (LTV) is ${mean_ltv:.2f} (Median: ${median_ltv:.2f}).",
            f"Top 10% of customers have achieved an LTV exceeding ${p90_ltv:.2f}.",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "mean_ltv": round(mean_ltv, 2),
                "median_ltv": round(median_ltv, 2),
                "p90_ltv": round(p90_ltv, 2),
                "customer_count": len(vals),
            },
            calculations=[
                {
                    "formula": "sum(customer_revenue) / count(customers)",
                    "result": round(mean_ltv, 2),
                },
            ],
            findings=findings,
            confidence_score=0.95,
        )


class PurchaseCadenceSkill(BaseAnalystSkill):
    """Measures inter-purchase interval distribution and identifies customer cadence delays."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="purchase_cadence_analysis",
                name="Purchase Cadence Analyst",
                description="Calculates individual inter-purchase interval days and identifies customers overdue relative to their personalized rhythm.",
                domain=SkillDomain.CUSTOMER_REVENUE,
                version="1.0.0",
                activation_conditions=[
                    "Purchase cadence",
                    "Buying frequency",
                    "Inter-purchase intervals",
                ],
                required_input_data=["sales"],
                methodology="Consecutive order date delta calculations per multi-order customer.",
                confidence_methodology="Calibrated against observed customer-specific inter-order intervals.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        # Query sales ordered by customer and transaction date
        sales = db.execute(
            select(Sale.customer_id, Sale.transaction_date)
            .where(Sale.business_id == biz_id, Sale.status == "completed")
            .order_by(Sale.customer_id, Sale.transaction_date)
        ).all()

        intervals: list[int] = []
        cust_dates: dict[int, list[date]] = {}
        for c_id, tx_date in sales:
            if c_id not in cust_dates:
                cust_dates[c_id] = []
            cust_dates[c_id].append(tx_date)

        for c_id, dates in cust_dates.items():
            if len(dates) > 1:
                for i in range(1, len(dates)):
                    delta_days = (dates[i] - dates[i - 1]).days
                    if delta_days >= 0:
                        intervals.append(delta_days)

        if not intervals:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="INSUFFICIENT_DATA",
                findings=["Insufficient multi-order history to compute inter-purchase cadence."],
                confidence_score=0.0,
            )

        mean_cadence = float(np.mean(intervals))
        median_cadence = float(np.median(intervals))

        findings = [
            f"Average inter-purchase interval across repeat buyers is {mean_cadence:.1f} days (Median: {median_cadence:.1f} days).",
            f"Cadence baseline established from {len(intervals)} repeat order cycles.",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "mean_cadence_days": round(mean_cadence, 1),
                "median_cadence_days": round(median_cadence, 1),
                "repeat_cycles_evaluated": len(intervals),
            },
            calculations=[
                {
                    "formula": "mean(order_date[i] - order_date[i-1])",
                    "result": f"{mean_cadence:.1f} days",
                },
            ],
            findings=findings,
            confidence_score=0.92,
        )


class ProductAffinitySkill(BaseAnalystSkill):
    """Identifies co-purchased product pairs and cross-sell affinities."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="product_affinity_basket",
                name="Product Affinity & Basket Analyst",
                description="Analyzes market basket co-occurrence to uncover high-affinity product pairs frequently purchased together.",
                domain=SkillDomain.CUSTOMER_REVENUE,
                version="1.0.0",
                activation_conditions=[
                    "Product affinity",
                    "Basket analysis",
                    "Cross-sell opportunities",
                ],
                required_input_data=["sales", "sale_items", "products"],
                methodology="Market basket co-occurrence matrix on multi-item orders.",
                confidence_methodology="Deterministic combinatorial transaction frequency.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        # Query multi-item orders
        items = db.execute(
            select(SaleItem.sale_id, Product.name)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .join(Product, SaleItem.product_id == Product.id)
            .where(Sale.business_id == biz_id)
        ).all()

        order_baskets: dict[int, set[str]] = {}
        for s_id, prod_name in items:
            if s_id not in order_baskets:
                order_baskets[s_id] = set()
            order_baskets[s_id].add(prod_name)

        pair_counts: Counter[tuple[str, ...]] = Counter()
        for basket in order_baskets.values():
            if len(basket) >= 2:
                for pair in itertools.combinations(sorted(basket), 2):
                    pair_counts[pair] += 1

        top_pairs = pair_counts.most_common(3)
        findings: list[str] = []
        if top_pairs:
            findings.append("Top co-purchased product pairs discovered:")
            for (p1, p2), cnt in top_pairs:
                findings.append(f"• '{p1}' + '{p2}': Bought together {cnt} times.")
        else:
            findings.append(
                "Single-item baskets predominate; no significant cross-product pairing observed."
            )

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "top_pairs": [
                    {"product_a": p1, "product_b": p2, "co_occurrences": cnt}
                    for (p1, p2), cnt in top_pairs
                ],
                "multi_item_orders_count": sum(1 for b in order_baskets.values() if len(b) >= 2),
            },
            findings=findings,
            confidence_score=0.88,
        )


class CustomerConcentrationSkill(BaseAnalystSkill):
    """Evaluates revenue concentration risk and Pareto 80/20 customer distribution."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="customer_concentration",
                name="Customer Concentration & Pareto Analyst",
                description="Assesses business reliance on top accounts by calculating top-decile revenue share and Pareto 80/20 ratio.",
                domain=SkillDomain.CUSTOMER_REVENUE,
                version="1.0.0",
                activation_conditions=[
                    "Concentration risk",
                    "Pareto analysis",
                    "Top customer revenue share",
                ],
                required_input_data=["sales"],
                methodology="Cumulative customer revenue Lorenz curve and top 10% / top 20% contribution shares.",
                confidence_methodology="Exact arithmetic revenue distribution.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        cust_rev = (
            db.execute(
                select(func.sum(Sale.total_amount))
                .where(Sale.business_id == biz_id, Sale.status == "completed")
                .group_by(Sale.customer_id)
                .order_by(func.sum(Sale.total_amount).desc())
            )
            .scalars()
            .all()
        )

        if not cust_rev:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="INSUFFICIENT_DATA",
                findings=["No customer revenue recorded for concentration analysis."],
                confidence_score=0.0,
            )

        vals = [float(x) for x in cust_rev]
        total_rev = sum(vals)
        total_cust = len(vals)

        top_10_pct_count = max(1, int(np.ceil(total_cust * 0.10)))
        top_10_pct_rev = sum(vals[:top_10_pct_count])
        top_10_share = (top_10_pct_rev / total_rev * 100) if total_rev else 0.0

        top_20_pct_count = max(1, int(np.ceil(total_cust * 0.20)))
        top_20_pct_rev = sum(vals[:top_20_pct_count])
        top_20_share = (top_20_pct_rev / total_rev * 100) if total_rev else 0.0

        findings = [
            f"Top 10% of customers ({top_10_pct_count} accounts) generate {top_10_share:.1f}% of total business revenue.",
            f"Top 20% of customers account for {top_20_share:.1f}% of revenue (Pareto ratio benchmark: 80%).",
        ]
        if top_10_share > 50:
            findings.append(
                "HIGH CONCENTRATION RISK: Business is heavily dependent on a narrow group of top buyers."
            )

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "top_10_pct_share": round(top_10_share, 2),
                "top_20_pct_share": round(top_20_share, 2),
                "top_10_account_count": top_10_pct_count,
                "total_active_accounts": total_cust,
            },
            calculations=[
                {"formula": "top_10_revenue / total_revenue", "result": f"{top_10_share:.1f}%"},
                {"formula": "top_20_revenue / total_revenue", "result": f"{top_20_share:.1f}%"},
            ],
            findings=findings,
            confidence_score=0.96,
        )
