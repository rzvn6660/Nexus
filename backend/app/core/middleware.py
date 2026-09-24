"""Application middlewares including Request Correlation ID and request tracing."""

import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware attaching unique correlation ID and logging request lifecycle."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Honor existing header or generate a new UUID4
        correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.correlation_id = correlation_id

        start_time = time.perf_counter()
        
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
