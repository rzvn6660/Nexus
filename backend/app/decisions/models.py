"""Pydantic data models for structured decision requests, results, and telemetry."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class DecisionTask(str, Enum):
    """Categorized decision tasks handled by the Decision Gateway."""
    INTENT_ROUTING = "intent_routing"
    TOOL_SELECTION = "tool_selection"
    RAG_RERANKING = "rag_reranking"
    EVIDENCE_RELEVANCE = "evidence_relevance"
    EVIDENCE_SUFFICIENCY = "evidence_sufficiency"
    INVESTIGATION_ROUTING = "investigation_routing"
    RISK_GATING = "risk_gating"


class DecisionStatus(str, Enum):
    """Operational status of an executed decision."""
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"


class DecisionTelemetry(BaseModel):
    """Execution telemetry and resource attribution for benchmarking."""
    provider: str = Field(description="Name of the executing provider (e.g., 'structured_llm', 'mock')")
    model: str | None = Field(default=None, description="Underlying model identifier if applicable")
    latency_ms: float = Field(default=0.0, description="Wall-clock decision latency in milliseconds")
    tokens_used: int | None = Field(default=None, description="Total tokens consumed if applicable")
    prompt_tokens: int | None = Field(default=None, description="Prompt tokens consumed if applicable")
    completion_tokens: int | None = Field(default=None, description="Completion tokens consumed if applicable")
    estimated_cost_usd: float | None = Field(default=None, description="Estimated API compute cost in USD")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Provider-specific telemetry and ranking metadata")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the decision evaluation"
    )


class DecisionRequest(BaseModel):
    """
    Provider-independent structured decision request.
    
    Contains task classification, contextual input, candidate discrete choices,
    operational constraints, and caller metadata.
    """
    task: DecisionTask | str = Field(description="Identifier of the decision task to execute")
    input_text: str = Field(description="Primary user query or evaluation target")
    context: dict[str, Any] = Field(default_factory=dict, description="Structured contextual parameters or data")
    candidate_options: list[str] = Field(
        default_factory=list,
        description="Allowed discrete choices (e.g. intent categories, tool names, ranking items)"
    )
    constraints: dict[str, Any] = Field(default_factory=dict, description="Execution boundaries or thresholds")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Audit and correlation metadata (e.g. request_id)")
    expected_schema: dict[str, Any] | None = Field(default=None, description="Optional JSON Schema for structured output validation")


class DecisionResult(BaseModel):
    """
    Standardized result payload emitted by all decision providers.
    
    Adheres strictly to the rule of honest confidence: if the provider does not
    emit a calibrated probability, confidence remains null. Fake numbers are prohibited.
    """
    task: str = Field(description="Task identifier matching the decision request")
    status: DecisionStatus = Field(default=DecisionStatus.SUCCESS, description="Execution outcome status")
    decision: str | None = Field(default=None, description="Primary discrete choice selected from candidate_options")
    structured_output: dict[str, Any] = Field(default_factory=dict, description="Full structured decision payload")
    rationale: str | None = Field(default=None, description="Explanatory reasoning if provided by provider")
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Calibrated probability score ONLY if supplied by provider. None if unavailable."
    )
    telemetry: DecisionTelemetry = Field(description="Telemetry and latency metrics for this execution")
    is_fallback: bool = Field(default=False, description="True if result was produced by an explicit degraded fallback")
    error_message: str | None = Field(default=None, description="Error detail if status is FAILED or DEGRADED")
