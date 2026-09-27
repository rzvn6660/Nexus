"""Pydantic schemas for Tenant Business Understanding and Semantic Activation (Phase 17)."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class KPIResponse(BaseModel):
    """Schema for individual KPI details from canonical ontology."""
    canonical_name: str
    display_name: str
    description: str
    synonyms: List[str] = Field(default_factory=list)
    analytics_tool: str
    metric_field: str
    calculation_reference: str
    unit: str
    business_domain: str
    status: str


class MetricAvailability(BaseModel):
    """Availability and grounding definition for a business metric."""
    canonical_name: str
    display_name: str
    description: str
    status: str  # AVAILABLE, REQUIRES_COST_DATA, INSUFFICIENT_HISTORY, UNAVAILABLE
    source_table: str
    source_field: str
    calculation_formula: str
    unit: str
    business_domain: str
    missing_prerequisites: List[str] = Field(default_factory=list)


class EntityUnderstanding(BaseModel):
    """Catalog of a discovered business entity."""
    entity_name: str
    record_count: int
    mapped_fields: Dict[str, str] = Field(default_factory=dict)
    sample_identifiers: List[str] = Field(default_factory=list)
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None


class DimensionUnderstanding(BaseModel):
    """Catalog of an analytical slicing dimension."""
    dimension_name: str
    source_table: str
    source_column: str
    cardinality: int = 0
    sample_values: List[str] = Field(default_factory=list)


class BusinessDataSummary(BaseModel):
    """Deterministic, database-grounded summary of customer's operational records."""
    sales_count: int = 0
    sales_date_start: Optional[str] = None
    sales_date_end: Optional[str] = None
    customers_count: int = 0
    products_count: int = 0
    inventory_count: int = 0
    expenses_count: int = 0
    supported_analytics: List[str] = Field(default_factory=list)
    unsupported_analytics: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class BusinessUnderstandingResponse(BaseModel):
    """Complete Business Understanding payload for workspace operators."""
    business_id: str
    version: int
    status: str  # NOT_ACTIVATED, ACTIVATING, ACTIVE, REQUIRES_REVIEW, FAILED
    source_dataset_id: Optional[str] = None
    summary: BusinessDataSummary
    entities: Dict[str, EntityUnderstanding] = Field(default_factory=dict)
    metrics: Dict[str, MetricAvailability] = Field(default_factory=dict)
    dimensions: Dict[str, DimensionUnderstanding] = Field(default_factory=dict)
    synonyms: Dict[str, str] = Field(default_factory=dict)
    ambiguous_terms: Dict[str, Any] = Field(default_factory=dict)
    has_conflicts: bool = False
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    activated_at: Optional[str] = None


class SemanticRevisionSummary(BaseModel):
    """Summary of a past semantic understanding revision."""
    id: str
    version: int
    status: str
    source_dataset_id: Optional[str] = None
    created_at: str
    entities_count: int
    metrics_available_count: int


class SemanticActivationRequest(BaseModel):
    """Explicit request to generate or refresh business understanding."""
    force_refresh: bool = False
    custom_synonyms: Optional[Dict[str, str]] = None


class SemanticActivationResponse(BaseModel):
    """Result of activating or refreshing business understanding."""
    business_id: str
    version: int
    status: str
    message: str
    understanding: BusinessUnderstandingResponse


class SemanticResolveRequest(BaseModel):
    """Query resolution request against tenant semantic model."""
    query: str


class SemanticResolveResponse(BaseModel):
    """Structured resolution produced for a query."""
    query: str
    canonical_name: Optional[str] = None
    canonical_kpi: Optional[str] = None
    display_name: Optional[str] = None
    analytics_tool: Optional[str] = None
    metric_field: Optional[str] = None
    resolved_kpi: Optional[KPIResponse] = None
    candidate_kpis: List[KPIResponse] = Field(default_factory=list)
    availability_status: str = "AVAILABLE"  # AVAILABLE, REQUIRES_COST_DATA, INSUFFICIENT_HISTORY, UNAVAILABLE
    source_table: Optional[str] = None
    source_field: Optional[str] = None
    calculation_formula: Optional[str] = None
    unit: Optional[str] = None
    is_ambiguous: bool = False
    clarification_prompt: Optional[str] = None
    ambiguity_candidates: List[str] = Field(default_factory=list)
    is_supported: bool = True
    unsupported_message: Optional[str] = None
    matched_synonym: Optional[str] = None
    evidence_provenance: Dict[str, Any] = Field(default_factory=dict)
