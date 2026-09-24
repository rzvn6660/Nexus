"""Tests for Analytics REST API endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from backend.tests.test_analytics_financial import multi_period_db


def test_api_analytics_summary(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/summary."""
    res = client.get(
        "/api/v1/analytics/summary",
        params={
            "date_from": "2023-06-01T00:00:00Z",
            "date_to": "2023-06-30T23:59:59Z",
            "comparison_date_from": "2023-05-01T00:00:00Z",
            "comparison_date_to": "2023-05-31T23:59:59Z",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert "data" in body
    assert "evidence" in body

    data = body["data"]
    assert float(data["net_sales"]["value"]) == 340.0
    assert float(data["cogs"]["value"]) == 120.0
    assert float(data["gross_profit"]["value"]) == 220.0

    # Evidence verification
    evidence = body["evidence"]
    assert "sales" in evidence["source_tables"]
    assert evidence["metric"] == "financial_summary"


def test_api_analytics_products(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/products."""
    res = client.get(
        "/api/v1/analytics/products",
        params={"ranking_metric": "revenue", "limit": 10},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 2
    assert body["data"][0]["sku"] == "SKU-B"


def test_api_analytics_categories(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/categories."""
    res = client.get("/api/v1/analytics/categories")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["dimension"] == "category"
    assert len(body["data"]["items"]) == 2


def test_api_analytics_customers(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/customers."""
    res = client.get("/api/v1/analytics/customers")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["dimension"] == "customer_segment"


def test_api_analytics_rfm(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/rfm."""
    res = client.get("/api/v1/analytics/rfm", params={"quantile_bins": 3})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["total_customers_analyzed"] == 2


def test_api_analytics_cohorts(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/cohorts."""
    res = client.get("/api/v1/analytics/cohorts")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["total_cohorts"] == 2


def test_api_analytics_repeat_purchase(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/repeat-purchase."""
    res = client.get("/api/v1/analytics/repeat-purchase")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["repeat_purchase_rate"] == 50.0


def test_api_analytics_variance(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/variance."""
    res = client.get(
        "/api/v1/analytics/variance",
        params={
            "dimension": "product",
            "date_from": "2023-06-01T00:00:00Z",
            "date_to": "2023-06-30T23:59:59Z",
            "comparison_date_from": "2023-05-01T00:00:00Z",
            "comparison_date_to": "2023-05-31T23:59:59Z",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert float(body["data"]["total_variance"]) == 185.0


def test_api_analytics_decomposition(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/decomposition."""
    res = client.get(
        "/api/v1/analytics/decomposition",
        params={
            "date_from": "2023-06-01T00:00:00Z",
            "date_to": "2023-06-30T23:59:59Z",
            "comparison_date_from": "2023-05-01T00:00:00Z",
            "comparison_date_to": "2023-05-31T23:59:59Z",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["reconciled"] is True


def test_api_analytics_correlation(client: TestClient, multi_period_db: Session):
    """Test GET /api/v1/analytics/statistics/correlation."""
    res = client.get(
        "/api/v1/analytics/statistics/correlation",
        params={"variable_x": "subtotal", "variable_y": "quantity"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert "correlation_coefficient" in body["data"]
