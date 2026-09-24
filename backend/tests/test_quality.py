"""Unit tests for the Data Quality engine, business rules, and quality scorecards."""

from decimal import Decimal
from sqlalchemy.orm import Session
from app.data.quality.checker import DataQualityChecker
from app.schemas.quality import QualitySeverity, QualityStatus


def test_quality_checker_passed_clean_data() -> None:
    """Validate quality checker passes completely on valid records."""
    valid_customers = [
        {"id": 1, "customer_code": "C1", "name": "Client A", "email": "a@test.com", "city": "Seattle", "customer_segment": "Retail"},
        {"id": 2, "customer_code": "C2", "name": "Client B", "email": "b@test.com", "city": "Portland", "customer_segment": "Corporate"},
    ]
    checker = DataQualityChecker()
    report = checker.check_records("customers", valid_customers)

    assert report.status == QualityStatus.PASSED
    assert report.errors_count == 0
    assert report.checks_failed == 0
    assert report.checks_passed == report.checks_executed


def test_quality_checker_detects_duplicate_and_missing_values() -> None:
    """Validate quality checker catches duplicate codes and missing emails."""
    flawed_customers = [
        {"id": 1, "customer_code": "C1", "name": "Client A", "email": "a@test.com", "city": "Seattle", "customer_segment": "Retail"},
        {"id": 2, "customer_code": "C1", "name": "Client B", "email": "", "city": "Portland", "customer_segment": "Corporate"},  # Dup code, empty email
    ]
    checker = DataQualityChecker()
    report = checker.check_records("customers", flawed_customers)

    assert report.status == QualityStatus.FAILED
    assert report.errors_count >= 1
    # Check that affected IDs are reported
    failed_checks = [c for c in report.checks if not c.passed]
    assert len(failed_checks) >= 1


def test_quality_checker_line_total_reconciliation() -> None:
    """Validate detection of mathematical discrepancies in sale item line totals."""
    bad_items = [
        # qty 2, price 10, discount 0 -> expected line_total 20, but provided 99.00
        {"id": 101, "sale_id": 1, "product_id": 1, "quantity": 2, "unit_price": "10.00", "discount_amount": "0.00", "line_total": "99.00"}
    ]
    checker = DataQualityChecker()
    report = checker.check_records("sale_items", bad_items)

    assert report.status == QualityStatus.FAILED
    line_check = next((c for c in report.checks if c.check_name == "chk_line_total_reconciliation"), None)
    assert line_check is not None
    assert line_check.passed is False
    assert 101 in line_check.sample_affected_ids


def test_quality_checker_referential_integrity() -> None:
    """Validate foreign key check catches orphaned records."""
    sales = [
        {"id": 1, "transaction_number": "T1", "customer_id": 999, "transaction_date": "2023-01-01", "subtotal": "100.00", "total_amount": "100.00"}
    ]
    context = {"customers": [{"id": 1}, {"id": 2}]}  # Customer 999 does not exist

    checker = DataQualityChecker()
    report = checker.check_records("sales", sales, context_data=context)

    assert report.status == QualityStatus.FAILED
    fk_check = next((c for c in report.checks if "customer_id" in c.check_name), None)
    assert fk_check is not None
    assert fk_check.passed is False


def test_quality_checker_on_seeded_database(seeded_db_session: Session) -> None:
    """Validate quality check run against a seeded database table."""
    checker = DataQualityChecker(db=seeded_db_session)
    report = checker.check_table("customers")
    assert report.dataset_name == "customers"
    assert report.total_rows >= 2
    assert report.status == QualityStatus.PASSED
