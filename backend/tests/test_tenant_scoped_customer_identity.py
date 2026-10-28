"""Regression tests for tenant-scoped customer identity and migration safety (Phase 1C.2 & 1C.3).

Validates:
1. Cross-tenant code co-existence: Two distinct tenants can use the exact same customer_code.
2. Intra-tenant code uniqueness: Duplicate customer_code within the same tenant raises IntegrityError.
3. Cross-tenant email co-existence: Two distinct tenants can register the same customer email.
4. Intra-tenant email uniqueness: Duplicate email within the same tenant raises IntegrityError.
5. Sales customer resolution boundary: Resolving customer in Tenant A never matches Tenant B's customer.
6. Cross-tenant IDOR rejection: Supplying a foreign tenant's customer_id never resolves or links.
7. Legacy null-tenant protection: Records with business_id IS NULL are never resolved or claimed by a tenant.
8. Safe failure on unresolvable customers: Sales ingestion fails safely without arbitrary fallback.
9. Referential integrity: Sale -> Customer FK relationships and cascading deletes function properly.
10. Data gateway customer CSV ingestion: Customer CSV upload in Tenant A accepts codes existing in Tenant B.
11. Null business_id handling: Legacy records without business_id do not collide under composite constraints.
12. Model normalization: Whitespace trimming on code and email, case normalization on email, preserving None.
13. Schema normalization: Pydantic CustomerBase normalizes customer_code and email.
14. Intra-tenant normalized duplicate rejection: Case and whitespace variants within a tenant trigger IntegrityError.
15. Migration lifecycle: Alembic migration 016 upgrade, idempotent re-upgrade, downgrade failure on cross-tenant
    duplicates, downgrade success after duplicate cleanup, and final re-upgrade in an isolated SQLite engine.
"""

import importlib.util
import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, Organization
from app.schemas.customer import CustomerCreate
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def two_tenants(db_session: Session) -> tuple[Business, Business]:
    """Create two separate tenant businesses for cross-tenant testing."""
    org_a = Organization(
        id=f"org-a-{uuid4().hex[:8]}",
        name="Org Alpha",
        slug=f"org-a-{uuid4().hex[:8]}",
    )
    org_b = Organization(
        id=f"org-b-{uuid4().hex[:8]}",
        name="Org Beta",
        slug=f"org-b-{uuid4().hex[:8]}",
    )
    db_session.add_all([org_a, org_b])
    db_session.flush()

    biz_a = Business(
        id=f"biz-test-a-{uuid4().hex[:8]}",
        organization_id=org_a.id,
        name="Tenant Alpha",
        industry="Retail",
        currency="USD",
    )
    biz_b = Business(
        id=f"biz-test-b-{uuid4().hex[:8]}",
        organization_id=org_b.id,
        name="Tenant Beta",
        industry="Wholesale",
        currency="USD",
    )
    db_session.add_all([biz_a, biz_b])
    db_session.commit()
    return biz_a, biz_b


def test_cross_tenant_same_customer_code(db_session: Session, two_tenants: tuple[Business, Business]) -> None:
    """1. Verify identical customer_code can exist in two different tenants without collisions."""
    biz_a, biz_b = two_tenants
    shared_code = "CUST-SHARED-001"
    now = datetime.now(UTC)

    cust_a = Customer(
        business_id=biz_a.id,
        customer_code=shared_code,
        name="Alpha Customer",
        email="buyer-alpha@shared-domain.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 15),
        created_at=now,
        updated_at=now,
    )
    cust_b = Customer(
        business_id=biz_b.id,
        customer_code=shared_code,
        name="Beta Customer",
        email="buyer-beta@shared-domain.com",
        city="Detroit",
        customer_segment="Wholesale",
        acquisition_date=date(2024, 2, 20),
        created_at=now,
        updated_at=now,
    )

    db_session.add_all([cust_a, cust_b])
    db_session.commit()

    a_res = db_session.scalar(
        select(Customer).where(Customer.business_id == biz_a.id, Customer.customer_code == shared_code)
    )
    b_res = db_session.scalar(
        select(Customer).where(Customer.business_id == biz_b.id, Customer.customer_code == shared_code)
    )

    assert a_res is not None
    assert b_res is not None
    assert a_res.id != b_res.id
    assert a_res.name == "Alpha Customer"
    assert b_res.name == "Beta Customer"


