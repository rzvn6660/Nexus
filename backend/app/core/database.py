"""SQLAlchemy 2.x database engine, session management, and connectivity checks."""

import time
from typing import Any, Dict, Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

def _get_engine_kwargs() -> dict[str, Any]:
    """Build SQLAlchemy engine arguments tailored for PostgreSQL or SQLite."""
    kwargs: dict[str, Any] = {
        "echo": settings.DB_ECHO,
        "pool_pre_ping": True,
    }
    if "sqlite" in settings.DATABASE_URL:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["connect_args"] = {"connect_timeout": 2}
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
        kwargs["pool_timeout"] = settings.DB_POOL_TIMEOUT
    return kwargs


# SQLAlchemy 2.x Engine configuration
engine = create_engine(settings.DATABASE_URL, **_get_engine_kwargs())


# Session factory for standard synchronous operations
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a managed database session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection(target_engine=None) -> Dict[str, Any]:
    """
    Verify database connectivity using a lightweight query.
    
    Returns structured status without raising unhandled exceptions,
    enabling robust health checking.
    """
    active_engine = target_engine or engine
    start_time = time.perf_counter()
    try:
        with active_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "status": "connected",
            "latency_ms": latency_ms,
        }
    except SQLAlchemyError as exc:
        logger.warning(f"Database health check failed: {exc}")
        return {
            "status": "disconnected",
            "error": "Database unreachable",
        }
    except Exception as exc:
        logger.error(f"Unexpected error during database check: {exc}")
        return {
            "status": "disconnected",
            "error": "Unexpected database error",
        }

