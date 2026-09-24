"""Create retail business domain tables (customers, products, sales, sale_items, inventory, expenses).

Revision ID: 001_phase2_retail_schema
Revises: None
Create Date: 2026-09-24 20:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_phase2_retail_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Customers Table
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=False),
        sa.Column("customer_segment", sa.String(length=64), nullable=False),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_code"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_customers_customer_code", "customers", ["customer_code"])
    op.create_index("ix_customers_email", "customers", ["email"])
    op.create_index("ix_customers_city", "customers", ["city"])
    op.create_index("ix_customers_customer_segment", "customers", ["customer_segment"])
    op.create_index("ix_customers_acquisition_date", "customers", ["acquisition_date"])
    op.create_index("ix_customers_segment_city", "customers", ["customer_segment", "city"])

    # 2. Products Table
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("subcategory", sa.String(length=128), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("selling_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("unit_cost >= 0", name="chk_product_unit_cost_non_negative"),
        sa.CheckConstraint("selling_price >= 0", name="chk_product_selling_price_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku"),
    )
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_subcategory", "products", ["subcategory"])
    op.create_index("ix_products_active", "products", ["active"])
    op.create_index("ix_products_category_active", "products", ["category", "active"])

    # 3. Sales Table
    op.create_table(
        "sales",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transaction_number", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0.00"),
        sa.Column("tax_amount", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0.00"),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("subtotal >= 0", name="chk_sales_subtotal_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="chk_sales_discount_non_negative"),
        sa.CheckConstraint("tax_amount >= 0", name="chk_sales_tax_non_negative"),
        sa.CheckConstraint("total_amount >= 0", name="chk_sales_total_non_negative"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_number"),
    )
    op.create_index("ix_sales_transaction_number", "sales", ["transaction_number"])
    op.create_index("ix_sales_customer_id", "sales", ["customer_id"])
    op.create_index("ix_sales_transaction_date", "sales", ["transaction_date"])
    op.create_index("ix_sales_status", "sales", ["status"])
    op.create_index("ix_sales_date_status", "sales", ["transaction_date", "status"])
    op.create_index("ix_sales_customer_date", "sales", ["customer_id", "transaction_date"])

    # 4. Sale Items Table
    op.create_table(
        "sale_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0.00"),
        sa.Column("line_total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="chk_sale_item_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="chk_sale_item_unit_price_non_negative"),
        sa.CheckConstraint("discount_amount >= 0", name="chk_sale_item_discount_non_negative"),
        sa.CheckConstraint("line_total >= 0", name="chk_sale_item_line_total_non_negative"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sale_items_sale_id", "sale_items", ["sale_id"])
    op.create_index("ix_sale_items_product_id", "sale_items", ["product_id"])
    op.create_index("ix_sale_items_product_sale", "sale_items", ["product_id", "sale_id"])

    # 5. Inventory Table
    op.create_table(
        "inventory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("stock_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reorder_threshold", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("warehouse_location", sa.String(length=128), nullable=False, server_default="Main Warehouse"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("stock_quantity >= 0", name="chk_inventory_stock_quantity_non_negative"),
        sa.CheckConstraint("reorder_threshold >= 0", name="chk_inventory_reorder_threshold_non_negative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id"),
    )
    op.create_index("ix_inventory_product_id", "inventory", ["product_id"])

    # 6. Expenses Table
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("recurring", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount >= 0", name="chk_expense_amount_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expenses_expense_date", "expenses", ["expense_date"])
    op.create_index("ix_expenses_category", "expenses", ["category"])
    op.create_index("ix_expenses_category_date", "expenses", ["category", "expense_date"])


def downgrade() -> None:
    op.drop_table("expenses")
    op.drop_table("inventory")
    op.drop_table("sale_items")
    op.drop_table("sales")
    op.drop_table("products")
    op.drop_table("customers")
