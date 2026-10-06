"""Regression tests for Investigation Engine diagnostic fixes.

Fix 1: Date-window recalibration -- future/empty windows are shifted to the
        tenant's last available full calendar month.
Fix 2: Currency symbol -- observation statements use the tenant's actual
        currency (INR -> rupee) instead of a hard-coded dollar sign.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.investigation.engine import InvestigationEngine
from app.models.customer import Customer
from app.models.sale import Sale


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(db: Session, business_id=None) -> InvestigationEngine:
    return InvestigationEngine(db, business_id=business_id)


# ---------------------------------------------------------------------------
# Fix 1: _recalibrate_dates_for_tenant_data unit tests
# ---------------------------------------------------------------------------


class TestRecalibrateDatesForTenantData:
    """Unit tests for the date-window recalibration guard."""

    def test_future_window_recalibrated_to_last_data_month(self, multi_period_db: Session):
        """When resolved dates are after tenant latest sale, recalibrate to last data month."""
        engine = _make_engine(multi_period_db)
        # multi_period_db has sales in May and June 2023.
        # Simulate a far-future window (as would happen querying today=2026).
        resolved = {
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "comparison_date_from": "2026-08-01",
            "comparison_date_to": "2026-08-31",
            "matched_expression": "recent_variance_baseline",
        }
        recalibrated = engine._recalibrate_dates_for_tenant_data(resolved)
        # Tenant latest sale is 2023-06-20 -> should shift to June 2023
        assert recalibrated["date_from"] == "2023-06-01"
        assert recalibrated["date_to"] == "2023-06-30"
        # Comparison should be the preceding month (May 2023)
        assert recalibrated["comparison_date_from"] == "2023-05-01"
        assert recalibrated["comparison_date_to"] == "2023-05-31"
        assert "recalibrated" in recalibrated["matched_expression"]

    def test_in_range_window_not_modified(self, multi_period_db: Session):
        """When resolved window start is within tenant data coverage, leave unchanged."""
        engine = _make_engine(multi_period_db)
        # 2023-05-01 to 2023-05-31 -- entirely within data (max_dt is 2023-06-20)
        resolved = {
            "date_from": "2023-05-01",
            "date_to": "2023-05-31",
            "comparison_date_from": "2023-04-01",
            "comparison_date_to": "2023-04-30",
            "matched_expression": "may_2023",
        }
        result = engine._recalibrate_dates_for_tenant_data(resolved)
        assert result["date_from"] == "2023-05-01"
        assert result["date_to"] == "2023-05-31"
        assert result["matched_expression"] == "may_2023"

    def test_none_dates_returned_unchanged(self, multi_period_db: Session):
        """When date_from/date_to are None, return unchanged (no date in query)."""
        engine = _make_engine(multi_period_db)
        resolved = {
            "date_from": None,
            "date_to": None,
            "comparison_date_from": None,
            "comparison_date_to": None,
            "matched_expression": None,
        }
        result = engine._recalibrate_dates_for_tenant_data(resolved)
        assert result["date_from"] is None
        assert result["date_to"] is None

    def test_empty_db_returns_unchanged(self, db_session: Session):
        """When the DB has no sales at all, return dates unchanged (no crash)."""
        engine = _make_engine(db_session)
        resolved = {
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "comparison_date_from": "2026-08-01",
            "comparison_date_to": "2026-08-31",
            "matched_expression": "recent_variance_baseline",
        }
        result = engine._recalibrate_dates_for_tenant_data(resolved)
        # No data -> return unchanged
        assert result["date_from"] == "2026-09-01"
        assert result["date_to"] == "2026-09-30"

    def test_january_recalibration_wraps_to_december_prior_year(self, db_session: Session):
        """January as anchor month -> comparison wraps back to December of previous year."""
        c = Customer(
            customer_code="CUST-JAN",
            name="Jan Tester",
            email="jan@test.com",
            city="Test City",
            customer_segment="Retail",
            acquisition_date=date(2023, 1, 1),
        )
        db_session.add(c)
        db_session.flush()
        s = Sale(
            transaction_number="TXN-JAN-01",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 15, tzinfo=timezone.utc),
            status="completed",
            subtotal=Decimal("100.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("8.00"),
            total_amount=Decimal("108.00"),
        )
        db_session.add(s)
        db_session.commit()

        engine = _make_engine(db_session)
        resolved = {
            "date_from": "2025-09-01",
            "date_to": "2025-09-30",
            "comparison_date_from": "2025-08-01",
            "comparison_date_to": "2025-08-31",
            "matched_expression": "recent_variance_baseline",
        }
        result = engine._recalibrate_dates_for_tenant_data(resolved)
        # Anchor month = January 2023 -> comparison = December 2022
        assert result["date_from"] == "2023-01-01"
        assert result["date_to"] == "2023-01-31"
        assert result["comparison_date_from"] == "2022-12-01"
        assert result["comparison_date_to"] == "2022-12-31"


# ---------------------------------------------------------------------------
# Fix 2: Currency symbol in observation statements
# ---------------------------------------------------------------------------


class TestObservationCurrencySymbol:
    """Unit tests for _extract_observations currency symbol fix."""

    def test_usd_observation_uses_dollar_symbol(self, multi_period_db: Session):
        """USD result emits dollar symbol in observation statement."""
        engine = _make_engine(multi_period_db)
        plan = MagicMock()
        plan.baseline_dates = {"date_from": "2023-05-01"}
        plan.comparison_dates = {"date_from": "2023-06-01"}
        result = {
            "currency": "USD",
            "currency_symbol": "$",
            "net_sales": {"value": 155.0, "comparison_value": None, "percentage_change": None},
        }
        obs = engine._extract_observations(1, "get_financial_summary", result, plan)
        assert len(obs) == 1
        assert "$155.00" in obs[0].statement
        assert "\u20b9" not in obs[0].statement

    def test_inr_observation_uses_rupee_symbol(self, multi_period_db: Session):
        """INR result emits rupee symbol in observation statement, not dollar."""
        engine = _make_engine(multi_period_db)
        plan = MagicMock()
        plan.baseline_dates = {"date_from": "2023-05-01"}
        plan.comparison_dates = {"date_from": "2023-06-01"}
        result = {
            "currency": "INR",
            "currency_symbol": "\u20b9",
            "net_sales": {
                "value": 254192.0,
                "comparison_value": 210000.0,
                "percentage_change": 21.0,
            },
        }
        obs = engine._extract_observations(1, "get_financial_summary", result, plan)
        assert len(obs) == 1
        stmt = obs[0].statement
        assert "\u20b9254,192.00" in stmt
        assert "\u20b9210,000.00" in stmt
        assert "$" not in stmt

    def test_missing_currency_symbol_falls_back_to_dollar(self, multi_period_db: Session):
        """When currency_symbol is absent from result, fall back gracefully to dollar."""
        engine = _make_engine(multi_period_db)
        plan = MagicMock()
        plan.baseline_dates = {"date_from": "2023-05-01"}
        plan.comparison_dates = {"date_from": "2023-06-01"}
        result = {
            "net_sales": {"value": 500.0, "comparison_value": None, "percentage_change": None},
        }
        obs = engine._extract_observations(1, "get_financial_summary", result, plan)
        assert len(obs) == 1
        assert "$500.00" in obs[0].statement


# ---------------------------------------------------------------------------
# Fix 1 + 2 end-to-end integration: no-date query with far-future reference
# ---------------------------------------------------------------------------


def test_investigation_no_explicit_date_uses_real_tenant_data(multi_period_db: Session):
    """
    End-to-end regression: a decline query with no date and a far-future
    reference_date must NOT return zero revenue.

    Before fix: DateInterpreter resolved to Sep 2026 (no data) -> $0.00.
    After fix:  engine recalibrates to June 2023 -> revenue > 0.
    """
    engine = _make_engine(multi_period_db)
    response = engine.investigate(
        query="Why did revenue decline?",
        explanation_level="manager",
        reference_date=date(2026, 10, 1),
    )

    assert response.status == "completed"
    fin_obs = [o for o in response.observations if o.metric == "net_sales"]
    assert len(fin_obs) >= 1, "Expected at least one net_sales observation"
    obs_val = fin_obs[0].value_current
    assert obs_val is not None and obs_val > 0, (
        f"Revenue must be > 0 after recalibration; got {obs_val}."
    )
    assert "$0.00" not in fin_obs[0].statement


def test_investigation_explicit_date_bypasses_recalibration(multi_period_db: Session):
    """
    When the query explicitly names a date within actual data range,
    no recalibration occurs and the original window is respected.
    """
    engine = _make_engine(multi_period_db)
    response = engine.investigate(
        query="Why did revenue decline in July 2023?",
        explanation_level="manager",
        reference_date=date(2023, 8, 1),
    )
    assert response.status == "completed"
    # July 2023 has no data in fixture, so 0 is legitimate -- not a bug
    fin_obs = [o for o in response.observations if o.metric == "net_sales"]
    assert len(fin_obs) >= 1
    assert "Net Sales (Revenue) was measured at" in fin_obs[0].statement

