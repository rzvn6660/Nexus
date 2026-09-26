"""API router exposing deterministic agent analytics workflows."""

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.service import NexusAgentService
from app.core.auth import get_optional_current_user, verify_user_business_access
from app.core.database import get_db
from app.models.tenant import Business, OrganizationMembership, UserIdentity
from app.schemas.agent import AgentAnalyzeRequest, AgentResponse

router = APIRouter()


@router.post(
    "/analyze",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute agentic business intelligence analysis",
    description=(
        "Processes natural language business questions using a stateful LangGraph "
        "agent orchestrating deterministic SQL and analytics tools. Returns grounded explanations, "
        "traceable EvidenceRecords, calculations, and follow-up guidance."
    ),
)
def analyze_business_query(
    payload: AgentAnalyzeRequest,
    x_business_id: str | None = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
) -> AgentResponse:
    """Entrypoint for agentic analytical requests."""
    business_id = x_business_id
    organization_id = None
    user_id = current_user.id if current_user else None

    if current_user:
        if x_business_id:
            biz = verify_user_business_access(
                db, current_user, x_business_id, action="execute analytical queries for"
            )
            business_id = biz.id
            organization_id = biz.organization_id
        else:
            user_org_ids = db.execute(
                select(OrganizationMembership.organization_id).where(
                    OrganizationMembership.user_id == current_user.id
                )
            ).scalars().all()
            biz = db.execute(
                select(Business).where(Business.organization_id.in_(user_org_ids))
            ).scalars().first()
            if biz:
                business_id = biz.id
                organization_id = biz.organization_id

    service = NexusAgentService(db)
    return service.run_analysis(
        query=payload.query,
        explanation_level=payload.explanation_level,
        reference_date=payload.reference_date,
        is_investigation=payload.is_investigation,
        is_forecast=payload.is_forecast,
        organization_id=organization_id,
        business_id=business_id,
        user_id=user_id,
    )
