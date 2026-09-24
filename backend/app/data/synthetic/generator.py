"""Deterministic Synthetic Data Generator for realistic Retail / Distribution Business."""

import random
import math
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple


def _quantize_decimal(val: float) -> Decimal:
    """Round float to 2 decimal places as exact Decimal."""
    return Decimal(str(round(val, 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


CATEGORIES = {
    "Electronics": {
        "subcategories": ["Audio", "Cables & Adapters", "Smart Devices", "Power & Batteries"],
        "price_range": (15.0, 350.0),
        "margin_range": (0.35, 0.55),
    },
    "Office Supplies": {
        "subcategories": ["Paper Goods", "Desk Organization", "Writing Instruments", "Binding"],
        "price_range": (4.0, 65.0),
        "margin_range": (0.45, 0.65),
    },
    "Industrial Tools": {
        "subcategories": ["Hand Tools", "Safety Equipment", "Fasteners & Hardware", "Measurement"],
        "price_range": (12.0, 480.0),
        "margin_range": (0.30, 0.50),
    },
    "Packaging & Shipping": {
        "subcategories": ["Cardboard Boxes", "Cushioning & Wrap", "Tape & Adhesives", "Envelopes"],
        "price_range": (8.0, 110.0),
        "margin_range": (0.40, 0.60),
    },
    "Workwear & Safety": {
        "subcategories": ["Protective Gloves", "High-Vis Vests", "Work Boots", "Eye Protection"],
        "price_range": (10.0, 180.0),
        "margin_range": (0.38, 0.52),
    },
}

CITIES = [
    ("Seattle", 0.18),
    ("Portland", 0.14),
    ("San Francisco", 0.15),
    ("Denver", 0.12),
    ("Austin", 0.13),
    ("Chicago", 0.16),
    ("Phoenix", 0.12),
]

SEGMENTS = [
    ("Retail", 0.55),
    ("Wholesale", 0.12),
    ("Corporate", 0.18),
    ("VIP", 0.15),
]

EXPENSE_CATEGORIES = [
    ("Rent", "Monthly warehouse & storefront lease", 4500.0, 0.0, True),
    ("Payroll", "Bi-weekly operational and warehouse payroll", 9200.0, 0.05, True),
    ("Utilities", "Electricity, water, heating, and broadband", 1100.0, 0.18, True),
    ("Logistics", "Freight carrier and last-mile delivery fees", 1450.0, 0.35, False),
    ("Marketing", "Search ads, printed flyers, local sponsorships", 1800.0, 0.25, False),
    ("Warehouse Supplies", "Pallets, packing tape, maintenance supplies", 650.0, 0.30, False),
]


class RetailDataGenerator:
    """
    Generates realistic, deterministic relational data for a small retail/distribution company.
    
    Adheres to business rules:
    - 100% exact math (reconcilable line totals and transaction sums).
    - Realistic demand seasonality (Q4 holiday surge, summer lull).
    - Pareto product popularity distribution.
    - Customer segmentation driving order size and volume.
    - Operating expenses with recurring leases and variable logistics.
    """

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.rng = random.Random(seed)

    def generate(
        self,
        num_customers: int = 800,
        num_products: int = 150,
        num_sales: int = 3500,
        months_history: int = 18,
        end_date: Optional[date] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Produce a full relational dataset containing customers, products,
        sales, sale_items, inventory, and expenses.
        """
        # Reset seed for exact reproducibility
        self.rng.seed(self.seed)

        if end_date is None:
            end_date = date.today()
        start_date = end_date - timedelta(days=months_history * 30)

        customers = self._generate_customers(num_customers, start_date, end_date)
        products = self._generate_products(num_products)
        inventory = self._generate_inventory(products)
        sales, sale_items = self._generate_sales_and_items(
            num_sales, customers, products, start_date, end_date
        )
        expenses = self._generate_expenses(start_date, end_date)

        return {
            "customers": customers,
            "products": products,
            "inventory": inventory,
            "sales": sales,
            "sale_items": sale_items,
            "expenses": expenses,
        }

    def _generate_customers(
        self, count: int, start_date: date, end_date: date
    ) -> List[Dict[str, Any]]:
        """Generate customer cohort with realistic segment and acquisition distribution."""
        first_names = [
            "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
            "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
            "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
            "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley",
            "Steven", "Kimberly", "Paul", "Emily", "Andrew", "Donna", "Joshua", "Michelle",
        ]
        last_names = [
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
            "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
            "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
            "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
        ]
        company_suffixes = ["Enterprises", "Logistics", "Retailers", "Solutions", "Supplies", "Group", "LLC", "Corp"]

        total_days = (end_date - start_date).days
        customers: List[Dict[str, Any]] = []

        cities, city_weights = zip(*CITIES)
        segments, segment_weights = zip(*SEGMENTS)

        now_utc = datetime.now(timezone.utc)

        for i in range(1, count + 1):
            segment = self.rng.choices(segments, weights=segment_weights, k=1)[0]
            city = self.rng.choices(cities, weights=city_weights, k=1)[0]


            fn = self.rng.choice(first_names)
            ln = self.rng.choice(last_names)

            if segment in ("Wholesale", "Corporate"):
                name = f"{ln} & {fn} {self.rng.choice(company_suffixes)}"
                email = f"purchasing@{ln.lower()}{fn.lower()}{i}.com"
            else:
                name = f"{fn} {ln}"
                email = f"{fn.lower()}.{ln.lower()}{i}@example.com"

            phone = f"+1-{self.rng.randint(200, 999)}-{self.rng.randint(200, 999)}-{self.rng.randint(1000, 9999)}"

            # Acquisition date skewed toward earlier in history
            acq_offset = int(self.rng.triangular(0, total_days, total_days * 0.3))
            acq_date = start_date + timedelta(days=acq_offset)

            customers.append({
                "id": i,
                "customer_code": f"CUST-{i:05d}",
                "name": name,
                "email": email,
                "phone": phone,
                "city": city,
                "customer_segment": segment,
                "acquisition_date": acq_date,
                "created_at": datetime.combine(acq_date, datetime.min.time(), tzinfo=timezone.utc),
                "updated_at": now_utc,
            })

        return customers

    def _generate_products(self, count: int) -> List[Dict[str, Any]]:
        """Generate product catalog with realistic price tiers and gross margins."""
        category_names = list(CATEGORIES.keys())
        products: List[Dict[str, Any]] = []
        now_utc = datetime.now(timezone.utc)

        adjectives = ["Pro", "Ultra", "Essential", "Industrial", "Heavy-Duty", "Compact", "Precision", "Standard", "Eco"]
        nouns = ["Kit", "Pack", "Module", "System", "Unit", "Station", "Set", "Apparatus"]

        for i in range(1, count + 1):
            cat_name = category_names[(i - 1) % len(category_names)]
            cat_info = CATEGORIES[cat_name]
            subcat = self.rng.choice(cat_info["subcategories"])

            min_p, max_p = cat_info["price_range"]
            # Log-uniform price distribution (more budget products, fewer high-end)
            price = math.exp(self.rng.uniform(math.log(min_p), math.log(max_p)))

            min_m, max_m = cat_info["margin_range"]
            margin = self.rng.uniform(min_m, max_m)
            cost = price * (1.0 - margin)

            price_dec = _quantize_decimal(price)
            cost_dec = _quantize_decimal(cost)

            # Ensure unit_cost <= selling_price
            if cost_dec > price_dec:
                cost_dec = _quantize_decimal(float(price_dec) * 0.7)

            adj = self.rng.choice(adjectives)
            noun = self.rng.choice(nouns)
            name = f"{adj} {subcat} {noun} #{i}"

            products.append({
                "id": i,
                "sku": f"SKU-{cat_name[:3].upper()}-{i:04d}",
                "name": name,
                "category": cat_name,
                "subcategory": subcat,
                "unit_cost": cost_dec,
                "selling_price": price_dec,
                "active": self.rng.random() > 0.05,  # 95% active
                "created_at": now_utc,
                "updated_at": now_utc,
            })

        return products

    def _generate_inventory(self, products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate current inventory levels and reorder thresholds."""
        inventory: List[Dict[str, Any]] = []
        now_utc = datetime.now(timezone.utc)

        locations = ["Zone A (Main)", "Zone B (High-Bay)", "Zone C (Secure)", "Zone D (Bulk Pallets)"]

        for prod in products:
            p_id = prod["id"]
            # Popular items have larger reorder thresholds
            threshold = self.rng.choice([10, 15, 25, 50, 100])
            
            # Stock level: mostly healthy, occasional stockout or low stock
            stock_dice = self.rng.random()
            if stock_dice < 0.04:
                # 4% out of stock
                stock = 0
            elif stock_dice < 0.12:
                # 8% below reorder threshold
                stock = self.rng.randint(1, threshold - 1)
            else:
                # Normal healthy stock
                stock = self.rng.randint(threshold, threshold * 6)

            inventory.append({
                "id": p_id,
                "product_id": p_id,
                "stock_quantity": stock,
                "reorder_threshold": threshold,
                "warehouse_location": self.rng.choice(locations),
                "created_at": now_utc,
                "updated_at": now_utc,
            })

        return inventory

    def _generate_sales_and_items(
        self,
        count: int,
        customers: List[Dict[str, Any]],
        products: List[Dict[str, Any]],
        start_date: date,
        end_date: date,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Generate orders and line items reflecting customer cohorts, seasonality,
        Pareto product popularity, and reconcilable financials.
        """
        sales: List[Dict[str, Any]] = []
        sale_items: List[Dict[str, Any]] = []
        item_counter = 1

        total_days = (end_date - start_date).days
        active_products = [p for p in products if p["active"]]
        if not active_products:
            active_products = products

        # Pre-assign popularity weights (Pareto 80/20 distribution)
        num_prods = len(active_products)
        prod_weights = [1.0 / (idx + 1) ** 0.8 for idx in range(num_prods)]

        now_utc = datetime.now(timezone.utc)

        for s_idx in range(1, count + 1):
            # Select customer
            customer = self.rng.choice(customers)
            c_acq = customer["acquisition_date"]
            c_segment = customer["customer_segment"]

            # Transaction date must be >= customer acquisition date
            days_available = (end_date - c_acq).days
            if days_available <= 0:
                tx_date = c_acq
            else:
                # Seasonal weighting: boost probability in November/December (Q4)
                while True:
                    day_offset = self.rng.randint(0, days_available)
                    candidate_date = c_acq + timedelta(days=day_offset)
                    month = candidate_date.month
                    # Rejection sampling for holiday seasonality
                    seasonality_factor = 1.6 if month in (11, 12) else 1.2 if month in (8, 9) else 1.0
                    if self.rng.random() < (seasonality_factor / 1.6):
                        tx_date = candidate_date
                        break

            # Line items count based on customer segment
            if c_segment == "Wholesale":
                num_items = self.rng.randint(4, 12)
                qty_range = (10, 80)
                seg_discount_pct = self.rng.choice([0.05, 0.10, 0.15])
            elif c_segment == "Corporate":
                num_items = self.rng.randint(2, 6)
                qty_range = (5, 30)
                seg_discount_pct = self.rng.choice([0.0, 0.05, 0.10])
            elif c_segment == "VIP":
                num_items = self.rng.randint(2, 5)
                qty_range = (1, 6)
                seg_discount_pct = self.rng.choice([0.05, 0.10])
            else:  # Retail
                num_items = self.rng.randint(1, 3)
                qty_range = (1, 4)
                seg_discount_pct = 0.0 if self.rng.random() > 0.15 else 0.05

            chosen_prods = self.rng.choices(active_products, weights=prod_weights, k=num_items)
            # Deduplicate items in single order
            chosen_prods = list({p["id"]: p for p in chosen_prods}.values())

            order_subtotal = Decimal("0.00")
            current_sale_items = []

            for p in chosen_prods:
                qty = self.rng.randint(qty_range[0], qty_range[1])
                u_price = p["selling_price"]
                raw_gross = u_price * Decimal(str(qty))

                # Line discount
                line_disc = _quantize_decimal(float(raw_gross) * seg_discount_pct)
                line_total = raw_gross - line_disc

                order_subtotal += line_total

                current_sale_items.append({
                    "id": item_counter,
                    "sale_id": s_idx,
                    "product_id": p["id"],
                    "quantity": qty,
                    "unit_price": u_price,
                    "discount_amount": line_disc,
                    "line_total": line_total,
                    "created_at": datetime.combine(tx_date, datetime.min.time(), tzinfo=timezone.utc),
                    "updated_at": now_utc,
                })
                item_counter += 1

            # Order level promotional coupon discount (occasional)
            order_discount = Decimal("0.00")
            if self.rng.random() < 0.08:
                order_discount = _quantize_decimal(float(order_subtotal) * 0.05)

            # Sales Tax / VAT (approx 7.5%)
            taxable_amount = max(Decimal("0.00"), order_subtotal - order_discount)
            tax_amount = _quantize_decimal(float(taxable_amount) * 0.075)

            total_amount = taxable_amount + tax_amount

            # Status distribution: 94% completed, 3% refunded, 2% pending, 1% cancelled
            status_roll = self.rng.random()
            if status_roll < 0.94:
                status = "completed"
            elif status_roll < 0.97:
                status = "refunded"
            elif status_roll < 0.99:
                status = "pending"
            else:
                status = "cancelled"

            sales.append({
                "id": s_idx,
                "transaction_number": f"TXN-{tx_date.strftime('%Y%m')}-{s_idx:06d}",
                "customer_id": customer["id"],
                "transaction_date": datetime.combine(tx_date, datetime.min.time(), tzinfo=timezone.utc),
                "status": status,
                "subtotal": order_subtotal,
                "discount_amount": order_discount,
                "tax_amount": tax_amount,
                "total_amount": total_amount,
                "created_at": datetime.combine(tx_date, datetime.min.time(), tzinfo=timezone.utc),
                "updated_at": now_utc,
            })
            sale_items.extend(current_sale_items)

        return sales, sale_items

    def _generate_expenses(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Generate recurring overhead and operational variable expenses."""
        expenses: List[Dict[str, Any]] = []
        now_utc = datetime.now(timezone.utc)
        exp_id = 1

        curr_month = date(start_date.year, start_date.month, 1)
        end_month = date(end_date.year, end_date.month, 1)

        while curr_month <= end_month:
            for cat, desc, base_amt, var_pct, recurring in EXPENSE_CATEGORIES:
                # Add monthly expense
                variance = self.rng.uniform(-var_pct, var_pct) if var_pct > 0 else 0.0
                amt = _quantize_decimal(base_amt * (1.0 + variance))

                # Rent on 1st of month, payroll bi-weekly, utilities on 15th
                if cat == "Rent":
                    exp_date = curr_month
                elif cat == "Payroll":
                    exp_date = curr_month + timedelta(days=14)
                elif cat == "Utilities":
                    exp_date = curr_month + timedelta(days=15)
                else:
                    exp_date = curr_month + timedelta(days=self.rng.randint(3, 27))

                if exp_date <= end_date:
                    expenses.append({
                        "id": exp_id,
                        "expense_date": exp_date,
                        "category": cat,
                        "description": desc,
                        "amount": amt,
                        "recurring": recurring,
                        "created_at": datetime.combine(exp_date, datetime.min.time(), tzinfo=timezone.utc),
                        "updated_at": now_utc,
                    })
                    exp_id += 1

            # Advance to next month
            if curr_month.month == 12:
                curr_month = date(curr_month.year + 1, 1, 1)
            else:
                curr_month = date(curr_month.year, curr_month.month + 1, 1)

        return expenses
