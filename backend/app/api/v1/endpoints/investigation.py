"""API endpoints for Phase 6 Diagnostic Investigation Engine."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.investigation.engine import InvestigationEngine
from app.investigation.schemas import InvestigationRequest, InvestigationResponse

router = APIRouter()


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
    db: Session = Depends(get_db),
) -> InvestigationResponse:
    """Entrypoint for diagnostic investigation requests."""
    engine = InvestigationEngine(db)
    return engine.investigate(
        query=payload.query,
        explanation_level=payload.explanation_level,
        reference_date=payload.reference_date,
    )
