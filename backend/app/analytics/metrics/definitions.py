"""Centralized metric definitions catalog for the NEXUS Analytics Engine."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from app.analytics.core.types import MetricUnit


class MetricDefinition(BaseModel):
    """Specification of an analytical metric, its formula, source data, and limitations."""
    key: str
    name: str
    business_meaning: str
    formula: str
    source_tables: List[str]
    source_columns: List[str]
    aggregation_method: str
    unit: MetricUnit
    default_filters: List[str]
    limitations: List[str]


METRIC_DEFINITIONS: Dict[str, MetricDefinition] = {
    "gross_sales": MetricDefinition(
        key="gross_sales",
        name="Gross Sales",
        business_meaning="Total pre-discount transaction value before order-level discounts and taxes.",
        formula="sum(sales.subtotal) OR sum(sale_items.quantity * sale_items.unit_price)",
        source_tables=["sales", "sale_items"],
        source_columns=["subtotal", "quantity", "unit_price"],
        aggregation_method="SUM",
        unit=MetricUnit.CURRENCY,
        default_filters=["status IN ('completed', 'shipped')"],
        limitations=["Does not reflect returns, restocking fees, or order cancellations."],
    ),
    "discounts": MetricDefinition(
        key="discounts",
        name="Total Discounts",
        business_meaning="Aggregate promotional price reductions granted at order and line-item level.",
        formula="sum(sales.discount_amount)",
        source_tables=["sales"],
        source_columns=["discount_amount"],
        aggregation_method="SUM",
        unit=MetricUnit.CURRENCY,
        default_filters=["status IN ('completed', 'shipped')"],
        limitations=["Line-item discounts already factored into line_total; order-level discounts captured separately."],
    ),
    "net_sales": MetricDefinition(
        key="net_sales",
        name="Net Sales / Revenue",
        business_meaning="Realized commercial revenue from completed transactions after trade discounts, excluding tax.",
        formula="sum(sales.subtotal - sales.discount_amount)",
        source_tables=["sales"],
        source_columns=["subtotal", "discount_amount"],
        aggregation_method="SUM(subtotal - discount_amount)",
        unit=MetricUnit.CURRENCY,
        default_filters=["status IN ('completed', 'shipped')"],
        limitations=["Excludes sales tax / VAT. Tax is a balance sheet liability, not recognized business revenue."],
    ),
    "units_sold": MetricDefinition(
        key="units_sold",
        name="Units Sold",
        business_meaning="Total physical count of merchandise units ordered and fulfilled.",
        formula="sum(sale_items.quantity)",
        source_tables=["sale_items", "sales"],
        source_columns=["sale_items.quantity", "sales.status"],
        aggregation_method="SUM",
        unit=MetricUnit.UNITS,
        default_filters=["sales.status IN ('completed', 'shipped')"],
        limitations=["Does not distinguish damaged or returned units."],
    ),
    "orders": MetricDefinition(
        key="orders",
        name="Total Orders",
        business_meaning="Count of distinct fulfilled customer transactions.",
        formula="count(distinct sales.id)",
        source_tables=["sales"],
        source_columns=["id", "status"],
        aggregation_method="COUNT(DISTINCT)",
        unit=MetricUnit.COUNT,
        default_filters=["status IN ('completed', 'shipped')"],
        limitations=["Multi-shipment partial orders are counted as a single order."],
    ),
    "average_order_value": MetricDefinition(
        key="average_order_value",
        name="Average Order Value (AOV)",
        business_meaning="Mean revenue generated per fulfilled customer transaction.",
        formula="Net Sales / Total Orders",
        source_tables=["sales"],
        source_columns=["subtotal", "discount_amount", "id"],
        aggregation_method="SUM(subtotal - discount) / COUNT(id)",
        unit=MetricUnit.CURRENCY,
        default_filters=["status IN ('completed', 'shipped')"],
        limitations=["Undefined if Total Orders is zero; sensitive to extreme corporate bulk orders."],
    ),
    "cogs": MetricDefinition(
        key="cogs",
        name="Cost of Goods Sold (COGS)",
        business_meaning="Direct procurement cost of products sold during the period.",
        formula="sum(sale_items.quantity * products.unit_cost)",
        source_tables=["sale_items", "products", "sales"],
        source_columns=["sale_items.quantity", "products.unit_cost", "sales.status"],
        aggregation_method="SUM(quantity * unit_cost)",
        unit=MetricUnit.CURRENCY,
        default_filters=["sales.status IN ('completed', 'shipped')"],
        limitations=["Uses current catalog product unit_cost as batch-specific historical cost tracking is not in Phase 2 schema."],
    ),
    "gross_profit": MetricDefinition(
        key="gross_profit",
        name="Gross Profit",
        business_meaning="Commercial profit after deducting direct cost of goods sold from net revenue.",
        formula="Net Sales - COGS",
        source_tables=["sales", "sale_items", "products"],
        source_columns=["sales.subtotal", "sales.discount_amount", "sale_items.quantity", "products.unit_cost"],
        aggregation_method="Net Sales - COGS",
        unit=MetricUnit.CURRENCY,
        default_filters=["sales.status IN ('completed', 'shipped')"],
        limitations=["Does not incorporate freight, shipping, or merchant payment gateway fees."],
    ),
    "gross_margin": MetricDefinition(
        key="gross_margin",
        name="Gross Margin Percentage",
        business_meaning="Proportion of net revenue retained as gross profit.",
        formula="(Gross Profit / Net Sales) * 100",
        source_tables=["sales", "sale_items", "products"],
        source_columns=["subtotal", "discount_amount", "quantity", "unit_cost"],
        aggregation_method="Ratio",
        unit=MetricUnit.PERCENTAGE,
        default_filters=["sales.status IN ('completed', 'shipped')"],
        limitations=["Undefined if Net Sales is zero."],
    ),
    "operating_expenses": MetricDefinition(
        key="operating_expenses",
        name="Operating Expenses (OPEX)",
        business_meaning="Total operational overhead expenditures (rent, payroll, utilities, marketing, logistics).",
        formula="sum(expenses.amount)",
        source_tables=["expenses"],
        source_columns=["amount", "expense_date"],
        aggregation_method="SUM",
        unit=MetricUnit.CURRENCY,
        default_filters=["None"],
        limitations=["Capital expenditures (CAPEX) and non-cash depreciation are not separated."],
    ),
    "net_profit": MetricDefinition(
        key="net_profit",
        name="Net Operating Profit",
        business_meaning="Bottom-line earnings before income taxes: Gross Profit minus Operating Expenses.",
        formula="Gross Profit - Operating Expenses",
        source_tables=["sales", "sale_items", "products", "expenses"],
        source_columns=["subtotal", "discount_amount", "quantity", "unit_cost", "expenses.amount"],
        aggregation_method="Gross Profit - OPEX",
        unit=MetricUnit.CURRENCY,
        default_filters=["sales.status IN ('completed', 'shipped')"],
        limitations=["Income taxes, interest, and corporate debt obligations are not represented."],
    ),
    "net_margin": MetricDefinition(
        key="net_margin",
        name="Net Profit Margin Percentage",
        business_meaning="Percentage of net revenue converted into bottom-line operating income.",
        formula="(Net Profit / Net Sales) * 100",
        source_tables=["sales", "sale_items", "products", "expenses"],
        source_columns=["subtotal", "discount_amount", "amount"],
        aggregation_method="Ratio",
        unit=MetricUnit.PERCENTAGE,
        default_filters=["sales.status IN ('completed', 'shipped')"],
        limitations=["Undefined if Net Sales is zero; can be negative if business experiences operating loss."],
    ),
    "inventory_turnover": MetricDefinition(
        key="inventory_turnover",
        name="Inventory Turnover Ratio",
        business_meaning="Number of times stock on hand is sold and replaced over the period.",
        formula="COGS / Average Inventory Value",
        source_tables=["sale_items", "products", "inventory"],
        source_columns=["quantity", "unit_cost", "stock_quantity"],
        aggregation_method="COGS / (sum(inventory.stock_quantity * products.unit_cost))",
        unit=MetricUnit.RATIO,
        default_filters=["Current inventory snapshot used as proxy for average inventory"],
        limitations=["Uses point-in-time stock quantity as periodic average inventory is not tracked in Phase 2."],
    ),
    "inventory_velocity": MetricDefinition(
        key="inventory_velocity",
        name="Inventory Sales Velocity",
        business_meaning="Average physical units sold per day during the evaluated interval.",
        formula="Units Sold / Days in Period",
        source_tables=["sale_items", "sales"],
        source_columns=["quantity", "transaction_date"],
        aggregation_method="SUM(quantity) / Days",
        unit=MetricUnit.RATIO,
        default_filters=["sales.status IN ('completed', 'shipped')"],
        limitations=["Requires a finite non-zero date range interval."],
    ),
    "repeat_purchase_rate": MetricDefinition(
        key="repeat_purchase_rate",
        name="Repeat Purchase Rate",
        business_meaning="Percentage of ordering customers who made two or more distinct purchases.",
        formula="(Customers with >= 2 orders / Total Customers with >= 1 order) * 100",
        source_tables=["sales"],
        source_columns=["customer_id", "status"],
        aggregation_method="Count Ratio",
        unit=MetricUnit.PERCENTAGE,
        default_filters=["sales.status IN ('completed', 'shipped')"],
        limitations=["Evaluated within the bounded analysis window."],
    ),
}


def get_metric_definition(metric_key: str) -> Optional[MetricDefinition]:
    """Retrieve metadata definition for a known business metric."""
    return METRIC_DEFINITIONS.get(metric_key)
