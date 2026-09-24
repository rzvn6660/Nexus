"""FastAPI endpoints exposing deterministic analytics and evidence metadata."""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_db_session
from app.analytics.core.types import (
    PeriodGranularity,
    SortOrder,
    CorrelationMethod,
    HypothesisTestType,
)
from app.analytics.core.context import AnalysisContext
from app.analytics.core.exceptions import (
    AnalyticsError,
    InsufficientDataError,
    InvalidContextError,
)
from app.analytics.service import AnalyticsService
from app.schemas.analytics import (
    SummaryResponse,
    ProductRankingResponse,
    BreakdownResponse,
    TimeSeriesResponse,
    RFMResponse,
    CohortResponse,
    RepeatPurchaseResponse,
    InventoryOverviewResponse,
    InventoryTurnoverResponse,
    ExpenseResponse,
    VarianceResponse,
    DecompositionResponse,
    CorrelationResponse,
    StatisticalTestResponse,
)

router = APIRouter()


def _build_context(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    comparison_date_from: Optional[datetime] = None,
    comparison_date_to: Optional[datetime] = None,
    categories: Optional[List[str]] = None,
    subcategories: Optional[List[str]] = None,
    customer_segments: Optional[List[str]] = None,
    product_ids: Optional[List[int]] = None,
    customer_ids: Optional[List[int]] = None,
    granularity: PeriodGranularity = PeriodGranularity.MONTHLY,
) -> AnalysisContext:
    try:
        return AnalysisContext(
            date_from=date_from,
            date_to=date_to,
            comparison_date_from=comparison_date_from,
            comparison_date_to=comparison_date_to,
            categories=categories,
            subcategories=subcategories,
            customer_segments=customer_segments,
            product_ids=product_ids,
            customer_ids=customer_ids,
            granularity=granularity,
        )
    except InvalidContextError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/summary", response_model=SummaryResponse, summary="Executive 12-metric financial summary")
