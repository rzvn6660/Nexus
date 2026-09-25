"""Tests for Analysis Run History, Decision Records (HITL), and Reports."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.history import AnalysisRun, DecisionRecord


def test_decision_lifecycle_workflow(client: TestClient, db_session: Session):
    """Test full Human-in-the-Loop decision review lifecycle: PENDING -> APPROVED -> REJECTED -> MODIFIED."""
    # 1. Create a decision record
    create_resp = client.post(
        "/api/v1/history/decisions",
        json={
            "recommendation_text": "Increase inventory buffer by 15% for SKU-PREM-101",
            "reviewer_notes": "Initial proposal from Q3 supply chain variance analysis",
        },
    )
    assert create_resp.status_code == 201
    decision = create_resp.json()
    assert decision["id"] is not None
    assert decision["status"] == "PENDING"
    assert decision["recommendation_text"] == "Increase inventory buffer by 15% for SKU-PREM-101"
    decision_id = decision["id"]

    # 2. List decisions with PENDING filter
    list_resp = client.get("/api/v1/history/decisions?status=PENDING")
    assert list_resp.status_code == 200
    pending_items = list_resp.json()
    assert any(d["id"] == decision_id for d in pending_items)

    # 3. Approve decision
    approve_resp = client.patch(
        f"/api/v1/history/decisions/{decision_id}",
        json={
            "status": "APPROVED",
            "reviewer_notes": "Approved based on confirmed vendor lead time increase.",
            "reviewed_by": "vp_supply_chain",
        },
    )
    assert approve_resp.status_code == 200
    approved_data = approve_resp.json()
    assert approved_data["status"] == "APPROVED"
    assert approved_data["reviewed_by"] == "vp_supply_chain"
    assert approved_data["reviewed_at"] is not None

    # 4. Modify decision
    modify_resp = client.patch(
        f"/api/v1/history/decisions/{decision_id}",
        json={
            "status": "MODIFIED",
            "reviewer_notes": "Adjusted reorder buffer from 15% to 10% due to warehouse space limits.",
            "reviewed_by": "inventory_director",
        },
    )
    assert modify_resp.status_code == 200
    assert modify_resp.json()["status"] == "MODIFIED"


def test_analysis_run_history_and_report_export(client: TestClient, db_session: Session):
    """Test analysis run retrieval and structured dossier report export."""
    # Seed an AnalysisRun
    run = AnalysisRun(
        request_id="test-run-uuid-12345",
        query="What was our total net revenue last month?",
        intent="metric_lookup",
        status="completed",
        explanation_level="manager",
        answer="Net Revenue was $340.00 across 2 orders with AOV of $170.00.",
        execution_time_ms=45.2,
        tools_used=["get_financial_summary"],
        calculations=[{"metric": "net_sales", "value": 340.0}],
        assumptions=["Standard 30-day billing window"],
        limitations=["Returns in transit excluded"],
        evidence_records=[
            {
                "analysis_id": "test-ev-1",
                "metric": "net_sales",
                "source_tables": ["sales", "sale_items"],
                "calculation": "SUM(subtotal) - SUM(discounts) - SUM(returns)",
            }
        ],
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    # Attach a decision to this run
    decision = DecisionRecord(
        analysis_id=run.id,
        recommendation_text="Maintain existing promotional discount rates",
        status="APPROVED",
        reviewed_by="senior_analyst",
    )
    db_session.add(decision)
    db_session.commit()

    # 1. List runs
    list_resp = client.get("/api/v1/history/runs")
    assert list_resp.status_code == 200
    runs_list = list_resp.json()
    assert len(runs_list) >= 1
    assert any(r["id"] == run.id for r in runs_list)

    # 2. Get run detail
    detail_resp = client.get(f"/api/v1/history/runs/{run.id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["query"] == "What was our total net revenue last month?"
    assert len(detail["decisions"]) == 1

    # 3. Export report as Markdown
    rpt_md_resp = client.get(f"/api/v1/history/runs/{run.id}/report?format=markdown")
    assert rpt_md_resp.status_code == 200
    rpt_md = rpt_md_resp.json()
    assert rpt_md["format"] == "markdown"
    assert "NEXUS Intelligence Dossier" in rpt_md["content"]
    assert "Net Revenue was $340.00" in rpt_md["content"]
    assert "get_financial_summary" in rpt_md["content"]

    # 4. Export report as JSON
    rpt_json_resp = client.get(f"/api/v1/history/runs/{run.id}/report?format=json")
    assert rpt_json_resp.status_code == 200
    rpt_json = rpt_json_resp.json()
    assert rpt_json["format"] == "json"
    assert "test-run-uuid-12345" in rpt_json["content"]


def test_history_and_decision_404_handling(client: TestClient):
    """Verify 404 responses for nonexistent analysis runs and decisions."""
    resp_run = client.get("/api/v1/history/runs/999999")
    assert resp_run.status_code == 404

    resp_rpt = client.get("/api/v1/history/runs/999999/report")
    assert resp_rpt.status_code == 404

    resp_dec = client.get("/api/v1/history/decisions/999999")
    assert resp_dec.status_code == 404
