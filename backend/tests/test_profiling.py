"""Unit tests for the Data Profiling engine."""

from decimal import Decimal
from datetime import datetime, date
from sqlalchemy.orm import Session
from app.data.profiling.profiler import DataProfiler


def test_profiler_on_records() -> None:
    """Validate statistical profiling across diverse data types."""
    records = [
        {"id": 1, "sku": "A1", "price": 10.0, "category": "Tools", "created": "2023-01-01"},
        {"id": 2, "sku": "A2", "price": 20.0, "category": "Tools", "created": "2023-01-10"},
        {"id": 3, "sku": "A3", "price": 30.0, "category": "Supplies", "created": "2023-01-20"},
        {"id": 4, "sku": "A4", "price": None, "category": "Tools", "created": "2023-01-30"},
    ]
    profiler = DataProfiler()
    profile = profiler.profile_records("sample_items", records)

    assert profile.table_name == "sample_items"
    assert profile.total_rows == 4
    assert profile.total_columns == 5
    assert profile.duplicate_rows == 0

    # Null detection on 'price'
    price_prof = profile.columns["price"]
    assert price_prof.null_count == 1
    assert price_prof.null_percentage == 25.0
    assert price_prof.numeric_stats is not None
    assert price_prof.numeric_stats.min_value == 10.0
    assert price_prof.numeric_stats.max_value == 30.0
    assert price_prof.numeric_stats.mean == 20.0

    # Categorical distribution on 'category'
    cat_prof = profile.columns["category"]
    assert cat_prof.null_count == 0
    assert cat_prof.unique_count == 2
    assert cat_prof.top_categories is not None
    assert cat_prof.top_categories[0].value == "Tools"
    assert cat_prof.top_categories[0].count == 3


def test_profiler_duplicate_detection() -> None:
    """Validate duplicate row counting."""
    records = [
        {"col1": "A", "col2": 1},
        {"col1": "A", "col2": 1},  # Duplicate
        {"col1": "B", "col2": 2},
    ]
    profiler = DataProfiler()
    profile = profiler.profile_records("test_dupes", records)
    assert profile.duplicate_rows == 1


def test_profiler_on_seeded_database_table(seeded_db_session: Session) -> None:
    """Validate database table profiling using seeded session."""
    profiler = DataProfiler(db=seeded_db_session)
    profile = profiler.profile_table("customers")

    assert profile.table_name == "customers"
    assert profile.total_rows >= 2
    assert "email" in profile.columns
    assert "customer_segment" in profile.columns

    summaries = profiler.get_table_summaries()
    assert len(summaries) == 6
    table_names = [s.table_name for s in summaries]
    assert "customers" in table_names
    assert "sales" in table_names
