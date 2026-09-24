"""Health and system readiness endpoint."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from app.core.config import Settings
from app.core.database import check_database_connection
from app.api.deps import get_current_settings
from app.schemas.health import HealthResponse, DatabaseHealth

router = APIRouter()


@router.get("", response_model=HealthResponse, summary="Service Health Check")
def get_health(
    settings: Settings = Depends(get_current_settings),
) -> HealthResponse:
    """
    Perform a system health check.
    
    Verifies that the API service is responsive and probes database connectivity.
    Returns service metadata, runtime environment, and connectivity status.
    """
    db_report = check_database_connection()
    db_health = DatabaseHealth(
        status=db_report.get("status", "unknown"),
        latency_ms=db_report.get("latency_ms"),
        error=db_report.get("error"),
    )

    return HealthResponse(
        status="healthy",
        service="nexus",
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        timestamp=datetime.now(timezone.utc),
        database=db_health,
    )
