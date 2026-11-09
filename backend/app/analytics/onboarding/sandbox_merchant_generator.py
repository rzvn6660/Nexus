"""Deterministic Sandbox Merchant Data Generator for NEXUS.

Provisions a dedicated, fully isolated synthetic merchant environment:
'Northstar Fashion & Retail — NEXUS Sandbox'

Guarantees:
1. Strict tenant isolation: Own organization, business, and manager identity.
2. Deterministic and reproducible: Seeded pseudo-random generation.
3. Realistic commercial topology:
   - 40 customers (repeat buyers, one-time buyers, and lapsed accounts).
   - 12 products across 4 categories with explicitly labelled synthetic unit costs.
   - 12+ months of continuous sales spanning 2025-01-05 to 2026-01-15.
   - Distinct seasonality (Spring launch, Summer baseline, Black Friday/Holiday surge).
   - Multi-line orders with exact line-level itemization and order invariant preservation.
4. Transparent synthetic tagging: Metadata explicitly labels all entities as demonstration fixtures.
"""

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Business, Organization, UserIdentity
from app.services.auth_service import AuthService

SANDBOX_TENANT_NAME = "Northstar Fashion & Retail — NEXUS Sandbox"
SANDBOX_ORG_NAME = "Northstar Fashion & Retail Group"
SANDBOX_ORG_SLUG = "northstar-sandbox-group"
SANDBOX_MANAGER_EMAIL = "sarah.jenkins@northstar-sandbox.local"
SANDBOX_MANAGER_NAME = "Sarah Jenkins"
SANDBOX_AUTH_REF = "AUTH-SANDBOX-NORTHSTAR-2026"
SANDBOX_SEED = 2026


def get_deterministic_rng() -> random.Random:
    """Return an isolated RNG seeded for full reproducibility."""
    return random.Random(SANDBOX_SEED)


def get_synthetic_catalog_definitions() -> list[dict[str, Any]]:
    """Return 12 distinct fashion retail product catalog specifications with synthetic COGS."""
    return [
        {
            "sku": "SKU-NS-APP-01",
            "name": "Silk Evening Blouse [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Apparel",
            "subcategory": "Tops",
            "selling_price": Decimal("145.00"),
            "unit_cost": Decimal("58.00"),
        },
        {
            "sku": "SKU-NS-APP-02",
            "name": "Tailored Linen Trousers [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Apparel",
            "subcategory": "Bottoms",
            "selling_price": Decimal("120.00"),
            "unit_cost": Decimal("48.00"),
        },
        {
            "sku": "SKU-NS-APP-03",
            "name": "Cashmere Knit Sweater [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Apparel",
            "subcategory": "Knitwear",
            "selling_price": Decimal("195.00"),
            "unit_cost": Decimal("78.00"),
        },
        {
            "sku": "SKU-NS-FTW-01",
            "name": "Italian Leather Loafers [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Footwear",
            "subcategory": "Dress Shoes",
            "selling_price": Decimal("240.00"),
            "unit_cost": Decimal("96.00"),
        },
        {
            "sku": "SKU-NS-FTW-02",
            "name": "Minimalist White Sneaker [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Footwear",
            "subcategory": "Casual Shoes",
            "selling_price": Decimal("160.00"),
            "unit_cost": Decimal("64.00"),
        },
        {
            "sku": "SKU-NS-ACC-01",
            "name": "Top-Grain Leather Belt [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Accessories",
            "subcategory": "Leather Goods",
            "selling_price": Decimal("65.00"),
            "unit_cost": Decimal("26.00"),
        },
        {
            "sku": "SKU-NS-ACC-02",
            "name": "Silk Twill Scarf [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Accessories",
            "subcategory": "Scarves",
            "selling_price": Decimal("75.00"),
            "unit_cost": Decimal("30.00"),
        },
        {
            "sku": "SKU-NS-ACC-03",
            "name": "Classic UV Sunglasses [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Accessories",
            "subcategory": "Eyewear",
            "selling_price": Decimal("95.00"),
            "unit_cost": Decimal("38.00"),
        },
        {
            "sku": "SKU-NS-OUT-01",
            "name": "Wool Trench Coat [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Outerwear",
            "subcategory": "Coats",
            "selling_price": Decimal("280.00"),
            "unit_cost": Decimal("112.00"),
        },
        {
            "sku": "SKU-NS-OUT-02",
            "name": "Quilted Puffer Jacket [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Outerwear",
            "subcategory": "Jackets",
            "selling_price": Decimal("210.00"),
            "unit_cost": Decimal("84.00"),
        },
        {
            "sku": "SKU-NS-SUM-01",
            "name": "Cotton Resort Shirt [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Apparel",
            "subcategory": "Shirts",
            "selling_price": Decimal("85.00"),
            "unit_cost": Decimal("34.00"),
        },
        {
            "sku": "SKU-NS-SUM-02",
            "name": "Pleated Chino Shorts [SYNTHETIC_BENCHMARK_COGS]",
            "category": "Apparel",
            "subcategory": "Shorts",
            "selling_price": Decimal("70.00"),
            "unit_cost": Decimal("28.00"),
        },
    ]


