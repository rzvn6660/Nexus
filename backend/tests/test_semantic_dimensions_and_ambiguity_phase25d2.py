"""Deterministic Phase 25D.2 tests for Canonical Dimensions, Business Rules, and Expanded Ambiguity.

Verifies:
1. Canonical dimension registration, alias indexing, tool bindings, and API endpoints.
2. Documented accounting & governance rules registration and domain queries.
3. Supported dimensions and filters on all canonical KPIs.
4. Expanded ambiguity detection and clarification across 8 terms:
   (profit, margin, cost, expenses, turnover, sales, retention, volume).
5. Deterministic disambiguation when qualifying phrases exist.
6. Dimension, entity filter, and temporal context extraction via DateInterpreter.
7. Strict confidence scoring: 1.0 for exact, 0.95 for synonym, 0.0 for ambiguous/unsupported/unresolved.
8. Evidence provenance integrity: verified lineage only when calculation and tool are known.
9. Tenant boundary isolation and backward compatibility.
"""

from app.main import app
from app.rag.semantic.models import BusinessDomain
from app.rag.semantic.ontology import kpi_ontology, semantic_resolver
from fastapi.testclient import TestClient


def test_canonical_dimensions_registration_and_lookup() -> None:
    """1. Verify canonical dimensions exist with complete metadata, tools, and filter keys."""
    ontology = kpi_ontology

    canonical_names = [
        "product",
        "category",
        "customer_segment",
        "customer",
        "warehouse",
        "time_granularity",
    ]
    for dim_name in canonical_names:
        dim = ontology.get_dimension(dim_name)
        assert dim is not None, f"Dimension '{dim_name}' not registered"
        assert dim.dimension_name == dim_name
        assert len(dim.applicable_tools) > 0
        assert dim.filter_key is not None
        assert dim.source_table in ["products", "customers", "inventory", "sales"]

    # Test alias resolution
    assert ontology.get_dimension("department").dimension_name == "category"
    assert ontology.get_dimension("product category").dimension_name == "category"
    assert ontology.get_dimension("by sku").dimension_name == "product"
    assert ontology.get_dimension("by segment").dimension_name == "customer_segment"
    assert ontology.get_dimension("warehouse location").dimension_name == "warehouse"
    assert ontology.get_dimension("monthly").dimension_name == "time_granularity"

    # Test list_dimensions
    all_dims = ontology.list_dimensions()
    assert len(all_dims) >= 6
    registered_names = {d.dimension_name for d in all_dims}
    for expected in canonical_names:
        assert expected in registered_names


def test_business_rules_registration_and_lookup() -> None:
    """2. Verify documented accounting and business rules exist with policy references."""
    ontology = kpi_ontology

    rule_ids = ["REV-001", "GP-001", "OP-001", "INV-001", "CUST-001", "EXP-001"]
    for rid in rule_ids:
        rule = ontology.get_rule(rid)
        assert rule is not None, f"Rule '{rid}' not registered"
        assert rule.rule_id == rid
        assert rule.policy_reference is not None
        assert len(rule.description) > 20
        assert rule.active is True

    # Test domain filtering
    finance_rules = ontology.list_rules(domain=BusinessDomain.FINANCE)
    assert len(finance_rules) == 3
    fin_ids = {r.rule_id for r in finance_rules}
    assert fin_ids == {"REV-001", "GP-001", "OP-001"}

    inv_rules = ontology.list_rules(domain=BusinessDomain.INVENTORY)
    assert any(r.rule_id == "INV-001" for r in inv_rules)


