"""Deterministic CSV Ingestion Service for NEXUS domain entities."""

from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Type, Union
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.data.connectors.csv_connector import CSVConnector
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.inventory import Inventory
from app.models.expense import Expense
from app.schemas.customer import CustomerCreate
from app.schemas.product import ProductCreate
from app.schemas.inventory import InventoryCreate
from app.schemas.expense import ExpenseCreate
from app.schemas.ingestion import IngestionResult, IngestionRowError

# Mapping of dataset names to Pydantic validation schemas and ORM models
DATASET_REGISTRY = {
    "customers": {
        "schema": CustomerCreate,
        "model": Customer,
        "required_columns": {"customer_code", "name", "email", "city", "customer_segment", "acquisition_date"},
    },
    "products": {
        "schema": ProductCreate,
        "model": Product,
        "required_columns": {"sku", "name", "category", "subcategory", "unit_cost", "selling_price"},
    },
    "inventory": {
        "schema": InventoryCreate,
        "model": Inventory,
        "required_columns": {"product_id", "stock_quantity", "reorder_threshold"},
    },
    "expenses": {
        "schema": ExpenseCreate,
        "model": Expense,
        "required_columns": {"expense_date", "category", "description", "amount"},
    },
}


class CSVIngestionService:
    """
    Validates and ingests CSV tabular data against domain contracts.
    
    Provides strict schema validation, type parsing, row-level error reporting,
    and optional database persistence.
    """

    def __init__(self, db: Optional[Session] = None) -> None:
        self.db = db

    def ingest_csv(
        self,
        dataset: str,
        source: Union[str, Any],
        filename: Optional[str] = None,
        persist: bool = False,
    ) -> IngestionResult:
        """
        Parse and validate CSV rows for the designated dataset.
        
        Args:
            dataset: Target dataset identifier (e.g. 'customers', 'products')
            source: Path, string content, or IO stream
            filename: Optional source file name for reporting
            persist: If True and db session is available, persists valid rows to DB
        """
        dataset_key = dataset.lower().strip()
        if dataset_key not in DATASET_REGISTRY:
            return IngestionResult(
                dataset_name=dataset,
                filename=filename,
                rows_read=0,
                rows_valid=0,
                rows_failed=1,
                errors=[
                    IngestionRowError(
                        row_number=0,
                        column_name=None,
                        raw_value=dataset,
                        error_type="UNKNOWN_DATASET",
                        message=f"Dataset '{dataset}' is not registered for CSV ingestion. Supported: {list(DATASET_REGISTRY.keys())}",
                    )
                ],
                success=False,
            )

        reg = DATASET_REGISTRY[dataset_key]
        schema_cls = reg["schema"]
        model_cls = reg["model"]
        required_cols = reg["required_columns"]

        connector = CSVConnector(source)
        try:
            connector.connect()
        except Exception as exc:
            return IngestionResult(
                dataset_name=dataset_key,
                filename=filename,
                rows_read=0,
                rows_valid=0,
                rows_failed=1,
                errors=[
                    IngestionRowError(
                        row_number=0,
                        column_name=None,
                        raw_value=None,
                        error_type="CONNECTION_ERROR",
                        message=f"Failed to open CSV stream: {str(exc)}",
                    )
                ],
                success=False,
            )

        headers = set(connector.headers)
        missing_cols = required_cols - headers
        if missing_cols:
            connector.disconnect()
            return IngestionResult(
                dataset_name=dataset_key,
                filename=filename,
                rows_read=0,
                rows_valid=0,
                rows_failed=1,
                errors=[
                    IngestionRowError(
                        row_number=0,
                        column_name="headers",
                        raw_value=list(headers),
                        error_type="MISSING_COLUMNS",
                        message=f"Missing required columns in CSV header: {sorted(list(missing_cols))}",
                    )
                ],
                success=False,
            )

        rows_read = 0
        rows_valid = 0
        errors: List[IngestionRowError] = []
        valid_objects: List[Any] = []

        try:
            for idx, raw_row in enumerate(connector.read_records(), start=1):
                rows_read += 1
                row_errors = self._validate_and_convert_row(idx, raw_row, schema_cls)
                if row_errors:
                    errors.extend(row_errors)
                else:
                    rows_valid += 1
                    if persist and self.db:
                        valid_objects.append(model_cls(**raw_row))

            if persist and self.db and valid_objects and len(errors) == 0:
                self.db.bulk_save_objects(valid_objects)
                self.db.commit()

        finally:
            connector.disconnect()

        return IngestionResult(
            dataset_name=dataset_key,
            filename=filename,
            rows_read=rows_read,
            rows_valid=rows_valid,
            rows_failed=len(errors),
            errors=errors,
            success=len(errors) == 0 and rows_read > 0,
        )

    def _validate_and_convert_row(
        self,
        row_number: int,
        row_data: Dict[str, Any],
        schema_cls: Type[Any],
    ) -> List[IngestionRowError]:
        """Validate row using target Pydantic schema and record error diagnostics."""
        row_errors: List[IngestionRowError] = []

        # Convert empty strings to None for optional fields
        cleaned = {k: (None if v == "" else v) for k, v in row_data.items()}

        try:
            schema_cls(**cleaned)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(l) for l in err["loc"])
                val = cleaned.get(loc)
                row_errors.append(
                    IngestionRowError(
                        row_number=row_number,
                        column_name=loc,
                        raw_value=val,
                        error_type=err["type"],
                        message=err["msg"],
                    )
                )
        except Exception as exc:
            row_errors.append(
                IngestionRowError(
                    row_number=row_number,
                    column_name=None,
                    raw_value=str(row_data),
                    error_type="PARSE_ERROR",
                    message=f"Row parsing error: {str(exc)}",
                )
            )

        return row_errors
