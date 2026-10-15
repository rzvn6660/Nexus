"""Health, liveness, and system readiness endpoints for NEXUS."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import get_current_settings
from app.core.cache import check_redis_health
from app.core.config import Settings
from app.core.database import check_database_connection
from app.schemas.health import (
    DatabaseHealth,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
    RedisHealth,
)

router = APIRouter()


@router.get(
    "",
    response_model=HealthResponse,
    summary="Service Health Check",
    description="Comprehensive health status evaluating API process, database connectivity, and Redis shared state.",
)
def get_health(
    settings: Settings = Depends(get_current_settings),
) -> HealthResponse:
    """
    Perform a complete system health check.

    Verifies that the API service is responsive and probes database connectivity and shared cache.
    Returns service metadata, runtime environment, and dependency connectivity status.
    """
    db_report = check_database_connection()
    is_db_connected = db_report.get("status") == "connected"

    db_health = DatabaseHealth(
        status=db_report.get("status", "unknown"),
        latency_ms=db_report.get("latency_ms"),
        error=db_report.get("error"),
    )

    redis_data = check_redis_health()
    redis_health = RedisHealth(**redis_data)

    # Determine overall status:
    # If DB is down -> degraded
    # If Redis is required and unavailable/reconnecting -> degraded
    # If Redis was configured with a URL but is failing -> degraded
    # If Redis is optional (dev) or connected -> optimal
    redis_healthy = True
    if redis_health.required:
        redis_healthy = redis_health.shared_state_available
    elif redis_health.status in ("reconnecting", "unavailable"):
        redis_healthy = False

    is_optimal = is_db_connected and redis_healthy

    return HealthResponse(
        status="healthy" if is_optimal else "degraded",
        service="nexus",
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        timestamp=datetime.now(timezone.utc),
        dependency_status="optimal" if is_optimal else "degraded",
        database=db_health,
        redis=redis_health,
    )


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Process Liveness Probe",
    description="Lightweight probe verifying that the ASGI process is running and accepting requests.",
)
def get_liveness() -> LivenessResponse:
    """Lightweight liveness probe for container orchestrators.

    CRITICAL: Strictly independent of Redis or database outages to prevent restart loops.
    """
    return LivenessResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Service Readiness Probe",
    description="Readiness probe verifying backend dependencies (PostgreSQL, Redis shared state).",
)
def get_readiness() -> Response:
    """
    Readiness probe verifying database connectivity and Redis shared state.

    In production (or when Redis is required for shared security state),
    readiness strictly requires shared Redis state to be available.
    In development with optional Redis, readiness gates only on database connectivity.
    Returns HTTP 200 when ready, HTTP 503 when dependencies are unreachable.
    """
    db_report = check_database_connection()
    is_db_connected = db_report.get("status") == "connected"

    db_health = DatabaseHealth(
        status=db_report.get("status", "unknown"),
        latency_ms=db_report.get("latency_ms"),
        error=db_report.get("error"),
    )

    redis_data = check_redis_health()
    redis_health = RedisHealth(**redis_data)

    redis_ready = True
    if redis_health.required:
        redis_ready = redis_health.shared_state_available

    is_ready = is_db_connected and redis_ready

    resp_data = ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        service="nexus",
        timestamp=datetime.now(timezone.utc),
        database=db_health,
        redis=redis_health,
    )

    if not is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=resp_data.model_dump(mode="json"),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=resp_data.model_dump(mode="json"),
    )