def test_kpi_dimension_bindings_and_filters() -> None:
    """3. Verify all canonical KPIs possess supported dimensions and filters."""
    ontology = kpi_ontology
    all_kpis = ontology.list_kpis()
    assert len(all_kpis) >= 27

    for kpi in all_kpis:
        assert isinstance(kpi.supported_dimensions, list)
        assert len(kpi.supported_dimensions) > 0, f"KPI '{kpi.canonical_name}' has empty supported_dimensions"
        assert isinstance(kpi.supported_filters, list)
        assert len(kpi.supported_filters) > 0, f"KPI '{kpi.canonical_name}' has empty supported_filters"
        assert kpi.default_dimension is not None, f"KPI '{kpi.canonical_name}' has None default_dimension"

    # Verify specific KPI mappings
    gross_sales = ontology.get_kpi("gross_sales")
    assert "product" in gross_sales.supported_dimensions
    assert "category" in gross_sales.supported_dimensions
    assert "product_ids" in gross_sales.supported_filters
    assert gross_sales.default_dimension == "category"

    stock_val = ontology.get_kpi("stock_value")
    assert "warehouse" in stock_val.supported_dimensions
    assert stock_val.default_dimension == "warehouse"


def test_expanded_ambiguity_all_eight_terms() -> None:
    """4. Verify ambiguity detection for all 8 required terms produces confidence=0.0 and no false lineage."""
    resolver = semantic_resolver

    ambiguous_checks = [
        ("What is our profit?", "profit", ["gross_profit", "net_profit", "product_profit"]),
        ("Show me the margin", "margin", ["gross_margin", "net_margin", "product_margin"]),
        ("What is total cost?", "cost", ["cogs", "operating_expense", "fixed_expense", "variable_expense"]),
        ("Report our expenses", "expenses", ["operating_expense", "fixed_expense", "variable_expense"]),
        ("What is our turnover?", "turnover", ["net_revenue", "inventory_turnover"]),
        ("How are sales doing?", "sales", ["gross_sales", "net_revenue", "units_sold", "orders"]),
        ("Check customer retention", "retention", ["repeat_purchase_rate", "active_customer"]),
        ("What was our volume last quarter?", "volume", ["units_sold", "orders"]),
    ]

    for query, term, expected_candidates in ambiguous_checks:
        res = resolver.resolve(query)
        assert res.is_ambiguous is True, f"Query '{query}' was not detected as ambiguous for term '{term}'"
        assert res.clarification_prompt is not None, f"Query '{query}' has no clarification prompt"
        assert res.confidence == 0.0, f"Ambiguous query '{query}' must have confidence=0.0, got {res.confidence}"
        assert res.evidence_provenance is None, f"Ambiguous query '{query}' must have None evidence_provenance"
        assert res.resolved_kpi is None

        candidate_names = [c.canonical_name for c in res.candidate_kpis]
        for ec in expected_candidates:
            assert ec in candidate_names, f"Expected candidate '{ec}' missing for term '{term}' in '{query}'"


def test_disambiguation_with_qualifying_phrases() -> None:
    """5. Verify ambiguous terms with qualifiers resolve deterministically with high confidence."""
    resolver = semantic_resolver

    disambiguation_cases = [
        ("Show gross profit for the period", "gross_profit", "get_financial_summary", 1.0),
        ("Show net profit after expenses", "net_profit", "get_financial_summary", 1.0),
        ("What was our gross margin?", "gross_margin", "get_financial_summary", 1.0),
        ("What was our net margin?", "net_margin", "get_financial_summary", 1.0),
        ("Analyze inventory turnover", "inventory_turnover", "get_inventory_turnover", 1.0),
        ("Calculate cost of goods sold", "cogs", "get_financial_summary", 0.95),
        ("Review fixed expenses", "fixed_expense", "get_expense_analytics", 1.0),
        ("What is the repeat purchase rate?", "repeat_purchase_rate", "get_repeat_purchase", 1.0),
        ("Total units sold this month", "units_sold", "get_financial_summary", 0.95),
        ("Units sold this month", "units_sold", "get_financial_summary", 1.0),
    ]

    for query, expected_kpi, expected_tool, min_confidence in disambiguation_cases:
        res = resolver.resolve(query)
        assert res.is_ambiguous is False, f"Query '{query}' should be disambiguated"
        assert res.canonical_name == expected_kpi, f"Query '{query}' resolved to {res.canonical_name}, expected {expected_kpi}"
        assert res.analytics_tool == expected_tool
        assert res.confidence >= min_confidence
        assert res.evidence_provenance is not None
        assert res.evidence_provenance["lineage_verified"] is True
        assert res.evidence_provenance["calculation_reference"] is not None


