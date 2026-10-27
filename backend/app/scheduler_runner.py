"""Dedicated background runner for the NEXUS Continuous Intelligence Scheduler (Phase 31B/32B).

Executes the continuous intelligence background scheduler in an isolated worker process,
preventing duplicate scheduler execution across multi-worker ASGI web processes.
Maintains an atomic health and progress heartbeat for external container probes,
detects unexpected background task termination, handles SIGINT/SIGTERM gracefully,
and safely releases database and cache resources on exit.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.analytics.continuous.scheduler import continuous_scheduler
from app.core.cache import check_redis_health, close_cache, get_cache
from app.core.config import settings
from app.core.database import check_database_connection, engine
from app.core.logging import get_logger, setup_logging
from app.scheduler_health import get_heartbeat_path

logger = get_logger("nexus.scheduler.runner")


class SchedulerRunner:
    """Manages the lifecycle, heartbeat, and graceful termination of the dedicated background scheduler process."""

    def __init__(
        self,
        heartbeat_interval_seconds: float = 10.0,
        stop_timeout_seconds: float = 5.0,
    ) -> None:
        self.stop_event = asyncio.Event()
        self.heartbeat_path = get_heartbeat_path()
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.stop_timeout_seconds = stop_timeout_seconds
        self.start_time: float = 0.0
        self._exit_code: int = 0

    def handle_signal(self, signum: int, frame: Any = None) -> None:
        """Handle OS termination signals (SIGINT, SIGTERM) by initiating cooperative shutdown."""
        try:
            sig_name = signal.Signals(signum).name
        except Exception:
            sig_name = str(signum)
        logger.info(f"Received shutdown signal {sig_name} ({signum}). Initiating graceful termination...")
        self.stop_event.set()

    def write_heartbeat(
        self,
        status: str,
        task_alive: bool,
        db_status: str,
        redis_status: str,
        error_detail: str | None = None,
        scheduler_enabled: bool | None = None,
    ) -> None:
        """Write an atomic, sanitized heartbeat file for external container health probes."""
        now = time.time()
        uptime = max(0.0, now - self.start_time) if self.start_time else 0.0
        raw_stats = getattr(continuous_scheduler, "stats", {})
        stats = raw_stats if isinstance(raw_stats, dict) else {}

        def _clean_num(val: Any, default: Any = 0) -> Any:
            return val if isinstance(val, (int, float)) else default

        is_enabled = (
            scheduler_enabled
            if scheduler_enabled is not None
            else bool(settings.CONTINUOUS_SCHEDULER_ENABLED)
        )

        payload: dict[str, Any] = {
            "timestamp": now,
            "pid": os.getpid(),
            "uptime_seconds": round(uptime, 2),
            "status": str(status),
            "task_alive": bool(task_alive),
            "scheduler_enabled": is_enabled,
            "total_ticks": _clean_num(stats.get("total_ticks"), 0),
            "last_tick_at": stats.get("last_tick_at") if isinstance(stats.get("last_tick_at"), (int, float)) else None,
            "last_tick_duration_ms": _clean_num(stats.get("last_tick_duration_ms"), None),
            "last_tick_errors": _clean_num(stats.get("last_tick_errors"), 0),
            "interval_seconds": _clean_num(stats.get("interval_seconds"), settings.CONTINUOUS_SCHEDULER_INTERVAL_SECONDS),
            "db_status": str(db_status),
            "redis_status": str(redis_status),
        }
        if error_detail:
            payload["error"] = str(error_detail)

        try:
            target_path = self.heartbeat_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Write to sibling temporary file then atomically replace to avoid partial reads
            temp_path = target_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            temp_path.replace(target_path)
        except Exception as exc:
            logger.warning("Failed to write scheduler heartbeat file %s: %s", self.heartbeat_path, exc)

    async def _run_heartbeat_loop(self) -> None:
        """Continuously evaluate health and emit sanitized heartbeat pulses."""
        logger.debug("Scheduler heartbeat pulse loop started [interval=%.1fs].", self.heartbeat_interval_seconds)
        while not self.stop_event.is_set():
            try:
                task = continuous_scheduler._task
                task_alive = bool(task is not None and not task.done())

                db_info = check_database_connection()
                db_status = db_info.get("status", "unknown")

                redis_info = check_redis_health()
                redis_status = redis_info.get("status", "unknown")

                # Determine overall status
                is_prod = settings.is_production
                is_redis_mandatory = bool(settings.REDIS_FAIL_CLOSED or settings.REDIS_REQUIRED)
                scheduler_enabled = bool(settings.CONTINUOUS_SCHEDULER_ENABLED)

                if scheduler_enabled:
                    if not task_alive:
                        status = "unhealthy"
                    elif db_status != "connected":
                        status = "degraded"
                    elif is_prod and is_redis_mandatory and redis_status != "connected":
                        status = "degraded"
                    else:
                        status = "healthy"
                else:
                    if db_status != "connected":
                        status = "degraded"
                    elif is_prod and is_redis_mandatory and redis_status != "connected":
                        status = "degraded"
                    else:
                        status = "dormant"

                self.write_heartbeat(
                    status=status,
                    task_alive=task_alive,
                    db_status=db_status,
                    redis_status=redis_status,
                    scheduler_enabled=scheduler_enabled,
                )
            except Exception as exc:
                logger.warning("Error during scheduler heartbeat pulse: %s", exc)

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.heartbeat_interval_seconds)
            except TimeoutError:
                pass

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
        self.start_time = time.time()
        logger.info("Starting NEXUS Dedicated Scheduler Runner (Continuous Intelligence)...")

        # Initialize optional error tracking (safe when SENTRY_DSN unset)
        from app.core.sentry import init_sentry

        init_sentry(process_name="scheduler")

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
            self.write_heartbeat(
                status="unhealthy",
                task_alive=False,
                db_status="disconnected",
                redis_status="unavailable",
                error_detail="Startup dependencies unavailable",
            )
            return 1

        # Start continuous intelligence scheduler
        continuous_scheduler.start()
        scheduler_enabled = bool(settings.CONTINUOUS_SCHEDULER_ENABLED)
        if scheduler_enabled:
            logger.info(
                "Continuous intelligence scheduler started successfully [interval=%ds, max_biz=%d, batch=%d].",
                continuous_scheduler.interval_seconds,
                continuous_scheduler.max_businesses,
                continuous_scheduler.batch_size,
            )
        else:
            logger.info(
                "Continuous intelligence scheduler is disabled (standby mode). Runner active for heartbeat & health probes."
            )

        task = continuous_scheduler._task
        task_alive = bool(task is not None and not task.done())
        initial_status = "healthy" if scheduler_enabled else "dormant"

        # Emit initial healthy or dormant heartbeat
        self.write_heartbeat(
            status=initial_status,
            task_alive=task_alive,
            db_status="connected" if deps_ok else "degraded",
            redis_status="connected" if deps_ok else "unknown",
            scheduler_enabled=scheduler_enabled,
        )

        # Launch periodic background heartbeat loop task
        heartbeat_task = asyncio.create_task(self._run_heartbeat_loop(), name="nexus_scheduler_heartbeat")

        scheduler_task = continuous_scheduler._task
        exit_code = 0

        try:
            if scheduler_task is not None:
                # Monitor both stop signal and the background scheduler task
                stop_waiter = asyncio.create_task(self.stop_event.wait(), name="nexus_scheduler_stop_waiter")
                done, pending = await asyncio.wait(
                    [stop_waiter, scheduler_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if scheduler_task in done:
                    # Scheduler task terminated without a cooperative shutdown signal!
                    if not self.stop_event.is_set():
                        exc = scheduler_task.exception() if not scheduler_task.cancelled() else None
                        if exc:
                            logger.critical("FATAL: Background scheduler loop task crashed with exception: %s", exc, exc_info=exc)
                        else:
                            logger.critical("FATAL: Background scheduler loop task terminated unexpectedly.")
                        exit_code = 1
                    # Clean up pending stop waiter
                    if stop_waiter in pending:
                        stop_waiter.cancel()
            else:
                # Scheduler disabled or not started
                await self.stop_event.wait()

        finally:
            logger.info("Stopping scheduler cooperatively...")
            # Cancel heartbeat loop
            self.stop_event.set()
            if not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # Gracefully stop the continuous scheduler with configured timeout
            await continuous_scheduler.stop(timeout_seconds=self.stop_timeout_seconds)

            # Record final shutdown heartbeat
            final_status = "crashed" if exit_code != 0 else "stopped"
            self.write_heartbeat(
                status=final_status,
                task_alive=False,
                db_status="disconnected",
                redis_status="disconnected",
                scheduler_enabled=scheduler_enabled,
            )

            # Clean cache and database pool disposal
            close_cache()
            engine.dispose()
            logger.info("Scheduler runner shutdown complete. All connection pools released.")

        return exit_code


def main() -> None:
    """Synchronous entry point for `python -m app.scheduler_runner`."""
    runner = SchedulerRunner()
    exit_code = asyncio.run(runner.run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
