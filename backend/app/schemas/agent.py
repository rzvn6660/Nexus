"""Pydantic schemas for the Agent API endpoint."""

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.analytics.evidence.models import EvidenceRecord
from app.rag.retrieval.models import RAGEvidence


class AgentAnalyzeRequest(BaseModel):
    """Payload for initiating a business intelligence query via the NEXUS agent."""
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language analytical question")
    explanation_level: str = Field(
        default="manager",
        description="Depth of explanation: 'simple', 'manager', 'analyst', or 'technical'"
    )
    reference_date: date | None = Field(
        default=None,
        description="Optional anchor date for relative temporal parsing (defaults to today)"
    )


class AgentExecutionMetadata(BaseModel):
    """Audit and evaluation metadata capturing execution performance for Phase 9."""
    request_id: str
    elapsed_ms: float
    iterations: int
    tool_call_count: int
    tools_executed: list[str]
    evidence_status: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentResponse(BaseModel):
    """Standardized response from the NEXUS agentic analytics engine."""
    answer: str = Field(description="Grounded natural language narrative explaining the analytical findings")
    intent: str = Field(description="Classified analytical intent category")
    explanation_level: str = Field(description="Requested explanation detail level")
    evidence: list[EvidenceRecord] = Field(
        default_factory=list,
        description="Full provenance and audit records for all underlying deterministic calculations"
    )
    rag_evidence: list[RAGEvidence] = Field(
        default_factory=list,
        description="Business context provenance records proving where definitions and policies originated"
    )
    semantic_context: dict[str, Any] | None = Field(
        default=None,
        description="Resolved KPI ontology and terminology mapping"
    )
    calculations: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Summary of explicit formulas and aggregation rules executed"
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Domain and modeling assumptions applied"
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Caveats and statistical constraints"
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="List of deterministic AnalyticsService tools invoked"
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description="Proactive analytical suggestions for subsequent inquiries"
    )
    needs_clarification: bool = Field(
        default=False,
        description="True if the request was ambiguous and requires further user input"
    )
    clarification_prompt: str | None = Field(
        default=None,
        description="Clarification request text if needs_clarification is True"
    )
    status: str = Field(
        default="completed",
        description="Final execution outcome: 'completed', 'clarification_needed', 'unsupported', or 'error'"
    )
    execution_metadata: AgentExecutionMetadata = Field(
        description="Execution trace metrics for performance monitoring and Phase 9 evaluation"
    )
