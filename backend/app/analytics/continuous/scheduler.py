"""Scheduled Continuous Intelligence Background Execution (Phase 29 Stage 3).

Provides autonomous, scheduled reconciliation and continuous intelligence scanning
without requiring manual user triggers or ingestion job re-submission.
Enforces multi-instance concurrency safety, tenant isolation, cooperative shutdown,
and bounded execution.
"""

import asyncio
import time
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.analytics.continuous.service import ContinuousIntelligenceService
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.tenant import Business

logger = get_logger("nexus.continuous.scheduler")


class ContinuousIntelligenceScheduler:
    """Autonomous scheduler for continuous intelligence scans across active businesses.

    Invariants:
    1. Multi-instance safety: In PostgreSQL, candidate workspaces and ingestion jobs
       are claimed using SELECT ... FOR UPDATE SKIP LOCKED. Multiple application
       instances or worker processes do not duplicate execution.
    2. Tenant isolation: Iterates businesses sequentially or independently; database
       transactions, sessions, and findings are strictly scoped to business_id.
    3. Cooperative shutdown: Listens to an asyncio.Event; cancels gracefully without
       leaving dangling database transactions or truncated findings.
    4. Bounded execution: Limits the number of businesses per tick and jobs per business
       to prevent runaway batch operations or database pool starvation.
    5. Non-blocking: Runs synchronous database scan operations in worker threads via
       asyncio.to_thread, keeping the FastAPI async event loop responsive.
    """

    def __init__(
        self,
        interval_seconds: int | None = None,
        batch_size: int | None = None,
        max_businesses: int | None = None,
        startup_delay_seconds: int | None = None,
    ) -> None:
        self.interval_seconds: int = (
            interval_seconds
            if interval_seconds is not None
            else settings.CONTINUOUS_SCHEDULER_INTERVAL_SECONDS
        )
        self.batch_size: int = (
            batch_size
            if batch_size is not None
            else settings.CONTINUOUS_SCHEDULER_BATCH_SIZE
        )
        self.max_businesses: int = (
            max_businesses
            if max_businesses is not None
            else settings.CONTINUOUS_SCHEDULER_MAX_BUSINESSES_PER_TICK
        )
        self.startup_delay_seconds: int = (
            startup_delay_seconds
            if startup_delay_seconds is not None
            else settings.CONTINUOUS_SCHEDULER_STARTUP_DELAY_SECONDS
        )

        self._shutdown_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._is_running: bool = False
        self._total_ticks: int = 0
        self._total_reconciled_scans: int = 0
        self._last_tick_at: float | None = None
        self._last_tick_duration_ms: float | None = None
        self._last_tick_reconciled: int = 0
        self._last_tick_errors: int = 0

    @property
    def is_running(self) -> bool:
        """Return True if background scheduler task is currently active."""
        return self._is_running

    @property
    def stats(self) -> dict[str, Any]:
        """Return telemetry statistics of scheduler runs."""
        return {
            "is_running": self._is_running,
            "enabled": settings.CONTINUOUS_SCHEDULER_ENABLED,
            "interval_seconds": self.interval_seconds,
            "batch_size": self.batch_size,
            "max_businesses": self.max_businesses,
            "total_ticks": self._total_ticks,
            "total_reconciled_scans": self._total_reconciled_scans,
            "last_tick_at": self._last_tick_at,
            "last_tick_duration_ms": self._last_tick_duration_ms,
            "last_tick_reconciled": self._last_tick_reconciled,
            "last_tick_errors": self._last_tick_errors,
        }

    def start(self) -> None:
        """Start the background scheduler task inside the active asyncio event loop."""
        if not settings.CONTINUOUS_SCHEDULER_ENABLED:
            logger.info("Continuous intelligence scheduler is DISABLED by configuration.")
            return

        if self._is_running:
            logger.warning("Continuous intelligence scheduler is already running.")
            return

        self._shutdown_event = asyncio.Event()
        self._is_running = True
        self._task = asyncio.create_task(self._run_loop(), name="nexus_continuous_scheduler")
        logger.info(
            "Continuous intelligence scheduler started: interval=%ds, batch_size=%d, max_biz=%d, startup_delay=%ds",
            self.interval_seconds,
            self.batch_size,
            self.max_businesses,
            self.startup_delay_seconds,
        )

    async def stop(self, timeout_seconds: float = 10.0) -> None:
        """Cooperatively signal shutdown and await task termination."""
        if not self._is_running or self._task is None:
            return

        logger.info("Stopping continuous intelligence scheduler (graceful timeout: %.1fs)...", timeout_seconds)
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        self._is_running = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=timeout_seconds)
            except (TimeoutError, asyncio.CancelledError):
                pass

        self._task = None
        logger.info("Continuous intelligence scheduler stopped cleanly.")

    async def _run_loop(self) -> None:
        """Background execution loop."""
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        try:
            if self.startup_delay_seconds > 0:
                logger.debug("Scheduler startup delay: sleeping for %ds...", self.startup_delay_seconds)
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.startup_delay_seconds)
                    return
                except TimeoutError:
                    pass

            while not self._shutdown_event.is_set():
                tick_start = time.perf_counter()
                try:
                    tick_summary = await asyncio.to_thread(self._execute_tick_in_thread)
                    elapsed_ms = (time.perf_counter() - tick_start) * 1000
                    self._total_ticks += 1
                    self._total_reconciled_scans += tick_summary.get("total_reconciled", 0)
                    self._last_tick_at = time.time()
                    self._last_tick_duration_ms = elapsed_ms
                    self._last_tick_reconciled = tick_summary.get("total_reconciled", 0)
                    self._last_tick_errors = len(tick_summary.get("errors", []))

                    # Operational Prometheus metrics (Phase 32A)
                    if settings.METRICS_ENABLED:
                        try:
                            from app.core.metrics import (
                                SCHEDULER_BUSINESSES_SCANNED_TOTAL,
                                SCHEDULER_SCANS_RECONCILED_TOTAL,
                                SCHEDULER_TICK_DURATION_SECONDS,
                                SCHEDULER_TICKS_TOTAL,
                            )

                            SCHEDULER_TICKS_TOTAL.labels(status="success").inc()
                            SCHEDULER_TICK_DURATION_SECONDS.observe(elapsed_ms / 1000.0)
                            reconciled = tick_summary.get("total_reconciled", 0)
                            if reconciled > 0:
                                SCHEDULER_SCANS_RECONCILED_TOTAL.inc(reconciled)
                            scanned = tick_summary.get("businesses_scanned", 0)
                            if scanned > 0:
                                SCHEDULER_BUSINESSES_SCANNED_TOTAL.inc(scanned)
                        except Exception:
                            pass

                    if tick_summary.get("total_reconciled", 0) > 0:
                        logger.info(
                            "Continuous scheduler tick complete: %d scans reconciled across %d businesses (%.2fms)",
                            tick_summary.get("total_reconciled", 0),
                            tick_summary.get("businesses_scanned", 0),
                            elapsed_ms,
                        )
                    else:
                        logger.debug("Continuous scheduler tick complete: no pending scans (%.2fms)", elapsed_ms)
                except Exception:
                    self._last_tick_errors += 1
                    if settings.METRICS_ENABLED:
                        try:
                            from app.core.metrics import (
                                SCHEDULER_TICK_DURATION_SECONDS,
                                SCHEDULER_TICKS_TOTAL,
                            )

                            SCHEDULER_TICKS_TOTAL.labels(status="error").inc()
                            SCHEDULER_TICK_DURATION_SECONDS.observe(
                                (time.perf_counter() - tick_start)
                            )
                        except Exception:
                            pass
                    logger.exception("Continuous scheduler tick encountered unhandled error.")

                # Wait for next interval or early shutdown
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=float(self.interval_seconds))
                except TimeoutError:
                    pass

        except asyncio.CancelledError:
            logger.debug("Continuous scheduler loop task cancelled.")
        finally:
            self._is_running = False

    def _execute_tick_in_thread(self) -> dict[str, Any]:
        """Worker thread entrypoint creating and releasing a scoped database session."""
        db: Session = SessionLocal()
        try:
            return self.run_single_tick(
                db=db,
                max_businesses=self.max_businesses,
                batch_size=self.batch_size,
            )
        finally:
            db.close()

    @classmethod
    def run_single_tick(
        cls,
        db: Session,
        max_businesses: int = 50,
        batch_size: int = 10,
    ) -> dict[str, Any]:
        """Execute a single synchronous tick of continuous intelligence reconciliation.

        This method is deterministic, idempotent, and callable directly in unit/integration tests
        without relying on background asyncio timers.

        Returns:
            Dictionary containing execution statistics (businesses_scanned, total_reconciled, errors).
        """
        # 1. Fetch active businesses ordered deterministically
        businesses = (
            db.execute(
                select(Business)
                .order_by(desc(Business.created_at))
                .limit(max_businesses)
            )
            .scalars()
            .all()
        )

        total_reconciled = 0
        businesses_scanned = 0
        errors: list[dict[str, str]] = []

        for biz in businesses:
            businesses_scanned += 1
            # Reconcile pending scans for this business via atomic per-ingestion-job claim
            try:
                reconciled = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
                    db=db,
                    business_id=biz.id,
                    current_user=None,
                    limit=batch_size,
                )
                total_reconciled += len(reconciled)
            except Exception as biz_err:  # noqa: BLE001
                logger.warning(
                    "Scheduler failed to reconcile continuous scans for business %s: %s",
                    biz.id,
                    biz_err,
                )
                errors.append({"business_id": biz.id, "error": str(biz_err)})

        return {
            "businesses_scanned": businesses_scanned,
            "total_reconciled": total_reconciled,
            "errors": errors,
        }


