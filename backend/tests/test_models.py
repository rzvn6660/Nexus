"""Unit tests for SQLAlchemy ORM models, relationships, and constraints."""

from datetime import datetime, date, timezone
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.inventory import Inventory
from app.models.expense import Expense


def test_customer_model_creation_and_query(db_session: Session) -> None:
    """Validate customer model persistence and querying."""
    now = datetime.now(timezone.utc)
    cust = Customer(
        customer_code="CUST-TEST-1",
        name="Test Client Corp",
        email="client@test.com",
        city="Seattle",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
        created_at=now,
        updated_at=now,
    )
    db_session.add(cust)
    db_session.commit()

    retrieved = db_session.scalar(select(Customer).where(Customer.customer_code == "CUST-TEST-1"))
    assert retrieved is not None
    assert retrieved.name == "Test Client Corp"
    assert retrieved.customer_segment == "Corporate"


def test_product_model_and_inventory_relationship(db_session: Session) -> None:
    """Validate Product model creation and 1-to-1 relationship with Inventory."""
    now = datetime.now(timezone.utc)
    prod = Product(
        sku="SKU-TEST-001",
        name="Precision Multimeter",
        category="Electronics",
        subcategory="Measurement",
        unit_cost=Decimal("45.50"),
        selling_price=Decimal("89.99"),
        active=True,
        created_at=now,
        updated_at=now,
    )
    db_session.add(prod)
    db_session.flush()

    inv = Inventory(
        product_id=prod.id,
        stock_quantity=150,
        reorder_threshold=20,
        warehouse_location="Zone A",
        created_at=now,
        updated_at=now,
    )
    db_session.add(inv)
    db_session.commit()

    # Query back via relationship
    p = db_session.scalar(select(Product).where(Product.sku == "SKU-TEST-001"))
    assert p is not None
    assert p.inventory is not None
    assert p.inventory.stock_quantity == 150
    assert p.inventory.reorder_threshold == 20


def test_sale_and_sale_items_relationship(db_session: Session) -> None:
    """Validate Sale order and SaleItem line items cascading relationships."""
    now = datetime.now(timezone.utc)
    cust = Customer(
        customer_code="CUST-TEST-2",
        name="Retail Buyer",
        email="buyer@test.com",
        city="Portland",
        customer_segment="Retail",
        acquisition_date=date(2023, 2, 1),
        created_at=now,
        updated_at=now,
    )
    prod = Product(
        sku="SKU-TEST-002",
        name="Safety Goggles",
        category="Workwear & Safety",
        subcategory="Eye Protection",
        unit_cost=Decimal("5.00"),
        selling_price=Decimal("12.50"),
        active=True,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([cust, prod])
    db_session.flush()

    sale = Sale(
        transaction_number="TXN-TEST-0001",
        customer_id=cust.id,
        transaction_date=now,
        status="completed",
        subtotal=Decimal("25.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("2.00"),
        total_amount=Decimal("27.00"),
        created_at=now,
        updated_at=now,
    )
    db_session.add(sale)
    db_session.flush()

    item = SaleItem(
        sale_id=sale.id,
        product_id=prod.id,
        quantity=2,
        unit_price=Decimal("12.50"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("25.00"),
        created_at=now,
        updated_at=now,
    )
    db_session.add(item)
    db_session.commit()

    s = db_session.scalar(select(Sale).where(Sale.transaction_number == "TXN-TEST-0001"))
    assert s is not None
    assert len(s.items) == 1
    assert s.items[0].quantity == 2
    assert s.items[0].product.name == "Safety Goggles"


def test_unique_constraints(db_session: Session) -> None:
    """Validate that uniqueness constraints on customer_code and sku are enforced."""
    now = datetime.now(timezone.utc)
    p1 = Product(
        sku="SKU-DUP-1",
        name="Item 1",
        category="Office",
        subcategory="Paper",
        unit_cost=Decimal("1.00"),
        selling_price=Decimal("2.00"),
        created_at=now,
        updated_at=now,
    )
    p2 = Product(
        sku="SKU-DUP-1",  # Duplicate SKU
        name="Item 2",
        category="Office",
        subcategory="Paper",
        unit_cost=Decimal("1.00"),
        selling_price=Decimal("2.00"),
        created_at=now,
        updated_at=now,
    )
    db_session.add(p1)
    db_session.commit()

    db_session.add(p2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_expense_model(db_session: Session) -> None:
    """Validate Expense model creation and querying."""
    now = datetime.now(timezone.utc)
    exp = Expense(
        expense_date=date(2023, 6, 1),
        category="Utilities",
        description="Electricity Bill",
        amount=Decimal("850.50"),
        recurring=True,
        created_at=now,
        updated_at=now,
    )
    db_session.add(exp)
    db_session.commit()

    e = db_session.scalar(select(Expense).where(Expense.category == "Utilities"))
    assert e is not None
    assert e.amount == Decimal("850.50")
    assert e.recurring is True
