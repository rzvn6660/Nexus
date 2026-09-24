"""Data Quality Checker orchestrating dataset audits and generating QualityReports."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.inventory import Inventory
from app.models.expense import Expense

from app.schemas.quality import (
    QualityCheckResult,
    QualityReport,
    QualitySeverity,
    QualityStatus,
)
from app.data.quality.rules import (
    check_non_negative_numeric,
    check_uniqueness,
    check_required_fields,
    check_line_total_reconciliation,
    check_transaction_total_reconciliation,
    check_foreign_key_reference,
)

MODEL_REGISTRY = {
    "customers": Customer,
    "products": Product,
    "sales": Sale,
    "sale_items": SaleItem,
    "inventory": Inventory,
    "expenses": Expense,
}


class DataQualityChecker:
    """
    Executes domain-specific data quality audits against database tables
    or supplied row collections.
    """

    def __init__(self, db: Optional[Session] = None) -> None:
        self.db = db

    def check_table(self, table_name: str) -> QualityReport:
        """Run all designated quality checks for a specific database table."""
        if not self.db:
            raise ValueError("Database session required to audit table quality.")

        key = table_name.lower().strip()
        if key not in MODEL_REGISTRY:
            raise ValueError(f"Unknown table '{table_name}'. Supported: {list(MODEL_REGISTRY.keys())}")

        model = MODEL_REGISTRY[key]
        records = self.db.scalars(select(model)).all()
        columns = [c.name for c in model.__table__.columns]
        rows = [{col: getattr(r, col) for col in columns} for r in records]

        return self.check_records(key, rows)

    def check_records(
        self,
        dataset_name: str,
        records: List[Dict[str, Any]],
        context_data: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> QualityReport:
        """
        Evaluate business validation rules against a collection of records.
        
        Args:
            dataset_name: Target dataset ('customers', 'products', 'sales', etc.)
            records: List of record dictionaries to validate
            context_data: Optional related tables needed for referential integrity checks
        """
        key = dataset_name.lower().strip()
        checks: List[QualityCheckResult] = []
        context = context_data or {}

        # Fetch context data from database if not supplied
        if self.db:
            if key == "sales" and "customers" not in context:
                custs = self.db.scalars(select(Customer)).all()
                context["customers"] = [{"id": c.id} for c in custs]
            elif key == "sale_items":
                if "sales" not in context:
                    sls = self.db.scalars(select(Sale)).all()
                    context["sales"] = [{"id": s.id} for s in sls]
                if "products" not in context:
                    prods = self.db.scalars(select(Product)).all()
                    context["products"] = [{"id": p.id} for p in prods]
            elif key == "inventory" and "products" not in context:
                prods = self.db.scalars(select(Product)).all()
                context["products"] = [{"id": p.id} for p in prods]

        if key == "customers":
            checks.append(check_required_fields(records, ["customer_code", "name", "email", "city", "customer_segment"]))
            checks.append(check_uniqueness(records, "customer_code"))
            checks.append(check_uniqueness(records, "email"))

        elif key == "products":
            checks.append(check_required_fields(records, ["sku", "name", "category", "unit_cost", "selling_price"]))
            checks.append(check_uniqueness(records, "sku"))
            checks.append(check_non_negative_numeric(records, "unit_cost"))
            checks.append(check_non_negative_numeric(records, "selling_price"))

        elif key == "sales":
            checks.append(check_required_fields(records, ["transaction_number", "customer_id", "transaction_date", "subtotal", "total_amount"]))
            checks.append(check_uniqueness(records, "transaction_number"))
            checks.append(check_non_negative_numeric(records, "subtotal"))
            checks.append(check_non_negative_numeric(records, "discount_amount"))
            checks.append(check_non_negative_numeric(records, "tax_amount"))
            checks.append(check_non_negative_numeric(records, "total_amount"))
            checks.append(check_transaction_total_reconciliation(records))
            if "customers" in context:
                checks.append(check_foreign_key_reference(records, context["customers"], "customer_id", "id", "Sales -> Customer"))

        elif key == "sale_items":
            checks.append(check_required_fields(records, ["sale_id", "product_id", "quantity", "unit_price", "line_total"]))
            checks.append(check_non_negative_numeric(records, "quantity", strictly_positive=True))
            checks.append(check_non_negative_numeric(records, "unit_price"))
            checks.append(check_non_negative_numeric(records, "discount_amount"))
            checks.append(check_non_negative_numeric(records, "line_total"))
            checks.append(check_line_total_reconciliation(records))
            if "sales" in context:
                checks.append(check_foreign_key_reference(records, context["sales"], "sale_id", "id", "SaleItems -> Sale"))
            if "products" in context:
                checks.append(check_foreign_key_reference(records, context["products"], "product_id", "id", "SaleItems -> Product"))

        elif key == "inventory":
            checks.append(check_required_fields(records, ["product_id", "stock_quantity", "reorder_threshold"]))
            checks.append(check_uniqueness(records, "product_id"))
            checks.append(check_non_negative_numeric(records, "stock_quantity"))
            checks.append(check_non_negative_numeric(records, "reorder_threshold"))
            if "products" in context:
                checks.append(check_foreign_key_reference(records, context["products"], "product_id", "id", "Inventory -> Product"))

        elif key == "expenses":
            checks.append(check_required_fields(records, ["expense_date", "category", "description", "amount"]))
            checks.append(check_non_negative_numeric(records, "amount"))

        # Calculate scorecard
        total_rows = len(records)
        executed = len(checks)
        passed_count = sum(1 for c in checks if c.passed)
        failed_count = sum(1 for c in checks if not c.passed)
        errors_count = sum(1 for c in checks if not c.passed and c.severity == QualitySeverity.ERROR)
        warnings_count = sum(1 for c in checks if not c.passed and c.severity == QualitySeverity.WARNING)

        if errors_count > 0:
            status = QualityStatus.FAILED
        elif warnings_count > 0:
            status = QualityStatus.WARNING
        else:
            status = QualityStatus.PASSED

        return QualityReport(
            dataset_name=key,
            total_rows=total_rows,
            checks_executed=executed,
            checks_passed=passed_count,
            checks_failed=failed_count,
            warnings_count=warnings_count,
            errors_count=errors_count,
            status=status,
            checks=checks,
        )
