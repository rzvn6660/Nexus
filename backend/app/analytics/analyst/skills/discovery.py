"""Family A: Data Discovery and Exploration Analyst Skills."""

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
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem


class DataProfilingSkill(BaseAnalystSkill):
    """Profiles business datasets: row counts, distinct values, date boundaries."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="data_profiling",
                name="Data Profiler",
                description="Comprehensive profiling of transactional records, customers, and active SKU catalog.",
                domain=SkillDomain.DISCOVERY,
                version="1.0.0",
                activation_conditions=[
                    "Any query assessing dataset size or coverage",
                    "Initial workspace inspection",
                ],
                required_input_data=["sales", "customers", "products"],
                methodology="Exact SQL aggregate counts and min/max timestamp boundaries grouped by tenant.",
                confidence_methodology="Deterministic exact database counts; 100% confidence on committed state.",
                known_limitations=["Excludes uncommitted external staging records."],
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        total_sales = (
            db.execute(select(func.count(Sale.id)).where(Sale.business_id == biz_id)).scalar() or 0
        )

        total_customers = (
            db.execute(
                select(func.count(Customer.id)).where(Customer.business_id == biz_id)
            ).scalar()
            or 0
        )

        total_products = (
            db.execute(select(func.count(Product.id)).where(Product.business_id == biz_id)).scalar()
            or 0
        )

        date_span = db.execute(
            select(func.min(Sale.transaction_date), func.max(Sale.transaction_date)).where(
                Sale.business_id == biz_id
            )
        ).first()

        min_date, max_date = date_span if date_span else (None, None)

        findings = [
            f"Workspace contains {total_sales:,} sales transactions across {total_customers:,} registered customers.",
            f"Active catalog spans {total_products:,} configured SKUs.",
        ]
        if min_date and max_date:
            findings.append(
                f"Recorded transaction history spans {min_date.date()} to {max_date.date()}."
            )

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "total_sales": total_sales,
                "total_customers": total_customers,
                "total_products": total_products,
                "earliest_transaction": min_date.isoformat() if min_date else None,
                "latest_transaction": max_date.isoformat() if max_date else None,
            },
            calculations=[
                {"metric": "total_transactions", "value": total_sales},
                {"metric": "total_customers", "value": total_customers},
                {"metric": "total_products", "value": total_products},
            ],
            findings=findings,
            confidence_score=1.0,
        )


class DistributionAnalysisSkill(BaseAnalystSkill):
    """Calculates order value distributions: median, quartiles, IQR, standard deviation."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="distribution_analysis",
                name="Order Value Distribution Analyst",
                description="Analyzes transaction value dispersion, median, percentiles (p25, p50, p75, p95), and spread.",
                domain=SkillDomain.DISCOVERY,
                version="1.0.0",
                activation_conditions=["Queries regarding order size, distribution, or dispersion"],
                required_input_data=["sales"],
                methodology="Parametric and non-parametric percentile estimation on total billed order amounts.",
                confidence_methodology="Sample size weighted; higher precision with >100 transactions.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id
        amounts = (
            db.execute(
                select(Sale.total_amount).where(
                    Sale.business_id == biz_id, Sale.status == "completed"
                )
            )
            .scalars()
            .all()
        )

        if not amounts:
            return SkillExecutionResult(
                skill_id=self.skill_id,
                skill_name=self.name,
                domain=self.domain,
                status="INSUFFICIENT_DATA",
                findings=["No completed sales records available to compute distribution."],
                confidence_score=0.0,
            )

        vals = np.array([float(a) for a in amounts])
        p25, p50, p75, p95 = np.percentile(vals, [25, 50, 75, 95])
        iqr = float(p75 - p25)
        mean_val = float(np.mean(vals))
        std_val = float(np.std(vals))

        findings = [
            f"Median order value is ${p50:.2f} with an Interquartile Range (IQR) of ${iqr:.2f}.",
            f"Middle 50% of orders fall between ${p25:.2f} and ${p75:.2f}.",
            f"95th percentile transaction threshold is ${p95:.2f} (mean: ${mean_val:.2f} ± ${std_val:.2f}).",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "p25": round(float(p25), 2),
                "p50_median": round(float(p50), 2),
                "p75": round(float(p75), 2),
                "p95": round(float(p95), 2),
                "mean": round(mean_val, 2),
                "std_dev": round(std_val, 2),
                "sample_size": len(vals),
            },
            calculations=[
                {"formula": "median(total_amount)", "result": round(float(p50), 2)},
                {"formula": "iqr = p75 - p25", "result": round(iqr, 2)},
            ],
            findings=findings,
            confidence_score=0.95 if len(vals) >= 50 else 0.75,
        )


