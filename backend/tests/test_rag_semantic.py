"""Tests for NEXUS Semantic Layer and KPI Ontology."""

from app.rag.semantic.models import KPI, BusinessDomain, MetricUnit
from app.rag.semantic.ontology import KPIOntology, SemanticResolver
from fastapi.testclient import TestClient


def test_kpi_registration_and_lookup():
    """Verify registration of canonical KPIs and domain indexing."""
    ontology = KPIOntology()
    kpi = KPI(
        canonical_name="test_metric",
        display_name="Test Metric",
        description="A test metric description",
        synonyms=["sample metric", "example kpi"],
        analytics_tool="get_financial_summary",
        metric_field="test_field",
        calculation_reference="SUM(test)",
        unit=MetricUnit.CURRENCY,
        business_domain=BusinessDomain.FINANCE,
    )
    ontology.register_kpi(kpi)

    retrieved = ontology.get_kpi("test_metric")
    assert retrieved is not None
    assert retrieved.display_name == "Test Metric"
    assert retrieved.unit == MetricUnit.CURRENCY

    # Verify domain filtering
    finance_kpis = ontology.list_kpis(domain=BusinessDomain.FINANCE)
    assert any(k.canonical_name == "test_metric" for k in finance_kpis)
    inventory_kpis = ontology.list_kpis(domain=BusinessDomain.INVENTORY)
    assert not any(k.canonical_name == "test_metric" for k in inventory_kpis)


def test_canonical_and_synonym_resolution():
    """Verify exact and synonym phrase resolution."""
    resolver = SemanticResolver()

    # Exact canonical phrase
    res = resolver.resolve("What was our gross sales last month?")
    assert res.is_supported is True
    assert res.is_ambiguous is False
    assert res.canonical_name == "gross_sales"
    assert res.analytics_tool == "get_financial_summary"

    # Known synonym
    res_syn = resolver.resolve("Show me net sales for Q2")
    assert res_syn.is_supported is True
    assert res_syn.is_ambiguous is False
    assert res_syn.canonical_name == "net_revenue"

    # Days sales inventory / DSI
    res_dsi = resolver.resolve("What is our dsi?")
    assert res_dsi.canonical_name == "days_sales_inventory"
    assert res_dsi.analytics_tool == "get_inventory_turnover"


def test_ambiguity_detection_and_disambiguation():
    """Verify ambiguous business terms trigger clarification unless qualified."""
    resolver = SemanticResolver()

    # Ambiguous: 'turnover' alone
    res_turnover = resolver.resolve("What is our turnover?")
    assert res_turnover.is_ambiguous is True
    assert res_turnover.clarification_prompt is not None
    assert "Net Revenue" in res_turnover.clarification_prompt
    assert "Inventory Turnover" in res_turnover.clarification_prompt
    assert len(res_turnover.candidate_kpis) == 2

    # Disambiguated by qualifier: 'inventory turnover'
    res_inv = resolver.resolve("What is our inventory turnover?")
    assert res_inv.is_ambiguous is False
    assert res_inv.canonical_name == "inventory_turnover"

    # Ambiguous: 'sales' alone
    res_sales = resolver.resolve("How are our sales?")
    assert res_sales.is_ambiguous is True
    assert "Gross Sales" in res_sales.clarification_prompt
    assert "Net Revenue" in res_sales.clarification_prompt

    # Disambiguated by qualifier: 'gross sales'
    res_gross = resolver.resolve("What are gross sales?")
    assert res_gross.is_ambiguous is False
    assert res_gross.canonical_name == "gross_sales"


def test_unsupported_metric_detection():
    """Verify explicitly unsupported metrics are rejected with helpful messaging."""
    resolver = SemanticResolver()

    res_clv = resolver.resolve("What is our customer lifetime value?")
    assert res_clv.is_supported is False
    assert "Customer Lifetime Value" in res_clv.unsupported_message

    res_churn = resolver.resolve("What is our churn rate?")
    assert res_clv.is_supported is False
    assert "Churn" in res_churn.unsupported_message

    res_cac = resolver.resolve("Calculate our CAC")
    assert res_cac.is_supported is False
    assert "Customer Acquisition Cost" in res_cac.unsupported_message


def test_case_and_punctuation_normalization():
    """Verify resolver is case-insensitive and strips punctuation."""
    resolver = SemanticResolver()

    res1 = resolver.resolve("NET REVENUE???")
    assert res1.canonical_name == "net_revenue"

    res2 = resolver.resolve("...average order value!,,")
    assert res2.canonical_name == "average_order_value"


def test_api_semantic_endpoints(api_client: TestClient):
    """Test REST API semantic endpoints."""
    # 1. Resolve endpoint
    resp = api_client.post("/api/v1/semantic/resolve", json={"query": "gross profit"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["canonical_name"] == "gross_profit"
    assert data["analytics_tool"] == "get_financial_summary"
    assert data["is_supported"] is True

    # 2. List all KPIs
    resp_kpis = api_client.get("/api/v1/semantic/kpis")
    assert resp_kpis.status_code == 200
    kpis = resp_kpis.json()
    assert len(kpis) >= 20

    # 3. Filter by domain
    resp_domain = api_client.get("/api/v1/semantic/kpis?domain=inventory")
    assert resp_domain.status_code == 200
    inv_kpis = resp_domain.json()
    assert all(k["business_domain"] == "inventory" for k in inv_kpis)

    # 4. Get specific KPI
    resp_single = api_client.get("/api/v1/semantic/kpis/cogs")
    assert resp_single.status_code == 200
    assert resp_single.json()["canonical_name"] == "cogs"

    # 5. Non-existent KPI 404
    resp_404 = api_client.get("/api/v1/semantic/kpis/non_existent_metric")
    assert resp_404.status_code == 404
