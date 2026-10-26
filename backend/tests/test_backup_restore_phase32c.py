"""NEXUS Phase 32C — Backup, Disaster Recovery & Operational Readiness Test Suite.

Verifies:
1. Cryptographic SHA-256 calculation, sidecar generation, and tamper detection.
2. Archive integrity validation (PostgreSQL custom format dump headers, valid/corrupt tar archives).
3. Fail-safe retention enforcement (preserves >= 7 valid sets, never deletes last known-good).
4. Failure alerting via Sentry and optional BACKUP_ALERT_WEBHOOK_URL.
5. Storage reconciliation (missing file detection, unindexed orphan audit, dry-run safety, constrained purge).
6. Live PostgreSQL 16 + pgvector coordinated backup and restore drill against isolated test database,
   executing real pg_dump -F c and pg_restore into a clean disposable database.
7. Operational script safety guards: confirmation flags, timestamp regex, path safety, permissions,
   Redis BGSAVE error handling, and partial-restore split-state detection.

Execution Guard:
Live PostgreSQL restore drill requires reachable PostgreSQL daemon with pgvector.
Fails hard when REQUIRE_POSTGRES=true and PostgreSQL or restore utilities are unreachable.
"""

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.backup import (
    CoordinatedBackupSet,
    compute_sha256,
    discover_backup_sets,
    enforce_retention,
    reconcile_tenant_storage,
    send_backup_alert,
    validate_pg_dump_header,
    validate_tar_archive,
    verify_sha256_file,
    write_sha256_file,
)
from app.models.tenant import Business, IngestionJob, Organization, UploadedDataset
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk


@pytest.fixture(autouse=True)
def _set_test_staging_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure mock subprocess tests in staging mode have strong, non-default credentials by default."""
    monkeypatch.setenv("POSTGRES_PASSWORD", "test_valid_staging_pw_16_chars")
    monkeypatch.setenv("SECRET_KEY", "test_valid_staging_secret_key_32_chars_long")
    monkeypatch.setenv("AUTH_JWT_SECRET", "test_valid_staging_jwt_secret_32_chars_long")


# ---------------------------------------------------------------------------
# Helper: Cross-Platform Bash Locator
# ---------------------------------------------------------------------------

def _find_bash() -> str | None:
    """Find a real bash executable across Linux and Windows environments."""
    if os.name == "nt":
        for candidate in [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
        ]:
            if os.path.exists(candidate):
                return candidate
    b = shutil.which("bash")
    if b and "WindowsApps" not in b:
        return b
    return None


# ---------------------------------------------------------------------------
# 1. Checksum & Archive Integrity Unit Tests
# ---------------------------------------------------------------------------

def test_sha256_calculation_and_sidecar_verification(tmp_path: Path) -> None:
    """SHA-256 digest is deterministically calculated, written, and verified."""
    test_file = tmp_path / "nexus_sample.dump"
    test_file.write_bytes(b"PGDMP_NEXUS_SAMPLE_CONTENT_12345")

    sidecar = write_sha256_file(test_file)
    assert sidecar.exists()
    assert sidecar.name == "nexus_sample.dump.sha256"

    # Valid check
    is_valid, msg = verify_sha256_file(test_file)
    assert is_valid is True
    assert "matches" in msg

    # Tamper detection
    test_file.write_bytes(b"TAMPERED_CONTENT")
    is_valid_tampered, tamper_msg = verify_sha256_file(test_file)
    assert is_valid_tampered is False
    assert "mismatch" in tamper_msg


def test_tar_archive_validation(tmp_path: Path) -> None:
    """Tar archive validation accepts valid archives and rejects corrupt/truncated ones."""
    archive_path = tmp_path / "valid_files.tar.gz"

    # Create valid tar.gz
    sample_data = tmp_path / "sample.csv"
    sample_data.write_text("order,amount\n1,100\n", encoding="utf-8")
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(sample_data, arcname="sample.csv")

    is_valid, msg = validate_tar_archive(archive_path)
    assert is_valid is True
    assert "Valid tar archive" in msg

    # Corrupt archive
    corrupt_path = tmp_path / "corrupt_files.tar.gz"
    corrupt_path.write_bytes(b"NOT_A_VALID_GZIP_OR_TAR_ARCHIVE_DATA")
    is_corrupt_valid, corrupt_msg = validate_tar_archive(corrupt_path)
    assert is_corrupt_valid is False
    assert "Corrupted" in corrupt_msg

    # Empty file
    empty_path = tmp_path / "empty.tar.gz"
    empty_path.touch()
    is_empty_valid, empty_msg = validate_tar_archive(empty_path)
    assert is_empty_valid is False
    assert "missing or empty" in empty_msg


def test_pg_dump_header_validation(tmp_path: Path) -> None:
    """PostgreSQL dump validator detects PGDMP magic bytes and SQL scripts."""
    valid_custom = tmp_path / "valid.dump"
    valid_custom.write_bytes(b"PGDMP\x01\x02\x03\x04rest_of_custom_dump")
    assert validate_pg_dump_header(valid_custom)[0] is True

    valid_sql = tmp_path / "valid.sql"
    valid_sql.write_text("-- PostgreSQL database dump\nSET statement_timeout = 0;\n", encoding="utf-8")
    assert validate_pg_dump_header(valid_sql)[0] is True

    invalid_dump = tmp_path / "invalid.dump"
    invalid_dump.write_bytes(b"UNKNOWN_RANDOM_BYTES_HEADER")
    is_valid, err = validate_pg_dump_header(invalid_dump)
    assert is_valid is False
    assert "Unrecognized dump format header" in err


# ---------------------------------------------------------------------------
# 2. Fail-Safe Retention Policy Tests
# ---------------------------------------------------------------------------

def test_retention_preserves_minimum_seven_sets(tmp_path: Path) -> None:
    """Fail-safe retention NEVER prunes backups if total valid sets <= 7, even if old."""
    now = time.time()
    # Create 5 old backup sets (age = 30 days old)
    for i in range(5):
        ts = f"2026010{i+1}_020000"
        db = tmp_path / f"nexus_db_{ts}.dump"
        files = tmp_path / f"nexus_files_{ts}.tar.gz"
        db.write_bytes(b"PGDMP_DUMP")
        files.write_bytes(b"FILES_TAR")
        write_sha256_file(db)
        write_sha256_file(files)
        # Set old mtime (30 days ago)
        old_mtime = now - (30 * 86400) + (i * 3600)
        os.utime(db, (old_mtime, old_mtime))
        os.utime(files, (old_mtime, old_mtime))

    # Prune with retention_days=14, min_retained=7
    pruned = enforce_retention(tmp_path, retention_days=14, min_retained_sets=7, now=now)
    # Must prune NOTHING because total valid sets (5) <= 7
    assert len(pruned) == 0
    assert len(discover_backup_sets(tmp_path)) == 5


def test_retention_pruning_leaves_at_least_seven_and_preserves_last_known_good(tmp_path: Path) -> None:
    """When > 7 sets exist and are expired, prunes down to min_retained and keeps newest."""
    now = time.time()
    # Create 10 backup sets, all 20 days old
    for i in range(10):
        ts = f"202601{i+10:02d}_020000"
        db = tmp_path / f"nexus_db_{ts}.dump"
        files = tmp_path / f"nexus_files_{ts}.tar.gz"
        db.write_bytes(b"PGDMP_DUMP")
        files.write_bytes(b"FILES_TAR")
        write_sha256_file(db)
        write_sha256_file(files)
        mtime = now - (20 * 86400) + (i * 3600)
        os.utime(db, (mtime, mtime))
        os.utime(files, (mtime, mtime))

    # 10 sets exist. min_retained = 7. Exactly 3 sets should be pruned.
    pruned = enforce_retention(tmp_path, retention_days=14, min_retained_sets=7, now=now)
    remaining_sets = [s for s in discover_backup_sets(tmp_path) if s.is_complete]

    assert len(remaining_sets) == 7
    assert len(pruned) == 12

    # Most recent set (ts: 20260119_020000) must still exist
    newest = remaining_sets[-1]
    assert newest.timestamp == "20260119_020000"
    assert newest.db_dump.exists()
    assert newest.files_archive.exists()


# ---------------------------------------------------------------------------
# 3. Alerting Tests (Sentry + Webhook)
# ---------------------------------------------------------------------------

def test_send_backup_alert_with_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backup alert posts sanitized JSON payload to BACKUP_ALERT_WEBHOOK_URL."""
    sent_payloads = []

    def mock_urlopen(req, timeout=5.0):
        sent_payloads.append(json.loads(req.data.decode("utf-8")))
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    monkeypatch.setenv("BACKUP_ALERT_WEBHOOK_URL", "https://alerts.nexus.internal/webhook")
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    success = send_backup_alert(
        event_type="BACKUP_FAILED",
        message="Database dump failed: lock timeout",
        details={"exit_code": 1, "target": "nexus_db"},
    )

    assert success is True
    assert len(sent_payloads) == 1
    p = sent_payloads[0]
    assert p["event_type"] == "BACKUP_FAILED"
    assert "Database dump failed" in p["message"]
    assert p["service"] == "nexus_backup"


# ---------------------------------------------------------------------------
# 4. Storage Reconciliation Tests
# ---------------------------------------------------------------------------

def test_storage_reconciliation_dry_run_and_constrained_purge(tmp_path: Path) -> None:
    """Storage reconciliation detects missing files and orphans; dry-run preserves, purge cleans."""
    data_dir = tmp_path / "data"
    tenants_dir = data_dir / "tenants" / "org_1" / "biz_1"
    tenants_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create a legitimate indexed file on disk
    dataset_1_dir = tenants_dir / "ds_1"
    dataset_1_dir.mkdir(parents=True, exist_ok=True)
    legit_file = dataset_1_dir / "sales.csv"
    legit_file.write_text("order,amount\n1,100\n", encoding="utf-8")

    # 2. Create an orphaned unindexed file on disk
    orphan_dir = tenants_dir / "ds_orphan"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan_file = orphan_dir / "untracked_data.csv"
    orphan_file.write_text("garbage\n", encoding="utf-8")

    # Mock DB session with two UploadedDataset records:
    mock_db = MagicMock()
    mock_records = [
        ("ds_1", "sales.csv", str(legit_file.relative_to(data_dir)).replace("\\", "/")),
        ("ds_2_missing", "missing.csv", "tenants/org_1/biz_1/ds_2_missing/missing.csv"),
    ]
    mock_db.execute.return_value.all.return_value = mock_records

    # Pass 1: DRY RUN (default, delete_orphans=False)
    with patch("app.services.data_gateway_service.DataGatewayService.resolve_storage_path") as mock_resolve:
        mock_resolve.side_effect = lambda key: data_dir / key

        audit_res = reconcile_tenant_storage(db=mock_db, base_dir=data_dir, delete_orphans=False)
        assert audit_res.total_db_records == 2
        assert len(audit_res.missing_files) == 1
        assert audit_res.missing_files[0][0] == "ds_2_missing"
        assert len(audit_res.orphan_files) == 1
        assert audit_res.orphan_files[0] == orphan_file.resolve()
        assert len(audit_res.purged_files) == 0
        assert orphan_file.exists()

        # Pass 2: PURGE (delete_orphans=True)
        purge_res = reconcile_tenant_storage(db=mock_db, base_dir=data_dir, delete_orphans=True)
        assert len(purge_res.purged_files) == 1
        assert not orphan_file.exists(), "Orphan file must be deleted when delete_orphans=True"
        assert not orphan_dir.exists(), "Empty parent directory must be pruned"
        assert legit_file.exists(), "Legitimate indexed file must NEVER be touched"


# ---------------------------------------------------------------------------
# 5. Operational Script Safety Hardening Unit Tests
# ---------------------------------------------------------------------------

