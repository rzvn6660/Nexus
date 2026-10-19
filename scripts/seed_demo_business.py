#!/usr/bin/env python3
"""NEXUS Demo Business Seeder.

Safely and idempotently provisions a demo retail organization, owner identity,
canonical retail dataset from data/sample/, and active semantic model in an
explicitly configured disposable/demo PostgreSQL database.

Safety requirements:
- Fails closed on any production target (APP_ENV=production, prod hostname/dbname).
- Requires explicit --confirm-disposable flag.
- Idempotent: checks for existing demo organization and skips without destructive resets.
- Uses existing sample files in data/sample/.
- Generates or accepts secure owner credentials without hardcoding secrets.
"""

import argparse
import io
import os
import secrets
import sys
from pathlib import Path
from typing import Dict, Any
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

# Ensure project root and backend dir are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.core.database import _get_engine_kwargs
from app.services.auth_service import AuthService
from app.services.data_gateway_service import DataGatewayService
from app.services.tenant_semantic_service import TenantSemanticService
from app.models.tenant import Organization, Business, UserIdentity, OrganizationMembership
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem


DEMO_ORG_SLUG = "demo-retail-corp"
DEMO_ORG_NAME = "NEXUS Demo Retail Corp"
DEMO_BIZ_NAME = "Apex Outfitters Demo Store"
DEMO_PREFIX = "DEMO_"


def is_production_target(db_url: str) -> bool:
    """Detect whether target database or environment indicates production."""
    if getattr(settings, "is_production", False) or (os.getenv("APP_ENV") or settings.APP_ENV or "").lower() in ("production", "prod"):
        return True

    parsed = urlparse(db_url)
    hostname = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    prod_markers = ("prod", "production", "live", "nexus-primary")
    for marker in prod_markers:
        if marker in hostname or marker in path:
            return True

    return False