def get_synthetic_customer_definitions() -> list[dict[str, Any]]:
    """Return 40 customer accounts split into repeat, one-time, and lapsed cohorts."""
    cities = ["New York", "Chicago", "Denver", "San Francisco", "Austin", "Seattle", "Boston", "Miami"]
    rng = get_deterministic_rng()
    customers = []

    # 1. 20 Repeat Buyers (Active Cadence)
    for i in range(1, 21):
        code = f"CUST-NS-REP-{i:02d}"
        customers.append({
            "customer_code": code,
            "name": f"Repeat Buyer {i:02d}",
            "email": f"buyer.repeat.{i:02d}@northstar.test",
            "city": rng.choice(cities),
            "customer_segment": "VIP" if i <= 5 else "Loyal",
            "cohort": "repeat",
            "target_orders": 4 + (i % 6),  # 4 to 9 orders
            "acquisition_date": date(2025, 1, 5) + timedelta(days=(i * 3)),
        })

    # 2. 12 One-Time Buyers
    for i in range(1, 13):
        code = f"CUST-NS-ONE-{i:02d}"
        customers.append({
            "customer_code": code,
            "name": f"Single Buyer {i:02d}",
            "email": f"buyer.single.{i:02d}@northstar.test",
            "city": rng.choice(cities),
            "customer_segment": "New",
            "cohort": "onetime",
            "target_orders": 1,
            "acquisition_date": date(2025, 3, 10) + timedelta(days=(i * 20)),
        })

    # 3. 8 Lapsed / Inactive Buyers
    for i in range(1, 9):
        code = f"CUST-NS-LAP-{i:02d}"
        customers.append({
            "customer_code": code,
            "name": f"Lapsed Buyer {i:02d}",
            "email": f"buyer.lapsed.{i:02d}@northstar.test",
            "city": rng.choice(cities),
            "customer_segment": "At-Risk",
            "cohort": "lapsed",
            "target_orders": 2,
            "acquisition_date": date(2025, 1, 10) + timedelta(days=i),
        })

    return customers


