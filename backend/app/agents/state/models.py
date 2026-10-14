"""Typed state models and schemas for the NEXUS LangGraph agent architecture."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class IntentCategory(str, Enum):
    """Authoritative analytical intent categories for NEXUS (Phase 13 Taxonomy)."""
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
    SEMANTIC_RESOLUTION = "semantic_resolution"
    BUSINESS_PROFILE = "business_profile"
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
    category: IntentCategory = Field(description="Classified canonical analytical intent")
    subtype: str | None = Field(default=None, description="Optional fine-grained intent subtype")
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
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Plan resolution confidence score")
    warnings: list[str] = Field(default_factory=list, description="Explicit warnings for unsupported dimensions or omitted filters")
    semantic_context: dict[str, Any] | None = Field(default=None, description="Semantic resolution context payload")
    provenance: dict[str, Any] | None = Field(default=None, description="Verified lineage, calculation reference, and accounting rule metadata")
    is_fallback: bool = Field(default=False, description="True if plan was formulated via fallback mock provider")
    fallback_reason: str | None = Field(default=None, description="Sanitized reason for fallback planning")
    llm_provider: str | None = Field(default=None, description="Identifier of the LLM provider that proposed the plan")
    llm_model: str | None = Field(default=None, description="Model name that proposed the plan")


class MetricCitation(BaseModel):
    """Citation of an analytical metric directly derived from tool execution."""
    metric_name: str = Field(description="Name of the metric, e.g. net_sales, gross_profit")
    value: Any = Field(description="Exact value as reported by the deterministic tool")
    tool_source: str = Field(description="Name of the deterministic tool that calculated this metric")
    unit_or_currency: str | None = Field(default=None, description="Currency symbol or unit of measurement")


class GroundedExplanation(BaseModel):
    """Structured, schema-validated analytical explanation grounded in verified evidence."""
    narrative: str = Field(
        description="Clear, executive-ready explanation answering the user's question, tailored to requested explanation level"
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Key bullet-point takeaways strictly grounded in tool results"
    )
    metric_citations: list[MetricCitation] = Field(
        default_factory=list,
        description="Specific metric figures cited with their originating tool source"
    )
    evidence_citations: list[str] = Field(
        default_factory=list,
        description="Explicit provenance citations (e.g. tool results, evidence IDs, accounting rules, document IDs)"
    )
    unsupported_or_missing: list[str] = Field(
        default_factory=list,
        description="Explicit disclosures of missing data, omitted filters, uncomputed metrics, or unverified claims"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings regarding unsupported dimensions, omitted filters, or ambiguity"
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Methodological caveats, statistical boundaries, or sample size limits"
    )
    is_fallback: bool = Field(default=False, description="True if synthesized via deterministic fallback")
    fallback_reason: str | None = Field(default=None, description="Sanitized reason for fallback if applicable")
    llm_provider: str | None = Field(default=None, description="LLM provider that synthesized the explanation")
    llm_model: str | None = Field(default=None, description="LLM model that synthesized the explanation")

    def to_formatted_text(self, explanation_level: ExplanationLevel | str = ExplanationLevel.MANAGER) -> str:
        """
        Format the grounded explanation into a human-readable narrative adhering to
        requested explanation level and disclosure standards.
        """
        lvl_str = explanation_level.value if hasattr(explanation_level, "value") else str(explanation_level)
        sections = [self.narrative.strip()]

        # Format key findings if not already in narrative and not simple level
        if self.key_findings and lvl_str != "simple":
            findings_text = "\n".join(f"• {f}" for f in self.key_findings if f not in self.narrative)
            if findings_text:
                sections.append(f"**Key Findings:**\n{findings_text}")

        # Disclose warnings if present
        if self.warnings:
            unique_warnings = list(dict.fromkeys(self.warnings))
            warn_text = "\n".join(f"⚠️ {w}" for w in unique_warnings if w not in self.narrative)
            if warn_text:
                sections.append(f"**Warnings & Scope Boundaries:**\n{warn_text}")

        # Disclose unsupported or missing data
        if self.unsupported_or_missing:
            unique_missing = list(dict.fromkeys(self.unsupported_or_missing))
            missing_text = "\n".join(f"ℹ️ {m}" for m in unique_missing if m not in self.narrative)
            if missing_text:
                sections.append(f"**Data Limitations & Gaps:**\n{missing_text}")

        # Disclose methodological limitations
        if self.limitations and lvl_str in ("analyst", "technical", "manager"):
            unique_limits = list(dict.fromkeys(self.limitations))
            limits_text = "\n".join(f"• {l}" for l in unique_limits if l not in self.narrative)
            if limits_text and "Note:" not in self.narrative and "Methodological" not in self.narrative:
                sections.append(f"**Methodological Caveats:**\n{limits_text}")

        # Traceability & Evidence for Analyst/Technical
        if lvl_str in ("analyst", "technical") and "--- Traceability & Evidence ---" not in self.narrative:
            trace_lines = ["--- Traceability & Evidence ---"]
            if self.metric_citations:
                trace_lines.append("**Metric Citations:**")
                for mc in self.metric_citations:
                    val_str = f"{mc.unit_or_currency}{mc.value}" if mc.unit_or_currency else str(mc.value)
                    trace_lines.append(f"• {mc.metric_name}: {val_str} (Source: {mc.tool_source})")
            if self.evidence_citations:
                trace_lines.append("**Verified Sources & Policy Provenance:**")
                for ec in self.evidence_citations:
                    trace_lines.append(f"• {ec}")
            if len(trace_lines) > 1:
                sections.append("\n".join(trace_lines))

        # Fallback notice if applicable
        if self.is_fallback:
            reason_msg = self.fallback_reason or "deterministic baseline rules applied"
            if "Notice:" not in self.narrative and "deterministic baseline" not in self.narrative:
                sections.append(f"*Notice: Analysis generated using deterministic baseline rules ({reason_msg}).*")

        return "\n\n".join(s for s in sections if s)


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
    organization_id: str | None
    business_id: str | None
    user_id: str | None
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
    has_business_context_conflict: bool
    business_context_conflict_description: str | None
    iteration_count: int
    max_iterations: int
    is_fallback: bool
    fallback_reason: str | None
    llm_provider_name: str | None
    llm_model_name: str | None
    grounded_explanation: dict[str, Any] | None

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

    # Phase 28 Stage 3 Historical Decision Memory Context
    historical_decisions: list[dict[str, Any]] | None
    historical_decision_context: str | None
    historical_decision_provenance: dict[str, Any] | None

