"""Data models and schemas for the NEXUS Semantic Layer and KPI Ontology."""

from enum import Enum
from typing import Any

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
    dimension_name: str = Field(description="Canonical dimension identifier (e.g. 'product', 'category')")
    display_name: str = Field(description="Human-readable business display title")
    source_table: str = Field(description="Underlying database source table")
    column_name: str = Field(description="Underlying database column name")
    allowed_values: list[str] | None = Field(default=None, description="Enumerated valid values if constrained")
    aliases: list[str] = Field(default_factory=list, description="Alternative phrasing, abbreviations, or synonyms")
    applicable_tools: list[str] = Field(default_factory=list, description="Tools in ToolRegistry supporting this dimension")
    filter_key: str | None = Field(default=None, description="Parameter key when filtering by this dimension in tools")
    description: str = Field(default="", description="Business explanation of this analytical dimension")


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
    supported_dimensions: list[str] = Field(default_factory=list, description="Canonical dimensions along which this metric can be sliced")
    supported_filters: list[str] = Field(default_factory=list, description="Tool parameter filter keys supported for this metric")
    default_dimension: str | None = Field(default=None, description="Default slicing dimension if breakdown requested without dimension")


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
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score for this semantic resolution (0.0 to 1.0)")
    resolved_dimensions: list[str] = Field(default_factory=list, description="Identified analytical dimensions in the query")
    extracted_filters: dict[str, Any] = Field(default_factory=dict, description="Identified categorical filters or entity constraints")
    temporal_context: dict[str, Any] | None = Field(default=None, description="Temporal interval and granularity context from DateInterpreter")
    evidence_provenance: dict[str, Any] | None = Field(default=None, description="Lineage metadata linking to source table, calculation reference, and accounting rule")
    matched_dimension_aliases: dict[str, str] = Field(default_factory=dict, description="Mapping of query phrases to canonical dimensions")
    unsupported_dimensions: list[str] = Field(default_factory=list, description="Requested analytical dimensions that are unsupported for this metric")
    unsupported_filters: dict[str, Any] = Field(default_factory=dict, description="Requested filter criteria that are unsupported for this metric")
