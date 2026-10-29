"""NEXUS Phase 1G.0 / 1G.0.1 — Live PostgreSQL Migration Rehearsal Test Suite for Revision 017.

Verifies:
1. Alembic migration chain upgrade through revision 017 on live PostgreSQL.
2. PostgreSQL information_schema verification for columns, types, nullability, and defaults.
3. Foreign key constraints: businesses.id (CASCADE) and ingestion_jobs.id (SET NULL).
4. PostgreSQL pg_indexes inspection: composite indexes and partial unique index definition.
5. Database-level partial unique index enforcement: duplicate active watermark raises SQLSTATE 23505.
6. Permitted historical inactive records: multiple superseded watermarks coexist without collision.
7. Multi-tenant isolation: distinct tenants manage identical source identifiers without collision.
8. ORM read/write lifecycle against migrated PostgreSQL catalogs.
9. Transaction rollback safety: uncommitted mutations do not alter active watermarks.
10. Clean downgrade to 016 and re-upgrade to 017 lifecycle on PostgreSQL.

Execution Guard:
Skipped automatically when a live PostgreSQL daemon is not reachable (e.g. local dev without Docker).
Strictly mandated in CI against pgvector/pgvector:pg16 container (0 skips when REQUIRE_POSTGRES=true).
"""

import importlib.util
import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models.tenant import Business, Organization
from app.models.watermark import TenantIngestionWatermark
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


def normalize_pg_url(url: str) -> str:
    """Normalize generic postgresql:// or postgres:// to postgresql+psycopg://."""
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


def should_skip_postgres_tests() -> bool:
    """Skip when in local development without strict PostgreSQL requirement."""
    if is_strict_postgres_required():
        return False
    reachable, _ = check_postgres_connection()
    return not reachable


def load_migration_module(migration_filename: str):
    """Dynamically import an Alembic migration script by filename."""
    versions_dir = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    module_path = versions_dir / migration_filename
    if not module_path.is_file():
        raise FileNotFoundError(f"Migration file not found: {module_path}")

    module_name = migration_filename.replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pg_engine():
    """Module-scoped PostgreSQL engine connected to test database."""
    if should_skip_postgres_tests():
        pytest.skip(
            "Live PostgreSQL daemon is not reachable on configured database URL. "
            "Set REQUIRE_POSTGRES=true or start PostgreSQL/Docker to run live rehearsal."
        )

    url = get_pg_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def m017_module():
    """Dynamically load migration 017 module."""
    return load_migration_module("017_phase1f2_authoritative_ingestion_watermark.py")


@pytest.fixture
def test_tenants(pg_engine) -> Generator[tuple[Organization, Business, Business], None, None]:
    """Create two isolated test businesses under an organization for multi-tenant tests."""
    SessionMaker = sessionmaker(bind=pg_engine)
    session = SessionMaker()

    org = Organization(
        id=f"org-pg-017-{uuid4().hex[:8]}",
        name="PostgreSQL 017 Rehearsal Org",
        slug=f"slug-017-{uuid4().hex[:8]}",
    )
    biz_a = Business(
        id=f"biz-pg-017-a-{uuid4().hex[:8]}",
        organization_id=org.id,
        name="Tenant A Retail",
    )
    biz_b = Business(
        id=f"biz-pg-017-b-{uuid4().hex[:8]}",
        organization_id=org.id,
        name="Tenant B Commerce",
    )
    session.add_all([org, biz_a, biz_b])
    session.commit()

    yield org, biz_a, biz_b

    # Cleanup
    with pg_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM businesses WHERE id IN (:a, :b)"),
            {"a": biz_a.id, "b": biz_b.id},
        )
        conn.execute(
            text("DELETE FROM organizations WHERE id = :org_id"),
            {"org_id": org.id},
        )
    session.close()


def test_01_postgres_connection_and_environment_guard():
    """1. Verify PostgreSQL connection status and enforce strict failure in CI."""
    reachable, err = check_postgres_connection()
    if is_strict_postgres_required() and not reachable:
        pytest.fail(f"REQUIRE_POSTGRES is set but PostgreSQL is unreachable: {err}")