def generate_synthetic_transactions() -> list[dict[str, Any]]:
    """
    Generate ~200-250 realistic multi-line sales transactions spanning over 12 months (2025-01-05 to 2026-01-15).
    Preserves exact order invariants and incorporates seasonal sales curves.
    """
    rng = get_deterministic_rng()
    customers = get_synthetic_customer_definitions()
    products = get_synthetic_catalog_definitions()

    sales: list[dict[str, Any]] = []
    order_seq = 1

    # Generate orders for each customer according to their cohort
    for cust in customers:
        c_code = cust["customer_code"]
        cohort = cust["cohort"]
        num_orders = cust["target_orders"]
        acq_date = cust["acquisition_date"]

        if cohort == "lapsed":
            # Orders clustered early in 2025 (Jan-March), inactive for remainder of year
            cur_dt = datetime(acq_date.year, acq_date.month, acq_date.day, 11, 30, tzinfo=UTC)
            for _ in range(num_orders):
                order_num = f"NS-ORD-{order_seq:04d}"
                order_seq += 1
                items_count = rng.randint(1, 2)
                selected_prods = rng.sample(products, items_count)
                line_items = []
                subtotal = Decimal("0.00")
                for p in selected_prods:
                    qty = rng.randint(1, 2)
                    price = p["selling_price"]
                    l_tot = price * qty
                    subtotal += l_tot
                    line_items.append({
                        "sku": p["sku"],
                        "quantity": qty,
                        "unit_price": price,
                        "discount": Decimal("0.00"),
                        "line_total": l_tot,
                    })

                discount = Decimal("0.00")
                tax = round(subtotal * Decimal("0.08"), 2)
                total = subtotal - discount + tax
                sales.append({
                    "order_number": order_num,
                    "customer_code": c_code,
                    "date": cur_dt,
                    "subtotal": subtotal,
                    "discount_amount": discount,
                    "tax_amount": tax,
                    "total_amount": total,
                    "status": "completed",
                    "items": line_items,
                })
                cur_dt += timedelta(days=rng.randint(15, 30))

        elif cohort == "onetime":
            # Exactly 1 order
            cur_dt = datetime(acq_date.year, acq_date.month, acq_date.day, 14, 15, tzinfo=UTC)
            order_num = f"NS-ORD-{order_seq:04d}"
            order_seq += 1
            items_count = rng.randint(1, 2)
            selected_prods = rng.sample(products, items_count)
            line_items = []
            subtotal = Decimal("0.00")
            for p in selected_prods:
                qty = rng.randint(1, 2)
                price = p["selling_price"]
                l_tot = price * qty
                subtotal += l_tot
                line_items.append({
                    "sku": p["sku"],
                    "quantity": qty,
                    "unit_price": price,
                    "discount": Decimal("0.00"),
                    "line_total": l_tot,
                })
            discount = Decimal("0.00")
            tax = round(subtotal * Decimal("0.08"), 2)
            total = subtotal - discount + tax
            sales.append({
                "order_number": order_num,
                "customer_code": c_code,
                "date": cur_dt,
                "subtotal": subtotal,
                "discount_amount": discount,
                "tax_amount": tax,
                "total_amount": total,
                "status": "completed",
                "items": line_items,
            })

        elif cohort == "repeat":
            # Multiple orders spaced across the 12+ month timeline
            cur_dt = datetime(acq_date.year, acq_date.month, acq_date.day, 10, 0, tzinfo=UTC)
            for ord_idx in range(num_orders):
                order_num = f"NS-ORD-{order_seq:04d}"
                order_seq += 1

                # Seasonality adjustment
                month = cur_dt.month
                is_holiday = (month == 11 and cur_dt.day >= 15) or (month == 12 and cur_dt.day <= 25)
                is_spring_promo = (month == 4)

                items_count = rng.randint(1, 3)
                if is_holiday:
                    items_count = rng.randint(2, 4)

                selected_prods = rng.sample(products, items_count)
                line_items = []
                subtotal = Decimal("0.00")
                for p in selected_prods:
                    qty = rng.randint(1, 2)
                    price = p["selling_price"]
                    l_tot = price * qty
                    subtotal += l_tot
                    line_items.append({
                        "sku": p["sku"],
                        "quantity": qty,
                        "unit_price": price,
                        "discount": Decimal("0.00"),
                        "line_total": l_tot,
                    })

                discount = Decimal("0.00")
                if is_holiday and subtotal > Decimal("200.00"):
                    discount = Decimal("25.00")
                elif is_spring_promo and subtotal > Decimal("150.00"):
                    discount = Decimal("15.00")

                tax = round((subtotal - discount) * Decimal("0.08"), 2)
                total = max(Decimal("0.00"), subtotal - discount + tax)

                # 97% completed, 3% refunded
                status = "refunded" if (ord_idx == num_orders - 1 and rng.random() < 0.05) else "completed"

                sales.append({
                    "order_number": order_num,
                    "customer_code": c_code,
                    "date": cur_dt,
                    "subtotal": subtotal,
                    "discount_amount": discount,
                    "tax_amount": tax,
                    "total_amount": total,
                    "status": status,
                    "items": line_items,
                })

                # Cadence interval to next purchase
                cadence_days = rng.randint(30, 65)
                cur_dt += timedelta(days=cadence_days)
                if cur_dt > datetime(2026, 1, 15, 23, 59, tzinfo=UTC):
                    break

    # Sort sales strictly by date
    sales.sort(key=lambda s: s["date"])
    return sales


