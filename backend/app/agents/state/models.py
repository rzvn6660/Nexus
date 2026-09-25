"""Typed state models and schemas for the NEXUS LangGraph agent architecture."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class IntentCategory(str, Enum):
    """Supported analytical intent categories for Phase 4."""
    METRIC_LOOKUP = "metric_lookup"
    COMPARISON = "comparison"
    TREND = "trend"
    PRODUCT_ANALYSIS = "product_analysis"
    CUSTOMER_ANALYSIS = "customer_analysis"
    INVENTORY_ANALYSIS = "inventory_analysis"
    EXPENSE_ANALYSIS = "expense_analysis"
    DIAGNOSTIC_ANALYSIS = "diagnostic_analysis"
    STATISTICAL_ANALYSIS = "statistical_analysis"
    FORECASTING = "forecasting"
    UNSUPPORTED = "unsupported"


class ExplanationLevel(str, Enum):
    """User experience explanation depth."""
    SIMPLE = "simple"
    MANAGER = "manager"
    ANALYST = "analyst"
    TECHNICAL = "technical"


class EvidenceSufficiencyStatus(str, Enum):
    """Evidence completeness state evaluation."""
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


class IntentResult(BaseModel):
    """Structured intent classification payload."""
    category: IntentCategory = Field(description="Classified analytical intent")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Classification confidence")
    reasoning: str = Field(default="", description="Reasoning behind intent classification")


class PlanStep(BaseModel):
    """A discrete analytical step within a structured analysis plan."""
    step_index: int = Field(description="0-indexed step sequence position")
    tool_name: str = Field(description="Name of the deterministic tool to execute")
    purpose: str = Field(description="Business objective for this analytical step")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Validated tool arguments")


class AnalysisPlan(BaseModel):
    """Structured analytical plan generated prior to tool invocation."""
    goal: str = Field(description="High-level analytical goal")
    steps: list[PlanStep] = Field(default_factory=list, description="Ordered tool execution steps")
    context_dates: dict[str, Any] = Field(
        default_factory=dict,
        description="Temporal interval boundaries resolved for this plan"
    )


class ToolCallRecord(BaseModel):
    """Audit record of an initiated tool execution."""
    tool: str
    arguments: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolResultRecord(BaseModel):
    """Structured result produced by a tool execution node."""
    tool: str
    status: str = Field(description="'success' or 'error'")
    result: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] | None = None
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    error_message: str | None = None


class AgentState(TypedDict, total=False):
    """
    State definition for the NEXUS LangGraph state machine.
    
    Carries the full context, plan, evidence, and execution trace
    across all nodes in the state graph.
    """
    request_id: str
    user_query: str
    explanation_level: str
    reference_date: str | None
    intent: dict[str, Any] | None
    resolved_dates: dict[str, Any]
    analysis_plan: dict[str, Any] | None
    current_step_index: int
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    assumptions: list[str]
    limitations: list[str]
    evidence_status: str
    needs_clarification: bool
    clarification_question: str | None
    is_unsupported: bool
    unsupported_reason: str | None
    final_answer: str | None
    calculations: list[dict[str, Any]]
    tools_used: list[str]
    follow_up_questions: list[str]
    errors: list[str]
    semantic_context: dict[str, Any] | None
    rag_evidence: list[dict[str, Any]]
    business_context_text: str | None
    is_definitional_only: bool
    iteration_count: int
    max_iterations: int

    # Phase 6 Investigation State
    is_investigation_required: bool
    investigation_id: str | None
    investigation_goal: str | None
    investigation_type: str | None
    investigation_plan: dict[str, Any] | None
    investigation_steps: list[dict[str, Any]]
    current_investigation_step: int
    hypotheses: list[dict[str, Any]]
    hypothesis_results: list[dict[str, Any]]
    evidence_items: list[dict[str, Any]]
    evidence_gaps: list[dict[str, Any]]
    investigation_status: str | None
    investigation_iterations: int
    max_investigation_iterations: int
    diagnostic_summary: dict[str, Any] | None

    # Phase 7 Predictive State
    is_forecast_required: bool
    forecast_target: str | None
    forecast_horizon: int | None
    forecast_frequency: str | None
    forecast_result: dict[str, Any] | None
