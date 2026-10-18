"""NEXUS Phase 30 & 32B — Live PostgreSQL Integration Test Suite.

Verifies:
1. Migration compatibility (Alembic versions 001-015, pgvector extension, table schemas).
2. Failure rollback and diagnostic persistence in PostgreSQL JSONB.
3. PostgreSQL uniqueness constraints and idempotent re-ingestion.
4. Concurrent multi-session ingestion safety (zero duplicate records, no deadlocks).
5. Native PostgreSQL row-level locking (SELECT ... FOR UPDATE SKIP LOCKED).
6. Multi-session scheduler atomic claim and SKIP LOCKED on IngestionJob (Phase 32B).
7. Multi-worker concurrent scheduler execution safety (zero duplicate scans) (Phase 32B).
8. Scheduler transaction rollback and idempotent retryability on mid-scan error (Phase 32B).

Execution Guard:
Skipped automatically when a live PostgreSQL daemon is not reachable (e.g. local SQLite dev).
Executed in CI against the pgvector/pgvector:pg16 service container (strictly 0 skips with REQUIRE_POSTGRES=true).
"""

import concurrent.futures
import io
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.sale import Sale
from app.models.tenant import UploadedDataset
from app.services.auth_service import AuthService
from app.services.data_gateway_service import DataGatewayService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker


