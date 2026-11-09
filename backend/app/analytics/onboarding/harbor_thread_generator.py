"""Deterministic Harbor & Thread Synthetic Pilot Merchant Generator for NEXUS.

Provisions a dedicated, fully isolated synthetic merchant environment:
'Harbor & Thread — NEXUS Synthetic Pilot'

Profile:
- Business: Harbor & Thread
- Industry: Fashion & Lifestyle Retail
- Location: Dubai, UAE (Currency: AED, 5% UAE VAT)
- Stores: 2 Physical Stores ('Dubai Mall Store', 'Mall of the Emirates Store') + 'Online Webstore'
- Owner: Daniel Morgan (fictional) (daniel.morgan@harbor-thread.local)
- Objective: Improve customer retention, revenue, profitability, and purchasing decisions.

Guarantees:
1. Strict tenant isolation: Dedicated organization, business, and manager identity.
2. Complete mathematical consistency: Item lines, subtotals, VAT (5%), and totals reconcile exactly.
3. 24-Month Temporal Span: 2024-11-01 to 2026-10-31 with Dubai seasonality (DSF, Eid, Summer, Autumn).
4. 1,200 Customers across Dubai neighborhoods with calibrated cohorts (VIP, regular, at-risk, lapsed, reactivated, one-time).
5. 180 Products across 6 categories with explicit verified synthetic unit costs (35%-50% cost ratio).
6. ~8,000 Orders totaling 12,000–16,000 sale-item rows.
7. Explicit synthetic labeling: All entities tagged as demonstration fixtures.
"""

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.services.auth_service import AuthService

HARBOR_THREAD_TENANT_NAME = "Harbor & Thread — NEXUS Synthetic Pilot"
HARBOR_THREAD_ORG_NAME = "Harbor & Thread Retail Group"
HARBOR_THREAD_ORG_SLUG = "harbor-thread-retail-group"
HARBOR_THREAD_MANAGER_EMAIL = "daniel.morgan@harbor-thread.local"
HARBOR_THREAD_MANAGER_NAME = "Daniel Morgan"
HARBOR_THREAD_MANAGER_PASSWORD = "Harbor#2026!DubaiPilot"
HARBOR_THREAD_CONSENT_REF = "SIMULATED_CONSENT_HT_2026_PILOT"
HARBOR_THREAD_AUTH_REF = "AUTH-SYNTHETIC-HARBOR-THREAD-2026"
HARBOR_THREAD_SEED = 4200
HARBOR_THREAD_CURRENCY = "AED"

CHANNELS = [
    "Dubai Mall Store",
    "Mall of the Emirates Store",
    "Online Webstore",
]

NEIGHBORHOODS = [
    "Downtown Dubai",
    "Palm Jumeirah",
    "Dubai Marina",
    "DIFC",
    "Jumeirah Beach Residence",
    "Arabian Ranches",
    "Business Bay",
    "Dubai Hills Estate",
    "Jumeirah 1",
    "Emirates Hills",
]


def get_deterministic_rng() -> random.Random:
    """Return isolated RNG seeded for exact reproducibility."""
    return random.Random(HARBOR_THREAD_SEED)


