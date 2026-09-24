#!/usr/bin/env python3
"""Database seeding utility to populate NEXUS PostgreSQL database with verified synthetic retail data."""

import argparse
import os
import sys
from sqlalchemy import select, func, text

# Ensure backend root is on sys.path
backend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, backend_path)

from app.core.config import settings
from app.core.database import SessionLocal, check_database_connection, engine
from app.models.base import Base
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.inventory import Inventory
from app.models.expense import Expense
from app.data.synthetic.generator import RetailDataGenerator
from app.data.quality.checker import DataQualityChecker


def seed(reset: bool = False, seed_num: int = 42, customers_cnt: int = 800, products_cnt: int = 150, sales_cnt: int = 3500) -> None:
    print("=" * 60)
    print("NEXUS -- Database Seeder")
    print("=" * 60)

    db_check = check_database_connection()
    if db_check.get("status") != "connected":
        print(f"[ERROR] Database connection failed: {db_check.get('error')}")
        print("Please ensure PostgreSQL is running (e.g., docker compose up -d postgres).")
        sys.exit(1)

    print(f"[OK] Database connection verified ({db_check.get('latency_ms')}ms)")

    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        # Check existing row counts
        existing_custs = session.scalar(select(func.count(Customer.id))) or 0
        if existing_custs > 0 and not reset:
            print(f"[INFO] Database already contains {existing_custs} customers. Skipping seed. Use --reset to overwrite.")
            return

        if reset:
            print("[INFO] Resetting existing records...")
            # Truncate tables in reverse dependency order
            session.execute(text("DELETE FROM sale_items"))
            session.execute(text("DELETE FROM sales"))
            session.execute(text("DELETE FROM inventory"))
            session.execute(text("DELETE FROM products"))
            session.execute(text("DELETE FROM customers"))
            session.execute(text("DELETE FROM expenses"))
            session.commit()
            print("[OK] Existing records cleared.")

        print(f"[INFO] Generating synthetic retail dataset (seed={seed_num})...")
        generator = RetailDataGenerator(seed=seed_num)
        data = generator.generate(
            num_customers=customers_cnt,
            num_products=products_cnt,
            num_sales=sales_cnt,
            months_history=18,
        )

        # Pre-seed validation check
        print("[INFO] Auditing generated data quality...")
        checker = DataQualityChecker()
        cust_report = checker.check_records("customers", data["customers"])
        if cust_report.errors_count > 0:
            print(f"[ERROR] Customer data quality check failed with {cust_report.errors_count} errors.")
            sys.exit(1)

        print("[INFO] Batch inserting records into database...")

        # 1. Customers
        session.bulk_insert_mappings(Customer, data["customers"])
        session.flush()

        # 2. Products
        session.bulk_insert_mappings(Product, data["products"])
        session.flush()

        # 3. Inventory
        session.bulk_insert_mappings(Inventory, data["inventory"])
        session.flush()

        # 4. Sales
        session.bulk_insert_mappings(Sale, data["sales"])
        session.flush()

        # 5. Sale Items
        session.bulk_insert_mappings(SaleItem, data["sale_items"])
        session.flush()

        # 6. Expenses
        session.bulk_insert_mappings(Expense, data["expenses"])
        session.commit()

        print("\n" + "=" * 60)
        print("SEEDING SUMMARY")
        print("=" * 60)
        print(f"  Customers:   {len(data['customers']):>6} inserted")
        print(f"  Products:    {len(data['products']):>6} inserted")
        print(f"  Inventory:   {len(data['inventory']):>6} inserted")
        print(f"  Sales:       {len(data['sales']):>6} inserted")
        print(f"  Sale Items:  {len(data['sale_items']):>6} inserted")
        print(f"  Expenses:    {len(data['expenses']):>6} inserted")
        print("=" * 60)
        print("[OK] Database seeded successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed NEXUS PostgreSQL database with synthetic retail data.")
    parser.add_argument("--reset", action="store_true", help="Truncate existing records before seeding")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic generator seed")
    parser.add_argument("--customers", type=int, default=800, help="Customer count")
    parser.add_argument("--products", type=int, default=150, help="Product count")
    parser.add_argument("--sales", type=int, default=3500, help="Sales transactions count")

    args = parser.parse_args()
    seed(
        reset=args.reset,
        seed_num=args.seed,
        customers_cnt=args.customers,
        products_cnt=args.products,
        sales_cnt=args.sales,
    )


if __name__ == "__main__":
    main()
