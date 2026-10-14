"""Pydantic schemas and contracts for Phase 27 Prescriptive Intelligence & Recommendations."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ObjectiveType(str, Enum):
    """Primary commercial objective guiding recommendation evaluation."""
    MINIMIZE_STOCKOUT = "minimize_stockout"
    MINIMIZE_HOLDING_COST = "minimize_holding_cost"
    MAXIMIZE_MARGIN = "maximize_margin"
    BALANCE_SERVICE_LEVEL = "balance_service_level"


class ActionType(str, Enum):
    """Categorized discrete action alternatives evaluated by the engine."""
    REORDER_STANDARD = "reorder_standard"
    REORDER_EXPEDITED = "reorder_expedited"
    MAINTAIN_STOCK = "maintain_stock"
    CLEARANCE_MARKDOWN = "clearance_markdown"
    HOLD_PRICE = "hold_price"
    DO_NOTHING = "do_nothing"


class RecommendationStatus(str, Enum):
    """Execution outcome status for prescriptive recommendation generation."""
    ACTIONABLE = "actionable"
    ABSTAINED = "abstained"
    CONFLICTING_CONSTRAINTS = "conflicting_constraints"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ConstraintSet(BaseModel):
    """Operational and financial boundary constraints for recommendation evaluation."""
    max_budget: float | None = Field(default=None, description="Maximum allowable working capital outlay.")
    max_storage_units: int | None = Field(default=None, description="Physical warehouse capacity limit for SKU.")
    target_service_level: float = Field(default=0.95, ge=0.50, le=0.999, description="Target probability of avoiding stockout.")
    min_order_quantity: int = Field(default=1, ge=1, description="Supplier minimum order quantity (MOQ).")
    max_order_quantity: int | None = Field(default=None, description="Supplier allocation ceiling.")
    lead_time_days: int = Field(default=7, ge=1, description="Supplier replenishment lead time in calendar days.")
    annual_holding_cost_rate: float = Field(default=0.20, ge=0.01, le=1.0, description="Annual cost of capital and storage as % of unit cost.")
    order_setup_cost: float | None = Field(default=None, ge=0.0, description="Tenant-configured procurement order setup cost ($). If omitted, system-wide default assumption ($50.00) is applied.")


class ExpectedImpact(BaseModel):
    """Deterministic quantified business outcomes for an action alternative."""
    expected_cost: float = Field(default=0.0, description="Immediate capital expenditure required ($).")
    expected_revenue_impact: float = Field(default=0.0, description="Expected revenue change ($).")
    expected_margin_impact: float = Field(default=0.0, description="Expected net gross margin delta ($).")
    service_level_achieved: float = Field(default=0.0, description="Estimated non-stockout probability [0.0 - 1.0].")
    stockout_risk: float = Field(default=0.0, description="Estimated probability of stockout before replenishment.")
    working_capital_required: float = Field(default=0.0, description="Working capital committed ($).")
    holding_cost_annual: float = Field(default=0.0, description="Projected annual inventory holding cost ($).")


class UncertaintyRange(BaseModel):
    """Worst-case, expected, and best-case financial dispersion based on forecast intervals."""
    worst_case_margin: float = Field(default=0.0, description="Outcome if lower forecast interval bound materializes ($).")
    expected_margin: float = Field(default=0.0, description="Outcome under central point forecast ($).")
    best_case_margin: float = Field(default=0.0, description="Outcome if upper forecast interval bound materializes ($).")


class ActionAlternative(BaseModel):
    """Discrete commercial action option evaluated against business constraints and objectives."""
    action_type: ActionType = Field(description="Discrete action classification.")
    title: str = Field(description="Short action summary title.")
    description: str = Field(description="Detailed operational description of the proposed action.")
    recommended_quantity: int = Field(default=0, description="Physical unit quantity to order, reallocate, or discount.")
    recommended_discount_pct: float = Field(default=0.0, description="Promotional discount rate (0.0 to 1.0) if applicable.")
    impact: ExpectedImpact = Field(default_factory=ExpectedImpact, description="Quantified business metrics.")
    uncertainty: UncertaintyRange = Field(default_factory=UncertaintyRange, description="Payoff dispersion across prediction intervals.")
    trade_offs: list[str] = Field(default_factory=list, description="Explicit commercial trade-offs and risks.")
    is_feasible: bool = Field(default=True, description="Whether alternative respects all specified constraints.")
    constraint_violations: list[str] = Field(default_factory=list, description="Explanations of violated constraints if infeasible.")


class ObservedFact(BaseModel):
    """Empirical historical measurement extracted deterministically from database tables."""
    metric: str
    value: Any
    source_table: str
    description: str


class ForecastInput(BaseModel):
    """Prospective predictive telemetry consumed from Phase 26 ForecastingService."""
    metric: str
    point_forecast: float
    lower_bound: float
    upper_bound: float
    confidence_level: float
    horizon_periods: int
    frequency: str
    model_name: str


class PrescriptiveRecommendation(BaseModel):
    """
    Standardized evidence-grounded recommendation record.
    
    Guarantees:
    1. Deterministic calculations (zero LLM math).
    2. Strict separation of observed facts, forecast inputs, assumptions, and estimated outcomes.
    3. Multi-alternative comparison against explicit business constraints.
    4. Mandatory Human-in-the-Loop review gating (requires_human_approval = True).
    """
    recommendation_id: str = Field(description="Unique recommendation identifier (e.g. REC-XXXXXXXX).")
    status: RecommendationStatus = Field(description="Operational recommendation status.")
    category: str = Field(description="Prescriptive category: inventory_replenishment or pricing_markdown.")
    business_id: str | None = Field(default=None, description="Tenant business ownership.")
    entity_type: str = Field(default="product", description="Entity scope: product, category, or business.")
    entity_id: str | None = Field(default=None, description="SKU or category identifier.")
    objective: ObjectiveType = Field(description="Governing business objective.")
    recommended_action: ActionAlternative | None = Field(default=None, description="Optimal feasible alternative.")
    alternatives: list[ActionAlternative] = Field(default_factory=list, description="All evaluated candidate actions.")
    observed_facts: list[ObservedFact] = Field(default_factory=list, description="Historical observed baseline evidence.")
    forecast_inputs: list[ForecastInput] = Field(default_factory=list, description="Prospective predictive projections.")
    assumptions: list[str] = Field(default_factory=list, description="Explicit modeling assumptions.")
    limitations: list[str] = Field(default_factory=list, description="Analytical boundaries and unobserved factors.")
    abstention_reason: str | None = Field(default=None, description="Reason for abstention if status != actionable.")
    requires_human_approval: bool = Field(default=True, description="Strict invariant: Human authorization required prior to action.")
    created_at: str = Field(description="ISO timestamp of recommendation generation.")