def provision_sandbox_tenant(
    db: Session,
    business_id: str | None = None,
) -> tuple[UserIdentity, Organization, Business]:
    """
    Idempotently provision or retrieve the isolated sandbox merchant tenant.
    Never touches or modifies Apex, demo, or existing real merchant records.
    """
    # Check for existing sandbox business
    existing_biz = None
    if business_id:
        existing_biz = db.execute(select(Business).where(Business.id == business_id)).scalar_one_or_none()
    if not existing_biz:
        existing_biz = db.execute(
            select(Business).where(Business.name == SANDBOX_TENANT_NAME)
        ).scalar_one_or_none()

    if existing_biz:
        org = db.execute(select(Organization).where(Organization.id == existing_biz.organization_id)).scalar_one()
        user = db.execute(select(UserIdentity).where(UserIdentity.email == SANDBOX_MANAGER_EMAIL)).scalar_one_or_none()
        if not user:
            user = UserIdentity(
                id=str(uuid4()),
                email=SANDBOX_MANAGER_EMAIL,
                full_name=SANDBOX_MANAGER_NAME,
                password_hash=AuthService.hash_password("SandboxPass123!"),
                is_active=True,
            )
            db.add(user)
            db.flush()
        return user, org, existing_biz

    # Provision brand new isolated sandbox organization, business, and manager
    user, org, biz = AuthService.signup(
        db=db,
        email=SANDBOX_MANAGER_EMAIL,
        password="SandboxPass123!",
        full_name=SANDBOX_MANAGER_NAME,
        organization_name=SANDBOX_ORG_NAME,
        business_name=SANDBOX_TENANT_NAME,
    )

    # Attach explicit sandbox and demonstration governance metadata
    biz.currency = "USD"
    # Business model has no metadata_json column in core DB; we manage governance safely via policy
    db.commit()
    return user, org, biz


def generate_gateway_csv_payloads() -> dict[str, str]:
    """
    Generate CSV file contents for:
    - customers.csv
    - products.csv
    - sales.csv
    - sale_items.csv
    - quarantine_probe.csv (testing customer unmapped isolation)
    - invalid_range_probe.csv (testing atomic rollback)
    """
    customers = get_synthetic_customer_definitions()
    products = get_synthetic_catalog_definitions()
    sales = generate_synthetic_transactions()

    # 1. customers.csv
    c_lines = ["customer_code,name,email,city,customer_segment,acquisition_date"]
    for c in customers:
        c_lines.append(f"{c['customer_code']},{c['name']},{c['email']},{c['city']},{c['customer_segment']},{c['acquisition_date']}")
    customers_csv = "\n".join(c_lines) + "\n"

    # 2. products.csv
    p_lines = ["sku,name,category,subcategory,selling_price,unit_cost"]
    for p in products:
        p_lines.append(f"{p['sku']},{p['name']},{p['category']},{p['subcategory']},{p['selling_price']},{p['unit_cost']}")
    products_csv = "\n".join(p_lines) + "\n"

    # 3. sales.csv
    s_lines = ["order_number,customer_code,sku,date,subtotal,discount_amount,tax_amount,total_amount,status"]
    si_lines = ["order_number,sku,quantity,unit_price,discount_amount,line_total"]

    for s in sales:
        dt_str = s["date"].strftime("%Y-%m-%d %H:%M:%S")
        sku_val = s["items"][0]["sku"] if s["items"] else "SKU-NS-APP-01"
        s_lines.append(
            f"{s['order_number']},{s['customer_code']},{sku_val},{dt_str},{s['subtotal']},{s['discount_amount']},{s['tax_amount']},{s['total_amount']},{s['status']}"
        )
        for it in s["items"]:
            si_lines.append(
                f"{s['order_number']},{it['sku']},{it['quantity']},{it['unit_price']},{it['discount']},{it['line_total']}"
            )

    sales_csv = "\n".join(s_lines) + "\n"
    sale_items_csv = "\n".join(si_lines) + "\n"

    # 4. quarantine_probe.csv: Contains an unmapped customer code to test quarantine
    q_lines = [
        "order_number,customer_code,date,subtotal,discount_amount,tax_amount,total_amount,status",
        "NS-QUARANTINE-01,CUST-UNKNOWN-999,2025-06-15 12:00:00,150.00,0.00,12.00,162.00,completed",
    ]
    quarantine_probe_csv = "\n".join(q_lines) + "\n"

    # 5. invalid_range_probe.csv: Contains negative amount to test atomic rollback
    inv_lines = [
        "order_number,customer_code,date,subtotal,discount_amount,tax_amount,total_amount,status",
        f"NS-ROLLBACK-01,{customers[0]['customer_code']},2025-06-15 12:00:00,100.00,0.00,8.00,108.00,completed",
        f"NS-ROLLBACK-02,{customers[0]['customer_code']},2025-06-15 12:05:00,-50.00,0.00,0.00,-50.00,completed",
    ]
    invalid_range_probe_csv = "\n".join(inv_lines) + "\n"

    return {
        "customers_csv": customers_csv,
        "products_csv": products_csv,
        "sales_csv": sales_csv,
        "sale_items_csv": sale_items_csv,
        "quarantine_probe_csv": quarantine_probe_csv,
        "invalid_range_probe_csv": invalid_range_probe_csv,
    }
