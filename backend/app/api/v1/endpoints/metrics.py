"""Prometheus Metrics Exporter Endpoint (Phase 32A).

Exposes Prometheus operational metrics for scraping by Prometheus, VictoriaMetrics,
or Datadog agents. Supports optional token-based authorization and global disable switch.
"""

import hmac
import secrets
from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.core.metrics import CONTENT_TYPE_LATEST, get_latest_metrics

router = APIRouter()


def verify_metrics_authorization(
    authorization: str | None = Header(default=None),
    x_metrics_token: str | None = Header(default=None),
) -> None:
    """Verify scraper credentials when METRICS_AUTH_TOKEN is configured or in production.

    Uses constant-time comparison (hmac.compare_digest) to prevent timing attacks.
    In production (APP_ENV=production):
    - When METRICS_AUTH_TOKEN is missing or blank, access fails closed with HTTP 403 Forbidden.
    - Scrapers must present a valid matching Bearer token or X-Metrics-Token header.
    In non-production environments (development, test):
    - If METRICS_AUTH_TOKEN is not configured, unauthenticated access is permitted for local debugging.
    - If METRICS_AUTH_TOKEN is configured, provided credentials must match.
    """
    expected_token = (settings.METRICS_AUTH_TOKEN or "").strip()
    if not expected_token:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Metrics access is forbidden in production when METRICS_AUTH_TOKEN is unconfigured.",
            )
        # Convenient unauthenticated access retained in development/test
        return

    # Extract token from Authorization Bearer or X-Metrics-Token header
    provided_token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        provided_token = authorization.split("Bearer ", 1)[1].strip()
    elif x_metrics_token:
        provided_token = x_metrics_token.strip()

    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized metrics scraper. Provide a valid Bearer token or 'X-Metrics-Token' header.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get(
    "",
    summary="Scrape Prometheus Operational Metrics",
    description=(
        "Exposes HTTP request counts, latency histograms, in-progress gauges, "
        "and scheduler execution metrics formatted for Prometheus scraping."
    ),
    response_class=PlainTextResponse,
    include_in_schema=False,
)
def get_metrics(
    authorization: str | None = Header(default=None),
    x_metrics_token: str | None = Header(default=None),
) -> Response:
    """Prometheus metrics scrape endpoint."""
    if not settings.METRICS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metrics collection is disabled on this server.",
        )

    verify_metrics_authorization(authorization=authorization, x_metrics_token=x_metrics_token)

    return Response(
        content=get_latest_metrics(),
        media_type=CONTENT_TYPE_LATEST,
    )