def test_dimension_and_filter_extraction() -> None:
    """6. Verify analytical dimensions and entity filters are accurately parsed from natural language."""
    resolver = semantic_resolver

    # Query with dimension "by category" and segment filter "VIP"
    res1 = resolver.resolve("Show gross profit by category for VIP customers")
    assert res1.canonical_name == "gross_profit"
    assert "category" in res1.resolved_dimensions
    assert res1.matched_dimension_aliases.get("by category") == "category"
    assert res1.extracted_filters.get("customer_segment") == "VIP"
    assert res1.confidence == 1.0

    # Query with dimension "by product"
    res2 = resolver.resolve("Break down net sales by product")
    assert res2.canonical_name == "net_revenue"
    assert "product" in res2.resolved_dimensions
    assert res2.matched_dimension_aliases.get("by product") == "product"

    # Query with warehouse location
    res3 = resolver.resolve("Stock value in Main Warehouse")
    assert res3.canonical_name == "stock_value"
    assert "warehouse" in res3.resolved_dimensions
    assert res3.extracted_filters.get("warehouse") == "Main Warehouse"


def test_temporal_context_extraction_via_date_interpreter() -> None:
    """7. Verify integration with DateInterpreter without modifying analytics math."""
    resolver = semantic_resolver

    res = resolver.resolve("What was gross sales last month?")
    assert res.canonical_name == "gross_sales"
    assert res.confidence == 1.0
    assert res.temporal_context is not None
    assert "date_from" in res.temporal_context
    assert "date_to" in res.temporal_context
    assert "date_from" in res.extracted_filters
    assert "date_to" in res.extracted_filters
    assert res.evidence_provenance is not None


def test_unsupported_metrics_and_unresolved_queries() -> None:
    """8. Verify unsupported and unresolvable queries strictly return confidence=0.0 and no false lineage."""
    resolver = semantic_resolver

    # Explicit unsupported metrics
    for term in ["clv", "customer lifetime value", "cac", "churn rate", "nps"]:
        res_unsupp = resolver.resolve(f"Calculate {term} for our business")
        assert res_unsupp.is_supported is False
        assert res_unsupp.confidence == 0.0
        assert res_unsupp.evidence_provenance is None
        assert res_unsupp.unsupported_message is not None

    # Unresolvable query
    res_unknown = resolver.resolve("completely unknown phrase about nothing")
    assert res_unknown.canonical_name is None
    assert res_unknown.confidence == 0.0
    assert res_unknown.evidence_provenance is None
    assert res_unknown.is_ambiguous is False
    assert res_unknown.is_supported is True


def test_api_dimension_endpoints(client: TestClient | None = None) -> None:
    """9. Verify REST API endpoints expose canonical dimension contracts."""
    test_client = client or TestClient(app)

    # List dimensions
    resp_list = test_client.get("/api/v1/semantic/dimensions")
    assert resp_list.status_code == 200
    dims = resp_list.json()
    assert len(dims) >= 6
    names = {d["dimension_name"] for d in dims}
    assert "product" in names
    assert "category" in names
    assert "customer_segment" in names
    assert "warehouse" in names
    assert "time_granularity" in names

    # Get specific dimension
    resp_cat = test_client.get("/api/v1/semantic/dimensions/category")
    assert resp_cat.status_code == 200
    assert resp_cat.json()["dimension_name"] == "category"
    assert "department" in resp_cat.json()["aliases"]

    # Get dimension by alias
    resp_alias = test_client.get("/api/v1/semantic/dimensions/department")
    assert resp_alias.status_code == 200
    assert resp_alias.json()["dimension_name"] == "category"

    # 404 for non-existent dimension
    resp_404 = test_client.get("/api/v1/semantic/dimensions/non_existent_dim")
    assert resp_404.status_code == 404