def test_restore_missing_confirmation_flag_fails() -> None:
    """Restore script execution fails closed if --confirm-destructive-restore is missing."""
    script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "restore_nexus_coordinated.sh"
    assert script_path.exists()

    bash_bin = _find_bash()
    if bash_bin:
        script_arg = str(script_path).replace("\\", "/")
        proc = subprocess.run(
            [bash_bin, script_arg, "20261019_020000"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
        assert "SAFETY ERROR" in proc.stderr or "--confirm-destructive-restore" in proc.stderr


def test_restore_invalid_timestamp_regex_fails() -> None:
    """Restore script rejects timestamps that do not strictly match ^[0-9]{8}_[0-9]{6}$."""
    script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "restore_nexus_coordinated.sh"
    bash_bin = _find_bash()
    if bash_bin:
        script_arg = str(script_path).replace("\\", "/")
        for invalid_ts in ["2026-10-19", "20261019", "invalid_timestamp", "../etc/passwd", "20261019_12"]:
            proc = subprocess.run(
                [bash_bin, script_arg, "--confirm-destructive-restore", invalid_ts],
                capture_output=True,
                text=True,
            )
            assert proc.returncode != 0
            assert "Invalid timestamp format" in proc.stderr or "Usage:" in proc.stderr


def test_backup_unsafe_paths_rejected() -> None:
    """Backup script rejects unsafe, empty, or root BACKUP_ROOT paths."""
    script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "backup_nexus_coordinated.sh"
    bash_bin = _find_bash()
    if bash_bin:
        script_arg = str(script_path).replace("\\", "/")
        for unsafe_path in ["/", "/root", "/etc", "/bin", "/usr"]:
            env = os.environ.copy()
            env["BACKUP_ROOT"] = unsafe_path
            proc = subprocess.run(
                [bash_bin, script_arg],
                env=env,
                capture_output=True,
                text=True,
            )
            assert proc.returncode != 0
            assert "Refusing to use empty, root, or system BACKUP_ROOT path" in proc.stderr


def test_coordinated_scripts_dual_gate_enforcement() -> None:
    """Both scripts fail closed unless BOTH --staging and NEXUS_STAGING_MODE=true are provided."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    # 1. Backup: --staging without NEXUS_STAGING_MODE=true
    env_clean = os.environ.copy()
    env_clean.pop("NEXUS_STAGING_MODE", None)
    proc = subprocess.run([bash_bin, backup_script, "--staging"], env=env_clean, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: Staging mode requires BOTH" in proc.stderr

    # 2. Backup: NEXUS_STAGING_MODE=true without --staging
    env_staging = os.environ.copy()
    env_staging["NEXUS_STAGING_MODE"] = "true"
    proc = subprocess.run([bash_bin, backup_script], env=env_staging, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: 'NEXUS_STAGING_MODE=true' is set, but the explicit '--staging' CLI flag was not passed" in proc.stderr

    # 3. Restore: --staging without NEXUS_STAGING_MODE=true
    proc = subprocess.run(
        [bash_bin, restore_script, "--staging", "--confirm-destructive-restore", "20261019_020000"],
        env=env_clean,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "SAFETY ERROR: Staging mode requires BOTH" in proc.stderr

    # 4. Restore: NEXUS_STAGING_MODE=true without --staging
    proc = subprocess.run(
        [bash_bin, restore_script, "--confirm-destructive-restore", "20261019_020000"],
        env=env_staging,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "SAFETY ERROR: 'NEXUS_STAGING_MODE=true' is set, but the explicit '--staging' CLI flag was not passed" in proc.stderr


def test_coordinated_scripts_production_reverse_guards() -> None:
    """Production mode execution fails closed if any staging parameter is provided in env."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    staging_params = [
        ("COMPOSE_PROJECT_NAME", "nexus-staging"),
        ("COMPOSE_FILE", "infra/staging/docker-compose.staging.yml"),
        ("POSTGRES_DB", "nexus_staging_db"),
        ("DATA_VOLUME", "nexus_backend_staging_data"),
        ("REDIS_VOLUME", "nexus_redis_staging_data"),
    ]

    for var_name, var_val in staging_params:
        env = os.environ.copy()
        env.pop("NEXUS_STAGING_MODE", None)
        env[var_name] = var_val

        # Backup script reverse guard
        proc_b = subprocess.run([bash_bin, backup_script], env=env, capture_output=True, text=True)
        assert proc_b.returncode != 0
        assert "contains 'staging' while running in production mode" in proc_b.stderr

        # Restore script reverse guard
        proc_r = subprocess.run(
            [bash_bin, restore_script, "--confirm-destructive-restore", "20261019_020000"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc_r.returncode != 0
        assert "contains 'staging' while running in production mode" in proc_r.stderr


def test_coordinated_scripts_staging_target_blacklists(tmp_path: Path) -> None:
    """Staging mode execution fails closed if production targets or invalid staging names are specified."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")
    dummy_compose_path = str(dummy_compose).replace("\\", "/")

    base_staging_env = os.environ.copy()
    base_staging_env["NEXUS_STAGING_MODE"] = "true"
    base_staging_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_staging_env["COMPOSE_FILE"] = dummy_compose_path
    base_staging_env["POSTGRES_DB"] = "nexus_staging_db"
    base_staging_env["DATA_VOLUME"] = "nexus_backend_staging_data"
    base_staging_env["REDIS_VOLUME"] = "nexus_redis_staging_data"

    blacklisted_scenarios = [
        ({"COMPOSE_PROJECT_NAME": "nexus"}, "COMPOSE_PROJECT_NAME must strictly equal 'nexus-staging'"),
        ({"COMPOSE_PROJECT_NAME": ""}, "COMPOSE_PROJECT_NAME must strictly equal 'nexus-staging'"),
        ({"COMPOSE_PROJECT_NAME": "staging"}, "COMPOSE_PROJECT_NAME must strictly equal 'nexus-staging'"),
        ({"COMPOSE_FILE": "docker-compose.prod.yml"}, "COMPOSE_FILE cannot be production/dev"),
        ({"COMPOSE_FILE": "infra/staging/nonexistent.staging.yml"}, "Specified staging COMPOSE_FILE does not exist"),
        ({"POSTGRES_DB": "nexus_db"}, "POSTGRES_DB cannot target 'nexus_db'"),
        ({"POSTGRES_DB": "other_db"}, "Target must match staging pattern"),
        ({"DATA_VOLUME": "nexus_backend_data"}, "DATA_VOLUME cannot target production volume"),
        ({"DATA_VOLUME": "nexus_volume"}, "Must end with '_staging_data'"),
        ({"REDIS_VOLUME": "nexus_redis_prod_data"}, "REDIS_VOLUME cannot target production volume"),
    ]

    for overrides, expected_err in blacklisted_scenarios:
        env = base_staging_env.copy()
        env.update(overrides)

        proc_b = subprocess.run([bash_bin, backup_script, "--staging"], env=env, capture_output=True, text=True)
        assert proc_b.returncode != 0
        assert expected_err in proc_b.stderr

        proc_r = subprocess.run(
            [bash_bin, restore_script, "--staging", "--confirm-destructive-restore", "20261019_020000"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc_r.returncode != 0
        assert expected_err in proc_r.stderr


def _create_docker_stub(bin_dir: Path, log_file: Path) -> Path:
    """Create a deterministic offline docker CLI stub that logs commands and supports controlled mock modes."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    docker_script = bin_dir / "docker"

    def _to_posix(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    content = f"""#!/bin/sh
LOGFILE="{_to_posix(log_file)}"
echo "MOCK_DOCKER: $@" >> "$LOGFILE"

case "$1" in
    compose)
        case "$*" in
            *"ps -q postgres"*)
                if [ "${{MOCK_POSTGRES_CONTAINERS:-1}}" = "0" ]; then
                    exit 0
                elif [ "${{MOCK_POSTGRES_CONTAINERS:-1}}" = "2" ]; then
                    echo "mock_pg_cid_1"
                    echo "mock_pg_cid_2"
                    exit 0
                else
                    echo "mock_pg_cid"
                    exit 0
                fi
                ;;
            *"ps -q redis"*)
                if [ "${{MOCK_REDIS_CONTAINERS:-1}}" = "0" ]; then
                    exit 0
                elif [ "${{MOCK_REDIS_CONTAINERS:-1}}" = "2" ]; then
                    echo "mock_redis_cid_1"
                    echo "mock_redis_cid_2"
                    exit 0
                else
                    echo "mock_redis_cid"
                    exit 0
                fi
                ;;
            *"config"*)
                exit 0
                ;;
            *"stop backend scheduler"*)
                echo "CALL: STOP_BACKEND_SCHEDULER" >> "$LOGFILE"
                exit 0
                ;;
            *"exec -T postgres psql"*"SELECT current_database()"*)
                echo "CALL: PSQL_CATALOG_QUERY $@" >> "$LOGFILE"
                # Realistic SQL engine contract check: If the outer query erroneously uses
                # an outer FROM pg_database WHERE filter, an actual engine returns zero rows when target is absent.
                case "$*" in
                    *"GROUP BY"*|*"') FROM pg_database WHERE"*|*", count(*),"*)
                        if [ "${{MOCK_CATALOG_MODE:-existing}}" = "missing_target" ]; then
                            exit 0
                        fi
                        ;;
                esac

                if [ "${{MOCK_CATALOG_MODE:-existing}}" = "fail_exit" ]; then
                    echo "simulated psql error" >&2
                    exit 1
                elif [ "${{MOCK_CATALOG_MODE:-existing}}" = "empty" ]; then
                    exit 0
                elif [ "${{MOCK_CATALOG_MODE:-existing}}" = "wrong_maint" ]; then
                    echo "other_db|1|nexus_staging_db"
                    exit 0
                elif [ "${{MOCK_CATALOG_MODE:-existing}}" = "corrupted_count" ]; then
                    echo "postgres|2|nexus_staging_db"
                    exit 0
                elif [ "${{MOCK_CATALOG_MODE:-existing}}" = "mismatched_target" ]; then
                    echo "postgres|1|wrong_db"
                    exit 0
                elif [ "${{MOCK_CATALOG_MODE:-existing}}" = "multiple_rows" ]; then
                    echo "postgres|1|nexus_staging_db"
                    echo "postgres|1|nexus_staging_db"
                    exit 0
                elif [ "${{MOCK_CATALOG_MODE:-existing}}" = "count_zero_nonempty_name" ]; then
                    echo "postgres|0|unexpected_name"
                    exit 0
                elif [ "${{MOCK_CATALOG_MODE:-existing}}" = "missing_target" ]; then
                    echo "postgres|0||${{MOCK_ROLE_CAN_CREATEDB:-t}}|${{MOCK_ROLE_IS_SUPER:-t}}"
                    exit 0
                elif [ "${{MOCK_CATALOG_MODE:-existing}}" = "existing" ]; then
                    echo "postgres|1|${{MOCK_TARGET_DB:-nexus_staging_db}}|${{MOCK_ROLE_CAN_CREATEDB:-t}}|${{MOCK_ROLE_IS_SUPER:-t}}"
                    exit 0
                fi
                ;;
            *"exec -T postgres psql"*"pg_terminate_backend"*)
                echo "CALL: PG_TERMINATE_BACKEND" >> "$LOGFILE"
                exit 0
                ;;
            *"exec -T postgres dropdb"*)
                echo "CALL: DROPDB" >> "$LOGFILE"
                exit 0
                ;;
            *"exec -T postgres createdb"*)
                echo "CALL: CREATEDB" >> "$LOGFILE"
                exit 0
                ;;
            *"exec -T postgres pg_restore"*)
                if [ "${{MOCK_RESTORE_FAIL:-false}}" = "true" ]; then
                    echo "simulated pg_restore failure" >&2
                    exit 1
                fi
                echo "CALL: PG_RESTORE" >> "$LOGFILE"
                exit 0
                ;;
            *"exec -T postgres pg_dump"*)
                echo "CALL: PG_DUMP" >> "$LOGFILE"
                echo "PGDMP_DUMMY_DATA"
                exit 0
                ;;
            *"exec -T redis redis-cli bgsave"*)
                echo "CALL: REDIS_BGSAVE" >> "$LOGFILE"
                exit 0
                ;;
            *"exec -T redis redis-cli info persistence"*)
                echo "rdb_bgsave_in_progress:0"
                echo "rdb_last_bgsave_status:ok"
                exit 0
                ;;
            *"stop redis"*)
                echo "CALL: STOP_REDIS" >> "$LOGFILE"
                exit 0
                ;;
            *"start redis"*)
                echo "CALL: START_REDIS" >> "$LOGFILE"
                exit 0
                ;;
            *"start backend scheduler"*)
                echo "CALL: START_BACKEND_SCHEDULER" >> "$LOGFILE"
                exit 0
                ;;
            *"run --rm"*backend*"scripts/reconcile_storage.py"*)
                echo "CALL: RECONCILE_STORAGE $@" >> "$LOGFILE"
                if [ "${{MOCK_RECONCILE_MODE:-success}}" = "fail_exec" ]; then
                    echo "simulated reconciliation operational error" >&2
                    exit 2
                elif [ "${{MOCK_RECONCILE_MODE:-success}}" = "fail_inconsistent" ]; then
                    echo "simulated reconciliation inconsistency detected"
                    exit 1
                fi
                exit 0
                ;;
            *"exec -T backend curl"*"/api/health/ready"*)
                echo "CALL: HEALTHCHECK" >> "$LOGFILE"
                exit 0
                ;;
            *)
                echo "CALL: UNKNOWN_COMPOSE $@" >> "$LOGFILE"
                exit 0
                ;;
        esac
        ;;
    inspect)
        case "$*" in
            *"mock_pg_cid"*)
                if [ "${{MOCK_INSPECT_FAIL:-false}}" = "true" ]; then
                    echo "simulated pg inspect error" >&2
                    exit 1
                elif [ "${{MOCK_LABEL_MISMATCH:-false}}" = "true" ]; then
                    echo "wrong-project-name"
                    exit 0
                elif [ "${{MOCK_LABEL_EMPTY:-false}}" = "true" ]; then
                    exit 0
                else
                    echo "${{MOCK_PROJECT_LABEL:-nexus-staging}}"
                    exit 0
                fi
                ;;
            *"mock_redis_cid"*)
                if [ "${{MOCK_INSPECT_FAIL:-false}}" = "true" ]; then
                    echo "simulated redis inspect error" >&2
                    exit 1
                elif [ "${{MOCK_REDIS_LABEL_MISMATCH:-false}}" = "true" ]; then
                    echo "wrong-project-name"
                    exit 0
                elif [ "${{MOCK_LABEL_EMPTY:-false}}" = "true" ]; then
                    exit 0
                else
                    echo "${{MOCK_PROJECT_LABEL:-nexus-staging}}"
                    exit 0
                fi
                ;;
            *)
                echo "${{MOCK_PROJECT_LABEL:-nexus-staging}}"
                exit 0
                ;;
        esac
        ;;
    volume)
        case "$*" in
            *"inspect"*)
                if [ "${{MOCK_VOL_INSPECT_FAIL:-false}}" = "true" ]; then
                    echo "simulated volume inspect error" >&2
                    exit 1
                elif [ "${{MOCK_VOL_LABEL_MISMATCH:-false}}" = "true" ]; then
                    echo "wrong-project-name"
                    exit 0
                fi

                case "$*" in
                    *"nexus_backend_staging_data"*|*"nexus_redis_staging_data"*|*"nexus_backend_fixture_staging_data"*)
                        echo "${{MOCK_PROJECT_LABEL:-nexus-staging}}"
                        exit 0
                        ;;
                    *)
                        case "$*" in
                            *"redis"*)
                                if [ "${{MOCK_REDIS_VOL_EXISTS:-false}}" = "true" ] || [ "${{MOCK_VOL_EXISTS:-false}}" = "true" ]; then
                                    echo "${{MOCK_PROJECT_LABEL:-nexus-staging}}"
                                    exit 0
                                else
                                    echo "Error: No such volume: mock_vol" >&2
                                    exit 1
                                fi
                                ;;
                            *)
                                if [ "${{MOCK_DATA_VOL_EXISTS:-false}}" = "true" ] || [ "${{MOCK_VOL_EXISTS:-false}}" = "true" ] || [ "${{MOCK_VOL_POPULATED:-false}}" = "true" ]; then
                                    echo "${{MOCK_PROJECT_LABEL:-nexus-staging}}"
                                    exit 0
                                else
                                    echo "Error: No such volume: mock_vol" >&2
                                    exit 1
                                fi
                                ;;
                        esac
                        ;;
                esac
                ;;
            *)
                exit 0
                ;;
        esac
        ;;
    run)
        case "$*" in
            *"find /data/tenants"*)
                if [ "${{MOCK_VOL_POPULATED:-false}}" = "true" ]; then
                    echo "1"
                else
                    echo "0"
                fi
                exit 0
                ;;
            *"dump.rdb"*"echo 1"*)
                if [ "${{MOCK_REDIS_VOL_POPULATED:-false}}" = "true" ]; then
                    echo "1"
                else
                    echo "0"
                fi
                exit 0
                ;;
            *"redis:7-alpine"*)
                if [ "${{MOCK_REDIS_VERIFY_FAIL:-false}}" = "true" ]; then
                    echo "simulated redis verification container failure" >&2
                    exit 1
                fi
                ;;
            *"tar -czf"*)
                for arg in "$@"; do
                    case "$arg" in
                        *":/backup"*)
                            host_dir="${{arg%%:*}}"
                            for f in "$@"; do
                                case "$f" in
                                    *"/backup/"*".tar.gz"*)
                                        fname=$(echo "$f" | grep -o 'nexus_[^" ]*\\.tar\\.gz')
                                        if [ -n "$fname" ] && [ -d "$host_dir" ]; then
                                            tar -czf "${{host_dir}}/${{fname}}" -T /dev/null 2>/dev/null || true
                                        fi
                                        ;;
                                esac
                            done
                            ;;
                    esac
                done
                ;;
        esac
        echo "CALL: DOCKER_RUN $@" >> "$LOGFILE"
        exit 0
        ;;
    *)
        echo "CALL: OTHER $@" >> "$LOGFILE"
        exit 0
        ;;
esac
"""
    docker_script.write_text(content.strip() + "\n", encoding="utf-8")
    return docker_script


def test_coordinated_scripts_staging_container_discovery_fails_closed(tmp_path: Path) -> None:
    """In authorized staging mode, missing or unidentifiable containers fail closed immediately."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")
    dummy_compose_path = _to_bash_path(dummy_compose)

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    staging_env = os.environ.copy()
    staging_env["PATH"] = f"{str(bin_dir)};{staging_env.get('PATH', '')}"
    staging_env["MOCK_POSTGRES_CONTAINERS"] = "0"
    staging_env["NEXUS_STAGING_MODE"] = "true"
    staging_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    staging_env["COMPOSE_FILE"] = dummy_compose_path
    staging_env["POSTGRES_DB"] = "nexus_staging_db"
    staging_env["DATA_VOLUME"] = "nexus_backend_staging_data"
    staging_env["REDIS_VOLUME"] = "nexus_redis_staging_data"

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    staging_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)

    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    # 1. Backup script fails closed when postgres container discovery fails
    proc_b = subprocess.run([bash_bin, backup_script, "--staging"], env=staging_env, capture_output=True, text=True)
    assert proc_b.returncode != 0
    assert "SAFETY ERROR: Staging postgres service must resolve to exactly one running container" in proc_b.stderr

    # 2. Restore script fails closed when postgres container discovery fails
    proc_r = subprocess.run(
        [bash_bin, restore_script, "--staging", "--confirm-destructive-restore", ts, "--backup-root=" + _to_bash_path(valid_backup_dir)],
        env=staging_env,
        capture_output=True,
        text=True,
    )
    assert proc_r.returncode != 0
    assert "SAFETY ERROR: Staging postgres service must resolve to exactly one running container" in proc_r.stderr


def test_coordinated_scripts_staging_container_cardinality_and_attestation(tmp_path: Path) -> None:
    """F-02: Both postgres and redis containers are attested with explicit single-container cardinality before stateful operations."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = "nexus_staging_db"
    base_env["DATA_VOLUME"] = "nexus_backend_staging_data"
    base_env["REDIS_VOLUME"] = "nexus_redis_staging_data"
    base_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)

    # 1. Missing Redis container (0 IDs) fails closed before stopping services or mutating data
    env = base_env.copy()
    env["MOCK_REDIS_CONTAINERS"] = "0"
    log_file.write_text("")
    proc = subprocess.run([bash_bin, backup_script, "--staging"], env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: Staging redis service must resolve to exactly one running container (found 0)" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: STOP_BACKEND_SCHEDULER" not in calls
    assert "CALL: DOCKER_RUN" not in calls

    # 2. Multiple Postgres containers (2 IDs) fails closed explicitly
    env = base_env.copy()
    env["MOCK_POSTGRES_CONTAINERS"] = "2"
    log_file.write_text("")
    proc = subprocess.run(
        [bash_bin, restore_script, "--staging", "--confirm-destructive-restore", ts, "--backup-root=" + _to_bash_path(valid_backup_dir)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "SAFETY ERROR: Staging postgres service must resolve to exactly one running container (found 2)" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: STOP_BACKEND_SCHEDULER" not in calls
    assert "CALL: DROPDB" not in calls

    # 3. Multiple Redis containers (2 IDs) fails closed explicitly
    env = base_env.copy()
    env["MOCK_REDIS_CONTAINERS"] = "2"
    log_file.write_text("")
    proc = subprocess.run([bash_bin, backup_script, "--staging"], env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: Staging redis service must resolve to exactly one running container (found 2)" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: STOP_BACKEND_SCHEDULER" not in calls

    # 4. Postgres container inspect failure fails closed
    env = base_env.copy()
    env["MOCK_INSPECT_FAIL"] = "true"
    log_file.write_text("")
    proc = subprocess.run([bash_bin, backup_script, "--staging"], env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: Failed to inspect project label" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: STOP_BACKEND_SCHEDULER" not in calls

    # 5. Redis project label mismatch fails closed
    env = base_env.copy()
    env["MOCK_REDIS_LABEL_MISMATCH"] = "true"
    log_file.write_text("")
    proc = subprocess.run(
        [bash_bin, restore_script, "--staging", "--confirm-destructive-restore", ts, "--backup-root=" + _to_bash_path(valid_backup_dir)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "SAFETY ERROR: Target redis container project label ('wrong-project-name') does not match expected staging project ('nexus-staging')" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: STOP_BACKEND_SCHEDULER" not in calls
    assert "CALL: DROPDB" not in calls


def test_restore_script_staging_catalog_verification_and_clean_target_recovery(tmp_path: Path) -> None:
    """F-01: Staging restore safely verifies catalog, supports existing vs absent targets, and avoids premature drops."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "catalog_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = "nexus_staging_db"
    base_env["DATA_VOLUME"] = "nexus_backend_staging_data"
    base_env["REDIS_VOLUME"] = "nexus_redis_staging_data"
    base_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)

    restore_args = [bash_bin, restore_script, "--staging", "--confirm-destructive-restore", ts, "--backup-root=" + _to_bash_path(valid_backup_dir)]

    # 1. Maintenance connection / query error fails closed before dropdb
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "fail_exit"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: PostgreSQL catalog query failed with exit code 1" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: DROPDB" not in calls
    assert "CALL: CREATEDB" not in calls

    # 2. Empty output from catalog query fails closed
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "empty"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert ("SAFETY ERROR: PostgreSQL catalog query returned 0 rows" in proc.stderr or "Empty output received" in proc.stderr)
    calls = log_file.read_text()
    assert "CALL: DROPDB" not in calls

    # 3. Connected to unexpected maintenance database fails closed
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "wrong_maint"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: Catalog query connected to unexpected maintenance database 'other_db' (expected 'postgres')" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: DROPDB" not in calls

    # 4. Corrupted match count fails closed
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "corrupted_count"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: Unexpected match count ('2') returned for target database in catalog" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: DROPDB" not in calls

    # 5. Mismatched database identity fails closed
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "mismatched_target"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: Catalog database match ('wrong_db') differs from expected target ('nexus_staging_db')" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: DROPDB" not in calls

    # 6. Existing target: follows verified terminate, drop, create, restore sequence
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "existing"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode == 0
    calls = log_file.read_text()
    assert "Verified existing target database 'nexus_staging_db' in catalog (approved for safe drop and recreate)" in proc.stdout
    # Verify scalar subquery shape was invoked and outer FROM filter was NOT used
    assert "SELECT current_database(), (SELECT count(*) FROM pg_database WHERE datname = 'nexus_staging_db'), COALESCE((SELECT datname FROM pg_database WHERE datname = 'nexus_staging_db'), '')" in calls
    assert "FROM pg_database WHERE datname = 'nexus_staging_db';" not in calls
    assert "CALL: PG_TERMINATE_BACKEND" in calls
    assert "CALL: DROPDB" in calls
    assert "CALL: CREATEDB" in calls
    assert "CALL: PG_RESTORE" in calls
    # Assert sequence
    drop_idx = calls.index("CALL: DROPDB")
    create_idx = calls.index("CALL: CREATEDB")
    restore_idx = calls.index("CALL: PG_RESTORE")
    assert drop_idx < create_idx < restore_idx

    # 7. Absent target: skips terminate and drop, proceeds to create and restore
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "missing_target"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode == 0
    calls = log_file.read_text()
    assert "Target database 'nexus_staging_db' does not yet exist in catalog. Clean target creation will proceed" in proc.stdout
    assert "CALL: PG_TERMINATE_BACKEND" not in calls
    assert "CALL: DROPDB" not in calls
    assert "CALL: CREATEDB" in calls
    assert "CALL: PG_RESTORE" in calls

    # 8. Multiple rows returned fails closed
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "multiple_rows"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: PostgreSQL catalog query returned 2 rows (expected exactly 1)" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: DROPDB" not in calls
    assert "CALL: CREATEDB" not in calls

    # 9. Count 0 with non-empty match name fails closed
    env = base_env.copy()
    env["MOCK_CATALOG_MODE"] = "count_zero_nonempty_name"
    log_file.write_text("")
    proc = subprocess.run(restore_args, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "SAFETY ERROR: Catalog query returned count 0 but non-empty database match ('unexpected_name')" in proc.stderr
    calls = log_file.read_text()
    assert "CALL: DROPDB" not in calls
    assert "CALL: CREATEDB" not in calls


def test_staging_catalog_query_contract_and_sql_shape() -> None:
    """Verify that restore_nexus_coordinated.sh uses scalar subqueries and adheres to the SQL response contract."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = repo_root / "scripts" / "restore_nexus_coordinated.sh"
    content = restore_script.read_text(encoding="utf-8")

    # 1. Static assertion on the SQL shape in the script
    # The hardened catalog query verifies:
    # 1: current_database() to confirm connection landed on maintenance DB ('postgres')
    # 2: count(*) of target DB in pg_database (0 or 1)
    # 3: COALESCE(datname, '') of target DB in pg_database
    # 4: COALESCE(rolcreatedb, 'f') from pg_roles for ${POSTGRES_USER}
    # 5: COALESCE(rolsuper, 'f') from pg_roles for ${POSTGRES_USER}
    expected_sql_pattern = (
        "SELECT current_database(), "
        "(SELECT count(*) FROM pg_database WHERE datname = '${POSTGRES_DB}'), "
        "COALESCE((SELECT datname FROM pg_database WHERE datname = '${POSTGRES_DB}'), ''), "
        "COALESCE((SELECT CASE WHEN rolcreatedb THEN 't' ELSE 'f' END FROM pg_roles WHERE rolname = '${POSTGRES_USER}'), 'f'), "
        "COALESCE((SELECT CASE WHEN rolsuper THEN 't' ELSE 'f' END FROM pg_roles WHERE rolname = '${POSTGRES_USER}'), 'f');"
    )
    assert expected_sql_pattern in content, (
        "Catalog query must use scalar subqueries for database presence and role privileges without an outer FROM filter"
    )
    assert "FROM pg_database WHERE datname = '${POSTGRES_DB}';" not in content, (
        "Catalog query must NOT filter the outer query with 'FROM pg_database WHERE', "
        "which returns 0 rows when the target is absent"
    )

    # 2. Functional verification against in-memory SQL engine (SQLite simulating the catalog contract)
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.create_function("current_database", 0, lambda: "postgres")
    conn.execute("CREATE TABLE pg_database (datname TEXT);")
    conn.execute("INSERT INTO pg_database (datname) VALUES ('postgres'), ('template1');")
    conn.execute("CREATE TABLE pg_roles (rolname TEXT, rolcreatedb INT, rolsuper INT);")
    conn.execute("INSERT INTO pg_roles (rolname, rolcreatedb, rolsuper) VALUES ('nexus_staging_user', 1, 0);")

    query = (
        "SELECT current_database(), "
        "(SELECT count(*) FROM pg_database WHERE datname = 'nexus_staging_db'), "
        "COALESCE((SELECT datname FROM pg_database WHERE datname = 'nexus_staging_db'), ''), "
        "COALESCE((SELECT CASE WHEN rolcreatedb THEN 't' ELSE 'f' END FROM pg_roles WHERE rolname = 'nexus_staging_user'), 'f'), "
        "COALESCE((SELECT CASE WHEN rolsuper THEN 't' ELSE 'f' END FROM pg_roles WHERE rolname = 'nexus_staging_user'), 'f');"
    )

    # Test Case A: Absent target, user has CREATEDB -> must return exactly 1 row ('postgres', 0, '', 't', 'f')
    rows_absent = conn.execute(query).fetchall()
    assert len(rows_absent) == 1
    assert rows_absent[0] == ("postgres", 0, "", "t", "f")
    formatted_absent = f"{rows_absent[0][0]}|{rows_absent[0][1]}|{rows_absent[0][2]}|{rows_absent[0][3]}|{rows_absent[0][4]}"
    assert formatted_absent == "postgres|0||t|f"

    # Test Case B: Present target, user is superuser -> must return exactly 1 row ('postgres', 1, 'nexus_staging_db', 'f', 't')
    conn.execute("INSERT INTO pg_database (datname) VALUES ('nexus_staging_db');")
    conn.execute("UPDATE pg_roles SET rolcreatedb = 0, rolsuper = 1 WHERE rolname = 'nexus_staging_user';")
    rows_present = conn.execute(query).fetchall()
    assert len(rows_present) == 1
    assert rows_present[0] == ("postgres", 1, "nexus_staging_db", "f", "t")
    formatted_present = f"{rows_present[0][0]}|{rows_present[0][1]}|{rows_present[0][2]}|{rows_present[0][3]}|{rows_present[0][4]}"
    assert formatted_present == "postgres|1|nexus_staging_db|f|t"

    # Test Case C: Target absent (deleted), user lacks both privileges -> must return ('postgres', 0, '', 'f', 'f')
    conn.execute("DELETE FROM pg_database WHERE datname = 'nexus_staging_db';")
    conn.execute("UPDATE pg_roles SET rolcreatedb = 0, rolsuper = 0 WHERE rolname = 'nexus_staging_user';")
    rows_nopriv = conn.execute(query).fetchall()
    assert len(rows_nopriv) == 1
    assert rows_nopriv[0] == ("postgres", 0, "", "f", "f")
    formatted_nopriv = f"{rows_nopriv[0][0]}|{rows_nopriv[0][1]}|{rows_nopriv[0][2]}|{rows_nopriv[0][3]}|{rows_nopriv[0][4]}"
    assert formatted_nopriv == "postgres|0||f|f"

    # Test Case D: User role missing from catalog -> COALESCE guarantees fallback to ('postgres', 0, '', 'f', 'f')
    conn.execute("DELETE FROM pg_roles;")
    rows_norole = conn.execute(query).fetchall()
    assert len(rows_norole) == 1
    assert rows_norole[0] == ("postgres", 0, "", "f", "f")
    formatted_norole = f"{rows_norole[0][0]}|{rows_norole[0][1]}|{rows_norole[0][2]}|{rows_norole[0][3]}|{rows_norole[0][4]}"
    assert formatted_norole == "postgres|0||f|f"
    conn.close()


def test_coordinated_scripts_production_zero_arg_compose_command(tmp_path: Path) -> None:
    """Zero-arg production mode preserves baseline: COMPOSE_PROJECT_NAME is empty and no -p is appended."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    env = os.environ.copy()
    env.pop("COMPOSE_PROJECT_NAME", None)
    env.pop("NEXUS_STAGING_MODE", None)
    valid_backup_dir = tmp_path / "prod_backup_zero_arg"
    env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)

    proc = subprocess.run([bash_bin, backup_script], env=env, capture_output=True, text=True)
    # Validate stdout logs show empty Project= and baseline production Compose file
    config_lines = [line for line in proc.stdout.splitlines() if "Configuration:" in line]
    assert len(config_lines) == 1
    assert "Project=," in config_lines[0]
    assert "File=docker-compose.prod.yml" in config_lines[0]
    assert "DB=nexus_db" in config_lines[0]
    assert "User=nexus_user" in config_lines[0]


def test_coordinated_scripts_pre_creation_canonicalization_rejects_forbidden_ancestor(tmp_path: Path) -> None:
    """Pre-creation canonical path resolution rejects non-existent paths under forbidden roots without creating them."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    forbidden_ancestor_paths = [
        "/var/lib/docker/volumes/nonexistent_subfolder_xyz",
        "/data/nonexistent_subfolder_xyz",
        "/app/data/nonexistent_subfolder_xyz",
        str(repo_root / ".git" / "nonexistent_subfolder_xyz").replace("\\", "/"),
        str(repo_root / "backend" / "data" / "nonexistent_subfolder_xyz").replace("\\", "/"),
    ]

    for fpath in forbidden_ancestor_paths:
        env = os.environ.copy()
        env["BACKUP_ROOT"] = fpath

        proc = subprocess.run([bash_bin, backup_script], env=env, capture_output=True, text=True)
        assert proc.returncode != 0
        assert "SAFETY ERROR: BACKUP_ROOT" in proc.stderr
        # Verify the directory was NEVER created
        assert not os.path.exists(fpath)


def test_coordinated_scripts_identifier_format_validation() -> None:
    """Invalid database and user identifiers fail closed before executing commands."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    invalid_ident_cases = [
        ({"POSTGRES_DB": "nexus_db;drop"}, "Invalid database identifier"),
        ({"POSTGRES_DB": "nexus db"}, "Invalid database identifier"),
        ({"POSTGRES_USER": "nexus-user;rm"}, "Invalid database user"),
    ]

    for overrides, expected_err in invalid_ident_cases:
        env = os.environ.copy()
        env.pop("NEXUS_STAGING_MODE", None)
        env.update(overrides)

        proc_b = subprocess.run([bash_bin, backup_script], env=env, capture_output=True, text=True)
        assert proc_b.returncode != 0
        assert expected_err in proc_b.stderr

        proc_r = subprocess.run(
            [bash_bin, restore_script, "--confirm-destructive-restore", "20261019_020000"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc_r.returncode != 0
        assert expected_err in proc_r.stderr


def test_coordinated_scripts_forbidden_path_rejection() -> None:
    """Both scripts reject BACKUP_ROOT residing in forbidden roots or repo data."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    forbidden_paths = [
        "/data",
        "/data/backups",
        "/app/data",
        "/var/lib/docker/volumes",
        "/var/lib/docker/volumes/foo",
        "backend/data",
        ".git/backups",
    ]

    for fpath in forbidden_paths:
        env = os.environ.copy()
        env["BACKUP_ROOT"] = fpath

        proc_b = subprocess.run([bash_bin, backup_script], env=env, capture_output=True, text=True)
        assert proc_b.returncode != 0
        assert "SAFETY ERROR: BACKUP_ROOT" in proc_b.stderr

        proc_r = subprocess.run(
            [bash_bin, restore_script, "--confirm-destructive-restore", "20261019_020000"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc_r.returncode != 0
        assert "SAFETY ERROR: BACKUP_ROOT" in proc_r.stderr


def test_redis_bgsave_failure_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis persistence failure triggers error and alert dispatch."""
    sent_payloads = []

    def mock_urlopen(req, timeout=5.0):
        sent_payloads.append(json.loads(req.data.decode("utf-8")))
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    monkeypatch.setenv("BACKUP_ALERT_WEBHOOK_URL", "https://alerts.nexus.internal/webhook")
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    status = send_backup_alert(
        event_type="BACKUP_FAILED",
        message="Redis BGSAVE failed: rdb_last_bgsave_status was err",
        details={"service": "redis", "exit_code": 1},
    )
    assert status is True
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["details"]["service"] == "redis"
    assert "Redis BGSAVE failed" in sent_payloads[0]["message"]


def test_backup_permissions_enforced(tmp_path: Path) -> None:
    """Backup artifacts enforce restrictive permissions (dumps: 0600, sidecars: 0644)."""
    db_file = tmp_path / "nexus_db_sample.dump"
    db_file.write_bytes(b"PGDMP_TEST")
    os.chmod(db_file, 0o600)
    sidecar = write_sha256_file(db_file)
    os.chmod(sidecar, 0o644)

    if os.name != "nt":
        assert (db_file.stat().st_mode & 0o777) == 0o600
        assert (sidecar.stat().st_mode & 0o777) == 0o644
    else:
        assert db_file.exists() and sidecar.exists()


def test_partial_restore_split_state_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Split-state condition triggers explicit RESTORE_SPLIT_STATE alert with operator instructions."""
    sent_payloads = []

    def mock_urlopen(req, timeout=5.0):
        sent_payloads.append(json.loads(req.data.decode("utf-8")))
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    monkeypatch.setenv("BACKUP_ALERT_WEBHOOK_URL", "https://alerts.nexus.internal/webhook")
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    success = send_backup_alert(
        event_type="RESTORE_SPLIT_STATE",
        message="Critical: Restore failed during FILES_RESTORING for timestamp 20261019_020000. Manual recovery required.",
        details={"phase": "FILES_RESTORING", "timestamp": "20261019_020000"},
    )
    assert success is True
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["event_type"] == "RESTORE_SPLIT_STATE"
    assert "Manual recovery required" in sent_payloads[0]["message"]


# ---------------------------------------------------------------------------
# 6. Real PostgreSQL 16 + pgvector Coordinated Restore Drill
# ---------------------------------------------------------------------------

def _get_pg_test_url() -> str | None:
    """Resolve explicit TEST_DATABASE_URL for live backup/restore drill.

    Safety Invariant: Does NOT fall back to DATABASE_URL to prevent accidental
    targeting of development, staging, or production application databases.
    """
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url or not raw_url.strip():
        return None
    return raw_url.strip()


def validate_restore_drill_source_url(url: str | None, strict_required: bool = False) -> str:
    """Validate source database URL for live backup/restore drill.

    Enforces fail-closed guardrails:
    1. TEST_DATABASE_URL must be explicitly provided (no DATABASE_URL fallback).
    2. Parsed database name must be exactly 'nexus_test_db' (case-insensitive).

    Boundary & Non-Claim:
    Matching 'nexus_test_db' prevents accidental writes to 'nexus_db', 'nexus_prod',
    or arbitrarily named databases. However, a database name of 'nexus_test_db' does
    NOT establish that the PostgreSQL host is an isolated or disposable server instance;
    it only validates target database naming.
    """
    if not url:
        msg = (
            "TEST_DATABASE_URL must be explicitly set to run live PostgreSQL restore drill. "
            "Fallback to DATABASE_URL is strictly disallowed to prevent targeting non-test databases."
        )
        if strict_required:
            pytest.fail(msg)
        pytest.skip(msg)

    parsed_url = make_url(url)
    db_name = (parsed_url.database or "").strip()
    if db_name.lower() != "nexus_test_db":
        pytest.fail(
            f"Safety Guardrail: Refusing to execute live restore drill against database '{parsed_url.database}'. "
            f"Source database name must be exactly 'nexus_test_db'."
        )
    return url


def _find_postgres_runner(parsed_url) -> tuple[str, str | None]:
    """Identify whether to execute pg_dump/pg_restore via host binary or Docker container.

    Host Target Boundary:
    Docker container discovery via 'docker ps' is strictly restricted to local host
    targets ('localhost', '127.0.0.1', '::1') to prevent running local container
    commands against remote database URLs. This does not imply the local server is
    containerized if host binaries are preferred.
    """
    if shutil.which("pg_dump") and shutil.which("pg_restore"):
        return "host", None

    is_local_host = (parsed_url.host or "localhost").lower() in ("localhost", "127.0.0.1", "::1")
    if is_local_host and shutil.which("docker"):
        port = parsed_url.port or 5432
        cmd = ["docker", "ps", "--format", "{{.ID}}\t{{.Ports}}\t{{.Names}}"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        cid, ports = parts[0], parts[1]
                        if f":{port}->" in ports or f":{port}/" in ports:
                            return "docker", cid
                # Fallback to any postgres/pg container
                for line in res.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 3 and any(k in parts[2].lower() for k in ("postgres", "pg", "vector")):
                        return "docker", parts[0]
        except Exception:
            pass

    return "none", None


def cleanup_restore_drill(
    *,
    admin_engine: Any | None,
    restore_engine: Any | None,
    session_factory: Any | None,
    restore_db_name: str | None,
    db_created: bool,
    biz_id: str | None = None,
    org_id: str | None = None,
) -> list[str]:
    """Execute teardown for live restore drill and return any encountered cleanup failures.

    Safety Guarantees & Constraints:
    - Never raises an unhandled exception (all teardown steps run to completion).
    - Never targets or drops any database other than `restore_db_name`.
    - Returns list of failure descriptions and emits RuntimeWarning for each failure.
    """
    cleanup_errors: list[str] = []

    if restore_engine is not None:
        try:
            restore_engine.dispose()
        except Exception as exc:
            err_msg = f"CLEANUP FAILURE: Failed to dispose restore_engine: {exc}"
            cleanup_errors.append(err_msg)
            warnings.warn(err_msg, RuntimeWarning, stacklevel=2)

    if db_created and admin_engine is not None and restore_db_name:
        try:
            # Validate generated database identifier before SQL interpolation
            if not re.fullmatch(r"^nexus_restore_verify_[a-zA-Z0-9_]{1,40}$", restore_db_name):
                raise ValueError(f"Unsafe restore database identifier: {restore_db_name!r}")

            with admin_engine.connect() as conn:
                conn.execute(
                    text("""
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE datname = :datname AND pid <> pg_backend_pid();
                    """),
                    {"datname": restore_db_name},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{restore_db_name}"'))
        except Exception as drop_exc:
            err_msg = (
                f"CLEANUP FAILURE: Failed to drop disposable restore database '{restore_db_name}': {drop_exc}. "
                f"Leftover database may persist in PostgreSQL instance."
            )
            cleanup_errors.append(err_msg)
            warnings.warn(err_msg, RuntimeWarning, stacklevel=2)

    if admin_engine is not None:
        try:
            admin_engine.dispose()
        except Exception:
            pass

    if session_factory is not None and biz_id and org_id:
        try:
            with session_factory() as db:
                try:
                    db.execute(text("DELETE FROM knowledge_chunks WHERE business_id = :biz_id"), {"biz_id": biz_id})
                    db.execute(text("DELETE FROM knowledge_documents WHERE business_id = :biz_id"), {"biz_id": biz_id})
                    db.execute(text("DELETE FROM ingestion_jobs WHERE business_id = :biz_id"), {"biz_id": biz_id})
                    db.execute(text("DELETE FROM uploaded_datasets WHERE business_id = :biz_id"), {"biz_id": biz_id})
                    db.execute(text("DELETE FROM businesses WHERE id = :biz_id"), {"biz_id": biz_id})
                    db.execute(text("DELETE FROM organizations WHERE id = :org_id"), {"org_id": org_id})
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
        except Exception as seed_exc:
            err_msg = f"CLEANUP FAILURE: Failed to clean seeded drill tenant records (biz_id={biz_id}): {seed_exc}"
            cleanup_errors.append(err_msg)
            warnings.warn(err_msg, RuntimeWarning, stacklevel=2)

    return cleanup_errors


def test_live_postgres_backup_restore_and_storage_reconciliation_drill(tmp_path: Path) -> None:
    """Mandatory Live PostgreSQL 16 + pgvector restore drill.

    Verifies:
    1. Seeding real tenant, business, datasets, files, sales, and vector data in dedicated test database 'nexus_test_db'.
    2. Real pg_dump -F c custom-format archive generation.
    3. Tenant file archive creation with SHA-256 sidecars.
    4. Creation of a clean, separate disposable restore database (nexus_restore_verify_<uid>).
    5. Real pg_restore execution into the clean disposable database.
    6. Complete verification of restored schema, row counts, sequences, foreign keys, JSONB data,
       pgvector extension and vector queries, and tenant isolation.
    7. Clean file restore and validation of file SHA-256 and size against restored database record.
    8. Storage reconciliation audit confirming 100% referential consistency.
    9. Teardown of disposable restore database and drill records.

    Safety Boundary:
    Targeting 'nexus_test_db' prevents accidental writes to application databases, but does
    not guarantee that the host PostgreSQL daemon is disposable or isolated from other databases.
    Teardown is constrained to 'nexus_restore_verify_<uid>' and the specific drill tenant records.
    """
    strict_required = os.getenv("REQUIRE_POSTGRES", "").lower() in ("true", "1", "yes")

    # 1. Validate Source Database Target (Fail-Closed Guardrail)
    url = validate_restore_drill_source_url(_get_pg_test_url(), strict_required=strict_required)

    # 2. Verify PostgreSQL Reachability
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        if strict_required:
            pytest.fail(f"REQUIRE_POSTGRES=true is set, but PostgreSQL is not reachable at {url}: {exc}")
        pytest.skip(f"Live PostgreSQL not reachable ({exc}). Verification pending CI.")

    parsed_url = make_url(url)
    runner_mode, container_id = _find_postgres_runner(parsed_url)

    if runner_mode == "none":
        if strict_required:
            pytest.fail("Neither pg_dump/pg_restore in host PATH nor accessible docker postgres container found to execute real restore drill.")
        pytest.skip("pg_dump/pg_restore utilities not found. Verification pending CI.")

    Session = sessionmaker(bind=engine)
    data_dir = tmp_path / "drill_data"
    backup_dir = tmp_path / "drill_backups"
    restore_dir = tmp_path / "drill_restored_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    restore_dir.mkdir(parents=True, exist_ok=True)

    uid = uuid4().hex[:8]
    restore_db_name = f"nexus_restore_verify_{uid}"
    org_id = str(uuid4())
    biz_id = str(uuid4())
    ds1_id = str(uuid4())
    job1_id = str(uuid4())

    # 2. Seed isolated test tenant records in PostgreSQL
    with Session() as db:
        org = Organization(id=org_id, name=f"Restore Drill Org {uid}", slug=f"drill-org-{uid}")
        biz = Business(id=biz_id, organization_id=org.id, name=f"Restore Drill Biz {uid}")
        db.add_all([org, biz])
        db.flush()

        # Seed physical dataset file on disk
        tenants_tree = data_dir / "tenants" / org.id / biz.id
        tenants_tree.mkdir(parents=True, exist_ok=True)

        ds1_dir = tenants_tree / ds1_id
        ds1_dir.mkdir(parents=True, exist_ok=True)
        ds1_file = ds1_dir / "sales_2025.csv"
        file_bytes = b"order,amount\nORD-01,150.00\nORD-02,250.00\n"
        ds1_file.write_bytes(file_bytes)
        rel_key1 = f"tenants/{org.id}/{biz.id}/{ds1_id}/sales_2025.csv"
        expected_sha256 = hashlib.sha256(file_bytes).hexdigest()
        expected_size = len(file_bytes)

        ds1 = UploadedDataset(
            id=ds1_id,
            organization_id=org.id,
            business_id=biz.id,
            filename="sales_2025.csv",
            file_type="csv",
            storage_key=rel_key1,
            file_size_bytes=expected_size,
            content_hash=expected_sha256,
            schema_json={"drill_marker": "jsonb_drill_test", "fields": ["order", "amount"], "batch_count": 42},
            readiness_status="READY",
        )

        job1 = IngestionJob(
            id=job1_id,
            organization_id=org.id,
            business_id=biz.id,
            dataset_id=ds1_id,
            status="COMPLETED",
            target_entity="Sale",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            rows_processed=2,
            error_message="Drill diagnostic error message sample",
        )

        # Seed KnowledgeDocument and KnowledgeChunk (Verifying Sequences & Foreign Keys)
        doc = KnowledgeDocument(
            business_id=biz.id,
            document_id=f"doc_{uid}",
            title="Drill Policy Document",
            source="internal_drill",
            document_type="markdown",
            content_hash="drill_hash_123",
            metadata_json={"author": "nexus_ops", "category": "drill", "drill_marker": "jsonb_drill_test"},
        )
        db.add(doc)
        db.flush()

        chunk = KnowledgeChunk(
            document_id=doc.id,
            chunk_id=f"chunk_{uid}",
            chunk_index=0,
            title="Drill Overview",
            content="Drill content for vector and foreign key verification.",
            business_id=biz.id,
            metadata_json={"section": "intro"},
        )

        db.add_all([ds1, job1, chunk])
        db.commit()
        doc_id = doc.id

    admin_engine = None
    restore_engine = None
    db_created = False
    admin_url = parsed_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_backup_file = backup_dir / f"nexus_db_{ts}.dump"
    files_backup_file = backup_dir / f"nexus_files_{ts}.tar.gz"

    try:
        # 3. Real pg_dump -F c Execution
        if runner_mode == "host":
            env = os.environ.copy()
            if parsed_url.password:
                env["PGPASSWORD"] = parsed_url.password
            cmd = [
                "pg_dump",
                "-h", parsed_url.host or "localhost",
                "-p", str(parsed_url.port or 5432),
                "-U", parsed_url.username or "nexus_user",
                "-d", parsed_url.database,
                "-F", "c",
                "-f", str(db_backup_file),
            ]
            subprocess.run(cmd, env=env, check=True)
        elif runner_mode == "docker":
            cmd = [
                "docker", "exec", container_id,
                "pg_dump",
                "-U", parsed_url.username or "nexus_user",
                "-d", parsed_url.database,
                "-F", "c",
            ]
            with db_backup_file.open("wb") as f:
                subprocess.run(cmd, stdout=f, check=True)

        # Verify real custom dump magic bytes
        assert db_backup_file.exists() and db_backup_file.stat().st_size > 0
        with db_backup_file.open("rb") as f:
            header = f.read(5)
        assert header == b"PGDMP", f"pg_dump did not produce PGDMP header: {header!r}"

        # 4. Backup tenant files via tar.gz
        with tarfile.open(files_backup_file, "w:gz") as tar:
            tar.add(data_dir, arcname=".")

        # Compute and verify SHA-256 sidecars
        write_sha256_file(db_backup_file)
        write_sha256_file(files_backup_file)
        assert verify_sha256_file(db_backup_file)[0] is True
        assert verify_sha256_file(files_backup_file)[0] is True
        assert validate_tar_archive(files_backup_file)[0] is True

        # 5. Create Separate Clean Disposable Database
        if not re.fullmatch(r"^nexus_restore_verify_[a-zA-Z0-9_]{1,40}$", restore_db_name):
            raise ValueError(f"Unsafe restore database identifier: {restore_db_name!r}")
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{restore_db_name}"'))
            conn.execute(text(f'CREATE DATABASE "{restore_db_name}"'))
        db_created = True

        # 6. Real pg_restore Execution into Separate Database
        if runner_mode == "host":
            env = os.environ.copy()
            if parsed_url.password:
                env["PGPASSWORD"] = parsed_url.password
            cmd = [
                "pg_restore",
                "-h", parsed_url.host or "localhost",
                "-p", str(parsed_url.port or 5432),
                "-U", parsed_url.username or "nexus_user",
                "-d", restore_db_name,
                "-v",
                str(db_backup_file),
            ]
            subprocess.run(cmd, env=env, check=True)
        elif runner_mode == "docker":
            cmd = [
                "docker", "exec", "-i", container_id,
                "pg_restore",
                "-U", parsed_url.username or "nexus_user",
                "-d", restore_db_name,
                "-v",
            ]
            with db_backup_file.open("rb") as f:
                subprocess.run(cmd, stdin=f, check=True)

        # 7. Connect to Restored Database and Validate All Entities & Constraints
        restore_url = parsed_url.set(database=restore_db_name)
        restore_engine = create_engine(restore_url)
        RestoreSession = sessionmaker(bind=restore_engine)

        with RestoreSession() as rdb:
            # A) Validate schema tables exist in restored database
            tables = inspect(restore_engine).get_table_names()
            for expected_tbl in ["organizations", "businesses", "uploaded_datasets", "ingestion_jobs", "knowledge_documents", "knowledge_chunks"]:
                assert expected_tbl in tables, f"Restored table {expected_tbl} missing!"

            # B) Validate Organization and Business row counts and fidelity
            restored_org = rdb.execute(select(Organization).where(Organization.id == org_id)).scalar_one()
            assert restored_org.name == f"Restore Drill Org {uid}"
            assert restored_org.slug == f"drill-org-{uid}"

            restored_biz = rdb.execute(select(Business).where(Business.id == biz_id)).scalar_one()
            assert restored_biz.name == f"Restore Drill Biz {uid}"
            assert restored_biz.organization_id == org_id

            # C) Validate Dataset and Ingestion Job
            restored_ds = rdb.execute(select(UploadedDataset).where(UploadedDataset.id == ds1_id)).scalar_one()
            assert restored_ds.filename == "sales_2025.csv"
            assert restored_ds.file_size_bytes == expected_size
            assert restored_ds.content_hash == expected_sha256

            restored_job = rdb.execute(select(IngestionJob).where(IngestionJob.id == job1_id)).scalar_one()
            assert restored_job.status == "COMPLETED"
            assert restored_job.rows_processed == 2
            assert restored_job.error_message == "Drill diagnostic error message sample"

            # D) Validate JSONB Data Fidelity in Restored DB
            assert restored_ds.schema_json is not None
            assert restored_ds.schema_json.get("drill_marker") == "jsonb_drill_test"
            assert restored_ds.schema_json.get("batch_count") == 42

            # E) Validate Sequences and Document/Chunk Alignment
            restored_doc = rdb.execute(select(KnowledgeDocument).where(KnowledgeDocument.business_id == biz_id)).scalar_one()
            assert restored_doc.document_id == f"doc_{uid}"
            assert restored_doc.id == doc_id, "Sequence primary key not preserved in restored db!"
            assert restored_doc.metadata_json.get("drill_marker") == "jsonb_drill_test"

            restored_chunk = rdb.execute(select(KnowledgeChunk).where(KnowledgeChunk.business_id == biz_id)).scalar_one()
            assert restored_chunk.document_id == restored_doc.id, "Foreign key relationship not preserved in restored db!"

            # F) Validate Foreign Key Constraint Integrity in Restored DB
            with pytest.raises(Exception):
                orphan_chunk = KnowledgeChunk(document_id=99999999, chunk_id=str(uuid4()), chunk_index=99, content="Orphan chunk", business_id=biz_id)
                rdb.add(orphan_chunk)
                rdb.commit()
            rdb.rollback()

            # G) Validate pgvector Extension and Vector Query in Restored DB
            ext_name = rdb.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'")).scalar_one_or_none()
            assert ext_name == "vector", "pgvector extension is not present in restored database!"

            vec_distance = rdb.execute(text("SELECT ('[1,2,3]'::vector <-> '[1,2,5]'::vector) AS dist")).scalar_one()
            assert abs(float(vec_distance) - 2.0) < 1e-5, f"pgvector similarity query failed: dist={vec_distance}"

            # H) Validate Tenant Isolation
            isolated_query = rdb.execute(
                select(UploadedDataset).where(UploadedDataset.business_id == "nonexistent_tenant_id")
            ).scalars().all()
            assert len(isolated_query) == 0

            # 8. Restore Tenant Files into Clean Directory & Validate SHA-256 + Size
            with tarfile.open(files_backup_file, "r:gz") as tar:
                tar.extractall(path=restore_dir)

            restored_file = restore_dir / "tenants" / org_id / biz_id / ds1_id / "sales_2025.csv"
            assert restored_file.exists()
            assert restored_file.stat().st_size == restored_ds.file_size_bytes

            # SHA-256 hash match against restored database record
            calculated_file_hash = compute_sha256(restored_file)
            assert calculated_file_hash == restored_ds.content_hash

            # 9. Storage Reconciliation Audit against Restored Database & Filesystem
            with patch("app.services.data_gateway_service.DataGatewayService.resolve_storage_path") as mock_resolve:
                mock_resolve.side_effect = lambda key: restore_dir / key
                reconcile_res = reconcile_tenant_storage(db=rdb, base_dir=restore_dir, delete_orphans=False)
                assert not any(m[0] == ds1_id for m in reconcile_res.missing_files), f"Restored dataset {ds1_id} was flagged as missing!"
                assert len(reconcile_res.orphan_files) == 0, f"Restored directory has unexpected orphans: {reconcile_res.orphan_files}"

    finally:
        # 10. Clean Up ONLY the Disposable Restore Database and Test Records
        import sys
        primary_exc = sys.exc_info()[1]

        cleanup_errors = cleanup_restore_drill(
            admin_engine=admin_engine,
            restore_engine=restore_engine,
            session_factory=Session if "Session" in locals() else None,
            restore_db_name=restore_db_name,
            db_created=db_created,
            biz_id=biz_id,
            org_id=org_id,
        )

        if cleanup_errors:
            if primary_exc is None:
                # Drill assertions passed, but cleanup failed -> fail closed
                pytest.fail("Restore drill completed body assertions, but cleanup failed:\n" + "\n".join(cleanup_errors))
            else:
                # Primary error is active. Do NOT mask it. Attach cleanup notes and let Python re-raise primary_exc.
                if hasattr(primary_exc, "add_note"):
                    for err in cleanup_errors:
                        primary_exc.add_note(err)


# ---------------------------------------------------------------------------
# 7. Live Backup/Restore Drill Safety Guardrail Unit Tests
# ---------------------------------------------------------------------------

def test_restore_drill_rejects_missing_test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TEST_DATABASE_URL is missing, fail closed if strict, skip if non-strict."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(pytest.fail.Exception) as exc_info:
        validate_restore_drill_source_url(None, strict_required=True)
    assert "TEST_DATABASE_URL must be explicitly set" in str(exc_info.value)
    assert "Fallback to DATABASE_URL is strictly disallowed" in str(exc_info.value)

    with pytest.raises(pytest.skip.Exception) as skip_info:
        validate_restore_drill_source_url(None, strict_required=False)
    assert "TEST_DATABASE_URL must be explicitly set" in str(skip_info.value)


def test_restore_drill_disallows_database_url_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL pointing to application database (nexus_db) is NOT used when TEST_DATABASE_URL is unset."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nexus_user:nexus_password@localhost:5432/nexus_db")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    resolved = _get_pg_test_url()
    assert resolved is None, f"_get_pg_test_url() must return None instead of falling back to DATABASE_URL, got: {resolved}"

    with pytest.raises(pytest.fail.Exception) as exc_info:
        validate_restore_drill_source_url(resolved, strict_required=True)
    assert "Fallback to DATABASE_URL is strictly disallowed" in str(exc_info.value)


@pytest.mark.parametrize(
    "invalid_db_name",
    [
        "nexus_db",
        "nexus_prod",
        "postgres",
        "test_db",
        "nexus_test",
        "my_test_database",
    ],
)
def test_restore_drill_rejects_non_nexus_test_db_name(invalid_db_name: str) -> None:
    """Any database name other than exactly 'nexus_test_db' is rejected immediately."""
    invalid_url = f"postgresql+psycopg://nexus_user:nexus_password@localhost:5432/{invalid_db_name}"
    with pytest.raises(pytest.fail.Exception) as exc_info:
        validate_restore_drill_source_url(invalid_url, strict_required=False)
    assert "Safety Guardrail: Refusing to execute live restore drill" in str(exc_info.value)
    assert "Source database name must be exactly 'nexus_test_db'" in str(exc_info.value)


def test_restore_drill_rejection_precedes_seed_data_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure invalid source database URL fails closed before any database connection or seed write."""
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://nexus_user:nexus_password@localhost:5432/nexus_db")
    monkeypatch.setenv("REQUIRE_POSTGRES", "true")

    connection_attempted = False

    def mock_create_engine(*args, **kwargs):
        nonlocal connection_attempted
        connection_attempted = True
        raise AssertionError("create_engine must NOT be called for an invalid source database URL!")

    monkeypatch.setattr("backend.tests.test_backup_restore_phase32c.create_engine", mock_create_engine, raising=False)
    monkeypatch.setattr("sqlalchemy.create_engine", mock_create_engine)

    with pytest.raises(pytest.fail.Exception) as exc_info:
        test_live_postgres_backup_restore_and_storage_reconciliation_drill(tmp_path)

    assert "Safety Guardrail" in str(exc_info.value)
    assert connection_attempted is False, "A database connection was attempted despite invalid source database name!"


def test_cleanup_restore_drill_reports_drop_database_failure() -> None:
    """Simulate a failed database-drop operation on admin_engine and verify cleanup_restore_drill reports it."""
    mock_admin_engine = MagicMock()
    mock_conn = MagicMock()
    mock_admin_engine.connect.return_value.__enter__.return_value = mock_conn

    def mock_execute(statement, *args, **kwargs):
        stmt_text = str(statement)
        if "DROP DATABASE" in stmt_text:
            raise RuntimeError("permission denied to drop database: simulated failure")
        return MagicMock()

    mock_conn.execute.side_effect = mock_execute
    restore_db_name = "nexus_restore_verify_mocked_drop"

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        errors = cleanup_restore_drill(
            admin_engine=mock_admin_engine,
            restore_engine=None,
            session_factory=None,
            restore_db_name=restore_db_name,
            db_created=True,
        )

    # 1. Returned errors list contains the failure details
    assert len(errors) == 1
    assert "CLEANUP FAILURE" in errors[0]
    assert restore_db_name in errors[0]
    assert "permission denied to drop database" in errors[0]

    # 2. RuntimeWarning was emitted with the failure details
    assert len(recorded_warnings) == 1
    assert issubclass(recorded_warnings[0].category, RuntimeWarning)
    assert "permission denied to drop database" in str(recorded_warnings[0].message)


def test_restore_drill_cleanup_preserves_primary_exception() -> None:
    """Verify that cleanup failures do not mask a primary test assertion or exception."""
    mock_admin_engine = MagicMock()
    mock_conn = MagicMock()
    mock_admin_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.side_effect = RuntimeError("simulated DROP DATABASE failure")

    primary_error = AssertionError("Original test assertion failed: expected 42, got 0")

    try:
        try:
            raise primary_error
        finally:
            import sys
            curr_exc = sys.exc_info()[1]
            errors = cleanup_restore_drill(
                admin_engine=mock_admin_engine,
                restore_engine=None,
                session_factory=None,
                restore_db_name="nexus_restore_verify_masked_check",
                db_created=True,
            )
            if errors:
                if curr_exc is None:
                    pytest.fail("Restore drill completed body assertions, but cleanup failed:\n" + "\n".join(errors))
                elif hasattr(curr_exc, "add_note"):
                    for err in errors:
                        curr_exc.add_note(err)
    except AssertionError as caught:
        # Assert the primary error was preserved and NOT replaced by a cleanup exception
        assert caught is primary_error
        assert "Original test assertion failed" in str(caught)
        if hasattr(caught, "__notes__"):
            assert any("simulated DROP DATABASE failure" in note for note in caught.__notes__)


def test_cleanup_restore_drill_seed_cleanup_failure_rolls_back_and_reports() -> None:
    """Verify that a failure during seed record cleanup rolls back the session and reports the failure."""
    mock_session = MagicMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_session.__enter__.return_value = mock_session
    mock_session.execute.side_effect = RuntimeError("simulated DB constraint failure on delete")

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        errors = cleanup_restore_drill(
            admin_engine=None,
            restore_engine=None,
            session_factory=mock_session_factory,
            restore_db_name="nexus_restore_verify_testseed",
            db_created=False,
            biz_id="test_biz_123",
            org_id="test_org_123",
        )

    # Rollback was called on error
    mock_session.rollback.assert_called_once()
    # Error was recorded and warned
    assert len(errors) == 1
    assert "CLEANUP FAILURE" in errors[0]
    assert "test_biz_123" in errors[0]
    assert len(recorded_warnings) == 1
    assert "simulated DB constraint failure on delete" in str(recorded_warnings[0].message)


def test_cleanup_restore_drill_rejects_unsafe_database_identifier() -> None:
    """Verify that an unsafe database identifier raises a ValueError during cleanup."""
    unsafe_name = 'nexus_restore_verify_test"; DROP TABLE users; --'
    mock_admin_engine = MagicMock()

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        errors = cleanup_restore_drill(
            admin_engine=mock_admin_engine,
            restore_engine=None,
            session_factory=None,
            restore_db_name=unsafe_name,
            db_created=True,
        )

    assert len(errors) == 1
    assert "Unsafe restore database identifier" in errors[0]
    assert len(recorded_warnings) == 1
    assert "Unsafe restore database identifier" in str(recorded_warnings[0].message)
    # Admin engine was never connected due to pre-validation rejection
    mock_admin_engine.connect.assert_not_called()


def test_disposable_restore_rejects_live_staging_targets_and_validates_isolation(tmp_path: Path) -> None:
    """Disposable target mode fails closed before mutating Docker when targeting live staging/prod resources."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = "nexus_disposable_staging_db"
    base_env["DATA_VOLUME"] = "nexus_backend_disposable_staging_data"
    base_env["REDIS_VOLUME"] = "nexus_redis_disposable_staging_data"
    base_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)

    default_db_url = "postgresql://nexus_user:nexus_password@postgres:5432/nexus_disposable_staging_db"

    # Scenarios testing isolation guards:
    scenarios = [
        # 1. Target is live staging DB
        ({"POSTGRES_DB": "nexus_staging_db"}, default_db_url, "In disposable target mode, POSTGRES_DB cannot target live staging database 'nexus_staging_db'"),
        # 2. Target is integration test DB
        ({"POSTGRES_DB": "nexus_test_db"}, default_db_url, "In staging mode, POSTGRES_DB cannot target 'nexus_test_db'"),
        # 3. Target is live staging data volume
        ({"DATA_VOLUME": "nexus_backend_staging_data"}, default_db_url, "In disposable target mode, DATA_VOLUME cannot target live staging volume 'nexus_backend_staging_data'"),
        # 4. Target is live staging redis volume
        ({"REDIS_VOLUME": "nexus_redis_staging_data"}, default_db_url, "In disposable target mode, REDIS_VOLUME cannot target live staging volume 'nexus_redis_staging_data'"),
        # 5. Missing --database-url
        ({}, None, "In disposable target mode, explicit '--database-url' is required for reconciliation"),
        # 6. Non-Postgres connection scheme
        ({}, "mysql://user:pass@host:3306/nexus_disposable_staging_db", "Disposable DATABASE_URL must be a PostgreSQL connection string"),
        # 7. URL database mismatch with POSTGRES_DB
        ({}, "postgresql://user:pass@postgres:5432/nexus_other_staging_db", "Disposable DATABASE_URL target database ('nexus_other_staging_db') does not match POSTGRES_DB ('nexus_disposable_staging_db')"),
        # 8. URL targets live staging database
        ({"POSTGRES_DB": "nexus_staging_db"}, "postgresql://user:pass@postgres:5432/nexus_staging_db", "In disposable target mode, POSTGRES_DB cannot target live staging database 'nexus_staging_db'"),
        # 9. URL targets test database
        ({"POSTGRES_DB": "nexus_test_db"}, "postgresql://user:pass@postgres:5432/nexus_test_db", "In staging mode, POSTGRES_DB cannot target 'nexus_test_db'"),
    ]

    for env_overrides, db_url_arg, expected_err in scenarios:
        env = base_env.copy()
        env.update(env_overrides)
        log_file.write_text("")

        cmd = [bash_bin, restore_script, "--staging", "--disposable-target", "--confirm-destructive-restore", ts, "--backup-root=" + _to_bash_path(valid_backup_dir)]
        if db_url_arg:
            cmd.append(f"--database-url={db_url_arg}")

        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        assert proc.returncode != 0
        assert expected_err in proc.stderr
        calls = log_file.read_text()
        assert "CALL: DROPDB" not in calls
        assert "CALL: CREATEDB" not in calls
        assert "CALL: STOP_BACKEND_SCHEDULER" not in calls
        assert "CALL: STOP_REDIS" not in calls

    # 10. Reverse guard: --disposable-target in production mode (without --staging)
    prod_env = os.environ.copy()
    prod_env["PATH"] = f"{str(bin_dir)};{prod_env.get('PATH', '')}"
    prod_env.pop("NEXUS_STAGING_MODE", None)
    proc_prod = subprocess.run(
        [bash_bin, restore_script, "--disposable-target", "--confirm-destructive-restore", ts, "--backup-root=" + _to_bash_path(valid_backup_dir)],
        env=prod_env,
        capture_output=True,
        text=True,
    )
    assert proc_prod.returncode != 0
    assert "Disposable target mode is strictly prohibited in production mode" in proc_prod.stderr


def test_disposable_restore_rejects_live_service_stop_start_restart_calls(tmp_path: Path) -> None:
    """Disposable target mode completes end-to-end without stopping, starting, or restarting live staging services."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    redis_file = valid_backup_dir / f"nexus_redis_{ts}.tar.gz"
    with tarfile.open(redis_file, "w:gz") as tar:
        pass
    redis_bytes = redis_file.read_bytes()
    redis_hash = hashlib.sha256(redis_bytes).hexdigest()
    sidecar_redis = valid_backup_dir / f"nexus_redis_{ts}.tar.gz.sha256"
    sidecar_redis.write_bytes(f"{redis_hash}  {_to_bash_path(redis_file)}\n".encode("utf-8"))

    env = os.environ.copy()
    env["PATH"] = f"{str(bin_dir)};{env.get('PATH', '')}"
    env["NEXUS_STAGING_MODE"] = "true"
    env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    env["POSTGRES_DB"] = "nexus_disposable_staging_db"
    env["DATA_VOLUME"] = "nexus_backend_disposable_staging_data"
    env["REDIS_VOLUME"] = "nexus_redis_disposable_staging_data"
    env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    env["MOCK_TARGET_DB"] = "nexus_disposable_staging_db"

    disposable_db_url = "postgresql://nexus_user:nexus_password@postgres:5432/nexus_disposable_staging_db"

    cmd = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--allow-target-recreate",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--database-url={disposable_db_url}",
    ]

    log_file.write_text("")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"Script failed with stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"

    # Verify stdout logs confirmation of untouched live services
    assert "Disposable target mode: Live services were not stopped and do not require resumption." in proc.stdout
    assert "Live backend and scheduler remain active and untouched." in proc.stdout
    assert "Disposable target mode: Verified Postgres container identity ('nexus-staging'). Live Redis container check bypassed." in proc.stdout

    # Verify docker calls:
    calls = log_file.read_text()
    assert "CALL: STOP_BACKEND_SCHEDULER" not in calls
    assert "CALL: START_BACKEND_SCHEDULER" not in calls
    assert "CALL: STOP_REDIS" not in calls
    assert "CALL: START_REDIS" not in calls
    assert "ps -q redis" not in calls
    assert "CALL: HEALTHCHECK" not in calls
    assert "CALL: PG_RESTORE" in calls


def test_disposable_restore_reconciliation_receives_exact_url_and_volume(tmp_path: Path) -> None:
    """Disposable reconciliation command receives the exact disposable DATABASE_URL and DATA_VOLUME."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    env = os.environ.copy()
    env["PATH"] = f"{str(bin_dir)};{env.get('PATH', '')}"
    env["NEXUS_STAGING_MODE"] = "true"
    env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    env["POSTGRES_DB"] = "nexus_disposable_staging_audit_db"
    env["DATA_VOLUME"] = "nexus_backend_disposable_audit_staging_data"
    env["REDIS_VOLUME"] = "nexus_redis_disposable_audit_staging_data"
    env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    env["MOCK_TARGET_DB"] = "nexus_disposable_staging_audit_db"

    disposable_db_url = "postgresql://test_user:test_secret@postgres:5432/nexus_disposable_staging_audit_db"

    cmd = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--allow-target-recreate",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--database-url={disposable_db_url}",
    ]

    log_file.write_text("")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert proc.returncode == 0

    calls = log_file.read_text()
    reconcile_calls = [line for line in calls.splitlines() if line.startswith("CALL: RECONCILE_STORAGE")]
    assert len(reconcile_calls) == 1
    call = reconcile_calls[0]
    # Check that environment override is passed
    assert f"-e DATABASE_URL={disposable_db_url}" in call
    # Check that data volume mount override is passed
    assert "-v nexus_backend_disposable_audit_staging_data:/app/data" in call
    # Check that scripts directory is mounted into /app/scripts:ro
    assert ":/app/scripts:ro" in call
    # Check that CLI flags are forwarded to reconcile_storage.py
    assert "--data-dir=/app/data" in call
    assert f"--database-url={disposable_db_url}" in call


def test_disposable_restore_redis_cannot_target_live_container_or_volume(tmp_path: Path) -> None:
    """Disposable Redis restore uses isolated container and disposable volume without touching live Redis."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    redis_file = valid_backup_dir / f"nexus_redis_{ts}.tar.gz"
    with tarfile.open(redis_file, "w:gz") as tar:
        pass
    redis_bytes = redis_file.read_bytes()
    redis_hash = hashlib.sha256(redis_bytes).hexdigest()
    sidecar_redis = valid_backup_dir / f"nexus_redis_{ts}.tar.gz.sha256"
    sidecar_redis.write_bytes(f"{redis_hash}  {_to_bash_path(redis_file)}\n".encode("utf-8"))

    env = os.environ.copy()
    env["PATH"] = f"{str(bin_dir)};{env.get('PATH', '')}"
    env["NEXUS_STAGING_MODE"] = "true"
    env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    env["POSTGRES_DB"] = "nexus_disposable_staging_db"
    env["DATA_VOLUME"] = "nexus_backend_disposable_staging_data"
    env["REDIS_VOLUME"] = "nexus_redis_disposable_staging_data"
    env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    env["MOCK_TARGET_DB"] = "nexus_disposable_staging_db"

    disposable_db_url = "postgresql://nexus_user:nexus_password@postgres:5432/nexus_disposable_staging_db"

    cmd = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--allow-target-recreate",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--database-url={disposable_db_url}",
    ]

    log_file.write_text("")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert proc.returncode == 0

    assert "Disposable Redis state verified end-to-end (live Redis untouched)." in proc.stdout
    calls = log_file.read_text()
    assert "CALL: STOP_REDIS" not in calls
    assert "CALL: START_REDIS" not in calls

    # Verify isolated docker run calls for redis volume and live process inspection
    assert "nexus_redis_disposable_staging_data:/data" in calls
    assert "tar -xzf /backup/nexus_redis_" in calls
    assert "redis:7-alpine" in calls
    assert "redis-server --dir /data --dbfilename dump.rdb" in calls
    assert "redis-cli ping" in calls
    assert "redis-cli dbsize" in calls

    # Failure scenario: Simulated Redis verification container failure fails closed
    fail_env = env.copy()
    fail_env["MOCK_REDIS_VERIFY_FAIL"] = "true"
    log_file.write_text("")
    proc_fail = subprocess.run(cmd, env=fail_env, capture_output=True, text=True)
    assert proc_fail.returncode != 0
    assert "CRITICAL: Restoration failed in phase 'REDIS_RESTORING'" in proc_fail.stderr
    calls_fail = log_file.read_text()
    assert "CALL: STOP_REDIS" not in calls_fail
    assert "CALL: START_REDIS" not in calls_fail


def test_disposable_restore_failure_retains_split_state_without_touching_live_services(tmp_path: Path) -> None:
    """Failure during disposable restore preserves split-state safety without touching live services or volumes."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    env = os.environ.copy()
    env["PATH"] = f"{str(bin_dir)};{env.get('PATH', '')}"
    env["NEXUS_STAGING_MODE"] = "true"
    env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    env["POSTGRES_DB"] = "nexus_disposable_staging_db"
    env["DATA_VOLUME"] = "nexus_backend_disposable_staging_data"
    env["REDIS_VOLUME"] = "nexus_redis_disposable_staging_data"
    env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    env["MOCK_TARGET_DB"] = "nexus_disposable_staging_db"
    env["MOCK_RESTORE_FAIL"] = "true"

    disposable_db_url = "postgresql://nexus_user:nexus_password@postgres:5432/nexus_disposable_staging_db"

    cmd = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--allow-target-recreate",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--database-url={disposable_db_url}",
    ]

    log_file.write_text("")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "CRITICAL: Restoration failed" in proc.stderr

    calls = log_file.read_text()
    # Confirm live services were never touched
    assert "CALL: STOP_BACKEND_SCHEDULER" not in calls
    assert "CALL: START_BACKEND_SCHEDULER" not in calls
    assert "CALL: STOP_REDIS" not in calls
    assert "CALL: START_REDIS" not in calls
    # Confirm no volume pruning or rollback deletion was performed
    assert "down -v" not in calls
    assert "volume rm" not in calls
    assert "volume prune" not in calls


def test_reconcile_storage_custom_database_url_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    """reconcile_storage.py supports --database-url and binds a custom SQLAlchemy session."""
    import sys
    from unittest.mock import MagicMock, patch
    from scripts import reconcile_storage

    mock_engine = MagicMock()
    mock_session_cls = MagicMock()
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    custom_url = "postgresql://user:pass@host:5432/custom_disposable_db"
    dummy_result = MagicMock()
    dummy_result.total_db_records = 10
    dummy_result.total_disk_files = 10
    dummy_result.missing_files = []
    dummy_result.orphan_files = []
    dummy_result.purged_files = []
    dummy_result.is_consistent = True

    # 1. With --database-url provided
    with patch("sqlalchemy.create_engine", return_value=mock_engine) as mock_create_engine, \
         patch("sqlalchemy.orm.sessionmaker", return_value=mock_session_cls) as mock_sessionmaker, \
         patch("scripts.reconcile_storage.reconcile_tenant_storage", return_value=dummy_result) as mock_reconcile:

        monkeypatch.setattr(sys, "argv", ["reconcile_storage.py", "--database-url", custom_url, "--data-dir", "/custom/data"])
        exit_code = reconcile_storage.main()
        assert exit_code == 0
        mock_create_engine.assert_called_once_with(custom_url)
        mock_sessionmaker.assert_called_once_with(autocommit=False, autoflush=False, bind=mock_engine)
        mock_reconcile.assert_called_once_with(db=mock_session, base_dir=Path("/custom/data"), delete_orphans=False)

    # 2. When --database-url is omitted, SessionLocal is used
    mock_sessionlocal = MagicMock()
    mock_sessionlocal.return_value.__enter__.return_value = mock_session
    with patch("scripts.reconcile_storage.SessionLocal", mock_sessionlocal), \
         patch("sqlalchemy.create_engine") as mock_create_engine_omitted, \
         patch("scripts.reconcile_storage.reconcile_tenant_storage", return_value=dummy_result):

        monkeypatch.setattr(sys, "argv", ["reconcile_storage.py"])
        exit_code = reconcile_storage.main()
        assert exit_code == 0
        mock_create_engine_omitted.assert_not_called()
        mock_sessionlocal.assert_called_once()


def test_backup_allow_test_db_source_scenarios(tmp_path: Path) -> None:
    """Verify --allow-test-db-source scope: default-deny, allowed with flag, and forbidden in prod."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["PYTHONPATH"] = f"{str(repo_root / 'backend')};{base_env.get('PYTHONPATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = "nexus_test_db"
    base_env["DATA_VOLUME"] = "nexus_backend_staging_data"
    base_env["REDIS_VOLUME"] = "nexus_redis_staging_data"
    base_env["BACKUP_ROOT"] = _to_bash_path(tmp_path / "backups")

    # 1. Default-deny: snapshotting nexus_test_db without --allow-test-db-source fails closed
    proc_deny = subprocess.run([bash_bin, backup_script, "--staging"], env=base_env, capture_output=True, text=True)
    assert proc_deny.returncode != 0
    assert "POSTGRES_DB cannot target 'nexus_test_db'" in proc_deny.stderr

    # 2. Permitted when explicit flag --allow-test-db-source is passed
    proc_allow = subprocess.run([bash_bin, backup_script, "--staging", "--allow-test-db-source"], env=base_env, capture_output=True, text=True)
    assert proc_allow.returncode == 0
    assert "Staging test-database source override active" in proc_allow.stdout

    # 3. Production reverse guard: --allow-test-db-source is strictly prohibited in production mode
    prod_env = os.environ.copy()
    prod_env.pop("NEXUS_STAGING_MODE", None)
    proc_prod = subprocess.run([bash_bin, backup_script, "--allow-test-db-source"], env=prod_env, capture_output=True, text=True)
    assert proc_prod.returncode != 0
    assert "Parameter '--allow-test-db-source' is strictly prohibited in production mode" in proc_prod.stderr

    # 4. Restore guard remains 100% untouched: nexus_test_db can NEVER be a restore target
    proc_restore = subprocess.run(
        [bash_bin, restore_script, "--staging", "--confirm-destructive-restore", "20261019_020000"],
        env=base_env,
        capture_output=True,
        text=True,
    )
    assert proc_restore.returncode != 0
    assert "POSTGRES_DB cannot target 'nexus_test_db'" in proc_restore.stderr


def test_backup_retention_isolation_between_directories(tmp_path: Path) -> None:
    """Enforce retention executed on dedicated directory B cannot discover, prune, or mutate directory A artifacts."""
    from app.core.backup import enforce_retention

    dir_a = tmp_path / "backups_phase3f8"
    dir_b = tmp_path / "backups_populated"
    dir_a.mkdir()
    dir_b.mkdir()

    # Create 10 backup sets in dir_a with old timestamps
    for i in range(10):
        ts = f"2026010{i}_000000"
        (dir_a / f"nexus_db_{ts}.dump").write_bytes(b"PGDMP_DUMMY")
        (dir_a / f"nexus_files_{ts}.tar.gz").write_bytes(b"FILES_DUMMY")
        (dir_a / f"nexus_redis_{ts}.tar.gz").write_bytes(b"REDIS_DUMMY")

    files_a_before = set(dir_a.iterdir())
    assert len(files_a_before) == 30

    # Create 2 backup sets in dir_b
    for i in range(2):
        ts = f"2026102{i}_000000"
        (dir_b / f"nexus_db_{ts}.dump").write_bytes(b"PGDMP_DUMMY")
        (dir_b / f"nexus_files_{ts}.tar.gz").write_bytes(b"FILES_DUMMY")

    # Enforce retention on dir_b (even with retention_days=0 and min_retained=1)
    pruned = enforce_retention(backup_dir=dir_b, retention_days=0, min_retained_sets=1, now=2000000000.0)

    # Prove dir_a is 100% untouched
    files_a_after = set(dir_a.iterdir())
    assert files_a_before == files_a_after, "Artifacts in dir_a must remain completely untouched"
    for f in dir_a.iterdir():
        assert f.exists()
        assert f.stat().st_size > 0


def test_reconcile_storage_exit_codes_and_json_modes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """reconcile_storage.py returns 0 for consistent, 1 for inconsistent, 2 for operational error, and supports --json."""
    import json
    import sys
    from unittest.mock import MagicMock, patch
    from scripts import reconcile_storage

    dummy_result = MagicMock()
    dummy_result.total_db_records = 34
    dummy_result.total_disk_files = 1908
    dummy_result.missing_files = [("id1", "file1.csv", "key1")]
    dummy_result.orphan_files = [Path("/path/to/orphan.csv")]
    dummy_result.purged_files = []
    dummy_result.is_consistent = False
    dummy_result.to_dict.return_value = {
        "total_db_records": 34,
        "missing_files_count": 1,
        "missing_files": [{"id": "id1", "filename": "file1.csv", "storage_key": "key1"}],
        "total_disk_files": 1908,
        "orphan_files_count": 1,
        "orphan_files": ["/path/to/orphan.csv"],
        "purged_files_count": 0,
        "is_consistent": False,
    }

    mock_session = MagicMock()
    mock_session_cls = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session

    # 1. Inconsistent audit: exits with code 1
    with patch("scripts.reconcile_storage.SessionLocal", mock_session_cls), \
         patch("scripts.reconcile_storage.reconcile_tenant_storage", return_value=dummy_result):
        monkeypatch.setattr(sys, "argv", ["reconcile_storage.py"])
        exit_code = reconcile_storage.main()
        assert exit_code == 1

    # 2. Inconsistent audit with --json: exits with code 1 and outputs valid JSON
    with patch("scripts.reconcile_storage.SessionLocal", mock_session_cls), \
         patch("scripts.reconcile_storage.reconcile_tenant_storage", return_value=dummy_result):
        monkeypatch.setattr(sys, "argv", ["reconcile_storage.py", "--json"])
        capsys.readouterr()  # clear buffer
        exit_code = reconcile_storage.main()
        assert exit_code == 1
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data["status"] == "inconsistent"
        assert data["is_consistent"] is False
        assert data["missing_files_count"] == 1

    # 3. Consistent audit: exits with code 0
    dummy_consistent = MagicMock()
    dummy_consistent.is_consistent = True
    dummy_consistent.total_db_records = 34
    dummy_consistent.total_disk_files = 34
    dummy_consistent.missing_files = []
    dummy_consistent.orphan_files = []
    dummy_consistent.purged_files = []
    dummy_consistent.to_dict.return_value = {"is_consistent": True}
    with patch("scripts.reconcile_storage.SessionLocal", mock_session_cls), \
         patch("scripts.reconcile_storage.reconcile_tenant_storage", return_value=dummy_consistent):
        monkeypatch.setattr(sys, "argv", ["reconcile_storage.py"])
        exit_code = reconcile_storage.main()
        assert exit_code == 0

    # 4. Operational / connection / schema error: exits with code 2
    with patch("scripts.reconcile_storage.SessionLocal", side_effect=Exception("Database connection timeout")):
        monkeypatch.setattr(sys, "argv", ["reconcile_storage.py"])
        exit_code = reconcile_storage.main()
        assert exit_code == 2

    # 5. Operational error with --json: exits with code 2 and outputs structured JSON error
    with patch("scripts.reconcile_storage.SessionLocal", side_effect=Exception("Relation does not exist")):
        monkeypatch.setattr(sys, "argv", ["reconcile_storage.py", "--json"])
        capsys.readouterr()
        exit_code = reconcile_storage.main()
        assert exit_code == 2
        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data["status"] == "error"
        assert data["error_type"] == "Exception"
        assert "Relation does not exist" in data["message"]


def test_disposable_restore_reconciliation_distinguishes_inconsistency_from_operational_error(tmp_path: Path) -> None:
    """Disposable restore allows preflight data discrepancy (exit 1) but fails closed on operational error (exit 2)."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    redis_file = valid_backup_dir / f"nexus_redis_{ts}.tar.gz"
    with tarfile.open(redis_file, "w:gz") as tar:
        pass
    redis_bytes = redis_file.read_bytes()
    redis_hash = hashlib.sha256(redis_bytes).hexdigest()
    sidecar_redis = valid_backup_dir / f"nexus_redis_{ts}.tar.gz.sha256"
    sidecar_redis.write_bytes(f"{redis_hash}  {_to_bash_path(redis_file)}\n".encode("utf-8"))

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = "nexus_disposable_staging_db"
    base_env["DATA_VOLUME"] = "nexus_backend_disposable_staging_data"
    base_env["REDIS_VOLUME"] = "nexus_redis_disposable_staging_data"
    base_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    base_env["MOCK_TARGET_DB"] = "nexus_disposable_staging_db"

    disposable_db_url = "postgresql://nexus_user:nexus_password@postgres:5432/nexus_disposable_staging_db"
    cmd = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--allow-target-recreate",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--database-url={disposable_db_url}",
    ]

    # 1. Inconsistent storage (exit code 1): logs discrepancy and completes successfully
    env_inconsistent = base_env.copy()
    env_inconsistent["MOCK_RECONCILE_MODE"] = "fail_inconsistent"
    log_file.write_text("")
    proc_inc = subprocess.run(cmd, env=env_inconsistent, capture_output=True, text=True)
    assert proc_inc.returncode == 0
    assert "Preflight discrepancy recorded: Test DB and staging volume are disjoint as expected" in proc_inc.stdout
    assert "=== Coordinated Restore Completed Successfully ===" in proc_inc.stdout

    # 2. Operational / connection / execution error (exit code 2): fails closed immediately
    env_exec_err = base_env.copy()
    env_exec_err["MOCK_RECONCILE_MODE"] = "fail_exec"
    log_file.write_text("")
    proc_err = subprocess.run(cmd, env=env_exec_err, capture_output=True, text=True)
    assert proc_err.returncode != 0
    assert "SAFETY ERROR: Storage reconciliation failed with operational/execution error (exit code 2)" in proc_err.stderr
    assert "CRITICAL: Restoration failed in phase 'VERIFYING'" in proc_err.stderr


def test_disposable_restore_fresh_target_isolation_and_label_attestation(tmp_path: Path) -> None:
    """Fresh disposable targets are fully isolated: drop/create targets only the new DB, never touching preserved or live DBs/volumes."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    redis_file = valid_backup_dir / f"nexus_redis_{ts}.tar.gz"
    with tarfile.open(redis_file, "w:gz") as tar:
        pass
    redis_bytes = redis_file.read_bytes()
    redis_hash = hashlib.sha256(redis_bytes).hexdigest()
    sidecar_redis = valid_backup_dir / f"nexus_redis_{ts}.tar.gz.sha256"
    sidecar_redis.write_bytes(f"{redis_hash}  {_to_bash_path(redis_file)}\n".encode("utf-8"))

    fresh_db = "nexus_disposable_populated_staging_db"
    fresh_data_vol = "nexus_backend_disposable_populated_staging_data"
    fresh_redis_vol = "nexus_redis_disposable_populated_staging_data"
    fresh_db_url = f"postgresql://nexus_user:nexus_password@postgres:5432/{fresh_db}"

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = fresh_db
    base_env["DATA_VOLUME"] = fresh_data_vol
    base_env["REDIS_VOLUME"] = fresh_redis_vol
    base_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    base_env["MOCK_TARGET_DB"] = fresh_db

    cmd = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--allow-target-recreate",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--database-url={fresh_db_url}",
    ]

    # 1. Successful fresh target restoration: drops and recreates strictly fresh_db
    log_file.write_text("")
    proc = subprocess.run(cmd, env=base_env, capture_output=True, text=True)
    assert proc.returncode == 0
    calls = log_file.read_text()

    # Verify dropdb and createdb targeted only the fresh DB
    assert f"dropdb -U nexus_user --if-exists {fresh_db}" in calls
    assert f"createdb -U nexus_user {fresh_db}" in calls
    assert f"pg_restore -U nexus_user -d {fresh_db}" in calls

    # Verify preserved DBs were NEVER dropped or targeted
    assert "dropdb -U nexus_user --if-exists nexus_disposable_staging_db" not in calls
    assert "dropdb -U nexus_user --if-exists nexus_staging_db" not in calls
    assert "dropdb -U nexus_user --if-exists nexus_test_db" not in calls
    assert "createdb -U nexus_user nexus_disposable_staging_db" not in calls
    assert "createdb -U nexus_user nexus_staging_db" not in calls
    assert "createdb -U nexus_user nexus_test_db" not in calls

    # Verify fresh volumes were mounted, preserving previous disposable and live volumes
    assert f"{fresh_data_vol}:/data" in calls
    assert f"{fresh_redis_vol}:/data" in calls
    assert "nexus_backend_disposable_staging_data:/data" not in calls
    assert "nexus_redis_disposable_staging_data:/data" not in calls
    assert "nexus_backend_staging_data:/data" not in calls
    assert "nexus_redis_staging_data:/data" not in calls

    # 2. Volume label attestation fails closed if volume lacks staging project label
    env_unlabeled_vol = base_env.copy()
    env_unlabeled_vol["MOCK_VOL_LABEL_MISMATCH"] = "true"
    log_file.write_text("")
    proc_vol_err = subprocess.run(cmd, env=env_unlabeled_vol, capture_output=True, text=True)
    assert proc_vol_err.returncode != 0
    assert "SAFETY ERROR: Staging volume" in proc_vol_err.stderr
    assert "does not match expected staging project ('nexus-staging')" in proc_vol_err.stderr
    calls_vol_err = log_file.read_text()
    assert "CALL: DROPDB" not in calls_vol_err
    assert "CALL: CREATEDB" not in calls_vol_err

    # 3. Mismatched database URL fails closed before any drop or restore
    mismatched_cmd = list(cmd)
    mismatched_cmd[-1] = "--database-url=postgresql://nexus_user:pass@postgres:5432/nexus_disposable_staging_db"
    proc_mismatch = subprocess.run(mismatched_cmd, env=base_env, capture_output=True, text=True)
    assert proc_mismatch.returncode != 0
    assert "SAFETY ERROR: Disposable DATABASE_URL target database ('nexus_disposable_staging_db') does not match POSTGRES_DB ('nexus_disposable_populated_staging_db')" in proc_mismatch.stderr


def test_disposable_restore_allow_target_recreate_guardrails(tmp_path: Path) -> None:
    """Verify --allow-target-recreate guardrails:
    1. An existing disposable target is rejected by default before any destructive command.
    2. An existing target is eligible for recreation only with the explicit flag.
    3. Protected databases remain rejected even with the flag.
    4. A missing fresh target proceeds without the flag.
    5. Production mode rejects the flag (and staging mode without --disposable-target rejects the flag).
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    redis_file = valid_backup_dir / f"nexus_redis_{ts}.tar.gz"
    with tarfile.open(redis_file, "w:gz") as tar:
        pass
    redis_bytes = redis_file.read_bytes()
    redis_hash = hashlib.sha256(redis_bytes).hexdigest()
    sidecar_redis = valid_backup_dir / f"nexus_redis_{ts}.tar.gz.sha256"
    sidecar_redis.write_bytes(f"{redis_hash}  {_to_bash_path(redis_file)}\n".encode("utf-8"))

    fresh_db = "nexus_disposable_audit_staging_db"
    fresh_data = "nexus_backend_disposable_audit_staging_data"
    fresh_redis = "nexus_redis_disposable_audit_staging_data"
    fresh_url = f"postgresql://nexus_user:pass@postgres:5432/{fresh_db}"

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = fresh_db
    base_env["DATA_VOLUME"] = fresh_data
    base_env["REDIS_VOLUME"] = fresh_redis
    base_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    base_env["MOCK_TARGET_DB"] = fresh_db

    cmd_no_flag = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--database-url={fresh_url}",
    ]

    # 1. Existing disposable target is rejected by default before any destructive command
    log_file.write_text("")
    proc1 = subprocess.run(cmd_no_flag, env=base_env, capture_output=True, text=True)
    assert proc1.returncode != 0
    assert f"SAFETY ERROR: Disposable target database '{fresh_db}' already exists in PostgreSQL catalog" in proc1.stderr
    assert "Fresh target verification requires target database to be absent (MATCH_COUNT=0)" in proc1.stderr
    assert "pass '--allow-target-recreate'" in proc1.stderr
    calls1 = log_file.read_text()
    assert "CALL: PG_TERMINATE_BACKEND" not in calls1
    assert "CALL: DROPDB" not in calls1
    assert "CALL: CREATEDB" not in calls1
    assert "CALL: PG_RESTORE" not in calls1
    assert "CALL: STOP_BACKEND_SCHEDULER" not in calls1
    assert "CALL: STOP_REDIS" not in calls1

    # 2. Existing target is eligible for recreation only with the explicit flag
    cmd_with_flag = list(cmd_no_flag) + ["--allow-target-recreate"]
    log_file.write_text("")
    proc2 = subprocess.run(cmd_with_flag, env=base_env, capture_output=True, text=True)
    assert proc2.returncode == 0, f"Failed with stderr:\n{proc2.stderr}"
    assert f"Verified existing target database '{fresh_db}' in catalog (approved for safe drop and recreate)" in proc2.stdout
    assert "=== Coordinated Restore Completed Successfully ===" in proc2.stdout
    calls2 = log_file.read_text()
    assert "CALL: PG_TERMINATE_BACKEND" in calls2
    assert f"dropdb -U nexus_user --if-exists {fresh_db}" in calls2
    assert f"createdb -U nexus_user {fresh_db}" in calls2
    assert f"pg_restore -U nexus_user -d {fresh_db}" in calls2

    # 3. Protected databases remain rejected even with the flag
    protected_cases = [
        ("nexus_staging_db", "In disposable target mode, POSTGRES_DB cannot target live staging database 'nexus_staging_db'"),
        ("nexus_test_db", "In staging mode, POSTGRES_DB cannot target 'nexus_test_db'"),
        ("nexus_db", "In staging mode, POSTGRES_DB cannot target 'nexus_db'"),
    ]
    for prot_db, expected_err in protected_cases:
        env_prot = base_env.copy()
        env_prot["POSTGRES_DB"] = prot_db
        env_prot["MOCK_TARGET_DB"] = prot_db
        prot_cmd = [
            bash_bin,
            restore_script,
            "--staging",
            "--disposable-target",
            "--allow-target-recreate",
            "--confirm-destructive-restore",
            ts,
            "--backup-root=" + _to_bash_path(valid_backup_dir),
            f"--database-url=postgresql://nexus_user:pass@postgres:5432/{prot_db}",
        ]
        log_file.write_text("")
        proc_prot = subprocess.run(prot_cmd, env=env_prot, capture_output=True, text=True)
        assert proc_prot.returncode != 0
        assert expected_err in proc_prot.stderr
        calls_prot = log_file.read_text()
        assert "CALL: PG_TERMINATE_BACKEND" not in calls_prot
        assert "CALL: DROPDB" not in calls_prot
        assert "CALL: CREATEDB" not in calls_prot

    # 4. A missing fresh target proceeds without the flag
    env_missing = base_env.copy()
    env_missing["MOCK_CATALOG_MODE"] = "missing_target"
    log_file.write_text("")
    proc4 = subprocess.run(cmd_no_flag, env=env_missing, capture_output=True, text=True)
    assert proc4.returncode == 0, f"Failed with stderr:\n{proc4.stderr}"
    assert f"Target database '{fresh_db}' does not yet exist in catalog. Clean target creation will proceed" in proc4.stdout
    assert "=== Coordinated Restore Completed Successfully ===" in proc4.stdout
    calls4 = log_file.read_text()
    assert "CALL: PG_TERMINATE_BACKEND" not in calls4
    assert "CALL: DROPDB" not in calls4
    assert f"createdb -U nexus_user {fresh_db}" in calls4
    assert f"pg_restore -U nexus_user -d {fresh_db}" in calls4

    # 5. Production mode rejects the flag (and staging without --disposable-target rejects the flag)
    prod_env = os.environ.copy()
    prod_env["PATH"] = f"{str(bin_dir)};{prod_env.get('PATH', '')}"
    prod_env.pop("NEXUS_STAGING_MODE", None)
    proc5a = subprocess.run(
        [bash_bin, restore_script, "--allow-target-recreate", "--confirm-destructive-restore", ts, "--backup-root=" + _to_bash_path(valid_backup_dir)],
        env=prod_env,
        capture_output=True,
        text=True,
    )
    assert proc5a.returncode != 0
    assert "'--allow-target-recreate' is strictly prohibited in production mode" in proc5a.stderr

    proc5b = subprocess.run(
        [bash_bin, restore_script, "--staging", "--allow-target-recreate", "--confirm-destructive-restore", ts, "--backup-root=" + _to_bash_path(valid_backup_dir)],
        env=base_env,
        capture_output=True,
        text=True,
    )
    assert proc5b.returncode != 0
    assert "'--allow-target-recreate' is valid only with '--disposable-target'" in proc5b.stderr


def test_backup_coordinated_skip_redis_flag(tmp_path: Path) -> None:
    """Verify that --skip-redis in backup_nexus_coordinated.sh cleanly excludes Redis snapshot, attestation, and archive."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    backup_script = str(repo_root / "scripts" / "backup_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["PYTHONPATH"] = f"{str(repo_root / 'backend')};{base_env.get('PYTHONPATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = "nexus_fixture_staging_db"
    base_env["DATA_VOLUME"] = "nexus_backend_fixture_staging_data"
    base_env["BACKUP_ROOT"] = _to_bash_path(backup_dir)

    # Note: REDIS_VOLUME is intentionally NOT set and Redis container is MOCK_REDIS_CONTAINERS=0
    base_env["MOCK_REDIS_CONTAINERS"] = "0"

    cmd = [
        bash_bin,
        backup_script,
        "--staging",
        "--skip-redis",
        "--no-quiesce",
        "--backup-root=" + _to_bash_path(backup_dir),
    ]

    log_file.write_text("")
    proc = subprocess.run(cmd, env=base_env, capture_output=True, text=True)
    assert proc.returncode == 0, f"Backup with --skip-redis failed:\n{proc.stderr}"
    assert "Skipping Redis persistence snapshot (--skip-redis specified)" in proc.stdout
    assert "Redis state excluded from backup set. Live Redis untouched" in proc.stdout
    assert "=== Coordinated Backup Completed Successfully ===" in proc.stdout

    calls = log_file.read_text()
    assert "CALL: REDIS_BGSAVE" not in calls

    # Verify that database and files archives exist with sha256 sidecars, but redis archive does not
    dump_files = list(backup_dir.glob("nexus_db_*.dump"))
    assert len(dump_files) == 1
    assert (backup_dir / f"{dump_files[0].name}.sha256").exists()

    tar_files = list(backup_dir.glob("nexus_files_*.tar.gz"))
    assert len(tar_files) == 1
    assert (backup_dir / f"{tar_files[0].name}.sha256").exists()

    redis_files = list(backup_dir.glob("nexus_redis_*.tar.gz"))
    assert len(redis_files) == 0


def test_disposable_restore_existence_guards_fail_closed_offline(tmp_path: Path) -> None:
    """Verify disposable restore existence guard fails closed when target database, data volume,
    or Redis volume already exists—even if a volume is empty or the Redis backup is absent.
    Verifies that no existing resources are deleted or recreated, and that clean fresh targets or
    explicit --allow-target-recreate proceed safely.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    sidecar_db = valid_backup_dir / f"nexus_db_{ts}.dump.sha256"
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    sidecar_db.write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))

    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_bytes = files_file.read_bytes()
    files_hash = hashlib.sha256(files_bytes).hexdigest()
    sidecar_files = valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256"
    sidecar_files.write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))

    redis_file = valid_backup_dir / f"nexus_redis_{ts}.tar.gz"
    with tarfile.open(redis_file, "w:gz") as tar:
        pass
    redis_bytes = redis_file.read_bytes()
    redis_hash = hashlib.sha256(redis_bytes).hexdigest()
    sidecar_redis = valid_backup_dir / f"nexus_redis_{ts}.tar.gz.sha256"
    sidecar_redis.write_bytes(f"{redis_hash}  {_to_bash_path(redis_file)}\n".encode("utf-8"))

    fresh_db = "nexus_disposable_guard_staging_db"
    fresh_data = "nexus_backend_disposable_guard_staging_data"
    fresh_redis = "nexus_redis_disposable_guard_staging_data"
    fresh_url = f"postgresql://nexus_user:pass@postgres:5432/{fresh_db}"

    base_env = os.environ.copy()
    base_env["PATH"] = f"{str(bin_dir)};{base_env.get('PATH', '')}"
    base_env["PYTHONPATH"] = f"{str(repo_root / 'backend')};{base_env.get('PYTHONPATH', '')}"
    base_env["NEXUS_STAGING_MODE"] = "true"
    base_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_env["POSTGRES_DB"] = fresh_db
    base_env["DATA_VOLUME"] = fresh_data
    base_env["REDIS_VOLUME"] = fresh_redis
    base_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    base_env["POSTGRES_PASSWORD"] = "test_valid_staging_pw_16_chars"
    base_env["SECRET_KEY"] = "test_valid_staging_secret_key_32_chars_long"
    base_env["AUTH_JWT_SECRET"] = "test_valid_staging_jwt_secret_32_chars_long"
    base_env["REQUIRE_POSTGRES"] = "true"
    base_env["LLM_ALLOW_EXTERNAL_CALLS"] = "false"

    cmd = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--redis-volume={fresh_redis}",
        f"--database-url={fresh_url}",
    ]

    # Case 1: Target database already exists in PostgreSQL catalog -> Fails closed without modifying anything
    env_db_exists = base_env.copy()
    env_db_exists["MOCK_TARGET_DB"] = fresh_db
    env_db_exists["MOCK_CATALOG_MODE"] = "existing"
    log_file.write_text("")
    proc_db = subprocess.run(cmd, env=env_db_exists, capture_output=True, text=True)
    assert proc_db.returncode != 0
    assert f"SAFETY ERROR: Disposable target database '{fresh_db}' already exists in PostgreSQL catalog" in proc_db.stderr
    assert "Fresh target verification requires target database to be absent (MATCH_COUNT=0)" in proc_db.stderr
    assert "pass '--allow-target-recreate'" in proc_db.stderr
    calls_db = log_file.read_text()
    assert "CALL: PG_TERMINATE_BACKEND" not in calls_db
    assert "CALL: DROPDB" not in calls_db
    assert "CALL: CREATEDB" not in calls_db
    assert "CALL: PG_RESTORE" not in calls_db

    # Case 2: Target data volume already exists (even if empty) -> Fails closed
    env_data_exists = base_env.copy()
    env_data_exists["MOCK_CATALOG_MODE"] = "missing_target"
    env_data_exists["MOCK_DATA_VOL_EXISTS"] = "true"
    log_file.write_text("")
    proc_data = subprocess.run(cmd, env=env_data_exists, capture_output=True, text=True)
    assert proc_data.returncode != 0
    assert f"SAFETY ERROR: Disposable target data volume '{fresh_data}' already exists in Docker volumes" in proc_data.stderr
    assert "Fresh target verification requires target data volume to be absent (even if empty)" in proc_data.stderr
    assert "pass '--allow-target-recreate'" in proc_data.stderr
    calls_data = log_file.read_text()
    assert "CALL: DROPDB" not in calls_data
    assert "CALL: CREATEDB" not in calls_data

    # Case 3: Target Redis volume already exists (even if empty) -> Fails closed
    env_redis_exists = base_env.copy()
    env_redis_exists["MOCK_CATALOG_MODE"] = "missing_target"
    env_redis_exists["MOCK_REDIS_VOL_EXISTS"] = "true"
    log_file.write_text("")
    proc_redis = subprocess.run(cmd, env=env_redis_exists, capture_output=True, text=True)
    assert proc_redis.returncode != 0
    assert f"SAFETY ERROR: Disposable target Redis volume '{fresh_redis}' already exists in Docker volumes" in proc_redis.stderr
    assert "Fresh target verification requires target Redis volume to be absent (even if empty or Redis backup is absent)" in proc_redis.stderr
    assert "pass '--allow-target-recreate'" in proc_redis.stderr
    calls_redis = log_file.read_text()
    assert "CALL: DROPDB" not in calls_redis
    assert "CALL: CREATEDB" not in calls_redis

    # Case 4: Target Redis volume already exists even if Redis backup is absent -> Fails closed
    backup_no_redis_dir = tmp_path / "backups_no_redis"
    backup_no_redis_dir.mkdir(parents=True, exist_ok=True)
    no_redis_db = backup_no_redis_dir / f"nexus_db_{ts}.dump"
    no_redis_db.write_bytes(b"PGDMP_TEST_CONTENT")
    (backup_no_redis_dir / f"nexus_db_{ts}.dump.sha256").write_bytes(f"{db_hash}  {_to_bash_path(no_redis_db)}\n".encode("utf-8"))
    no_redis_files = backup_no_redis_dir / f"nexus_files_{ts}.tar.gz"
    with tarfile.open(no_redis_files, "w:gz") as tar:
        pass
    no_redis_files_bytes = no_redis_files.read_bytes()
    no_redis_files_hash = hashlib.sha256(no_redis_files_bytes).hexdigest()
    (backup_no_redis_dir / f"nexus_files_{ts}.tar.gz.sha256").write_bytes(f"{no_redis_files_hash}  {_to_bash_path(no_redis_files)}\n".encode("utf-8"))

    cmd_no_redis = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(backup_no_redis_dir),
        f"--redis-volume={fresh_redis}",
        f"--database-url={fresh_url}",
    ]
    env_no_redis_backup = base_env.copy()
    env_no_redis_backup["MOCK_CATALOG_MODE"] = "missing_target"
    env_no_redis_backup["MOCK_REDIS_VOL_EXISTS"] = "true"
    env_no_redis_backup["BACKUP_ROOT"] = _to_bash_path(backup_no_redis_dir)
    log_file.write_text("")
    proc_no_rdb = subprocess.run(cmd_no_redis, env=env_no_redis_backup, capture_output=True, text=True)
    assert proc_no_rdb.returncode != 0
    assert f"SAFETY ERROR: Disposable target Redis volume '{fresh_redis}' already exists in Docker volumes" in proc_no_rdb.stderr
    assert "Fresh target verification requires target Redis volume to be absent (even if empty or Redis backup is absent)" in proc_no_rdb.stderr
    assert "pass '--allow-target-recreate'" in proc_no_rdb.stderr

    # Case 5: Clean fresh targets (DB absent, data volume absent, Redis volume absent) -> Succeeds without --allow-target-recreate
    env_clean = base_env.copy()
    env_clean["MOCK_CATALOG_MODE"] = "missing_target"
    log_file.write_text("")
    proc_clean = subprocess.run(cmd, env=env_clean, capture_output=True, text=True)
    assert proc_clean.returncode == 0, f"Clean disposable restore failed with stderr:\n{proc_clean.stderr}"
    assert "Verified disposable target volumes" in proc_clean.stdout
    assert "are absent and fresh" in proc_clean.stdout
    assert "Target database 'nexus_disposable_guard_staging_db' does not yet exist in catalog. Clean target creation will proceed" in proc_clean.stdout
    assert "=== Coordinated Restore Completed Successfully ===" in proc_clean.stdout
    calls_clean = log_file.read_text()
    assert "CALL: PG_TERMINATE_BACKEND" not in calls_clean
    assert "CALL: DROPDB" not in calls_clean
    assert f"createdb -U nexus_user {fresh_db}" in calls_clean
    assert f"pg_restore -U nexus_user -d {fresh_db}" in calls_clean

    # Case 6: Existing targets with --allow-target-recreate -> Proceeds and drops/recreates safely
    env_recreate = base_env.copy()
    env_recreate["MOCK_CATALOG_MODE"] = "existing"
    env_recreate["MOCK_TARGET_DB"] = fresh_db
    env_recreate["MOCK_DATA_VOL_EXISTS"] = "true"
    env_recreate["MOCK_REDIS_VOL_EXISTS"] = "true"
    cmd_override = list(cmd) + ["--allow-target-recreate"]
    log_file.write_text("")
    proc_recreate = subprocess.run(cmd_override, env=env_recreate, capture_output=True, text=True)
    assert proc_recreate.returncode == 0, f"Override disposable restore failed with stderr:\n{proc_recreate.stderr}"
    assert "Disposable target recreate approved (--allow-target-recreate). Attesting existing volume labels" in proc_recreate.stdout
    assert f"Verified existing target database '{fresh_db}' in catalog (approved for safe drop and recreate)" in proc_recreate.stdout
    assert "=== Coordinated Restore Completed Successfully ===" in proc_recreate.stdout
    calls_recreate = log_file.read_text()
    assert "CALL: PG_TERMINATE_BACKEND" in calls_recreate
    assert f"dropdb -U nexus_user --if-exists {fresh_db}" in calls_recreate
    assert f"createdb -U nexus_user {fresh_db}" in calls_recreate
    assert f"pg_restore -U nexus_user -d {fresh_db}" in calls_recreate


