"""Dedicated health probe for the NEXUS Continuous Intelligence Scheduler (Phase 32B).

Executed as a container health check (e.g. `python -m app.scheduler_health`).
Verifies that:
1. The scheduler runner process is active and regularly updating its heartbeat.
2. The background asyncio scheduler task is alive and not crashed.
3. The continuous intelligence scheduler is actively making progress (not stalled).
4. Required infrastructure dependencies (PostgreSQL and Redis) are reachable.
5. Container configuration matches reported runner execution mode (standby vs. active).

SECURITY INVARIANT:
Never exposes credentials, secrets, database URLs, tenant data, or business IDs in stdout/stderr.
Outputs concise, sanitized operational health status and exits with:
- 0: Healthy
- 1: Unhealthy / Stalled / Failed

DESIGN DECISION (PID Check vs. Monotonic Heartbeat TTL in Containers):
Container runtimes (Docker, Kubernetes, ECS) frequently isolate process ID namespaces:
the healthcheck CLI probe runs in a separate exec/subshell process context from PID 1
(the scheduler runner), and rootless or multi-tenant containers may restrict `kill(pid, 0)`
probes across namespace boundaries. Furthermore, relying on PID existence cannot detect
event-loop hangs, deadlocks, or blocked I/O where the process is alive but completely unresponsive.
Therefore, this health probe relies on strict monotonic heartbeat file freshness (TTL <= 45s)
and progress counters updated by the running asyncio loop. Heartbeat pulse freshness guarantees
both process liveness and active event-loop execution without namespace or permission pitfalls.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("nexus.scheduler.health")

DEFAULT_HEARTBEAT_FILE = "nexus_scheduler_heartbeat.json"


def get_heartbeat_path() -> Path:
    """Resolve active heartbeat file path honoring SCHEDULER_HEARTBEAT_PATH."""
    custom_path = os.getenv("SCHEDULER_HEARTBEAT_PATH")
    if custom_path and custom_path.strip():
        return Path(custom_path.strip())

    # In Linux container environments, prefer /tmp
    tmp_dir = Path("/tmp")
    if tmp_dir.exists() and os.name != "nt":
        return tmp_dir / DEFAULT_HEARTBEAT_FILE

    # Cross-platform fallback (e.g. Windows development/testing)
    return Path(tempfile.gettempdir()) / DEFAULT_HEARTBEAT_FILE


def check_scheduler_health(
    max_heartbeat_age_seconds: float = 45.0,
    progress_grace_multiplier: float = 2.0,
    progress_grace_buffer_seconds: float = 120.0,
) -> tuple[bool, str, dict[str, Any]]:
    """Evaluate dedicated scheduler health against operational criteria.

    Args:
        max_heartbeat_age_seconds: Maximum allowable age of the runner heartbeat file.
        progress_grace_multiplier: Multiplier on interval_seconds before declaring progress stalled.
        progress_grace_buffer_seconds: Fixed buffer seconds added to interval before declaring stalled.

    Returns:
        tuple of (is_healthy: bool, summary_message: str, details: dict)
    """
    heartbeat_path = get_heartbeat_path()

    # 1. Verify heartbeat file existence
    if not heartbeat_path.exists():
        return (
            False,
            f"Heartbeat file not found at {heartbeat_path.name} (scheduler may not be started)",
            {"heartbeat_found": False},
        )

    # 2. Parse heartbeat file safely
    try:
        content = heartbeat_path.read_text(encoding="utf-8")
        data: dict[str, Any] = json.loads(content)
    except Exception as exc:
        return (
            False,
            f"Heartbeat file is corrupted or unreadable: {type(exc).__name__}",
            {"heartbeat_found": True, "parse_error": True},
        )

    now = time.time()
    heartbeat_timestamp = float(data.get("timestamp", 0.0))
    heartbeat_age = max(0.0, now - heartbeat_timestamp)

    # Authoritative container configuration
    config_enabled = bool(settings.CONTINUOUS_SCHEDULER_ENABLED)
    reported_enabled_raw = data.get("scheduler_enabled")

    details: dict[str, Any] = {
        "heartbeat_found": True,
        "heartbeat_age_seconds": round(heartbeat_age, 2),
        "status": data.get("status", "unknown"),
        "task_alive": data.get("task_alive", False),
        "scheduler_enabled": config_enabled,
        "reported_scheduler_enabled": reported_enabled_raw,
        "total_ticks": data.get("total_ticks", 0),
        "interval_seconds": data.get("interval_seconds", settings.CONTINUOUS_SCHEDULER_INTERVAL_SECONDS),
        "db_status": data.get("db_status", "unknown"),
        "redis_status": data.get("redis_status", "unknown"),
    }

    # 3. Check heartbeat freshness (runner process loop liveness)
    if heartbeat_age > max_heartbeat_age_seconds:
        return (
            False,
            f"Heartbeat is stale ({heartbeat_age:.1f}s old > max {max_heartbeat_age_seconds:.1f}s; runner loop hung or terminated)",
            details,
        )

    # 4. Check reported runner status
    runner_status = data.get("status")
    if runner_status in ("stopped", "crashed", "unhealthy"):
        return (
            False,
            f"Scheduler runner reported unhealthy status: {runner_status}",
            details,
        )

    # 5. Check configuration consistency between container settings and heartbeat
    if reported_enabled_raw is not None and bool(reported_enabled_raw) != config_enabled:
        return (
            False,
            f"Scheduler heartbeat mode (scheduler_enabled={reported_enabled_raw}) does not match authoritative container configuration (CONTINUOUS_SCHEDULER_ENABLED={config_enabled})",
            details,
        )

    if config_enabled and runner_status == "dormant":
        return (
            False,
            "Scheduler runner reported dormant status while authoritative container configuration has CONTINUOUS_SCHEDULER_ENABLED=True",
            details,
        )

    if not config_enabled and runner_status == "healthy":
        return (
            False,
            "Scheduler runner reported healthy active status while authoritative container configuration has CONTINUOUS_SCHEDULER_ENABLED=False",
            details,
        )

    scheduler_enabled = config_enabled

    # 6. Check background scheduler task liveness (only required when scheduler is enabled)
    if scheduler_enabled:
        if not data.get("task_alive", False):
            return (
                False,
                "Background continuous intelligence scheduler task is terminated/crashed",
                details,
            )

        # 7. Check scheduler progress (stalled execution detection)
        interval = float(details["interval_seconds"])
        total_ticks = int(details["total_ticks"])
        last_tick_at = data.get("last_tick_at")

        if total_ticks > 0 and last_tick_at is not None:
            last_tick_age = max(0.0, now - float(last_tick_at))
            details["last_tick_age_seconds"] = round(last_tick_age, 2)
            max_progress_age = (interval * progress_grace_multiplier) + progress_grace_buffer_seconds
            if last_tick_age > max_progress_age:
                return (
                    False,
                    f"Scheduler tick execution is stalled (last tick was {last_tick_age:.1f}s ago > threshold {max_progress_age:.1f}s)",
                    details,
                )
        elif total_ticks == 0:
            # Starting up: allow startup delay + initial tick buffer
            uptime = float(data.get("uptime_seconds", 0.0))
            max_initial_startup_wait = float(settings.CONTINUOUS_SCHEDULER_STARTUP_DELAY_SECONDS) + progress_grace_buffer_seconds
            if uptime > max_initial_startup_wait:
                return (
                    False,
                    f"Scheduler has not executed initial tick after {uptime:.1f}s (exceeds startup threshold {max_initial_startup_wait:.1f}s)",
                    details,
                )

    # 8. Check database dependency reachability
    db_status = data.get("db_status")
    if db_status != "connected":
        return (
            False,
            f"PostgreSQL database dependency is not connected (status: {db_status})",
            details,
        )

    # 9. Check Redis shared state dependency reachability (if required in production)
    is_prod = settings.is_production
    is_redis_mandatory = bool(settings.REDIS_FAIL_CLOSED or settings.REDIS_REQUIRED)
    redis_status = data.get("redis_status")
    if is_prod and is_redis_mandatory and redis_status != "connected":
        return (
            False,
            f"Redis shared state is required in production but reported: {redis_status}",
            details,
        )

    if scheduler_enabled:
        summary = (
            f"Scheduler healthy: uptime={data.get('uptime_seconds', 0):.0f}s, "
            f"ticks={details.get('total_ticks', 0)}, last_tick_age={details.get('last_tick_age_seconds', 'N/A')}s, "
            f"db={db_status}, redis={redis_status}"
        )
    else:
        summary = (
            f"Scheduler dormant (standby): uptime={data.get('uptime_seconds', 0):.0f}s, "
            f"ticks=0 (disabled), db={db_status}, redis={redis_status}"
        )
    return True, summary, details


def main() -> None:
    """CLI entrypoint for container health check."""
    is_healthy, summary, _ = check_scheduler_health()
    if is_healthy:
        print(f"HEALTHCHECK OK: {summary}")
        sys.exit(0)
    else:
        print(f"HEALTHCHECK FAILED: {summary}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
