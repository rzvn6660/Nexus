"""Unit and integration tests for dedicated scheduler health probe (Phase 32B).

Verifies:
1. Detection of missing, corrupted, or stale heartbeat files.
2. Detection of terminated/crashed background scheduler tasks.
3. Detection of stalled progress (ticks not advancing within threshold).
4. Dependency status evaluation (PostgreSQL and Redis reachability).
5. Sanitized operational summary with zero secret/tenant credential leakage.
6. CLI entrypoint exit codes (0 = healthy, 1 = unhealthy).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch
import pytest

from app.core.config import settings
from app.scheduler_health import check_scheduler_health, get_heartbeat_path, main


@pytest.fixture
def temp_heartbeat_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture providing an isolated temporary heartbeat file path."""
    hb_file = tmp_path / "test_scheduler_heartbeat.json"
    monkeypatch.setenv("SCHEDULER_HEARTBEAT_PATH", str(hb_file))
    return hb_file


def _write_heartbeat(
    path: Path,
    *,
    status: str = "healthy",
    timestamp: float | None = None,
    task_alive: bool = True,
    uptime_seconds: float = 30.0,
    total_ticks: int = 1,
    last_tick_at: float | None = None,
    interval_seconds: int = 60,
    db_status: str = "connected",
    redis_status: str = "connected",
) -> None:
    now = time.time()
    payload = {
        "timestamp": timestamp if timestamp is not None else now,
        "pid": 12345,
        "uptime_seconds": uptime_seconds,
        "status": status,
        "task_alive": task_alive,
        "total_ticks": total_ticks,
        "last_tick_at": last_tick_at if last_tick_at is not None else now - 5.0,
        "last_tick_duration_ms": 25.0,
        "last_tick_errors": 0,
        "interval_seconds": interval_seconds,
        "db_status": db_status,
        "redis_status": redis_status,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_scheduler_health_missing_heartbeat_fails(temp_heartbeat_file: Path):
    """When heartbeat file is missing, health check fails with informative summary."""
    assert not temp_heartbeat_file.exists()
    ok, msg, details = check_scheduler_health()
    assert ok is False
    assert "Heartbeat file not found" in msg
    assert details["heartbeat_found"] is False


def test_scheduler_health_corrupt_heartbeat_fails(temp_heartbeat_file: Path):
    """When heartbeat file contains invalid JSON, health check fails safely."""
    temp_heartbeat_file.write_text("NOT_VALID_JSON{{{", encoding="utf-8")
    ok, msg, details = check_scheduler_health()
    assert ok is False
    assert "corrupted or unreadable" in msg
    assert details.get("parse_error") is True


def test_scheduler_health_stale_heartbeat_fails(temp_heartbeat_file: Path):
    """When heartbeat timestamp is older than max_heartbeat_age_seconds, health check fails."""
    old_time = time.time() - 100.0  # 100s ago
    _write_heartbeat(temp_heartbeat_file, timestamp=old_time)

    ok, msg, details = check_scheduler_health(max_heartbeat_age_seconds=45.0)
    assert ok is False
    assert "Heartbeat is stale" in msg
    assert details["heartbeat_age_seconds"] >= 95.0


def test_scheduler_health_reported_unhealthy_status_fails(temp_heartbeat_file: Path):
    """When runner status indicates crash or stop, health check reports unhealthy."""
    _write_heartbeat(temp_heartbeat_file, status="crashed")
    ok, msg, _ = check_scheduler_health()
    assert ok is False
    assert "crashed" in msg

    _write_heartbeat(temp_heartbeat_file, status="stopped")
    ok, msg, _ = check_scheduler_health()
    assert ok is False
    assert "stopped" in msg


def test_scheduler_health_task_not_alive_fails(temp_heartbeat_file: Path):
    """When background asyncio task is dead, health check fails."""
    _write_heartbeat(temp_heartbeat_file, task_alive=False)
    ok, msg, details = check_scheduler_health()
    assert ok is False
    assert "task is terminated/crashed" in msg
    assert details["task_alive"] is False


def test_scheduler_health_stalled_progress_fails(temp_heartbeat_file: Path):
    """When ticks have started but no tick occurred within the progress threshold, marks stalled."""
    now = time.time()
    # Interval = 60, last tick was 400s ago (exceeds threshold 60*2 + 120 = 240s)
    _write_heartbeat(
        temp_heartbeat_file,
        total_ticks=5,
        interval_seconds=60,
        last_tick_at=now - 400.0,
    )
    ok, msg, details = check_scheduler_health(
        progress_grace_multiplier=2.0,
        progress_grace_buffer_seconds=120.0,
    )
    assert ok is False
    assert "Scheduler tick execution is stalled" in msg


def test_scheduler_health_stalled_startup_fails(temp_heartbeat_file: Path, monkeypatch: pytest.MonkeyPatch):
    """When scheduler has not executed its first tick after extended startup window, fails."""
    monkeypatch.setattr(settings, "CONTINUOUS_SCHEDULER_STARTUP_DELAY_SECONDS", 5)
    _write_heartbeat(
        temp_heartbeat_file,
        total_ticks=0,
        uptime_seconds=300.0,  # 300s without a single tick
        last_tick_at=None,
    )
    ok, msg, _ = check_scheduler_health(progress_grace_buffer_seconds=60.0)
    assert ok is False
    assert "has not executed initial tick" in msg


def test_scheduler_health_db_disconnected_fails(temp_heartbeat_file: Path):
    """When PostgreSQL is disconnected, health check reports failure."""
    _write_heartbeat(temp_heartbeat_file, db_status="disconnected")
    ok, msg, details = check_scheduler_health()
    assert ok is False
    assert "PostgreSQL database dependency is not connected" in msg
    assert details["db_status"] == "disconnected"


def test_scheduler_health_redis_disconnected_fails_in_production(
    temp_heartbeat_file: Path, monkeypatch: pytest.MonkeyPatch
):
    """In production with mandatory Redis, disconnected Redis causes health check failure."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "REDIS_FAIL_CLOSED", True)
    _write_heartbeat(temp_heartbeat_file, redis_status="unavailable")

    ok, msg, details = check_scheduler_health()
    assert ok is False
    assert "Redis shared state is required in production" in msg
    assert details["redis_status"] == "unavailable"


def test_scheduler_health_healthy_passes(temp_heartbeat_file: Path):
    """When all metrics are active and fresh, health check returns True with sanitized summary."""
    now = time.time()
    _write_heartbeat(
        temp_heartbeat_file,
        status="healthy",
        timestamp=now - 2.0,
        task_alive=True,
        uptime_seconds=120.0,
        total_ticks=3,
        last_tick_at=now - 10.0,
        interval_seconds=60,
        db_status="connected",
        redis_status="connected",
    )
    ok, msg, details = check_scheduler_health()
    assert ok is True
    assert "Scheduler healthy" in msg
    assert details["task_alive"] is True
    assert details["db_status"] == "connected"
    assert details["redis_status"] == "connected"


def test_scheduler_health_sanitized_output_no_secrets(temp_heartbeat_file: Path):
    """Verify that health messages never leak sensitive connection URLs, tokens, or IDs."""
    _write_heartbeat(temp_heartbeat_file)
    ok, msg, _ = check_scheduler_health()
    assert ok is True

    # Critical security checks: ensure no passwords, hosts, or tokens are logged
    forbidden = ["password", "secret", "token", "postgres://", "redis://", "http://", "biz_", "org_"]
    for token in forbidden:
        assert token not in msg.lower(), f"Sensitive token '{token}' detected in health output!"


def test_scheduler_health_cli_main_exit_codes(temp_heartbeat_file: Path):
    """Verify CLI main() exits with 0 on healthy and 1 on unhealthy."""
    # 1. Healthy exit 0
    _write_heartbeat(temp_heartbeat_file, status="healthy", task_alive=True, db_status="connected")
    with pytest.raises(SystemExit) as exc1:
        main()
    assert exc1.value.code == 0

    # 2. Unhealthy exit 1
    _write_heartbeat(temp_heartbeat_file, status="crashed", task_alive=False)
    with pytest.raises(SystemExit) as exc2:
        main()
    assert exc2.value.code == 1