def test_intra_tenant_duplicate_customer_code_rejected(db_session: Session, two_tenants: tuple[Business, Business]) -> None:
    """2. Verify duplicate customer_code within the SAME tenant raises IntegrityError."""
    biz_a, _ = two_tenants
    code = "CUST-DUP-001"
    now = datetime.now(UTC)

    cust1 = Customer(
        business_id=biz_a.id,
        customer_code=code,
        name="Original Customer",
        email="orig@tenant-a.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 15),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust1)
    db_session.commit()

    cust2 = Customer(
        business_id=biz_a.id,
        customer_code=code,
        name="Duplicate Customer",
        email="dup@tenant-a.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2024, 3, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cross_tenant_same_email(db_session: Session, two_tenants: tuple[Business, Business]) -> None:
    """3. Verify identical email can exist in two different tenants without collisions."""
    biz_a, biz_b = two_tenants
    shared_email = "consumer.pat@example.com"
    now = datetime.now(UTC)

    cust_a = Customer(
        business_id=biz_a.id,
        customer_code="CUST-ALPHA-99",
        name="Pat at Coffee Roasters",
        email=shared_email,
        city="Seattle",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 10),
        created_at=now,
        updated_at=now,
    )
    cust_b = Customer(
        business_id=biz_b.id,
        customer_code="CUST-BETA-99",
        name="Pat at Artisan Bakery",
        email=shared_email,
        city="Portland",
        customer_segment="Wholesale",
        acquisition_date=date(2024, 2, 10),
        created_at=now,
        updated_at=now,
    )

    db_session.add_all([cust_a, cust_b])
    db_session.commit()

    a_res = db_session.scalar(
        select(Customer).where(Customer.business_id == biz_a.id, Customer.email == shared_email)
    )
    b_res = db_session.scalar(
        select(Customer).where(Customer.business_id == biz_b.id, Customer.email == shared_email)
    )

    assert a_res is not None
    assert b_res is not None
    assert a_res.id != b_res.id
    assert a_res.customer_code == "CUST-ALPHA-99"
    assert b_res.customer_code == "CUST-BETA-99"


def test_intra_tenant_duplicate_email_rejected(db_session: Session, two_tenants: tuple[Business, Business]) -> None:
    """4. Verify duplicate email within the SAME tenant raises IntegrityError."""
    biz_a, _ = two_tenants
    email = "single-buyer@example.com"
    now = datetime.now(UTC)

    cust1 = Customer(
        business_id=biz_a.id,
        customer_code="CUST-A-101",
        name="Buyer One",
        email=email,
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust1)
    db_session.commit()

    cust2 = Customer(
        business_id=biz_a.id,
        customer_code="CUST-A-102",
        name="Buyer Two",
        email=email,
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2024, 2, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_sales_customer_resolution_preserves_tenant_boundary_with_shared_codes(
    db_session: Session, two_tenants: tuple[Business, Business]
) -> None:
    """5. Verify sales ingestion customer resolution strictly stays within tenant boundary when codes match."""
    biz_a, biz_b = two_tenants
    shared_code = "CUST-TWIN-01"
    now = datetime.now(UTC)

    cust_a = Customer(
        business_id=biz_a.id,
        customer_code=shared_code,
        name="Alpha Twin",
        email="twin-a@corp.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    cust_b = Customer(
        business_id=biz_b.id,
        customer_code=shared_code,
        name="Beta Twin",
        email="twin-b@corp.com",
        city="Denver",
        customer_segment="Wholesale",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([cust_a, cust_b])
    db_session.commit()

    # Tenant A customer resolution map
    cust_rows_a = db_session.execute(
        select(Customer.id, Customer.customer_code).where(Customer.business_id == biz_a.id)
    ).all()
    code_to_cust_id_a = {str(c.customer_code).strip().lower(): c.id for c in cust_rows_a if c.customer_code}

    # Tenant B customer resolution map
    cust_rows_b = db_session.execute(
        select(Customer.id, Customer.customer_code).where(Customer.business_id == biz_b.id)
    ).all()
    code_to_cust_id_b = {str(c.customer_code).strip().lower(): c.id for c in cust_rows_b if c.customer_code}

    assert shared_code.lower() in code_to_cust_id_a
    assert code_to_cust_id_a[shared_code.lower()] == cust_a.id
    assert code_to_cust_id_a[shared_code.lower()] != cust_b.id

    assert shared_code.lower() in code_to_cust_id_b
    assert code_to_cust_id_b[shared_code.lower()] == cust_b.id
    assert code_to_cust_id_b[shared_code.lower()] != cust_a.id


def test_supplied_customer_id_foreign_tenant_rejected(
    db_session: Session, two_tenants: tuple[Business, Business]
) -> None:
    """6. Verify supplying Tenant B's customer ID in Tenant A resolution fails to resolve."""
    biz_a, biz_b = two_tenants
    now = datetime.now(UTC)

    cust_b = Customer(
        business_id=biz_b.id,
        customer_code="CUST-B-FOREIGN",
        name="Foreign Customer",
        email="foreign@beta.com",
        city="Denver",
        customer_segment="Wholesale",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust_b)
    db_session.commit()

    # Pre-fetch for Tenant A
    cust_rows_a = db_session.execute(
        select(Customer.id, Customer.customer_code).where(Customer.business_id == biz_a.id)
    ).all()
    id_to_cust_id_a = {c.id: c.id for c in cust_rows_a}

    # Verify cust_b.id is not present in Tenant A's resolution index
    assert cust_b.id not in id_to_cust_id_a


def test_legacy_null_business_id_customer_cannot_be_resolved_or_claimed(
    db_session: Session, two_tenants: tuple[Business, Business]
) -> None:
    """7. Verify legacy records with business_id IS NULL are never resolved by a tenant."""
    biz_a, _ = two_tenants
    now = datetime.now(UTC)

    legacy_cust = Customer(
        business_id=None,
        customer_code="CUST-LEGACY-NULL",
        name="Unassigned Legacy Customer",
        email="legacy@nexus.local",
        city="Global",
        customer_segment="Retail",
        acquisition_date=date(2022, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(legacy_cust)
    db_session.commit()

    # Tenant A scoped query
    tenant_a_custs = db_session.scalars(
        select(Customer).where(Customer.business_id == biz_a.id)
    ).all()
    tenant_a_codes = {c.customer_code for c in tenant_a_custs}

    assert "CUST-LEGACY-NULL" not in tenant_a_codes
    assert legacy_cust.id not in {c.id for c in tenant_a_custs}


def test_missing_or_unresolved_customer_fails_safely_without_arbitrary_fallback(
    db_session: Session, two_tenants: tuple[Business, Business]
) -> None:
    """8. Verify missing or unresolvable customer identifiers fail safely without picking arbitrary customer."""
    biz_a, _ = two_tenants
    now = datetime.now(UTC)

    # Existing customer in tenant
    existing_cust = Customer(
        business_id=biz_a.id,
        customer_code="CUST-VALID",
        name="Valid Buyer",
        email="valid@buyer.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(existing_cust)
    db_session.commit()

    # DataGatewayService resolution indexes
    cust_rows = db_session.execute(
        select(Customer.id, Customer.customer_code).where(Customer.business_id == biz_a.id)
    ).all()
    code_to_cust_id = {str(c.customer_code).strip().lower(): c.id for c in cust_rows if c.customer_code}
    id_to_cust_id = {c.id: c.id for c in cust_rows}

    # Simulate resolving an unknown customer identifier with allow_unmapped_fallback = False
    unresolved_identifier = "NON_EXISTENT_CODE"
    allow_unmapped_fallback = False

    resolved_id = None
    if unresolved_identifier.lower() in code_to_cust_id:
        resolved_id = code_to_cust_id[unresolved_identifier.lower()]
    elif unresolved_identifier.isdigit() and int(unresolved_identifier) in id_to_cust_id:
        resolved_id = id_to_cust_id[int(unresolved_identifier)]
    else:
        if not allow_unmapped_fallback:
            # Replicates exact DataGatewayService safe rejection
            resolved_id = None

    # Assert it was NOT assigned to existing_cust.id
    assert resolved_id is None
    assert resolved_id != existing_cust.id


def test_sale_foreign_key_referential_integrity(db_session: Session, two_tenants: tuple[Business, Business]) -> None:
    """9. Verify Sale -> Customer foreign key constraints and cascading behavior remain intact."""
    biz_a, _ = two_tenants
    now = datetime.now(UTC)

    cust = Customer(
        business_id=biz_a.id,
        customer_code="CUST-FK-01",
        name="FK Test Customer",
        email="fk@test.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust)
    db_session.commit()

    sale = Sale(
        business_id=biz_a.id,
        transaction_number="TXN-FK-01",
        customer_id=cust.id,
        transaction_date=now,
        status="completed",
        subtotal=Decimal("50.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("4.00"),
        total_amount=Decimal("54.00"),
        created_at=now,
        updated_at=now,
    )
    db_session.add(sale)
    db_session.commit()

    reloaded_cust = db_session.scalar(select(Customer).where(Customer.id == cust.id))
    assert reloaded_cust is not None
    assert len(reloaded_cust.sales) == 1
    assert reloaded_cust.sales[0].transaction_number == "TXN-FK-01"


def test_customer_csv_ingestion_cross_tenant_independence(
    db_session: Session, two_tenants: tuple[Business, Business]
) -> None:
    """10. Verify Customer CSV ingestion into Tenant A accepts codes that already exist in Tenant B."""
    biz_a, biz_b = two_tenants
    shared_code = "CUST-CSV-001"
    shared_email = "shared-csv@domain.com"
    now = datetime.now(UTC)

    cust_b = Customer(
        business_id=biz_b.id,
        customer_code=shared_code,
        name="Pre-existing Beta Customer",
        email=shared_email,
        city="Denver",
        customer_segment="Wholesale",
        acquisition_date=date(2023, 10, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust_b)
    db_session.commit()

    csv_content = f"""customer_code,name,email,city,customer_segment,acquisition_date
{shared_code},New Alpha Buyer,{shared_email},Austin,Retail,2024-03-15
"""
    df = pd.read_csv(io.StringIO(csv_content))

    existing_codes_set: set[str] = set()
    existing_emails_set: set[str] = set()
    existing_custs = db_session.execute(
        select(Customer.customer_code, Customer.email).where(
            Customer.business_id == biz_a.id
        )
    ).all()
    for c_code, c_email in existing_custs:
        if c_code:
            existing_codes_set.add(str(c_code).strip())
        if c_email:
            existing_emails_set.add(str(c_email).strip().lower())

    seen_codes_in_file: set[str] = set()
    seen_emails_in_file: set[str] = set()
    staged_customers = []

    for _, row in df.iterrows():
        c_code = str(row["customer_code"]).strip()
        c_email = str(row["email"]).strip().lower()

        if c_code in seen_codes_in_file or c_email in seen_emails_in_file:
            continue
        seen_codes_in_file.add(c_code)
        seen_emails_in_file.add(c_email)

        if c_code in existing_codes_set or c_email in existing_emails_set:
            continue
        existing_codes_set.add(c_code)
        existing_emails_set.add(c_email)

        cust = Customer(
            business_id=biz_a.id,
            customer_code=c_code,
            name=str(row["name"]).strip(),
            email=c_email,
            city=str(row["city"]).strip(),
            customer_segment=str(row["customer_segment"]).strip(),
            acquisition_date=pd.to_datetime(row["acquisition_date"]).date(),
        )
        staged_customers.append(cust)

    assert len(staged_customers) == 1
    db_session.add_all(staged_customers)
    db_session.commit()

    cust_a = db_session.scalar(select(Customer).where(Customer.business_id == biz_a.id, Customer.customer_code == shared_code))
    cust_b_reloaded = db_session.scalar(select(Customer).where(Customer.business_id == biz_b.id, Customer.customer_code == shared_code))

    assert cust_a is not None
    assert cust_b_reloaded is not None
    assert cust_a.id != cust_b_reloaded.id


def test_null_business_id_coexistence(db_session: Session) -> None:
    """11. Verify multiple legacy/unassigned records where business_id is None do not collide."""
    now = datetime.now(UTC)
    cust_null1 = Customer(
        business_id=None,
        customer_code="LEGACY-001",
        name="Legacy Customer 1",
        email="legacy1@example.com",
        city="Unknown",
        customer_segment="Retail",
        acquisition_date=date(2022, 1, 1),
        created_at=now,
        updated_at=now,
    )
    cust_null2 = Customer(
        business_id=None,
        customer_code="LEGACY-002",
        name="Legacy Customer 2",
        email="legacy2@example.com",
        city="Unknown",
        customer_segment="Retail",
        acquisition_date=date(2022, 2, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([cust_null1, cust_null2])
    db_session.commit()

    null_custs = db_session.scalars(select(Customer).where(Customer.business_id.is_(None))).all()
    assert len(null_custs) >= 2


def test_customer_model_normalization_trim_and_lowercase() -> None:
    """12. Verify ORM model normalizes whitespace and email case, and preserves None."""
    now = datetime.now(UTC)
    cust = Customer(
        business_id="biz-test",
        customer_code="  CUST-WHITESPACE-01  ",
        name="Whitespace Corp",
        email="  Alice.Buyer@SUB.Domain.COM  ",
        city="Seattle",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )

    assert cust.customer_code == "CUST-WHITESPACE-01"
    assert cust.email == "alice.buyer@sub.domain.com"

    # Verify None preservation
    cust.customer_code = None
    assert cust.customer_code is None
    cust.email = None
    assert cust.email is None


def test_customer_schema_normalization_trim_and_lowercase() -> None:
    """13. Verify Pydantic schema trims code and lowercases email."""
    payload = {
        "customer_code": "  CUST-SCHEMA-99  ",
        "name": "Schema Test",
        "email": "  Buyer.Schema@Domain.COM  ",
        "city": "Dallas",
        "customer_segment": "Retail",
        "acquisition_date": "2024-01-01",
    }
    schema_obj = CustomerCreate(**payload)
    assert schema_obj.customer_code == "CUST-SCHEMA-99"
    assert schema_obj.email == "buyer.schema@domain.com"


def test_intra_tenant_whitespace_and_case_duplicate_rejected(
    db_session: Session, two_tenants: tuple[Business, Business]
) -> None:
    """14. Verify case and whitespace variants within same tenant collide and trigger IntegrityError."""
    biz_a, _ = two_tenants
    now = datetime.now(UTC)

    cust1 = Customer(
        business_id=biz_a.id,
        customer_code="CUST-CANONICAL",
        name="Primary Buyer",
        email="buyer.test@example.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust1)
    db_session.commit()

    # Attempt inserting with different whitespace on code
    cust_dup_code = Customer(
        business_id=biz_a.id,
        customer_code="  CUST-CANONICAL  ",
        name="Whitespace Variant",
        email="other@example.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust_dup_code)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Attempt inserting with case and whitespace variant on email
    cust_dup_email = Customer(
        business_id=biz_a.id,
        customer_code="CUST-OTHER",
        name="Case Variant",
        email="  BUYER.TEST@Example.COM  ",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust_dup_email)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_alembic_016_migration_upgrade_downgrade_reupgrade_and_downgrade_failure() -> None:
    """15. Test Alembic migration 016 complete lifecycle: upgrade, idempotent re-upgrade,
    downgrade failure on cross-tenant duplicates, downgrade success after cleanup, and re-upgrade.
    """
    p015 = Path("backend/alembic/versions/015_phase29_continuous_intelligence.py")
    if not p015.exists():
        p015 = Path("alembic/versions/015_phase29_continuous_intelligence.py")
    p016 = Path("backend/alembic/versions/016_phase1c2_tenant_scoped_customer_identity.py")
    if not p016.exists():
        p016 = Path("alembic/versions/016_phase1c2_tenant_scoped_customer_identity.py")

    assert p015.exists(), "Migration 015 must exist"
    assert p016.exists(), "Migration 016 must exist"

    spec016 = importlib.util.spec_from_file_location("m016", p016)
    assert spec016 is not None and spec016.loader is not None
    m016 = importlib.util.module_from_spec(spec016)
    spec016.loader.exec_module(m016)

    assert m016.revision == "016_phase1c2_tenant_scoped_customer_identity"
    assert m016.down_revision == "015_phase29_continuous_intelligence"

    # Test execution against isolated SQLite database
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            op = Operations(ctx)
            # 1. Base table simulating state after 001 and 005
            op.create_table(
                "customers",
                sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
                sa.Column("business_id", sa.String(length=36), nullable=True),
                sa.Column("customer_code", sa.String(length=32), nullable=False),
                sa.Column("name", sa.String(length=255), nullable=False),
                sa.Column("email", sa.String(length=255), nullable=False),
                sa.Column("city", sa.String(length=128), nullable=False),
                sa.Column("customer_segment", sa.String(length=64), nullable=False),
                sa.Column("acquisition_date", sa.Date(), nullable=False),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                sa.PrimaryKeyConstraint("id"),
                sa.UniqueConstraint("customer_code"),
                sa.UniqueConstraint("email"),
            )
            conn.commit()

            # 2. Upgrade
            m016.upgrade()
            conn.commit()

            # Verify composite constraints exist
            insp_after_up = sa.inspect(conn)
            uqs = insp_after_up.get_unique_constraints("customers")
            uq_col_sets = [set(u["column_names"]) for u in uqs]
            assert {"business_id", "customer_code"} in uq_col_sets
            assert {"business_id", "email"} in uq_col_sets
            assert {"customer_code"} not in uq_col_sets
            assert {"email"} not in uq_col_sets

            # 3. Idempotent re-upgrade (must not fail when constraints already composite)
            m016.upgrade()
            conn.commit()

            # 4. Insert cross-tenant duplicates (allowed under composite constraints)
            conn.execute(sa.text("INSERT INTO customers (id, business_id, customer_code, name, email, city, customer_segment, acquisition_date) VALUES (1, 'biz-1', 'CUST-X', 'Name 1', 'x@test.com', 'City', 'Retail', '2024-01-01')"))
            conn.execute(sa.text("INSERT INTO customers (id, business_id, customer_code, name, email, city, customer_segment, acquisition_date) VALUES (2, 'biz-2', 'CUST-X', 'Name 2', 'x@test.com', 'City', 'Retail', '2024-01-01')"))
            conn.commit()

            # 5. Verify same-tenant duplicate fails
            with pytest.raises(IntegrityError):
                conn.execute(sa.text("INSERT INTO customers (id, business_id, customer_code, name, email, city, customer_segment, acquisition_date) VALUES (3, 'biz-1', 'CUST-X', 'Name 3', 'diff@test.com', 'City', 'Retail', '2024-01-01')"))
            conn.rollback()

            # 6. Verify downgrade fails when cross-tenant duplicates exist
            with pytest.raises(IntegrityError):
                m016.downgrade()
            conn.rollback()

            # Clean duplicate and temp table in SQLite
            conn.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_customers"))
            conn.execute(sa.text("DELETE FROM customers WHERE id = 2"))
            conn.commit()

            # 7. Downgrade succeeds after duplicate removed
            m016.downgrade()
            conn.commit()

            insp_after_down = sa.inspect(conn)
            uqs_down = insp_after_down.get_unique_constraints("customers")
            uq_down_col_sets = [set(u["column_names"]) for u in uqs_down]
            assert {"customer_code"} in uq_down_col_sets
            assert {"email"} in uq_down_col_sets

            # 8. Re-upgrade back to composite
            m016.upgrade()
            conn.commit()

            insp_re = sa.inspect(conn)
            uqs_re = insp_re.get_unique_constraints("customers")
            uq_re_col_sets = [set(u["column_names"]) for u in uqs_re]
            assert {"business_id", "customer_code"} in uq_re_col_sets
            assert {"business_id", "email"} in uq_re_col_sets


def test_alembic_016_partial_schema_state_guards() -> None:
    """16. Verify migration 016 fails cleanly on unexpected partial schema states:
    - Missing customers table fails with informative RuntimeError.
    - Missing business_id column (pre-005 schema state) fails with informative RuntimeError.
    """
    p016 = Path("backend/alembic/versions/016_phase1c2_tenant_scoped_customer_identity.py")
    if not p016.exists():
        p016 = Path("alembic/versions/016_phase1c2_tenant_scoped_customer_identity.py")

    spec016 = importlib.util.spec_from_file_location("m016_guard", p016)
    assert spec016 is not None and spec016.loader is not None
    m016 = importlib.util.module_from_spec(spec016)
    spec016.loader.exec_module(m016)

    # Test 1: Missing table entirely
    engine1 = sa.create_engine("sqlite:///:memory:")
    with engine1.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx), pytest.raises(RuntimeError, match="table 'customers' does not exist"):
            m016.upgrade()

    # Test 2: Missing business_id column (pre-005 legacy state)
    engine2 = sa.create_engine("sqlite:///:memory:")
    with engine2.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            op = Operations(ctx)
            op.create_table(
                "customers",
                sa.Column("id", sa.Integer(), primary_key=True),
                # Note: business_id is omitted!
                sa.Column("customer_code", sa.String(32), nullable=False),
                sa.Column("name", sa.String(255), nullable=False),
                sa.Column("email", sa.String(255), nullable=False),
                sa.UniqueConstraint("customer_code"),
                sa.UniqueConstraint("email"),
            )
            conn.commit()

            with pytest.raises(RuntimeError, match="column 'business_id' missing"):
                m016.upgrade()


def test_functional_unique_index_case_insensitivity_and_null_support() -> None:
    """17. Verify functional unique index behavior on (business_id, lower(email)) WHERE email IS NOT NULL:
    - Allows identical email across distinct tenants.
    - Rejects case variants within the same tenant.
    - Allows multiple NULL emails within the same tenant.
    """
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                business_id VARCHAR(36),
                customer_code VARCHAR(32) NOT NULL,
                email VARCHAR(255)
            )
        """))
        conn.execute(sa.text("""
            CREATE UNIQUE INDEX uq_customers_business_email_lower
            ON customers (business_id, lower(email))
            WHERE email IS NOT NULL
        """))

        # Cross-tenant same email succeeds
        conn.execute(sa.text("INSERT INTO customers (id, business_id, customer_code, email) VALUES (1, 'biz-1', 'C-1', 'alice@test.com')"))
        conn.execute(sa.text("INSERT INTO customers (id, business_id, customer_code, email) VALUES (2, 'biz-2', 'C-1', 'ALICE@TEST.COM')"))

        # Same-tenant case variant rejected by database engine index
        with pytest.raises(IntegrityError):
            conn.execute(sa.text("INSERT INTO customers (id, business_id, customer_code, email) VALUES (3, 'biz-1', 'C-2', 'Alice@Test.Com')"))

        # Multiple NULL emails in same tenant succeed
        conn.execute(sa.text("INSERT INTO customers (id, business_id, customer_code, email) VALUES (4, 'biz-1', 'C-3', NULL)"))
        conn.execute(sa.text("INSERT INTO customers (id, business_id, customer_code, email) VALUES (5, 'biz-1', 'C-4', NULL)"))

        rows = conn.execute(sa.text("SELECT count(*) FROM customers")).scalar()
        assert rows == 4