def normalize_pg_url(url: str) -> str:
    """Normalize generic postgresql:// or postgres:// to postgresql+psycopg:// preserving existing drivers."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def get_pg_database_url() -> str:
    """Resolve active PostgreSQL connection URL honoring TEST_DATABASE_URL and DATABASE_URL."""
    raw_url = (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql+psycopg://nexus_user:nexus_password@localhost:5432/nexus_test_db"
    )
    return normalize_pg_url(raw_url)


def is_strict_postgres_required() -> bool:
    """Check whether execution environment strictly mandates live PostgreSQL verification."""
    return (
        os.getenv("CI", "").strip().lower() in ("true", "1")
        or os.getenv("REQUIRE_POSTGRES", "").strip().lower() in ("true", "1")
    )


def check_postgres_connection() -> tuple[bool, str | None]:
    """Check whether a live PostgreSQL daemon responds on active database URL."""
    url = get_pg_database_url()
    if not url.startswith(("postgresql", "postgres")):
        return False, f"URL scheme does not indicate PostgreSQL: {url}"
    try:
        eng = create_engine(url, connect_args={"connect_timeout": 2})
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def is_postgres_reachable() -> bool:
    """Check whether a live PostgreSQL daemon responds on active database URL."""
    reachable, _ = check_postgres_connection()
    return reachable


def should_skip_postgres_tests() -> bool:
    """Only allow skipping when in local development without strict PostgreSQL requirement."""
    if is_strict_postgres_required():
        return False  # Strict Gate: Never skip in CI or when explicitly required
    return not is_postgres_reachable()


pytestmark = pytest.mark.skipif(
    should_skip_postgres_tests(),
    reason="Live PostgreSQL daemon is not reachable on configured DATABASE_URL. Verification pending CI run.",
)


@pytest.fixture(scope="module", autouse=True)
def require_postgres():
    """Ensure live PostgreSQL daemon is verified reachable after test environment configuration."""
    reachable, err = check_postgres_connection()
    if not reachable:
        if is_strict_postgres_required():
            pytest.fail(
                f"PostgreSQL Verification Gate Failure: Live PostgreSQL is strictly required "
                f"(CI={os.getenv('CI')}, REQUIRE_POSTGRES={os.getenv('REQUIRE_POSTGRES')}), "
                f"but connection probe failed on {get_pg_database_url()}. Error: {err}"
            )
        pytest.skip(
            f"Live PostgreSQL daemon is not reachable on configured DATABASE_URL ({err}). "
            "Verification pending CI run."
        )


@pytest.fixture(scope="module")
def pg_engine():
    """Create dedicated engine for PostgreSQL integration testing initialized after test configuration."""
    url = get_pg_database_url()
    eng = create_engine(url, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def pg_session_factory(pg_engine):
    """Provide sessionmaker bound to PostgreSQL."""
    return sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)


@pytest.fixture
def pg_db(pg_session_factory):
    """Provide managed database session for individual test."""
    session = pg_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pg_tenant(pg_db):
    """Create isolated tenant on PostgreSQL for testing."""
    hex_id = uuid4().hex[:6]
    user, org, biz = AuthService.signup(
        db=pg_db,
        email=f"pg_test_{hex_id}@nexus.postgres",
        password="SecurePassword123!",
        full_name="PostgreSQL Integration Analyst",
        organization_name=f"PG Corp {hex_id}",
        business_name=f"PG Retail {hex_id}",
    )
    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=org.id,
        business_id=biz.id,
    )
    return {"user": user, "org": org, "biz": biz, "token": token}


@pytest.fixture
def pg_client(pg_db):
    """FastAPI TestClient routed to PostgreSQL test session."""
    def override_get_db():
        try:
            yield pg_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POSTGRESQL INTEGRATION TESTS
# ---------------------------------------------------------------------------

def test_pg_01_migration_and_pgvector_compatibility(pg_engine):
    """PostgreSQL schema migration head (015) and pgvector extension are verified."""
    inspector = inspect(pg_engine)
    table_names = set(inspector.get_table_names())

    # Core and hardened phase tables must exist
    required_tables = {
        "alembic_version",
        "organizations",
        "businesses",
        "users",
        "uploaded_datasets",
        "ingestion_jobs",
        "sales",
        "products",
        "customers",
        "inventory",
        "continuous_scan_runs",
        "continuous_findings",
        "decision_records",
        "decision_outcome_observations",
    }
    missing = required_tables - table_names
    assert not missing, f"Missing PostgreSQL migration tables: {missing}"

    # Verify pgvector extension
    with pg_engine.connect() as conn:
        ext_res = conn.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'")).scalar()
        assert ext_res == "vector", "pgvector extension must be active in PostgreSQL."

        # Verify Alembic head migration revision 015
        alembic_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert alembic_rev is not None
        assert "015" in alembic_rev or alembic_rev == "015_phase29_continuous_intelligence"


def test_pg_02_failure_rollback_and_diagnostic_persistence(pg_client, pg_tenant, pg_session_factory):
    """PostgreSQL atomic rollback purges staged models while diagnostics persist in JSONB."""
    headers = {
        "Authorization": f"Bearer {pg_tenant['token']}",
        "X-Business-ID": pg_tenant["biz"].id,
    }

    prefix = uuid4().hex[:6].upper()
    ord1 = f"PG-ROLLBACK-{prefix}-01"
    ord2 = f"PG-ROLLBACK-{prefix}-02"
    ord3 = f"PG-ROLLBACK-{prefix}-03"

    # Upload dataset with 2 valid sales followed by 1 invalid amount
    csv_data = (
        "order_number,date,amount\n"
        f"{ord1},2025-05-01,100.00\n"
        f"{ord2},2025-05-02,200.00\n"
        f"{ord3},2025-05-03,CORRUPT_NON_NUMERIC\n"
    )
    files = {"file": ("pg_rollback_test.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = pg_client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    # Ingestion must fail with HTTP 400
    ingest_res = pg_client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_res.status_code == 400
    assert ingest_res.json()["detail"]["total_errors"] == 1

    # Open fresh PostgreSQL session to verify zero uncommitted leaks
    with pg_session_factory() as fresh_db:
        persisted = fresh_db.execute(
            select(Sale).where(
                Sale.business_id == pg_tenant["biz"].id,
                Sale.transaction_number.in_([ord1, ord2, ord3]),
            )
        ).scalars().all()
        assert len(persisted) == 0, "PostgreSQL rollback failed: partial records found committed."

        # Verify failure diagnostics survived in PostgreSQL JSONB
        ds = fresh_db.execute(select(UploadedDataset).where(UploadedDataset.id == dataset_id)).scalar_one()
        assert ds.schema_json["ingestion_status"] == "FAILED"
        assert len(ds.schema_json["ingestion_errors"]) == 1
        assert ds.schema_json["ingestion_errors"][0]["row"] == 3


def test_pg_03_uniqueness_constraints_and_idempotency(pg_client, pg_tenant, pg_session_factory):
    """PostgreSQL native unique constraints and ingestion idempotency work seamlessly."""
    headers = {
        "Authorization": f"Bearer {pg_tenant['token']}",
        "X-Business-ID": pg_tenant["biz"].id,
    }

    prefix = uuid4().hex[:6].upper()
    ord1 = f"PG-IDEMP-{prefix}-01"
    ord2 = f"PG-IDEMP-{prefix}-02"

    csv_data = (
        "order_number,date,amount\n"
        f"{ord1},2025-05-10,50.00\n"
        f"{ord2},2025-05-11,75.00\n"
    )
    files = {"file": ("pg_idempotent.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    res_upload = pg_client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res_upload.status_code == 201
    dataset_id = res_upload.json()["dataset_id"]

    # Initial Ingest
    res_1 = pg_client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert res_1.status_code == 200
    assert res_1.json()["records_persisted"] == 2

    # Second Ingest (Idempotent Retry)
    res_2 = pg_client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert res_2.status_code == 200
    assert "idempotent no-op" in res_2.json()["message"]

    # Verify record count is strictly 2
    with pg_session_factory() as fresh_db:
        sales = fresh_db.execute(
            select(Sale).where(
                Sale.business_id == pg_tenant["biz"].id,
                Sale.transaction_number.in_([ord1, ord2]),
            )
        ).scalars().all()
        assert len(sales) == 2


def test_pg_04_concurrent_ingestion_safety(pg_client, pg_tenant, pg_session_factory):
    """Concurrent worker threads committing to PostgreSQL complete without deadlocks or duplicates."""
    headers = {
        "Authorization": f"Bearer {pg_tenant['token']}",
        "X-Business-ID": pg_tenant["biz"].id,
    }

    prefix = uuid4().hex[:6].upper()
    rows = ["order_number,date,amount"]
    expected_orders = []
    for i in range(10):
        ord_num = f"PG-CONCUR-{prefix}-{i:02d}"
        expected_orders.append(ord_num)
        rows.append(f"{ord_num},2025-05-15,{20.00 + i:.2f}")
    csv_data = "\n".join(rows) + "\n"

    files = {"file": ("pg_concur.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = pg_client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    def run_worker():
        with pg_session_factory() as session:
            return DataGatewayService.ingest_into_core_models(
                db=session,
                dataset_id=dataset_id,
                business_id=pg_tenant["biz"].id,
                target_entity="Sale",
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(run_worker)
        future2 = executor.submit(run_worker)
        res1 = future1.result(timeout=15)
        res2 = future2.result(timeout=15)

    assert res1["status"] == "COMPLETED"
    assert res2["status"] == "COMPLETED"

    with pg_session_factory() as fresh_db:
        sales = fresh_db.execute(
            select(Sale).where(
                Sale.business_id == pg_tenant["biz"].id,
                Sale.transaction_number.in_(expected_orders),
            )
        ).scalars().all()
        assert len(sales) == 10, f"Expected exactly 10 sales, found {len(sales)} (duplicate insertion occurred)"


def test_pg_05_database_locking_phase29_scheduler(pg_session_factory, pg_tenant):
    """PostgreSQL native SELECT ... FOR UPDATE SKIP LOCKED executes without errors."""
    from app.models.continuous import FindingScanRun

    # Create a pending scan run in PostgreSQL
    with pg_session_factory() as db:
        scan = FindingScanRun(
            organization_id=pg_tenant["org"].id,
            business_id=pg_tenant["biz"].id,
            status="PENDING",
            trigger_type="scheduled",
            metrics_scanned=["revenue", "margin"],
            metadata_json={"dataset_version": 1},
        )
        db.add(scan)
        db.commit()
        scan_id = scan.id

    # Test native PostgreSQL row lock with SKIP LOCKED
    with pg_session_factory() as db1:
        # Worker 1 acquires row lock
        locked_scan = db1.execute(
            select(FindingScanRun)
            .where(FindingScanRun.id == scan_id)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        assert locked_scan is not None
        assert locked_scan.id == scan_id

        # Worker 2 attempts to query the same row with SKIP LOCKED -> must skip and return None
        with pg_session_factory() as db2:
            second_query = db2.execute(
                select(FindingScanRun)
                .where(FindingScanRun.id == scan_id)
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            assert second_query is None, "PostgreSQL SKIP LOCKED failed: worker 2 did not skip locked row."

        # Release lock
        db1.rollback()


def test_pg_06_scheduler_skip_locked_ingestion_claim(pg_session_factory, pg_tenant):
    """PostgreSQL native SELECT IngestionJob ... FOR UPDATE SKIP LOCKED skips rows held by concurrent sessions."""
    from app.models.tenant import IngestionJob, UploadedDataset
    from app.models.continuous import FindingScanRun
    from app.analytics.continuous.service import ContinuousIntelligenceService

    biz = pg_tenant["biz"]
    org = pg_tenant["org"]

    # 1. Seed two completed IngestionJobs
    with pg_session_factory() as db:
        ds1 = UploadedDataset(
            id=str(uuid4()),
            organization_id=org.id,
            business_id=biz.id,
            filename="pg_cand_1.csv",
            file_type="csv",
            storage_key="/tmp/pg_cand_1.csv",
            file_size_bytes=1024,
            readiness_status="READY",
        )
        ds2 = UploadedDataset(
            id=str(uuid4()),
            organization_id=org.id,
            business_id=biz.id,
            filename="pg_cand_2.csv",
            file_type="csv",
            storage_key="/tmp/pg_cand_2.csv",
            file_size_bytes=1024,
            readiness_status="READY",
        )
        job1 = IngestionJob(
            id=str(uuid4()),
            organization_id=org.id,
            business_id=biz.id,
            dataset_id=ds1.id,
            status="COMPLETED",
            target_entity="Sale",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            rows_processed=10,
        )
        job2 = IngestionJob(
            id=str(uuid4()),
            organization_id=org.id,
            business_id=biz.id,
            dataset_id=ds2.id,
            status="COMPLETED",
            target_entity="Sale",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            rows_processed=10,
        )
        db.add_all([ds1, ds2, job1, job2])
        db.commit()
        job1_id, job2_id = job1.id, job2.id

    # 2. Worker Session 1 acquires an exclusive row lock on job1 (without committing)
    session1 = pg_session_factory()
    try:
        locked_job1 = session1.execute(
            select(IngestionJob)
            .where(IngestionJob.id == job1_id)
            .with_for_update()
        ).scalar_one_or_none()
        assert locked_job1 is not None

        # 3. Worker Session 2 runs reconciliation in parallel
        with pg_session_factory() as session2:
            reconciled = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
                db=session2,
                business_id=biz.id,
                limit=10,
            )
            # In PostgreSQL: job1 was skipped because of SKIP LOCKED; only job2 was claimed
            assert len(reconciled) == 1, f"Expected exactly 1 reconciled scan, got {len(reconciled)}"
            runs = session2.execute(
                select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
            ).scalars().all()
            claimed_job_ids = [
                r.metadata_json.get("ingestion_job_id")
                for r in runs
                if r.metadata_json
            ]
            assert job2_id in claimed_job_ids
            assert job1_id not in claimed_job_ids, "job1 was locked by session1 and should NOT have been claimed!"

    finally:
        session1.rollback()
        session1.close()

    # 4. Now that session1 released its lock, a second reconciliation pass successfully claims job1
    with pg_session_factory() as session3:
        reconciled_pass2 = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
            db=session3,
            business_id=biz.id,
            limit=10,
        )
        assert len(reconciled_pass2) == 1
        runs_pass2 = session3.execute(
            select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
        ).scalars().all()
        all_claimed = [
            r.metadata_json.get("ingestion_job_id") for r in runs_pass2 if r.metadata_json
        ]
        assert job1_id in all_claimed


def test_pg_07_concurrent_scheduler_ticks_no_duplicate_scans(pg_session_factory, pg_tenant):
    """Two concurrent threads executing ContinuousIntelligenceScheduler.run_single_tick do not create duplicate scans."""
    from app.models.tenant import IngestionJob, UploadedDataset
    from app.models.continuous import FindingScanRun
    from app.analytics.continuous.scheduler import ContinuousIntelligenceScheduler

    biz = pg_tenant["biz"]
    org = pg_tenant["org"]

    # Pre-clean: drain any preexisting completed jobs from prior tests for isolated test accounting
    with pg_session_factory() as pre_db:
        ContinuousIntelligenceScheduler.run_single_tick(db=pre_db, max_businesses=50, batch_size=50)

    # 1. Seed 4 completed IngestionJobs
    job_ids = []
    with pg_session_factory() as db:
        for i in range(4):
            ds = UploadedDataset(
                id=str(uuid4()),
                organization_id=org.id,
                business_id=biz.id,
                filename=f"pg_concur_{i}.csv",
                file_type="csv",
                storage_key=f"/tmp/pg_concur_{i}.csv",
                file_size_bytes=1024,
                readiness_status="READY",
            )
            job = IngestionJob(
                id=str(uuid4()),
                organization_id=org.id,
                business_id=biz.id,
                dataset_id=ds.id,
                status="COMPLETED",
                target_entity="Sale",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                rows_processed=15,
            )
            db.add_all([ds, job])
            job_ids.append(job.id)
        db.commit()

    # 2. Concurrently run single ticks from two independent database sessions
    def run_tick():
        with pg_session_factory() as thread_db:
            return ContinuousIntelligenceScheduler.run_single_tick(
                db=thread_db,
                max_businesses=10,
                batch_size=10,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_tick)
        f2 = executor.submit(run_tick)
        res1 = f1.result(timeout=20)
        res2 = f2.result(timeout=20)

    # 3. Verify total reconciled across both workers equals 4
    total_reconciled = res1["total_reconciled"] + res2["total_reconciled"]
    assert total_reconciled == 4, f"Expected exactly 4 scans reconciled across concurrent workers, got {total_reconciled}"
    assert len(res1["errors"]) == 0
    assert len(res2["errors"]) == 0

    # 4. Verify ZERO duplicate FindingScanRun records in PostgreSQL
    with pg_session_factory() as db:
        runs = db.execute(
            select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
        ).scalars().all()
        # Filter for the jobs seeded in this test
        test_runs = [
            r for r in runs
            if r.metadata_json and r.metadata_json.get("ingestion_job_id") in job_ids
        ]
        assert len(test_runs) == 4, f"Expected exactly 4 scan runs, found {len(test_runs)} (possible duplicate execution)"
        recorded_job_ids = [r.metadata_json["ingestion_job_id"] for r in test_runs]
        assert len(set(recorded_job_ids)) == 4, "Duplicate scan runs detected for an ingestion job!"


def test_pg_08_scheduler_transaction_rollback_and_retryability(pg_session_factory, pg_tenant):
    """Scheduler transaction rolls back cleanly on scan error without corrupting state or leaving dangling locks."""
    from unittest.mock import patch
    from app.models.tenant import IngestionJob, UploadedDataset
    from app.models.continuous import FindingScanRun
    from app.analytics.continuous.service import ContinuousIntelligenceService
    from app.analytics.continuous.scheduler import ContinuousIntelligenceScheduler

    biz = pg_tenant["biz"]
    org = pg_tenant["org"]

    # 1. Seed a completed job
    with pg_session_factory() as db:
        ds = UploadedDataset(
            id=str(uuid4()),
            organization_id=org.id,
            business_id=biz.id,
            filename="pg_failing_scan.csv",
            file_type="csv",
            storage_key="/tmp/pg_failing_scan.csv",
            file_size_bytes=1024,
            readiness_status="READY",
        )
        job = IngestionJob(
            id=str(uuid4()),
            organization_id=org.id,
            business_id=biz.id,
            dataset_id=ds.id,
            status="COMPLETED",
            target_entity="Sale",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            rows_processed=10,
        )
        db.add_all([ds, job])
        db.commit()
        job_id = job.id

    # 2. Simulate transient failure during trigger_ingestion_scan
    # Service handles per-job failure by rolling back the transaction so no partial state is committed
    with patch.object(
        ContinuousIntelligenceService,
        "trigger_ingestion_scan",
        side_effect=RuntimeError("Transient database lock timeout during scan"),
    ):
        with pg_session_factory() as db:
            result = ContinuousIntelligenceScheduler.run_single_tick(
                db=db,
                max_businesses=10,
                batch_size=10,
            )
            # Service rolled back transaction and did not claim/reconcile
            assert result["total_reconciled"] == 0

    # 3. Verify PostgreSQL transaction state is clean (no half-created FindingScanRun)
    with pg_session_factory() as db:
        runs = db.execute(
            select(FindingScanRun).where(
                FindingScanRun.business_id == biz.id,
            )
        ).scalars().all()
        failing_runs = [
            r for r in runs
            if r.metadata_json and r.metadata_json.get("ingestion_job_id") == job_id
        ]
        assert len(failing_runs) == 0, "Failed scan committed partial FindingScanRun record!"

        # Candidate IngestionJob must remain COMPLETED and intact
        candidate_job = db.execute(
            select(IngestionJob).where(IngestionJob.id == job_id)
        ).scalar_one()
        assert candidate_job.status == "COMPLETED"

    # 4. Subsequent tick without failure successfully reconciles the job (retryability)
    with pg_session_factory() as db:
        clean_result = ContinuousIntelligenceScheduler.run_single_tick(
            db=db,
            max_businesses=10,
            batch_size=10,
        )
        assert clean_result["total_reconciled"] >= 1

    with pg_session_factory() as db:
        runs_after = db.execute(
            select(FindingScanRun).where(FindingScanRun.business_id == biz.id)
        ).scalars().all()
        success_runs = [
            r for r in runs_after
            if r.metadata_json and r.metadata_json.get("ingestion_job_id") == job_id
        ]
        assert len(success_runs) == 1
        assert success_runs[0].status == "COMPLETED"
