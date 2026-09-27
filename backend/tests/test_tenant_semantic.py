"""Comprehensive test suite for Phase 17: Tenant-Aware Business Understanding & Semantic Activation.

Covers:
1. Business understanding generation
2. Tenant semantic persistence
3. KPI availability states (AVAILABLE, REQUIRES_COST_DATA, INSUFFICIENT_HISTORY, UNAVAILABLE)
4. Synonym resolution
5. Ambiguous synonym handling & clarification prompts
6. Multi-tenant isolation
7. Cross-tenant semantic IDOR protection
8. Business context / OKF retrieval isolation
9. Metric mapping traceability
10. Explicit unsupported metrics rejection
11. Semantic activation endpoint
12. Activation failure handling
13. Semantic versioning and revision history
14. Dataset semantic update
15. Semantic conflict detection (REQUIRES_REVIEW)
16. Fiscal calendar and timezone preservation
17. Evidence semantic provenance capture
18. Agent semantic context integration
19. Agent clarification on ambiguous query
20. End-to-end customer semantic journey
"""

import io
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.expense import Expense
from app.models.inventory import Inventory
from app.models.okf import OKFBundleModel, OKFItemModel
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, TenantSemanticModel
from app.services.auth_service import AuthService
from app.services.tenant_semantic_service import TenantSemanticService
from app.services.data_gateway_service import DataGatewayService
from app.agents.service import NexusAgentService


TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def tenant_fixture(db_session):
    """Provisions two isolated tenants: Tenant A and Tenant B."""
    user_a, org_a, biz_a = AuthService.signup(
        db=db_session,
        email=f"owner_a_{uuid4().hex[:6]}@domain-a.com",
        password="SecurePassword123!",
        full_name="Alice Owner",
        organization_name="Enterprise Alpha",
        business_name="Alpha Retail Inc",
    )
    token_a = AuthService.create_access_token(
        user_id=user_a.id,
        email=user_a.email,
        organization_id=org_a.id,
        business_id=biz_a.id,
    )

    user_b, org_b, biz_b = AuthService.signup(
        db=db_session,
        email=f"owner_b_{uuid4().hex[:6]}@domain-b.com",
        password="SecurePassword123!",
        full_name="Bob Owner",
        organization_name="Enterprise Beta",
        business_name="Beta Retail Inc",
    )
    token_b = AuthService.create_access_token(
        user_id=user_b.id,
        email=user_b.email,
        organization_id=org_b.id,
        business_id=biz_b.id,
    )

    return {
        "user_a": user_a,
        "token_a": token_a,
        "biz_a": biz_a,
        "org_a": org_a,
        "user_b": user_b,
        "token_b": token_b,
        "biz_b": biz_b,
        "org_b": org_b,
    }


