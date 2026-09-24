"""Tests for diagnostic variance analysis and Price / Volume / Mix decomposition."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.analytics.core.context import AnalysisContext
from app.analytics.core.types import TrendDirection
from app.analytics.diagnostic.variance import VarianceDiagnosticAnalyzer
from app.analytics.diagnostic.decomposition import PriceVolumeMixAnalyzer


def test_variance_analysis_dissection(multi_period_db: Session):
    """Verify revenue variance decomposition across products."""
    context = AnalysisContext(
        date_from=datetime(2023, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, tzinfo=timezone.utc),
        comparison_date_from=datetime(2023, 5, 1, tzinfo=timezone.utc),
        comparison_date_to=datetime(2023, 5, 31, tzinfo=timezone.utc),
    )
    result = VarianceDiagnosticAnalyzer.analyze_revenue_variance(
        multi_period_db, context, dimension="product"
    )

    # May total = 155.00
    # June total = 340.00
    # Variance = +185.00
    assert result.prior_period_value == Decimal("155.00")
    assert result.current_period_value == Decimal("340.00")
    assert result.total_variance == Decimal("185.00")
    assert result.direction == TrendDirection.INCREASE

    # Check top positive contributors
    # SKU-B: June 200.00 - May 90.00 = +110.00
    # SKU-A: June 140.00 - May 65.00 = +75.00
    assert len(result.top_positive_contributors) == 2
    top1 = result.top_positive_contributors[0]
    assert top1.entity_id == "SKU-B"
    assert top1.absolute_change == Decimal("110.00")
    assert top1.contribution_to_change_pct == round((110.0 / 185.0) * 100.0, 2)

    top2 = result.top_positive_contributors[1]
    assert top2.entity_id == "SKU-A"
    assert top2.absolute_change == Decimal("75.00")
    assert top2.contribution_to_change_pct == round((75.0 / 185.0) * 100.0, 2)


def test_price_volume_mix_decomposition_reconciliation(multi_period_db: Session):
    """Verify that Volume + Price + Mix exactly reconciles with Total Variance."""
    context = AnalysisContext(
        date_from=datetime(2023, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, tzinfo=timezone.utc),
        comparison_date_from=datetime(2023, 5, 1, tzinfo=timezone.utc),
        comparison_date_to=datetime(2023, 5, 31, tzinfo=timezone.utc),
    )
    decomp = PriceVolumeMixAnalyzer.decompose(multi_period_db, context)

    # Total variance = 340.00 - 155.00 = 185.00
    assert decomp.prior_revenue == Decimal("155.00")
    assert decomp.current_revenue == Decimal("340.00")
    assert decomp.total_variance == Decimal("185.00")

    # Critical mathematical identity:
    # Volume Effect + Price Effect + Mix Effect == Total Variance
    calculated_sum = decomp.volume_effect + decomp.price_effect + decomp.mix_effect
    assert calculated_sum == decomp.total_variance
    assert decomp.reconciled is True
