"""API endpoints for NEXUS Continuous Intelligence (Phase 29)."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.continuous.schemas import (
    ContinuousFindingListResponse,
    ContinuousFindingResponse,
    ContinuousScanRequest,
    ContinuousScanResponse,
    FindingDecisionLinkRequest,
    FindingFeedbackRequest,
    FindingFeedbackResponse,
    FindingStatus,
)
from app.analytics.continuous.service import ContinuousIntelligenceService
from app.api.deps import get_db_session
from app.core.auth import get_current_user
from app.models.tenant import OrganizationMembership, UserIdentity

router = APIRouter()


def _resolve_business_id(x_business_id: str | None) -> str:
    if not x_business_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Header 'X-Business-ID' is required for continuous intelligence operations.",
        )
    return x_business_id


@router.post(
    "/scan",
    response_model=ContinuousScanResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute continuous intelligence metric shift scan",
)
def run_continuous_scan(
    payload: ContinuousScanRequest | None = None,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ContinuousScanResponse:
    """Run deterministic detection scan across supported business metrics."""
    target_biz_id = _resolve_business_id(x_business_id)
    return ContinuousIntelligenceService.execute_business_scan(
        db=db,
        current_user=current_user,
        business_id=target_biz_id,
        scan_request=payload,
        trigger_type="MANUAL",
    )


@router.post(
    "/reconcile",
    response_model=list[ContinuousScanResponse],
    status_code=status.HTTP_200_OK,
    summary="Reconcile pending continuous intelligence scans",
)
def reconcile_pending_scans(
    limit: int = Query(10, ge=1, le=50, description="Maximum pending scans to reconcile"),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[ContinuousScanResponse]:
    """Operational endpoint to reconcile completed ingestion jobs lacking continuous scans."""
    target_biz_id = _resolve_business_id(x_business_id)
    return ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db,
        business_id=target_biz_id,
        current_user=current_user,
        limit=limit,
    )


@router.get(
    "/scheduler/status",
    summary="Get autonomous continuous scheduler status and telemetry",
)
def get_scheduler_status(
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> dict:
    """Return runtime configuration and telemetry of the autonomous continuous scheduler.

    Requires administrative privileges (owner or admin role in an active organization).
    """
    admin_membership = db.execute(
        select(OrganizationMembership.id).where(
            OrganizationMembership.user_id == current_user.id,
            OrganizationMembership.role.in_(["owner", "admin"]),
        )
    ).scalar_one_or_none()

    if not admin_membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Administrative privileges (owner or admin role) required to view scheduler telemetry.",
        )

    from app.analytics.continuous.scheduler import continuous_scheduler

    return continuous_scheduler.stats


@router.get(
    "/findings",
    response_model=ContinuousFindingListResponse,
    summary="List proactive business findings",
)
def list_findings(
    status: str | None = Query(None, description="Filter by status (ACTIVE, ACKNOWLEDGED, DISMISSED, RESOLVED)"),
    severity: str | None = Query(None, description="Filter by severity (LOW, MEDIUM, HIGH, CRITICAL)"),
    metric_key: str | None = Query(None, description="Filter by metric key"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ContinuousFindingListResponse:
    """Retrieve filtered findings scoped to authorized business."""
    target_biz_id = _resolve_business_id(x_business_id)
    return ContinuousIntelligenceService.list_findings(
        db=db,
        current_user=current_user,
        business_id=target_biz_id,
        status_filter=status,
        severity_filter=severity,
        metric_filter=metric_key,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/findings/{finding_id}",
    response_model=ContinuousFindingResponse,
    summary="Retrieve continuous finding details",
)
def get_finding(
    finding_id: int,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ContinuousFindingResponse:
    """Retrieve detailed observation with Tukey IQR fences and calculation details."""
    target_biz_id = _resolve_business_id(x_business_id)
    return ContinuousIntelligenceService.get_finding_detail(
        db=db,
        current_user=current_user,
        business_id=target_biz_id,
        finding_id=finding_id,
    )


@router.patch(
    "/findings/{finding_id}/status",
    response_model=ContinuousFindingResponse,
    summary="Update finding lifecycle status",
)
def update_status(
    finding_id: int,
    status: FindingStatus = Query(..., description="Target finding status"),
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ContinuousFindingResponse:
    """Acknowledge, dismiss, or resolve a proactive finding."""
    target_biz_id = _resolve_business_id(x_business_id)
    return ContinuousIntelligenceService.update_finding_status(
        db=db,
        current_user=current_user,
        business_id=target_biz_id,
        finding_id=finding_id,
        new_status=status,
    )


@router.post(
    "/findings/{finding_id}/feedback",
    response_model=FindingFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record human feedback on a continuous finding",
)
def record_feedback(
    finding_id: int,
    payload: FindingFeedbackRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> FindingFeedbackResponse:
    """Capture executive/analyst rating of finding relevance and false-positive status."""
    target_biz_id = _resolve_business_id(x_business_id)
    return ContinuousIntelligenceService.record_finding_feedback(
        db=db,
        current_user=current_user,
        business_id=target_biz_id,
        finding_id=finding_id,
        feedback_type=payload.feedback_type,
        notes=payload.notes,
    )


@router.post(
    "/findings/{finding_id}/link-decision",
    response_model=ContinuousFindingResponse,
    summary="Link continuous finding to a DecisionRecord",
)
def link_decision(
    finding_id: int,
    payload: FindingDecisionLinkRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ContinuousFindingResponse:
    """Connect proactive observation to an approved Human-in-the-Loop decision."""
    target_biz_id = _resolve_business_id(x_business_id)
    return ContinuousIntelligenceService.link_finding_to_decision(
        db=db,
        current_user=current_user,
        business_id=target_biz_id,
        finding_id=finding_id,
        decision_id=payload.decision_id,
    )
