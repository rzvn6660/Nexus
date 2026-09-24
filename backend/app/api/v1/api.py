"""API v1 Router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import agent, analytics, data, health, knowledge, semantic

api_v1_router = APIRouter()
api_v1_router.include_router(health.router, prefix="/health", tags=["health"])
api_v1_router.include_router(data.router, prefix="/data", tags=["data"])
api_v1_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_v1_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_v1_router.include_router(semantic.router, prefix="/semantic", tags=["semantic"])
api_v1_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
