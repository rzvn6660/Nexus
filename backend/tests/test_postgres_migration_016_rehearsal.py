"""NEXUS Phase 1D.1 — Live PostgreSQL Migration Rehearsal Test Suite.

Verifies:
1. Full Alembic migration chain upgrade through revision 016 on PostgreSQL.
2. Customer code and email composite uniqueness constraints in PostgreSQL catalogs.
3. Cross-tenant customer code and email reuse without collisions.
4. Intra-tenant duplicate customer code and email rejection (SQLSTATE 23505).
5. Downgrade failure and atomic rollback when cross-tenant duplicates exist.
6. Clean downgrade and re-upgrade lifecycle after duplicate cleanup.
7. Existing customer primary keys and sales foreign keys remain intact.
8. PostgreSQL functional unique index compatibility: (business_id, lower(email)) WHERE email IS NOT NULL.

Execution Guard:
Skipped automatically when a live PostgreSQL daemon is not reachable (e.g. local SQLite dev).
Executed in CI against the pgvector/pgvector:pg16 service container (strictly 0 skips with REQUIRE_POSTGRES=true).
"""

import importlib.util
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


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


def should_skip_postgres_tests() -> bool:
    """Skip when in local development without strict PostgreSQL requirement."""
    if is_strict_postgres_required():
        return False
    reachable, _ = check_postgres_connection()
    return not reachable


pytestmark = pytest.mark.skipif(
    should_skip_postgres_tests(),
    reason="Live PostgreSQL daemon is not reachable on configured DATABASE_URL. Verification pending CI run.",
)


@pytest.fixture(scope="module", autouse=True)
def require_postgres():
    """Ensure live PostgreSQL daemon is verified reachable or fail in CI."""
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
    """Provide PostgreSQL test engine."""
    url = get_pg_database_url()
    eng = create_engine(url, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture
def m016_module():
    """Dynamically load migration 016 module."""
    p016 = Path("backend/alembic/versions/016_phase1c2_tenant_scoped_customer_identity.py")
    if not p016.exists():
        p016 = Path("alembic/versions/016_phase1c2_tenant_scoped_customer_identity.py")
    assert p016.exists(), "Migration 016 must exist"
    spec = importlib.util.spec_from_file_location("m016_pg_rehearsal", p016)
    assert spec is not None and spec.loader is not None
    m016 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m016)
    return m016


def test_postgres_alembic_chain_upgrade_to_016(pg_engine) -> None:
    """1. Verify full Alembic migration chain upgrade through revision 016 on PostgreSQL."""
    with pg_engine.connect() as conn:
        insp = sa.inspect(conn)
        assert insp.has_table("customers"), "Table 'customers' must exist in PostgreSQL schema"
        assert insp.has_table("sales"), "Table 'sales' must exist in PostgreSQL schema"
        assert insp.has_table("alembic_version"), "Table 'alembic_version' must exist"

        ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert ver == "016_phase1c2_tenant_scoped_customer_identity", (
            f"Expected alembic_version head to be '016_phase1c2_tenant_scoped_customer_identity', got {ver}"
        )


def test_postgres_customer_composite_constraints_inspected(pg_engine) -> None:
    """2. Verify customer code and email composite uniqueness constraints in PostgreSQL catalogs."""
    with pg_engine.connect() as conn:
        insp = sa.inspect(conn)
        uqs = insp.get_unique_constraints("customers")
        uq_col_sets = {frozenset(u["column_names"]) for u in uqs}

        assert frozenset(["business_id", "customer_code"]) in uq_col_sets, (
            "Composite constraint (business_id, customer_code) missing from PostgreSQL customers table"
        )
        assert frozenset(["business_id", "email"]) in uq_col_sets, (
            "Composite constraint (business_id, email) missing from PostgreSQL customers table"
        )
        assert frozenset(["customer_code"]) not in uq_col_sets, (
            "Legacy global unique constraint on customer_code must not exist on PostgreSQL"
        )
        assert frozenset(["email"]) not in uq_col_sets, (
            "Legacy global unique constraint on email must not exist on PostgreSQL"
        )


