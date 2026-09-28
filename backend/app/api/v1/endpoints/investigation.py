"""API endpoints for Phase 6 Diagnostic Investigation Engine."""

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_optional_current_user, verify_user_business_access
from app.core.database import get_db
from app.investigation.engine import InvestigationEngine
from app.investigation.schemas import InvestigationRequest, InvestigationResponse
from app.models.tenant import Business, OrganizationMembership, UserIdentity

router = APIRouter()


def _resolve_tenant_business_id(
    db: Session,
    current_user: UserIdentity | None = None,
    x_business_id: str | None = None,
) -> str | None:
    if current_user:
        if x_business_id:
            biz = verify_user_business_access(
                db, current_user, x_business_id, action="access investigation for"
            )
            return biz.id
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
    return x_business_id


@router.post(
    "/analyze",
    response_model=InvestigationResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute diagnostic business investigation",
    description=(
        "Executes a multi-step, evidence-backed diagnostic investigation to answer "
        "'Why did this happen?'. Decomposes the business variance across categories, products, "
        "and economic price/volume/mix effects, generates and tests hypotheses, audits evidence gaps, "
        "and returns audited conclusions with strict causality safeguards."
    ),
)
def analyze_investigation(
    payload: InvestigationRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    """Entrypoint for diagnostic investigation requests."""
    biz_id = _resolve_tenant_business_id(db, current_user, x_business_id)
    engine = InvestigationEngine(db, business_id=biz_id)
    return engine.investigate(
        query=payload.query,
        explanation_level=payload.explanation_level,
        reference_date=payload.reference_date,
    )
