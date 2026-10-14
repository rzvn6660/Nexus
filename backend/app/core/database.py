"""SQLAlchemy 2.x database engine, session management, and connectivity checks."""

import time
from typing import Any, Dict, Generator
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

def _get_engine_kwargs(custom_settings: Any | None = None) -> dict[str, Any]:
    """Build SQLAlchemy engine arguments tailored for PostgreSQL or SQLite.

    Configures connection pre-ping, connection timeouts, connection pool recycling,
    and PostgreSQL TLS sslmode.
    """
    cfg = custom_settings or settings
    kwargs: dict[str, Any] = {
        "echo": cfg.DB_ECHO,
        "pool_pre_ping": True,
    }
    if "sqlite" in cfg.DATABASE_URL:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        connect_args: dict[str, Any] = {"connect_timeout": 2}
        ssl_mode = cfg.effective_db_ssl_mode
        parsed_url = urlparse(cfg.DATABASE_URL)
        query_params = parse_qs(parsed_url.query)

        # Defense-in-depth: reject ambiguous duplicate or insecure sslmode/sslrootcert URL overrides in production
        if cfg.is_production:
            if len(query_params.get("sslmode", [])) > 1:
                raise ValueError(
                    f"Ambiguous multiple 'sslmode' parameters in DATABASE_URL: {query_params['sslmode']}."
                )
            if len(query_params.get("sslrootcert", [])) > 1:
                raise ValueError(
                    f"Ambiguous multiple 'sslrootcert' parameters in DATABASE_URL: {query_params['sslrootcert']}."
                )
            for mode_val in query_params.get("sslmode", []):
                if mode_val.strip().lower() in ("disable", "allow", "prefer"):
                    raise ValueError(
                        f"Insecure sslmode='{mode_val}' in DATABASE_URL rejected in production."
                    )

        # Honor explicit sslmode query parameter in DATABASE_URL if present, else apply configured mode
        if ssl_mode and "sslmode" not in query_params:
            connect_args["sslmode"] = ssl_mode
        # Honor explicit sslrootcert query parameter in DATABASE_URL if present, else apply configured mode
        if cfg.DB_SSL_ROOT_CERT and "sslrootcert" not in query_params:
            connect_args["sslrootcert"] = cfg.DB_SSL_ROOT_CERT
        kwargs["connect_args"] = connect_args
        kwargs["pool_size"] = cfg.DB_POOL_SIZE
        kwargs["max_overflow"] = cfg.DB_MAX_OVERFLOW
        kwargs["pool_timeout"] = cfg.DB_POOL_TIMEOUT
        kwargs["pool_recycle"] = cfg.DB_POOL_RECYCLE
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

