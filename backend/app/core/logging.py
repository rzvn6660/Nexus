"""Structured logging setup for NEXUS."""

import logging
import sys
from typing import Any, Dict
from app.core.config import settings


class CorrelationFilter(logging.Filter):
    """Logging filter ensuring correlation_id is always present in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        return True


def setup_logging() -> None:
    """Configure root logger with structured output and appropriate level."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    log_format = (
        "[%(asctime)s] [%(levelname)s] [%(correlation_id)s] "
        "[%(name)s:%(funcName)s:%(lineno)d] - %(message)s"
    )

    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]

    # Silence overly verbose external loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger instance with correlation filter attached."""
    logger = logging.getLogger(name)
    logger.addFilter(CorrelationFilter())
    return logger
