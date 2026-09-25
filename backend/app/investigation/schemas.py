"""Pydantic request and response schemas for the Investigation API."""

from datetime import date

from pydantic import BaseModel, Field

from app.analytics.evidence.models import EvidenceRecord
from app.investigation.models import (
    EvidenceGap,
    InvestigationConclusion,
    InvestigationHypothesis,
    InvestigationObservation,
    InvestigationStep,
)
from app.rag.retrieval.models import RAGEvidence


class InvestigationRequest(BaseModel):
    """Payload for submitting a diagnostic investigation inquiry."""
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language diagnostic question (e.g. 'Why did revenue decline in August?')"
    )
    explanation_level: str = Field(
        default="manager",
        description="Audience depth: 'simple', 'manager', 'analyst', or 'technical'"
    )
    reference_date: date | None = Field(
        default=None,
        description="Anchor reference date for relative temporal parsing"
    )


class InvestigationResponse(BaseModel):
    """Audited, evidence-backed diagnostic response from the Investigation Engine."""
    status: str = Field(
        default="completed",
        description="Lifecycle status: 'completed', 'clarification_needed', 'unsupported', or 'failed'"
    )
    question: str = Field(description="The user's original diagnostic inquiry")
    summary: str = Field(description="High-level diagnostic executive takeaway")
    investigation_type: str = Field(description="Classified investigation archetype")
    observations: list[InvestigationObservation] = Field(
        default_factory=list,
        description="Empirical observations established from tool executions"
    )
    hypotheses: list[InvestigationHypothesis] = Field(
        default_factory=list,
        description="Tested candidate explanations with evidence strength and status"
    )
    conclusions: list[InvestigationConclusion] = Field(
        default_factory=list,
        description="Audited conclusions accompanied by causality safeguards"
    )
    evidence: list[EvidenceRecord] = Field(
        default_factory=list,
        description="Deterministic calculation evidence records from AnalyticsService"
    )
    rag_evidence: list[RAGEvidence] = Field(
        default_factory=list,
        description="Business context and policy documentation provenance"
    )
    evidence_gaps: list[EvidenceGap] = Field(
        default_factory=list,
        description="Explicitly identified missing data or unmeasured telemetry"
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Analytical and modeling assumptions applied"
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Data and statistical caveats"
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="List of deterministic analytics tools invoked"
    )
    investigation_steps: list[InvestigationStep] = Field(
        default_factory=list,
        description="Complete sequence of investigative steps executed"
    )
    stopped_reason: str = Field(
        default="sufficient_evidence",
        description="Termination rationale: 'sufficient_evidence', 'iteration_limit_reached', etc."
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description="Proactive analytical inquiries suggested for further exploration"
    )
    explanation: str = Field(
        description="Grounded, section-formatted diagnostic narrative"
    )
