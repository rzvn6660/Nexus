"""Tests for Phase 31B Step 1: Persistent Storage, Path Isolation, and Data Durability.

Covers:
1. Docker Compose and Dockerfile production persistent volume contract (nexus_backend_data mounted at /app/data).
2. Tenant and business workspace path isolation.
3. Filename sanitization and path traversal prevention.
4. File creation and read-back under configured storage roots (DATA_DIR).
5. Missing storage file behavior (HTTP 404 with descriptive error).
6. Unwritable storage directory failure safety (HTTP 500, no orphaned DB record).
7. Preservation of canonical storage_key format.
"""

import io
import re
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import yaml
from app.core.config import settings
from app.models.base import Base
from app.models.tenant import Business, Organization, UploadedDataset
from app.services.data_gateway_service import DataGatewayService
from app.services.tenant_data_service import TenantDataService


@pytest.fixture
def test_db():
    """In-memory SQLite session with all tables created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_org_and_business(test_db: Session):
    """Create a sample organization and business for testing."""
    org_id = str(uuid4())
    org = Organization(
        id=org_id,
        name="Durability Test Org",
        slug=f"durability-org-{org_id[:8]}",
        status="active",
    )
    test_db.add(org)
    test_db.flush()

    biz_id = str(uuid4())
    biz = Business(
        id=biz_id,
        organization_id=org_id,
        name="Durability Test Store",
        industry="Retail",
        currency="USD",
    )
    test_db.add(biz)
    test_db.commit()
    return org, biz


# ==============================================================================
# 1. PRODUCTION DOCKER & VOLUME CONFIGURATION TESTS
# ==============================================================================


def test_production_compose_volume_configuration():
    """Verify docker-compose.prod.yml declares nexus_backend_data volume and mounts it at /app/data."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    compose_path = repo_root / "docker-compose.prod.yml"
    assert compose_path.exists(), f"Missing docker-compose.prod.yml at {compose_path}"

    with open(compose_path, "r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)

    # Verify top-level volumes include nexus_backend_data
    assert "volumes" in compose, "docker-compose.prod.yml missing top-level 'volumes' section"
    assert "nexus_backend_data" in compose["volumes"], (
        "docker-compose.prod.yml must declare 'nexus_backend_data' in top-level volumes"
    )
    assert compose["volumes"]["nexus_backend_data"]["driver"] == "local"

    # Verify backend service volume mount
    assert "services" in compose, "docker-compose.prod.yml missing 'services' section"
    backend_service = compose["services"].get("backend")
    assert backend_service is not None, "docker-compose.prod.yml missing 'backend' service"
    volumes = backend_service.get("volumes", [])
    assert any("nexus_backend_data:/app/data" in v for v in volumes), (
        f"Backend service must mount 'nexus_backend_data:/app/data', found: {volumes}"
    )


def test_dockerfile_backend_persistent_directories_and_permissions():
    """Verify infra/docker/Dockerfile.backend creates /app/data/tenants and sets appuser ownership."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    dockerfile_path = repo_root / "infra" / "docker" / "Dockerfile.backend"
    assert dockerfile_path.exists(), f"Missing Dockerfile.backend at {dockerfile_path}"

    content = dockerfile_path.read_text(encoding="utf-8")

    # Verify appuser creation and non-root USER
    assert "useradd -m -u 1000 appuser" in content, "Dockerfile.backend must create appuser with UID 1000"
    assert "USER appuser" in content, "Dockerfile.backend must run as non-root USER appuser"

    # Verify persistent directories creation and chown
    assert "/app/data/tenants" in content, (
        "Dockerfile.backend must create /app/data/tenants for persistent tenant storage"
    )
    assert "chown -R appuser:appuser /app" in content, (
        "Dockerfile.backend must chown /app to appuser:appuser"
    )


# ==============================================================================
# 2. TENANT & BUSINESS PATH ISOLATION TESTS
# ==============================================================================


def test_tenant_and_business_storage_path_isolation(test_db: Session, tmp_path: Path, monkeypatch):
    """Verify datasets for different tenants and businesses are strictly segregated."""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))

    org_a = str(uuid4())
    biz_a = str(uuid4())
    org_b = str(uuid4())
    biz_b = str(uuid4())

    csv_data = b"date,amount,item\n2026-01-01,100,Widget\n"

    # Upload for Tenant A
    ds_a, _ = TenantDataService.save_and_profile_file(
        organization_id=org_a,
        business_id=biz_a,
        filename="sales.csv",
        content=csv_data,
        session=test_db,
    )

    # Upload for Tenant B
    ds_b, _ = TenantDataService.save_and_profile_file(
        organization_id=org_b,
        business_id=biz_b,
        filename="sales.csv",
        content=csv_data,
        session=test_db,
    )

    # Verify paths are physically isolated
    path_a = Path(ds_a.storage_key)
    path_b = Path(ds_b.storage_key)

    assert path_a.exists()
    assert path_b.exists()
    assert path_a != path_b

    # Verify directory structure reflects tenant boundaries
    assert f"tenants/{org_a}/{biz_a}" in ds_a.storage_key.replace("\\", "/")
    assert f"tenants/{org_b}/{biz_b}" in ds_b.storage_key.replace("\\", "/")

    # Ensure Tenant A path does not reside anywhere inside Tenant B path
    assert str(path_b.parent) not in str(path_a)
    assert str(path_a.parent) not in str(path_b)


# ==============================================================================
# 3. PATH TRAVERSAL SANITIZATION TESTS
# ==============================================================================


def test_path_traversal_sanitization_defense(tmp_path: Path, monkeypatch, test_db: Session):
    """Verify malicious filenames attempting directory traversal are neutralized."""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))

    org_id = str(uuid4())
    biz_id = str(uuid4())
    malicious_names = [
        "../../etc/passwd.csv",
        "..\\..\\windows\\system32\\cmd.csv",
        "nested/sub/folder/data.csv",
        "something/../../../secret.csv",
        "malicious\x00file.csv",
    ]

    csv_data = b"date,amount\n2026-01-01,50\n"

    for bad_name in malicious_names:
        sanitized = TenantDataService.sanitize_filename(bad_name)
        # Ensure no path separators or traversal tokens remain
        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert ".." not in sanitized
        assert "\x00" not in sanitized

        # Upload and verify the file stays within the tenant directory
        ds, _ = TenantDataService.save_and_profile_file(
            organization_id=org_id,
            business_id=biz_id,
            filename=bad_name,
            content=csv_data,
            session=test_db,
        )

        disk_path = Path(ds.storage_key)
        assert disk_path.exists()
        # Ensure canonical path is strictly inside the tenant directory
        expected_parent = tmp_path / "tenants" / org_id / biz_id / ds.id
        assert disk_path.parent == expected_parent


# ==============================================================================
# 4. CONFIGURED STORAGE ROOT & READ-BACK TESTS
# ==============================================================================


def test_file_creation_and_readback_under_configured_storage_root(
    test_db: Session, sample_org_and_business, tmp_path: Path, monkeypatch
):
    """Verify files are created and accurately read back under custom DATA_DIR."""
    custom_root = tmp_path / "custom_storage"
    custom_root.mkdir()
    monkeypatch.setattr(settings, "DATA_DIR", str(custom_root))

    org, biz = sample_org_and_business

    csv_content = (
        b"date,customer_name,total_amount,payment_method\n"
        b"2026-03-01,Alice Corp,500.00,credit_card\n"
        b"2026-03-02,Bob Ltd,750.50,wire\n"
    )

    dataset = DataGatewayService.save_raw_dataset(
        db=test_db,
        organization_id=org.id,
        business_id=biz.id,
        filename="monthly_sales.csv",
        content=csv_content,
    )

    # 1. Verify file exists under custom_root
    storage_path = Path(dataset.storage_key)
    assert storage_path.exists(), f"File missing at {storage_path}"
    assert str(custom_root) in str(storage_path)
    assert storage_path.read_bytes() == csv_content

    # 2. Read back via DataGatewayService.get_dataset_preview
    preview = DataGatewayService.get_dataset_preview(
        db=test_db,
        dataset_id=dataset.id,
        business_id=biz.id,
        sample_size=10,
    )
    assert preview.dataset_id == dataset.id
    assert preview.row_count == 2
    assert "total_amount" in preview.columns
    assert len(preview.sample_rows) == 2
    assert preview.sample_rows[0]["customer_name"] == "Alice Corp"
    assert preview.sample_rows[1]["customer_name"] == "Bob Ltd"


# ==============================================================================
# 5. MISSING STORAGE FILE BEHAVIOR TESTS
# ==============================================================================


def test_missing_storage_file_raises_http_404(
    test_db: Session, sample_org_and_business, tmp_path: Path, monkeypatch
):
    """Verify missing storage file triggers clear HTTP 404 rather than unhandled 500 error."""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    org, biz = sample_org_and_business

    # Create dataset record pointing to a non-existent file
    ghost_dataset = UploadedDataset(
        id=str(uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        filename="ghost_data.csv",
        file_type="csv",
        storage_key=str(tmp_path / "tenants" / org.id / biz.id / "non_existent.csv").replace("\\", "/"),
        file_size_bytes=100,
        row_count=5,
        column_count=2,
    )
    test_db.add(ghost_dataset)
    test_db.commit()

    # 1. Preview request must fail with 404
    with pytest.raises(HTTPException) as exc_preview:
        DataGatewayService.get_dataset_preview(
            db=test_db,
            dataset_id=ghost_dataset.id,
            business_id=biz.id,
        )
    assert exc_preview.value.status_code == 404
    assert "Dataset file is no longer available on storage" in exc_preview.value.detail

    # 2. Ingestion request must fail with 404
    with pytest.raises(HTTPException) as exc_ingest:
        DataGatewayService.ingest_into_core_models(
            db=test_db,
            dataset_id=ghost_dataset.id,
            business_id=biz.id,
        )
    assert exc_ingest.value.status_code == 404
    assert "Dataset storage file not found" in exc_ingest.value.detail


# ==============================================================================
# 6. UNWRITABLE STORAGE DIRECTORY & FAILURE SAFETY TESTS
# ==============================================================================


def test_unwritable_storage_directory_fails_safely_without_orphaned_records(
    test_db: Session, sample_org_and_business, tmp_path: Path, monkeypatch
):
    """Verify write failure raises HTTP 500 and prevents orphaned database records."""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    org, biz = sample_org_and_business

    csv_content = b"date,amount\n2026-01-01,100\n"

    # Simulate filesystem write failure (e.g. disk full, permission denied, unwritable mount)
    with patch.object(Path, "write_bytes", side_effect=OSError("Read-only file system or disk full")):
        with pytest.raises(HTTPException) as exc_info:
            DataGatewayService.save_raw_dataset(
                db=test_db,
                organization_id=org.id,
                business_id=biz.id,
                filename="failing_upload.csv",
                content=csv_content,
            )

        assert exc_info.value.status_code == 500
        assert "Storage error: unable to save file to persistent volume" in exc_info.value.detail

    # Verify no orphaned UploadedDataset record was committed to the database
    committed_datasets = test_db.execute(
        select(UploadedDataset).where(UploadedDataset.business_id == biz.id)
    ).scalars().all()
    assert len(committed_datasets) == 0, "No dataset should be committed on storage failure"


def test_tenant_data_service_unwritable_storage_fails_safely(
    test_db: Session, sample_org_and_business, tmp_path: Path, monkeypatch
):
    """Verify TenantDataService.save_and_profile_file fails safely on OSError."""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    org, biz = sample_org_and_business

    csv_content = b"date,amount\n2026-01-01,100\n"

    with patch.object(Path, "write_bytes", side_effect=PermissionError("Permission denied")):
        with pytest.raises(HTTPException) as exc_info:
            TenantDataService.save_and_profile_file(
                organization_id=org.id,
                business_id=biz.id,
                filename="failing_tenant_data.csv",
                content=csv_content,
                session=test_db,
            )

        assert exc_info.value.status_code == 500
        assert "Storage error: unable to save file to persistent volume" in exc_info.value.detail

    # Verify no orphaned record
    committed = test_db.execute(
        select(UploadedDataset).where(UploadedDataset.business_id == biz.id)
    ).scalars().all()
    assert len(committed) == 0


# ==============================================================================
# 7. PRESERVATION OF EXISTING STORAGE KEY FORMAT
# ==============================================================================


def test_canonical_storage_key_format_preserved(test_db: Session, sample_org_and_business, monkeypatch):
    """Verify default storage keys maintain the canonical 'data/tenants/...' forward-slash path."""
    # When DATA_DIR is default "data"
    monkeypatch.setattr(settings, "DATA_DIR", "data")
    org, biz = sample_org_and_business

    csv_data = b"date,sales\n2026-01-01,100\n"

    # Mock write_bytes and mkdir to avoid polluting local filesystem during format test
    with patch.object(Path, "mkdir"), patch.object(Path, "write_bytes"):
        ds, _ = TenantDataService.save_and_profile_file(
            organization_id=org.id,
            business_id=biz.id,
            filename="my_sales_file.csv",
            content=csv_data,
            session=test_db,
        )

        assert ds.storage_key.startswith("data/tenants/")
        assert "\\" not in ds.storage_key
        assert f"/{org.id}/{biz.id}/{ds.id}/my_sales_file.csv" in ds.storage_key


# ==============================================================================
# 8. DATABASE COMMIT FAILURE ROLLBACK & FILE CLEANUP
# ==============================================================================


def test_database_commit_failure_cleans_up_file_on_disk(
    test_db: Session, sample_org_and_business, tmp_path: Path, monkeypatch
):
    """Verify that if database commit fails, the created file is cleaned up and DB is rolled back."""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    org, biz = sample_org_and_business

    csv_data = b"date,amount\n2026-01-01,250\n"

    # Simulate database commit failure (e.g. operational error or constraint failure)
    with patch.object(test_db, "commit", side_effect=RuntimeError("Simulated database failure on commit")):
        with pytest.raises(RuntimeError, match="Simulated database failure on commit"):
            DataGatewayService.save_raw_dataset(
                db=test_db,
                organization_id=org.id,
                business_id=biz.id,
                filename="doomed_upload.csv",
                content=csv_data,
            )

    # 1. Verify no record was committed to database
    committed = test_db.execute(
        select(UploadedDataset).where(UploadedDataset.business_id == biz.id)
    ).scalars().all()
    assert len(committed) == 0

    # 2. Verify no unmanaged residue file exists in tmp_path
    all_files = list(tmp_path.rglob("*.csv"))
    assert len(all_files) == 0, f"Expected disk file to be cleaned up on commit failure, found: {all_files}"


def test_cleanup_failure_logs_warning_and_preserves_db_exception(
    test_db: Session, sample_org_and_business, tmp_path: Path, monkeypatch, caplog
):
    """Verify that if rollback file unlink cleanup raises OSError, it logs a warning and preserves original DB error."""
    import logging
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    org, biz = sample_org_and_business

    csv_data = b"date,amount\n2026-01-01,250\n"

    def failing_unlink(self, *args, **kwargs):
        raise OSError("Permission denied / file locked during cleanup")

    with patch.object(test_db, "commit", side_effect=RuntimeError("Database failure on commit")):
        with patch.object(Path, "unlink", failing_unlink):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(RuntimeError, match="Database failure on commit"):
                    DataGatewayService.save_raw_dataset(
                        db=test_db,
                        organization_id=org.id,
                        business_id=biz.id,
                        filename="cleanup_failure_upload.csv",
                        content=csv_data,
                    )

    # 1. Verify warning was logged with storage path
    assert "Failed to clean up unindexed storage file" in caplog.text

    # 2. Verify no record was committed to database
    committed = test_db.execute(
        select(UploadedDataset).where(UploadedDataset.business_id == biz.id)
    ).scalars().all()
    assert len(committed) == 0

    # 3. File remains on disk as an unindexed file (to be caught by orphan reconciliation)
    all_files = list(tmp_path.rglob("*.csv"))
    assert len(all_files) == 1


def test_tenant_data_service_cleanup_failure_logs_warning_and_preserves_db_exception(
    test_db: Session, sample_org_and_business, tmp_path: Path, monkeypatch, caplog
):
    """Verify TenantDataService logs warning and preserves DB error if unlink fails during rollback."""
    import logging
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    org, biz = sample_org_and_business

    csv_data = b"date,amount\n2026-01-01,250\n"

    def failing_unlink(self, *args, **kwargs):
        raise OSError("File locked during cleanup")

    with patch.object(test_db, "commit", side_effect=RuntimeError("Tenant DB commit failure")):
        with patch.object(Path, "unlink", failing_unlink):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(RuntimeError, match="Tenant DB commit failure"):
                    TenantDataService.save_and_profile_file(
                        organization_id=org.id,
                        business_id=biz.id,
                        filename="tenant_cleanup_failure.csv",
                        content=csv_data,
                        session=test_db,
                    )

    assert "Failed to clean up unindexed storage file" in caplog.text
    committed = test_db.execute(
        select(UploadedDataset).where(UploadedDataset.business_id == biz.id)
    ).scalars().all()
    assert len(committed) == 0


# ==============================================================================
# 9. ESCAPE ROOT PREVENTION AND CONTAINMENT
# ==============================================================================


def test_storage_path_escape_root_sanitized_and_contained(
    test_db: Session, sample_org_and_business, tmp_path: Path, monkeypatch
):
    """Verify that even with path traversal tokens in identifiers, files cannot escape DATA_DIR."""
    storage_root = tmp_path / "safe_storage"
    storage_root.mkdir()
    monkeypatch.setattr(settings, "DATA_DIR", str(storage_root))

    csv_data = b"date,amount\n2026-01-01,100\n"

    # Malicious organization and business IDs attempting directory traversal
    malicious_org = "../../escaping_org"
    malicious_biz = "../../../escaping_biz"

    dataset = DataGatewayService.save_raw_dataset(
        db=test_db,
        organization_id=malicious_org,
        business_id=malicious_biz,
        filename="test.csv",
        content=csv_data,
    )

    disk_path = Path(dataset.storage_key)
    assert disk_path.exists()
    # Canonical resolved path MUST be strictly inside storage_root
    assert disk_path.resolve().is_relative_to(storage_root.resolve())
    assert ".." not in dataset.storage_key


# ==============================================================================
# 10. RESOLVE STORAGE PATH FLEXIBILITY & NORMALIZATION
# ==============================================================================


def test_resolve_storage_path_flexibility_and_normalization(tmp_path: Path, monkeypatch):
    """Verify resolve_storage_path handles literal paths, relative roots, and backslash normalization."""
    custom_root = tmp_path / "app_data"
    custom_root.mkdir()
    monkeypatch.setattr(settings, "DATA_DIR", str(custom_root))

    # Create an actual physical file in custom_root
    tenant_dir = custom_root / "tenants" / "org1" / "biz1" / "ds1"
    tenant_dir.mkdir(parents=True)
    sample_file = tenant_dir / "sales.csv"
    sample_file.write_text("date,amt\n2026-01-01,10\n", encoding="utf-8")

    # Case 1: Exact literal path
    res1 = DataGatewayService.resolve_storage_path(str(sample_file))
    assert res1.exists()
    assert res1 == sample_file

    # Case 2: Canonical database storage_key with 'data/' prefix
    key_with_data = "data/tenants/org1/biz1/ds1/sales.csv"
    res2 = DataGatewayService.resolve_storage_path(key_with_data)
    assert res2.exists()
    assert res2 == sample_file

    # Case 3: Windows backslash key
    win_key = "data\\tenants\\org1\\biz1\\ds1\\sales.csv"
    res3 = DataGatewayService.resolve_storage_path(win_key)
    assert res3.exists()
    assert res3 == sample_file

    # Case 4: Storage key without 'data/' prefix (e.g. 'tenants/org1/biz1/ds1/sales.csv')
    key_tenants = "tenants/org1/biz1/ds1/sales.csv"
    res4 = DataGatewayService.resolve_storage_path(key_tenants)
    assert res4.exists()
    assert res4 == sample_file

    # Case 5: Non-existent file returns Path object (so caller raises 404)
    res5 = DataGatewayService.resolve_storage_path("data/tenants/nonexistent/file.csv")
    assert not res5.exists()
