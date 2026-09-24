"""Pydantic schemas for the Semantic Layer API endpoints."""


from pydantic import BaseModel, Field


class SemanticResolveRequest(BaseModel):
    """Payload for resolving business language against the KPI ontology."""
    query: str = Field(..., min_length=1, max_length=1000, description="Natural language query or metric name")


class KPIResponse(BaseModel):
    """Canonical KPI description and analytics tool linkage."""
    canonical_name: str
    display_name: str
    description: str
    synonyms: list[str] = Field(default_factory=list)
    analytics_tool: str
    metric_field: str
    calculation_reference: str
    unit: str
    business_domain: str
    status: str = "active"


class SemanticResolveResponse(BaseModel):
    """Structured resolution result explaining KPI binding or ambiguity."""
    query: str
    resolved_kpi: KPIResponse | None = None
    canonical_name: str | None = None
    analytics_tool: str | None = None
    metric_field: str | None = None
    is_ambiguous: bool = False
    candidate_kpis: list[KPIResponse] = Field(default_factory=list)
    is_supported: bool = True
    unsupported_message: str | None = None
    clarification_prompt: str | None = None
    matched_synonym: str | None = None