def get_synthetic_catalog_definitions() -> list[dict[str, Any]]:
    """Return 180 fashion and lifestyle product specifications across 6 categories."""
    categories = [
        (
            "Linen & Resortwear",
            "LIN",
            [
                ("Linen Long-Sleeve Shirt", "Shirts", Decimal("280.00"), Decimal("112.00")),
                ("Linen Drawstring Trouser", "Bottoms", Decimal("340.00"), Decimal("136.00")),
                ("Resort Camp-Collar Shirt", "Shirts", Decimal("260.00"), Decimal("104.00")),
                ("Breezy Cabana Shorts", "Shorts", Decimal("220.00"), Decimal("88.00")),
                ("Linen Safari Overshirt", "Overshirts", Decimal("420.00"), Decimal("168.00")),
            ],
        ),
        (
            "Tailored Suiting & Formalwear",
            "TLS",
            [
                ("Deconstructed Wool Blazer", "Jackets", Decimal("1250.00"), Decimal("500.00")),
                ("Tailored Wool Trousers", "Bottoms", Decimal("580.00"), Decimal("232.00")),
                (
                    "Double-Breasted Linen Suit Jacket",
                    "Jackets",
                    Decimal("1450.00"),
                    Decimal("580.00"),
                ),
                ("Egyptian Cotton Dinner Shirt", "Shirts", Decimal("390.00"), Decimal("156.00")),
                ("Sartorial Dress Waistcoat", "Vests", Decimal("480.00"), Decimal("192.00")),
            ],
        ),
        (
            "Silk & Eveningwear",
            "SLK",
            [
                ("Mulberry Silk Evening Blouse", "Tops", Decimal("520.00"), Decimal("208.00")),
                ("Silk Crepe Wide-Leg Pant", "Bottoms", Decimal("640.00"), Decimal("256.00")),
                ("Embroidered Silk Kaftan", "Dresses", Decimal("1150.00"), Decimal("460.00")),
                ("Silk Twill Statement Shawl", "Wraps", Decimal("380.00"), Decimal("152.00")),
                ("Silk Slip Midi Dress", "Dresses", Decimal("890.00"), Decimal("356.00")),
            ],
        ),
        (
            "Footwear & Leather Goods",
            "FTW",
            [
                ("Handcrafted Suede Loafer", "Shoes", Decimal("720.00"), Decimal("288.00")),
                ("Italian Calfskin Driver Shoe", "Shoes", Decimal("680.00"), Decimal("272.00")),
                ("Minimalist Leather Sneaker", "Shoes", Decimal("590.00"), Decimal("236.00")),
                (
                    "Full-Grain Leather Weekender Bag",
                    "Luggage",
                    Decimal("1650.00"),
                    Decimal("660.00"),
                ),
                ("Structured Leather Crossbody", "Bags", Decimal("780.00"), Decimal("312.00")),
            ],
        ),
        (
            "Fine Accessories",
            "ACC",
            [
                ("Hand-Woven Calfskin Belt", "Belts", Decimal("290.00"), Decimal("116.00")),
                ("Polarized Acetate Sunglasses", "Eyewear", Decimal("460.00"), Decimal("184.00")),
                (
                    "Hand-Rolled Silk Pocket Square",
                    "Pocket Squares",
                    Decimal("140.00"),
                    Decimal("56.00"),
                ),
                (
                    "Brushed Steel Minimalist Chronograph",
                    "Watches",
                    Decimal("1200.00"),
                    Decimal("480.00"),
                ),
                ("Sterling Silver Cufflinks", "Jewelry", Decimal("320.00"), Decimal("128.00")),
            ],
        ),
        (
            "Fragrance & Lifestyle",
            "FRG",
            [
                (
                    "Oud & Bergamot Eau de Parfum 100ml",
                    "Fragrance",
                    Decimal("520.00"),
                    Decimal("208.00"),
                ),
                (
                    "Amber & Cedarwood Room Diffuser",
                    "Home Scent",
                    Decimal("280.00"),
                    Decimal("112.00"),
                ),
                (
                    "Prestige Botanical Grooming Oil",
                    "Grooming",
                    Decimal("180.00"),
                    Decimal("72.00"),
                ),
                (
                    "Hand-Poured Soy Wax Scented Candle",
                    "Candles",
                    Decimal("160.00"),
                    Decimal("64.00"),
                ),
                ("Cashmere Travel Blanket", "Lifestyle", Decimal("950.00"), Decimal("380.00")),
            ],
        ),
    ]

    products = []
    prod_id = 1
    rng = get_deterministic_rng()

    for cat_name, prefix, templates in categories:
        for i in range(1, 31):  # Exactly 30 products per category -> 180 total
            tpl = templates[(i - 1) % len(templates)]
            variant_num = ((i - 1) // len(templates)) + 1
            name_suffix = f" (Edition {variant_num})" if variant_num > 1 else ""
            sku = f"HT-{prefix}-{i:03d}"
            name = f"{tpl[0]}{name_suffix} [SYNTHETIC_PILOT_COGS]"
            subcat = tpl[1]

            # Price slight variation per edition
            mult = Decimal(str(1.0 + ((i % 5) * 0.05)))
            price = round(tpl[2] * mult, 2)
            # Guaranteed synthetic COGS between 38% and 44% of selling price
            cogs_ratio = Decimal(str(0.38 + ((i % 7) * 0.01)))
            unit_cost = round(price * cogs_ratio, 2)

            # 25 discontinued items (e.g. earlier editions)
            is_active = not (i > 25 and prefix in ("LIN", "SLK", "TLS"))

            products.append(
                {
                    "sku": sku,
                    "name": name,
                    "category": cat_name,
                    "subcategory": subcat,
                    "selling_price": price,
                    "unit_cost": unit_cost,
                    "is_active": is_active,
                }
            )
            prod_id += 1

    return products


def get_synthetic_customer_definitions() -> list[dict[str, Any]]:
    """Return 1,200 customer accounts across calibrated behavioral cohorts and Dubai locations."""
    rng = get_deterministic_rng()
    customers = []

    first_names = [
        "Rashid",
        "Fatima",
        "Tariq",
        "Mariam",
        "Sultan",
        "Noura",
        "Omar",
        "Layla",
        "Zayed",
        "Salma",
        "Alexander",
        "Sophia",
        "James",
        "Elena",
        "Lucas",
        "Charlotte",
        "Maximilian",
        "Isabella",
        "Julian",
        "Amelia",
        "Rohan",
        "Priya",
        "Arjun",
        "Ananya",
        "Vikram",
        "Sneha",
        "Karan",
        "Pooja",
        "Sameer",
        "Divya",
        "Pierre",
        "Camille",
        "Henrik",
        "Astrid",
        "Mateo",
        "Valentina",
        "Liam",
        "Chloe",
        "Noah",
        "Emma",
    ]
    last_names = [
        "Al Mansoori",
        "Al Nuaimi",
        "Al Hashimi",
        "Al Falasi",
        "Al Maktoum",
        "Al Zaabi",
        "Al Qasimi",
        "Al Suwaidi",
        "Sterling",
        "Sinclair",
        "Vanderbilt",
        "Beaumont",
        "Mercer",
        "Harrington",
        "Kensington",
        "Montgomery",
        "Kapoor",
        "Mehta",
        "Sharma",
        "Singhania",
        "Deshmukh",
        "Nambiar",
        "Verma",
        "Chowdhury",
        "Dubois",
        "Moreau",
        "Lindqvist",
        "Bergman",
        "Castillo",
        "Navarro",
        "O'Connor",
        "Brennan",
    ]

    base_start = date(2024, 11, 1)

    # 1. VIP Repeat Buyers (100 customers: 18 to 28 orders, regular 24-38 day cadence)
    for i in range(1, 101):
        fn = rng.choice(first_names)
        ln = rng.choice(last_names)
        code = f"HT-CUST-VIP-{i:04d}"
        acq_offset = rng.randint(0, 45)
        customers.append(
            {
                "customer_code": code,
                "name": f"{fn} {ln}",
                "email": f"vip.{fn.lower()}.{ln.lower().replace(' ', '')}.{i}@harbor-thread.pilot",
                "city": rng.choice(NEIGHBORHOODS[:4]),  # Downtown, Palm, Marina, DIFC
                "customer_segment": "VIP",
                "cohort": "vip_repeat",
                "target_orders": rng.randint(18, 28),
                "acquisition_date": base_start + timedelta(days=acq_offset),
                "cadence_days_mean": rng.randint(24, 38),
            }
        )

    # 2. Regular Repeat Buyers (350 customers: 10 to 16 orders, steady 42-62 day cadence)
    for i in range(1, 351):
        fn = rng.choice(first_names)
        ln = rng.choice(last_names)
        code = f"HT-CUST-REG-{i:04d}"
        acq_offset = rng.randint(0, 180)
        customers.append(
            {
                "customer_code": code,
                "name": f"{fn} {ln}",
                "email": f"regular.{fn.lower()}.{ln.lower().replace(' ', '')}.{i}@harbor-thread.pilot",
                "city": rng.choice(NEIGHBORHOODS),
                "customer_segment": "Loyal",
                "cohort": "regular_repeat",
                "target_orders": rng.randint(10, 16),
                "acquisition_date": base_start + timedelta(days=acq_offset),
                "cadence_days_mean": rng.randint(42, 62),
            }
        )

    # 3. Occasional / At-Risk Repeat Buyers (150 customers: 3 to 5 orders, overdue gap)
    for i in range(1, 151):
        fn = rng.choice(first_names)
        ln = rng.choice(last_names)
        code = f"HT-CUST-RSK-{i:04d}"
        acq_offset = rng.randint(30, 200)
        customers.append(
            {
                "customer_code": code,
                "name": f"{fn} {ln}",
                "email": f"atrisk.{fn.lower()}.{ln.lower().replace(' ', '')}.{i}@harbor-thread.pilot",
                "city": rng.choice(NEIGHBORHOODS),
                "customer_segment": "At-Risk",
                "cohort": "at_risk_repeat",
                "target_orders": rng.randint(3, 5),
                "acquisition_date": base_start + timedelta(days=acq_offset),
                "cadence_days_mean": rng.randint(75, 110),
            }
        )

    # 4. Lapsed / Dormant Buyers (200 customers: 2 to 3 orders early, dormant > 180 days)
    for i in range(1, 201):
        fn = rng.choice(first_names)
        ln = rng.choice(last_names)
        code = f"HT-CUST-LAP-{i:04d}"
        acq_offset = rng.randint(0, 90)
        customers.append(
            {
                "customer_code": code,
                "name": f"{fn} {ln}",
                "email": f"lapsed.{fn.lower()}.{ln.lower().replace(' ', '')}.{i}@harbor-thread.pilot",
                "city": rng.choice(NEIGHBORHOODS),
                "customer_segment": "Dormant",
                "cohort": "lapsed",
                "target_orders": rng.randint(2, 3),
                "acquisition_date": base_start + timedelta(days=acq_offset),
                "cadence_days_mean": rng.randint(40, 60),
            }
        )

    # 5. Reactivated Buyers (100 customers: orders early, long gap, returned in Q3/Q4 2026)
    for i in range(1, 101):
        fn = rng.choice(first_names)
        ln = rng.choice(last_names)
        code = f"HT-CUST-REA-{i:04d}"
        acq_offset = rng.randint(0, 60)
        customers.append(
            {
                "customer_code": code,
                "name": f"{fn} {ln}",
                "email": f"reactivated.{fn.lower()}.{ln.lower().replace(' ', '')}.{i}@harbor-thread.pilot",
                "city": rng.choice(NEIGHBORHOODS),
                "customer_segment": "Reactivated",
                "cohort": "reactivated",
                "target_orders": rng.randint(4, 6),
                "acquisition_date": base_start + timedelta(days=acq_offset),
                "cadence_days_mean": rng.randint(50, 75),
            }
        )

    # 6. One-Time Buyers (300 customers: exactly 1 purchase)
    for i in range(1, 301):
        fn = rng.choice(first_names)
        ln = rng.choice(last_names)
        code = f"HT-CUST-ONE-{i:04d}"
        acq_offset = rng.randint(0, 700)  # Spread evenly across the entire 24 months
        customers.append(
            {
                "customer_code": code,
                "name": f"{fn} {ln}",
                "email": f"single.{fn.lower()}.{ln.lower().replace(' ', '')}.{i}@harbor-thread.pilot",
                "city": rng.choice(NEIGHBORHOODS),
                "customer_segment": "New",
                "cohort": "one_time",
                "target_orders": 1,
                "acquisition_date": base_start + timedelta(days=acq_offset),
                "cadence_days_mean": 0,
            }
        )

    return customers


def generate_synthetic_transactions() -> list[dict[str, Any]]:
    """
    Generate ~8,000 realistic orders totaling 12,000–16,000 items spanning 24 months (2024-11-01 to 2026-10-31).
    Incorporates:
    - Dubai Shopping Festival (DSF, Dec 15 to Jan 31): high volume and promotion
    - Ramadan / Eid Surges: Spring 2025 and Spring 2026
    - Dubai Summer Slump: July-August slower baseline
    - Autumn Collections: September-October high AOV
    - Strict line-item and order-level invariants:
      item.line_total = quantity * unit_price - discount
      sale.subtotal = sum(item.line_total)
      sale.tax = round((subtotal - discount) * 0.05, 2) [UAE 5% VAT]
      sale.total = subtotal - discount + tax
    """
    rng = get_deterministic_rng()
    customers = get_synthetic_customer_definitions()
    products = get_synthetic_catalog_definitions()

    sales: list[dict[str, Any]] = []
    order_seq = 1
    cutoff_dt = datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC)

    for cust in customers:
        cohort = cust["cohort"]
        c_code = cust["customer_code"]
        target_orders = cust["target_orders"]
        acq_dt = datetime(
            cust["acquisition_date"].year,
            cust["acquisition_date"].month,
            cust["acquisition_date"].day,
            10,
            0,
            tzinfo=UTC,
        )
        cadence_mean = cust.get("cadence_days_mean", 45)

        cur_dt = acq_dt + timedelta(hours=rng.randint(1, 10), minutes=rng.randint(0, 59))

        for ord_idx in range(target_orders):
            if cur_dt > cutoff_dt:
                break

            # Check seasonal date adjustments
            m = cur_dt.month
            d = cur_dt.day

            is_dsf = (m == 12 and d >= 15) or (m == 1)
            is_eid_2025 = cur_dt.year == 2025 and ((m == 3 and d >= 15) or (m == 4 and d <= 10))
            is_eid_2026 = cur_dt.year == 2026 and ((m == 2 and d >= 20) or (m == 3 and d <= 25))
            is_summer = m in (7, 8)
            is_autumn = m in (9, 10)

            # Channel selection
            r_chan = rng.random()
            if r_chan < 0.40:
                channel = "Dubai Mall Store"
            elif r_chan < 0.75:
                channel = "Mall of the Emirates Store"
            else:
                channel = "Online Webstore"

            # Basket size (items count: 1 to 3 items, holiday/DSF up to 4)
            items_count = rng.randint(1, 2)
            if is_dsf or is_eid_2025 or is_eid_2026:
                items_count = rng.randint(2, 4)
            elif cohort == "vip_repeat":
                items_count = rng.randint(2, 3)

            selected_prods = rng.sample(products, items_count)
            line_items = []
            subtotal = Decimal("0.00")

            for prod in selected_prods:
                qty = 1 if (cohort != "vip_repeat" or rng.random() < 0.75) else 2
                price = prod["selling_price"]
                line_disc = Decimal("0.00")

                # Line discount during DSF or promotions
                if (
                    (is_dsf or is_eid_2025 or is_eid_2026)
                    and price > Decimal("300.00")
                    and rng.random() < 0.40
                ):
                    line_disc = round(price * Decimal("0.10"), 2)

                l_tot = (price * qty) - line_disc
                subtotal += l_tot

                line_items.append(
                    {
                        "sku": prod["sku"],
                        "product_name": prod["name"],
                        "category": prod["category"],
                        "quantity": qty,
                        "unit_price": price,
                        "discount_amount": line_disc,
                        "unit_cost": prod["unit_cost"],
                        "line_total": l_tot,
                    }
                )

            order_discount = Decimal("0.00")
            if (is_dsf or is_eid_2025 or is_eid_2026) and subtotal > Decimal("1000.00"):
                order_discount = Decimal("50.00")

            # UAE 5% VAT calculation
            taxable_base = max(Decimal("0.00"), subtotal - order_discount)
            tax_amount = round(taxable_base * Decimal("0.05"), 2)
            total_amount = taxable_base + tax_amount

            # Status: 96.5% completed, 2.5% refunded, 1.0% cancelled
            r_status = rng.random()
            if r_status < 0.025 and ord_idx > 0:
                status = "refunded"
            elif r_status < 0.035:
                status = "cancelled"
            else:
                status = "completed"

            order_num = f"HT-ORD-{order_seq:05d}"
            order_seq += 1

            sales.append(
                {
                    "order_number": order_num,
                    "customer_code": c_code,
                    "channel": channel,
                    "date": cur_dt,
                    "subtotal": subtotal,
                    "discount_amount": order_discount,
                    "tax_amount": tax_amount,
                    "total_amount": total_amount,
                    "status": status,
                    "items": line_items,
                }
            )

            # Advance cur_dt according to cohort behavior
            if cohort == "one_time":
                break
            elif cohort == "lapsed":
                # Orders in early 2025, then silence
                cur_dt += timedelta(days=rng.randint(25, 45))
                if ord_idx >= target_orders - 1:
                    break
            elif cohort == "reactivated":
                if ord_idx < 2:
                    cur_dt += timedelta(days=rng.randint(30, 50))
                elif ord_idx == 2:
                    # Giant gap of 220-300 days before reactivation in 2026
                    cur_dt += timedelta(days=rng.randint(220, 280))
                else:
                    cur_dt += timedelta(days=rng.randint(35, 60))
            elif cohort == "at_risk_repeat":
                # Long intervals leading to overdue state
                cur_dt += timedelta(days=rng.randint(cadence_mean - 10, cadence_mean + 35))
            else:  # vip_repeat, regular_repeat
                variance = rng.randint(-10, 15)
                step_days = max(18, cadence_mean + variance)
                if is_summer:
                    step_days += 15  # Summer purchase delay
                cur_dt += timedelta(days=step_days)

    # Sort deterministically by transaction timestamp
    sales.sort(key=lambda s: s["date"])
    return sales


