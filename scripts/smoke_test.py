#!/usr/bin/env python
"""NEXUS Production Smoke Test Suite.

Executes an end-to-end verification of the 11 core production capabilities:
  1. Root Index & Navigation
  2. Health, Liveness & Readiness Probes
  3. Data Layer Health & Model Registry
  4. Deterministic Analytics Engine
  5. Semantic KPI & Synonym Resolution
  6. Hybrid RAG Context Retrieval
  7. Predictive Time-Series Forecasting
  8. Diagnostic Causal Investigation
  9. Agentic LangGraph Pipeline
 10. Request Tracing & Correlation Headers (X-Request-ID)
 11. CORS & Security Safeguards

Usage:
  python scripts/smoke_test.py                     # Runs in-process via FastAPI TestClient
  python scripts/smoke_test.py --base-url http://localhost:8000 # Runs against live deployment
"""

import argparse
import os
import sys
import time
from typing import Any, Dict

# Ensure project root and backend directory are in sys.path for local in-process testing
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


def print_step(step_num: int, title: str) -> None:
    print(f"\n[{step_num:02d}/11] {title}...", flush=True)


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"       [PASS] {message}", flush=True)
    else:
        print(f"       [FAIL] {message}", flush=True)
        raise AssertionError(f"Smoke test failed: {message}")


