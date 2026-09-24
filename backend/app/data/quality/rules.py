"""Deterministic business validation rules for the retail domain."""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from app.schemas.quality import QualitySeverity, QualityCheckResult


def check_non_negative_numeric(
    records: List[Dict[str, Any]],
    field_name: str,
    id_field: str = "id",
    strictly_positive: bool = False,
) -> QualityCheckResult:
    """Validate that numeric values are non-negative (or strictly positive)."""
    invalid_ids = []
    comparison_str = "> 0" if strictly_positive else ">= 0"

    for r in records:
        val = r.get(field_name)
        if val is not None:
            try:
                num = Decimal(str(val))
                if strictly_positive and num <= 0:
                    invalid_ids.append(r.get(id_field, "unknown"))
                elif not strictly_positive and num < 0:
                    invalid_ids.append(r.get(id_field, "unknown"))
            except Exception:
                invalid_ids.append(r.get(id_field, "unknown"))

    passed = len(invalid_ids) == 0
    return QualityCheckResult(
        check_name=f"chk_{field_name}_{'strictly_positive' if strictly_positive else 'non_negative'}",
        rule_description=f"Field '{field_name}' must be {comparison_str}",
        severity=QualitySeverity.ERROR,
        passed=passed,
        affected_rows_count=len(invalid_ids),
        sample_affected_ids=invalid_ids[:10],
        message=(
            f"All {len(records)} records satisfy {field_name} {comparison_str}."
            if passed
            else f"Found {len(invalid_ids)} records violating {field_name} {comparison_str}."
        ),
    )


def check_uniqueness(
    records: List[Dict[str, Any]],
    field_name: str,
    id_field: str = "id",
) -> QualityCheckResult:
    """Validate that field values are unique across all records."""
    seen = set()
    duplicate_ids = []

    for r in records:
        val = r.get(field_name)
        if val is not None:
            val_str = str(val).strip()
            if val_str in seen:
                duplicate_ids.append(r.get(id_field, "unknown"))
            else:
                seen.add(val_str)

    passed = len(duplicate_ids) == 0
    return QualityCheckResult(
        check_name=f"chk_{field_name}_unique",
        rule_description=f"Field '{field_name}' must have unique values across the dataset",
        severity=QualitySeverity.ERROR,
        passed=passed,
        affected_rows_count=len(duplicate_ids),
        sample_affected_ids=duplicate_ids[:10],
        message=(
            f"All values in '{field_name}' are unique."
            if passed
            else f"Found {len(duplicate_ids)} duplicate values in '{field_name}'."
        ),
    )


def check_required_fields(
    records: List[Dict[str, Any]],
    required_fields: List[str],
    id_field: str = "id",
) -> QualityCheckResult:
    """Validate that mandatory fields are not null or empty."""
    invalid_ids = []

    for r in records:
        missing = [f for f in required_fields if r.get(f) is None or str(r.get(f)).strip() == ""]
        if missing:
            invalid_ids.append(r.get(id_field, "unknown"))

    passed = len(invalid_ids) == 0
    return QualityCheckResult(
        check_name="chk_required_fields_present",
        rule_description=f"Required fields must be present and non-null: {', '.join(required_fields)}",
        severity=QualitySeverity.ERROR,
        passed=passed,
        affected_rows_count=len(invalid_ids),
        sample_affected_ids=invalid_ids[:10],
        message=(
            f"All {len(records)} records contain all required fields."
            if passed
            else f"Found {len(invalid_ids)} records with missing required fields."
        ),
    )


def check_line_total_reconciliation(
    sale_items: List[Dict[str, Any]],
    tolerance: Decimal = Decimal("0.02"),
) -> QualityCheckResult:
    """
    Validate that line_total == (quantity * unit_price) - discount_amount.
    """
    mismatched_ids = []

    for item in sale_items:
        try:
            qty = Decimal(str(item.get("quantity", 0)))
            price = Decimal(str(item.get("unit_price", 0)))
            discount = Decimal(str(item.get("discount_amount", 0)))
            line_total = Decimal(str(item.get("line_total", 0)))

            expected = (qty * price) - discount
            if abs(line_total - expected) > tolerance:
                mismatched_ids.append(item.get("id", "unknown"))
        except Exception:
            mismatched_ids.append(item.get("id", "unknown"))

    passed = len(mismatched_ids) == 0
    return QualityCheckResult(
        check_name="chk_line_total_reconciliation",
        rule_description="line_total must reconcile with (quantity * unit_price) - discount_amount",
        severity=QualitySeverity.ERROR,
        passed=passed,
        affected_rows_count=len(mismatched_ids),
        sample_affected_ids=mismatched_ids[:10],
        message=(
            f"All {len(sale_items)} line items correctly reconcile."
            if passed
            else f"Found {len(mismatched_ids)} line items with arithmetic total discrepancies."
        ),
    )


def check_transaction_total_reconciliation(
    sales: List[Dict[str, Any]],
    tolerance: Decimal = Decimal("0.02"),
) -> QualityCheckResult:
    """
    Validate that total_amount == subtotal - discount_amount + tax_amount.
    """
    mismatched_ids = []

    for sale in sales:
        try:
            subtotal = Decimal(str(sale.get("subtotal", 0)))
            discount = Decimal(str(sale.get("discount_amount", 0)))
            tax = Decimal(str(sale.get("tax_amount", 0)))
            total = Decimal(str(sale.get("total_amount", 0)))

            expected = subtotal - discount + tax
            if abs(total - expected) > tolerance:
                mismatched_ids.append(sale.get("transaction_number", sale.get("id", "unknown")))
        except Exception:
            mismatched_ids.append(sale.get("transaction_number", sale.get("id", "unknown")))

    passed = len(mismatched_ids) == 0
    return QualityCheckResult(
        check_name="chk_transaction_total_reconciliation",
        rule_description="total_amount must reconcile with subtotal - discount_amount + tax_amount",
        severity=QualitySeverity.ERROR,
        passed=passed,
        affected_rows_count=len(mismatched_ids),
        sample_affected_ids=mismatched_ids[:10],
        message=(
            f"All {len(sales)} sales orders reconcile perfectly."
            if passed
            else f"Found {len(mismatched_ids)} transactions with order total discrepancies."
        ),
    )


def check_foreign_key_reference(
    child_records: List[Dict[str, Any]],
    parent_records: List[Dict[str, Any]],
    child_fk_field: str,
    parent_pk_field: str = "id",
    relationship_name: str = "Foreign Key Reference",
) -> QualityCheckResult:
    """Verify that foreign keys in child records reference valid parents."""
    parent_ids = {p.get(parent_pk_field) for p in parent_records if p.get(parent_pk_field) is not None}
    orphan_ids = []

    for child in child_records:
        fk_val = child.get(child_fk_field)
        if fk_val is None or fk_val not in parent_ids:
            orphan_ids.append(child.get("id", "unknown"))

    passed = len(orphan_ids) == 0
    return QualityCheckResult(
        check_name=f"chk_fk_{child_fk_field}_references_{parent_pk_field}",
        rule_description=f"{relationship_name}: '{child_fk_field}' must reference existing '{parent_pk_field}'",
        severity=QualitySeverity.ERROR,
        passed=passed,
        affected_rows_count=len(orphan_ids),
        sample_affected_ids=orphan_ids[:10],
        message=(
            f"All {len(child_records)} records maintain valid referential integrity."
            if passed
            else f"Found {len(orphan_ids)} orphaned child records with invalid foreign keys."
        ),
    )
