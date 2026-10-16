"""Root API Router for NEXUS."""

from fastapi import APIRouter
from app.api.v1.api import api_v1_router
from app.api.v1.endpoints import health, metrics

root_api_router = APIRouter()

# Top-level /api/health endpoint as required by the platform specification
root_api_router.include_router(health.router, prefix="/health", tags=["system"])

# Top-level Prometheus operational metrics exporter (/api/metrics and /api/v1/metrics)
root_api_router.include_router(metrics.router, prefix="/metrics", tags=["system"])
root_api_router.include_router(metrics.router, prefix="/v1/metrics", tags=["system"])

# Versioned API routes (/api/v1)
root_api_router.include_router(api_v1_router, prefix="/v1")
