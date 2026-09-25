"""Diagnostic strategy for investigating revenue decline and growth."""

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


class RevenueInvestigationStrategy(BaseInvestigationStrategy):
    """
    Orchestrates systematic diagnostic investigation into revenue variances.
    
    Diagnostic Progression:
    1. Financial Summary: Establish baseline, comparison period, and macro revenue variance.
    2. Category Variance: Decompose variance by category to locate concentration.
    3. Price/Volume/Mix: Decompose revenue change into economic drivers (Price vs Volume vs Mix).
    4. Adaptive Drill-down: If concentration is high, drill into product variance.
    """

    def __init__(self, is_decline: bool = True) -> None:
        self._is_decline = is_decline

    @property
    def investigation_type(self) -> InvestigationType:
        return InvestigationType.REVENUE_DECLINE if self._is_decline else InvestigationType.REVENUE_GROWTH

    def build_initial_steps(
        self, resolved_dates: dict[str, Any], query: str
    ) -> list[InvestigationStep]:
        d_from = resolved_dates.get("date_from")
        d_to = resolved_dates.get("date_to")
        c_from = resolved_dates.get("comparison_date_from")
        c_to = resolved_dates.get("comparison_date_to")

        steps = [
            InvestigationStep(
                step=1,
                purpose="Establish macro revenue variance and period comparison baseline",
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
                purpose="Decompose revenue variance by merchandise category to identify primary contributors",
                tool="run_variance_analysis",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                    "comparison_date_from": c_from,
                    "comparison_date_to": c_to,
                    "dimension": "category",
                },
            ),
            InvestigationStep(
                step=3,
                purpose="Decompose revenue change into Price Effect, Volume Effect, and Mix Effect",
                tool="run_price_volume_mix",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                    "comparison_date_from": c_from,
                    "comparison_date_to": c_to,
                },
            ),
        ]
        return steps

    def generate_candidate_hypotheses(
        self, investigation_id: str, resolved_dates: dict[str, Any]
    ) -> list[InvestigationHypothesis]:
        direction_word = "decline" if self._is_decline else "growth"
        return [
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-CAT",
                statement=f"The revenue {direction_word} was concentrated within specific merchandise categories.",
                type="category_contribution",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending variance decomposition across categories.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-VOL",
                statement=f"The revenue {direction_word} was primarily driven by changes in transaction sales volume rather than unit pricing.",
                type="volume_effect",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending Price/Volume/Mix decomposition.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-MIX",
                statement=f"Shifts in the relative product mix significantly impacted overall revenue {direction_word}.",
                type="mix_effect",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending mix effect quantification.",
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

        # If category variance analysis showed strong concentration, drill down into product-level variance
        if last_step.tool == "run_variance_analysis" and last_step.arguments.get("dimension") == "category":
            items = (
                last_result.get("top_negative_contributors", [])
                or last_result.get("top_positive_contributors", [])
                or last_result.get("items", [])
            )
            if items:
                top_item = items[0]
                share = abs(float(top_item.get("contribution_to_change_pct", top_item.get("contribution_percentage", 0.0))))
                if share >= 35.0:  # Material concentration
                    return InvestigationStep(
                        step=current_step_count + 1,
                        purpose="Drill down into product-level variance to isolate specific SKU drivers within top contributors",
                        tool="run_variance_analysis",
                        arguments={
                            "date_from": resolved_dates.get("date_from"),
                            "date_to": resolved_dates.get("date_to"),
                            "comparison_date_from": resolved_dates.get("comparison_date_from"),
                            "comparison_date_to": resolved_dates.get("comparison_date_to"),
                            "dimension": "product",
                        },
                    )

        # If PVM indicates volume effect is dominant, check customer segment participation
        if last_step.tool == "run_price_volume_mix":
            vol = abs(float(last_result.get("volume_effect", 0.0)))
            total = abs(float(last_result.get("total_variance", 1.0)))
            if total > 0 and (vol / total) > 0.6:
                return InvestigationStep(
                    step=current_step_count + 1,
                    purpose="Analyze customer segment activity to determine whether volume change spans all tiers",
                    tool="get_customer_segments",
                    arguments={
                        "date_from": resolved_dates.get("date_from"),
                        "date_to": resolved_dates.get("date_to"),
                    },
                )

        return None

    def identify_evidence_gaps(
        self, executed_tools: list[str], results: list[dict[str, Any]]
    ) -> list[EvidenceGap]:
        gaps: list[EvidenceGap] = [
            EvidenceGap(
                description="Competitor pricing and macroeconomic market indicators are unobserved.",
                affected_hypothesis=None,
                missing_data="External retail market benchmark data",
                impact="Analysis is limited to internal operational and transactional telemetry."
            )
        ]
        return gaps