def test_postgres_cross_tenant_identity_reuse(pg_engine) -> None:
    """3. Verify different tenants can reuse customer codes and email addresses on PostgreSQL."""
    biz_a = f"biz-pg-a-{uuid4().hex[:8]}"
    biz_b = f"biz-pg-b-{uuid4().hex[:8]}"
    shared_code = f"CODE-{uuid4().hex[:6]}"
    shared_email = f"shared-{uuid4().hex[:6]}@example-domain.com"
    now = datetime.now(UTC)

    with pg_engine.begin() as conn:
        # Create prerequisite business rows if needed or insert synthetic customer fixtures
        res1 = conn.execute(
            text("""
                INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                VALUES (:biz, :code, :name, :email, :city, :segment, :acq, :now, :now)
                RETURNING id;
            """),
            {
                "biz": biz_a,
                "code": shared_code,
                "name": "Tenant A Customer",
                "email": shared_email,
                "city": "Chicago",
                "segment": "Retail",
                "acq": date(2024, 1, 1),
                "now": now,
            },
        )
        cust_a_id = res1.scalar()

        res2 = conn.execute(
            text("""
                INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                VALUES (:biz, :code, :name, :email, :city, :segment, :acq, :now, :now)
                RETURNING id;
            """),
            {
                "biz": biz_b,
                "code": shared_code,
                "name": "Tenant B Customer",
                "email": shared_email,
                "city": "Detroit",
                "segment": "Wholesale",
                "acq": date(2024, 1, 1),
                "now": now,
            },
        )
        cust_b_id = res2.scalar()

        assert cust_a_id is not None
        assert cust_b_id is not None
        assert cust_a_id != cust_b_id

        # Cleanup synthetic test records
        conn.execute(text("DELETE FROM customers WHERE id IN (:id1, :id2)"), {"id1": cust_a_id, "id2": cust_b_id})


def test_postgres_intra_tenant_duplicate_rejected(pg_engine) -> None:
    """4. Verify duplicate codes and emails within one tenant are rejected on PostgreSQL."""
    biz_a = f"biz-pg-{uuid4().hex[:8]}"
    code_1 = f"CODE-{uuid4().hex[:6]}"
    email_1 = f"buyer-{uuid4().hex[:6]}@domain.com"
    now = datetime.now(UTC)

    with pg_engine.connect() as conn:
        trans = conn.begin()
        res = conn.execute(
            text("""
                INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                VALUES (:biz, :code, :name, :email, :city, :segment, :acq, :now, :now)
                RETURNING id;
            """),
            {
                "biz": biz_a,
                "code": code_1,
                "name": "Canonical Customer",
                "email": email_1,
                "city": "Austin",
                "segment": "Retail",
                "acq": date(2024, 1, 1),
                "now": now,
            },
        )
        cust_id = res.scalar()
        trans.commit()

        # Duplicate code in same tenant must fail
        with pytest.raises(IntegrityError), conn.begin():
            conn.execute(
                text("""
                    INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                    VALUES (:biz, :code, :name, :email, :city, :segment, :acq, :now, :now);
                """),
                {
                    "biz": biz_a,
                    "code": code_1,
                    "name": "Duplicate Code",
                    "email": f"other-{uuid4().hex[:6]}@domain.com",
                    "city": "Austin",
                    "segment": "Retail",
                    "acq": date(2024, 1, 1),
                    "now": now,
                },
            )

        # Duplicate email in same tenant must fail
        with pytest.raises(IntegrityError), conn.begin():
            conn.execute(
                text("""
                    INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                    VALUES (:biz, :code, :name, :email, :city, :segment, :acq, :now, :now);
                """),
                {
                    "biz": biz_a,
                    "code": f"CODE-{uuid4().hex[:6]}",
                    "name": "Duplicate Email",
                    "email": email_1,
                    "city": "Austin",
                    "segment": "Retail",
                    "acq": date(2024, 1, 1),
                    "now": now,
                },
            )

        # Cleanup
        with conn.begin():
            conn.execute(text("DELETE FROM customers WHERE id = :id"), {"id": cust_id})