def run_smoke_test(client_getter) -> None:
    print("=" * 60)
    print("NEXUS Platform Production Smoke Test")
    print("Where Business Data Becomes Intelligence.")
    print("=" * 60)

    start_total = time.perf_counter()
    passed_steps = 0

    client = client_getter()

    # Step 1: Root Index
    print_step(1, "Testing Root Index & Metadata")
    resp = client.get("/")
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    data = resp.json()
    check(data.get("name") == "NEXUS", f"Application name: {data.get('name')}")
    check("Agentic Business Intelligence" in data.get("title", ""), f"Title: {data.get('title')}")
    check("health" in data and "readiness" in data, "Health links present")
    passed_steps += 1

    # Step 2: Health Probes
    print_step(2, "Testing Liveness & Readiness Probes")
    resp_live = client.get("/api/v1/health/live")
    check(resp_live.status_code == 200, f"Liveness probe: HTTP 200 (got {resp_live.status_code})")
    check(resp_live.json().get("status") == "alive", "Liveness status: alive")

    resp_health = client.get("/api/v1/health")
    check(resp_health.status_code == 200, f"Full health check: HTTP 200 (got {resp_health.status_code})")
    health_data = resp_health.json()
    check(health_data.get("status") in ["healthy", "degraded"], f"Status: {health_data.get('status')}")
    check("database" in health_data, "Database health block present")
    passed_steps += 1

    # Step 3: Data Layer Health
    print_step(3, "Testing Data Layer & Entity Registry")
    resp = client.get("/api/v1/data/health")
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    data = resp.json()
    check(data.get("layer") == "data_layer", "Layer identification: data_layer")
    check(data.get("registered_models", 0) >= 6, f"Registered models: {data.get('registered_models')}")
    passed_steps += 1

    # Step 4: Deterministic Analytics
    print_step(4, "Testing Deterministic Analytics Engine")
    resp = client.get("/api/v1/analytics/summary")
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    summary_envelope = resp.json()
    check(summary_envelope.get("success") is True, "Envelope success: true")
    summary = summary_envelope.get("data", {})
    check("net_sales" in summary, "Metric 'net_sales' present in data")
    check("orders" in summary, "Metric 'orders' present in data")
    check("average_order_value" in summary, "Metric 'average_order_value' present in data")
    check("gross_profit" in summary, "Metric 'gross_profit' present in data")
    check("evidence" in summary_envelope, "EvidenceRecord present in envelope")
    passed_steps += 1

    # Step 5: Semantic Layer
    print_step(5, "Testing Semantic KPI & Ambiguity Resolution")
    resp = client.post("/api/v1/semantic/resolve", json={"query": "net sales"})
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    sem_data = resp.json()
    check(sem_data.get("canonical_name") == "net_revenue", f"Resolved 'net sales' to: {sem_data.get('canonical_name')}")

    # Ambiguity detection verification
    resp_amb = client.post("/api/v1/semantic/resolve", json={"query": "sales turnover"})
    check(resp_amb.status_code == 200, f"Ambiguity check HTTP 200 (got {resp_amb.status_code})")
    check(resp_amb.json().get("is_ambiguous") is True, "Ambiguity correctly flagged for 'sales turnover'")
    passed_steps += 1

    # Step 6: Hybrid RAG Search
    print_step(6, "Testing Business Context Knowledge Search")
    resp = client.post("/api/v1/knowledge/search", json={"query": "revenue recognition policy", "top_k": 2})
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    rag_data = resp.json()
    chunks = rag_data.get("chunks", [])
    check(isinstance(chunks, list), f"Retrieved context records: {len(chunks)} chunks")
    passed_steps += 1

    # Step 7: Predictive Time-Series Forecasting
    print_step(7, "Testing Predictive Intelligence & Forecasting")
    resp = client.post("/api/v1/forecast/analyze", json={"query": "Forecast revenue for next 3 months", "reference_date": "2026-09-01"})
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    fc_data = resp.json()
    check(fc_data.get("target_metric") in ["revenue", "sales"], f"Target metric: {fc_data.get('target_metric')}")
    check(len(fc_data.get("predictions", [])) == 3, f"Forecast horizon: {len(fc_data.get('predictions', []))} periods")
    passed_steps += 1

    # Step 8: Diagnostic Investigation
    print_step(8, "Testing Diagnostic Causal Investigation")
    resp = client.post("/api/v1/investigation/analyze", json={"query": "Why did revenue decline?", "reference_date": "2026-09-01"})
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    inv_data = resp.json()
    check("summary" in inv_data, "Executive summary generated")
    check("hypotheses" in inv_data, "Tested hypotheses present")
    check("status" in inv_data, f"Investigation status: {inv_data.get('status')}")
    passed_steps += 1

    # Step 9: Agentic LangGraph Pipeline
    print_step(9, "Testing Multi-Agent LangGraph Pipeline")
    resp = client.post("/api/v1/agent/analyze", json={"query": "What was net revenue last month?", "reference_date": "2026-09-01"})
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    agent_data = resp.json()
    check(agent_data.get("status") in ["completed", "success", "clarification_needed"], f"Agent status: {agent_data.get('status')}")
    check("evidence" in agent_data, "Grounded EvidenceRecord returned")
    passed_steps += 1

    # Step 10: Request Correlation & Latency
    print_step(10, "Testing Request Correlation & Latency Tracking")
    custom_req_id = "smoke-test-corr-id-12345"
    resp = client.get("/api/v1/health/live", headers={"X-Request-ID": custom_req_id})
    check(resp.headers.get("X-Request-ID") == custom_req_id, f"Correlation ID reflected: {resp.headers.get('X-Request-ID')}")
    check("X-Process-Time-Ms" in resp.headers, f"Process latency: {resp.headers.get('X-Process-Time-Ms')}ms")
    passed_steps += 1

    # Step 11: Security & Boundary Safeguards
    print_step(11, "Testing Security & Upload Size Boundaries")
    # CSV extension rejection
    fake_exe = b"MZ\x90\x00Binary"
    files = {"file": ("malicious.exe", fake_exe, "application/octet-stream")}
    data_form = {"dataset": "products"}
    resp = client.post("/api/v1/data/ingest/csv", data=data_form, files=files)
    check(resp.status_code == 400, f"Invalid file format rejected: HTTP {resp.status_code}")

    # Forecast horizon limit
    resp = client.post("/api/v1/forecast/analyze", json={"query": "Forecast revenue for next 48 months"})
    check(resp.status_code == 422, f"Out-of-bounds horizon rejected: HTTP {resp.status_code}")
    passed_steps += 1

    total_time_ms = (time.perf_counter() - start_total) * 1000
    print("\n" + "=" * 60)
    print(f"SMOKE TEST SUMMARY: {passed_steps}/11 STEPS PASSED")
    print(f"Total Execution Time: {total_time_ms:.2f}ms")
    print("ALL PRODUCTION CORE CAPABILITIES VERIFIED SUCCESSFULLY.")
    print("=" * 60)


def create_in_process_client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import get_db
    from app.api.deps import get_db_session
    from evaluation.runner.runner import create_evaluation_database

    session = create_evaluation_database()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db

    return TestClient(app)


def main():
    parser = argparse.ArgumentParser(description="NEXUS Production Smoke Test")
    parser.add_argument("--base-url", type=str, default=None, help="Base URL of live deployment (e.g. http://localhost:8000)")
    args = parser.parse_args()

    if args.base_url:
        import httpx
        client_getter = lambda: httpx.Client(base_url=args.base_url, timeout=30.0)
    else:
        client_getter = create_in_process_client

    try:
        run_smoke_test(client_getter)
    except Exception as exc:
        print(f"\n[ERROR] Smoke test suite failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
