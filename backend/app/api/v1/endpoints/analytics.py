"""FastAPI endpoints exposing deterministic analytics and evidence metadata."""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db_session
from app.core.auth import get_optional_current_user, verify_user_business_access
from app.models.tenant import Business, OrganizationMembership, UserIdentity
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
    GrossToNetResponse,
    CadenceResponse,
    RetentionOverviewResponse,
    RetentionCustomerListApiResponse,
    RetentionCustomerDetailResponse,
    RetentionOutcomeEvaluationResponse,
)
from app.schemas.retention import (
    RetentionCustomerFilter,
    RetentionActionCreateRequest,
    RetentionActionReviewRequest,
    RetentionActionExecuteRequest,
    RetentionCustomerResponseRequest,
)

router = APIRouter()


def _resolve_tenant_business_id(
    db: Session,
    current_user: Optional[UserIdentity] = None,
    x_business_id: Optional[str] = None,
) -> Optional[str]:
    if x_business_id:
        biz = verify_user_business_access(
            db, current_user, x_business_id, action="access analytics for"
        )
        return biz.id
    if current_user:
        user_org_ids = db.execute(
            select(OrganizationMembership.organization_id).where(
                OrganizationMembership.user_id == current_user.id
            )
        ).scalars().all()
        biz = db.execute(
            select(Business).where(Business.organization_id.in_(user_org_ids))
        ).scalars().first()
        if biz:
            return biz.id
    return None


