"""API v1 Router aggregation with security boundary."""

from fastapi import APIRouter, Depends

from app.api.v1.endpoints import (
    agent,
    analytics,
    data,
    forecast,
    health,
    history,
    investigation,
    knowledge,
    semantic,
)
from app.core.security import verify_api_key

# Enforce API Key / Bearer Token authentication on all v1 endpoints when enabled
api_v1_router = APIRouter(dependencies=[Depends(verify_api_key)])

api_v1_router.include_router(health.router, prefix="/health", tags=["health"])
api_v1_router.include_router(data.router, prefix="/data", tags=["data"])
api_v1_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_v1_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_v1_router.include_router(investigation.router, prefix="/investigation", tags=["investigation"])
api_v1_router.include_router(semantic.router, prefix="/semantic", tags=["semantic"])
api_v1_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_v1_router.include_router(forecast.router, prefix="/forecast", tags=["forecast"])
api_v1_router.include_router(history.router, prefix="/history", tags=["history", "decisions"])
