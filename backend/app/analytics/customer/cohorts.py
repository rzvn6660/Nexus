"""Deterministic customer cohort retention and spend analytics."""

from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.sale import Sale
from app.analytics.core.context import AnalysisContext
from app.analytics.core.models import CohortCell, CohortRow


class CohortAnalysisResult(BaseModel):
    """Customer cohort retention scorecard."""
    cohort_dimension: str = Field(
        default="acquisition_month",
        description="Dimension used to define cohorts (e.g. 'acquisition_month')"
    )
    total_cohorts: int
    max_periods: int
    cohorts: List[CohortRow]
    methodology: str
    limitations: List[str]


class CustomerCohortAnalyzer:
    """Calculates customer cohort retention and spend decay over time."""

    @classmethod
    def evaluate(
        cls,
        session: Session,
        context: Optional[AnalysisContext] = None,
        max_period_offset: int = 12,
    ) -> CohortAnalysisResult:
        """
        Group customers into monthly acquisition cohorts and track subsequent order activity.
        
        Cohort definition: Customer.acquisition_date truncated to YYYY-MM.
        Offset: Number of calendar months elapsed between acquisition and transaction date.
        """
        # 1. Fetch customers and their acquisition month
        cust_stmt = select(
            Customer.id.label("customer_id"),
            Customer.acquisition_date.label("acq_date"),
        )
        if context and context.customer_segments:
            cust_stmt = cust_stmt.where(Customer.customer_segment.in_(context.customer_segments))

        cust_rows = session.execute(cust_stmt).all()
        if not cust_rows:
            return CohortAnalysisResult(
                cohort_dimension="acquisition_month",
                total_cohorts=0,
                max_periods=0,
                cohorts=[],
                methodology="Monthly acquisition cohorts tracking transaction activity offsets",
                limitations=["No customer records found."],
            )

        customer_cohort_map: Dict[int, str] = {}
        cohort_sizes: Dict[str, int] = {}
        for r in cust_rows:
            acq: date = r.acq_date
            cohort_key = f"{acq.year:04d}-{acq.month:02d}"
            customer_cohort_map[r.customer_id] = cohort_key
            cohort_sizes[cohort_key] = cohort_sizes.get(cohort_key, 0) + 1

        # 2. Fetch sales with transaction date
        sales_stmt = select(
            Sale.customer_id.label("customer_id"),
            Sale.transaction_date.label("tx_date"),
            (Sale.subtotal - Sale.discount_amount).label("net_revenue"),
        ).where(Sale.status.in_(["completed", "shipped"]))

        if context and context.date_from:
            sales_stmt = sales_stmt.where(Sale.transaction_date >= context.date_from)
        if context and context.date_to:
            sales_stmt = sales_stmt.where(Sale.transaction_date <= context.date_to)

        sales_rows = session.execute(sales_stmt).all()

        # 3. Aggregate activity per (cohort, period_offset)
        # Store distinct customers and revenue
        activity: Dict[str, Dict[int, Dict[str, Any]]] = {}

        for r in sales_rows:
            cid = r.customer_id
            if cid not in customer_cohort_map:
                continue
            cohort_key = customer_cohort_map[cid]
            acq_year, acq_month = map(int, cohort_key.split("-"))

            tx: datetime = r.tx_date
            offset = (tx.year - acq_year) * 12 + (tx.month - acq_month)
            if offset < 0 or offset > max_period_offset:
                continue

            if cohort_key not in activity:
                activity[cohort_key] = {}
            if offset not in activity[cohort_key]:
                activity[cohort_key][offset] = {
                    "customers": set(),
                    "total_spend": Decimal("0.00"),
                }

            activity[cohort_key][offset]["customers"].add(cid)
            spend = Decimal(str(r.net_revenue))
            activity[cohort_key][offset]["total_spend"] += spend

        # 4. Build output rows sorted chronologically
        sorted_cohorts = sorted(cohort_sizes.keys())
        cohort_rows: List[CohortRow] = []

        for cohort_key in sorted_cohorts:
            size = cohort_sizes[cohort_key]
            cells: List[CohortCell] = []

            for offset in range(max_period_offset + 1):
                cohort_act = activity.get(cohort_key, {}).get(offset)
                if cohort_act:
                    active_cnt = len(cohort_act["customers"])
                    tot_spend = cohort_act["total_spend"].quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    ret_rate = round((active_cnt / size) * 100.0, 2)
                    avg_spend = (
                        (tot_spend / active_cnt).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        if active_cnt > 0
                        else Decimal("0.00")
                    )
                else:
                    active_cnt = 0
                    tot_spend = Decimal("0.00")
                    ret_rate = 0.0
                    avg_spend = Decimal("0.00")

                cells.append(
                    CohortCell(
                        period_index=offset,
                        period_label=f"M+{offset}",
                        active_customers=active_cnt,
                        retention_rate=ret_rate,
                        total_spend=tot_spend,
                        average_spend_per_active=avg_spend,
                    )
                )

            cohort_rows.append(
                CohortRow(
                    cohort_period=cohort_key,
                    cohort_size=size,
                    periods=cells,
                )
            )

        return CohortAnalysisResult(
            cohort_dimension="acquisition_month",
            total_cohorts=len(cohort_rows),
            max_periods=max_period_offset,
            cohorts=cohort_rows,
            methodology=(
                "Grouped customers by acquisition month (Customer.acquisition_date). "
                "Evaluated unique customer order participation and net spend for each month offset M+0, M+1, etc."
            ),
            limitations=[
                "Deterministic historical retention only; does not forecast future cohort churn.",
                "Offset M+0 represents purchases made in the same calendar month as customer acquisition.",
            ],
        )