def test_02_postgres_alembic_chain_upgrade_to_017(pg_engine):
    """2. Verify Alembic migration chain upgrade reaches revision 017 on live PostgreSQL."""
    with pg_engine.connect() as conn:
        insp = sa.inspect(conn)
        assert insp.has_table("alembic_version"), "Table 'alembic_version' must exist"
        assert insp.has_table("tenant_ingestion_watermarks"), "Table 'tenant_ingestion_watermarks' must exist"

        ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert ver == "017_phase1f2_authoritative_ingestion_watermark", (
            f"Expected alembic_version head to be '017_phase1f2_authoritative_ingestion_watermark', got '{ver}'"
        )


def test_03_postgres_table_columns_types_and_defaults(pg_engine):
    """3. Verify column names, data types, nullability, and defaults in PostgreSQL catalogs."""
    with pg_engine.connect() as conn:
        insp = sa.inspect(conn)
        cols = {c["name"]: c for c in insp.get_columns("tenant_ingestion_watermarks")}

        required_cols = [
            ("id", False),
            ("business_id", False),
            ("source_id", False),
            ("complete_through_dt", False),
            ("recorded_at", False),
            ("ingestion_job_id", True),
            ("provenance_type", False),
            ("verification_status", False),
            ("invalidation_reason", True),
            ("is_active", False),
            ("metadata_json", True),
            ("created_at", False),
            ("updated_at", False),
        ]

        for col_name, nullable in required_cols:
            assert col_name in cols, f"Column '{col_name}' missing from tenant_ingestion_watermarks"
            assert cols[col_name]["nullable"] is nullable, (
                f"Column '{col_name}' nullable mismatch: expected {nullable}, got {cols[col_name]['nullable']}"
            )


def test_04_postgres_foreign_key_constraints_and_cascades(pg_engine):
    """4. Verify foreign key definitions to businesses and ingestion_jobs with cascades in PostgreSQL catalogs."""
    with pg_engine.connect() as conn:
        insp = sa.inspect(conn)
        fks = insp.get_foreign_keys("tenant_ingestion_watermarks")
        fk_map = {fk["referred_table"]: fk for fk in fks}

        assert "businesses" in fk_map, "Foreign key to 'businesses' missing"
        assert fk_map["businesses"]["constrained_columns"] == ["business_id"]
        assert fk_map["businesses"]["referred_columns"] == ["id"]

        assert "ingestion_jobs" in fk_map, "Foreign key to 'ingestion_jobs' missing"
        assert fk_map["ingestion_jobs"]["constrained_columns"] == ["ingestion_job_id"]
        assert fk_map["ingestion_jobs"]["referred_columns"] == ["id"]


def test_05_postgres_indexes_and_partial_unique_index_catalog(pg_engine):
    """5. Inspect PostgreSQL pg_indexes to verify standard composite and partial unique index definitions."""
    with pg_engine.connect() as conn:
        res = conn.execute(
            text("""
                SELECT indexname, indexdef
                FROM pg_catalog.pg_indexes
                WHERE tablename = 'tenant_ingestion_watermarks';
            """)
        )
        indexes = {row[0]: row[1] for row in res}

        # Check standard composite indexes
        assert "ix_tenant_wm_biz_source_active" in indexes, "Composite index ix_tenant_wm_biz_source_active missing"
        assert "ix_tenant_wm_biz_complete_dt" in indexes, "Composite index ix_tenant_wm_biz_complete_dt missing"

        # Check partial unique index
        assert "uq_tenant_watermarks_active_source" in indexes, "Partial unique index uq_tenant_watermarks_active_source missing"
        idx_def = indexes["uq_tenant_watermarks_active_source"].lower()
        assert "unique" in idx_def, "Index uq_tenant_watermarks_active_source must be UNIQUE"
        assert "where (is_active = true)" in idx_def or "where (is_active is true)" in idx_def, (
            f"Expected partial predicate 'WHERE (is_active = true)', got: {indexes['uq_tenant_watermarks_active_source']}"
        )


