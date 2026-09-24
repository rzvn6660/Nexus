"""Deterministic data profiling engine for tabular datasets and database entities."""

import math
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union
from collections import Counter
from sqlalchemy import select, func, inspect
from sqlalchemy.orm import Session

from app.schemas.profiling import (
    ColumnProfile,
    NumericStats,
    DateRangeStats,
    CategoricalValueCount,
    DatasetProfile,
    TableSummary,
)
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.inventory import Inventory
from app.models.expense import Expense

MODEL_REGISTRY = {
    "customers": Customer,
    "products": Product,
    "sales": Sale,
    "sale_items": SaleItem,
    "inventory": Inventory,
    "expenses": Expense,
}


class DataProfiler:
    """
    Profiles database tables or in-memory row collections.
    
    Produces statistical summaries, null frequencies, uniqueness flags,
    numeric descriptive metrics, date spans, and categorical distributions.
    """

    def __init__(self, db: Optional[Session] = None) -> None:
        self.db = db

    def get_table_summaries(self) -> List[TableSummary]:
        """Return high-level summary of all registered domain entities."""
        if not self.db:
            raise ValueError("Database session required to inspect table summaries.")

        summaries = []
        for name, model in MODEL_REGISTRY.items():
            count = self.db.scalar(select(func.count(model.id))) or 0
            cols = [col.name for col in model.__table__.columns]
            summaries.append(
                TableSummary(
                    table_name=name,
                    row_count=count,
                    column_count=len(cols),
                    columns=cols,
                )
            )
        return summaries

    def profile_table(self, table_name: str) -> DatasetProfile:
        """Profile an active database table using SQLAlchemy."""
        if not self.db:
            raise ValueError("Database session required to profile database table.")

        key = table_name.lower().strip()
        if key not in MODEL_REGISTRY:
            raise ValueError(f"Unknown table '{table_name}'. Supported: {list(MODEL_REGISTRY.keys())}")

        model = MODEL_REGISTRY[key]
        records = self.db.scalars(select(model)).all()
        # Convert ORM instances to dictionaries
        columns = [c.name for c in model.__table__.columns]
        rows = [{col: getattr(r, col) for col in columns} for r in records]

        return self.profile_records(key, rows, columns)

    def profile_records(
        self,
        dataset_name: str,
        records: List[Dict[str, Any]],
        column_names: Optional[List[str]] = None,
    ) -> DatasetProfile:
        """Profile an in-memory list of record dictionaries."""
        total_rows = len(records)
        if column_names is None:
            if total_rows > 0:
                column_names = list(records[0].keys())
            else:
                column_names = []

        total_cols = len(column_names)
        duplicate_count = self._count_duplicate_rows(records)

        col_profiles: Dict[str, ColumnProfile] = {}
        for col in column_names:
            col_values = [r.get(col) for r in records]
            col_profiles[col] = self._profile_column(col, col_values, total_rows)

        return DatasetProfile(
            table_name=dataset_name,
            total_rows=total_rows,
            total_columns=total_cols,
            duplicate_rows=duplicate_count,
            columns=col_profiles,
        )

    def _count_duplicate_rows(self, records: List[Dict[str, Any]]) -> int:
        """Calculate count of completely duplicate records."""
        if not records:
            return 0
        seen = set()
        duplicates = 0
        for r in records:
            # Create a hashable tuple representation
            row_tuple = tuple(sorted((k, str(v)) for k, v in r.items()))
            if row_tuple in seen:
                duplicates += 1
            else:
                seen.add(row_tuple)
        return duplicates

    def _profile_column(self, col_name: str, values: List[Any], total_rows: int) -> ColumnProfile:
        """Compute metrics for a single column."""
        non_nulls = [v for v in values if v is not None and v != ""]
        null_count = total_rows - len(non_nulls)
        null_pct = round((null_count / total_rows * 100), 2) if total_rows > 0 else 0.0

        unique_vals = set(str(v) for v in non_nulls)
        unique_count = len(unique_vals)
        is_unique = (unique_count == total_rows) if total_rows > 0 else False

        inferred_type = self._infer_column_type(non_nulls)

        num_stats = None
        date_stats = None
        top_cats = None

        if inferred_type in ("integer", "decimal", "float"):
            num_stats = self._calc_numeric_stats(non_nulls)
        elif inferred_type in ("date", "datetime"):
            date_stats = self._calc_date_stats(non_nulls)
        elif inferred_type in ("string", "boolean"):
            top_cats = self._calc_categorical_distribution(non_nulls, len(non_nulls))

        return ColumnProfile(
            column_name=col_name,
            inferred_type=inferred_type,
            total_count=total_rows,
            null_count=null_count,
            null_percentage=null_pct,
            unique_count=unique_count,
            is_unique=is_unique,
            numeric_stats=num_stats,
            date_stats=date_stats,
            top_categories=top_cats,
        )

    def _infer_column_type(self, values: List[Any]) -> str:
        """Determine highest-probability logical type for non-null values."""
        if not values:
            return "unknown"
        sample = values[:100]
        if all(isinstance(v, bool) for v in sample):
            return "boolean"
        if all(isinstance(v, int) and not isinstance(v, bool) for v in sample):
            return "integer"
        if all(isinstance(v, (Decimal, float)) for v in sample):
            return "decimal"
        if all(isinstance(v, (datetime, date)) for v in sample):
            return "datetime"

        # Check string representations
        numeric_count = 0
        date_count = 0
        for v in sample:
            val_str = str(v).strip()
            try:
                float(val_str)
                numeric_count += 1
                continue
            except ValueError:
                pass
            try:
                datetime.fromisoformat(val_str)
                date_count += 1
                continue
            except ValueError:
                pass

        if numeric_count == len(sample):
            return "numeric"
        if date_count == len(sample):
            return "date"

        return "string"

    def _calc_numeric_stats(self, values: List[Any]) -> Optional[NumericStats]:
        """Calculate min, max, mean, median, and std_dev."""
        nums: List[float] = []
        for v in values:
            try:
                nums.append(float(v))
            except (ValueError, TypeError):
                continue

        if not nums:
            return None

        nums.sort()
        n = len(nums)
        min_v = nums[0]
        max_v = nums[-1]
        sum_v = sum(nums)
        mean_v = sum_v / n

        # Median
        if n % 2 == 1:
            median_v = nums[n // 2]
        else:
            median_v = (nums[n // 2 - 1] + nums[n // 2]) / 2.0

        # Std Dev
        if n > 1:
            variance = sum((x - mean_v) ** 2 for x in nums) / (n - 1)
            std_dev = math.sqrt(variance)
        else:
            std_dev = 0.0

        return NumericStats(
            min_value=round(min_v, 2),
            max_value=round(max_v, 2),
            mean=round(mean_v, 2),
            median=round(median_v, 2),
            std_dev=round(std_dev, 2),
            sum_value=round(sum_v, 2),
        )

    def _calc_date_stats(self, values: List[Any]) -> Optional[DateRangeStats]:
        """Calculate earliest and latest date bounds."""
        dates = []
        for v in values:
            if isinstance(v, datetime):
                dates.append(v)
            elif isinstance(v, date):
                dates.append(datetime.combine(v, datetime.min.time()))
            elif isinstance(v, str):
                try:
                    dates.append(datetime.fromisoformat(v))
                except ValueError:
                    pass

        if not dates:
            return None

        earliest = min(dates)
        latest = max(dates)
        duration = (latest - earliest).days

        return DateRangeStats(
            min_date=earliest.isoformat(),
            max_date=latest.isoformat(),
            duration_days=duration,
        )

    def _calc_categorical_distribution(
        self, values: List[Any], total: int, top_n: int = 5
    ) -> List[CategoricalValueCount]:
        """Compute top categorical frequencies."""
        if total == 0:
            return []
        counter = Counter(str(v) for v in values)
        results = []
        for val, count in counter.most_common(top_n):
            pct = round((count / total) * 100, 2)
            results.append(CategoricalValueCount(value=val, count=count, percentage=pct))
        return results
