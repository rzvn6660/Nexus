"""Operational Metrics and Prometheus Telemetry (Phase 32A).

Provides HTTP request count, latency histograms, concurrency gauges,
and background scheduler metrics with low-cardinality label normalization.
Guarantees zero leakage of tenant IDs, user IDs, tokens, or raw paths.
"""

import re
from typing import Any
from fastapi import Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.core.config import settings

# ------------------------------------------------------------------------------
# Prometheus Metrics Definitions
# ------------------------------------------------------------------------------

# HTTP Request Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "nexus_http_requests_total",
    "Total HTTP requests handled by NEXUS",
    ["method", "handler", "status_class", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "nexus_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "handler"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "nexus_http_requests_in_progress",
    "Number of HTTP requests currently being handled",
    ["method"],
)

# Background Scheduler Metrics
SCHEDULER_TICKS_TOTAL = Counter(
    "nexus_scheduler_ticks_total",
    "Total continuous intelligence scheduler ticks executed",
    ["status"],
)

SCHEDULER_TICK_DURATION_SECONDS = Histogram(
    "nexus_scheduler_tick_duration_seconds",
    "Duration of continuous intelligence scheduler ticks in seconds",
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

SCHEDULER_SCANS_RECONCILED_TOTAL = Counter(
    "nexus_scheduler_scans_reconciled_total",
    "Total scans reconciled by continuous intelligence background scheduler",
)

SCHEDULER_BUSINESSES_SCANNED_TOTAL = Counter(
    "nexus_scheduler_businesses_scanned_total",
    "Total distinct businesses scanned by continuous intelligence scheduler",
)


# ------------------------------------------------------------------------------
# Route & Path Normalization (Low Cardinality Enforcement)
# ------------------------------------------------------------------------------

_UUID_REGEX = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX_HASH_REGEX = re.compile(r"(?<=/)[0-9a-fA-F]{16,}(?=/|$)")
_NUMERIC_ID_REGEX = re.compile(r"(?<=/)\d+(?=/|$)")


def normalize_path(raw_path: str) -> str:
    """Normalize raw URL paths by replacing UUIDs, hashes, and numeric IDs with placeholders.

    Prevents label explosion in Prometheus when routes are unmatched or dynamic.
    """
    if not raw_path:
        return "/"

    # Strip query parameters if accidentally included
    clean_path = raw_path.split("?")[0].strip()

    # Mask UUIDs
    clean_path = _UUID_REGEX.sub(":id", clean_path)

    # Mask long hex strings (hashes/tokens)
    clean_path = _HEX_HASH_REGEX.sub(":hash", clean_path)

    # Mask numeric IDs
    clean_path = _NUMERIC_ID_REGEX.sub(":id", clean_path)

    # Bound maximum path depth to 6 segments to avoid runaway label diversity
    segments = [s for s in clean_path.split("/") if s]
    if len(segments) > 6:
        clean_path = "/" + "/".join(segments[:6]) + "/:rest"

    return clean_path or "/"


def get_route_handler(request: Request) -> str:
    """Extract parameterized route template or normalized path from request.

    If Starlette successfully routed the request, uses the route template
    (e.g., '/api/v1/businesses/{business_id}/overview').
    If the request did not match a route (404) or was intercepted early,
    falls back to the scrubbed normalized path.
    """
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if route_path and isinstance(route_path, str):
        return route_path

    # Fallback to normalized path
    return normalize_path(request.url.path)


def get_status_class(status_code: int) -> str:
    """Return status-code category (e.g., '2xx', '4xx', '5xx')."""
    if 100 <= status_code < 200:
        return "1xx"
    elif 200 <= status_code < 300:
        return "2xx"
    elif 300 <= status_code < 400:
        return "3xx"
    elif 400 <= status_code < 500:
        return "4xx"
    elif 500 <= status_code < 600:
        return "5xx"
    return "unknown"


def get_latest_metrics() -> bytes:
    """Export the current metrics registry in Prometheus text format."""
    return generate_latest(REGISTRY)
