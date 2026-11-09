"""FastAPI Endpoints for NEXUS Adaptive Analyst Engine & PostgreSQL Onboarding."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.analyst.models import SkillDomain, SkillMetadata
from app.analytics.analyst.service import AnalystService
from app.analytics.onboarding.postgres_service import PostgreSQLOnboardingService
from app.api.deps import get_db_session
from app.core.auth import get_current_user, verify_user_business_access
from app.models.tenant import Business, OrganizationMembership, UserIdentity

router = APIRouter()


def _resolve_business_id(
    db: Session,
    current_user: UserIdentity,
    x_business_id: Optional[str] = None,
) -> str:
    """Resolve and authorize tenant workspace ID."""
    if x_business_id:
        biz = verify_user_business_access(db, current_user, x_business_id, action="access analyst engine for")
        return biz.id

    user_org_ids = db.execute(
        select(OrganizationMembership.organization_id).where(OrganizationMembership.user_id == current_user.id)
    ).scalars().all()
    if user_org_ids:
        biz = db.execute(select(Business).where(Business.organization_id.in_(user_org_ids))).scalars().first()
        if biz:
            return biz.id

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Tenant context required. Provide X-Business-ID header.",
    )


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class AnalyzeQuestionRequest(BaseModel):
    query: str = Field(..., description="Natural language business question")


class ToggleSkillRequest(BaseModel):
    enabled: bool = Field(..., description="Target enable status for the analyst skill")


class PostgresConnectionConfig(BaseModel):
    host: str = Field(..., description="PostgreSQL server hostname or IP")
    port: int = Field(5432, description="PostgreSQL port")
    database: str = Field(..., description="Target database name")
    user: str = Field(..., description="Database username")
    password: str = Field(..., description="Database user password")
    sslmode: str = Field("prefer", description="SSL mode: disable, require, prefer")


class PostgresTablePreviewRequest(PostgresConnectionConfig):
    table_name: str = Field(..., description="Table name to preview")
    schema_name: str = Field("public", description="Schema name (defaults to public)")
    limit: int = Field(15, description="Maximum sample rows to retrieve")


class PostgresIngestRequest(PostgresConnectionConfig):
    table_name: str = Field(..., description="Source PostgreSQL table name")
    schema_name: str = Field("public", description="Schema name")
    target_entity: str = Field("Sale", description="Target canonical entity: Sale, Customer, Product")
    column_mapping: Dict[str, str] = Field(
        ...,
        description="Source column name to Canonical field mapping (e.g. {'order_id': 'order_number', 'amount': 'amount', 'date': 'date'})",
    )
    max_rows: int = Field(50_000, description="Maximum rows to ingest in single transaction")


# ---------------------------------------------------------------------------
# Analyst Studio & Orchestration Endpoints
# ---------------------------------------------------------------------------

@router.get("/overview", summary="Analyst Studio Telemetry Overview")
def get_analyst_overview(
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve telemetry overview for the Analyst Studio dashboard."""
    biz_id = _resolve_business_id(db, current_user, x_business_id)
    return AnalystService.get_overview(db, biz_id)


@router.get("/skills", response_model=List[SkillMetadata], summary="List Registered Analyst Skills")
def list_analyst_skills(
    domain: Optional[SkillDomain] = Query(None, description="Optional domain filter"),
    current_user: UserIdentity = Depends(get_current_user),
) -> List[SkillMetadata]:
    """List all registered analyst skills across the 8 specialist domains."""
    return AnalystService.list_skills(domain)


@router.post("/skills/{skill_id}/toggle", summary="Enable or Disable an Analyst Skill")
def toggle_analyst_skill(
    skill_id: str,
    payload: ToggleSkillRequest,
    current_user: UserIdentity = Depends(get_current_user),
) -> Dict[str, Any]:
    """Safely enable or disable an analytical skill in the central registry."""
    success = AnalystService.toggle_skill(skill_id, payload.enabled)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_id}' not found in registry.",
        )
    return {"skill_id": skill_id, "enabled": payload.enabled, "status": "UPDATED"}


