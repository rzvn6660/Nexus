"""Application middlewares including Request Correlation ID and request tracing."""

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
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
    """Middleware attaching standard OWASP production security headers to all API responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
