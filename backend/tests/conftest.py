"""Pytest fixtures and configuration for NEXUS backend test suite."""

import os
import sys
from decimal import Decimal
from datetime import datetime, date, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Ensure backend root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.base import Base
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.inventory import Inventory
from app.models.expense import Expense
from app.main import create_application

# Dedicated in-memory SQLite engine for unit tests
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def get_test_settings() -> Settings:
    """Provide isolated settings for the test runner."""
    return Settings(
        APP_ENV="test",
        DEBUG=False,
        DATABASE_URL=TEST_DB_URL,
        BACKEND_CORS_ORIGINS=["http://localhost:3000"],
    )


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create all schema tables in test database once for the session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def db_session() -> Session:
    """Provide an isolated database session per test function."""
    session = TestingSessionLocal()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()


@pytest.fixture(scope="function")
def seeded_db_session(db_session: Session) -> Session:
    """Populate test database with a small representative retail dataset."""
    for table in reversed(Base.metadata.sorted_tables):
        db_session.execute(table.delete())
    db_session.commit()

    now_utc = datetime.now(timezone.utc)


    # 1. Customer
    cust1 = Customer(
        customer_code="CUST-00001",
        name="Acme Industrial Corp",
        email="purchasing@acme1.com",
        city="Seattle",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 15),
        created_at=now_utc,
        updated_at=now_utc,
    )
    cust2 = Customer(
        customer_code="CUST-00002",
        name="John Retailer",
        email="john@example.com",
        city="Portland",
        customer_segment="Retail",
        acquisition_date=date(2023, 2, 20),
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add_all([cust1, cust2])
    db_session.flush()

    # 2. Products
    p1 = Product(
        sku="SKU-ELE-0001",
        name="Pro Audio Cable #1",
        category="Electronics",
        subcategory="Audio",
        unit_cost=Decimal("15.00"),
        selling_price=Decimal("35.00"),
        active=True,
        created_at=now_utc,
        updated_at=now_utc,
    )
    p2 = Product(
        sku="SKU-OFF-0002",
        name="Desk Organizer Box #2",
        category="Office Supplies",
        subcategory="Desk Organization",
        unit_cost=Decimal("6.00"),
        selling_price=Decimal("18.00"),
        active=True,
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add_all([p1, p2])
    db_session.flush()

    # 3. Inventory
    inv1 = Inventory(
        product_id=p1.id,
        stock_quantity=80,
        reorder_threshold=15,
        warehouse_location="Main Warehouse",
        created_at=now_utc,
        updated_at=now_utc,
    )
    inv2 = Inventory(
        product_id=p2.id,
        stock_quantity=5,  # Low stock
        reorder_threshold=20,
        warehouse_location="Zone B",
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add_all([inv1, inv2])
    db_session.flush()

    # 4. Sales & SaleItems
    s1 = Sale(
        transaction_number="TXN-202305-000001",
        customer_id=cust1.id,
        transaction_date=datetime(2023, 5, 10, 14, 30, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("70.00"),
        discount_amount=Decimal("5.00"),
        tax_amount=Decimal("4.88"),
        total_amount=Decimal("69.88"),
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add(s1)
    db_session.flush()

    item1 = SaleItem(
        sale_id=s1.id,
        product_id=p1.id,
        quantity=2,
        unit_price=Decimal("35.00"),
        discount_amount=Decimal("5.00"),
        line_total=Decimal("65.00"),
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add(item1)

    # 5. Expenses
    exp1 = Expense(
        expense_date=date(2023, 5, 1),
        category="Rent",
        description="Monthly Warehouse Rent",
        amount=Decimal("4500.00"),
        recurring=True,
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add(exp1)

    db_session.commit()
    return db_session


@pytest.fixture(scope="function")
def test_app(db_session: Session):
    """Create and return a configured FastAPI test application with test DB."""
    app = create_application()
    app.dependency_overrides[get_settings] = get_test_settings
    app.dependency_overrides[get_db] = lambda: db_session
    return app


@pytest.fixture(scope="function")
def client(test_app) -> TestClient:
    """Provide a TestClient instance bound to the test application."""
    with TestClient(test_app) as test_client:
        yield test_client
