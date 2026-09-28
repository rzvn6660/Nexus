"""Phase 23.5 â€” Private Business-Owner Acceptance Test Suite for NEXUS.

Simulates a real-world small-business owner (Elena Rostova, owner of
'Northwind Roasters & Provisions' specialty coffee and gourmet pantry retail boutique)
using NEXUS end-to-end across all 10 evaluation criteria:

1. Signup/login and business creation
2. Tabular retail dataset upload + automated ingestion
3. Business Understanding + semantic review/activation (v1 ACTIVE)
4. Real-world business inquiries via agentic reasoning
5. Analytics/statistics, investigations, and forecasting capabilities
6. Traceable evidence, grounded explanations, and executive recommendations
7. Historical ledger, re-opening run details, markdown dossier export, and version reproducibility
8. Empty, error, and degraded states handled gracefully
9. Strict multi-tenant and data isolation (defense against cross-tenant data leakage)
10. Overall UX, clarity, boardroom readiness, and trust
"""

import io
from datetime import datetime, timezone, date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.expense import Expense
from app.models.tenant import (
    Business,
    IngestionJob,
    Organization,
    OrganizationMembership,
    TenantSemanticModel,
    UploadedDataset,
    UserIdentity,
)
from app.models.history import AnalysisRun


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
    yield session
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


def _generate_realistic_retail_csv() -> str:
    """
    Generate realistic 6-month transaction data for Northwind Roasters & Provisions.
    Spans 2025-08-01 through 2026-01-31 (180 transactions):
    - Channels: In-Store and Online
    - Seasonal surge in December (holiday gift baskets, beans, grinders)
    - Commercial adjustments (customer return of broken mug, order cancellation)
    """
    lines = ["order_id,order_date,amount,channel,notes"]

    # 6 months of daily representative transactions
    order_num = 1
    # August to November baseline (~25 orders/month)
    dates_months = [
        ("2025-08", 25, 45.0, 75.0),
        ("2025-09", 25, 50.0, 80.0),
        ("2025-10", 25, 52.0, 85.0),
        ("2025-11", 30, 60.0, 110.0),
        ("2025-12", 45, 95.0, 180.0),  # Holiday peak
        ("2026-01", 30, 48.0, 70.0),   # Post-holiday normalization
    ]

    for month_str, count, instore_val, online_val in dates_months:
        for day in range(1, count + 1):
            day_str = f"{day:02d}"
            date_val = f"{month_str}-{day_str}"
            is_online = (day % 3 == 0)
            channel = "Online" if is_online else "In-Store"
            base_amt = online_val if is_online else instore_val
            # Add variation
            amt = round(base_amt + ((day * 7) % 23) - 5.5, 2)

            # Legitimate commercial adjustments
            note = "standard sale"
            if month_str == "2025-12" and day == 28:
                amt = 12.50
                note = "gift card redemption"
            elif month_str == "2026-01" and day == 5:
                amt = 15.00
                note = "clearance accessory"

            lines.append(f"NWD-{order_num:04d},{date_val},{amt:.2f},{channel},{note}")
            order_num += 1

    return "\n".join(lines) + "\n"