def seed_demo_business(
    db_url: str,
    owner_email: str = "demo.owner@nexus.local",
    owner_password: str | None = None,
    confirm_disposable: bool = False,
) -> Dict[str, Any]:
    print("=" * 65)
    print("NEXUS Demo Business Seeder")
    print("Where Business Data Becomes Intelligence.")
    print("=" * 65)

    if not confirm_disposable:
        print("[FAIL] Missing required confirmation flag: --confirm-disposable", file=sys.stderr)
        print("This safety guard ensures demo seeding is only executed against disposable targets.", file=sys.stderr)
        sys.exit(1)

    clean_url = db_url
    if clean_url.startswith("postgresql://"):
        clean_url = clean_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif clean_url.startswith("postgres://"):
        clean_url = clean_url.replace("postgres://", "postgresql+psycopg://", 1)

    if is_production_target(clean_url):
        print(f"[FAIL] ABORTED: Target database appears to be a PRODUCTION database: {clean_url}", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(clean_url, **_get_engine_kwargs())
    if engine.dialect.name != "postgresql":
        print(f"[FAIL] ABORTED: Engine dialect is '{engine.dialect.name}'. PostgreSQL 16+ is required.", file=sys.stderr)
        sys.exit(1)

    sample_dir = PROJECT_ROOT / "data" / "sample"
    if not sample_dir.exists():
        print(f"[FAIL] Sample data directory not found at: {sample_dir}", file=sys.stderr)
        sys.exit(1)

    with Session(engine) as session:
        # Check idempotency: does demo org already exist?
        existing_org = session.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
        if existing_org:
            existing_biz = session.scalar(select(Business).where(Business.organization_id == existing_org.id))
            if existing_biz:
                sales_count = session.scalar(select(func.count(Sale.id)).where(Sale.business_id == existing_biz.id)) or 0
                if sales_count > 0:
                    print(f"[INFO] Demo organization already seeded:")
                    print(f"       Org ID:      {existing_org.id}")
                    print(f"       Business ID: {existing_biz.id}")
                    print(f"       Sales Count: {sales_count}")
                    print("[INFO] Seeder is idempotent and will not duplicate existing records.")
                    return {
                        "status": "already_seeded",
                        "organization_id": existing_org.id,
                        "business_id": existing_biz.id,
                    }

        generated_pass = False
        if not owner_password:
            owner_password = secrets.token_urlsafe(16)
            generated_pass = True

        print(f"[INFO] Creating demo organization '{DEMO_ORG_NAME}'...")
        org = Organization(
            id=f"org_demo_{secrets.token_hex(4)}",
            name=DEMO_ORG_NAME,
            slug=DEMO_ORG_SLUG,
        )
        session.add(org)
        session.flush()

        biz = Business(
            id=f"biz_demo_{secrets.token_hex(4)}",
            organization_id=org.id,
            name=DEMO_BIZ_NAME,
            status="active",
        )
        session.add(biz)
        session.flush()

        # Check existing user
        user = session.scalar(select(UserIdentity).where(UserIdentity.email == owner_email))
        if not user:
            user = UserIdentity(
                id=f"usr_demo_{secrets.token_hex(4)}",
                email=owner_email,
                full_name="Demo Business Owner",
                password_hash=AuthService.hash_password(owner_password),
                is_active=True,
                is_verified=True,
            )
            session.add(user)
            session.flush()

        mem = session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.organization_id == org.id,
            )
        )
        if not mem:
            mem = OrganizationMembership(
                user_id=user.id,
                organization_id=org.id,
                role="owner",
            )
            session.add(mem)
            session.flush()

        print(f"[INFO] Loading and ingesting sample retail datasets from {sample_dir}...")
        # Supported transformations for multi-tenant isolation:
        # 1. products.csv: prefix SKU
        df_prod = pd.read_csv(sample_dir / "products.csv")
        prod_id_to_sku = dict(zip(df_prod["id"], df_prod["sku"]))
        df_prod["sku"] = DEMO_PREFIX + df_prod["sku"].astype(str)
        prod_bytes = df_prod.to_csv(index=False).encode("utf-8")

        # 2. customers.csv: prefix id, customer_code, email
        df_cust = pd.read_csv(sample_dir / "customers.csv")
        df_cust["id"] = DEMO_PREFIX + df_cust["id"].astype(str)
        df_cust["customer_code"] = DEMO_PREFIX + df_cust["customer_code"].astype(str)
        df_cust["email"] = DEMO_PREFIX.lower() + df_cust["email"].astype(str)
        cust_bytes = df_cust.to_csv(index=False).encode("utf-8")

        # 3. inventory.csv: map product_id to matching SKU
        df_inv = pd.read_csv(sample_dir / "inventory.csv")
        df_inv["sku"] = df_inv["product_id"].map(lambda pid: DEMO_PREFIX + str(prod_id_to_sku[pid]))
        inv_bytes = df_inv.to_csv(index=False).encode("utf-8")

        # 4. expenses.csv
        df_exp = pd.read_csv(sample_dir / "expenses.csv")
        exp_bytes = df_exp.to_csv(index=False).encode("utf-8")

        # 5. sales.csv: prefix transaction_number
        df_sales = pd.read_csv(sample_dir / "sales.csv")
        sale_id_to_txn = dict(zip(df_sales["id"], df_sales["transaction_number"]))
        df_sales["transaction_number"] = DEMO_PREFIX + df_sales["transaction_number"].astype(str)
        sales_bytes = df_sales.to_csv(index=False).encode("utf-8")

        # 6. sale_items.csv: resolve natural keys using transaction_number and product SKU
        df_items = pd.read_csv(sample_dir / "sale_items.csv")
        df_items["transaction_number"] = df_items["sale_id"].map(lambda sid: DEMO_PREFIX + str(sale_id_to_txn[sid]))
        df_items["sku"] = df_items["product_id"].map(lambda pid: DEMO_PREFIX + str(prod_id_to_sku[pid]))
        df_items_clean = df_items.drop(columns=["sale_id", "product_id"])
        items_bytes = df_items_clean.to_csv(index=False).encode("utf-8")

        files_to_ingest = [
            ("products.csv", prod_bytes, "Product", {}),
            ("customers.csv", cust_bytes, "Customer", {"customer_code": "customer_code"}),
            ("inventory.csv", inv_bytes, "Inventory", {"sku": "sku", "product_id": "ignore"}),
            ("expenses.csv", exp_bytes, "Expense", {}),
            ("sales.csv", sales_bytes, "Sale", {
                "transaction_number": "order_number",
                "subtotal": "amount",
                "transaction_date": "date",
            }),
            ("sale_items.csv", items_bytes, "SaleItem", {
                "transaction_number": "sale_id",
                "sku": "product_id",
                "quantity": "quantity",
                "unit_price": "unit_price",
                "discount_amount": "discount_amount",
                "line_total": "line_total",
            }),
        ]

        last_dataset = None
        for filename, file_content, entity, overrides in files_to_ingest:
            dataset_rec = DataGatewayService.save_raw_dataset(
                db=session,
                organization_id=org.id,
                business_id=biz.id,
                filename=filename,
                content=file_content,
            )
            session.commit()
            last_dataset = dataset_rec

            ingest_res = DataGatewayService.ingest_into_core_models(
                db=session,
                dataset_id=dataset_rec.id,
                business_id=biz.id,
                target_entity=entity,
                column_overrides=overrides,
            )
            print(f"       Ingested {filename:<14} -> {entity:<10} ({ingest_res.get('records_persisted', 0)} rows)")

        # Activate semantic model
        print("[INFO] Generating and activating canonical semantic model...")
        semantic_model = TenantSemanticService.generate_business_understanding(
            business_id=biz.id,
            organization_id=org.id,
            db=session,
        )
        session.commit()

        # Query summary metrics
        total_customers = session.scalar(select(func.count(Customer.id)).where(Customer.business_id == biz.id))
        total_products = session.scalar(select(func.count(Product.id)).where(Product.business_id == biz.id))
        total_sales = session.scalar(select(func.count(Sale.id)).where(Sale.business_id == biz.id))
        completed_sales = session.scalar(select(func.count(Sale.id)).where(Sale.business_id == biz.id, Sale.status.in_(["completed", "shipped"]))) or 0
        net_sales = session.scalar(select(func.sum(Sale.subtotal - Sale.discount_amount)).where(Sale.business_id == biz.id, Sale.status.in_(["completed", "shipped"]))) or 0.0
        tax_amount = session.scalar(select(func.sum(Sale.tax_amount)).where(Sale.business_id == biz.id, Sale.status.in_(["completed", "shipped"]))) or 0.0
        total_billed = session.scalar(select(func.sum(Sale.total_amount)).where(Sale.business_id == biz.id, Sale.status.in_(["completed", "shipped"]))) or 0.0

        print("\n" + "=" * 65)
        print("DEMO BUSINESS SEEDING COMPLETED SUCCESSFULLY")
        print("=" * 65)
        print(f"  Organization ID:       {org.id}")
        print(f"  Organization Name:     {org.name}")
        print(f"  Business ID:           {biz.id}")
        print(f"  Business Name:         {biz.name}")
        print(f"  Owner Email:           {owner_email}")
        if generated_pass:
            print(f"  Owner Password:        {owner_password}  <-- Save this password")
        else:
            print(f"  Owner Password:        [CONFIGURED VIA CLI ARGUMENT]")
        print("-" * 65)
        print(f"  Customers:             {total_customers}")
        print(f"  Products:              {total_products}")
        print(f"  Total Ingested Orders: {total_sales}")
        print(f"  Completed Orders:      {completed_sales}")
        print(f"  Net Commercial Sales:  ${float(net_sales):,.2f}")
        print(f"  Sales Tax Liability:   ${float(tax_amount):,.2f}")
        print(f"  Total Billed:          ${float(total_billed):,.2f}")
        print(f"  Semantic Model:        Version {semantic_model.version} ({semantic_model.status})")
        print("=" * 65)

        return {
            "status": "success",
            "organization_id": org.id,
            "business_id": biz.id,
            "owner_email": owner_email,
            "sales_count": total_sales,
            "completed_sales_count": completed_sales,
            "net_sales": float(net_sales),
            "tax_amount": float(tax_amount),
            "total_billed": float(total_billed),
        }


def main():
    parser = argparse.ArgumentParser(description="NEXUS Demo Business Seeder")
    parser.add_argument("--db-url", type=str, default=None, help="PostgreSQL connection URL (or defaults to TEST_DATABASE_URL/DATABASE_URL)")
    parser.add_argument("--confirm-disposable", action="store_true", default=False, help="Explicit confirmation that target DB is disposable/demo")
    parser.add_argument("--owner-email", type=str, default="demo.owner@nexus.local", help="Demo owner email")
    parser.add_argument("--owner-password", type=str, default=None, help="Demo owner password (auto-generated if omitted)")
    args = parser.parse_args()

    db_url = args.db_url or os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("[FAIL] No database URL provided or found in environment (DATABASE_URL / TEST_DATABASE_URL).", file=sys.stderr)
        sys.exit(1)

    seed_demo_business(
        db_url=db_url,
        owner_email=args.owner_email,
        owner_password=args.owner_password,
        confirm_disposable=args.confirm_disposable,
    )


if __name__ == "__main__":
    main()