def provision_harbor_thread_tenant(
    db: Session,
    business_id: str | None = None,
) -> tuple[UserIdentity, Organization, Business]:
    """
    Idempotently provision or retrieve the isolated Harbor & Thread synthetic pilot merchant.
    Guarantees zero interference with Northstar, Apex, or other existing tenants.
    """
    existing_biz = None
    if business_id:
        existing_biz = db.execute(
            select(Business).where(Business.id == business_id)
        ).scalar_one_or_none()
    if not existing_biz:
        existing_biz = db.execute(
            select(Business).where(Business.name == HARBOR_THREAD_TENANT_NAME)
        ).scalar_one_or_none()

    if existing_biz:
        org = db.execute(
            select(Organization).where(Organization.id == existing_biz.organization_id)
        ).scalar_one()
        user = db.execute(
            select(UserIdentity).where(UserIdentity.email == HARBOR_THREAD_MANAGER_EMAIL)
        ).scalar_one_or_none()
        if not user:
            user = UserIdentity(
                id=str(uuid4()),
                email=HARBOR_THREAD_MANAGER_EMAIL,
                full_name=HARBOR_THREAD_MANAGER_NAME,
                password_hash=AuthService.hash_password(HARBOR_THREAD_MANAGER_PASSWORD),
                is_active=True,
            )
            db.add(user)
            db.flush()
            # Ensure organization membership
            m_exist = db.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.organization_id == org.id,
                )
            ).scalar_one_or_none()
            if not m_exist:
                db.add(
                    OrganizationMembership(
                        id=str(uuid4()),
                        user_id=user.id,
                        organization_id=org.id,
                        role="admin",
                    )
                )
            db.flush()
        return user, org, existing_biz

    # Provision brand new isolated synthetic pilot organization, business, and manager
    user, org, biz = AuthService.signup(
        db=db,
        email=HARBOR_THREAD_MANAGER_EMAIL,
        password=HARBOR_THREAD_MANAGER_PASSWORD,
        full_name=HARBOR_THREAD_MANAGER_NAME,
        organization_name=HARBOR_THREAD_ORG_NAME,
        business_name=HARBOR_THREAD_TENANT_NAME,
    )

    biz.currency = HARBOR_THREAD_CURRENCY
    db.commit()
    return user, org, biz