class MissingValueAnalysisSkill(BaseAnalystSkill):
    """Detects null or missing fields in core business entities."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="missing_value_analysis",
                name="Missing Value Analyst",
                description="Scans customer, product, and transaction attributes for null values and completeness ratios.",
                domain=SkillDomain.DISCOVERY,
                version="1.0.0",
                activation_conditions=["Data completeness queries", "Pre-flight analytical audits"],
                required_input_data=["customers", "sales", "products"],
                methodology="SQL IS NULL count checks across critical foreign keys and descriptors.",
                confidence_methodology="Exact relational query verification.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        # Customer null checks
        total_cust = (
            db.execute(
                select(func.count(Customer.id)).where(Customer.business_id == biz_id)
            ).scalar()
            or 0
        )
        missing_phone = (
            db.execute(
                select(func.count(Customer.id)).where(
                    Customer.business_id == biz_id, Customer.phone.is_(None)
                )
            ).scalar()
            or 0
        )
        missing_city = (
            db.execute(
                select(func.count(Customer.id)).where(
                    Customer.business_id == biz_id, (Customer.city == "") | Customer.city.is_(None)
                )
            ).scalar()
            or 0
        )

        # Sales missing customer link
        orphan_sales = (
            db.execute(
                select(func.count(Sale.id)).where(
                    Sale.business_id == biz_id, Sale.customer_id.is_(None)
                )
            ).scalar()
            or 0
        )

        findings: list[str] = []
        if orphan_sales > 0:
            findings.append(
                f"CRITICAL: Found {orphan_sales} sales transactions without customer attribution."
            )
        else:
            findings.append("All sales transactions have valid customer foreign key attributions.")

        phone_pct = (missing_phone / total_cust * 100) if total_cust else 0
        findings.append(
            f"Customer phone completeness: {100 - phone_pct:.1f}% ({missing_phone} records unpopulated)."
        )

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "total_customers": total_cust,
                "missing_phone": missing_phone,
                "missing_city": missing_city,
                "orphan_sales": orphan_sales,
            },
            calculations=[
                {"metric": "orphan_sales_count", "value": orphan_sales},
                {"metric": "phone_missing_pct", "value": round(phone_pct, 1)},
            ],
            findings=findings,
            confidence_score=1.0,
        )


class RelationshipDiscoverySkill(BaseAnalystSkill):
    """Discovers structural ratios: items per order, orders per customer, repeat buyer ratios."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="relationship_discovery",
                name="Entity Relationship Analyst",
                description="Measures relational density: items-per-order, order frequency per buyer, and basket volume.",
                domain=SkillDomain.DISCOVERY,
                version="1.0.0",
                activation_conditions=["Understanding structural customer/order patterns"],
                required_input_data=["sales", "customers", "sale_items"],
                methodology="Relational cross-table aggregation.",
                confidence_methodology="Exact deterministic relational ratios.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        total_sales = (
            db.execute(select(func.count(Sale.id)).where(Sale.business_id == biz_id)).scalar() or 0
        )
        total_items = (
            db.execute(
                select(func.count(SaleItem.id))
                .join(Sale, SaleItem.sale_id == Sale.id)
                .where(Sale.business_id == biz_id)
            ).scalar()
            or 0
        )
        unique_buyers = (
            db.execute(
                select(func.count(func.distinct(Sale.customer_id))).where(
                    Sale.business_id == biz_id
                )
            ).scalar()
            or 0
        )

        items_per_order = (total_items / total_sales) if total_sales else 0.0
        orders_per_buyer = (total_sales / unique_buyers) if unique_buyers else 0.0

        findings = [
            f"Average basket depth is {items_per_order:.2f} line items per order.",
            f"Transacting customers average {orders_per_buyer:.2f} lifetime purchases each.",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "items_per_order": round(items_per_order, 2),
                "orders_per_buyer": round(orders_per_buyer, 2),
                "total_sales": total_sales,
                "unique_buyers": unique_buyers,
            },
            calculations=[
                {"formula": "total_items / total_sales", "result": round(items_per_order, 2)},
                {"formula": "total_sales / unique_buyers", "result": round(orders_per_buyer, 2)},
            ],
            findings=findings,
            confidence_score=0.95,
        )


