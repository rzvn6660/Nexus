"""Unit tests for the CSV Ingestion service and error reporting."""

import io
from app.data.ingestion.csv_ingestion import CSVIngestionService


def test_valid_customers_csv_ingestion() -> None:
    """Validate successful parsing of compliant customers CSV."""
    csv_content = (
        "customer_code,name,email,phone,city,customer_segment,acquisition_date\n"
        "CUST-001,Alice Smith,alice@example.com,555-1234,Seattle,Retail,2023-01-10\n"
        "CUST-002,Bob Jones,bob@corp.com,555-5678,Portland,Corporate,2023-02-15\n"
    )
    service = CSVIngestionService()
    result = service.ingest_csv(dataset="customers", source=csv_content)

    assert result.success is True
    assert result.rows_read == 2
    assert result.rows_valid == 2
    assert result.rows_failed == 0
    assert len(result.errors) == 0


def test_missing_required_columns_csv() -> None:
    """Validate rejection when required header columns are missing."""
    csv_content = (
        "customer_code,name\n"
        "CUST-001,Alice Smith\n"
    )
    service = CSVIngestionService()
    result = service.ingest_csv(dataset="customers", source=csv_content)

    assert result.success is False
    assert result.rows_read == 0
    assert result.rows_failed == 1
    assert result.errors[0].error_type == "MISSING_COLUMNS"


def test_malformed_rows_and_type_errors() -> None:
    """Validate row-level error reporting on invalid data formats."""
    csv_content = (
        "sku,name,category,subcategory,unit_cost,selling_price\n"
        "SKU-001,Valid Item,Electronics,Audio,10.00,20.00\n"
        "SKU-002,Bad Price Item,Electronics,Audio,10.00,-5.00\n"  # Negative price violates ge=0
        "SKU-003,Bad Cost Item,Electronics,Audio,invalid_cost,25.00\n"  # String cost
    )
    service = CSVIngestionService()
    result = service.ingest_csv(dataset="products", source=csv_content)

    assert result.success is False
    assert result.rows_read == 3
    assert result.rows_valid == 1
    assert result.rows_failed >= 2
    # Verify row numbers are captured accurately
    row_nums = [e.row_number for e in result.errors]
    assert 2 in row_nums or 3 in row_nums


def test_unknown_dataset_error() -> None:
    """Validate graceful error handling when unknown dataset is requested."""
    service = CSVIngestionService()
    result = service.ingest_csv(dataset="nonexistent_dataset", source="a,b\n1,2\n")
    assert result.success is False
    assert result.errors[0].error_type == "UNKNOWN_DATASET"
