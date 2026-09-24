"""Unit tests for the synthetic retail data generator."""

from decimal import Decimal
from datetime import date
from app.data.synthetic.generator import RetailDataGenerator


def test_generator_reproducibility() -> None:
    """Validate that identical seed produces byte-for-byte identical output."""
    gen1 = RetailDataGenerator(seed=123)
    data1 = gen1.generate(num_customers=50, num_products=20, num_sales=50, months_history=3)

    gen2 = RetailDataGenerator(seed=123)
    data2 = gen2.generate(num_customers=50, num_products=20, num_sales=50, months_history=3)

    # Validate customers match
    assert len(data1["customers"]) == len(data2["customers"])
    for c1, c2 in zip(data1["customers"], data2["customers"]):
        assert c1["customer_code"] == c2["customer_code"]
        assert c1["name"] == c2["name"]
        assert c1["email"] == c2["email"]

    # Validate sales match
    assert len(data1["sales"]) == len(data2["sales"])
    for s1, s2 in zip(data1["sales"], data2["sales"]):
        assert s1["transaction_number"] == s2["transaction_number"]
        assert s1["total_amount"] == s2["total_amount"]
        assert s1["subtotal"] == s2["subtotal"]


def test_generator_different_seeds() -> None:
    """Validate that different seeds produce distinct datasets."""
    gen1 = RetailDataGenerator(seed=101)
    data1 = gen1.generate(num_customers=30, num_products=10, num_sales=30, months_history=3)

    gen2 = RetailDataGenerator(seed=202)
    data2 = gen2.generate(num_customers=30, num_products=10, num_sales=30, months_history=3)

    assert data1["customers"][0]["name"] != data2["customers"][0]["name"]
    assert data1["sales"][0]["total_amount"] != data2["sales"][0]["total_amount"]


def test_generator_configurable_sizes() -> None:
    """Validate that requested entity counts are accurately respected."""
    gen = RetailDataGenerator(seed=42)
    data = gen.generate(num_customers=40, num_products=15, num_sales=45, months_history=6)

    assert len(data["customers"]) == 40
    assert len(data["products"]) == 15
    assert len(data["inventory"]) == 15
    assert len(data["sales"]) == 45
    assert len(data["sale_items"]) >= 45  # At least 1 item per sale
    assert len(data["expenses"]) > 0


def test_generator_financial_reconciliation() -> None:
    """Validate that line_total and order total math reconciles exactly."""
    gen = RetailDataGenerator(seed=42)
    data = gen.generate(num_customers=20, num_products=10, num_sales=30, months_history=3)

    # Check sale_items line_total reconciliation
    for item in data["sale_items"]:
        qty = Decimal(str(item["quantity"]))
        unit_price = Decimal(str(item["unit_price"]))
        discount = Decimal(str(item["discount_amount"]))
        expected_line = (qty * unit_price) - discount
        assert item["line_total"] == expected_line
        assert item["line_total"] >= 0

    # Check sales total reconciliation
    for sale in data["sales"]:
        subtotal = Decimal(str(sale["subtotal"]))
        discount = Decimal(str(sale["discount_amount"]))
        tax = Decimal(str(sale["tax_amount"]))
        expected_total = subtotal - discount + tax
        assert abs(sale["total_amount"] - expected_total) <= Decimal("0.01")
        assert sale["total_amount"] >= 0