class DescriptiveStatisticsSkill(BaseAnalystSkill):
    """Calculates summary descriptive statistics for key financial metrics."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="descriptive_statistics",
                name="Descriptive Statistics Analyst",
                description="Generates standard descriptive statistics: mean, median, min, max, sum, and variance.",
                domain=SkillDomain.DISCOVERY,
                version="1.0.0",
                activation_conditions=["Descriptive statistics requests", "Summary overviews"],
                required_input_data=["sales"],
                methodology="SQL aggregates and numpy statistical functions.",
                confidence_methodology="Exact arithmetic computation.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        stats = db.execute(
            select(
                func.count(Sale.id),
                func.sum(Sale.total_amount),
                func.avg(Sale.total_amount),
                func.min(Sale.total_amount),
                func.max(Sale.total_amount),
            ).where(Sale.business_id == biz_id, Sale.status == "completed")
        ).first()

        count, total_sum, avg_val, min_val, max_val = stats if stats else (0, 0, 0, 0, 0)
        total_sum_f = float(total_sum or 0)
        avg_val_f = float(avg_val or 0)
        min_val_f = float(min_val or 0)
        max_val_f = float(max_val or 0)

        findings = [
            f"Cumulative completed revenue: ${total_sum_f:,.2f} across {count:,} orders.",
            f"Average order value (AOV): ${avg_val_f:.2f} (Range: ${min_val_f:.2f} to ${max_val_f:.2f}).",
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={
                "count": count,
                "total_revenue": round(total_sum_f, 2),
                "aov": round(avg_val_f, 2),
                "min_order": round(min_val_f, 2),
                "max_order": round(max_val_f, 2),
            },
            calculations=[
                {"metric": "total_revenue", "value": round(total_sum_f, 2)},
                {"metric": "aov", "value": round(avg_val_f, 2)},
            ],
            findings=findings,
            confidence_score=1.0,
        )


class ExploratoryDataAnalysisSkill(BaseAnalystSkill):
    """Combines summary profiling, order trends, and segment breakdowns."""

    def __init__(self) -> None:
        super().__init__(
            SkillMetadata(
                skill_id="exploratory_data_analysis",
                name="Exploratory Data Analyst (EDA)",
                description="Comprehensive multi-dimensional EDA synthesizing volume, channels, and segment mix.",
                domain=SkillDomain.DISCOVERY,
                version="1.0.0",
                activation_conditions=["General business discovery", "Broad exploratory questions"],
                required_input_data=["sales", "customers"],
                methodology="Multi-group relational aggregation.",
                confidence_methodology="Deterministic SQL segmentation.",
            )
        )

    def _execute(self, db: Session, context: ExecutionContext) -> SkillExecutionResult:
        biz_id = context.business_id

        # Segments breakdown
        segments = db.execute(
            select(Customer.customer_segment, func.count(Customer.id))
            .where(Customer.business_id == biz_id)
            .group_by(Customer.customer_segment)
        ).all()

        segment_breakdown = {seg: count for seg, count in segments}
        findings = [
            f"Customer distribution across segments: {', '.join([f'{k}: {v}' for k, v in segment_breakdown.items()])}."
        ]

        return SkillExecutionResult(
            skill_id=self.skill_id,
            skill_name=self.name,
            domain=self.domain,
            status="SUCCESS",
            data={"segment_breakdown": segment_breakdown},
            calculations=[{"metric": "segments_count", "value": len(segment_breakdown)}],
            findings=findings,
            confidence_score=0.95,
        )
