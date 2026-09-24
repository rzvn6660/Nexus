"""API v1 Router aggregation."""

from fastapi import APIRouter
from app.api.v1.endpoints import health, data

api_v1_router = APIRouter()
api_v1_router.include_router(health.router, prefix="/health", tags=["health"])
api_v1_router.include_router(data.router, prefix="/data", tags=["data"])

