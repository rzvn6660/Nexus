"""Generic diagnostic strategy for general variance and contribution inquiries."""

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


class GenericDiagnosticStrategy(BaseInvestigationStrategy):
    """
    Fallback diagnostic strategy for inquiries not matching specific metric archetypes.
    
    Diagnostic Progression:
    1. Financial Summary: Establish period performance baselines.
    2. Variance Analysis: Decompose revenue variance by category.
    3. Price/Volume/Mix: Decompose revenue change into fundamental economic drivers.
    """

    @property
    def investigation_type(self) -> InvestigationType:
        return InvestigationType.GENERIC_DIAGNOSTIC

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
                purpose="Establish macro business performance and period-over-period baseline",
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
                purpose="Decompose variance by merchandise category to inspect distribution",
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
                purpose="Evaluate commercial Price, Volume, and Mix effects",
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
        return [
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-VARIANCE",
                statement="The observed variance was concentrated in specific commercial segments or categories.",
                type="category_variance",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending variance decomposition.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-VOLUME",
                statement="Transaction volume shifts, rather than pricing variations, were the primary factor.",
                type="volume_driver",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending PVM analysis.",
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
            items = (
                last_result.get("top_negative_contributors", [])
                or last_result.get("top_positive_contributors", [])
                or last_result.get("items", [])
            )
            if items:
                top_item = items[0]
                share = abs(float(top_item.get("contribution_to_change_pct", top_item.get("contribution_percentage", 0.0))))
                if share >= 40.0 and last_step.arguments.get("dimension") != "product":
                    return InvestigationStep(
                        step=current_step_count + 1,
                        purpose="Drill down into product-level variance following high category concentration",
                        tool="run_variance_analysis",
                        arguments={
                            "date_from": resolved_dates.get("date_from"),
                            "date_to": resolved_dates.get("date_to"),
                            "comparison_date_from": resolved_dates.get("comparison_date_from"),
                            "comparison_date_to": resolved_dates.get("comparison_date_to"),
                            "dimension": "product",
                        },
                    )
        return None

    def identify_evidence_gaps(
        self, executed_tools: list[str], results: list[dict[str, Any]]
    ) -> list[EvidenceGap]:
        return [
            EvidenceGap(
                description="Exogenous market conditions and customer behavioral surveys are unobserved.",
                affected_hypothesis=None,
                missing_data="Macroeconomic and consumer sentiment indices",
                impact="Analysis is strictly confined to internal transactional records."
            )
        ]