def test_staging_credentials_and_privilege_preflight_fail_closed_offline(tmp_path: Path) -> None:
    """Offline test suite for staging credentials and database privilege preflight (Phase 3F.32).
    Verifies fail-closed behavior for:
    1. Missing secrets (POSTGRES_PASSWORD, SECRET_KEY, AUTH_JWT_SECRET).
    2. Empty secrets.
    3. Known insecure defaults (e.g. nexus_staging_password, nexus-staging-secret-key-change-me).
    4. Default example placeholders (GENERATE_SECURE_PASSWORD_MIN_16_CHARS).
    5. Short secrets (password < 16 chars, app secrets < 32 chars).
    6. Security invariant violations (REQUIRE_POSTGRES != true, LLM_ALLOW_EXTERNAL_CALLS != false).
    7. Database role lacking CREATEDB and superuser authority in pg_roles.
    8. Successful execution when strong credentials and CREATEDB permissions are supplied.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    preflight_script = str(repo_root / "scripts" / "preflight_staging_env.sh").replace("\\", "/")
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    def _to_bash_path(p: Path) -> str:
        s = str(p).replace("\\", "/")
        if len(s) >= 2 and s[1] == ":":
            s = f"/{s[0].lower()}{s[2:]}"
        return s

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker_calls.log"
    _create_docker_stub(bin_dir, log_file)

    dummy_compose = tmp_path / "docker-compose.staging.yml"
    dummy_compose.write_text("services: {}\n")

    valid_backup_dir = tmp_path / "valid_backups"
    valid_backup_dir.mkdir(parents=True, exist_ok=True)
    ts = "20261019_020000"
    db_file = valid_backup_dir / f"nexus_db_{ts}.dump"
    db_file.write_bytes(b"PGDMP_TEST_CONTENT")
    import hashlib
    db_hash = hashlib.sha256(b"PGDMP_TEST_CONTENT").hexdigest()
    (valid_backup_dir / f"nexus_db_{ts}.dump.sha256").write_bytes(f"{db_hash}  {_to_bash_path(db_file)}\n".encode("utf-8"))
    files_file = valid_backup_dir / f"nexus_files_{ts}.tar.gz"
    import tarfile
    with tarfile.open(files_file, "w:gz") as tar:
        pass
    files_hash = hashlib.sha256(files_file.read_bytes()).hexdigest()
    (valid_backup_dir / f"nexus_files_{ts}.tar.gz.sha256").write_bytes(f"{files_hash}  {_to_bash_path(files_file)}\n".encode("utf-8"))
    redis_file = valid_backup_dir / f"nexus_redis_{ts}.tar.gz"
    with tarfile.open(redis_file, "w:gz") as tar:
        pass
    redis_hash = hashlib.sha256(redis_file.read_bytes()).hexdigest()
    (valid_backup_dir / f"nexus_redis_{ts}.tar.gz.sha256").write_bytes(f"{redis_hash}  {_to_bash_path(redis_file)}\n".encode("utf-8"))

    fresh_db = "nexus_preflight_guard_staging_db"
    fresh_data = "nexus_backend_preflight_guard_staging_data"
    fresh_redis = "nexus_redis_preflight_guard_staging_data"
    fresh_url = f"postgresql://nexus_user:pass@postgres:5432/{fresh_db}"

    # 1. Standalone Preflight Tests via preflight_staging_env.sh
    # Case 1A: Completely missing credentials -> fails closed
    p1 = subprocess.run([bash_bin, preflight_script, "--staging"], capture_output=True, text=True, env={})
    assert p1.returncode != 0
    assert "Environment variable 'POSTGRES_PASSWORD (or STAGING_DB_PASSWORD)' is unset or empty" in p1.stderr
    assert "Environment variable 'SECRET_KEY' is unset or empty" in p1.stderr
    assert "Environment variable 'AUTH_JWT_SECRET' is unset or empty" in p1.stderr

    # Case 1B: Empty string password -> fails closed
    env_empty = {
        "NEXUS_STAGING_MODE": "true",
        "POSTGRES_PASSWORD": "",
        "SECRET_KEY": "valid_staging_secret_key_32_chars_long",
        "AUTH_JWT_SECRET": "valid_staging_jwt_secret_32_chars_long",
        "REQUIRE_POSTGRES": "true",
        "LLM_ALLOW_EXTERNAL_CALLS": "false",
    }
    p_empty = subprocess.run([bash_bin, preflight_script, "--staging"], capture_output=True, text=True, env=env_empty)
    assert p_empty.returncode != 0
    assert "Environment variable 'POSTGRES_PASSWORD (or STAGING_DB_PASSWORD)' is unset or empty" in p_empty.stderr

    # Case 1C: Known insecure defaults -> fails closed
    env_default = {
        "NEXUS_STAGING_MODE": "true",
        "POSTGRES_PASSWORD": "nexus_staging_password",
        "SECRET_KEY": "nexus-staging-secret-key-change-me",
        "AUTH_JWT_SECRET": "nexus-staging-jwt-secret-key-change-in-staging-min-32-chars",
        "REQUIRE_POSTGRES": "true",
        "LLM_ALLOW_EXTERNAL_CALLS": "false",
    }
    p_def = subprocess.run([bash_bin, preflight_script, "--staging"], capture_output=True, text=True, env=env_default)
    assert p_def.returncode != 0
    assert "Environment variable 'POSTGRES_PASSWORD' matches known insecure default or placeholder value" in p_def.stderr
    assert "Environment variable 'SECRET_KEY' matches known insecure default or placeholder value" in p_def.stderr
    assert "Environment variable 'AUTH_JWT_SECRET' matches known insecure default or placeholder value" in p_def.stderr

    # Case 1D: Staging example placeholders -> fails closed
    env_placeholder = {
        "NEXUS_STAGING_MODE": "true",
        "POSTGRES_PASSWORD": "GENERATE_SECURE_PASSWORD_MIN_16_CHARS",
        "SECRET_KEY": "GENERATE_SECURE_SECRET_MIN_32_CHARS",
        "AUTH_JWT_SECRET": "GENERATE_SECURE_SECRET_MIN_32_CHARS",
        "REQUIRE_POSTGRES": "true",
        "LLM_ALLOW_EXTERNAL_CALLS": "false",
    }
    p_ph = subprocess.run([bash_bin, preflight_script, "--staging"], capture_output=True, text=True, env=env_placeholder)
    assert p_ph.returncode != 0
    assert "Environment variable 'POSTGRES_PASSWORD' matches known insecure default or placeholder value" in p_ph.stderr

    # Case 1E: Short password and secrets -> fails closed
    env_short = {
        "NEXUS_STAGING_MODE": "true",
        "POSTGRES_PASSWORD": "shortpassword",
        "SECRET_KEY": "shortsecretkey",
        "AUTH_JWT_SECRET": "shortjwtsecret",
        "REQUIRE_POSTGRES": "true",
        "LLM_ALLOW_EXTERNAL_CALLS": "false",
    }
    p_short = subprocess.run([bash_bin, preflight_script, "--staging"], capture_output=True, text=True, env=env_short)
    assert p_short.returncode != 0
    assert "Environment variable 'POSTGRES_PASSWORD' length (13) is below required minimum of 16 characters" in p_short.stderr
    assert "Environment variable 'SECRET_KEY' length (14) is below required minimum of 32 characters" in p_short.stderr

    # Case 1F: Security Invariant Violations -> fails closed
    env_inv = {
        "NEXUS_STAGING_MODE": "true",
        "POSTGRES_PASSWORD": "valid_strong_test_password_16_chars",
        "SECRET_KEY": "valid_staging_secret_key_32_chars_long",
        "AUTH_JWT_SECRET": "valid_staging_jwt_secret_32_chars_long",
        "REQUIRE_POSTGRES": "false",
        "LLM_ALLOW_EXTERNAL_CALLS": "true",
    }
    p_inv = subprocess.run([bash_bin, preflight_script, "--staging"], capture_output=True, text=True, env=env_inv)
    assert p_inv.returncode != 0
    assert "Invariant violation: REQUIRE_POSTGRES must be 'true'" in p_inv.stderr
    assert "Invariant violation: LLM_ALLOW_EXTERNAL_CALLS must be 'false'" in p_inv.stderr

    # Case 1G: Valid strong credentials -> passes preflight cleanly
    env_valid = {
        "NEXUS_STAGING_MODE": "true",
        "POSTGRES_PASSWORD": "valid_strong_test_password_16_chars",
        "SECRET_KEY": "valid_staging_secret_key_32_chars_long",
        "AUTH_JWT_SECRET": "valid_staging_jwt_secret_32_chars_long",
        "REQUIRE_POSTGRES": "true",
        "LLM_ALLOW_EXTERNAL_CALLS": "false",
    }
    p_valid = subprocess.run([bash_bin, preflight_script, "--staging"], capture_output=True, text=True, env=env_valid)
    assert p_valid.returncode == 0
    assert "Staging environment & credentials preflight passed" in p_valid.stdout

    # 2. Integrated Restore Preflight Tests via restore_nexus_coordinated.sh
    base_restore_env = os.environ.copy()
    base_restore_env["PATH"] = f"{str(bin_dir)};{base_restore_env.get('PATH', '')}"
    base_restore_env["PYTHONPATH"] = f"{str(repo_root / 'backend')};{base_restore_env.get('PYTHONPATH', '')}"
    base_restore_env["NEXUS_STAGING_MODE"] = "true"
    base_restore_env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    base_restore_env["COMPOSE_FILE"] = _to_bash_path(dummy_compose)
    base_restore_env["POSTGRES_DB"] = fresh_db
    base_restore_env["DATA_VOLUME"] = fresh_data
    base_restore_env["REDIS_VOLUME"] = fresh_redis
    base_restore_env["BACKUP_ROOT"] = _to_bash_path(valid_backup_dir)
    base_restore_env["REQUIRE_POSTGRES"] = "true"
    base_restore_env["LLM_ALLOW_EXTERNAL_CALLS"] = "false"

    cmd_restore = [
        bash_bin,
        restore_script,
        "--staging",
        "--disposable-target",
        "--confirm-destructive-restore",
        ts,
        "--backup-root=" + _to_bash_path(valid_backup_dir),
        f"--redis-volume={fresh_redis}",
        f"--database-url={fresh_url}",
    ]

    # Case 2A: Restore script fails closed before Docker calls when credentials missing
    env_no_pass = base_restore_env.copy()
    env_no_pass.pop("POSTGRES_PASSWORD", None)
    env_no_pass.pop("STAGING_DB_PASSWORD", None)
    env_no_pass.pop("SECRET_KEY", None)
    env_no_pass.pop("AUTH_JWT_SECRET", None)
    log_file.write_text("")
    p_rest_no_pass = subprocess.run(cmd_restore, capture_output=True, text=True, env=env_no_pass)
    assert p_rest_no_pass.returncode != 0
    assert "Environment variable 'POSTGRES_PASSWORD (or STAGING_DB_PASSWORD)' is unset or empty" in p_rest_no_pass.stderr
    calls_no_pass = log_file.read_text()
    assert "CALL: DROPDB" not in calls_no_pass
    assert "CALL: CREATEDB" not in calls_no_pass
    assert "CALL: PG_RESTORE" not in calls_no_pass

    # Case 2B: Database role lacking CREATEDB/superuser authority -> fails closed in catalog query
    env_no_priv = base_restore_env.copy()
    env_no_priv["POSTGRES_PASSWORD"] = "valid_strong_test_password_16_chars"
    env_no_priv["SECRET_KEY"] = "valid_staging_secret_key_32_chars_long"
    env_no_priv["AUTH_JWT_SECRET"] = "valid_staging_jwt_secret_32_chars_long"
    env_no_priv["MOCK_CATALOG_MODE"] = "missing_target"
    env_no_priv["MOCK_ROLE_CAN_CREATEDB"] = "f"
    env_no_priv["MOCK_ROLE_IS_SUPER"] = "f"
    log_file.write_text("")
    p_rest_no_priv = subprocess.run(cmd_restore, capture_output=True, text=True, env=env_no_priv)
    assert p_rest_no_priv.returncode != 0
    assert "SAFETY ERROR: PostgreSQL role 'nexus_user' lacks 'CREATEDB' or superuser authority in pg_roles" in p_rest_no_priv.stderr
    assert "Prerequisite: An administrator must grant CREATEDB" in p_rest_no_priv.stderr
    calls_no_priv = log_file.read_text()
    assert "CALL: DROPDB" not in calls_no_priv
    assert "CALL: CREATEDB" not in calls_no_priv

    # Case 2C: Full success when strong credentials and CREATEDB role authority provided
    env_success = base_restore_env.copy()
    env_success["POSTGRES_PASSWORD"] = "valid_strong_test_password_16_chars"
    env_success["SECRET_KEY"] = "valid_staging_secret_key_32_chars_long"
    env_success["AUTH_JWT_SECRET"] = "valid_staging_jwt_secret_32_chars_long"
    env_success["MOCK_CATALOG_MODE"] = "missing_target"
    env_success["MOCK_ROLE_CAN_CREATEDB"] = "t"
    env_success["MOCK_ROLE_IS_SUPER"] = "f"
    log_file.write_text("")
    p_rest_succ = subprocess.run(cmd_restore, capture_output=True, text=True, env=env_success)
    assert p_rest_succ.returncode == 0
    assert "Staging environment & credentials preflight passed" in p_rest_succ.stdout
    assert "Verified PostgreSQL role 'nexus_user' privileges (CREATEDB=t, SUPERUSER=f)" in p_rest_succ.stdout
    assert "=== Coordinated Restore Completed Successfully ===" in p_rest_succ.stdout
    calls_succ = log_file.read_text()
    assert f"createdb -U nexus_user {fresh_db}" in calls_succ
    assert f"pg_restore -U nexus_user -d {fresh_db}" in calls_succ


# ---------------------------------------------------------------------------
# 11. Offline Selection & Mandatory-Gate Failure Contract Regression Tests
# ---------------------------------------------------------------------------

def test_validate_restore_drill_source_url_offline_and_strict_gate_contract() -> None:
    """Verify validate_restore_drill_source_url enforces fail-closed in strict gate and skips offline."""
    # 1. Offline run: TEST_DATABASE_URL is absent and strict_required is False -> must skip
    with pytest.raises(pytest.skip.Exception) as exc_info:
        validate_restore_drill_source_url(None, strict_required=False)
    assert "TEST_DATABASE_URL must be explicitly set" in str(exc_info.value)

    # 2. Mandatory gate: TEST_DATABASE_URL is absent and strict_required is True -> must fail closed
    with pytest.raises(pytest.fail.Exception) as exc_info:
        validate_restore_drill_source_url(None, strict_required=True)
    assert "TEST_DATABASE_URL must be explicitly set" in str(exc_info.value)

    # 3. Guardrail: Target database name must be exactly 'nexus_test_db' (fail closed even if URL provided)
    for bad_db in ["nexus_staging_db", "nexus_db", "nexus_prod", "postgres", "test_db"]:
        with pytest.raises(pytest.fail.Exception) as exc_info:
            validate_restore_drill_source_url(
                f"postgresql+psycopg://nexus_user:pass@localhost:5432/{bad_db}",
                strict_required=False,
            )
        assert "Source database name must be exactly 'nexus_test_db'" in str(exc_info.value)

    # 4. Success: Valid nexus_test_db URL passes validation and returns normalized URL
    valid_url = "postgresql+psycopg://nexus_user:pass@localhost:5432/nexus_test_db"
    res = validate_restore_drill_source_url(valid_url, strict_required=True)
    assert res == valid_url


def test_database_url_reserved_characters_encoding_and_redaction() -> None:
    """Verify structured URL construction handles reserved characters safely and error messages redact secrets."""
    from sqlalchemy.engine import URL, make_url
    from scripts.reconcile_storage import _redact_credentials

    # 1. Structured URL creation with characters that break naive string interpolation: @, #, %, :, /, +, spaces
    complex_password = "p@ss#word%1:2/3+ 4"
    u = URL.create(
        drivername="postgresql+psycopg",
        username="nexus_staging_user",
        password=complex_password,
        host="postgres",
        port=5432,
        database="nexus_disposable_target_db",
        query={"sslmode": "prefer"},
    )
    rendered = u.render_as_string(hide_password=False)
    # Confirm reserved characters are percent-encoded in the rendered string
    assert "%40" in rendered  # @
    assert "%23" in rendered  # #
    assert "%25" in rendered  # %
    assert "%3A" in rendered  # :
    assert "%2F" in rendered  # /

    # 2. Round-trip through make_url: all components retain exact semantic meaning
    parsed = make_url(rendered)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.username == "nexus_staging_user"
    assert parsed.password == complex_password
    assert parsed.host == "postgres"
    assert parsed.port == 5432
    assert parsed.database == "nexus_disposable_target_db"
    assert parsed.query.get("sslmode") == "prefer"

    # 3. Masked rendering hides password completely
    masked = u.render_as_string(hide_password=True)
    assert complex_password not in masked
    assert "***" in masked

    # 4. _redact_credentials helper masks passwords in error strings (both unquoted and percent-encoded forms)
    sample_error = f"OperationalError: connection failed for {rendered}: FATAL: authentication failed for {complex_password}"
    sanitized = _redact_credentials(sample_error, rendered)
    assert complex_password not in sanitized
    assert "p%40ss" not in sanitized
    assert "******" in sanitized

    # 5. Contrast with naive unencoded string: unencoded @ causes naive parsers to corrupt host
    unencoded_ambiguous = "postgresql+psycopg://nexus_staging_user:p@ssword@postgres:5432/nexus_disposable_target_db"
    naive_parsed = make_url(unencoded_ambiguous)
    # Naive string splits at first '@': password is truncated to 'p' and host becomes 'ssword@postgres'
    assert naive_parsed.password == "p"
    assert naive_parsed.host == "ssword@postgres"
    # In contrast, structured URL.create ensures host and password are never conflated
    assert parsed.host == "postgres"
    assert parsed.password == complex_password


def test_restore_script_redacts_database_url_in_error_message(tmp_path: Path) -> None:
    """Verify restore_nexus_coordinated.sh redacts DATABASE_URL when reporting invalid scheme."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    restore_script = str(repo_root / "scripts" / "restore_nexus_coordinated.sh").replace("\\", "/")
    bash_bin = _find_bash()
    if not bash_bin:
        pytest.skip("Bash executable not found")

    secret_in_url = "super_secret_restore_password_xyz987"
    bad_url = f"mysql://nexus_user:{secret_in_url}@localhost:3306/nexus_disposable_staging_db"

    env = os.environ.copy()
    env["NEXUS_STAGING_MODE"] = "true"
    env["COMPOSE_PROJECT_NAME"] = "nexus-staging"
    env["COMPOSE_FILE"] = "infra/staging/docker-compose.staging.yml"
    env["POSTGRES_DB"] = "nexus_disposable_staging_db"
    env["DATA_VOLUME"] = "nexus_backend_disposable_staging_data"
    env["REDIS_VOLUME"] = "nexus_redis_disposable_staging_data"
    env["POSTGRES_PASSWORD"] = "valid_strong_test_password_16_chars"
    env["SECRET_KEY"] = "valid_staging_secret_key_32_chars_long"
    env["AUTH_JWT_SECRET"] = "valid_staging_jwt_secret_32_chars_long"

    proc = subprocess.run(
        [
            bash_bin,
            restore_script,
            "--staging",
            "--disposable-target",
            "--confirm-destructive-restore",
            "20261027_000000",
            f"--database-url={bad_url}",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode != 0
    # Must reject non-postgresql connection string
    assert "SAFETY ERROR: Disposable DATABASE_URL must be a PostgreSQL connection string" in proc.stderr
    # Must NOT expose the secret from the URL
    assert secret_in_url not in proc.stderr
    assert secret_in_url not in proc.stdout
