"""Diagnostic strategy for investigating inventory turnover, stockouts, and velocity issues."""

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


class InventoryInvestigationStrategy(BaseInvestigationStrategy):
    """
    Orchestrates systematic diagnostic investigation into inventory operational health.
    
    Diagnostic Progression:
    1. Inventory Overview: Stock quantities, reorder threshold alerts, and valuation.
    2. Inventory Turnover: Turnover ratio and Days Sales of Inventory (DSI).
    3. Inventory Velocity: SKU velocity classifications and dormant inventory identification.
    """

    @property
    def investigation_type(self) -> InvestigationType:
        return InvestigationType.INVENTORY_ISSUE

    def build_initial_steps(
        self, resolved_dates: dict[str, Any], query: str
    ) -> list[InvestigationStep]:
        d_from = resolved_dates.get("date_from")
        d_to = resolved_dates.get("date_to")

        return [
            InvestigationStep(
                step=1,
                purpose="Evaluate real-time inventory health, low-stock counts, and stockout alerts",
                tool="get_inventory_overview",
                arguments={},
            ),
            InvestigationStep(
                step=2,
                purpose="Calculate inventory turnover ratio and Days Sales of Inventory (DSI)",
                tool="get_inventory_turnover",
                arguments={
                    "date_from": d_from,
                    "date_to": d_to,
                },
            ),
            InvestigationStep(
                step=3,
                purpose="Classify SKU sales velocity to locate dormant and slow-moving inventory capital",
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
                id=f"{investigation_id}-HYP-STOCKOUT",
                statement="Stockouts or low stock inventory alerts constrained sales fulfillment capacity.",
                type="stockout_constraint",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending inventory stockout audit.",
            ),
            InvestigationHypothesis(
                id=f"{investigation_id}-HYP-DORMANT",
                statement="A disproportionate share of inventory capital is tied up in slow-moving or dormant SKUs.",
                type="dormant_capital",
                evidence_strength=EvidenceStrength.INSUFFICIENT,
                status=HypothesisStatus.INCONCLUSIVE,
                confidence_reason="Pending turnover and velocity analysis.",
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

        # If low stock count is high, inspect product rankings to cross-reference top selling items
        if last_step.tool == "get_inventory_overview":
            low_stock = int(last_result.get("low_stock_count", 0))
            if low_stock > 0:
                return InvestigationStep(
                    step=current_step_count + 1,
                    purpose="Cross-reference top revenue-generating products with stock alert levels",
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
                description="Historical daily stock snapshot logs are unavailable in the operational schema.",
                affected_hypothesis="stockout_constraint",
                missing_data="Historical daily inventory balance snapshots",
                impact="Current stock levels represent real-time state; cannot definitively prove past stockouts caused historical revenue drops."
            )
        ]
