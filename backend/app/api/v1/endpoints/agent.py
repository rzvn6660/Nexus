"""API router exposing deterministic agent analytics workflows."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.agents.service import NexusAgentService
from app.core.database import get_db
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
    db: Session = Depends(get_db),
) -> AgentResponse:
    """Entrypoint for agentic analytical requests."""
    service = NexusAgentService(db)
    return service.run_analysis(
        query=payload.query,
        explanation_level=payload.explanation_level,
        reference_date=payload.reference_date,
        is_investigation=payload.is_investigation,
    )