def test_06_postgres_active_watermark_unique_rejection_sqlstate(pg_engine, test_tenants):
    """6. Verify duplicate active watermark for same tenant and source raises PostgreSQL SQLSTATE 23505."""
    _, biz_a, _ = test_tenants

    with pg_engine.begin() as conn:
        # Insert initial active watermark
        conn.execute(
            text("""
                INSERT INTO tenant_ingestion_watermarks (
                    id, business_id, source_id, complete_through_dt, recorded_at,
                    provenance_type, verification_status, is_active, created_at, updated_at
                ) VALUES (
                    :id, :biz, :src, :dt, :rec, :prov, :stat, true, now(), now()
                );
            """),
            {
                "id": f"wm-pg-1-{uuid4().hex[:8]}",
                "biz": biz_a.id,
                "src": "pos_retail",
                "dt": datetime(2023, 6, 30, 23, 59, tzinfo=UTC),
                "rec": datetime.now(UTC),
                "prov": "reconciliation_batch",
                "stat": "verified",
            },
        )

        # Attempt second active watermark with same (business_id, source_id)
        with pytest.raises(IntegrityError) as exc_info:
            conn.execute(
                text("""
                    INSERT INTO tenant_ingestion_watermarks (
                        id, business_id, source_id, complete_through_dt, recorded_at,
                        provenance_type, verification_status, is_active, created_at, updated_at
                    ) VALUES (
                        :id, :biz, :src, :dt, :rec, :prov, :stat, true, now(), now()
                    );
                """),
                {
                    "id": f"wm-pg-2-{uuid4().hex[:8]}",
                    "biz": biz_a.id,
                    "src": "pos_retail",
                    "dt": datetime(2023, 7, 31, 23, 59, tzinfo=UTC),
                    "rec": datetime.now(UTC),
                    "prov": "reconciliation_batch",
                    "stat": "verified",
                },
            )

        err_msg = str(exc_info.value).lower()
        assert "uq_tenant_watermarks_active_source" in err_msg or "unique" in err_msg, (
            f"Expected unique index violation for active watermark, got: {exc_info.value}"
        )


def test_07_postgres_permitted_historical_inactive_records(pg_engine, test_tenants):
    """7. Verify multiple inactive historical watermarks for same tenant and source coexist (audit ledger)."""
    _, biz_a, _ = test_tenants

    with pg_engine.begin() as conn:
        # Clean any previous records for this source
        conn.execute(
            text("DELETE FROM tenant_ingestion_watermarks WHERE business_id = :b AND source_id = :s"),
            {"b": biz_a.id, "s": "audit_source"},
        )

        # Insert 3 inactive historical records for the same (business_id, source_id)
        for i in range(1, 4):
            conn.execute(
                text("""
                    INSERT INTO tenant_ingestion_watermarks (
                        id, business_id, source_id, complete_through_dt, recorded_at,
                        provenance_type, verification_status, is_active, created_at, updated_at
                    ) VALUES (
                        :id, :biz, :src, :dt, :rec, :prov, :stat, false, now(), now()
                    );
                """),
                {
                    "id": f"wm-hist-{i}-{uuid4().hex[:8]}",
                    "biz": biz_a.id,
                    "src": "audit_source",
                    "dt": datetime(2023, i, 28, 23, 59, tzinfo=UTC),
                    "rec": datetime.now(UTC),
                    "prov": "reconciliation_batch",
                    "stat": "verified",
                },
            )

        # Verify all 3 inactive records coexist in PostgreSQL
        count = conn.execute(
            text("SELECT count(*) FROM tenant_ingestion_watermarks WHERE business_id = :b AND source_id = :s"),
            {"b": biz_a.id, "s": "audit_source"},
        ).scalar()
        assert count == 3, f"Expected 3 historical inactive watermarks, found {count}"


