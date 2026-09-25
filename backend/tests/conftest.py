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

# Ensure backend root and project root are in python path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(backend_dir)
sys.path.insert(0, backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

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
def api_client(db_session: Session) -> TestClient:
    """Provide a TestClient with dependency override to the test db_session."""
    from app.main import app
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


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


@pytest.fixture(scope="function")
def multi_period_db(db_session: Session) -> Session:
    """Populate database with multi-period retail data for financial verification."""
    # Customers
    c1 = Customer(
        customer_code="CUST-001",
        name="Corp Buyer A",
        email="buyer@corpa.com",
        city="Seattle",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 10),
    )
    c2 = Customer(
        customer_code="CUST-002",
        name="Retail Buyer B",
        email="buyer@retailb.com",
        city="Portland",
        customer_segment="Retail",
        acquisition_date=date(2023, 2, 15),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    # Products
    p1 = Product(
        sku="SKU-A",
        name="Widget A",
        category="Hardware",
        subcategory="Tools",
        unit_cost=Decimal("15.00"),
        selling_price=Decimal("35.00"),
        active=True,
    )
    p2 = Product(
        sku="SKU-B",
        name="Gadget B",
        category="Electronics",
        subcategory="Accessories",
        unit_cost=Decimal("6.00"),
        selling_price=Decimal("18.00"),
        active=True,
    )
    db_session.add_all([p1, p2])
    db_session.flush()

    # Inventory
    inv1 = Inventory(
        product_id=p1.id,
        stock_quantity=50,
        reorder_threshold=10,
        warehouse_location="Warehouse North",
    )
    inv2 = Inventory(
        product_id=p2.id,
        stock_quantity=3,
        reorder_threshold=10,
        warehouse_location="Warehouse South",
    )
    db_session.add_all([inv1, inv2])
    db_session.flush()

    # May 2023 (Baseline period)
    s1 = Sale(
        transaction_number="TXN-202305-01",
        customer_id=c1.id,
        transaction_date=datetime(2023, 5, 10, 10, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("70.00"),
        discount_amount=Decimal("5.00"),
        tax_amount=Decimal("5.20"),
        total_amount=Decimal("70.20"),
    )
    db_session.add(s1)
    db_session.flush()
    i1 = SaleItem(
        sale_id=s1.id,
        product_id=p1.id,
        quantity=2,
        unit_price=Decimal("35.00"),
        discount_amount=Decimal("5.00"),
        line_total=Decimal("65.00"),
    )
    db_session.add(i1)

    s2 = Sale(
        transaction_number="TXN-202305-02",
        customer_id=c2.id,
        transaction_date=datetime(2023, 5, 20, 14, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("90.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("7.20"),
        total_amount=Decimal("97.20"),
    )
    db_session.add(s2)
    db_session.flush()
    i2 = SaleItem(
        sale_id=s2.id,
        product_id=p2.id,
        quantity=5,
        unit_price=Decimal("18.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("90.00"),
    )
    db_session.add(i2)

    # June 2023 (Current period)
    s3 = Sale(
        transaction_number="TXN-202306-01",
        customer_id=c1.id,
        transaction_date=datetime(2023, 6, 5, 11, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("140.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("11.20"),
        total_amount=Decimal("151.20"),
    )
    db_session.add(s3)
    db_session.flush()
    i3 = SaleItem(
        sale_id=s3.id,
        product_id=p1.id,
        quantity=4,
        unit_price=Decimal("35.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("140.00"),
    )
    db_session.add(i3)

    s4 = Sale(
        transaction_number="TXN-202306-02",
        customer_id=c1.id,
        transaction_date=datetime(2023, 6, 20, 16, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("200.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("16.00"),
        total_amount=Decimal("216.00"),
    )
    db_session.add(s4)
    db_session.flush()
    i4 = SaleItem(
        sale_id=s4.id,
        product_id=p2.id,
        quantity=10,
        unit_price=Decimal("20.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("200.00"),
    )
    db_session.add(i4)

    # Operating Expenses
    exp_may = Expense(
        expense_date=date(2023, 5, 1),
        category="Rent",
        description="May Rent",
        amount=Decimal("100.00"),
        recurring=True,
    )
    exp_june = Expense(
        expense_date=date(2023, 6, 1),
        category="Rent",
        description="June Rent",
        amount=Decimal("120.00"),
        recurring=True,
    )
    db_session.add_all([exp_may, exp_june])
    db_session.commit()
    return db_session


@pytest.fixture(scope="function")
def predictive_db_session(db_session: Session) -> Session:
    """Populate database with 12 consecutive months of retail sales for forecasting tests."""
    for table in reversed(Base.metadata.sorted_tables):
        db_session.execute(table.delete())
    db_session.commit()

    c = Customer(
        customer_code="CUST-PRED-1",
        name="Predictive Test Retailer",
        email="test_pred@example.com",
        city="New York",
        customer_segment="Regular",
        acquisition_date=date(2023, 1, 15),
    )
    db_session.add(c)
    db_session.flush()

    p1 = Product(
        sku="SKU-PROD-A",
        name="Predictive Widget Alpha",
        category="Electronics",
        subcategory="Gadgets",
        unit_cost=Decimal("20.00"),
        selling_price=Decimal("50.00"),
        active=True,
    )
    p2 = Product(
        sku="SKU-PROD-B",
        name="Predictive Widget Beta",
        category="Hardware",
        subcategory="Tools",
        unit_cost=Decimal("10.00"),
        selling_price=Decimal("25.00"),
        active=True,
    )
    db_session.add_all([p1, p2])
    db_session.flush()

    # Create sales across 12 consecutive months (2023-01 to 2023-12)
    # Base pattern with steady trend and slight variance
    base_qty_p1 = [10, 12, 14, 15, 18, 20, 22, 24, 25, 28, 30, 32]
    base_qty_p2 = [20, 22, 21, 25, 24, 28, 30, 31, 33, 35, 38, 40]

    for month_idx in range(1, 13):
        # Transaction on the 10th of each month
        dt = datetime(2023, month_idx, 10, 12, 0, tzinfo=timezone.utc)
        qty1 = base_qty_p1[month_idx - 1]
        qty2 = base_qty_p2[month_idx - 1]

        subtotal1 = Decimal(str(qty1 * 50))
        subtotal2 = Decimal(str(qty2 * 25))
        total_subtotal = subtotal1 + subtotal2

        s = Sale(
            transaction_number=f"TXN-PRED-2023{month_idx:02d}",
            customer_id=c.id,
            transaction_date=dt,
            status="completed",
            subtotal=total_subtotal,
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal(str(round(float(total_subtotal) * 0.08, 2))),
            total_amount=Decimal(str(round(float(total_subtotal) * 1.08, 2))),
        )
        db_session.add(s)
        db_session.flush()

        item1 = SaleItem(
            sale_id=s.id,
            product_id=p1.id,
            quantity=qty1,
            unit_price=Decimal("50.00"),
            discount_amount=Decimal("0.00"),
            line_total=subtotal1,
        )
        item2 = SaleItem(
            sale_id=s.id,
            product_id=p2.id,
            quantity=qty2,
            unit_price=Decimal("25.00"),
            discount_amount=Decimal("0.00"),
            line_total=subtotal2,
        )
        db_session.add_all([item1, item2])

    db_session.commit()
    return db_session

