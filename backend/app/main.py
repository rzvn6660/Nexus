"""NEXUS FastAPI Application Entrypoint.

Starts backend API server with structured logging, CORS handling,
request correlation tracking, production error shielding, and versioned routing.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.database import engine, check_database_connection
from app.core.middleware import RequestCorrelationMiddleware
from app.api.router import root_api_router

# Initialize structured logging
setup_logging()
logger = get_logger("nexus.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager handling application startup and shutdown tasks."""
    logger.info(
        f"Starting {settings.APP_NAME} v{settings.APP_VERSION} "
        f"[env={settings.APP_ENV}, debug={settings.DEBUG}]"
    )

    # Validate database connectivity on startup
    db_status = check_database_connection()
    if db_status.get("status") == "connected":
        logger.info(
            f"Database connectivity established successfully (latency: {db_status.get('latency_ms')}ms)"
        )
    else:
        logger.warning(
            f"Database not reachable at startup ({db_status.get('error', 'unknown')}). "
            "Ensure PostgreSQL is running via Docker or local service."
        )

    yield

    logger.info(f"Shutting down {settings.APP_NAME}...")
    engine.dispose()
    logger.info("Database engine connections disposed cleanly.")


def create_application() -> FastAPI:
    """Application factory for NEXUS FastAPI server."""
    app = FastAPI(
        title=settings.APP_TITLE,
        version=settings.APP_VERSION,
        description=(
            "NEXUS is an Agentic Business Intelligence Platform designed to augment "
            "professional data analysts and empower business decision-makers. "
            "Where Business Data Becomes Intelligence."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Request correlation and logging middleware
    app.add_middleware(RequestCorrelationMiddleware)

    # Cross-Origin Resource Sharing (strictly sanitized for production)
    allowed_origins = settings.get_sanitized_cors_origins()
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Global unhandled exception handler: shields internal tracebacks in production
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", "-")
        logger.error(
            f"Unhandled server exception on {request.method} {request.url.path}: {exc}",
            exc_info=True,
            extra={"correlation_id": correlation_id},
        )
        if settings.DEBUG:
            detail_msg = f"Internal server error: {str(exc)}"
        else:
            detail_msg = (
                f"An internal error occurred. Please contact system support "
                f"referencing correlation ID: {correlation_id}"
            )
        return JSONResponse(
            status_code=500,
            content={"detail": detail_msg, "correlation_id": correlation_id},
        )

    # API Routing
    app.include_router(root_api_router, prefix="/api")

    @app.get("/", summary="Root Index", tags=["system"])
    def root_index() -> dict[str, str]:
        """Root landing endpoint providing system identification and navigation."""
        return {
            "name": settings.APP_NAME,
            "title": settings.APP_TITLE,
            "version": settings.APP_VERSION,
            "tagline": "Where Business Data Becomes Intelligence.",
            "docs": "/docs",
            "health": "/api/health",
            "liveness": "/api/health/live",
            "readiness": "/api/health/ready",
        }

    return app


app = create_application()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=settings.DEBUG,
    )
