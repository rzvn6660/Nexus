"""NEXUS Phase 31B Step 4 — Dedicated Scheduler Worker & Operational Reliability Tests.

Validates:
1. SchedulerRunner dependency verification (PostgreSQL and Redis reachability pre-flight checks).
2. Signal handling (SIGTERM, SIGINT) and cooperative graceful termination without dangling locks.
3. Dedicated background worker service configuration in docker-compose.prod.yml.
4. Prevention of duplicate scheduler execution across multi-worker ASGI web processes.
5. Resource disposal (engine.dispose, close_cache) upon worker exit.
"""

import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import yaml

from app.core.config import settings
from app.scheduler_runner import SchedulerRunner


# ---------------------------------------------------------------------------
# 1. Dependency Pre-Flight Verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_runner_dependency_verification_success() -> None:
    """When PostgreSQL and Redis are reachable, verify_dependencies returns True."""
    runner = SchedulerRunner()

    with patch("app.scheduler_runner.check_database_connection", return_value={"status": "connected", "latency_ms": 1.2}), \
         patch("app.scheduler_runner.check_redis_health", return_value={"status": "connected", "shared_state_available": True, "required": True}):
        ok = await runner.verify_dependencies(max_retries=1)
        assert ok is True


@pytest.mark.asyncio
async def test_scheduler_runner_dependency_verification_fails_when_db_down() -> None:
    """When PostgreSQL is down, verify_dependencies fails after retries."""
    runner = SchedulerRunner()

    with patch("app.scheduler_runner.check_database_connection", return_value={"status": "disconnected", "error": "timeout"}), \
         patch("app.scheduler_runner.check_redis_health", return_value={"status": "connected", "shared_state_available": True, "required": True}):
        ok = await runner.verify_dependencies(max_retries=2, retry_interval=0.01)
        assert ok is False


@pytest.mark.asyncio
async def test_scheduler_runner_dependency_verification_allows_optional_redis_in_dev() -> None:
    """In development where Redis is optional, verify_dependencies passes if DB is up."""
    runner = SchedulerRunner()

    with patch("app.scheduler_runner.check_database_connection", return_value={"status": "connected", "latency_ms": 0.8}), \
         patch("app.scheduler_runner.check_redis_health", return_value={"status": "optional", "shared_state_available": False, "required": False}):
        ok = await runner.verify_dependencies(max_retries=1)
        assert ok is True


# ---------------------------------------------------------------------------
# 2. Signal Handling and Cooperative Shutdown
# ---------------------------------------------------------------------------


def test_scheduler_runner_handles_termination_signals() -> None:
    """Invoking handle_signal with SIGTERM or SIGINT triggers stop_event."""
    runner = SchedulerRunner()
    assert not runner.stop_event.is_set()

    runner.handle_signal(signal.SIGTERM)
    assert runner.stop_event.is_set()


@pytest.mark.asyncio
async def test_scheduler_runner_run_lifecycle_and_clean_disposal() -> None:
    """Test full runner lifecycle: starts scheduler, cooperatively stops upon signal, releases pools."""
    runner = SchedulerRunner()

    mock_scheduler = MagicMock()
    mock_scheduler.interval_seconds = 60
    mock_scheduler.max_businesses = 10
    mock_scheduler.batch_size = 5
    mock_scheduler.stop = AsyncMock()

    mock_dispose = MagicMock()
    mock_close_cache = MagicMock()

    with patch("app.scheduler_runner.continuous_scheduler", mock_scheduler), \
         patch("app.scheduler_runner.engine.dispose", mock_dispose), \
         patch("app.scheduler_runner.close_cache", mock_close_cache), \
         patch.object(runner, "verify_dependencies", AsyncMock(return_value=True)):

        # Trigger stop_event almost immediately after starting
        async def _trigger_stop():
            await asyncio.sleep(0.05)
            runner.stop_event.set()

        asyncio.create_task(_trigger_stop())

        exit_code = await runner.run()
        assert exit_code == 0

        # Verify scheduler was started and stopped cooperatively
        mock_scheduler.start.assert_called_once()
        mock_scheduler.stop.assert_awaited_once_with(timeout_seconds=5.0)

        # Verify connection pools were cleanly disposed
        mock_close_cache.assert_called_once()
        mock_dispose.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Docker Compose Production Configuration Validation
# ---------------------------------------------------------------------------


def test_docker_compose_production_scheduler_service() -> None:
    """Validate that docker-compose.prod.yml defines the dedicated scheduler worker with correct wiring."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    compose_path = repo_root / "docker-compose.prod.yml"
    assert compose_path.exists()

    with open(compose_path, "r", encoding="utf-8") as f:
        compose_cfg = yaml.safe_load(f)

    services = compose_cfg.get("services", {})
    assert "backend" in services, "backend service must exist"
    assert "scheduler" in services, "scheduler service must exist"

    # Backend web service must NOT autostart scheduler in multi-worker mode
    backend_env = services["backend"].get("environment", [])
    assert any("CONTINUOUS_SCHEDULER_AUTOSTART=false" in str(e) for e in backend_env), \
        "backend service must set CONTINUOUS_SCHEDULER_AUTOSTART=false to prevent duplicate workers"

    # Dedicated scheduler service configuration
    sched_svc = services["scheduler"]
    assert sched_svc.get("container_name") == "nexus_scheduler_prod"
    assert sched_svc.get("restart") == "unless-stopped"
    assert sched_svc.get("command") == ["python", "-m", "app.scheduler_runner"]

    sched_env = sched_svc.get("environment", [])
    assert any("CONTINUOUS_SCHEDULER_ENABLED=true" in str(e) for e in sched_env)
    assert any("CONTINUOUS_SCHEDULER_AUTOSTART=true" in str(e) for e in sched_env)

    # Must mount persistent tenant data volume
    sched_volumes = sched_svc.get("volumes", [])
    assert any("nexus_backend_data:/app/data" in str(v) for v in sched_volumes), \
        "scheduler must mount persistent tenant data volume"

    # Must depend on healthy postgres and redis
    sched_depends = sched_svc.get("depends_on", {})
    assert "postgres" in sched_depends
    assert "redis" in sched_depends


def test_scheduler_runner_fresh_subprocess_import_no_circular_dependencies() -> None:
    """Verify that app.scheduler_runner can be cleanly imported in a fresh Python process without circular imports."""
    import subprocess
    import sys
    backend_dir = Path(__file__).resolve().parent.parent

    proc = subprocess.run(
        [sys.executable, "-c", "import app.scheduler_runner; print('OK')"],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Import failed with stderr: {proc.stderr}\nstdout: {proc.stdout}"
    assert "OK" in proc.stdout

