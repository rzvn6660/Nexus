"""API dependencies for FastAPI endpoints."""

from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session
from app.core.config import Settings, get_settings
from app.core.database import get_db


def get_current_settings() -> Settings:
    """Dependency for accessing application settings."""
    return get_settings()


def get_db_session(
    db: Session = Depends(get_db),
) -> Session:
    """Dependency returning active database session."""
    return db

