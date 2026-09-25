"""Diagnostic strategy for investigating profit decline and growth."""

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


class ProfitInvestigationStrategy(BaseInvestigationStrategy):
    """
    Orchestrates systematic diagnostic investigation into profit changes.
    
    Diagnostic Progression:
    1. Financial Summary: Measure gross profit and net profit movements against COGS and OPEX.
    2. Expense Analytics: Investigate operating expense composition (recurring vs variable overhead).
    3. Price/Volume/Mix: Reconcile top-line drivers impacting unit margins.
    4. Adaptive Step: Decompose category or product variance if gross margin variance dominates.
    """

    def __init__(self, is_decline: bool = True) -> None:
        self._is_decline = is_decline

    @property
    def investigation_type(self) -> InvestigationType:
        return InvestigationType.PROFIT_DECLINE if self._is_decline else InvestigationType.PROFIT_GROWTH

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
                purpose="Establish baseline profitability metrics: Gross Profit, COGS, OPEX, and Net Profit",
                tool="get_financial_summary",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                    "comparison_date_from": c_from,
                    "comparison_date_to": c_to,
                },
            ),
            InvestigationStep(
                step=2,
                purpose="Analyze operating expenses to evaluate overhead changes and recurring cost shares",
                tool="get_expense_analytics",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                },
            ),
            InvestigationStep(
                step=3,
                purpose="Evaluate commercial Price, Volume, and Mix effects on revenue that flow into gross profit",
                tool="run_price_volume_mix",
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
        direction = "decline" if self._is_decline else "growth"
        return [
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-COGS",
                statement=f"Changes in Cost of Goods Sold (COGS) relative to sales volume were the primary contributor to profit {direction}.",
                type="cogs_impact",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending COGS ratio and margin evaluation.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-OPEX",
                statement=f"Operating expense expansion or non-recurring overhead drove net profit {direction}.",
                type="opex_impact",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending expense structure audit.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-VOL",
                statement=f"Top-line sales volume changes, rather than cost inflation, dominated the profit {direction}.",
                type="volume_impact",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending PVM decomposition.",
            ),
        ]

    def evaluate_adaptive_branch(
        self,
        current_step_count: int,
        max_steps: int,
        last_step: InvestigationStep,
        last_result: dict[str, Any],
        resolved_dates: dict[str, Any],
    ) -> InvestigationStep | None:
        if current_step_count >= max_steps:
            return None

        # If financial summary indicates high COGS ratio, drill into product category margin variance
        if last_step.tool == "get_financial_summary":
            return InvestigationStep(
                step=current_step_count + 1,
                purpose="Decompose category variance to identify merchandise lines with margin compression",
                tool="run_variance_analysis",
                arguments={
                    "date_from": resolved_dates.get("date_from"),
                    "date_to": resolved_dates.get("date_to"),
                    "comparison_date_from": resolved_dates.get("comparison_date_from"),
                    "comparison_date_to": resolved_dates.get("comparison_date_to"),
                    "dimension": "category",
                },
            )

        return None

    def identify_evidence_gaps(
        self, executed_tools: list[str], results: list[dict[str, Any]]
    ) -> list[EvidenceGap]:
        return [
            EvidenceGap(
                description="Capital expenditures, depreciation, debt service, and corporate income taxes are not in scope.",
                affected_hypothesis=None,
                missing_data="Non-cash corporate accounting records",
                impact="Analysis is limited to operational Gross Profit and Operating Income (EBIT)."
            )
        ]