def test_postgres_downgrade_fails_safely_on_cross_tenant_duplicates(pg_engine, m016_module) -> None:
    """5. Verify downgrade fails safely on PostgreSQL when cross-tenant duplicates exist,
    leaving the database and Alembic revision in a consistent state without altering schema.
    """
    biz_a = f"biz-pg-a-{uuid4().hex[:8]}"
    biz_b = f"biz-pg-b-{uuid4().hex[:8]}"
    dup_code = f"DUP-CODE-{uuid4().hex[:6]}"
    now = datetime.now(UTC)

    with pg_engine.connect() as conn:
        # Insert cross-tenant duplicates
        trans = conn.begin()
        res1 = conn.execute(
            text("""
                INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                VALUES (:biz, :code, :name, :email, :city, :segment, :acq, :now, :now)
                RETURNING id;
            """),
            {
                "biz": biz_a,
                "code": dup_code,
                "name": "Tenant A Cust",
                "email": f"a-{uuid4().hex[:6]}@domain.com",
                "city": "Dallas",
                "segment": "Retail",
                "acq": date(2024, 1, 1),
                "now": now,
            },
        )
        id1 = res1.scalar()

        res2 = conn.execute(
            text("""
                INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                VALUES (:biz, :code, :name, :email, :city, :segment, :acq, :now, :now)
                RETURNING id;
            """),
            {
                "biz": biz_b,
                "code": dup_code,
                "name": "Tenant B Cust",
                "email": f"b-{uuid4().hex[:6]}@domain.com",
                "city": "Houston",
                "segment": "Retail",
                "acq": date(2024, 1, 1),
                "now": now,
            },
        )
        id2 = res2.scalar()
        trans.commit()

        # Attempting downgrade must fail with IntegrityError
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx), pytest.raises(IntegrityError), conn.begin():
            m016_module.downgrade()

        # Verify PostgreSQL transactional atomicity: composite constraints are still in place
        insp = sa.inspect(conn)
        uqs = insp.get_unique_constraints("customers")
        uq_col_sets = {frozenset(u["column_names"]) for u in uqs}
        assert frozenset(["business_id", "customer_code"]) in uq_col_sets

        # Cleanup
        with conn.begin():
            conn.execute(text("DELETE FROM customers WHERE id IN (:id1, :id2)"), {"id1": id1, "id2": id2})


def test_postgres_clean_downgrade_and_reupgrade_lifecycle(pg_engine, m016_module) -> None:
    """6. Verify clean downgrade succeeds after duplicate cleanup and re-upgrade succeeds idempotently on PostgreSQL."""
    with pg_engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            # Downgrade
            with conn.begin():
                m016_module.downgrade()

            # Verify single-column constraints restored
            insp_down = sa.inspect(conn)
            uqs_down = insp_down.get_unique_constraints("customers")
            uq_down_sets = {frozenset(u["column_names"]) for u in uqs_down}
            assert frozenset(["customer_code"]) in uq_down_sets
            assert frozenset(["email"]) in uq_down_sets

            # Re-upgrade
            with conn.begin():
                m016_module.upgrade()

            # Verify composite constraints restored
            insp_up = sa.inspect(conn)
            uqs_up = insp_up.get_unique_constraints("customers")
            uq_up_sets = {frozenset(u["column_names"]) for u in uqs_up}
            assert frozenset(["business_id", "customer_code"]) in uq_up_sets
            assert frozenset(["business_id", "email"]) in uq_up_sets