def get_summary(
    date_from: Optional[datetime] = Query(None, description="Start date (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="End date (ISO 8601)"),
    comparison_date_from: Optional[datetime] = Query(None, description="Baseline comparison start"),
    comparison_date_to: Optional[datetime] = Query(None, description="Baseline comparison end"),
    categories: Optional[List[str]] = Query(None),
    customer_segments: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
        categories=categories,
        customer_segments=customer_segments,
    )
    service = AnalyticsService(db)
    data, evidence = service.get_financial_summary(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/revenue", response_model=TimeSeriesResponse, summary="Revenue timeseries and growth")
def get_revenue(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    granularity: PeriodGranularity = Query(PeriodGranularity.MONTHLY),
    categories: Optional[List[str]] = Query(None),
    customer_segments: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        customer_segments=customer_segments,
        granularity=granularity,
    )
    service = AnalyticsService(db)
    data, evidence = service.get_timeseries_analytics(ctx, metric="revenue")
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/profit", response_model=TimeSeriesResponse, summary="Gross and net profit timeseries")
def get_profit(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    granularity: PeriodGranularity = Query(PeriodGranularity.MONTHLY),
    categories: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        granularity=granularity,
    )
    service = AnalyticsService(db)
    data, evidence = service.get_timeseries_analytics(ctx, metric="profit")
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/sales", response_model=TimeSeriesResponse, summary="Sales units and transaction orders timeseries")
def get_sales(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    granularity: PeriodGranularity = Query(PeriodGranularity.MONTHLY),
    categories: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        granularity=granularity,
    )
    service = AnalyticsService(db)
    data, evidence = service.get_timeseries_analytics(ctx, metric="units")
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/products", response_model=ProductRankingResponse, summary="Product performance rankings")
def get_products(
    ranking_metric: str = Query("revenue", description="Metric to rank by: revenue, profit, units, margin, velocity"),
    limit: int = Query(50, ge=1, le=500),
    sort_order: SortOrder = Query(SortOrder.DESC),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    categories: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, categories=categories)
    service = AnalyticsService(db)
    data, evidence = service.get_product_rankings(
        ctx, ranking_metric=ranking_metric, limit=limit, sort_order=sort_order
    )
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/categories", response_model=BreakdownResponse, summary="Product category performance breakdown")
def get_categories(
    metric: str = Query("revenue", description="Metric to rank: revenue, profit, units, orders"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to)
    service = AnalyticsService(db)
    data, evidence = service.get_category_breakdown(ctx, metric=metric)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/customers", response_model=BreakdownResponse, summary="Customer segment performance breakdown")
def get_customers(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to)
    service = AnalyticsService(db)
    data, evidence = service.get_customer_segments_breakdown(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/rfm", response_model=RFMResponse, summary="Customer RFM segmentation and scores")
def get_rfm(
    quantile_bins: int = Query(5, ge=3, le=10),
    limit_top: int = Query(50, ge=1, le=500),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    customer_segments: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, customer_segments=customer_segments)
    service = AnalyticsService(db)
    data, evidence = service.get_rfm_analysis(ctx, quantile_bins=quantile_bins, limit_top=limit_top)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/cohorts", response_model=CohortResponse, summary="Customer cohort retention analysis")
def get_cohorts(
    max_periods: int = Query(12, ge=1, le=24),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    customer_segments: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, customer_segments=customer_segments)
    service = AnalyticsService(db)
    data, evidence = service.get_cohort_analysis(ctx, max_periods=max_periods)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/repeat-purchase", response_model=RepeatPurchaseResponse, summary="Repeat purchase metrics")
def get_repeat_purchase(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to)
    service = AnalyticsService(db)
    data, evidence = service.get_repeat_purchase_metrics(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/inventory", response_model=InventoryOverviewResponse, summary="Current inventory health and alerts")
def get_inventory(
    warehouse: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db_session),
):
    service = AnalyticsService(db)
    data, evidence = service.get_inventory_overview(warehouse=warehouse, category=category)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/inventory/turnover", response_model=InventoryTurnoverResponse, summary="Inventory turnover ratio and DSI")
def get_inventory_turnover(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    categories: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, categories=categories)
    service = AnalyticsService(db)
    data, evidence = service.get_inventory_turnover(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/expenses", response_model=ExpenseResponse, summary="Operating expense breakdown and comparison")
def get_expenses(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    comparison_date_from: Optional[datetime] = Query(None),
    comparison_date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
    )
    service = AnalyticsService(db)
    data, evidence = service.get_expense_analytics(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/timeseries", response_model=TimeSeriesResponse, summary="Custom metric timeseries")
def get_timeseries(
    metric: str = Query("revenue", description="revenue, profit, units, orders"),
    granularity: PeriodGranularity = Query(PeriodGranularity.MONTHLY),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    categories: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, categories=categories, granularity=granularity)
    service = AnalyticsService(db)
    data, evidence = service.get_timeseries_analytics(ctx, metric=metric)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/variance", response_model=VarianceResponse, summary="Diagnostic revenue variance breakdown")
def get_variance(
    dimension: str = Query("product", description="Dimension to dissect: product, category, customer_segment"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    comparison_date_from: Optional[datetime] = Query(None),
    comparison_date_to: Optional[datetime] = Query(None),
    top_n: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
    )
    if not ctx.has_comparison:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Variance analysis requires comparison_date_from and comparison_date_to query parameters.",
        )
    service = AnalyticsService(db)
    data, evidence = service.get_variance_analysis(ctx, dimension=dimension)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/decomposition", response_model=DecompositionResponse, summary="Price / Volume / Mix decomposition")
def get_decomposition(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    comparison_date_from: Optional[datetime] = Query(None),
    comparison_date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
    )
    if not ctx.has_comparison:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Price/Volume/Mix decomposition requires comparison_date_from and comparison_date_to.",
        )
    service = AnalyticsService(db)
    data, evidence = service.get_pvm_decomposition(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/statistics/correlation", response_model=CorrelationResponse, summary="Bivariate correlation")
def get_correlation(
    variable_x: str = Query("subtotal", description="subtotal, quantity, discount_amount, total_amount"),
    variable_y: str = Query("quantity", description="subtotal, quantity, discount_amount, total_amount"),
    method: CorrelationMethod = Query(CorrelationMethod.PEARSON),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to)
    service = AnalyticsService(db)
    try:
        data, evidence = service.get_bivariate_correlation(
            variable_x=variable_x, variable_y=variable_y, context=ctx, method=method
        )
        return {"success": True, "data": data, "evidence": evidence}
    except InsufficientDataError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/statistics/hypothesis", response_model=StatisticalTestResponse, summary="Hypothesis testing")
def get_hypothesis(
    group1: str = Query("Corporate", description="First customer segment"),
    group2: str = Query("Retail", description="Second customer segment"),
    metric: str = Query("order_value", description="Metric to compare"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to)
    service = AnalyticsService(db)
    try:
        data, evidence = service.get_hypothesis_test(
            group1_segment=group1, group2_segment=group2, metric=metric, context=ctx
        )
        return {"success": True, "data": data, "evidence": evidence}
    except InsufficientDataError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