class TestPhase23_5_BusinessOwnerAcceptance:
    """Complete Private Business-Owner Acceptance test covering all 10 criteria."""

    elena_token: str = ""
    elena_biz_id: str = ""
    elena_org_id: str = ""
    dataset_id: str = ""
    semantic_v1_id: str = ""
    run_1_id: str = ""

    # Second tenant fixtures
    marcus_token: str = ""
    marcus_biz_id: str = ""
    marcus_org_id: str = ""

    def test_01_owner_signup_and_business_creation(self, client: TestClient):
        """1. Signup/login and business creation."""
        # Elena registers her boutique business
        res = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "elena@northwindprovisions.com",
                "password": "NorthwindSecure2026!#",
                "full_name": "Elena Rostova",
                "organization_name": "Northwind Holdings LLC",
                "business_name": "Northwind Roasters & Provisions",
            },
        )
        assert res.status_code == 201, f"Signup failed: {res.text}"
        data = res.json()
        assert "access_token" in data
        assert data["business"]["name"] == "Northwind Roasters & Provisions"

        TestPhase23_5_BusinessOwnerAcceptance.elena_token = data["access_token"]
        TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id = data["business"]["id"]
        TestPhase23_5_BusinessOwnerAcceptance.elena_org_id = data["organization"]["id"]

        # Elena logs in again to confirm credentials work
        login_res = client.post(
            "/api/v1/auth/login",
            json={
                "email": "elena@northwindprovisions.com",
                "password": "NorthwindSecure2026!#",
            },
        )
        assert login_res.status_code == 200
        assert "access_token" in login_res.json()

        # Check initial empty state
        headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }
        empty_runs = client.get("/api/v1/history/runs", headers=headers)
        assert empty_runs.status_code == 200
        assert empty_runs.json() == []

    def test_02_dataset_upload_and_ingestion(self, client: TestClient):
        """2. Dataset upload + ingestion with realistic retail data."""
        headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }

        csv_content = _generate_realistic_retail_csv()
        files = {
            "file": (
                "northwind_h2_2025_sales.csv",
                io.BytesIO(csv_content.encode("utf-8")),
                "text/csv",
            )
        }

        # Upload
        upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
        assert upload_res.status_code == 201, f"Upload failed: {upload_res.text}"
        up_data = upload_res.json()

        assert up_data["row_count"] == 180
        assert up_data["column_count"] == 5
        assert up_data["readiness_status"] in ["ready", "READY", "ready_with_warnings"]
        assert up_data["readiness_score"] >= 80

        dataset_id = up_data["dataset_id"]
        TestPhase23_5_BusinessOwnerAcceptance.dataset_id = dataset_id

        # Ingestion into Sale core model
        ingest_res = client.post(
            f"/api/v1/gateway/datasets/{dataset_id}/ingest",
            headers=headers,
            json={"target_entity": "Sale"},
        )
        assert ingest_res.status_code == 200
        ingest_data = ingest_res.json()
        assert ingest_data["status"] == "COMPLETED"
        assert ingest_data["records_persisted"] >= 170

    def test_03_business_understanding_and_semantic_activation(self, client: TestClient):
        """3. Business Understanding + semantic review/activation."""
        headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }

        # Verify semantic revision was created automatically
        rev_res = client.get("/api/v1/semantic/revisions", headers=headers)
        assert rev_res.status_code == 200
        revs = rev_res.json()
        assert len(revs) >= 1

        active = [r for r in revs if r["status"] == "ACTIVE"]
        if not active:
            # Elena approves the revision
            rev_to_approve = revs[0]
            appr_res = client.post(
                f"/api/v1/semantic/revisions/{rev_to_approve['id']}/approve",
                headers=headers,
                json={"comment": "Approved by Elena for commercial operations"},
            )
            assert appr_res.status_code == 200
            TestPhase23_5_BusinessOwnerAcceptance.semantic_v1_id = appr_res.json()["revision_id"]
        else:
            TestPhase23_5_BusinessOwnerAcceptance.semantic_v1_id = active[0]["id"]

        # Confirm semantic model is ACTIVE
        active_model = client.get("/api/v1/semantic/understanding", headers=headers)
        assert active_model.status_code == 200
        assert active_model.json()["status"] == "ACTIVE"

    def test_04_ask_real_business_questions(self, client: TestClient):
        """4. Ask real business questions via agentic intelligence."""
        headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }

        # Query 1: Total net sales & orders
        q1_res = client.post(
            "/api/v1/agent/analyze",
            headers=headers,
            json={
                "query": "What is our total net sales revenue and how many orders did we complete?",
                "explanation_level": "manager",
            },
        )
        assert q1_res.status_code == 200
        q1_data = q1_res.json()
        assert q1_data["status"] == "completed"
        assert len(q1_data["evidence"]) >= 1
        assert "answer" in q1_data
        assert len(q1_data["answer"]) > 20

        # Query 2: December holiday performance
        q2_res = client.post(
            "/api/v1/agent/analyze",
            headers=headers,
            json={
                "query": "How did December 2025 revenue compare to November 2025?",
                "explanation_level": "executive",
            },
        )
        assert q2_res.status_code == 200
        q2_data = q2_res.json()
        assert q2_data["status"] == "completed"

    def test_05_analytics_statistics_and_predictive_intelligence(self, client: TestClient, db_session: Session):
        """5. Analytics/statistics, investigations, and forecasts."""
        headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }
        biz_id = TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id

        # 5a. Executive 12-metric financial summary via Analytics API
        summary_res = client.get("/api/v1/analytics/summary", headers=headers)
        assert summary_res.status_code == 200
        s_data = summary_res.json()["data"]
        assert "net_sales" in s_data
        assert "orders" in s_data
        assert "average_order_value" in s_data
        assert float(s_data["net_sales"]["value"]) > 0
        assert float(s_data["orders"]["value"]) > 0

        # 5b. Statistical comparison between Online vs In-Store order distributions
        # Populate Customer segment tags to enable two-sample comparison
        sales = db_session.execute(select(Sale).where(Sale.business_id == biz_id)).scalars().all()
        assert len(sales) > 0

        # Seed two distinct customer segments for comparison
        cust_online = Customer(
            business_id=biz_id,
            customer_code="CUST-ONLINE",
            name="Online Shoppers",
            email="online@northwind.test",
            city="Seattle",
            customer_segment="Online",
            acquisition_date=date(2025, 8, 1),
        )
        cust_store = Customer(
            business_id=biz_id,
            customer_code="CUST-STORE",
            name="In-Store Patrons",
            email="store@northwind.test",
            city="Portland",
            customer_segment="In-Store",
            acquisition_date=date(2025, 8, 1),
        )
        db_session.add_all([cust_online, cust_store])
        db_session.flush()

        # Assign sales to customers
        for idx, s in enumerate(sales):
            s.customer_id = cust_online.id if (idx % 3 == 0) else cust_store.id
        db_session.commit()

        # Run statistical hypothesis test comparing Online vs In-Store order values
        stat_res = client.get(
            "/api/v1/analytics/statistics/hypothesis?group1=Online&group2=In-Store&metric=order_value",
            headers=headers,
        )
        assert stat_res.status_code == 200
        t_data = stat_res.json()["data"]
        assert "p_value" in t_data
        assert "statistic" in t_data
        assert "effect_size" in t_data
        assert len(t_data["assumptions_and_limitations"]) > 0
        # Causation safeguard check
        assert "causation" in str(stat_res.json()).lower() or "causal" in str(stat_res.json()).lower()

        # 5c. Time series forecast
        fcst_res = client.post(
            "/api/v1/forecast/analyze",
            headers=headers,
            json={"query": "Forecast monthly revenue for next 3 months", "explanation_level": "manager"},
        )
        assert fcst_res.status_code == 200
        f_data = fcst_res.json()
        assert f_data["status"] in ["completed", "degraded", "insufficient_data", "unavailable"]

        # 5d. Diagnostic investigation
        inv_res = client.post(
            "/api/v1/investigation/analyze",
            headers=headers,
            json={"query": "Why did sales increase in December 2025?", "explanation_level": "manager"},
        )
        assert inv_res.status_code == 200
        inv_data = inv_res.json()
        assert "status" in inv_data

    def test_06_evidence_explanations_and_recommendations(self, client: TestClient):
        """6. Evidence, explanations and recommendations."""
        headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }

        res = client.post(
            "/api/v1/agent/analyze",
            headers=headers,
            json={"query": "What is our average order value and how are margins trending?"},
        )
        assert res.status_code == 200
        data = res.json()

        # Check evidence provenance
        assert len(data["evidence"]) >= 1
        ev = data["evidence"][0]
        assert "sources" in ev or "table" in ev or "semantic_definition" in ev or "calculation" in ev

        # Check assumptions & limitations
        assert isinstance(data["assumptions"], list)
        assert isinstance(data["limitations"], list)

    def test_07_history_reopening_and_reproducibility(self, client: TestClient):
        """7. History/reopening and reproducibility."""
        headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }

        # Check runs ledger
        runs_res = client.get("/api/v1/history/runs", headers=headers)
        assert runs_res.status_code == 200
        runs = runs_res.json()
        assert len(runs) >= 1

        run_id = runs[0]["id"]
        TestPhase23_5_BusinessOwnerAcceptance.run_1_id = run_id

        # Reopen run details
        detail = client.get(f"/api/v1/history/runs/{run_id}", headers=headers).json()
        assert detail["id"] == run_id
        assert detail["semantic_version"] == 1
        assert detail["dataset_content_hash"] is not None

        # Export Intelligence Dossier in Markdown
        report_res = client.get(f"/api/v1/history/runs/{run_id}/report?format=markdown", headers=headers)
        assert report_res.status_code == 200
        report_content = report_res.json()["content"]
        assert "NEXUS Intelligence Dossier" in report_content
        assert detail["query"] in report_content

        # Semantic Model Upgrade to v2
        mod_res = client.post(
            f"/api/v1/semantic/revisions/{TestPhase23_5_BusinessOwnerAcceptance.semantic_v1_id}/modify",
            headers=headers,
            json={
                "metrics_override": {
                    "net_revenue": {"calculation_formula": "SUM(sales.total_amount * 0.98)"}
                },
                "comment": "Reserve 2% for catering breakage",
            },
        )
        assert mod_res.status_code == 200
        rev_v2_id = mod_res.json()["revision_id"]

        client.post(
            f"/api/v1/semantic/revisions/{rev_v2_id}/approve",
            headers=headers,
            json={"comment": "Approve v2"},
        )

        # Historical Run 1 MUST retain semantic_version=1 (Reproducibility)
        reopened = client.get(f"/api/v1/history/runs/{run_id}", headers=headers).json()
        assert reopened["semantic_version"] == 1
        assert reopened["semantic_revision_id"] == TestPhase23_5_BusinessOwnerAcceptance.semantic_v1_id

    def test_08_empty_error_and_degraded_states(self, client: TestClient):
        """8. Empty/error/degraded states."""
        # Create a new business with no data uploaded
        new_user = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "nodata.owner@domain.test",
                "password": "Password123!#",
                "full_name": "No Data Owner",
                "organization_name": "Fresh Org",
                "business_name": "Fresh Business",
            },
        ).json()
        new_headers = {
            "Authorization": f"Bearer {new_user['access_token']}",
            "X-Business-ID": new_user["business"]["id"],
        }

        # 8a. Query agent before data upload -> gracefully returns data-not-ready (not 500)
        res = client.post(
            "/api/v1/agent/analyze",
            headers=new_headers,
            json={"query": "What is my revenue?"},
        )
        assert res.status_code == 200
        assert res.json()["status"] in ["data-not-ready", "semantic-not-ready"]
        assert "ready" in res.json()["answer"].lower() or "semantic" in res.json()["answer"].lower()

        # 8b. Upload empty CSV -> rejected with 400
        empty_res = client.post(
            "/api/v1/gateway/upload",
            files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
            headers=new_headers,
        )
        assert empty_res.status_code == 400

        # 8c. Upload executable / malware file -> rejected
        mal_res = client.post(
            "/api/v1/gateway/upload",
            files={"file": ("virus.exe", io.BytesIO(b"MZ\x90\x00\x03"), "application/octet-stream")},
            headers=new_headers,
        )
        assert mal_res.status_code in [400, 415]

    def test_09_multi_tenant_and_data_isolation(self, client: TestClient, db_session: Session):
        """9. Tenant/data isolation (Zero cross-tenant bleed)."""
        # Register a second business owner: Marcus Vance ("Blue Harbor Seafood")
        marcus_res = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "marcus@blueharbor.test",
                "password": "MarcusSecure2026!#",
                "full_name": "Marcus Vance",
                "organization_name": "Blue Harbor Enterprises",
                "business_name": "Blue Harbor Seafood",
            },
        )
        assert marcus_res.status_code == 201
        m_data = marcus_res.json()
        TestPhase23_5_BusinessOwnerAcceptance.marcus_token = m_data["access_token"]
        TestPhase23_5_BusinessOwnerAcceptance.marcus_biz_id = m_data["business"]["id"]

        marcus_headers = {
            "Authorization": f"Bearer {m_data['access_token']}",
            "X-Business-ID": m_data["business"]["id"],
        }
        elena_headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }

        # 9a. IDOR Defense: Marcus cannot view Elena's dataset
        elena_dataset_id = TestPhase23_5_BusinessOwnerAcceptance.dataset_id
        idor_ds = client.get(f"/api/v1/gateway/datasets/{elena_dataset_id}/preview", headers=marcus_headers)
        assert idor_ds.status_code in [403, 404]

        # 9b. IDOR Defense: Marcus cannot see Elena's historical runs
        marcus_runs = client.get("/api/v1/history/runs", headers=marcus_headers).json()
        assert not any(r["id"] == TestPhase23_5_BusinessOwnerAcceptance.run_1_id for r in marcus_runs)

        # 9c. IDOR Defense: Marcus cannot reopen Elena's run by ID
        idor_run = client.get(
            f"/api/v1/history/runs/{TestPhase23_5_BusinessOwnerAcceptance.run_1_id}",
            headers=marcus_headers,
        )
        assert idor_run.status_code in [403, 404]

        # 9d. IDOR Defense: Marcus cannot export Elena's report dossier
        idor_rep = client.get(
            f"/api/v1/history/runs/{TestPhase23_5_BusinessOwnerAcceptance.run_1_id}/report",
            headers=marcus_headers,
        )
        assert idor_rep.status_code in [403, 404]

        # 9e. IDOR Defense: Marcus cannot query with Elena's business ID header
        tampered_headers = {
            "Authorization": f"Bearer {m_data['access_token']}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }
        tampered_res = client.post(
            "/api/v1/agent/analyze",
            headers=tampered_headers,
            json={"query": "Give me sales data"},
        )
        assert tampered_res.status_code in [403, 404]

        # 9f. CRITICAL DATA ISOLATION: Marcus's analytics must NOT include Elena's sales!
        # Upload a separate small dataset for Marcus (3 rows = $300 total)
        marcus_csv = "order_id,date,amount,channel\nBHS-001,2026-01-10,100.00,Direct\nBHS-002,2026-01-11,100.00,Direct\nBHS-003,2026-01-12,100.00,Direct\n"
        up_m = client.post(
            "/api/v1/gateway/upload",
            files={"file": ("seafood.csv", io.BytesIO(marcus_csv.encode("utf-8")), "text/csv")},
            headers=marcus_headers,
        ).json()
        client.post(f"/api/v1/gateway/datasets/{up_m['dataset_id']}/ingest", headers=marcus_headers, json={"target_entity": "Sale"})

        # Elena's summary
        elena_sum = client.get("/api/v1/analytics/summary", headers=elena_headers).json()["data"]
        # Marcus's summary
        marcus_sum = client.get("/api/v1/analytics/summary", headers=marcus_headers).json()["data"]

        # Marcus's orders should be exactly 3, not 180+
        assert int(marcus_sum["orders"]["value"]) == 3
        # Marcus's net sales should be $300, completely isolated from Elena's thousands of dollars of revenue
        assert float(marcus_sum["net_sales"]["value"]) == 300.0
        assert float(elena_sum["orders"]["value"]) >= 170

    def test_10_ux_trust_and_boardroom_usability(self, client: TestClient):
        """10. Overall UX, clarity, trust and usability."""
        headers = {
            "Authorization": f"Bearer {TestPhase23_5_BusinessOwnerAcceptance.elena_token}",
            "X-Business-ID": TestPhase23_5_BusinessOwnerAcceptance.elena_biz_id,
        }

        # Check financial summary formatting
        summary = client.get("/api/v1/analytics/summary", headers=headers).json()
        data = summary["data"]

        # Check clean currency formatting ($X,XXX.XX)
        assert data["net_sales"]["formatted"].startswith("$")
        assert "." in data["net_sales"]["formatted"]

        # Check absence of NaN / Inf / null crashes
        for key in ["net_sales", "gross_profit", "average_order_value", "orders"]:
            val = data[key]["value"]
            assert val is not None
            assert str(val) != "nan"
            assert str(val) != "inf"

        # Check trust: no fabricated precision
        assert data["average_order_value"]["formatted"].count(".") == 1