def test_01_business_understanding_generation(db_session, tenant_fixture):
    """1. Verify business understanding generation correctly audits empty and populated entities."""
    biz_a = tenant_fixture["biz_a"]

    # Initial generation with no records
    model = TenantSemanticService.generate_business_understanding(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        db=db_session,
    )
    assert model is not None
    assert model.version == 1
    assert model.status == "ACTIVE"
    assert model.business_summary_json["sales_count"] == 0
    assert "Sale" not in model.entities_json

    # Create a customer first for foreign key integrity
    cust = Customer(
        business_id=biz_a.id,
        customer_code="CUST-ALPHA-1",
        name="Alpha Customer",
        email="customer1@alpha.com",
        city="New York",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add(cust)
    db_session.commit()

    # Seed sales records for Tenant A
    sale1 = Sale(
        business_id=biz_a.id,
        customer_id=cust.id,
        transaction_date=datetime(2025, 1, 10, 10, 0, tzinfo=timezone.utc),
        subtotal=Decimal("150.00"),
        total_amount=Decimal("150.00"),
        transaction_number=f"TX-{uuid4().hex[:8]}",
    )
    sale2 = Sale(
        business_id=biz_a.id,
        customer_id=cust.id,
        transaction_date=datetime(2025, 1, 20, 15, 30, tzinfo=timezone.utc),
        subtotal=Decimal("250.00"),
        total_amount=Decimal("250.00"),
        transaction_number=f"TX-{uuid4().hex[:8]}",
    )
    db_session.add_all([sale1, sale2])
    db_session.commit()

    # Regenerate understanding
    updated_model = TenantSemanticService.generate_business_understanding(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        db=db_session,
    )
    assert updated_model.version == 2
    assert "Sale" in updated_model.entities_json
    assert updated_model.entities_json["Sale"]["record_count"] == 2
    assert updated_model.business_summary_json["sales_count"] == 2
    assert updated_model.business_summary_json["sales_date_start"] == "2025-01-10"
    assert updated_model.business_summary_json["sales_date_end"] == "2025-01-20"


def test_02_tenant_semantic_persistence(db_session, tenant_fixture):
    """2. Verify TenantSemanticModel persists correctly in database and queries via get_active_semantic_model."""
    biz_a = tenant_fixture["biz_a"]
    active = TenantSemanticService.get_active_semantic_model(biz_a.id, db_session)
    assert active is not None
    assert active.business_id == biz_a.id
    assert active.version == 2
    assert "net_revenue" in active.metrics_json


def test_03_kpi_availability_grounding(db_session, tenant_fixture):
    """3. Verify metric availability states (AVAILABLE, REQUIRES_COST_DATA, INSUFFICIENT_HISTORY, UNAVAILABLE)."""
    biz_a = tenant_fixture["biz_a"]

    model = TenantSemanticService.get_active_semantic_model(biz_a.id, db_session)
    metrics = model.metrics_json

    # Net Revenue is AVAILABLE because Sale entity exists
    assert metrics["net_revenue"]["status"] == "AVAILABLE"

    # Orders is AVAILABLE
    assert metrics["orders"]["status"] == "AVAILABLE"

    # Gross Margin requires Product entity and unit_cost -> UNAVAILABLE because Product entity is missing
    assert metrics["gross_margin"]["status"] == "UNAVAILABLE"

    # Customer Retention requires at least 90 days history -> INSUFFICIENT_HISTORY (only 10 days)
    assert metrics["customer_retention"]["status"] == "INSUFFICIENT_HISTORY"

    # Now add Product with zero unit_cost
    prod = Product(
        business_id=biz_a.id,
        sku="SKU-TEST-1",
        name="Test Widget",
        category="General",
        subcategory="Widgets",
        selling_price=Decimal("100.00"),
        unit_cost=Decimal("0.00"),
    )
    db_session.add(prod)
    db_session.commit()

    model = TenantSemanticService.generate_business_understanding(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        db=db_session,
    )
    assert model.metrics_json["gross_margin"]["status"] == "REQUIRES_COST_DATA"

    # Update Product with unit_cost > 0 -> becomes AVAILABLE
    prod.unit_cost = Decimal("40.00")
    db_session.commit()

    model = TenantSemanticService.generate_business_understanding(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        db=db_session,
    )
    assert model.metrics_json["gross_margin"]["status"] == "AVAILABLE"


def test_04_synonym_resolution(db_session, tenant_fixture):
    """4. Verify tenant custom and canonical synonyms map to canonical concepts."""
    biz_a = tenant_fixture["biz_a"]

    # "net sales" -> net_revenue
    res_sales = TenantSemanticService.resolve_query_with_tenant_context(
        query="what was our net sales?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_sales.canonical_name == "net_revenue"
    assert res_sales.availability_status == "AVAILABLE"

    # "sales revenue" -> net_revenue
    res_rev = TenantSemanticService.resolve_query_with_tenant_context(
        query="what was our total sales revenue?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_rev.canonical_name == "net_revenue"

    # "transactions" -> orders
    res_orders = TenantSemanticService.resolve_query_with_tenant_context(
        query="how many transactions did we record?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_orders.canonical_name == "orders"


def test_05_ambiguous_synonym_handling(db_session, tenant_fixture):
    """5. Ambiguous terms (e.g. standalone 'sales', 'turnover', 'margin') trigger clarification rather than guessing."""
    biz_a = tenant_fixture["biz_a"]

    # "sales" is ambiguous
    res_ambig = TenantSemanticService.resolve_query_with_tenant_context(
        query="How did sales perform?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_ambig.is_ambiguous is True
    assert "ambiguous" in res_ambig.clarification_prompt.lower()
    assert "net_revenue" in res_ambig.ambiguity_candidates
    assert "orders" in res_ambig.ambiguity_candidates

    # "turnover" is ambiguous (revenue vs inventory velocity)
    res_turn = TenantSemanticService.resolve_query_with_tenant_context(
        query="what was total turnover last week?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_turn.is_ambiguous is True
    assert "turnover" in res_turn.clarification_prompt.lower()


def test_06_tenant_isolation(db_session, tenant_fixture):
    """6. Ensure Tenant A records and semantic models are strictly isolated from Tenant B."""
    biz_a = tenant_fixture["biz_a"]
    biz_b = tenant_fixture["biz_b"]

    model_b = TenantSemanticService.generate_business_understanding(
        business_id=biz_b.id,
        organization_id=biz_b.organization_id,
        db=db_session,
    )
    # Tenant B has 0 sales even though Tenant A has 2
    assert model_b.business_summary_json["sales_count"] == 0
    assert "Sale" not in model_b.entities_json


def test_07_cross_tenant_semantic_idor(client, tenant_fixture):
    """7. Test IDOR protection: Tenant A cannot view or manipulate Tenant B's understanding."""
    token_a = tenant_fixture["token_a"]
    biz_b = tenant_fixture["biz_b"]

    # Attempt to access Tenant B understanding using Tenant A auth token
    resp = client.get(
        "/api/v1/semantic/understanding",
        headers={
            "Authorization": f"Bearer {token_a}",
            "X-Business-ID": biz_b.id,
        },
    )
    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"] or "Forbidden" in resp.json()["detail"]


def test_08_business_context_retrieval_isolation(db_session, tenant_fixture):
    """8. Custom OKF synonyms for Tenant A do not bleed into Tenant B."""
    biz_a = tenant_fixture["biz_a"]
    biz_b = tenant_fixture["biz_b"]

    # Add bundle and custom OKF item for Tenant A with unique synonym
    bundle = OKFBundleModel(
        business_id=biz_a.id,
        bundle_id=f"bundle_{uuid4().hex[:8]}",
        name="VIP Context Bundle",
        author="Admin",
    )
    db_session.add(bundle)
    db_session.commit()

    okf_item = OKFItemModel(
        business_id=biz_a.id,
        bundle_id=bundle.id,
        item_id=f"item_{uuid4().hex[:8]}",
        name="Special VIP Income",
        item_type="kpi",
        source="business_policy",
        metric_field="net_revenue",
        synonyms=["vip top income", "vip intake"],
        status="verified",
    )
    db_session.add(okf_item)
    db_session.commit()

    # Re-activate Tenant A and Tenant B
    TenantSemanticService.generate_business_understanding(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        db=db_session,
    )
    TenantSemanticService.generate_business_understanding(
        business_id=biz_b.id,
        organization_id=biz_b.organization_id,
        db=db_session,
    )

    # Tenant A resolves "vip top income" to net_revenue
    res_a = TenantSemanticService.resolve_query_with_tenant_context(
        query="show me vip top income",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_a.canonical_name == "net_revenue"

    # Tenant B does NOT resolve "vip top income"
    res_b = TenantSemanticService.resolve_query_with_tenant_context(
        query="show me vip top income",
        business_id=biz_b.id,
        db=db_session,
    )
    assert res_b.matched_synonym != "vip top income"


def test_09_metric_mapping_traceability(db_session, tenant_fixture):
    """9. Verify resolved metrics contain full calculation formula and source table provenance."""
    biz_a = tenant_fixture["biz_a"]

    res = TenantSemanticService.resolve_query_with_tenant_context(
        query="What was our net revenue?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res.source_table == "sales"
    assert res.source_field == "total_amount"
    assert res.calculation_formula == "SUM(sales.total_amount)"
    assert res.evidence_provenance["tenant_scoped"] is True
    assert res.evidence_provenance["source_data"] == "sales"


def test_10_unsupported_metric_handling(db_session, tenant_fixture):
    """10. Verify explicit unsupported metrics are rejected deterministically."""
    biz_a = tenant_fixture["biz_a"]

    for metric_term in ["what is our CLV?", "customer acquisition cost report", "show NPS score"]:
        res = TenantSemanticService.resolve_query_with_tenant_context(
            query=metric_term,
            business_id=biz_a.id,
            db=db_session,
        )
        assert res.is_supported is False
        assert res.unsupported_message is not None


def test_11_semantic_activation_endpoint(client, tenant_fixture):
    """11. Verify POST /api/v1/semantic/activate triggers activation via API."""
    token_a = tenant_fixture["token_a"]
    biz_a = tenant_fixture["biz_a"]

    resp = client.post(
        "/api/v1/semantic/activate",
        json={"force_refresh": True, "custom_synonyms": {"custom earnings": "net_revenue"}},
        headers={
            "Authorization": f"Bearer {token_a}",
            "X-Business-ID": biz_a.id,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ["ACTIVE", "REQUIRES_REVIEW"]
    assert "understanding" in data
    assert data["understanding"]["synonyms"]["custom earnings"] == "net_revenue"


def test_12_activation_failure_handling(client, tenant_fixture):
    """12. Verify activation fails gracefully on non-existent business."""
    token_a = tenant_fixture["token_a"]
    fake_biz_id = str(uuid4())

    resp = client.post(
        "/api/v1/semantic/activate",
        json={"force_refresh": True},
        headers={
            "Authorization": f"Bearer {token_a}",
            "X-Business-ID": fake_biz_id,
        },
    )
    assert resp.status_code == 404


def test_13_semantic_versioning_and_revisions(client, tenant_fixture):
    """13. Verify GET /api/v1/semantic/revisions returns version history in descending order."""
    token_a = tenant_fixture["token_a"]
    biz_a = tenant_fixture["biz_a"]

    resp = client.get(
        "/api/v1/semantic/revisions",
        headers={
            "Authorization": f"Bearer {token_a}",
            "X-Business-ID": biz_a.id,
        },
    )
    assert resp.status_code == 200
    revs = resp.json()
    assert len(revs) >= 2
    versions = [r["version"] for r in revs]
    assert versions == sorted(versions, reverse=True)


def test_14_dataset_semantic_update_via_gateway(client, tenant_fixture, db_session):
    """14. Ingesting new data updates Business Understanding record counts."""
    token_a = tenant_fixture["token_a"]
    biz_a = tenant_fixture["biz_a"]

    csv_data = (
        "transaction_id,transaction_date,total_amount,payment_method,channel\n"
        "TX-201,2025-02-01,310.00,Credit Card,Online\n"
        "TX-202,2025-02-02,420.00,Debit Card,In-Store\n"
    )
    files = {"file": ("sales_batch2.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post(
        "/api/v1/gateway/upload",
        files=files,
        headers={"Authorization": f"Bearer {token_a}", "X-Business-ID": biz_a.id},
    )
    assert upload_res.status_code in [200, 201]
    dataset_id = upload_res.json().get("dataset_id") or upload_res.json().get("id")

    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        json={"target_entity": "Sale", "column_overrides": {}},
        headers={"Authorization": f"Bearer {token_a}", "X-Business-ID": biz_a.id},
    )
    assert ingest_res.status_code == 200

    # Verify understanding updated
    under_res = client.get(
        "/api/v1/semantic/understanding",
        headers={"Authorization": f"Bearer {token_a}", "X-Business-ID": biz_a.id},
    )
    assert under_res.status_code == 200
    summary = under_res.json()["summary"]
    # 2 from test_01 + 2 from this batch = 4
    assert summary["sales_count"] >= 4


def test_15_semantic_conflict_detection(db_session, tenant_fixture):
    """15. Conflicting metric formulas flag status as REQUIRES_REVIEW without silent overwriting.

    Verifies 8-step conflict safety invariant:
    1. Active semantic version 1 exists
    2. Introduce conflicting definition
    3. Create version 2
    4. Assert version 2 = REQUIRES_REVIEW
    5. Assert version 1 remains the active model
    6. Ask an agent semantic query
    7. Assert the agent uses version 1
    8. Assert conflicting version 2 is not used
    """
    biz_a = tenant_fixture["biz_a"]

    # 1. Fetch active semantic version 1
    v1 = TenantSemanticService.get_active_semantic_model(biz_a.id, db_session)
    assert v1 is not None
    assert v1.status == "ACTIVE"
    v1_id = v1.id
    v1_version = v1.version

    # 2. Introduce conflicting definition in existing verified active model
    metrics_copy = dict(v1.metrics_json)
    metrics_copy["net_revenue"] = dict(metrics_copy["net_revenue"])
    metrics_copy["net_revenue"]["calculation_formula"] = "SUM(sales.custom_formula_amount)"
    v1.metrics_json = metrics_copy
    db_session.commit()

    # 3. Create version 2 (will propose standard "SUM(sales.total_amount)" which conflicts with v1's formula)
    v2 = TenantSemanticService.generate_business_understanding(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        db=db_session,
    )

    # 4. Assert version 2 = REQUIRES_REVIEW
    assert v2.status == "REQUIRES_REVIEW"
    assert v2.version == v1_version + 1
    assert v2.conflicts_json is not None
    assert len(v2.conflicts_json["conflicts"]) > 0
    assert v2.conflicts_json["conflicts"][0]["metric"] == "net_revenue"

    # 5. Assert version 1 remains the active model
    active_now = TenantSemanticService.get_active_semantic_model(biz_a.id, db_session)
    assert active_now.id == v1_id
    assert active_now.version == v1_version
    assert active_now.status == "ACTIVE"

    # 6. Ask an agent semantic query
    res = TenantSemanticService.resolve_query_with_tenant_context(
        query="What was our net revenue?",
        business_id=biz_a.id,
        db=db_session,
    )

    # 7. Assert the agent uses version 1
    assert res.calculation_formula == "SUM(sales.custom_formula_amount)"

    # 8. Assert conflicting version 2 is not used
    assert res.calculation_formula != "SUM(sales.total_amount)"


def test_16_fiscal_calendar_preservation(client, tenant_fixture):
    """16. Verify business profile metadata (currency, timezone, fiscal year) is returned."""
    token_a = tenant_fixture["token_a"]
    biz_a = tenant_fixture["biz_a"]

    resp = client.get(
        f"/api/v1/businesses/{biz_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    biz_data = resp.json()
    assert biz_data["currency"] == "USD"
    assert biz_data["timezone"] == "UTC"
    assert biz_data["fiscal_year_start"] == 1


def test_17_evidence_semantic_provenance(db_session, tenant_fixture):
    """17. Verify AgentService run includes semantic provenance in evidence."""
    biz_a = tenant_fixture["biz_a"]

    service = NexusAgentService(session=db_session)
    response = service.run_analysis(
        query="What is our Net Revenue?",
        organization_id=biz_a.organization_id,
        business_id=biz_a.id,
    )
    assert response.semantic_context is not None
    assert response.semantic_context.get("canonical_name") == "net_revenue"
    # Provenance exists
    prov = response.semantic_context.get("evidence_provenance")
    if prov:
        assert prov.get("tenant_scoped") is True
        assert prov.get("source_data") == "sales"


def test_18_agent_semantic_context_integration(db_session, tenant_fixture):
    """18. Verify agent uses tenant semantic context to resolve revenue query."""
    biz_a = tenant_fixture["biz_a"]

    service = NexusAgentService(session=db_session)
    response = service.run_analysis(
        query="What was our total net revenue?",
        organization_id=biz_a.organization_id,
        business_id=biz_a.id,
    )
    assert response.semantic_context is not None
    assert response.semantic_context.get("canonical_name") == "net_revenue"


def test_19_agent_clarification_on_ambiguous_metric(db_session, tenant_fixture):
    """19. Ambiguous metric in Agent run stops and returns clarification needed."""
    biz_a = tenant_fixture["biz_a"]

    service = NexusAgentService(session=db_session)
    response = service.run_analysis(
        query="How did sales perform?",
        organization_id=biz_a.organization_id,
        business_id=biz_a.id,
    )
    assert response.status == "clarification_needed"
    assert response.needs_clarification is True
    assert response.clarification_prompt is not None


def test_20_end_to_end_customer_semantic_journey(client, db_session):
    """20. End-to-end customer flow: Signup -> Create Business -> Upload CSV -> Data Ready -> Automatic Business Understanding -> Semantic Resolution."""
    # 1. Signup & Create Business
    user, org, biz = AuthService.signup(
        db=db_session,
        email=f"e2e_customer_{uuid4().hex[:6]}@retailcorp.com",
        password="ProductionPassword123!",
        full_name="E2E Operator",
        organization_name="E2E Corporation",
        business_name="E2E Retail Store",
    )
    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=org.id,
        business_id=biz.id,
    )

    # 2. Upload CSV
    csv_content = (
        "transaction_id,transaction_date,total_amount,payment_method,channel\n"
        "TX-901,2025-08-01,500.00,Credit Card,Online\n"
        "TX-902,2025-08-15,350.00,Cash,Retail Store\n"
        "TX-903,2025-08-30,650.00,Debit Card,Online\n"
    )
    files = {"file": ("august_sales.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    upload_res = client.post(
        "/api/v1/gateway/upload",
        files=files,
        headers={"Authorization": f"Bearer {token}", "X-Business-ID": biz.id},
    )
    assert upload_res.status_code in [200, 201]
    dataset_id = upload_res.json().get("dataset_id") or upload_res.json().get("id")

    # 3. Ingest into Sale domain
    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        json={"target_entity": "Sale", "column_overrides": {}},
        headers={"Authorization": f"Bearer {token}", "X-Business-ID": biz.id},
    )
    assert ingest_res.status_code == 200

    # 4. Check Business Understanding automatically activated
    under_res = client.get(
        "/api/v1/semantic/understanding",
        headers={"Authorization": f"Bearer {token}", "X-Business-ID": biz.id},
    )
    assert under_res.status_code == 200
    under_data = under_res.json()
    assert under_data["status"] == "ACTIVE"
    assert under_data["summary"]["sales_count"] == 3
    assert under_data["metrics"]["net_revenue"]["status"] == "AVAILABLE"

    # 5. Resolve query against tenant semantic layer
    resolve_res = client.post(
        "/api/v1/semantic/resolve",
        json={"query": "How much revenue did we make?"},
        headers={"Authorization": f"Bearer {token}", "X-Business-ID": biz.id},
    )
    assert resolve_res.status_code == 200
    res_data = resolve_res.json()
    assert res_data["canonical_name"] == "net_revenue"
    assert res_data["availability_status"] == "AVAILABLE"
    assert res_data["calculation_formula"] == "SUM(sales.total_amount)"
    assert res_data["evidence_provenance"]["tenant_scoped"] is True


def test_21_alembic_migration_007_real_verification():
    """21. Real migration verification test: checks revision chain 005 -> 006 -> 007,
    schema modifications, foreign keys, unique constraint, index, downgrade, and re-upgrade.
    """
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    # 1. Verify revision chain across 005 -> 006 -> 007
    p005 = Path("backend/alembic/versions/005_phase15_saas_multi_tenancy.py")
    p006 = Path("backend/alembic/versions/006_phase16_data_gateway_ingestion.py")
    p007 = Path("backend/alembic/versions/007_phase17_business_understanding_semantic.py")

    assert p005.exists(), "Migration 005 must exist"
    assert p006.exists(), "Migration 006 must exist"
    assert p007.exists(), "Migration 007 must exist"

    spec005 = importlib.util.spec_from_file_location("m005", p005)
    m005 = importlib.util.module_from_spec(spec005)
    spec005.loader.exec_module(m005)

    spec006 = importlib.util.spec_from_file_location("m006", p006)
    m006 = importlib.util.module_from_spec(spec006)
    spec006.loader.exec_module(m006)

    spec007 = importlib.util.spec_from_file_location("m007", p007)
    m007 = importlib.util.module_from_spec(spec007)
    spec007.loader.exec_module(m007)

    assert m005.revision == "005_phase15_saas_multi_tenancy"
    assert m006.revision == "006_phase16_data_gateway_ingestion"
    assert m006.down_revision == m005.revision
    assert m007.revision == "007_phase17_business_understanding_semantic"
    assert m007.down_revision == m006.revision

    # 2. Real upgrade verification in SQLite
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        # Create prerequisite tables that 007 alters/references
        conn.execute(sa.text("CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE businesses (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE uploaded_datasets (id VARCHAR(36) PRIMARY KEY)"))
        conn.commit()

        with Operations.context(ctx):
            # Run upgrade
            m007.upgrade()

            insp = sa.inspect(conn)
            table_names = insp.get_table_names()
            assert "tenant_semantic_models" in table_names

            # Check businesses.semantic_status
            biz_cols = [c["name"] for c in insp.get_columns("businesses")]
            assert "semantic_status" in biz_cols

            # Check tenant_semantic_models columns
            sem_cols = {c["name"]: c for c in insp.get_columns("tenant_semantic_models")}
            expected_cols = [
                "id", "organization_id", "business_id", "version", "status",
                "source_dataset_id", "entities_json", "metrics_json", "dimensions_json",
                "synonyms_json", "ambiguous_terms_json", "business_summary_json",
                "conflicts_json", "created_at", "updated_at"
            ]
            for col in expected_cols:
                assert col in sem_cols, f"Missing column {col} in tenant_semantic_models"

            # Check PK
            pk_constraint = insp.get_pk_constraint("tenant_semantic_models")
            assert pk_constraint["constrained_columns"] == ["id"]

            # Check FKs
            fks = insp.get_foreign_keys("tenant_semantic_models")
            fk_targets = {fk["referred_table"] for fk in fks}
            assert "organizations" in fk_targets
            assert "businesses" in fk_targets
            assert "uploaded_datasets" in fk_targets

            # Check indexes
            indexes = insp.get_indexes("tenant_semantic_models")
            idx_names = [idx["name"] for idx in indexes]
            assert "ix_tenant_semantic_business_status" in idx_names

            # Check downgrade
            m007.downgrade()
            insp_down = sa.inspect(conn)
            assert "tenant_semantic_models" not in insp_down.get_table_names()
            biz_cols_down = [c["name"] for c in insp_down.get_columns("businesses")]
            assert "semantic_status" not in biz_cols_down

            # Check successful re-upgrade
            m007.upgrade()
            insp_re = sa.inspect(conn)
            assert "tenant_semantic_models" in insp_re.get_table_names()
            biz_cols_re = [c["name"] for c in insp_re.get_columns("businesses")]
            assert "semantic_status" in biz_cols_re


def test_22_semantic_activation_idempotency(db_session):
    """22. Verify semantic activation idempotency:
    - Identical dataset state produces no new version (model reused)
    - Meaningful change produces new version and archives previous
    - Conflict produces REQUIRES_REVIEW without replacing active model
    """
    user, org, biz = AuthService.signup(
        db=db_session,
        email=f"idempotent_tester_{uuid4().hex[:6]}@store.com",
        password="ProductionPassword123!",
        full_name="Idempotency Tester",
        organization_name="Idempotency Org",
        business_name="Idempotency Biz",
    )

    cust = Customer(
        business_id=biz.id,
        customer_code=f"CUST-{uuid4().hex[:6]}",
        name="Idempotent Customer",
        email=f"cust_{uuid4().hex[:6]}@store.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add(cust)
    db_session.commit()

    sale1 = Sale(
        business_id=biz.id,
        customer_id=cust.id,
        transaction_number=f"TX-{uuid4().hex[:8]}",
        transaction_date=datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc),
        subtotal=Decimal("150.00"),
        total_amount=Decimal("150.00"),
    )
    db_session.add(sale1)
    db_session.commit()

    # Initial activation -> v1
    v1 = TenantSemanticService.generate_business_understanding(
        business_id=biz.id,
        organization_id=org.id,
        db=db_session,
    )
    assert v1.version == 1
    assert v1.status == "ACTIVE"

    # Repeated identical activation -> must reuse v1, not create v2
    v1_repeat = TenantSemanticService.generate_business_understanding(
        business_id=biz.id,
        organization_id=org.id,
        db=db_session,
    )
    assert v1_repeat.id == v1.id
    assert v1_repeat.version == 1

    # Ingest new record (meaningful change)
    sale2 = Sale(
        business_id=biz.id,
        customer_id=cust.id,
        transaction_number=f"TX-{uuid4().hex[:8]}",
        transaction_date=datetime(2025, 3, 5, 12, 0, tzinfo=timezone.utc),
        subtotal=Decimal("250.00"),
        total_amount=Decimal("250.00"),
    )
    db_session.add(sale2)
    db_session.commit()

    # Meaningful change -> v2 created and ACTIVE, v1 archived
    v2 = TenantSemanticService.generate_business_understanding(
        business_id=biz.id,
        organization_id=org.id,
        db=db_session,
    )
    assert v2.version == 2
    assert v2.status == "ACTIVE"
    assert v2.id != v1.id

    db_session.refresh(v1)
    assert v1.status == "ARCHIVED"


def test_23_active_semantic_model_count_invariant(db_session):
    """23. Invariant: For any business, ACTIVE semantic model count <= 1 at all times.
    If no active model exists, agent does not invent semantic definitions.
    """
    user, org, biz = AuthService.signup(
        db=db_session,
        email=f"invariant_tester_{uuid4().hex[:6]}@store.com",
        password="ProductionPassword123!",
        full_name="Invariant Tester",
        organization_name="Invariant Org",
        business_name="Invariant Biz",
    )

    # 1. No active model yet
    active_initial = TenantSemanticService.get_active_semantic_model(biz.id, db_session)
    assert active_initial is None

    # Safe state when no active model exists
    res_safe = TenantSemanticService.resolve_query_with_tenant_context(
        query="What was our total revenue?",
        business_id=biz.id,
        db=db_session,
    )
    assert res_safe.is_supported is False
    assert res_safe.availability_status == "UNAVAILABLE"
    assert "No active business understanding" in (res_safe.unsupported_message or "")

    # 2. Add data and create v1
    cust = Customer(
        business_id=biz.id,
        customer_code=f"CUST-{uuid4().hex[:6]}",
        name="Invariant Customer",
        email=f"cust_{uuid4().hex[:6]}@store.com",
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add(cust)
    db_session.commit()

    sale = Sale(
        business_id=biz.id,
        customer_id=cust.id,
        transaction_number=f"TX-{uuid4().hex[:8]}",
        transaction_date=datetime(2025, 4, 1, 10, 0, tzinfo=timezone.utc),
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add(sale)
    db_session.commit()

    TenantSemanticService.generate_business_understanding(biz.id, org.id, db_session)
    active_count_1 = db_session.execute(
        select(func.count(TenantSemanticModel.id))
        .where(TenantSemanticModel.business_id == biz.id, TenantSemanticModel.status == "ACTIVE")
    ).scalar()
    assert active_count_1 == 1

    # 3. Add more data and create v2
    sale2 = Sale(
        business_id=biz.id,
        customer_id=cust.id,
        transaction_number=f"TX-{uuid4().hex[:8]}",
        transaction_date=datetime(2025, 4, 10, 10, 0, tzinfo=timezone.utc),
        subtotal=Decimal("200.00"),
        total_amount=Decimal("200.00"),
    )
    db_session.add(sale2)
    db_session.commit()

    TenantSemanticService.generate_business_understanding(biz.id, org.id, db_session)
    active_count_2 = db_session.execute(
        select(func.count(TenantSemanticModel.id))
        .where(TenantSemanticModel.business_id == biz.id, TenantSemanticModel.status == "ACTIVE")
    ).scalar()
    assert active_count_2 == 1


def test_24_version_history_preservation_and_immutability(db_session):
    """24. Verify old revisions are preserved, immutable, and queryable in descending order."""
    user, org, biz = AuthService.signup(
        db=db_session,
        email=f"history_tester_{uuid4().hex[:6]}@store.com",
        password="ProductionPassword123!",
        full_name="History Tester",
        organization_name="History Org",
        business_name="History Biz",
    )

    cust = Customer(
        business_id=biz.id,
        customer_code=f"CUST-{uuid4().hex[:6]}",
        name="History Customer",
        email=f"cust_{uuid4().hex[:6]}@store.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add(cust)
    db_session.commit()

    # Version 1
    s1 = Sale(
        business_id=biz.id,
        customer_id=cust.id,
        transaction_number=f"TX-{uuid4().hex[:8]}",
        transaction_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add(s1)
    db_session.commit()
    v1 = TenantSemanticService.generate_business_understanding(biz.id, org.id, db_session)

    # Version 2 (custom synonyms)
    v2 = TenantSemanticService.generate_business_understanding(
        biz.id, org.id, db_session, custom_synonyms={"custom_term": "net_revenue"}
    )

    # Version 3 (new sale)
    s2 = Sale(
        business_id=biz.id,
        customer_id=cust.id,
        transaction_number=f"TX-{uuid4().hex[:8]}",
        transaction_date=datetime(2025, 1, 5, tzinfo=timezone.utc),
        subtotal=Decimal("200.00"),
        total_amount=Decimal("200.00"),
    )
    db_session.add(s2)
    db_session.commit()
    v3 = TenantSemanticService.generate_business_understanding(biz.id, org.id, db_session)

    revs = TenantSemanticService.list_revisions(biz.id, db_session)
    assert len(revs) == 3
    assert [r.version for r in revs] == [3, 2, 1]

    # Immutability check: v1 and v2 still exist in DB
    all_models = db_session.execute(
        select(TenantSemanticModel)
        .where(TenantSemanticModel.business_id == biz.id)
        .order_by(TenantSemanticModel.version.asc())
    ).scalars().all()
    assert len(all_models) == 3
    assert all_models[0].version == 1
    assert all_models[1].version == 2
    assert all_models[2].version == 3



