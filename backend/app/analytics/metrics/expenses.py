"""Deterministic expense analytics and category overhead breakdown."""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.expense import Expense
from app.analytics.core.context import AnalysisContext
from app.analytics.core.models import (
    BreakdownItem,
    BreakdownResult,
    ComparisonResult,
)
from app.analytics.metrics.financial import calculate_comparison


class ExpenseAnalysisResult(BaseModel):
    """Overall operational expenditure scorecard."""
    total_expenses: Decimal
    recurring_expenses: Decimal
    variable_expenses: Decimal
    recurring_share_pct: float
    category_breakdown: BreakdownResult
    comparison: Optional[ComparisonResult] = None


class ExpenseAnalyticsCalculator:
    """Calculates operational expense metrics and categorical overhead allocations."""

    @classmethod
    def evaluate(
        cls, session: Session, context: AnalysisContext
    ) -> ExpenseAnalysisResult:
        """
        Evaluate operating expenses for primary period and optional baseline comparison.
        """
        # Primary period
        clauses = []
        if context.date_from:
            clauses.append(Expense.expense_date >= context.date_from.date())
        if context.date_to:
            clauses.append(Expense.expense_date <= context.date_to.date())

        stmt = select(
            Expense.category.label("category"),
            Expense.recurring.label("recurring"),
            func.coalesce(func.sum(Expense.amount), Decimal("0.00")).label("amount"),
            func.count(Expense.id).label("count"),
        ).group_by(Expense.category, Expense.recurring)

        if clauses:
            stmt = stmt.where(and_(*clauses))

        rows = session.execute(stmt).all()

        total = Decimal("0.00")
        recurring = Decimal("0.00")
        variable = Decimal("0.00")
        cat_map: Dict[str, Dict[str, Any]] = {}

        for r in rows:
            amt = Decimal(str(r.amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            cnt = int(r.count)
            is_rec = bool(r.recurring)

            total += amt
            if is_rec:
                recurring += amt
            else:
                variable += amt

            cat = r.category
            if cat not in cat_map:
                cat_map[cat] = {"amount": Decimal("0.00"), "count": 0}
            cat_map[cat]["amount"] += amt
            cat_map[cat]["count"] += cnt

        rec_share = round(float((recurring / total) * Decimal("100.0")), 2) if total > 0 else 0.0

        items: List[BreakdownItem] = []
        for cat, data in cat_map.items():
            amt = data["amount"]
            pct = round(float((amt / total) * Decimal("100.0")), 2) if total > 0 else 0.0
            items.append(
                BreakdownItem(
                    key=cat,
                    label=cat,
                    value=amt,
                    formatted_value=f"${amt:,.2f}",
                    percentage_of_total=pct,
                    count=data["count"],
                )
            )

        items.sort(key=lambda x: x.value, reverse=True)
        cat_breakdown = BreakdownResult(
            dimension="category",
            metric="operating_expenses",
            total_value=total,
            items=items,
        )

        comp: Optional[ComparisonResult] = None
        if context.has_comparison:
            prev_clauses = []
            if context.comparison_date_from:
                prev_clauses.append(Expense.expense_date >= context.comparison_date_from.date())
            if context.comparison_date_to:
                prev_clauses.append(Expense.expense_date <= context.comparison_date_to.date())

            prev_stmt = select(func.coalesce(func.sum(Expense.amount), Decimal("0.00")))
            if prev_clauses:
                prev_stmt = prev_stmt.where(and_(*prev_clauses))
            prev_val = Decimal(str(session.execute(prev_stmt).scalar_one())).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            comp = calculate_comparison(total, prev_val)

        return ExpenseAnalysisResult(
            total_expenses=total,
            recurring_expenses=recurring,
            variable_expenses=variable,
            recurring_share_pct=rec_share,
            category_breakdown=cat_breakdown,
            comparison=comp,
        )
