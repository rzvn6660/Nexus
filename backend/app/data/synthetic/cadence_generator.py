"""Experimental Synthetic Customer Cadence Dataset Generator.

Designed to stress-test the NEXUS CustomerCadenceAnalyzer and HistoricalCadenceValidator
under realistic, non-memoryless customer renewal processes, heterogeneous purchase cadences,
one-time buyers, seasonality, churn dropouts, and simulated ingestion delays.

DISCLAIMER:
This module is strictly an experimental data-quality, stress-testing, and simulation tool.
Synthetic dataset outcomes must NEVER be represented as empirical evidence of real-world
commercial predictive validity.
"""

import math
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, IngestionJob, Organization, UploadedDataset


def _quantize_currency(val: float | Decimal) -> Decimal:
    """Round float or Decimal to 2 decimal places as exact currency Decimal."""
    return Decimal(str(round(float(val), 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class CustomerBehaviorArchetype(str, Enum):
    """Behavioral archetype governing renewal intervals, cadence, and attrition."""

    ONE_TIME = "one_time"
    FREQUENT_REPLENISHMENT = "frequent_replenishment"
    REGULAR_REPEAT = "regular_repeat"
    IRREGULAR = "irregular"
    LONG_CYCLE = "long_cycle"
    SEASONAL = "seasonal"
    NEWLY_ACQUIRED = "newly_acquired"
    CHURNING_DROPOUT = "churning_dropout"
    LONG_INTERVAL_ACTIVE = "long_interval_active"


class CadenceGeneratorConfig(BaseModel):
    """Configuration governing synthetic customer cadence generation."""

    seed: int = Field(default=42, description="Random seed for deterministic reproducibility.")
    num_customers: int = Field(default=200, ge=10, description="Total customers to generate.")
    start_date: date = Field(
        default=date(2022, 1, 1), description="Earliest possible customer acquisition date."
    )
    end_date: date = Field(
        default=date(2023, 12, 31), description="Latest transaction date boundary."
    )
    business_id: str | None = Field(
        default="biz-cadence-synth", description="Tenant workspace ID."
    )
    organization_id: str | None = Field(
        default="org-cadence-synth", description="Tenant organization ID."
    )
    customer_id_start: int = Field(default=1, ge=1, description="Initial customer integer ID.")
    sale_id_start: int = Field(default=1, ge=1, description="Initial sale integer ID.")
    product_id_start: int = Field(default=1, ge=1, description="Initial product integer ID.")
    sale_item_id_start: int = Field(default=1, ge=1, description="Initial sale item integer ID.")
    customer_code_prefix: str = Field(default="CUST-SYNTH", description="Prefix for customer codes.")
    transaction_prefix: str = Field(default="TXN-SYNTH", description="Prefix for transaction numbers.")
    sku_prefix: str = Field(default="SKU", description="Prefix for product SKUs.")
    email_domain: str = Field(default="nexus-cadence-test.io", description="Email domain for synthetic customers.")
    zero_purchase_pct: float = Field(
        default=0.0, ge=0.0, le=0.5, description="Proportion of registered customers who make 0 purchases."
    )
    one_time_buyer_pct: float = Field(
        default=0.45,
        ge=0.0,
        le=0.9,
        description="Target proportion of customers who make only 1 purchase (typical retail: 40-70%).",
    )
    mean_ingestion_delay_days: float = Field(
        default=2.0, ge=0.0, description="Mean exponential pipeline latency between event and ingestion."
    )
    tail_delay_prob: float = Field(
        default=0.05, ge=0.0, le=0.5, description="Probability an order experiences a long tail ingestion delay."
    )
    tail_delay_max_days: float = Field(
        default=14.0, ge=1.0, description="Maximum tail ingestion delay in days."
    )
    simulate_incomplete_ingestion: bool = Field(
        default=False, description="Whether to omit records with created_at > ingestion_cutoff."
    )
    ingestion_cutoff: datetime | None = Field(
        default=None, description="Pipeline cutoff timestamp for simulated incomplete ingestion."
    )
    archetype_weights: dict[CustomerBehaviorArchetype, float] | None = Field(
        default=None,
        description="Optional explicit weight distribution across customer archetypes for scenario customization.",
    )


SYNTH_CATEGORIES = {
    "Industrial Tools": {
        "subcategories": ["Hand Tools", "Safety Equipment", "Fasteners", "Measurement"],
        "price_range": (20.0, 350.0),
        "margin_range": (0.35, 0.50),
    },
    "Office Supplies": {
        "subcategories": ["Paper Goods", "Desk Organization", "Writing Instruments"],
        "price_range": (5.0, 55.0),
        "margin_range": (0.45, 0.65),
    },
    "Packaging & Shipping": {
        "subcategories": ["Boxes", "Wrap & Bubble", "Tape & Adhesives"],
        "price_range": (10.0, 120.0),
        "margin_range": (0.40, 0.55),
    },
}

SEGMENT_PROFILES = [
    ("Retail", 0.55, (1, 3), (1, 4)),
    ("Corporate", 0.20, (2, 5), (5, 25)),
    ("Wholesale", 0.15, (4, 10), (20, 80)),
    ("VIP", 0.10, (2, 6), (2, 8)),
]


class CadenceValidationDatasetGenerator:
    """
    Dedicated generator creating realistic customer cohorts with stochastic renewal processes.

    Key capabilities:
    - Customer-specific renewal cadences drawn from LogNormal-Gamma distributions.
    - Realistic one-time buyer proportions (40% to 70%).
    - Explicit behavioral archetypes (frequent, regular, irregular, long-cycle, seasonal, churn dropout).
    - Separation of event timestamps (transaction_date) from table insertion timestamps (created_at).
    - Factory methods for standardized stress-test scenarios.
    """

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

    def generate(self, config: CadenceGeneratorConfig | None = None) -> dict[str, Any]:
        """Generate a complete relational dataset adhering to configuration specifications."""
        cfg = config or CadenceGeneratorConfig(seed=self.seed)
        # Seed both generators for deterministic byte-level reproducibility
        self.rng.seed(cfg.seed)
        self.np_rng = np.random.default_rng(cfg.seed)

        products = self._generate_products(cfg)
        customers, customer_archetypes = self._generate_customers(cfg)
        sales, sale_items = self._generate_orders(
            cfg=cfg,
            customers=customers,
            customer_archetypes=customer_archetypes,
            products=products,
        )

        archetype_counts = {}
        for arch in CustomerBehaviorArchetype:
            archetype_counts[arch.value] = sum(1 for a in customer_archetypes.values() if a == arch)

        n_cust = len(customers)
        cust_order_counts = {}
        for s in sales:
            cid = s["customer_id"]
            cust_order_counts[cid] = cust_order_counts.get(cid, 0) + 1
        one_time_count = sum(1 for c in customers if cust_order_counts.get(c["id"], 0) == 1)
        zero_count = sum(1 for c in customers if cust_order_counts.get(c["id"], 0) == 0)
        actual_one_time_share = round(one_time_count / n_cust, 4) if n_cust > 0 else 0.0

        metadata = {
            "seed": cfg.seed,
            "business_id": cfg.business_id,
            "organization_id": cfg.organization_id,
            "total_customers": n_cust,
            "total_sales": len(sales),
            "total_sale_items": len(sale_items),
            "zero_purchase_buyers_count": zero_count,
            "one_time_buyers_count": one_time_count,
            "one_time_buyers_share": actual_one_time_share,
            "archetype_distribution": archetype_counts,
            "date_range_start": cfg.start_date.isoformat(),
            "date_range_end": cfg.end_date.isoformat(),
            "simulate_incomplete_ingestion": cfg.simulate_incomplete_ingestion,
            "ingestion_cutoff": cfg.ingestion_cutoff.isoformat() if cfg.ingestion_cutoff else None,
        }

        return {
            "customers": customers,
            "products": products,
            "sales": sales,
            "sale_items": sale_items,
            "metadata": metadata,
        }

    def _generate_products(self, cfg: CadenceGeneratorConfig) -> list[dict[str, Any]]:
        """Generate a small, consistent product catalog."""
        products = []
        p_id = cfg.product_id_start
        prod_base_dt = datetime.combine(cfg.start_date, datetime.min.time(), tzinfo=UTC)

        for cat_name, cat_info in SYNTH_CATEGORIES.items():
            for subcat in cat_info["subcategories"]:
                min_p, max_p = cat_info["price_range"]
                min_m, max_m = cat_info["margin_range"]

                price = self.rng.uniform(min_p, max_p)
                margin = self.rng.uniform(min_m, max_m)
                cost = price * (1.0 - margin)

                products.append({
                    "id": p_id,
                    "business_id": cfg.business_id,
                    "sku": f"{cfg.sku_prefix}-{cat_name[:3].upper()}-{p_id:04d}",
                    "name": f"Pro {subcat} Unit #{p_id}",
                    "category": cat_name,
                    "subcategory": subcat,
                    "unit_cost": _quantize_currency(cost),
                    "selling_price": _quantize_currency(price),
                    "active": True,
                    "created_at": prod_base_dt,
                    "updated_at": prod_base_dt,
                })
                p_id += 1

        return products

    def _generate_customers(
        self, cfg: CadenceGeneratorConfig
    ) -> tuple[list[dict[str, Any]], dict[int, CustomerBehaviorArchetype]]:
        """Generate customers distributed across segments and behavioral archetypes."""
        customers = []
        customer_archetypes: dict[int, CustomerBehaviorArchetype] = {}
        total_days = max(1, (cfg.end_date - cfg.start_date).days)

        segment_names, segment_weights, _, _ = zip(*SEGMENT_PROFILES)

        if cfg.archetype_weights is not None:
            # Custom scenario-defined archetype distribution
            arch_enums = list(cfg.archetype_weights.keys())
            arch_weights = list(cfg.archetype_weights.values())
        else:
            # Distribute remaining repeat customer share across non-one-time archetypes
            repeat_share = max(0.1, 1.0 - cfg.one_time_buyer_pct)
            repeat_archetypes = [
                (CustomerBehaviorArchetype.REGULAR_REPEAT, 0.30 * repeat_share),
                (CustomerBehaviorArchetype.FREQUENT_REPLENISHMENT, 0.20 * repeat_share),
                (CustomerBehaviorArchetype.IRREGULAR, 0.15 * repeat_share),
                (CustomerBehaviorArchetype.LONG_CYCLE, 0.15 * repeat_share),
                (CustomerBehaviorArchetype.SEASONAL, 0.08 * repeat_share),
                (CustomerBehaviorArchetype.CHURNING_DROPOUT, 0.07 * repeat_share),
                (CustomerBehaviorArchetype.LONG_INTERVAL_ACTIVE, 0.05 * repeat_share),
            ]
            all_archetypes = [(CustomerBehaviorArchetype.ONE_TIME, cfg.one_time_buyer_pct)] + repeat_archetypes
            arch_enums, arch_weights = zip(*all_archetypes)

        # Normalize weights
        w_sum = sum(arch_weights)
        norm_arch_weights = [w / w_sum for w in arch_weights]

        for idx in range(cfg.num_customers):
            i = cfg.customer_id_start + idx
            segment = self.rng.choices(segment_names, weights=segment_weights, k=1)[0]
            archetype = self.rng.choices(arch_enums, weights=norm_arch_weights, k=1)[0]

            # Acquisition date distribution:
            if archetype == CustomerBehaviorArchetype.NEWLY_ACQUIRED:
                # Acquired in the final 45 days of observation window
                max_days = max(5, min(45, total_days))
                min_days = min(5, max_days)
                acq_offset = max(0, total_days - self.rng.randint(min_days, max_days))
            else:
                # Triangularly distributed earlier in history
                acq_offset = int(self.rng.triangular(0, total_days, total_days * 0.25))

            acq_date = min(cfg.start_date + timedelta(days=acq_offset), cfg.end_date)

            cust_dt = datetime.combine(acq_date, datetime.min.time(), tzinfo=UTC)
            c_dict = {
                "id": i,
                "business_id": cfg.business_id,
                "customer_code": f"{cfg.customer_code_prefix}-{i:05d}",
                "name": f"Customer {i} ({archetype.value})",
                "email": f"cust_{i}@{cfg.email_domain}",
                "phone": f"+1-555-{i:04d}",
                "city": self.rng.choice(["Seattle", "Portland", "Chicago", "Denver", "Austin"]),
                "customer_segment": segment,
                "acquisition_date": acq_date,
                "created_at": cust_dt,
                "updated_at": cust_dt,
            }
            customers.append(c_dict)
            customer_archetypes[i] = archetype

        return customers, customer_archetypes

    def _generate_orders(
        self,
        cfg: CadenceGeneratorConfig,
        customers: list[dict[str, Any]],
        customer_archetypes: dict[int, CustomerBehaviorArchetype],
        products: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Generate orders using stochastic Gamma renewal intervals and customer-specific cadences.
        """
        sales: list[dict[str, Any]] = []
        sale_items: list[dict[str, Any]] = []
        sale_id = cfg.sale_id_start
        item_id = cfg.sale_item_id_start

        # Select zero-purchase customers if configured
        zero_cust_ids: set[int] = set()
        if cfg.zero_purchase_pct > 0.0 and customers:
            num_zero = round(len(customers) * cfg.zero_purchase_pct)
            if num_zero > 0:
                zero_cust_ids = set(self.rng.sample([c["id"] for c in customers], k=num_zero))

        segment_rules = {name: (items_rng, qty_rng) for name, _, items_rng, qty_rng in SEGMENT_PROFILES}

        # Archetype renewal parameters: (base_cadence_mean, base_cadence_sigma, gamma_shape)
        archetype_params = {
            CustomerBehaviorArchetype.FREQUENT_REPLENISHMENT: (10.0, 0.20, 10.0),
            CustomerBehaviorArchetype.REGULAR_REPEAT: (30.0, 0.25, 12.0),
            CustomerBehaviorArchetype.IRREGULAR: (45.0, 0.40, 1.5),
            CustomerBehaviorArchetype.LONG_CYCLE: (105.0, 0.25, 8.0),
            CustomerBehaviorArchetype.LONG_INTERVAL_ACTIVE: (80.0, 0.20, 9.0),
            CustomerBehaviorArchetype.SEASONAL: (18.0, 0.20, 8.0),
            CustomerBehaviorArchetype.NEWLY_ACQUIRED: (25.0, 0.20, 10.0),
            CustomerBehaviorArchetype.CHURNING_DROPOUT: (28.0, 0.20, 10.0),
        }

        for cust in customers:
            c_id = cust["id"]
            if c_id in zero_cust_ids:
                # Registered customer with no purchases
                continue

            c_seg = cust["customer_segment"]
            c_acq = cust["acquisition_date"]
            archetype = customer_archetypes[c_id]
            items_range, qty_range = segment_rules.get(c_seg, ((1, 3), (1, 4)))

            # Initial acquisition order at acquisition date
            order_dt = datetime.combine(
                c_acq,
                datetime.min.time().replace(
                    hour=self.rng.randint(8, 17), minute=self.rng.randint(0, 59)
                ),
                tzinfo=UTC,
            )

            cust_order_dates: list[datetime] = [order_dt]

            if archetype != CustomerBehaviorArchetype.ONE_TIME:
                mean_cad, sigma_cad, gamma_shape = archetype_params.get(
                    archetype, (30.0, 0.25, 10.0)
                )

                # Draw customer-specific base cadence theta_i ~ LogNormal
                log_mu = math.log(mean_cad) - 0.5 * (sigma_cad**2)
                theta_i = float(self.np_rng.lognormal(mean=log_mu, sigma=sigma_cad))
                theta_i = max(4.0, min(theta_i, 180.0))

                # For churning dropout, draw an attrition date tau_i
                days_to_end = (cfg.end_date - c_acq).days
                if archetype == CustomerBehaviorArchetype.CHURNING_DROPOUT:
                    churn_delay_days = self.rng.randint(45, max(50, int(days_to_end * 0.65)))
                    churn_tau = order_dt + timedelta(days=churn_delay_days)
                else:
                    churn_tau = datetime.max.replace(tzinfo=UTC)

                current_dt = order_dt
                end_dt = datetime.combine(cfg.end_date, datetime.max.time(), tzinfo=UTC)

                while current_dt < end_dt:
                    if archetype == CustomerBehaviorArchetype.SEASONAL:
                        # In Q4 (Oct-Dec), frequent cadence; outside Q4, long lull (jump to next autumn)
                        curr_month = current_dt.month
                        if curr_month in (10, 11, 12):
                            interval_days = float(
                                self.np_rng.gamma(shape=gamma_shape, scale=theta_i / gamma_shape)
                            )
                        else:
                            # Skip to next October
                            next_year = current_dt.year if curr_month < 10 else current_dt.year + 1
                            target_oct = datetime(next_year, 10, self.rng.randint(1, 15), 10, 0, tzinfo=UTC)
                            interval_days = max(1.0, (target_oct - current_dt).total_seconds() / 86400.0)
                    else:
                        # Stochastic renewal interval: Delta t ~ Gamma(k, theta / k)
                        interval_days = float(
                            self.np_rng.gamma(shape=gamma_shape, scale=theta_i / gamma_shape)
                        )

                    # Ensure interval is positive and non-zero
                    interval_days = max(1.0, interval_days)
                    # Add intra-day jitter to prevent identical timestamps
                    jitter_seconds = self.rng.randint(3600, 86400)
                    next_dt = current_dt + timedelta(days=int(interval_days), seconds=jitter_seconds)

                    if next_dt > end_dt or next_dt >= churn_tau:
                        break

                    cust_order_dates.append(next_dt)
                    current_dt = next_dt

            # Generate Sale and SaleItem records for each simulated order date
            for o_dt in cust_order_dates:
                # Simulate pipeline ingestion delay:
                # standard delay ~ Exponential(mean_delay); tail delay ~ Uniform(7, tail_max)
                if self.rng.random() < cfg.tail_delay_prob:
                    delay_days = self.rng.uniform(7.0, cfg.tail_delay_max_days)
                else:
                    delay_days = float(self.np_rng.exponential(scale=cfg.mean_ingestion_delay_days))

                ingest_dt = o_dt + timedelta(days=delay_days, seconds=self.rng.randint(60, 3600))

                # If simulating incomplete pipeline ingestion, skip records ingested after cutoff
                if (
                    cfg.simulate_incomplete_ingestion
                    and cfg.ingestion_cutoff
                    and ingest_dt > cfg.ingestion_cutoff
                ):
                    continue

                # Status distribution: 95% completed, 3% shipped, 1% refunded, 1% cancelled
                roll = self.rng.random()
                if roll < 0.95:
                    status = "completed"
                elif roll < 0.98:
                    status = "shipped"
                elif roll < 0.99:
                    status = "refunded"
                else:
                    status = "cancelled"

                # Pick 1 to N products
                num_items = self.rng.randint(items_range[0], items_range[1])
                chosen_prods = self.rng.sample(products, k=min(num_items, len(products)))

                subtotal = Decimal("0.00")
                sale_items_local = []

                for p in chosen_prods:
                    qty = self.rng.randint(qty_range[0], qty_range[1])
                    unit_p = p["selling_price"]
                    line_disc = _quantize_currency(float(unit_p * qty) * (0.05 if c_seg in ("Wholesale", "Corporate") else 0.0))
                    line_tot = _quantize_currency((unit_p * qty) - line_disc)
                    subtotal += line_tot

                    sale_items_local.append({
                        "id": item_id,
                        "sale_id": sale_id,
                        "product_id": p["id"],
                        "quantity": qty,
                        "unit_price": unit_p,
                        "discount_amount": line_disc,
                        "line_total": line_tot,
                        "created_at": ingest_dt,
                        "updated_at": ingest_dt,
                    })
                    item_id += 1

                disc_amt = Decimal("0.00")
                tax_amt = _quantize_currency(float(subtotal) * 0.075)
                tot_amt = subtotal + tax_amt

                sales.append({
                    "id": sale_id,
                    "business_id": cfg.business_id,
                    "transaction_number": f"{cfg.transaction_prefix}-{sale_id:07d}",
                    "customer_id": c_id,
                    "transaction_date": o_dt,
                    "status": status,
                    "subtotal": subtotal,
                    "discount_amount": disc_amt,
                    "tax_amount": tax_amt,
                    "total_amount": tot_amt,
                    "created_at": ingest_dt,
                    "updated_at": ingest_dt,
                })
                sale_items.extend(sale_items_local)
                sale_id += 1

        return sales, sale_items

    @classmethod
    def load_into_session(
        cls,
        session: Session,
        dataset: dict[str, Any],
        business_id: str | None = None,
        organization_id: str | None = None,
        in_flight_job_status: str | None = None,
    ) -> None:
        """
        Load synthetic dataset into active SQLAlchemy database session.

        Inserts Organization, Business, Products, Customers, Sales, and SaleItems.
        Optionally attaches an in-flight IngestionJob to test pipeline interception.
        """
        biz_id = business_id or dataset["metadata"].get("business_id") or "biz-cadence-synth"
        org_id = organization_id or "org-cadence-synth"

        # Check existing database max IDs to prevent primary key collisions with existing tenants
        from sqlalchemy import func, select

        db_max_cust = session.execute(select(func.coalesce(func.max(Customer.id), 0))).scalar() or 0
        db_max_prod = session.execute(select(func.coalesce(func.max(Product.id), 0))).scalar() or 0
        db_max_sale = session.execute(select(func.coalesce(func.max(Sale.id), 0))).scalar() or 0
        db_max_item = session.execute(select(func.coalesce(func.max(SaleItem.id), 0))).scalar() or 0

        # Check if dataset IDs collide with existing records from other businesses
        cust_ids = [c["id"] for c in dataset["customers"]]
        collision_cust = session.execute(
            select(Customer.id).where(Customer.id.in_(cust_ids[:20]), Customer.business_id != biz_id).limit(1)
        ).scalar_one_or_none() if cust_ids else None

        cust_offset = db_max_cust if collision_cust is not None else 0
        prod_offset = db_max_prod if collision_cust is not None else 0
        sale_offset = db_max_sale if collision_cust is not None else 0
        item_offset = db_max_item if collision_cust is not None else 0

        if cust_offset > 0:
            for c in dataset["customers"]:
                c["id"] += cust_offset
            for s in dataset["sales"]:
                s["customer_id"] += cust_offset

        if prod_offset > 0:
            for p in dataset["products"]:
                p["id"] += prod_offset
            for it in dataset["sale_items"]:
                it["product_id"] += prod_offset

        if sale_offset > 0:
            for s in dataset["sales"]:
                s["id"] += sale_offset
            for it in dataset["sale_items"]:
                it["sale_id"] += sale_offset

        if item_offset > 0:
            for it in dataset["sale_items"]:
                it["id"] += item_offset

        # Check for cross-tenant SKU collisions
        for p in dataset["products"]:
            existing_prod = session.execute(
                select(Product.business_id).where(Product.sku == p["sku"]).limit(1)
            ).scalar_one_or_none()
            if existing_prod is not None and existing_prod != biz_id:
                p["sku"] = f"{biz_id[:8].upper()}-{p['sku']}"

        # Check for cross-tenant transaction_number collisions
        for s in dataset["sales"]:
            existing_sale = session.execute(
                select(Sale.business_id).where(Sale.transaction_number == s["transaction_number"]).limit(1)
            ).scalar_one_or_none()
            if existing_sale is not None and existing_sale != biz_id:
                s["transaction_number"] = f"{biz_id[:8].upper()}-{s['transaction_number']}"

        # 1. Ensure Organization and Business exist
        org = session.get(Organization, org_id)
        if not org:
            org = Organization(
                id=org_id,
                name=f"Org {org_id}",
                slug=f"slug-{org_id}",
                status="active",
            )
            session.add(org)
            session.flush()

        biz = session.get(Business, biz_id)
        if not biz:
            biz = Business(
                id=biz_id,
                organization_id=org_id,
                name=f"Workspace {biz_id}",
                industry="Retail & Distribution",
                status="active",
            )
            session.add(biz)
            session.flush()

        # 2. Add Products
        for p in dataset["products"]:
            prod = Product(
                id=p["id"],
                business_id=biz_id,
                sku=p["sku"],
                name=p["name"],
                category=p["category"],
                subcategory=p["subcategory"],
                unit_cost=p["unit_cost"],
                selling_price=p["selling_price"],
                active=p["active"],
                created_at=p["created_at"],
                updated_at=p["updated_at"],
            )
            session.merge(prod)

        # 3. Add Customers
        for c in dataset["customers"]:
            cust = Customer(
                id=c["id"],
                business_id=biz_id,
                customer_code=c["customer_code"],
                name=c["name"],
                email=c["email"],
                phone=c["phone"],
                city=c["city"],
                customer_segment=c["customer_segment"],
                acquisition_date=c["acquisition_date"],
                created_at=c["created_at"],
                updated_at=c["updated_at"],
            )
            session.merge(cust)
        session.flush()

        # 4. Add Sales
        for s in dataset["sales"]:
            sale = Sale(
                id=s["id"],
                business_id=biz_id,
                transaction_number=s["transaction_number"],
                customer_id=s["customer_id"],
                transaction_date=s["transaction_date"],
                status=s["status"],
                subtotal=s["subtotal"],
                discount_amount=s["discount_amount"],
                tax_amount=s["tax_amount"],
                total_amount=s["total_amount"],
                created_at=s["created_at"],
                updated_at=s["updated_at"],
            )
            session.merge(sale)

        # 5. Add SaleItems
        for it in dataset["sale_items"]:
            item = SaleItem(
                id=it["id"],
                sale_id=it["sale_id"],
                product_id=it["product_id"],
                quantity=it["quantity"],
                unit_price=it["unit_price"],
                discount_amount=it["discount_amount"],
                line_total=it["line_total"],
                created_at=it["created_at"],
                updated_at=it["updated_at"],
            )
            session.merge(item)

        # 6. Optional in-flight ingestion job
        if in_flight_job_status:
            ds = UploadedDataset(
                id=f"ds-{biz_id}",
                business_id=biz_id,
                organization_id=org_id,
                filename="batch_stream.csv",
                file_type="csv",
                storage_key="/storage/batch.csv",
                file_size_bytes=4096,
            )
            session.merge(ds)
            session.flush()

            job = IngestionJob(
                id=f"job-{biz_id}-{uuid.uuid4()}",
                organization_id=org_id,
                business_id=biz_id,
                dataset_id=ds.id,
                status=in_flight_job_status,
            )
            session.merge(job)

        session.commit()

    @classmethod
    def create_scenario(
        cls,
        scenario_name: str,
        seed: int = 42,
        **overrides: Any,
    ) -> dict[str, Any]:
        """
        Factory producing pre-configured datasets for the 10 canonical validation scenarios.

        Scenarios:
        1. complete_pipeline: Healthy, mature dataset with complete follow-up.
        2. delayed_ingestion_valid_watermark: Ingestion delay with authoritative watermark.
        3. incomplete_future_followup: Database truncated before outcome end (right-censored).
        4. seasonal_active: High concentration of seasonal buyers evaluated in off-season.
        5. long_cycle_short_horizon: 90-120d wholesale cycle evaluated with 60d horizon.
        6. high_recency: Cohort with elevated recency / dormant accounts.
        7. irregular_purchasers: High-variance overdispersed purchase intervals (Gamma shape ~1.5).
        8. sparse_segments: Small customer count (N=15) testing segment baseline thresholds.
        9. cross_tenant: Multi-tenant dataset for biz-alpha and biz-beta.
        10. robustness_seeds: Multi-seed comparison fixture.
        """
        gen = cls(seed=seed)

        def _make_cfg(defaults: dict[str, Any]) -> CadenceGeneratorConfig:
            merged = {**defaults, **overrides}
            return CadenceGeneratorConfig(**merged)

        if scenario_name == "complete_pipeline":
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 150,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 12, 31),
                "one_time_buyer_pct": 0.40,
                "mean_ingestion_delay_days": 1.5,
            })
            return gen.generate(cfg)

        elif scenario_name == "delayed_ingestion_valid_watermark":
            # Orders occur up to Dec 31, 2023; pipeline has higher mean delay (4d)
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 120,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 12, 31),
                "mean_ingestion_delay_days": 4.0,
                "tail_delay_prob": 0.10,
            })
            ds = gen.generate(cfg)
            ds["metadata"]["ingestion_watermark"] = datetime(2023, 12, 31, 23, 59, tzinfo=UTC).isoformat()
            return ds

        elif scenario_name == "incomplete_future_followup":
            # Dataset terminates early (e.g. March 15, 2023), so evaluating a cutoff at March 1 with 60d horizon is right-censored
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 80,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 3, 15),
            })
            return gen.generate(cfg)

        elif scenario_name == "seasonal_active":
            # High proportion of seasonal buyers
            weights = {
                CustomerBehaviorArchetype.SEASONAL: 0.50,
                CustomerBehaviorArchetype.ONE_TIME: 0.20,
                CustomerBehaviorArchetype.REGULAR_REPEAT: 0.20,
                CustomerBehaviorArchetype.FREQUENT_REPLENISHMENT: 0.10,
            }
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 100,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 12, 31),
                "one_time_buyer_pct": 0.20,
                "archetype_weights": weights,
            })
            return gen.generate(cfg)

        elif scenario_name == "long_cycle_short_horizon":
            # High proportion of long-cycle (90-120d) wholesale buyers
            weights = {
                CustomerBehaviorArchetype.LONG_CYCLE: 0.50,
                CustomerBehaviorArchetype.ONE_TIME: 0.15,
                CustomerBehaviorArchetype.REGULAR_REPEAT: 0.20,
                CustomerBehaviorArchetype.LONG_INTERVAL_ACTIVE: 0.15,
            }
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 100,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 12, 31),
                "one_time_buyer_pct": 0.15,
                "archetype_weights": weights,
            })
            return gen.generate(cfg)

        elif scenario_name == "high_recency":
            # Dominated by one-time and churning dropout customers
            weights = {
                CustomerBehaviorArchetype.ONE_TIME: 0.65,
                CustomerBehaviorArchetype.CHURNING_DROPOUT: 0.25,
                CustomerBehaviorArchetype.REGULAR_REPEAT: 0.10,
            }
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 120,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 12, 31),
                "one_time_buyer_pct": 0.65,
                "archetype_weights": weights,
            })
            return gen.generate(cfg)

        elif scenario_name == "irregular_purchasers":
            # High interval dispersion
            weights = {
                CustomerBehaviorArchetype.IRREGULAR: 0.50,
                CustomerBehaviorArchetype.ONE_TIME: 0.30,
                CustomerBehaviorArchetype.REGULAR_REPEAT: 0.20,
            }
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 100,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 12, 31),
                "one_time_buyer_pct": 0.30,
                "archetype_weights": weights,
            })
            return gen.generate(cfg)

        elif scenario_name == "sparse_segments":
            # Small total customer base to test segment fallback thresholds
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 15,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 6, 30),
                "one_time_buyer_pct": 0.30,
            })
            return gen.generate(cfg)

        elif scenario_name == "cross_tenant":
            # Multi-tenant scenario
            cfg_a = CadenceGeneratorConfig(
                seed=seed,
                num_customers=50,
                start_date=date(2022, 1, 1),
                end_date=date(2023, 12, 31),
                business_id="biz-alpha",
                organization_id="org-shared",
            )
            cfg_b = CadenceGeneratorConfig(
                seed=seed + 1000,
                num_customers=50,
                start_date=date(2022, 1, 1),
                end_date=date(2023, 12, 31),
                business_id="biz-beta",
                organization_id="org-shared",
            )
            ds_a = gen.generate(cfg_a)
            gen_b = cls(seed=seed + 1000)
            ds_b = gen_b.generate(cfg_b)

            # Re-index ids to avoid collision in combined dict
            offset_cust = len(ds_a["customers"])
            offset_sales = len(ds_a["sales"])
            offset_items = len(ds_a["sale_items"])

            for c in ds_b["customers"]:
                c["id"] += offset_cust
                c["customer_code"] = f"CUST-BETA-{c['id']:05d}"
                c["email"] = f"cust_beta_{c['id']}@nexus-cadence-test.io"
            for s in ds_b["sales"]:
                s["id"] += offset_sales
                s["customer_id"] += offset_cust
                s["transaction_number"] = f"TXN-BETA-{s['id']:07d}"
            for it in ds_b["sale_items"]:
                it["id"] += offset_items
                it["sale_id"] += offset_sales

            return {
                "customers": ds_a["customers"] + ds_b["customers"],
                "products": ds_a["products"],  # Shared product catalog
                "sales": ds_a["sales"] + ds_b["sales"],
                "sale_items": ds_a["sale_items"] + ds_b["sale_items"],
                "metadata": {
                    "scenario": "cross_tenant",
                    "tenants": ["biz-alpha", "biz-beta"],
                    "total_customers": len(ds_a["customers"]) + len(ds_b["customers"]),
                    "total_sales": len(ds_a["sales"]) + len(ds_b["sales"]),
                },
            }

        elif scenario_name == "robustness_seeds":
            # Returns dictionary of multiple datasets across 4 seeds
            seeds = [42, 101, 777, 999]
            multi_ds = {}
            for s in seeds:
                g = cls(seed=s)
                c_cfg = CadenceGeneratorConfig(
                    seed=s,
                    num_customers=80,
                    start_date=date(2022, 1, 1),
                    end_date=date(2023, 12, 31),
                    one_time_buyer_pct=0.40,
                )
                multi_ds[s] = g.generate(c_cfg)
            return {
                "scenarios_by_seed": multi_ds,
                "metadata": {"seeds": seeds, "num_customers_per_seed": 80},
            }

        elif scenario_name == "multi_customer_cadence_validation":
            # Representative 100-customer validation cohort across all behavioral archetypes (Phase 1F)
            weights = {
                CustomerBehaviorArchetype.ONE_TIME: 0.35,
                CustomerBehaviorArchetype.REGULAR_REPEAT: 0.20,
                CustomerBehaviorArchetype.FREQUENT_REPLENISHMENT: 0.15,
                CustomerBehaviorArchetype.IRREGULAR: 0.10,
                CustomerBehaviorArchetype.LONG_CYCLE: 0.08,
                CustomerBehaviorArchetype.SEASONAL: 0.06,
                CustomerBehaviorArchetype.CHURNING_DROPOUT: 0.06,
            }
            cfg = _make_cfg({
                "seed": seed,
                "num_customers": 100,
                "start_date": date(2022, 1, 1),
                "end_date": date(2023, 12, 31),
                "one_time_buyer_pct": 0.35,
                "archetype_weights": weights,
                "customer_code_prefix": "CUST-SYNTH-VAL",
                "transaction_prefix": "TXN-SYNTH-VAL",
                "sku_prefix": "SKU-VAL",
                "email_domain": "nexus-val-synth.io",
                "business_id": "biz-synth-val-phase1f",
                "organization_id": "org-synth-val-phase1f",
                "zero_purchase_pct": 0.05,
            })
            return gen.generate(cfg)

        else:
            raise ValueError(f"Unknown scenario name: '{scenario_name}'")