def get_analytics_business_id(
    db: Session = Depends(get_db_session),
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
) -> Optional[str]:
    return _resolve_tenant_business_id(db, current_user, x_business_id)


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
    business_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> AnalysisContext:
    currency = "USD"
    if business_id and db:
        biz_currency = db.execute(
            select(Business.currency).where(Business.id == business_id)
        ).scalar_one_or_none()
        if biz_currency:
            currency = biz_currency
    try:
        return AnalysisContext(
            business_id=business_id,
            currency=currency,
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
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
        categories=categories,
        customer_segments=customer_segments,
        business_id=biz_id,
        db=db,
    )
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_financial_summary(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/waterfall/gross-to-net", response_model=GrossToNetResponse, summary="Commercial Gross-to-Net revenue waterfall")
def get_gross_to_net(
    date_from: Optional[datetime] = Query(None, description="Start date (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="End date (ISO 8601)"),
    categories: Optional[List[str]] = Query(None),
    customer_segments: Optional[List[str]] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        customer_segments=customer_segments,
        business_id=biz_id,
        db=db,
    )
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_gross_to_net_waterfall(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/revenue", response_model=TimeSeriesResponse, summary="Revenue timeseries and growth")
def get_revenue(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    granularity: PeriodGranularity = Query(PeriodGranularity.MONTHLY),
    categories: Optional[List[str]] = Query(None),
    customer_segments: Optional[List[str]] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        customer_segments=customer_segments,
        granularity=granularity,
        business_id=biz_id,
    )
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_timeseries_analytics(ctx, metric="revenue")
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/profit", response_model=TimeSeriesResponse, summary="Gross and net profit timeseries")
def get_profit(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    granularity: PeriodGranularity = Query(PeriodGranularity.MONTHLY),
    categories: Optional[List[str]] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        granularity=granularity,
        business_id=biz_id,
    )
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_timeseries_analytics(ctx, metric="profit")
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/sales", response_model=TimeSeriesResponse, summary="Sales units and transaction orders timeseries")
def get_sales(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    granularity: PeriodGranularity = Query(PeriodGranularity.MONTHLY),
    categories: Optional[List[str]] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        granularity=granularity,
        business_id=biz_id,
    )
    service = AnalyticsService(db, business_id=biz_id)
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
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, categories=categories, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_product_rankings(
        ctx, ranking_metric=ranking_metric, limit=limit, sort_order=sort_order
    )
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/categories", response_model=BreakdownResponse, summary="Product category performance breakdown")
def get_categories(
    metric: str = Query("revenue", description="Metric to rank: revenue, profit, units, orders"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_category_breakdown(ctx, metric=metric)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/customers", response_model=BreakdownResponse, summary="Customer segment performance breakdown")
def get_customers(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_customer_segments_breakdown(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/rfm", response_model=RFMResponse, summary="Customer RFM segmentation and scores")
def get_rfm(
    quantile_bins: int = Query(5, ge=3, le=10),
    limit_top: int = Query(50, ge=1, le=500),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    customer_segments: Optional[List[str]] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, customer_segments=customer_segments, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_rfm_analysis(ctx, quantile_bins=quantile_bins, limit_top=limit_top)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/cohorts", response_model=CohortResponse, summary="Customer cohort retention analysis")
def get_cohorts(
    max_periods: int = Query(12, ge=1, le=24),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    customer_segments: Optional[List[str]] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, customer_segments=customer_segments, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_cohort_analysis(ctx, max_periods=max_periods)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/repeat-purchase", response_model=RepeatPurchaseResponse, summary="Repeat purchase metrics")
def get_repeat_purchase(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_repeat_purchase_metrics(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/cadence", response_model=CadenceResponse, summary="Customer purchase cadence with safety gates")
def get_cadence(
    date_to: Optional[datetime] = Query(None),
    required_sources: Optional[List[str]] = Query(None),
    seasonal_context: Optional[str] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    summary, verdict, evidence = service.get_customer_cadence_analysis(
        context=ctx,
        as_of_date=date_to,
        required_sources=required_sources,
        seasonal_context=seasonal_context,
    )
    return {
        "success": True,
        "data": {
            "summary": summary,
            "safety_verdict": verdict,
        },
        "evidence": evidence,
    }


# ==============================================================================
# Customer Retention & Intelligent Churn Prediction Endpoints
# ==============================================================================

@router.get("/retention/overview", response_model=RetentionOverviewResponse, summary="Executive & operational retention overview with safety gates")
def get_retention_overview(
    date_to: Optional[datetime] = Query(None),
    required_sources: Optional[List[str]] = Query(None),
    seasonal_context: Optional[str] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    ctx = _build_context(date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    overview, evidence = service.get_retention_overview(
        context=ctx,
        as_of_date=date_to,
        required_sources=required_sources,
        seasonal_context=seasonal_context,
    )
    return {"success": True, "data": overview, "evidence": evidence}


@router.get("/retention/customers", response_model=RetentionCustomerListApiResponse, summary="List & prioritize at-risk customers with retention recommendations")
def list_retention_customers(
    risk_tier: Optional[str] = Query(None, description="Filter by risk tier: critical, high, medium, low, insufficient_history"),
    urgency: Optional[str] = Query(None, description="Filter by urgency: immediate, proactive, watchlist, healthy, insufficient_history"),
    segment: Optional[str] = Query(None, description="Filter by customer segment"),
    search: Optional[str] = Query(None, description="Search by customer code or name"),
    requires_attention_only: bool = Query(False, description="Filter strictly to Critical and High risk repeat buyers"),
    is_repeat_only: bool = Query(True, description="Filter strictly to repeat buyers (>= 2 completed purchases)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    ctx = _build_context(date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)

    filters = RetentionCustomerFilter(
        risk_tiers=[risk_tier] if risk_tier else None,
        urgencies=[urgency] if urgency else None,
        segments=[segment] if segment else None,
        search=search,
        requires_attention_only=requires_attention_only,
        is_repeat_only=is_repeat_only,
        page=page,
        page_size=page_size,
    )
    data, evidence = service.list_customers_at_risk(
        context=ctx,
        filters=filters,
        as_of_date=date_to,
    )
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/retention/customers/{customer_id}", response_model=RetentionCustomerDetailResponse, summary="Deep-dive customer risk profile, cadence progression, and retention proposal")
def get_retention_customer_detail(
    customer_id: int,
    date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    ctx = _build_context(date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    detail, evidence = service.get_customer_risk_detail(
        customer_id=customer_id,
        context=ctx,
        as_of_date=date_to,
    )
    return {"success": True, "data": detail, "evidence": evidence}


@router.post("/retention/actions/recommend", summary="Register a prescriptive retention recommendation in the HITL ledger")
def create_retention_recommendation(
    payload: RetentionActionCreateRequest,
    current_user: Optional[UserIdentity] = Depends(get_optional_current_user),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    service = AnalyticsService(db, business_id=biz_id)
    record = service.create_retention_decision(
        customer_id=payload.customer_id,
        action_type=payload.action_type,
        custom_notes=payload.custom_notes,
        current_user=current_user,
    )
    return {
        "success": True,
        "data": {
            "decision_id": record.id,
            "status": record.status,
            "recommendation_text": record.recommendation_text,
            "action_target_id": record.action_target_id,
            "current_revision": record.current_revision,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        },
    }


@router.post("/retention/actions/review", summary="Record merchant review disposition for a retention decision (HITL)")
def review_retention_recommendation(
    payload: RetentionActionReviewRequest,
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    current_user: Optional[UserIdentity] = Depends(get_optional_current_user),
    db: Session = Depends(get_db_session),
):
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    reviewer_identity = (current_user.email if current_user and current_user.email else None) or payload.reviewer_id or "merchant_admin"
    service = AnalyticsService(db, business_id=biz_id)
    record = service.review_retention_decision(
        decision_id=payload.decision_id,
        status=payload.status,
        reviewer_id=reviewer_identity,
        reviewer_notes=payload.reviewer_notes,
        modified_action_type=payload.modified_action_type,
    )
    return {
        "success": True,
        "data": {
            "decision_id": record.id,
            "status": record.status,
            "reviewed_by": record.reviewed_by,
            "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
            "current_revision": record.current_revision,
        },
    }


@router.post("/retention/actions/execute", summary="Record execution of an approved retention action")
def execute_retention_action_endpoint(
    payload: RetentionActionExecuteRequest,
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    current_user: Optional[UserIdentity] = Depends(get_optional_current_user),
    db: Session = Depends(get_db_session),
):
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    executor_identity = (current_user.email if current_user and current_user.email else None) or payload.executed_by or "merchant_operator"
    service = AnalyticsService(db, business_id=biz_id)
    record = service.execute_retention_action(
        decision_id=payload.decision_id,
        execution_channel=payload.execution_channel,
        executed_by=executor_identity,
        execution_notes=payload.execution_notes,
        offer_code=payload.offer_code,
        execution_date=payload.execution_date,
    )
    return {
        "success": True,
        "data": {
            "decision_id": record.id,
            "status": "EXECUTED",
            "current_revision": record.current_revision,
            "executed_by": executor_identity,
            "execution_channel": payload.execution_channel,
        },
    }


@router.post("/retention/actions/response", summary="Log customer response to an executed retention intervention")
def log_customer_response_endpoint(
    payload: RetentionCustomerResponseRequest,
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    current_user: Optional[UserIdentity] = Depends(get_optional_current_user),
    db: Session = Depends(get_db_session),
):
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    logger_identity = (current_user.email if current_user and current_user.email else None) or payload.logged_by or "merchant_operator"
    service = AnalyticsService(db, business_id=biz_id)
    record = service.log_customer_response(
        decision_id=payload.decision_id,
        response_status=payload.response_status,
        logged_by=logger_identity,
        response_notes=payload.response_notes,
        response_date=payload.response_date,
    )
    return {
        "success": True,
        "data": {
            "decision_id": record.id,
            "current_revision": record.current_revision,
            "response_status": payload.response_status,
            "logged_by": logger_identity,
        },
    }


@router.get("/retention/evaluation", response_model=RetentionOutcomeEvaluationResponse, summary="Evaluate retention intervention outcomes vs comparison cohorts")
def get_retention_evaluation(
    evaluation_window_days: int = Query(30, ge=7, le=365, description="Forward evaluation window in days"),
    date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    if not biz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context is required. Provide X-Business-ID header.",
        )
    ctx = _build_context(date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    evaluation, evidence = service.evaluate_retention_outcomes(
        context=ctx,
        evaluation_window_days=evaluation_window_days,
        as_of_date=date_to,
    )
    return {"success": True, "data": evaluation, "evidence": evidence}


@router.get("/inventory", response_model=InventoryOverviewResponse, summary="Current inventory health and alerts")
def get_inventory(
    warehouse: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_inventory_overview(warehouse=warehouse, category=category)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/inventory/turnover", response_model=InventoryTurnoverResponse, summary="Inventory turnover ratio and DSI")
def get_inventory_turnover(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    categories: Optional[List[str]] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, categories=categories, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_inventory_turnover(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/expenses", response_model=ExpenseResponse, summary="Operating expense breakdown and comparison")
def get_expenses(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    comparison_date_from: Optional[datetime] = Query(None),
    comparison_date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
        business_id=biz_id,
    )
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_expense_analytics(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/timeseries", response_model=TimeSeriesResponse, summary="Custom metric timeseries")
def get_timeseries(
    metric: str = Query("revenue", description="revenue, profit, units, orders"),
    granularity: PeriodGranularity = Query(PeriodGranularity.MONTHLY),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    categories: Optional[List[str]] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, categories=categories, granularity=granularity, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
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
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
        business_id=biz_id,
    )
    if not ctx.has_comparison:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Variance analysis requires comparison_date_from and comparison_date_to query parameters.",
        )
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_variance_analysis(ctx, dimension=dimension)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/decomposition", response_model=DecompositionResponse, summary="Price / Volume / Mix decomposition")
def get_decomposition(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    comparison_date_from: Optional[datetime] = Query(None),
    comparison_date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(
        date_from=date_from,
        date_to=date_to,
        comparison_date_from=comparison_date_from,
        comparison_date_to=comparison_date_to,
        business_id=biz_id,
    )
    if not ctx.has_comparison:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Price/Volume/Mix decomposition requires comparison_date_from and comparison_date_to.",
        )
    service = AnalyticsService(db, business_id=biz_id)
    data, evidence = service.get_pvm_decomposition(ctx)
    return {"success": True, "data": data, "evidence": evidence}


@router.get("/statistics/correlation", response_model=CorrelationResponse, summary="Bivariate correlation")
def get_correlation(
    variable_x: str = Query("subtotal", description="subtotal, quantity, discount_amount, total_amount"),
    variable_y: str = Query("quantity", description="subtotal, quantity, discount_amount, total_amount"),
    method: CorrelationMethod = Query(CorrelationMethod.PEARSON),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
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
    biz_id: Optional[str] = Depends(get_analytics_business_id),
    db: Session = Depends(get_db_session),
):
    ctx = _build_context(date_from=date_from, date_to=date_to, business_id=biz_id)
    service = AnalyticsService(db, business_id=biz_id)
    try:
        data, evidence = service.get_hypothesis_test(
            group1_segment=group1, group2_segment=group2, metric=metric, context=ctx
        )
        return {"success": True, "data": data, "evidence": evidence}
    except InsufficientDataError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