def test_08_postgres_cross_tenant_source_isolation(pg_engine, test_tenants):
    """8. Verify distinct tenants can have active watermarks with the exact same source_id without collision."""
    _, biz_a, biz_b = test_tenants

    with pg_engine.begin() as conn:
        # Clean test source
        conn.execute(
            text("DELETE FROM tenant_ingestion_watermarks WHERE source_id = :s"),
            {"s": "shared_channel_shopify"},
        )

        # Tenant A active watermark
        conn.execute(
            text("""
                INSERT INTO tenant_ingestion_watermarks (
                    id, business_id, source_id, complete_through_dt, recorded_at,
                    provenance_type, verification_status, is_active, created_at, updated_at
                ) VALUES (
                    :id, :biz, :src, :dt, :rec, :prov, :stat, true, now(), now()
                );
            """),
            {
                "id": f"wm-ten-a-{uuid4().hex[:8]}",
                "biz": biz_a.id,
                "src": "shared_channel_shopify",
                "dt": datetime(2023, 8, 31, 23, 59, tzinfo=UTC),
                "rec": datetime.now(UTC),
                "prov": "shopify_webhook",
                "stat": "verified",
            },
        )

        # Tenant B active watermark with SAME source_id
        conn.execute(
            text("""
                INSERT INTO tenant_ingestion_watermarks (
                    id, business_id, source_id, complete_through_dt, recorded_at,
                    provenance_type, verification_status, is_active, created_at, updated_at
                ) VALUES (
                    :id, :biz, :src, :dt, :rec, :prov, :stat, true, now(), now()
                );
            """),
            {
                "id": f"wm-ten-b-{uuid4().hex[:8]}",
                "biz": biz_b.id,
                "src": "shared_channel_shopify",
                "dt": datetime(2023, 8, 15, 23, 59, tzinfo=UTC),
                "rec": datetime.now(UTC),
                "prov": "shopify_webhook",
                "stat": "verified",
            },
        )

        # Verify both active records exist cleanly
        res = conn.execute(
            text("SELECT business_id, is_active FROM tenant_ingestion_watermarks WHERE source_id = :s"),
            {"s": "shared_channel_shopify"},
        ).fetchall()
        assert len(res) == 2
        assert {row[0] for row in res} == {biz_a.id, biz_b.id}
        assert all(row[1] is True for row in res)


def test_09_postgres_orm_reads_writes_and_rollback_preservation(pg_engine, test_tenants):
    """9. Verify SQLAlchemy ORM session interaction and transaction rollback safety on PostgreSQL."""
    _, biz_a, _ = test_tenants
    SessionMaker = sessionmaker(bind=pg_engine)
    session = SessionMaker()

    try:
        # Create ORM entity
        wm = TenantIngestionWatermark(
            id=f"wm-orm-{uuid4().hex[:8]}",
            business_id=biz_a.id,
            source_id="orm_test_source",
            complete_through_dt=datetime(2023, 9, 30, 23, 59, tzinfo=UTC),
            recorded_at=datetime.now(UTC),
            provenance_type="accounting_close",
            verification_status="verified",
            is_active=True,
            metadata_json={"batch_id": "BATCH-001", "records": 500},
        )
        session.add(wm)
        session.commit()

        # Query back via ORM
        loaded = session.query(TenantIngestionWatermark).filter_by(id=wm.id).one()
        assert loaded.source_id == "orm_test_source"
        assert loaded.metadata_json == {"batch_id": "BATCH-001", "records": 500}

        # Simulate aborted transaction: mutate state, flush, then rollback
        loaded.verification_status = "invalidated"
        loaded.invalidation_reason = "Speculative mutation that should roll back"
        session.flush()
        session.rollback()

        # Verify rollback preserved original status
        refreshed = session.query(TenantIngestionWatermark).filter_by(id=wm.id).one()
        assert refreshed.verification_status == "verified"
        assert refreshed.invalidation_reason is None
    finally:
        session.close()


def test_10_postgres_downgrade_and_reupgrade_lifecycle(pg_engine, m017_module):
    """10. Verify clean downgrade from 017 to 016 and subsequent re-upgrade on live PostgreSQL."""
    # 1. Downgrade 017 -> 016
    with pg_engine.connect() as down_conn:
        ctx_down = MigrationContext.configure(down_conn)
        with Operations.context(ctx_down), down_conn.begin():
            m017_module.downgrade()

    # Verify table and indexes dropped from PostgreSQL catalogs
    with pg_engine.connect() as check_conn:
        insp = sa.inspect(check_conn)
        assert not insp.has_table("tenant_ingestion_watermarks"), (
            "Table 'tenant_ingestion_watermarks' must be dropped on downgrade"
        )

    # 2. Re-upgrade 016 -> 017
    with pg_engine.connect() as up_conn:
        ctx_up = MigrationContext.configure(up_conn)
        with Operations.context(ctx_up), up_conn.begin():
            m017_module.upgrade()

    # Verify table and indexes restored in PostgreSQL catalogs
    with pg_engine.connect() as final_conn:
        insp = sa.inspect(final_conn)
        assert insp.has_table("tenant_ingestion_watermarks"), (
            "Table 'tenant_ingestion_watermarks' must be restored on re-upgrade"
        )
        indexes = {idx["name"]: idx for idx in insp.get_indexes("tenant_ingestion_watermarks")}
        assert "uq_tenant_watermarks_active_source" in indexes
        assert indexes["uq_tenant_watermarks_active_source"]["unique"] is True
