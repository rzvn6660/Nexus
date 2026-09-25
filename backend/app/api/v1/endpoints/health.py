"""Health, liveness, and system readiness endpoints for NEXUS."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import get_current_settings
from app.core.config import Settings
from app.core.database import check_database_connection
from app.schemas.health import (
    DatabaseHealth,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)

router = APIRouter()


@router.get(
    "",
    response_model=HealthResponse,
    summary="Service Health Check",
    description="Comprehensive health status evaluating API process and database connectivity.",
)
def get_health(
    settings: Settings = Depends(get_current_settings),
) -> HealthResponse:
    """
    Perform a complete system health check.
    
    Verifies that the API service is responsive and probes database connectivity.
    Returns service metadata, runtime environment, and connectivity status.
    """
    db_report = check_database_connection()
    is_connected = db_report.get("status") == "connected"
    
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
        dependency_status="optimal" if is_connected else "degraded",
        database=db_health,
    )


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Process Liveness Probe",
    description="Lightweight probe verifying that the ASGI process is running and accepting requests.",
)
def get_liveness() -> LivenessResponse:
    """Lightweight liveness probe for container orchestrators."""
    return LivenessResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Service Readiness Probe",
    description="Readiness probe verifying that backend dependencies (PostgreSQL) are operational.",
)
def get_readiness() -> Response:
    """
    Readiness probe verifying database connectivity.
    Returns HTTP 200 when ready, HTTP 503 when dependencies are unreachable.
    """
    db_report = check_database_connection()
    is_connected = db_report.get("status") == "connected"

    db_health = DatabaseHealth(
        status=db_report.get("status", "unknown"),
        latency_ms=db_report.get("latency_ms"),
        error=db_report.get("error"),
    )

    resp_data = ReadinessResponse(
        status="ready" if is_connected else "not_ready",
        service="nexus",
        timestamp=datetime.now(timezone.utc),
        database=db_health,
    )

    if not is_connected:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=resp_data.model_dump(mode="json"),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=resp_data.model_dump(mode="json"),
    )