@router.post("/analyze", summary="Execute Automated Multi-Skill Analysis")
def analyze_question(
    payload: AnalyzeQuestionRequest,
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Execute end-to-end multi-skill analysis:
    Understands question, dynamically selects specialist skills, executes dependency graph,
    reconciles findings via Lead Analyst, and persists run to immutable Evidence Ledger.
    """
    biz_id = _resolve_business_id(db, current_user, x_business_id)
    try:
        return AnalystService.analyze_business_question(
            db=db,
            business_id=biz_id,
            query=payload.query,
            user_id=current_user.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/runs", summary="List Historical Analysis Runs")
def list_analysis_runs(
    limit: int = Query(50, ge=1, le=100),
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List prior analysis runs and executive summaries from the Evidence Ledger."""
    biz_id = _resolve_business_id(db, current_user, x_business_id)
    return AnalystService.list_runs(db, biz_id, limit)


@router.get("/runs/{run_id}", summary="Get Detailed Analysis Run & Evidence")
def get_analysis_run(
    run_id: int,
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve full audit trace: execution plan, skill outputs, and calculations."""
    biz_id = _resolve_business_id(db, current_user, x_business_id)
    run_detail = AnalystService.get_run_detail(db, biz_id, run_id)
    if not run_detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found.")
    return run_detail


# ---------------------------------------------------------------------------
# PostgreSQL Relational Onboarding Endpoints
# ---------------------------------------------------------------------------

@router.post("/onboard/postgres/test", summary="Test External PostgreSQL Connection")
def test_postgres_connection(
    payload: PostgresConnectionConfig,
    current_user: UserIdentity = Depends(get_current_user),
) -> Dict[str, Any]:
    """Verify network connectivity and credentials to an external PostgreSQL database."""
    return PostgreSQLOnboardingService.test_connection(
        host=payload.host,
        port=payload.port,
        database=payload.database,
        user=payload.user,
        password=payload.password,
        sslmode=payload.sslmode,
    )


@router.post("/onboard/postgres/inspect", summary="Inspect PostgreSQL Schema and Tables")
def inspect_postgres_tables(
    payload: PostgresConnectionConfig,
    current_user: UserIdentity = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """List available user tables and their column schemas in target PostgreSQL database."""
    try:
        return PostgreSQLOnboardingService.inspect_tables(
            host=payload.host,
            port=payload.port,
            database=payload.database,
            user=payload.user,
            password=payload.password,
            sslmode=payload.sslmode,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/onboard/postgres/preview", summary="Preview External PostgreSQL Table Sample Rows")
def preview_postgres_table(
    payload: PostgresTablePreviewRequest,
    current_user: UserIdentity = Depends(get_current_user),
) -> Dict[str, Any]:
    """Fetch sample rows and column telemetry for mapping preparation."""
    try:
        return PostgreSQLOnboardingService.preview_table(
            host=payload.host,
            port=payload.port,
            database=payload.database,
            user=payload.user,
            password=payload.password,
            table_name=payload.table_name,
            schema_name=payload.schema_name,
            limit=payload.limit,
            sslmode=payload.sslmode,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/onboard/postgres/ingest", summary="Ingest External PostgreSQL Table to Canonical Entity")
def ingest_postgres_table(
    payload: PostgresIngestRequest,
    x_business_id: Optional[str] = Header(None, alias="X-Business-ID"),
    current_user: UserIdentity = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """
    Commit mapped tabular records from external PostgreSQL table into NEXUS canonical models.
    Enforces tenant boundaries, deduplication, and atomic rollback on failure.
    """
    biz_id = _resolve_business_id(db, current_user, x_business_id)
    try:
        return PostgreSQLOnboardingService.ingest_table_to_canonical(
            db=db,
            business_id=biz_id,
            host=payload.host,
            port=payload.port,
            database=payload.database,
            user=payload.user,
            password=payload.password,
            table_name=payload.table_name,
            target_entity=payload.target_entity,
            column_mapping=payload.column_mapping,
            schema_name=payload.schema_name,
            max_rows=payload.max_rows,
            sslmode=payload.sslmode,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
