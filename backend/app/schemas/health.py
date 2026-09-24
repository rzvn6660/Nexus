"""Pydantic v2 schemas for health checks and system readiness."""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    """Database connectivity details."""

    status: str = Field(description="Database connectivity status: connected or disconnected")
    latency_ms: Optional[float] = Field(default=None, description="Round-trip latency in milliseconds")
    error: Optional[str] = Field(default=None, description="Error message if disconnected")


class HealthResponse(BaseModel):
    """Structured health response for NEXUS platform."""

    status: str = Field(default="healthy", description="Overall service status")
    service: str = Field(default="nexus", description="Service identifier")
    version: str = Field(description="Application version")
    environment: str = Field(description="Runtime environment")
    timestamp: datetime = Field(description="UTC timestamp of the health check")
    database: Optional[DatabaseHealth] = Field(
        default=None,
        description="Detailed database health check report",
    )
