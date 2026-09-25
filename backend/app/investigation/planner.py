"""Investigation Planner responsible for formulating structured diagnostic plans."""

from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta

from app.core.config import settings
from app.investigation.models import (
    InvestigationPlan,
    InvestigationType,
)
from app.investigation.strategies import get_investigation_strategy
from app.investigation.validators import InvestigationValidator


class InvestigationPlanner:
    """
    Decomposes business diagnostic inquiries into inspectable, deterministic investigation plans.
    """

    @classmethod
    def classify_investigation_type(
        cls, query: str, semantic_context: dict[str, Any] | None = None
    ) -> InvestigationType:
        """Deterministically map natural language query and semantic metadata to an investigation archetype."""
        q = query.lower()

        # Check semantic KPI context first if available
        if semantic_context:
            canonical_name = semantic_context.get("canonical_name", "").lower()
            if "profit" in canonical_name or "margin" in canonical_name:
                if any(w in q for w in ["margin", "discount"]):
                    return InvestigationType.MARGIN_CHANGE
                if any(w in q for w in ["grow", "growth", "increase", "up", "rise"]):
                    return InvestigationType.PROFIT_GROWTH
                return InvestigationType.PROFIT_DECLINE
            if "inventory" in canonical_name or canonical_name in ("inventory_turnover", "days_sales_inventory", "stock_value"):
                return InvestigationType.INVENTORY_ISSUE
            if "customer" in canonical_name or canonical_name in ("repeat_purchase_rate", "active_customer"):
                return InvestigationType.CUSTOMER_CHANGE
            if "expense" in canonical_name or canonical_name in ("operating_expense", "fixed_expense"):
                return InvestigationType.EXPENSE_CHANGE

        # Keyword mapping
        if any(w in q for w in ["inventory", "stock", "stockout", "out of stock", "reorder", "warehouse"]):
            return InvestigationType.INVENTORY_ISSUE
        if any(w in q for w in ["customer", "repeat purchase", "retention", "cohort", "rfm", "churn"]):
            return InvestigationType.CUSTOMER_CHANGE
        if any(w in q for w in ["expense", "opex", "overhead", "operating cost"]):
            return InvestigationType.EXPENSE_CHANGE
        if any(w in q for w in ["gross margin", "net margin", "margin", "discount"]):
            return InvestigationType.MARGIN_CHANGE
        if any(w in q for w in ["profit", "net profit", "gross profit", "earnings", "bottom line"]):
            if any(w in q for w in ["grow", "growth", "increase", "up", "rose", "improved"]):
                return InvestigationType.PROFIT_GROWTH
            return InvestigationType.PROFIT_DECLINE
        if any(w in q for w in ["product", "sku", "category", "best seller", "items"]):
            return InvestigationType.PRODUCT_PERFORMANCE_CHANGE
        if any(w in q for w in ["grow", "growth", "increase", "up", "rose", "surge", "higher"]):
            return InvestigationType.REVENUE_GROWTH
        if any(w in q for w in ["decline", "fall", "drop", "fell", "decrease", "down", "lower", "slump", "loss"]):
            return InvestigationType.REVENUE_DECLINE

        return InvestigationType.GENERIC_DIAGNOSTIC

    @classmethod
    def resolve_comparison_dates(cls, resolved_dates: dict[str, Any]) -> dict[str, Any]:
        """
        Ensure both current evaluation dates and baseline comparison dates are populated.
        If comparison dates are absent, automatically construct the preceding equivalent temporal period.
        """
        dates = dict(resolved_dates)
        d_from_str = dates.get("date_from")
        d_to_str = dates.get("date_to")
        c_from_str = dates.get("comparison_date_from")
        c_to_str = dates.get("comparison_date_to")

        if d_from_str and d_to_str and (not c_from_str or not c_to_str):
            try:
                d_from = date.fromisoformat(str(d_from_str))
                d_to = date.fromisoformat(str(d_to_str))
                delta_days = (d_to - d_from).days + 1

                # If full month interval, shift back 1 month
                if d_from.day == 1 and (d_to + relativedelta(days=1)).day == 1:
                    c_to = d_from - relativedelta(days=1)
                    c_from = c_to.replace(day=1)
                else:
                    c_to = d_from - relativedelta(days=1)
                    c_from = c_to - relativedelta(days=delta_days - 1)

                dates["comparison_date_from"] = c_from.isoformat()
                dates["comparison_date_to"] = c_to.isoformat()
            except (ValueError, TypeError):
                pass

        return dates

    @classmethod
    def plan(
        cls,
        query: str,
        semantic_context: dict[str, Any] | None = None,
        resolved_dates: dict[str, Any] | None = None,
    ) -> tuple[InvestigationPlan, list[str]]:
        """
        Formulate a structured InvestigationPlan for the diagnostic inquiry.
        Returns the plan and any validation errors encountered.
        """
        clean_dates = cls.resolve_comparison_dates(resolved_dates or {})
        inv_type = cls.classify_investigation_type(query, semantic_context)
        strategy = get_investigation_strategy(inv_type)

        initial_steps = strategy.build_initial_steps(clean_dates, query)
        max_steps = getattr(settings, "MAX_INVESTIGATION_STEPS", 8)

        goal = f"Diagnose factors contributing to {inv_type.value.replace('_', ' ')}: '{query}'"

        plan = InvestigationPlan(
            goal=goal,
            investigation_type=inv_type,
            baseline_dates={
                "date_from": clean_dates.get("comparison_date_from"),
                "date_to": clean_dates.get("comparison_date_to"),
            },
            comparison_dates={
                "date_from": clean_dates.get("date_from"),
                "date_to": clean_dates.get("date_to"),
            },
            context_dates=clean_dates,
            steps=initial_steps,
            adaptive_branching_enabled=True,
            max_steps=max_steps,
        )

        _is_valid, errors = InvestigationValidator.validate_plan(plan)
        return plan, errors