# Global singleton instance for application lifespan
continuous_scheduler = ContinuousIntelligenceScheduler()


def run_scheduler_daemon() -> None:
    """Run the continuous intelligence scheduler as a dedicated standalone daemon process.

    Provides signal-aware execution (SIGINT, SIGTERM) for independent background worker
    containers or systemd units, preventing duplicate execution across multi-worker web processes.
    """
    import signal

    logger.info("Starting standalone Continuous Intelligence Scheduler daemon process...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    scheduler = ContinuousIntelligenceScheduler()
    scheduler.start()

    def handle_signal(sig: int, frame: Any) -> None:
        logger.info("Received termination signal (%d), initiating graceful shutdown...", sig)
        if scheduler._shutdown_event is not None:
            scheduler._shutdown_event.set()
        scheduler._is_running = False

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except (ValueError, AttributeError):
        # In non-main thread or special OS environments, signal handlers may not be attachable
        pass

    async def _wait_until_stopped() -> None:
        while scheduler.is_running:
            await asyncio.sleep(0.5)

    try:
        loop.run_until_complete(_wait_until_stopped())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler daemon received keyboard interrupt or system exit.")
    finally:
        if scheduler.is_running:
            loop.run_until_complete(scheduler.stop(timeout_seconds=5.0))
        loop.close()
        logger.info("Standalone scheduler daemon process terminated cleanly.")


if __name__ == "__main__":
    from app.core.logging import setup_logging

    setup_logging()
    run_scheduler_daemon()

