"""Dedicated background runner for the NEXUS Continuous Intelligence Scheduler (Phase 31B Step 4).

Executes the continuous intelligence background scheduler in an isolated worker process,
preventing duplicate scheduler execution across multi-worker ASGI web processes.
Handles SIGINT and SIGTERM gracefully, waits for active batch scans to finish,
and safely releases database and cache resources on exit.
"""

import asyncio
import signal
import sys
import time
from typing import Any

from app.analytics.continuous.scheduler import continuous_scheduler
from app.core.cache import check_redis_health, close_cache, get_cache
from app.core.config import settings
from app.core.database import check_database_connection, engine
from app.core.logging import get_logger, setup_logging

logger = get_logger("nexus.scheduler.runner")


class SchedulerRunner:
    """Manages the lifecycle and graceful termination of the dedicated background scheduler process."""

    def __init__(self) -> None:
        self.stop_event = asyncio.Event()

    def handle_signal(self, signum: int, frame: Any = None) -> None:
        """Handle OS termination signals (SIGINT, SIGTERM) by initiating cooperative shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received shutdown signal {sig_name} ({signum}). Initiating graceful termination...")
        self.stop_event.set()

    async def verify_dependencies(self, max_retries: int = 5, retry_interval: float = 2.0) -> bool:
        """Verify that mandatory dependencies (PostgreSQL and Redis) are available before scheduler ticks."""
        logger.info("Scheduler runner verifying service dependencies...")

        for attempt in range(1, max_retries + 1):
            db_status = check_database_connection()
            db_ok = db_status.get("status") == "connected"

            redis_status = check_redis_health()
            redis_ok = (
                redis_status.get("shared_state_available", False)
                or not redis_status.get("required", False)
            )

            if db_ok and redis_ok:
                logger.info(
                    "Scheduler dependencies verified: PostgreSQL connected (latency: %sms), Redis [%s, shared=%s].",
                    db_status.get("latency_ms", "N/A"),
                    redis_status.get("status"),
                    redis_status.get("shared_state_available"),
                )
                return True

            logger.warning(
                "Scheduler dependency probe attempt %d/%d failed (DB: %s, Redis: %s). Retrying in %.1fs...",
                attempt,
                max_retries,
                db_status.get("status"),
                redis_status.get("status"),
                retry_interval,
            )
            await asyncio.sleep(retry_interval)

        return False

    async def run(self) -> int:
        """Run the continuous intelligence scheduler loop until a shutdown signal is received."""
        setup_logging()
        logger.info("Starting NEXUS Dedicated Scheduler Runner (Continuous Intelligence)...")

        # Register signal handlers for clean container stop (SIGTERM, SIGINT)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: self.handle_signal(s))
            except (NotImplementedError, AttributeError):
                # Windows event loop fallback
                signal.signal(sig, self.handle_signal)

        # Pre-flight dependency check
        deps_ok = await self.verify_dependencies()
        if not deps_ok and settings.is_production:
            logger.error("FATAL: Required dependencies unavailable at scheduler startup. Exiting.")
            return 1

        # Start continuous intelligence scheduler
        continuous_scheduler.start()
        logger.info(
            "Continuous intelligence scheduler started successfully [interval=%ds, max_biz=%d, batch=%d].",
            continuous_scheduler.interval_seconds,
            continuous_scheduler.max_businesses,
            continuous_scheduler.batch_size,
        )

        try:
            # Wait asynchronously until SIGTERM or SIGINT triggers stop_event
            await self.stop_event.wait()
        finally:
            logger.info("Stopping scheduler cooperatively...")
            await continuous_scheduler.stop(timeout_seconds=5.0)

            # Clean cache and database pool disposal
            close_cache()
            engine.dispose()
            logger.info("Scheduler runner shutdown complete. All connection pools released.")

        return 0


def main() -> None:
    """Synchronous entry point for `python -m app.scheduler_runner`."""
    runner = SchedulerRunner()
    exit_code = asyncio.run(runner.run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
