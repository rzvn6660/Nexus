"""Pydantic v2 schemas for health checks and system readiness."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    """Database connectivity details."""

    status: str = Field(description="Database connectivity status: connected or disconnected")
    latency_ms: Optional[float] = Field(default=None, description="Round-trip latency in milliseconds")
    error: Optional[str] = Field(default=None, description="Error message if disconnected")


class HealthResponse(BaseModel):
    """Structured health response for NEXUS platform."""

    status: str = Field(default="healthy", description="Application service status: healthy")
    service: str = Field(default="nexus", description="Service identifier")
    version: str = Field(description="Application version")
    environment: str = Field(description="Runtime environment")
    timestamp: datetime = Field(description="UTC timestamp of the health check")
    dependency_status: str = Field(default="optimal", description="Dependency status: optimal or degraded")
    database: Optional[DatabaseHealth] = Field(
        default=None,
        description="Detailed database health check report",
    )


class LivenessResponse(BaseModel):
    """Lightweight process liveness probe response."""

    status: str = Field(default="alive", description="Process liveness state: alive")
    timestamp: datetime = Field(description="UTC timestamp of the probe")


class ReadinessResponse(BaseModel):
    """Dependency readiness probe response for load balancers."""

    status: str = Field(description="Readiness state: ready or not_ready")
    service: str = Field(default="nexus", description="Service identifier")
    timestamp: datetime = Field(description="UTC timestamp of the probe")
    database: DatabaseHealth = Field(description="Database connection status report")
