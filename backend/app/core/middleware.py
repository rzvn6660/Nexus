"""Application middlewares including Request Correlation ID and request tracing."""

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
from app.core.logging import get_logger, correlation_id_var

logger = get_logger(__name__)


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware attaching unique correlation ID and logging request lifecycle."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Honor existing header or generate a new UUID4
        correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.correlation_id = correlation_id

        # Bind correlation ID to ContextVar for this request's async task context
        token = correlation_id_var.set(correlation_id)
        start_time = time.perf_counter()

        try:
            # Process request
            response = await call_next(request)

            process_time_ms = (time.perf_counter() - start_time) * 1000

            # Attach header to response
            response.headers["X-Request-ID"] = correlation_id
            response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f}"

            # Structured request log
            logger.info(
                f"{request.method} {request.url.path} -> {response.status_code} "
                f"({process_time_ms:.2f}ms)",
                extra={"correlation_id": correlation_id},
            )

            return response
        finally:
            # Reset ContextVar to prevent leak across pooled tasks/threads
            correlation_id_var.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware attaching OWASP security headers, CSP, Permissions-Policy, and HSTS to responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Baseline OWASP security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy (Report-Only rollout by default)
        if settings.SECURE_CSP_ENABLED:
            csp_header = (
                "Content-Security-Policy-Report-Only"
                if settings.SECURE_CSP_REPORT_ONLY
                else "Content-Security-Policy"
            )
            csp_val = settings.SECURE_CSP_DIRECTIVES
            if settings.SECURE_CSP_REPORT_URI:
                csp_val = f"{csp_val.rstrip('; ')}; report-uri {settings.SECURE_CSP_REPORT_URI};"
            response.headers[csp_header] = csp_val

        # Permissions Policy
        if settings.SECURE_PERMISSIONS_POLICY:
            response.headers["Permissions-Policy"] = settings.SECURE_PERMISSIONS_POLICY

        # HTTP Strict Transport Security (HSTS)
        # Enabled conditionally when SECURE_HSTS_SECONDS > 0 (prevents breaking local dev/test HTTP)
        if settings.SECURE_HSTS_SECONDS > 0:
            hsts_parts = [f"max-age={settings.SECURE_HSTS_SECONDS}"]
            if settings.SECURE_HSTS_INCLUDE_SUBDOMAINS:
                hsts_parts.append("includeSubDomains")
            if settings.SECURE_HSTS_PRELOAD:
                hsts_parts.append("preload")
            response.headers["Strict-Transport-Security"] = "; ".join(hsts_parts)

        return response


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Middleware recording HTTP request counts, latency histograms, and concurrency gauges."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not settings.METRICS_ENABLED:
            return await call_next(request)

        from app.core.metrics import (
            HTTP_REQUESTS_IN_PROGRESS,
            HTTP_REQUESTS_TOTAL,
            HTTP_REQUEST_DURATION_SECONDS,
            get_route_handler,
            get_status_class,
        )

        method = request.method
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()
        start_time = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start_time
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()

            handler = get_route_handler(request)
            status_class = get_status_class(status_code)

            HTTP_REQUESTS_TOTAL.labels(
                method=method,
                handler=handler,
                status_class=status_class,
                status_code=str(status_code),
            ).inc()

            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method,
                handler=handler,
            ).observe(duration)
