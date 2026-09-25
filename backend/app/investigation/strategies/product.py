"""Diagnostic strategy for investigating product and category performance changes."""

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


class ProductInvestigationStrategy(BaseInvestigationStrategy):
    """
    Orchestrates systematic diagnostic investigation into product and category variances.
    
    Diagnostic Progression:
    1. Product Rankings: Evaluate revenue, units sold, and margins across catalog SKUs.
    2. Variance Analysis: Decompose product-level revenue differences against comparison period.
    3. Inventory Velocity: Identify velocity slowdowns and dormant catalog items.
    """

    @property
    def investigation_type(self) -> InvestigationType:
        return InvestigationType.PRODUCT_PERFORMANCE_CHANGE

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
                purpose="Rank top products by revenue and evaluate unit volumes and margins",
                tool="get_product_rankings",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                    "ranking_metric": "revenue",
                    "limit": 15,
                },
            ),
            InvestigationStep(
                step=2,
                purpose="Analyze product-level variance against baseline period to identify specific SKU drivers",
                tool="run_variance_analysis",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                    "comparison_date_from": c_from,
                    "comparison_date_to": c_to,
                    "dimension": "product",
                },
            ),
            InvestigationStep(
                step=3,
                purpose="Evaluate SKU sales velocity to classify high, medium, slow, and dormant items",
                tool="get_inventory_velocity",
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
                id=f"{investigation_id}-HYP-CONCENTRATION",
                statement="Performance variance was concentrated in a small subset of high-volume SKUs.",
                type="sku_concentration",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending product variance distribution.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-VELOCITY",
                statement="Product velocity decelerated across active catalog lines, increasing dormant SKU counts.",
                type="velocity_slowdown",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending velocity analysis.",
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

        if last_step.tool == "run_variance_analysis":
            return InvestigationStep(
                step=current_step_count + 1,
                purpose="Decompose variance by merchandise category to check if product trends are category-wide",
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
                description="Marketing ad spend and promotional campaign tagging per SKU are not tracked.",
                affected_hypothesis=None,
                missing_data="Marketing campaign attribution data",
                impact="Cannot determine whether product slowdown is correlated with reduced promotional ad spend."
            )
        ]