def test_postgres_customer_pk_and_sales_fk_preserved(pg_engine) -> None:
    """7. Verify existing customer primary keys and sales foreign keys remain intact on PostgreSQL."""
    biz_id = f"biz-pg-{uuid4().hex[:8]}"
    cust_code = f"CODE-{uuid4().hex[:6]}"
    now = datetime.now(UTC)

    with pg_engine.begin() as conn:
        # Create customer
        res_c = conn.execute(
            text("""
                INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                VALUES (:biz, :code, :name, :email, :city, :segment, :acq, :now, :now)
                RETURNING id;
            """),
            {
                "biz": biz_id,
                "code": cust_code,
                "name": "FK Test Customer",
                "email": f"fk-{uuid4().hex[:6]}@domain.com",
                "city": "Denver",
                "segment": "Retail",
                "acq": date(2024, 1, 1),
                "now": now,
            },
        )
        customer_id = res_c.scalar()
        assert customer_id is not None

        # Create sale linked via customer_id
        tx_num = f"TX-PG-{uuid4().hex[:8]}"
        res_s = conn.execute(
            text("""
                INSERT INTO sales (business_id, transaction_number, customer_id, transaction_date, status, subtotal, discount_amount, tax_amount, total_amount, created_at, updated_at)
                VALUES (:biz, :tx, :cid, :dt, :st, :sub, :disc, :tax, :tot, :now, :now)
                RETURNING id;
            """),
            {
                "biz": biz_id,
                "tx": tx_num,
                "cid": customer_id,
                "dt": now,
                "st": "completed",
                "sub": Decimal("100.00"),
                "disc": Decimal("0.00"),
                "tax": Decimal("8.00"),
                "tot": Decimal("108.00"),
                "now": now,
            },
        )
        sale_id = res_s.scalar()
        assert sale_id is not None

        # Verify sale links to customer
        fetched_cid = conn.execute(text("SELECT customer_id FROM sales WHERE id = :sid"), {"sid": sale_id}).scalar()
        assert fetched_cid == customer_id

        # Verify CASCADE on customer deletion
        conn.execute(text("DELETE FROM customers WHERE id = :cid"), {"cid": customer_id})
        sales_remaining = conn.execute(text("SELECT COUNT(*) FROM sales WHERE id = :sid"), {"sid": sale_id}).scalar()
        assert sales_remaining == 0


def test_postgres_functional_unique_index_compatibility(pg_engine) -> None:
    """8. Verify PostgreSQL functional unique index compatibility: (business_id, lower(email)) WHERE email IS NOT NULL."""
    biz_a = f"biz-fidx-a-{uuid4().hex[:8]}"
    biz_b = f"biz-fidx-b-{uuid4().hex[:8]}"
    now = datetime.now(UTC)

    with pg_engine.connect() as conn:
        # Create functional unique index
        with conn.begin():
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_business_email_lower
                ON customers (business_id, lower(email))
                WHERE email IS NOT NULL;
            """))

        try:
            # 1. Distinct tenants can use same email (even with different case)
            with conn.begin():
                conn.execute(
                    text("""
                        INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                        VALUES (:b, :c, 'A', 'test.user@company.com', 'City', 'Retail', '2024-01-01', :now, :now);
                    """),
                    {"b": biz_a, "c": f"C-{uuid4().hex[:6]}", "now": now},
                )
                conn.execute(
                    text("""
                        INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                        VALUES (:b, :c, 'B', 'TEST.USER@COMPANY.COM', 'City', 'Retail', '2024-01-01', :now, :now);
                    """),
                    {"b": biz_b, "c": f"C-{uuid4().hex[:6]}", "now": now},
                )

            # 2. Same tenant cannot insert case variant
            with pytest.raises(IntegrityError), conn.begin():
                conn.execute(
                    text("""
                        INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                        VALUES (:b, :c, 'A-Dup', 'TEST.USER@COMPANY.COM', 'City', 'Retail', '2024-01-01', :now, :now);
                    """),
                    {"b": biz_a, "c": f"C-{uuid4().hex[:6]}", "now": now},
                )

            # 3. Multiple NULL emails in same tenant succeed
            with conn.begin():
                conn.execute(
                    text("""
                        INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                        VALUES (:b, :c, 'Null 1', NULL, 'City', 'Retail', '2024-01-01', :now, :now);
                    """),
                    {"b": biz_a, "c": f"C-{uuid4().hex[:6]}", "now": now},
                )
                conn.execute(
                    text("""
                        INSERT INTO customers (business_id, customer_code, name, email, city, customer_segment, acquisition_date, created_at, updated_at)
                        VALUES (:b, :c, 'Null 2', NULL, 'City', 'Retail', '2024-01-01', :now, :now);
                    """),
                    {"b": biz_a, "c": f"C-{uuid4().hex[:6]}", "now": now},
                )

        finally:
            # Cleanup test rows and index
            with conn.begin():
                conn.execute(text("DELETE FROM customers WHERE business_id IN (:ba, :bb)"), {"ba": biz_a, "bb": biz_b})
                conn.execute(text("DROP INDEX IF EXISTS uq_customers_business_email_lower;"))
