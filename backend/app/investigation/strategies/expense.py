"""Diagnostic strategy for investigating operating expense changes."""

from typing import Any

from app.investigation.models import (
    EvidenceGap,
    EvidenceStrength,
    HypothesisStatus,
    InvestigationHypothesis,
    InvestigationStep,
    InvestigationType,
)
from app.investigation.strategies.base import BaseInvestigationStrategy


class ExpenseInvestigationStrategy(BaseInvestigationStrategy):
    """
    Orchestrates systematic diagnostic investigation into operating expense growth and overhead changes.
    
    Diagnostic Progression:
    1. Expense Analytics: Aggregate total expenses, recurring overhead share, and category distributions.
    2. Financial Summary: Compare expense growth relative to net sales (OPEX ratio).
    """

    @property
    def investigation_type(self) -> InvestigationType:
        return InvestigationType.EXPENSE_CHANGE

    def build_initial_steps(
        self, resolved_dates: dict[str, Any], query: str
    ) -> list[InvestigationStep]:
        d_from = resolved_dates.get("date_from")
        d_to = resolved_dates.get("date_to")
        c_from = resolved_dates.get("comparison_date_from")
        c_to = resolved_dates.get("comparison_date_to")

        return [
            InvestigationStep(
                step=1,
                purpose="Evaluate operating expenses partitioned into recurring overhead and variable costs",
                tool="get_expense_analytics",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                },
            ),
            InvestigationStep(
                step=2,
                purpose="Evaluate commercial revenue and OPEX ratio in financial summary",
                tool="get_financial_summary",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                    "comparison_date_from": c_from,
                    "comparison_date_to": c_to,
                },
            ),
        ]

    def generate_candidate_hypotheses(
        self, investigation_id: str, resolved_dates: dict[str, Any]
    ) -> list[InvestigationHypothesis]:
        return [
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-EXP-RECURRING",
                statement="Fixed recurring operational commitments (e.g. lease, SaaS, base salaries) drove expense growth.",
                type="recurring_overhead",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending recurring overhead share measurement.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-EXP-VARIABLE",
                statement="Variable operational or administrative costs expanded disproportionately.",
                type="variable_overhead",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending expense category breakdown.",
            ),
        ]

    def identify_evidence_gaps(
        self, executed_tools: list[str], results: list[dict[str, Any]]
    ) -> list[EvidenceGap]:
        return [
            EvidenceGap(
                description="Sub-line vendor invoices and line-item expense receipts are summarized at category level.",
                affected_hypothesis=None,
                missing_data="Granular sub-invoice receipt telemetry",
                impact="Analysis is limited to ledger categories without sub-vendor line scrutiny."
            )
        ]
