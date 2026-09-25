"""Diagnostic strategy for investigating gross and net margin changes."""

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


class MarginInvestigationStrategy(BaseInvestigationStrategy):
    """
    Orchestrates systematic diagnostic investigation into gross and net margin changes.
    
    Diagnostic Progression:
    1. Financial Summary: Measure margin ratios and cost-to-revenue relationships.
    2. Price/Volume/Mix: Isolate price realization effect from product mix shifts.
    3. Category Breakdown: Inspect category contributions to identify low-margin product groups.
    """

    @property
    def investigation_type(self) -> InvestigationType:
        return InvestigationType.MARGIN_CHANGE

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
                purpose="Establish baseline gross margin and net margin percentage changes",
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
                purpose="Evaluate Price Effect vs Mix Effect to determine if margin changed due to price cuts or product mix shifts",
                tool="run_price_volume_mix",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                    "comparison_date_from": c_from,
                    "comparison_date_to": c_to,
                },
            ),
            InvestigationStep(
                step=3,
                purpose="Inspect category breakdown to identify lower-margin merchandise categories",
                tool="get_category_breakdown",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                    "metric": "revenue",
                },
            ),
        ]

    def generate_candidate_hypotheses(
        self, investigation_id: str, resolved_dates: dict[str, Any]
    ) -> list[InvestigationHypothesis]:
        return [
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-PRICE",
                statement="Discounting or lower realized selling prices contributed to gross margin compression.",
                type="price_effect",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending Price Effect quantification in PVM.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-MIX",
                statement="A shift in consumer demand toward lower-margin merchandise diluted overall margin.",
                type="mix_effect",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending Mix Effect quantification in PVM.",
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

        if last_step.tool == "run_price_volume_mix":
            mix = abs(float(last_result.get("mix_effect", 0.0)))
            total = abs(float(last_result.get("total_variance", 1.0)))
            if total > 0 and (mix / total) > 0.3:
                return InvestigationStep(
                    step=current_step_count + 1,
                    purpose="Dissect product rankings to identify specific low-margin items gaining volume share",
                    tool="get_product_rankings",
                    arguments={
                        "date_from": resolved_dates.get("date_from"),
                        "date_to": resolved_dates.get("date_to"),
                        "ranking_metric": "revenue",
                        "limit": 10,
                    },
                )
        return None

    def identify_evidence_gaps(
        self, executed_tools: list[str], results: list[dict[str, Any]]
    ) -> list[EvidenceGap]:
        return [
            EvidenceGap(
                description="Historical vendor purchase order price changes are not tracked per batch.",
                affected_hypothesis=None,
                missing_data="Vendor wholesale purchase order batch pricing",
                impact="COGS is calculated using current product unit_cost rather than historical FIFO batches."
            )
        ]
