"""Focused unit and contract tests for Phase 25D.1: Semantic Model & Schema Contracts.

Exercises:
1. Dimension model defaults, field types, validation, and JSON serialization.
2. KPI model backward compatibility, dimension/filter declarations, and defaults.
3. SemanticResolutionResult defaults, confidence boundary validation (0.0-1.0), and provenance.
4. KPIResponse and SemanticResolveResponse API schemas serialization and defaults.
5. DimensionResponse schema validation.
6. Backward compatibility with runtime KPIOntology and SemanticResolver.
7. API endpoint response contract preservation on /api/v1/semantic/resolve and /api/v1/semantic/kpis.
"""

import pytest
from app.main import app
from app.rag.semantic.models import (
    KPI,
    BusinessDomain,
    Dimension,
    MetricUnit,
    SemanticResolutionResult,
)
from app.rag.semantic.ontology import semantic_resolver
from app.schemas.semantic import (
    DimensionResponse,
    KPIResponse,
    SemanticResolveResponse,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_dimension_model_defaults_and_contracts() -> None:
    """Verify Dimension model defaults and validation contracts."""
    # 1. Minimal instantiation with required fields only
    dim_min = Dimension(
        dimension_name="product",
        display_name="Product",
        source_table="products",
        column_name="id",
    )
    assert dim_min.dimension_name == "product"
    assert dim_min.display_name == "Product"
    assert dim_min.source_table == "products"
    assert dim_min.column_name == "id"
    assert dim_min.allowed_values is None
    assert dim_min.aliases == []
    assert dim_min.applicable_tools == []
    assert dim_min.filter_key is None
    assert dim_min.description == ""

    # 2. Full instantiation with all Phase 25D.1 fields
    dim_full = Dimension(
        dimension_name="category",
        display_name="Product Category",
        source_table="products",
        column_name="category",
        allowed_values=["Electronics", "Apparel", "Home"],
        aliases=["department", "merchandise group", "family"],
        applicable_tools=["get_category_breakdown", "run_variance_analysis"],
        filter_key="categories",
        description="Hierarchical merchandise classification department.",
    )
    assert dim_full.dimension_name == "category"
    assert len(dim_full.aliases) == 3
    assert "department" in dim_full.aliases
    assert dim_full.filter_key == "categories"
    assert len(dim_full.applicable_tools) == 2

    # 3. Serialization round-trip
    dumped = dim_full.model_dump()
    reconstructed = Dimension.model_validate(dumped)
    assert reconstructed == dim_full

    # 4. Validation error on missing required field
    with pytest.raises(ValidationError):
        Dimension(
            dimension_name="missing_fields",
            display_name="Incomplete",
            # missing source_table and column_name
        )


def test_kpi_model_defaults_and_contracts() -> None:
    """Verify KPI model backward compatibility and new schema fields."""
    # 1. Minimal legacy instantiation
    kpi_legacy = KPI(
        canonical_name="gross_sales",
        display_name="Gross Sales",
        description="Total unadjusted sales value before discounts.",
        analytics_tool="get_financial_summary",
        metric_field="gross_sales",
        calculation_reference="SUM(unit_price * quantity)",
        unit=MetricUnit.CURRENCY,
        business_domain=BusinessDomain.FINANCE,
    )
    assert kpi_legacy.canonical_name == "gross_sales"
    assert kpi_legacy.supported_dimensions == []
    assert kpi_legacy.supported_filters == []
    assert kpi_legacy.default_dimension is None
    assert kpi_legacy.status == "active"

    # 2. Full instantiation with dimension metadata
    kpi_enhanced = KPI(
        canonical_name="net_revenue",
        display_name="Net Revenue",
        description="Total revenue after discounts.",
        synonyms=["net sales", "revenue"],
        analytics_tool="get_financial_summary",
        metric_field="net_revenue",
        calculation_reference="gross_sales - discounts",
        unit=MetricUnit.CURRENCY,
        business_domain=BusinessDomain.FINANCE,
        supported_dimensions=["category", "product", "customer_segment", "time"],
        supported_filters=["categories", "product_ids", "customer_ids"],
        default_dimension="category",
    )
    assert len(kpi_enhanced.supported_dimensions) == 4
    assert "category" in kpi_enhanced.supported_dimensions
    assert kpi_enhanced.default_dimension == "category"
    assert "categories" in kpi_enhanced.supported_filters

    # 3. Serialization round-trip
    payload = kpi_enhanced.model_dump()
    restored = KPI.model_validate(payload)
    assert restored.supported_dimensions == kpi_enhanced.supported_dimensions
    assert restored.default_dimension == "category"


def test_semantic_resolution_result_defaults_and_validation() -> None:
    """Verify SemanticResolutionResult defaults, confidence bounds, and provenance."""
    # 1. Minimal instantiation
    res_min = SemanticResolutionResult(query="test query")
    assert res_min.query == "test query"
    assert res_min.confidence == 0.0
    assert res_min.resolved_dimensions == []
    assert res_min.extracted_filters == {}
    assert res_min.temporal_context is None
    assert res_min.evidence_provenance is None
    assert res_min.matched_dimension_aliases == {}

    # 2. Confidence boundary validation
    res_valid_low = SemanticResolutionResult(query="q", confidence=0.0)
    assert res_valid_low.confidence == 0.0

    res_valid_mid = SemanticResolutionResult(query="q", confidence=0.85)
    assert res_valid_mid.confidence == 0.85

    res_valid_high = SemanticResolutionResult(query="q", confidence=1.0)
    assert res_valid_high.confidence == 1.0

    with pytest.raises(ValidationError):
        SemanticResolutionResult(query="q", confidence=-0.01)

    with pytest.raises(ValidationError):
        SemanticResolutionResult(query="q", confidence=1.01)

    # 3. Full instantiation with enriched context
    prov = {
        "source_tables": ["sales", "sale_items"],
        "calculation_reference": "SUM(unit_price * quantity)",
        "accounting_rule": "GAAP Revenue Recognition ASC 606",
    }
    temp_ctx = {
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
        "granularity": "monthly",
    }
    res_full = SemanticResolutionResult(
        query="net revenue by category for electronics last month",
        canonical_name="net_revenue",
        analytics_tool="get_category_breakdown",
        metric_field="category_revenue",
        confidence=0.95,
        resolved_dimensions=["category"],
        extracted_filters={"categories": ["electronics"]},
        temporal_context=temp_ctx,
        evidence_provenance=prov,
        matched_dimension_aliases={"by category": "category"},
    )
    assert res_full.confidence == 0.95
    assert res_full.resolved_dimensions == ["category"]
    assert res_full.extracted_filters == {"categories": ["electronics"]}
    assert res_full.temporal_context["date_from"] == "2024-08-01"
    assert res_full.evidence_provenance["accounting_rule"] == "GAAP Revenue Recognition ASC 606"


def test_schema_models_api_contracts() -> None:
    """Verify KPIResponse, DimensionResponse, and SemanticResolveResponse API schemas."""
    # 1. KPIResponse
    kpi_resp = KPIResponse(
        canonical_name="cogs",
        display_name="Cost of Goods Sold",
        description="Direct inventory cost.",
        synonyms=["cost of goods sold"],
        analytics_tool="get_financial_summary",
        metric_field="cogs",
        calculation_reference="SUM(cost_price * quantity)",
        unit="currency",
        business_domain="finance",
        status="active",
        supported_dimensions=["category", "product"],
        supported_filters=["product_ids"],
        default_dimension="product",
    )
    assert kpi_resp.supported_dimensions == ["category", "product"]
    assert kpi_resp.default_dimension == "product"

    # 2. DimensionResponse
    dim_resp = DimensionResponse(
        dimension_name="customer_segment",
        display_name="Customer Segment",
        source_table="customers",
        column_name="segment",
        allowed_values=["VIP", "Regular", "Wholesale"],
        aliases=["tier", "customer tier"],
        applicable_tools=["get_customer_segments", "run_variance_analysis"],
        filter_key="customer_segment",
        description="Customer classification based on RFM score.",
    )
    assert dim_resp.dimension_name == "customer_segment"
    assert len(dim_resp.allowed_values) == 3

    # 3. SemanticResolveResponse
    resolve_resp = SemanticResolveResponse(
        query="show net sales by product",
        canonical_name="net_revenue",
        canonical_kpi="net_revenue",
        analytics_tool="get_product_rankings",
        metric_field="product_revenue",
        confidence=0.95,
        resolved_dimensions=["product"],
        extracted_filters={},
        temporal_context={"granularity": "monthly"},
        supported_dimensions=["category", "product"],
    )
    assert resolve_resp.confidence == 0.95
    assert resolve_resp.resolved_dimensions == ["product"]
    assert resolve_resp.supported_dimensions == ["category", "product"]


def test_backward_compatibility_with_runtime_ontology_and_resolver() -> None:
    """Verify that existing runtime ontology and resolver produce valid 25D.1 contracts."""
    res = semantic_resolver.resolve("What was our gross sales last month?")
    assert res.canonical_name == "gross_sales"
    assert res.analytics_tool == "get_financial_summary"
    # Ensure enriched fields are populated
    assert hasattr(res, "confidence")
    assert res.confidence == 1.0
    assert hasattr(res, "resolved_dimensions")
    assert hasattr(res, "extracted_filters")
    assert hasattr(res, "temporal_context")
    assert res.temporal_context is not None
    assert hasattr(res, "evidence_provenance")
    assert res.evidence_provenance is not None
    assert res.evidence_provenance["analytics_tool"] == "get_financial_summary"

    # Unresolved query produces clean defaults with confidence 0.0 and no false lineage
    unresolved = semantic_resolver.resolve("completely unknown business query")
    assert unresolved.confidence == 0.0
    assert unresolved.canonical_name is None
    assert unresolved.evidence_provenance is None
    assert unresolved.temporal_context is None


def test_api_endpoints_return_25d1_contract(client: TestClient | None = None) -> None:
    """Verify REST API endpoints serialize 25D.1 contract fields cleanly."""
    test_client = client or TestClient(app)

    # 1. Resolve endpoint
    resp = test_client.post("/api/v1/semantic/resolve", json={"query": "gross profit"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["canonical_name"] == "gross_profit"
    assert "confidence" in data
    assert data["confidence"] == 1.0
    assert "resolved_dimensions" in data
    assert isinstance(data["resolved_dimensions"], list)
    assert "extracted_filters" in data
    assert isinstance(data["extracted_filters"], dict)
    assert "supported_dimensions" in data

    # 2. Specific KPI endpoint
    resp_kpi = test_client.get("/api/v1/semantic/kpis/gross_profit")
    assert resp_kpi.status_code == 200
    kpi_data = resp_kpi.json()
    assert kpi_data["canonical_name"] == "gross_profit"
    assert "supported_dimensions" in kpi_data
    assert "supported_filters" in kpi_data
    assert "default_dimension" in kpi_data
