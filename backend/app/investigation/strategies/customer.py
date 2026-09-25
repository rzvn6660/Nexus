"""Diagnostic strategy for investigating customer behavior, retention, and segmentation changes."""

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


class CustomerInvestigationStrategy(BaseInvestigationStrategy):
    """
    Orchestrates systematic diagnostic investigation into customer behavior and retention changes.
    
    Diagnostic Progression:
    1. Repeat Purchase: Quantify repeat purchase rate and repeat customer proportions.
    2. Customer Segments: Analyze revenue contribution across customer tiers.
    3. RFM Analysis: Evaluate recency, frequency, and monetary score shifts.
    """

    @property
    def investigation_type(self) -> InvestigationType:
        return InvestigationType.CUSTOMER_CHANGE

    def build_initial_steps(
        self, resolved_dates: dict[str, Any], query: str
    ) -> list[InvestigationStep]:
        d_from = resolved_dates.get("date_from")
        d_to = resolved_dates.get("date_to")

        return [
            InvestigationStep(
                step=1,
                purpose="Evaluate repeat purchase rate and order frequency across ordering customers",
                tool="get_repeat_purchase",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                },
            ),
            InvestigationStep(
                step=2,
                purpose="Analyze revenue and order distribution by customer segment tier",
                tool="get_customer_segments",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                },
            ),
            InvestigationStep(
                step=3,
                purpose="Perform RFM segmentation to evaluate recency and frequency migration",
                tool="get_rfm_analysis",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                },
            ),
        ]

    def generate_candidate_hypotheses(
        self, investigation_id: str, resolved_dates: dict[str, Any]
    ) -> list[InvestigationHypothesis]:
        return [
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-REPEAT",
                statement="A contraction in repeat purchase frequency among existing customers contributed to the observed change.",
                type="repeat_purchase_decline",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending repeat purchase rate measurement.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-TIER",
                statement="High-value VIP or core customer segments experienced lower order activity.",
                type="segment_migration",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending segment breakdown evaluation.",
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

        if last_step.tool == "get_repeat_purchase":
            return InvestigationStep(
                step=current_step_count + 1,
                purpose="Evaluate customer cohort retention to observe multi-period drop-off patterns",
                tool="get_cohort_analysis",
                arguments={
                    "date_from": resolved_dates.get("date_from"),
                    "date_to": resolved_dates.get("date_to"),
                    "max_periods": 6,
                },
            )
        return None

    def identify_evidence_gaps(
        self, executed_tools: list[str], results: list[dict[str, Any]]
    ) -> list[EvidenceGap]:
        return [
            EvidenceGap(
                description="Customer churn surveys, NPS feedback, and direct contact notes are not available.",
                affected_hypothesis=None,
                missing_data="Qualitative customer feedback & satisfaction scores",
                impact="Cannot establish psychological or service-quality reasons behind customer inactivity."
            )
        ]
