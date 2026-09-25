"""Base abstraction for diagnostic investigation strategies."""

from abc import ABC, abstractmethod
from typing import Any

from app.investigation.models import (
    EvidenceGap,
    InvestigationHypothesis,
    InvestigationStep,
    InvestigationType,
)


class BaseInvestigationStrategy(ABC):
    """Abstract interface defining diagnostic strategy behavior."""

    @property
    @abstractmethod
    def investigation_type(self) -> InvestigationType:
        """The specific diagnostic archetype handled by this strategy."""

    @abstractmethod
    def build_initial_steps(
        self, resolved_dates: dict[str, Any], query: str
    ) -> list[InvestigationStep]:
        """Construct the bounded initial sequence of evidence collection steps."""

    @abstractmethod
    def generate_candidate_hypotheses(
        self, investigation_id: str, resolved_dates: dict[str, Any]
    ) -> list[InvestigationHypothesis]:
        """Formulate initial candidate hypotheses to be tested against empirical results."""

    def evaluate_adaptive_branch(
        self,
        current_step_count: int,
        max_steps: int,
        last_step: InvestigationStep,
        last_result: dict[str, Any],
        resolved_dates: dict[str, Any],
    ) -> InvestigationStep | None:
        """
        Optionally propose a dynamically tailored follow-up step based on newly surfaced evidence.
        Returns None if no adaptive drill-down is required or if step limits are reached.
        """
        return None

    def identify_evidence_gaps(
        self, executed_tools: list[str], results: list[dict[str, Any]]
    ) -> list[EvidenceGap]:
        """Audit completed analysis for missing historical data or unmeasured factors."""
        return []
