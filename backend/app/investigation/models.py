"""Domain models and data structures for the NEXUS Investigation Engine (Phase 6 Diagnostic Intelligence)."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class InvestigationType(str, Enum):
    """Supported diagnostic investigation archetypes."""
    REVENUE_DECLINE = "revenue_decline"
    REVENUE_GROWTH = "revenue_growth"
    PROFIT_DECLINE = "profit_decline"
    PROFIT_GROWTH = "profit_growth"
    MARGIN_CHANGE = "margin_change"
    SALES_CHANGE = "sales_change"
    PRODUCT_PERFORMANCE_CHANGE = "product_performance_change"
    CATEGORY_PERFORMANCE_CHANGE = "category_performance_change"
    CUSTOMER_CHANGE = "customer_change"
    INVENTORY_ISSUE = "inventory_issue"
    EXPENSE_CHANGE = "expense_change"
    DISCOUNT_CHANGE = "discount_change"
    GENERIC_DIAGNOSTIC = "generic_diagnostic"


class EvidenceStrength(str, Enum):
    """
    Transparent evidence strength classification.
    
    Levels:
    - DIRECT: A deterministic decomposition directly attributes a measurable share of variance.
    - STRONG: Multiple independent analyses point in the same direction.
    - MODERATE: A measurable association or contribution exists but does not establish causality.
    - WEAK: A plausible relationship exists with limited supporting evidence.
    - INSUFFICIENT: Available data cannot support the hypothesis.
    """
    DIRECT = "DIRECT"
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    INSUFFICIENT = "INSUFFICIENT"


class HypothesisStatus(str, Enum):
    """Evaluation status of an investigative hypothesis."""
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class InvestigationStatus(str, Enum):
    """Lifecycle status of a diagnostic investigation."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    STOPPED = "stopped"
    CLARIFICATION_NEEDED = "clarification_needed"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class StoppedReason(str, Enum):
    """Terminal reason for halting investigative steps."""
    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    NO_FURTHER_HYPOTHESES = "no_further_hypotheses"
    TOOL_LIMITATIONS = "tool_limitations"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    ITERATION_LIMIT_REACHED = "iteration_limit_reached"
    MISSING_REQUIRED_DATA = "missing_required_data"


class EvidenceLink(BaseModel):
    """Traceable link connecting a tool result metric to an investigative hypothesis."""
    tool_name: str = Field(description="Name of the deterministic tool executed")
    metric: str = Field(description="Specific metric evaluated (e.g. variance, volume_effect, correlation)")
    source: str = Field(description="Primary underlying database table or entity source")
    value: Any = Field(description="Measured numerical or categorized value")
    contribution_pct: float | None = Field(
        default=None,
        description="Share of total variance or contribution percentage where applicable"
    )
    notes: str = Field(default="", description="Descriptive context or analytical qualifier")


class InvestigationObservation(BaseModel):
    """Factual, empirical observation established by deterministic execution."""
    id: str = Field(description="Unique observation identifier (e.g. OBS-1)")
    statement: str = Field(description="Fact-based empirical statement (e.g. 'Revenue declined by 8.2%')")
    metric: str = Field(description="Canonical metric name")
    value_baseline: float | None = Field(default=None, description="Baseline period magnitude")
    value_current: float | None = Field(default=None, description="Evaluation period magnitude")
    change_abs: float | None = Field(default=None, description="Absolute difference")
    change_pct: float | None = Field(default=None, description="Relative percentage change")
    period_baseline: str | None = Field(default=None, description="Baseline date interval string")
    period_current: str | None = Field(default=None, description="Current evaluation date interval string")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InvestigationHypothesis(BaseModel):
    """Candidate explanation tested against collected evidence."""
    id: str = Field(description="Unique hypothesis identifier (e.g. HYP-1)")
    statement: str = Field(description="Hypothesis assertion (e.g. 'Category A was the primary contributor')")
    type: str = Field(description="Hypothesis category (e.g. category_contribution, volume_effect, inventory_shortage)")
    supporting_evidence: list[EvidenceLink] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceLink] = Field(default_factory=list)
    evidence_strength: EvidenceStrength = Field(default=EvidenceStrength.INSUFFICIENT)
    status: HypothesisStatus = Field(default=HypothesisStatus.INCONCLUSIVE)
    confidence_reason: str = Field(default="", description="Factual justification for status and strength assignment")
    limitations: list[str] = Field(default_factory=list, description="Caveats and constraints")


class InvestigationConclusion(BaseModel):
    """Verified analytical conclusion derived from tested hypotheses with explicit causality safeguards."""
    id: str = Field(description="Conclusion identifier (e.g. CONC-1)")
    statement: str = Field(description="Audited conclusion statement")
    hypothesis_id: str | None = Field(default=None, description="Associated hypothesis ID")
    strength: EvidenceStrength = Field(description="Evaluated evidence strength")
    supporting_tools: list[str] = Field(default_factory=list, description="Tools providing direct validation")
    contribution_share_pct: float | None = Field(
        default=None,
        description="Quantified share of variance or impact percentage"
    )
    causal_caveat: str = Field(
        default="Contribution/association measure; does not prove independent causal mechanism.",
        description="Safeguard distinguishing contribution/association from independent causation"
    )


class EvidenceGap(BaseModel):
    """Explicitly documented missing data or unmeasured factor preventing conclusive evaluation."""
    description: str = Field(description="Description of what could not be established")
    affected_hypothesis: str | None = Field(default=None, description="Related hypothesis identifier")
    missing_data: str = Field(description="Specific data element or historical snapshot not available")
    impact: str = Field(description="Analytical consequence of this gap")


class InvestigationStep(BaseModel):
    """Discrete executable step within an adaptive investigation plan."""
    step: int = Field(description="1-indexed sequence order")
    purpose: str = Field(description="Specific investigative objective of this step")
    tool: str = Field(description="Name of registered deterministic tool to execute")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Validated tool arguments")
    executed: bool = Field(default=False, description="Whether this step has been completed")
    result_summary: dict[str, Any] | None = Field(default=None, description="Summarized output from step")


class InvestigationPlan(BaseModel):
    """Structured, bounded plan orchestrating evidence collection."""
    goal: str = Field(description="Diagnostic investigative goal")
    investigation_type: InvestigationType = Field(description="Classified investigation archetype")
    baseline_dates: dict[str, Any] = Field(default_factory=dict, description="Baseline period dates")
    comparison_dates: dict[str, Any] = Field(default_factory=dict, description="Comparison period dates")
    context_dates: dict[str, Any] = Field(default_factory=dict, description="Full context dates dictionary")
    steps: list[InvestigationStep] = Field(default_factory=list, description="Ordered investigative steps")
    adaptive_branching_enabled: bool = Field(default=True, description="Allow dynamic drill-down based on results")
    max_steps: int = Field(default=8, ge=1, le=12, description="Upper bound on total investigative steps")


class DiagnosticSummary(BaseModel):
    """High-level executive summary of diagnostic findings."""
    metric_analyzed: str
    direction: str
    magnitude_pct: float | None = None
    primary_contributor: str | None = None
    contributor_share_pct: float | None = None
    primary_effect: str | None = None