def generate_gateway_csv_payloads() -> dict[str, str]:
    """
    Generate CSV file contents for:
    - customers.csv (1,200 rows)
    - products.csv (180 rows)
    - sales.csv (~8,000 rows)
    - sale_items.csv (~12,000–16,000 rows)
    - quarantine_customer_probe.csv (testing customer unmapped isolation)
    - atomic_rollback_probe.csv (testing atomic rollback)
    """
    customers = get_synthetic_customer_definitions()
    products = get_synthetic_catalog_definitions()
    sales = generate_synthetic_transactions()

    # 1. customers.csv
    c_lines = ["customer_code,name,email,city,customer_segment,acquisition_date"]
    for c in customers:
        c_lines.append(
            f"{c['customer_code']},{c['name']},{c['email']},{c['city']},{c['customer_segment']},{c['acquisition_date']}"
        )
    customers_csv = "\n".join(c_lines) + "\n"

    # 2. products.csv
    p_lines = ["sku,name,category,subcategory,selling_price,unit_cost"]
    for p in products:
        p_lines.append(
            f"{p['sku']},{p['name']},{p['category']},{p['subcategory']},{p['selling_price']},{p['unit_cost']}"
        )
    products_csv = "\n".join(p_lines) + "\n"

    # 3. sales.csv & 4. sale_items.csv
    s_lines = [
        "order_number,customer_code,date,subtotal,discount_amount,tax_amount,total_amount,status"
    ]
    si_lines = ["order_number,sku,quantity,unit_price,discount_amount,line_total"]

    for s in sales:
        dt_str = s["date"].strftime("%Y-%m-%d %H:%M:%S")
        s_lines.append(
            f"{s['order_number']},{s['customer_code']},{dt_str},{s['subtotal']},{s['discount_amount']},{s['tax_amount']},{s['total_amount']},{s['status']}"
        )
        for it in s["items"]:
            si_lines.append(
                f"{s['order_number']},{it['sku']},{it['quantity']},{it['unit_price']},{it['discount_amount']},{it['line_total']}"
            )

    sales_csv = "\n".join(s_lines) + "\n"
    sale_items_csv = "\n".join(si_lines) + "\n"

    # 5. quarantine_customer_probe.csv: Contains unmapped customer code
    q_lines = [
        "order_number,customer_code,date,subtotal,discount_amount,tax_amount,total_amount,status",
        "HT-QUARANTINE-001,HT-CUST-UNMAPPED-999,2026-05-15 14:00:00,450.00,0.00,22.50,472.50,completed",
    ]
    quarantine_customer_probe_csv = "\n".join(q_lines) + "\n"

    # 6. atomic_rollback_probe.csv: Contains negative amount violating domain invariant
    inv_lines = [
        "order_number,customer_code,date,subtotal,discount_amount,tax_amount,total_amount,status",
        f"HT-ROLLBACK-001,{customers[0]['customer_code']},2026-05-15 14:00:00,350.00,0.00,17.50,367.50,completed",
        f"HT-ROLLBACK-002,{customers[0]['customer_code']},2026-05-15 14:05:00,-250.00,0.00,0.00,-250.00,completed",
    ]
    atomic_rollback_probe_csv = "\n".join(inv_lines) + "\n"

    return {
        "customers_csv": customers_csv,
        "products_csv": products_csv,
        "sales_csv": sales_csv,
        "sale_items_csv": sale_items_csv,
        "quarantine_customer_probe_csv": quarantine_customer_probe_csv,
        "atomic_rollback_probe_csv": atomic_rollback_probe_csv,
    }
