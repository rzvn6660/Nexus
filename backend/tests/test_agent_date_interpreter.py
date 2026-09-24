"""Deterministic unit tests for DateInterpreter."""

from datetime import date

from app.agents.tools.date_interpreter import DateInterpreter


def test_date_interpreter_last_month() -> None:
    ref = date(2024, 9, 15)
    res = DateInterpreter.interpret("What was revenue last month?", reference_date=ref)
    assert res["date_from"] == "2024-08-01"
    assert res["date_to"] == "2024-08-31"
    assert res["comparison_date_from"] == "2024-07-01"
    assert res["comparison_date_to"] == "2024-07-31"
    assert res["matched_expression"] == "last_month"


def test_date_interpreter_this_month() -> None:
    ref = date(2024, 8, 20)
    res = DateInterpreter.interpret("Show sales for this month", reference_date=ref)
    assert res["date_from"] == "2024-08-01"
    assert res["date_to"] == "2024-08-20"
    assert res["comparison_date_from"] == "2024-07-01"
    assert res["matched_expression"] == "this_month"


def test_date_interpreter_last_quarter() -> None:
    ref = date(2024, 5, 10)  # Q2
    res = DateInterpreter.interpret("What was profit last quarter?", reference_date=ref)
    assert res["date_from"] == "2024-01-01"
    assert res["date_to"] == "2024-03-31"
    assert res["matched_expression"] == "last_quarter"


def test_date_interpreter_named_month_year() -> None:
    ref = date(2024, 12, 1)
    res = DateInterpreter.interpret("Calculate revenue for August 2024", reference_date=ref)
    assert res["date_from"] == "2024-08-01"
    assert res["date_to"] == "2024-08-31"
    assert res["comparison_date_from"] == "2024-07-01"
    assert res["comparison_date_to"] == "2024-07-31"


def test_date_interpreter_explicit_iso_range() -> None:
    res = DateInterpreter.interpret("Analyze performance from 2024-01-01 to 2024-03-31")
    assert res["date_from"] == "2024-01-01"
    assert res["date_to"] == "2024-03-31"
    assert res["comparison_date_to"] == "2023-12-31"


def test_date_interpreter_past_days() -> None:
    ref = date(2024, 8, 31)
    res = DateInterpreter.interpret("Sales for the last 30 days", reference_date=ref)
    assert res["date_to"] == "2024-08-31"
    assert res["date_from"] == "2024-08-02"
    assert res["comparison_date_to"] == "2024-08-01"
    assert res["matched_expression"] == "last_30_days"


def test_date_interpreter_unspecified_dates() -> None:
    res = DateInterpreter.interpret("What are our top products?")
    assert res["date_from"] is None
    assert res["date_to"] is None
    assert res["is_ambiguous"] is False
