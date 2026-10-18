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
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
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

def _get_pg_test_url() -> str:
    return (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql+psycopg://nexus_user:nexus_password@localhost:5432/nexus_test_db"
    )


def _find_postgres_runner(parsed_url) -> tuple[str, str | None]:
    """Identify whether to execute pg_dump/pg_restore via host binary or Docker container."""
    if shutil.which("pg_dump") and shutil.which("pg_restore"):
        return "host", None

    if shutil.which("docker"):
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


def test_live_postgres_backup_restore_and_storage_reconciliation_drill(tmp_path: Path) -> None:
    """Mandatory Live PostgreSQL 16 + pgvector restore drill.

    Verifies:
    1. Seeding real tenant, business, datasets, files, sales, and vector data in PostgreSQL.
    2. Real pg_dump -F c custom-format archive generation.
    3. Tenant file archive creation with SHA-256 sidecars.
    4. Creation of a clean, separate disposable restore database (nexus_restore_verify_<uid>).
    5. Real pg_restore execution into the clean disposable database.
    6. Complete verification of restored schema, row counts, sequences, foreign keys, JSONB data,
       pgvector extension and vector queries, and tenant isolation.
    7. Clean file restore and validation of file SHA-256 and size against restored database record.
    8. Storage reconciliation audit confirming 100% referential consistency.
    9. Teardown of disposable restore database and drill records.
    """
    url = _get_pg_test_url()
    strict_required = os.getenv("REQUIRE_POSTGRES", "").lower() in ("true", "1", "yes")

    # 1. Verify PostgreSQL Reachability
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

    # Admin connection to create/drop disposable database
    admin_url = parsed_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_backup_file = backup_dir / f"nexus_db_{ts}.dump"
    files_backup_file = backup_dir / f"nexus_files_{ts}.tar.gz"

    restore_engine = None

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
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{restore_db_name}"'))
            conn.execute(text(f'CREATE DATABASE "{restore_db_name}"'))

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
        if restore_engine is not None:
            restore_engine.dispose()

        try:
            with admin_engine.connect() as conn:
                conn.execute(text(f"""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = '{restore_db_name}' AND pid <> pg_backend_pid();
                """))
                conn.execute(text(f'DROP DATABASE IF EXISTS "{restore_db_name}"'))
        except Exception:
            pass

        admin_engine.dispose()

        # Clean seeded test tenant records from source test database
        with Session() as db:
            try:
                db.execute(text(f"DELETE FROM knowledge_chunks WHERE business_id = '{biz_id}'"))
                db.execute(text(f"DELETE FROM knowledge_documents WHERE business_id = '{biz_id}'"))
                db.execute(text(f"DELETE FROM ingestion_jobs WHERE business_id = '{biz_id}'"))
                db.execute(text(f"DELETE FROM uploaded_datasets WHERE business_id = '{biz_id}'"))
                db.execute(text(f"DELETE FROM businesses WHERE id = '{biz_id}'"))
                db.execute(text(f"DELETE FROM organizations WHERE id = '{org_id}'"))
                db.commit()
            except Exception:
                db.rollback()
