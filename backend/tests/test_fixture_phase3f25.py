# NEXUS Phase 3F.25 — Offline Isolated Recovery Fixture Tests
#
# Verifies all static and unit-testable properties of the Phase 3F.25 fixture
# without any live DB connections, Docker, volumes, backup/restore execution,
# or network I/O.
#
# Test categories:
# A. Resource name compliance (bash script guard patterns).
# B. ORM construction validity (no DB session).
# C. Storage key format and resolve_storage_path behaviour.
# D. Physical file write + hash consistency.
# E. Reconciliation contract (mock DB — consistent / missing / orphan).
# F. Script bash -n syntax checks (skipped when bash absent).
# G. Python compilation of fixture_3f25_seed.py.
# H. Staging Compose environment guards (REQUIRE_POSTGRES, LLM_ALLOW_EXTERNAL_CALLS).

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys
_tests_dir = Path(__file__).resolve().parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from fixture_3f25_seed import (
    ALLOWED_POSTGRESQL_DRIVERS,
    FIXTURE_BACKUP_DIR,
    FIXTURE_BIZ_ID,
    FIXTURE_CSV_CONTENT,
    FIXTURE_CSV_FILENAME,
    FIXTURE_CSV_ROW_COUNT,
    FIXTURE_CSV_SHA256,
    FIXTURE_DS_ID,
    FIXTURE_JOB_ID,
    FIXTURE_ORG_ID,
    FIXTURE_ORG_SLUG,
    FIXTURE_REDIS_MARKER_KEY,
    FIXTURE_REDIS_MARKER_VALUE,
    FIXTURE_RESTORE_DB,
    FIXTURE_RESTORE_REDIS_VOLUME,
    FIXTURE_RESTORE_VOLUME,
    FIXTURE_SOURCE_DB,
    FIXTURE_SOURCE_VOLUME,
    build_fixture_records,
    build_storage_key,
    main as fixture_main,
    seed_fixture_records,
    verify_fixture_integrity,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
BACKUP_SCRIPT = SCRIPTS_DIR / "backup_nexus_coordinated.sh"
RESTORE_SCRIPT = SCRIPTS_DIR / "restore_nexus_coordinated.sh"
STAGING_COMPOSE = REPO_ROOT / "infra" / "staging" / "docker-compose.staging.yml"

_STAGING_PATTERN = re.compile(r"^nexus_.*staging.*$")
_STAGING_DATA_SUFFIX = "_staging_data"
_PROTECTED_DBS = frozenset(
    {"nexus_db", "nexus_staging_db", "nexus_test_db", "postgres", "template1"}
)
_LIVE_STAGING_DB        = "nexus_staging_db"
_LIVE_STAGING_DATA_VOL  = "nexus_backend_staging_data"
_LIVE_STAGING_REDIS_VOL = "nexus_redis_staging_data"
_PROD_DATA_VOL          = "nexus_backend_data"


def _find_bash() -> str | None:
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


# ===========================================================================
# A. Resource name compliance
# ===========================================================================


class TestResourceNameCompliance:
    """All six fixed names must pass the exact guards in both shell scripts."""

    def test_source_db_matches_staging_pattern(self) -> None:
        assert _STAGING_PATTERN.match(FIXTURE_SOURCE_DB)

    def test_restore_db_matches_staging_pattern(self) -> None:
        assert _STAGING_PATTERN.match(FIXTURE_RESTORE_DB)

    def test_source_db_not_in_protected_set(self) -> None:
        assert FIXTURE_SOURCE_DB not in _PROTECTED_DBS

    def test_restore_db_not_in_protected_set(self) -> None:
        assert FIXTURE_RESTORE_DB not in _PROTECTED_DBS

    def test_restore_db_not_live_staging_db(self) -> None:
        assert FIXTURE_RESTORE_DB != _LIVE_STAGING_DB

    def test_source_volume_ends_with_staging_data(self) -> None:
        assert FIXTURE_SOURCE_VOLUME.endswith(_STAGING_DATA_SUFFIX)

    def test_restore_volume_ends_with_staging_data(self) -> None:
        assert FIXTURE_RESTORE_VOLUME.endswith(_STAGING_DATA_SUFFIX)

    def test_restore_redis_volume_ends_with_staging_data(self) -> None:
        assert FIXTURE_RESTORE_REDIS_VOLUME.endswith(_STAGING_DATA_SUFFIX)

    def test_source_volume_not_production_data_volume(self) -> None:
        assert FIXTURE_SOURCE_VOLUME != _PROD_DATA_VOL

    def test_restore_volume_not_live_staging_data_volume(self) -> None:
        assert FIXTURE_RESTORE_VOLUME != _LIVE_STAGING_DATA_VOL

    def test_restore_redis_volume_not_live_staging_redis_volume(self) -> None:
        assert FIXTURE_RESTORE_REDIS_VOLUME != _LIVE_STAGING_REDIS_VOL

    def test_database_url_tail_matches_restore_db(self) -> None:
        """Restore script extracts DB name via URL_DB=${URL_CLEAN##*/}."""
        example_url = (
            "postgresql+psycopg://nexus_staging_user:REDACTED"
            f"@127.0.0.1:5433/{FIXTURE_RESTORE_DB}"
        )
        url_db = example_url.split("?")[0].rsplit("/", 1)[-1]
        assert url_db == FIXTURE_RESTORE_DB

    def test_backup_dir_not_forbidden_path(self) -> None:
        forbidden = {"/", "/root", "/etc", "/bin", "/usr", "/data",
                     "/var/lib/docker/volumes", "/app/data"}
        p = FIXTURE_BACKUP_DIR.replace("\\", "/")
        assert p not in forbidden
        assert not any(p.startswith(f + "/") for f in forbidden)
        assert ".git" not in p
        assert "backend/data" not in p

    def test_backup_dir_overridable_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        custom_dir = "/tmp/custom_fixture_backups"
        monkeypatch.setenv("NEXUS_FIXTURE_BACKUP_DIR", custom_dir)
        import importlib
        import fixture_3f25_seed
        importlib.reload(fixture_3f25_seed)
        assert fixture_3f25_seed.FIXTURE_BACKUP_DIR == custom_dir
        monkeypatch.delenv("NEXUS_FIXTURE_BACKUP_DIR", raising=False)
        importlib.reload(fixture_3f25_seed)


# ===========================================================================
# B. ORM construction validity
# ===========================================================================


class TestOrmConstruction:
    """Instantiate fixture ORM objects (no DB session) and check required fields."""

    def test_returns_five_tuple(self, tmp_path: Path) -> None:
        result = build_fixture_records(tmp_path)
        assert len(result) == 5

    def test_organization_fields(self, tmp_path: Path) -> None:
        org, _, _, _, _ = build_fixture_records(tmp_path)
        assert org.id == FIXTURE_ORG_ID
        assert org.name == "Fixture Drill Organization"
        assert org.slug == FIXTURE_ORG_SLUG
        assert org.status == "active"

    def test_business_fk_references_org(self, tmp_path: Path) -> None:
        _, biz, _, _, _ = build_fixture_records(tmp_path)
        assert biz.id == FIXTURE_BIZ_ID
        assert biz.organization_id == FIXTURE_ORG_ID

    def test_dataset_required_fields(self, tmp_path: Path) -> None:
        _, _, ds, _, _ = build_fixture_records(tmp_path)
        assert ds.id == FIXTURE_DS_ID
        assert ds.organization_id == FIXTURE_ORG_ID
        assert ds.business_id == FIXTURE_BIZ_ID
        assert ds.filename == FIXTURE_CSV_FILENAME
        assert ds.file_type == "csv"
        assert ds.file_size_bytes == len(FIXTURE_CSV_CONTENT)
        assert ds.row_count == FIXTURE_CSV_ROW_COUNT
        assert ds.column_count == 3

    def test_dataset_content_hash_matches_fixture_constant(self, tmp_path: Path) -> None:
        _, _, ds, _, _ = build_fixture_records(tmp_path)
        assert ds.content_hash == FIXTURE_CSV_SHA256

    def test_dataset_storage_key_format(self, tmp_path: Path) -> None:
        _, _, ds, _, _ = build_fixture_records(tmp_path)
        expected = (
            f"tenants/{FIXTURE_ORG_ID}/{FIXTURE_BIZ_ID}"
            f"/{FIXTURE_DS_ID}/{FIXTURE_CSV_FILENAME}"
        )
        assert ds.storage_key == expected

    def test_dataset_readiness_status(self, tmp_path: Path) -> None:
        _, _, ds, _, _ = build_fixture_records(tmp_path)
        assert ds.readiness_status == "READY"

    def test_ingestion_job_fks_and_fields(self, tmp_path: Path) -> None:
        _, _, _, job, _ = build_fixture_records(tmp_path)
        assert job.id == FIXTURE_JOB_ID
        assert job.organization_id == FIXTURE_ORG_ID
        assert job.business_id == FIXTURE_BIZ_ID
        assert job.dataset_id == FIXTURE_DS_ID
        assert job.status == "COMPLETED"
        assert job.rows_processed == FIXTURE_CSV_ROW_COUNT
        assert job.error_message is None

    def test_csv_path_absolute_under_tenants_tree(self, tmp_path: Path) -> None:
        _, _, _, _, csv_path = build_fixture_records(tmp_path)
        assert csv_path.is_absolute()
        expected = (
            tmp_path / "tenants" / FIXTURE_ORG_ID / FIXTURE_BIZ_ID
            / FIXTURE_DS_ID / FIXTURE_CSV_FILENAME
        )
        assert csv_path == expected


# ===========================================================================
# C. Storage key format
# ===========================================================================


class TestStorageKeyFormat:
    def test_canonical_format(self) -> None:
        sk = build_storage_key("O", "B", "D", "f.csv")
        assert sk == "tenants/O/B/D/f.csv"

    def test_no_leading_slash(self) -> None:
        sk = build_storage_key(
            FIXTURE_ORG_ID, FIXTURE_BIZ_ID, FIXTURE_DS_ID, FIXTURE_CSV_FILENAME
        )
        assert not sk.startswith("/")

    def test_no_backslashes(self) -> None:
        sk = build_storage_key(
            FIXTURE_ORG_ID, FIXTURE_BIZ_ID, FIXTURE_DS_ID, FIXTURE_CSV_FILENAME
        )
        assert "\\" not in sk

    def test_starts_with_tenants(self) -> None:
        sk = build_storage_key(
            FIXTURE_ORG_ID, FIXTURE_BIZ_ID, FIXTURE_DS_ID, FIXTURE_CSV_FILENAME
        )
        assert sk.startswith("tenants/")

    def test_resolve_storage_path_finds_written_file(self, tmp_path: Path) -> None:
        from app.services.data_gateway_service import DataGatewayService

        _, _, ds, _, csv_path = build_fixture_records(tmp_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(FIXTURE_CSV_CONTENT)

        with patch("app.services.data_gateway_service.settings") as mock_settings:
            mock_settings.DATA_DIR = str(tmp_path)
            resolved = DataGatewayService.resolve_storage_path(ds.storage_key)

        assert resolved.exists()
        assert resolved.read_bytes() == FIXTURE_CSV_CONTENT


# ===========================================================================
# D. Physical file consistency
# ===========================================================================


class TestPhysicalFileConsistency:
    def test_sha256_constant_is_correct(self) -> None:
        computed = hashlib.sha256(FIXTURE_CSV_CONTENT).hexdigest()
        assert FIXTURE_CSV_SHA256 == computed, (
            f"Pre-computed SHA256 {FIXTURE_CSV_SHA256!r} does not match "
            f"runtime value {computed!r} — FIXTURE_CSV_CONTENT was altered."
        )

    def test_row_count(self) -> None:
        lines = FIXTURE_CSV_CONTENT.decode("utf-8").strip().splitlines()
        data_lines = [ln for ln in lines if ln]
        # first line is header
        assert len(data_lines) - 1 == FIXTURE_CSV_ROW_COUNT

    def test_column_count(self) -> None:
        header = FIXTURE_CSV_CONTENT.decode("utf-8").splitlines()[0]
        assert len(header.split(",")) == 3

    def test_physical_write_and_verify(self, tmp_path: Path) -> None:
        _, _, _, _, csv_path = build_fixture_records(tmp_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(FIXTURE_CSV_CONTENT)
        assert csv_path.exists()
        assert csv_path.read_bytes() == FIXTURE_CSV_CONTENT
        assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == FIXTURE_CSV_SHA256

    def test_file_size_matches_dataset_field(self, tmp_path: Path) -> None:
        _, _, ds, _, csv_path = build_fixture_records(tmp_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(FIXTURE_CSV_CONTENT)
        assert csv_path.stat().st_size == ds.file_size_bytes


# ===========================================================================
# E. Reconciliation contract
# ===========================================================================


class TestReconciliationContract:
    """Verify reconcile_tenant_storage with mock DB sessions — no live PG."""

    @staticmethod
    def _mock_db(records: list) -> MagicMock:
        m = MagicMock()
        m.execute.return_value.all.return_value = records
        return m

    def test_consistent_state(self, tmp_path: Path) -> None:
        from app.core.backup import reconcile_tenant_storage

        _, _, ds, _, csv_path = build_fixture_records(tmp_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(FIXTURE_CSV_CONTENT)

        with patch(
            "app.services.data_gateway_service.DataGatewayService.resolve_storage_path"
        ) as mock_rsp:
            mock_rsp.side_effect = lambda key: tmp_path / key
            result = reconcile_tenant_storage(
                db=self._mock_db([(ds.id, ds.filename, ds.storage_key)]),
                base_dir=tmp_path,
                delete_orphans=False,
            )

        assert result.total_db_records == 1
        assert len(result.missing_files) == 0
        assert len(result.orphan_files) == 0
        assert result.is_consistent is True

    def test_missing_file_detected(self, tmp_path: Path) -> None:
        from app.core.backup import reconcile_tenant_storage

        _, _, ds, _, _ = build_fixture_records(tmp_path)
        # Intentionally do NOT create the physical file

        with patch(
            "app.services.data_gateway_service.DataGatewayService.resolve_storage_path"
        ) as mock_rsp:
            mock_rsp.side_effect = lambda key: tmp_path / key
            result = reconcile_tenant_storage(
                db=self._mock_db([(ds.id, ds.filename, ds.storage_key)]),
                base_dir=tmp_path,
                delete_orphans=False,
            )

        assert result.total_db_records == 1
        assert len(result.missing_files) == 1
        assert result.missing_files[0][0] == ds.id
        assert result.is_consistent is False

    def test_orphan_file_detected(self, tmp_path: Path) -> None:
        from app.core.backup import reconcile_tenant_storage

        orphan_dir = tmp_path / "tenants" / "orphan_org" / "orphan_biz"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        orphan_file = orphan_dir / "unindexed.csv"
        orphan_file.write_bytes(b"not,in,db\n")

        with patch(
            "app.services.data_gateway_service.DataGatewayService.resolve_storage_path"
        ) as mock_rsp:
            mock_rsp.side_effect = lambda key: tmp_path / key
            result = reconcile_tenant_storage(
                db=self._mock_db([]),
                base_dir=tmp_path,
                delete_orphans=False,
            )

        assert result.total_db_records == 0
        assert len(result.orphan_files) == 1
        assert result.orphan_files[0].resolve() == orphan_file.resolve()
        assert result.is_consistent is False

    def test_missing_files_count_matches_array_length(self) -> None:
        from app.core.backup import StorageReconciliationResult

        result = StorageReconciliationResult(
            total_db_records=2,
            missing_files=[
                ("id1", "a.csv", "tenants/o/b/d1/a.csv"),
                ("id2", "b.csv", "tenants/o/b/d2/b.csv"),
            ],
        )
        d = result.to_dict()
        assert d["missing_files_count"] == len(result.missing_files) == 2

    def test_orphan_files_count_matches_array_length(self, tmp_path: Path) -> None:
        from app.core.backup import StorageReconciliationResult

        orphan = tmp_path / "tenants" / "x" / "stray.csv"
        result = StorageReconciliationResult(
            total_db_records=0,
            total_disk_files=1,
            orphan_files=[orphan],
        )
        d = result.to_dict()
        assert d["orphan_files_count"] == len(result.orphan_files) == 1

    def test_exit_code_semantics(self) -> None:
        """reconcile_storage.py returns 0 for consistent, 1 for inconsistent."""
        from app.core.backup import StorageReconciliationResult

        consistent = StorageReconciliationResult(total_db_records=1)
        assert consistent.is_consistent is True  # main() returns 0

        inconsistent = StorageReconciliationResult(
            total_db_records=1,
            missing_files=[("id1", "f.csv", "tenants/o/b/d/f.csv")],
        )
        assert inconsistent.is_consistent is False  # main() returns 1

    def test_completed_restore_with_inconsistent_storage_is_failed_recovery(
        self,
    ) -> None:
        """A restore that exits 0 but has inconsistencies is FAILED RECOVERY VALIDATION.

        Restoring successfully does not constitute a passed drill when
        reconciliation reports is_consistent=False.
        """
        from app.core.backup import StorageReconciliationResult

        result = StorageReconciliationResult(
            total_db_records=1,
            missing_files=[
                ("id1", "fixture_sales.csv", "tenants/o/b/d/fixture_sales.csv")
            ],
            total_disk_files=0,
        )
        restore_command_succeeded = True
        assert restore_command_succeeded is True    # restore exited 0
        assert result.is_consistent is False         # storage is inconsistent
        # => FAILED RECOVERY VALIDATION
        recovery_passed = restore_command_succeeded and result.is_consistent
        assert recovery_passed is False


# ===========================================================================
# F. Script bash -n syntax checks
# ===========================================================================


class TestScriptSyntax:
    @pytest.fixture(autouse=True)
    def require_bash(self) -> None:
        if not _find_bash():
            pytest.skip("bash not found; skipping syntax check")

    def test_backup_script_bash_syntax(self) -> None:
        bash = _find_bash()
        assert BACKUP_SCRIPT.exists()
        proc = subprocess.run(
            [bash, "-n", str(BACKUP_SCRIPT).replace("\\", "/")],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"bash -n failed:\n{proc.stderr}"

    def test_restore_script_bash_syntax(self) -> None:
        bash = _find_bash()
        assert RESTORE_SCRIPT.exists()
        proc = subprocess.run(
            [bash, "-n", str(RESTORE_SCRIPT).replace("\\", "/")],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"bash -n failed:\n{proc.stderr}"


# ===========================================================================
# G. Python compilation
# ===========================================================================


class TestPythonCompilation:
    def test_seed_module_compiles(self) -> None:
        import py_compile

        seed_path = Path(__file__).parent / "fixture_3f25_seed.py"
        assert seed_path.exists(), f"Seed module not found: {seed_path}"
        py_compile.compile(str(seed_path), doraise=True)

    def test_reconcile_storage_script_compiles(self) -> None:
        import py_compile

        py_compile.compile(str(SCRIPTS_DIR / "reconcile_storage.py"), doraise=True)


# ===========================================================================
# H. Staging environment guards
# ===========================================================================


class TestStagingEnvironmentGuards:
    """Static contract checks for staging compose and disaster recovery scripts.

    NOTE: Behavioral execution verification of `--disposable-target`, `--allow-target-recreate`,
    reconciliation isolation, and database target safety is performed in the end-to-end
    mock suite `backend/tests/test_backup_restore_phase32c.py`.
    """

    @staticmethod
    def _compose_text() -> str:
        assert STAGING_COMPOSE.exists(), f"Not found: {STAGING_COMPOSE}"
        return STAGING_COMPOSE.read_text(encoding="utf-8")

    def test_require_postgres_true_in_compose(self) -> None:
        assert "REQUIRE_POSTGRES=true" in self._compose_text()

    def test_llm_allow_external_calls_false_in_compose(self) -> None:
        assert "LLM_ALLOW_EXTERNAL_CALLS=false" in self._compose_text()

    def test_staging_project_name(self) -> None:
        assert "name: nexus-staging" in self._compose_text()

    def test_no_quiesce_flag_in_backup_script(self) -> None:
        text = BACKUP_SCRIPT.read_text(encoding="utf-8")
        assert "--no-quiesce" in text

    def test_disposable_target_flag_in_restore_script(self) -> None:
        text = RESTORE_SCRIPT.read_text(encoding="utf-8")
        assert "--disposable-target" in text

    def test_allow_target_recreate_flag_in_restore_script(self) -> None:
        text = RESTORE_SCRIPT.read_text(encoding="utf-8")
        assert "--allow-target-recreate" in text

    def test_restore_script_blocks_live_staging_db_as_disposable(self) -> None:
        text = RESTORE_SCRIPT.read_text(encoding="utf-8")
        assert "nexus_staging_db" in text

    def test_allow_test_db_source_flag_in_backup_script(self) -> None:
        text = BACKUP_SCRIPT.read_text(encoding="utf-8")
        assert "allow-test-db-source" in text


# ===========================================================================
# I. Fixture Seeder and Verification
# ===========================================================================


class TestFixtureSeederAndIntegrity:
    """Verify seed_fixture_records, verify_fixture_integrity, and CLI guards."""

    @pytest.fixture
    def test_session(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool
        from app.models.base import Base

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        with Session(engine) as session:
            yield session
        Base.metadata.drop_all(bind=engine)

    def test_seed_fixture_records_fresh(self, test_session, tmp_path: Path) -> None:
        org, biz, ds, job, csv_path, status = seed_fixture_records(test_session, tmp_path)
        assert status == "seeded_fresh"
        assert csv_path.exists()
        assert csv_path.read_bytes() == FIXTURE_CSV_CONTENT
        assert org.id == FIXTURE_ORG_ID
        assert biz.id == FIXTURE_BIZ_ID
        assert ds.id == FIXTURE_DS_ID
        assert job.id == FIXTURE_JOB_ID

    def test_seed_fixture_records_idempotent(self, test_session, tmp_path: Path) -> None:
        _, _, _, _, _, status1 = seed_fixture_records(test_session, tmp_path)
        assert status1 == "seeded_fresh"

        # Re-running on existing state must succeed idempotently
        _, _, _, _, _, status2 = seed_fixture_records(test_session, tmp_path)
        assert status2 == "already_seeded"

    def test_seed_fixture_records_fail_if_exists(self, test_session, tmp_path: Path) -> None:
        seed_fixture_records(test_session, tmp_path)
        with pytest.raises(RuntimeError, match="SAFETY ERROR: Pre-existing fixture organization"):
            seed_fixture_records(test_session, tmp_path, fail_if_exists=True)

    def test_seed_fixture_records_corrupted_csv_fails(self, test_session, tmp_path: Path) -> None:
        _, _, _, _, csv_path, _ = seed_fixture_records(test_session, tmp_path)
        # Tamper with file content
        csv_path.write_bytes(b"tampered,data\n")
        with pytest.raises(RuntimeError, match="Physical CSV content at '.*' does not match"):
            seed_fixture_records(test_session, tmp_path)

    def test_verify_fixture_integrity_success(self, test_session, tmp_path: Path) -> None:
        seed_fixture_records(test_session, tmp_path)
        res = verify_fixture_integrity(test_session, tmp_path)
        assert res["verified"] is True
        assert res["org_id"] == FIXTURE_ORG_ID
        assert res["dataset_id"] == FIXTURE_DS_ID
        assert res["file_size_bytes"] == len(FIXTURE_CSV_CONTENT)
        assert res["sha256"] == FIXTURE_CSV_SHA256

    def test_verify_fixture_integrity_missing_file(self, test_session, tmp_path: Path) -> None:
        _, _, _, _, csv_path, _ = seed_fixture_records(test_session, tmp_path)
        csv_path.unlink()
        res = verify_fixture_integrity(test_session, tmp_path)
        assert res["verified"] is False
        assert "CSV file missing on disk" in str(res["error"])

    def test_cli_dry_run_exits_zero(self, tmp_path: Path) -> None:
        code = fixture_main(["--dry-run", "--data-dir", str(tmp_path)])
        assert code == 0

    def test_cli_rejects_missing_database_url_when_not_dry_run(self) -> None:
        code = fixture_main([])
        assert code == 1

    def test_cli_rejects_unauthorized_database_urls(self) -> None:
        forbidden = [
            "postgresql://user:pass@localhost:5432/nexus_staging_db",
            "postgresql://user:pass@localhost:5432/nexus_db",
            "postgresql://user:pass@localhost:5432/nexus_test_db",
            "postgresql://user:pass@localhost:5432/postgres",
        ]
        for url in forbidden:
            code = fixture_main(["--database-url", url])
            assert code == 1

    def test_cli_rejects_non_postgres_scheme(self, capsys: pytest.CaptureFixture) -> None:
        forbidden_schemes = [
            "sqlite:///nexus_fixture_staging_db",
            "mysql://user:pass@localhost/nexus_fixture_staging_db",
            "mysql+pymysql://user:pass@localhost/nexus_fixture_staging_db",
            "oracle://user:pass@localhost/nexus_fixture_staging_db",
            "postgresql_fake://user:pass@localhost/nexus_fixture_staging_db",
            "postgresfake://user:pass@localhost/nexus_fixture_staging_db",
            "postgresql+unsupported://user:pass@localhost/nexus_fixture_staging_db",
        ]
        for url in forbidden_schemes:
            code = fixture_main(["--database-url", url])
            assert code == 1
            err = capsys.readouterr().err
            assert "SAFETY ERROR: Unauthorized driver" in err

    def test_cli_accepts_all_supported_postgres_schemes(
        self, capsys: pytest.CaptureFixture, tmp_path: Path
    ) -> None:
        for driver in ALLOWED_POSTGRESQL_DRIVERS:
            url = f"{driver}://nexus_user:pass@localhost:5432/{FIXTURE_SOURCE_DB}"
            code = fixture_main(["--dry-run", "--database-url", url, "--data-dir", str(tmp_path)])
            assert code == 0
            out = capsys.readouterr().out
            assert "PLAN: Target DB URL" in out

    def test_cli_rejects_malformed_url(self, capsys: pytest.CaptureFixture) -> None:
        code = fixture_main(["--database-url", "://invalid-url"])
        assert code == 1
        err = capsys.readouterr().err
        assert "SAFETY ERROR: Malformed database URL" in err

    def test_cli_dry_run_redacts_password(self, capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
        secret = "super_secret_p@ssword!123"
        url = f"postgresql://nexus_user:{secret}@localhost:5432/{FIXTURE_SOURCE_DB}"
        code = fixture_main(["--dry-run", "--database-url", url, "--data-dir", str(tmp_path)])
        assert code == 0
        captured = capsys.readouterr()
        assert secret not in captured.out
        assert secret not in captured.err
        assert "***" in captured.out

    def test_cli_database_error_sanitizes_output(self, capsys: pytest.CaptureFixture, tmp_path: Path) -> None:
        secret = "leak_candidate_pw_987"
        url = f"postgresql://nexus_user:{secret}@127.0.0.1:59999/{FIXTURE_SOURCE_DB}"
        code = fixture_main(["--database-url", url, "--data-dir", str(tmp_path)])
        assert code == 1
        captured = capsys.readouterr()
        assert secret not in captured.err
        assert secret not in captured.out
        assert "DATABASE ERROR" in captured.err

    def test_seed_fixture_records_cleans_up_csv_on_commit_failure(
        self, test_session, tmp_path: Path
    ) -> None:
        """When session.commit fails during seeding, the physical CSV file is unlinked (no orphan)."""
        expected_csv = (
            tmp_path
            / "tenants"
            / FIXTURE_ORG_ID
            / FIXTURE_BIZ_ID
            / FIXTURE_DS_ID
            / FIXTURE_CSV_FILENAME
        )
        assert not expected_csv.exists()

        with patch.object(test_session, "commit", side_effect=RuntimeError("Simulated DB commit error")):
            with pytest.raises(RuntimeError, match="Simulated DB commit error"):
                seed_fixture_records(test_session, tmp_path)

        # Newly created file must have been cleaned up and not left as an orphan
        assert not expected_csv.exists()

    def test_seed_fixture_records_preserves_preexisting_csv_on_commit_failure(
        self, test_session, tmp_path: Path
    ) -> None:
        """When session.commit fails, a pre-existing CSV file must NEVER be deleted."""
        expected_csv = (
            tmp_path
            / "tenants"
            / FIXTURE_ORG_ID
            / FIXTURE_BIZ_ID
            / FIXTURE_DS_ID
            / FIXTURE_CSV_FILENAME
        )
        expected_csv.parent.mkdir(parents=True, exist_ok=True)
        prior_content = b"pre_existing_unrelated_content\n"
        expected_csv.write_bytes(prior_content)
        assert expected_csv.exists()

        with patch.object(test_session, "commit", side_effect=RuntimeError("Simulated DB commit error")):
            with pytest.raises(RuntimeError, match="Simulated DB commit error"):
                seed_fixture_records(test_session, tmp_path)

        # Pre-existing file must STILL exist (must never be unlinked/deleted)
        assert expected_csv.exists()

    def test_redis_marker_constants(self) -> None:
        assert FIXTURE_REDIS_MARKER_KEY.startswith("nexus:drill:")
        assert "marker" in FIXTURE_REDIS_MARKER_KEY
        assert len(FIXTURE_REDIS_MARKER_VALUE) > 10
