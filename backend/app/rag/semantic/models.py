"""Data models and schemas for the NEXUS Semantic Layer and KPI Ontology."""

from enum import Enum

from pydantic import BaseModel, Field


class MetricUnit(str, Enum):
    """Measurement unit for business concepts."""
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    COUNT = "count"
    RATIO = "ratio"
    DAYS = "days"
    UNITS = "units"


class BusinessDomain(str, Enum):
    """Functional business domain taxonomy."""
    FINANCE = "finance"
    SALES = "sales"
    PRODUCT = "product"
    CUSTOMER = "customer"
    INVENTORY = "inventory"
    EXPENSES = "expenses"
    DIAGNOSTIC = "diagnostic"
    STATISTICS = "statistics"


class BusinessRule(BaseModel):
    """Declared business governance rule or accounting convention."""
    rule_id: str = Field(description="Unique business rule identifier")
    name: str = Field(description="Human-readable rule title")
    domain: BusinessDomain
    description: str = Field(description="Policy explanation or domain rationale")
    policy_reference: str | None = Field(default=None, description="Document source or section title")
    active: bool = Field(default=True)


class Dimension(BaseModel):
    """Analytical dimension model for slicing business metrics."""
    dimension_name: str
    display_name: str
    source_table: str
    column_name: str
    allowed_values: list[str] | None = None


class KPI(BaseModel):
    """
    Canonical definition of a Key Performance Indicator (KPI).
    
    Binds business terminology, accounting definitions, and synonyms directly
    to Phase 3 deterministic analytics tools and output fields.
    """
    canonical_name: str = Field(description="System identifier, e.g. 'net_revenue'")
    display_name: str = Field(description="Official business title, e.g. 'Net Revenue'")
    description: str = Field(description="GAAP/Operational business meaning")
    synonyms: list[str] = Field(default_factory=list, description="Alternative business phrases")
    analytics_tool: str = Field(description="Name of the deterministic tool in ToolRegistry")
    metric_field: str = Field(description="Specific field key in tool output result")
    calculation_reference: str = Field(description="Reference to deterministic formula")
    unit: MetricUnit
    business_domain: BusinessDomain
    status: str = Field(default="active", description="'active', 'deprecated', or 'preview'")


BusinessMetric = KPI


class SemanticResolutionResult(BaseModel):
    """Structured resolution produced by the SemanticResolver."""
    query: str
    resolved_kpi: KPI | None = None
    canonical_name: str | None = None
    analytics_tool: str | None = None
    metric_field: str | None = None
    is_ambiguous: bool = False
    candidate_kpis: list[KPI] = Field(default_factory=list)
    is_supported: bool = True
    unsupported_message: str | None = None
    clarification_prompt: str | None = None
    matched_synonym: str | None = None
