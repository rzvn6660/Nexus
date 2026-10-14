"""KPI Ontology and Deterministic Semantic Resolution for NEXUS.

Maps business terms, synonyms, and conversational language to Phase 3 deterministic
analytics tools, ensuring numbers are only ever computed by AnalyticsService.
"""

import re
from datetime import date
from typing import Any

from app.rag.semantic.models import (
    KPI,
    BusinessDomain,
    BusinessRule,
    Dimension,
    MetricUnit,
    SemanticResolutionResult,
)


class KPIOntology:
    """
    Central registry of approved NEXUS KPIs, business dimensions, and accounting rules.
    Exposes only KPIs deterministically supported by Phase 3 AnalyticsService.
    """

    def __init__(self) -> None:
        self._kpis: dict[str, KPI] = {}
        self._synonym_map: dict[str, str] = {}  # lowercase synonym -> canonical_name
        self._rules: dict[str, BusinessRule] = {}
        self._dimensions: dict[str, Dimension] = {}
        self._dimension_alias_map: dict[str, str] = {}  # lowercase alias -> canonical dimension_name
        self._ambiguous_terms: dict[str, dict[str, Any]] = {}
        self._unsupported_terms: dict[str, str] = {}
        self._register_default_ontology()

    def register_kpi(self, kpi: KPI) -> None:
        """Register a canonical KPI and index its synonyms."""
        self._kpis[kpi.canonical_name] = kpi
        self._synonym_map[kpi.canonical_name.lower().replace("_", " ")] = kpi.canonical_name
        self._synonym_map[kpi.canonical_name.lower()] = kpi.canonical_name
        self._synonym_map[kpi.display_name.lower()] = kpi.canonical_name

        for syn in kpi.synonyms:
            self._synonym_map[syn.lower().strip()] = kpi.canonical_name

    def get_kpi(self, canonical_name: str) -> KPI | None:
        """Lookup KPI by exact canonical name."""
        return self._kpis.get(canonical_name)

    def list_kpis(self, domain: BusinessDomain | None = None) -> list[KPI]:
        """List all active KPIs, optionally filtered by business domain."""
        kpis = [k for k in self._kpis.values() if k.status == "active"]
        if domain:
            kpis = [k for k in kpis if k.business_domain == domain]
        return kpis

    def register_dimension(self, dimension: Dimension) -> None:
        """Register a canonical analytical dimension and index its aliases."""
        self._dimensions[dimension.dimension_name] = dimension
        self._dimension_alias_map[dimension.dimension_name.lower()] = dimension.dimension_name
        self._dimension_alias_map[dimension.dimension_name.lower().replace("_", " ")] = dimension.dimension_name
        self._dimension_alias_map[dimension.display_name.lower()] = dimension.dimension_name
        for alias in dimension.aliases:
            self._dimension_alias_map[alias.lower().strip()] = dimension.dimension_name

    def get_dimension(self, dimension_name: str) -> Dimension | None:
        """Lookup dimension by canonical name or direct alias."""
        dim_key = self._dimension_alias_map.get(dimension_name.lower().strip(), dimension_name)
        return self._dimensions.get(dim_key)

    def list_dimensions(self) -> list[Dimension]:
        """List all registered canonical analytical dimensions."""
        return list(self._dimensions.values())

    def register_rule(self, rule: BusinessRule) -> None:
        """Register a declared business rule or accounting policy."""
        self._rules[rule.rule_id] = rule

    def get_rule(self, rule_id: str) -> BusinessRule | None:
        """Lookup business rule by identifier."""
        return self._rules.get(rule_id)

    def list_rules(self, domain: BusinessDomain | None = None) -> list[BusinessRule]:
        """List active business rules, optionally filtered by domain."""
        rules = [r for r in self._rules.values() if r.active]
        if domain:
            rules = [r for r in rules if r.domain == domain]
        return rules

    def _register_default_ontology(self) -> None:
        """Populate the retail & distribution KPI catalog, dimensions, and rules backed by Phase 3."""

        # -------------------------------------------------------------
        # 0. CANONICAL ANALYTICAL DIMENSIONS
        # -------------------------------------------------------------
        self.register_dimension(Dimension(
            dimension_name="product",
            display_name="Product / SKU",
            source_table="products",
            column_name="sku",
            aliases=["sku", "item", "product_id", "by product", "by sku", "by item", "per product", "product level"],
            applicable_tools=["get_product_rankings", "run_variance_analysis", "run_pareto_concentration", "get_financial_summary", "forecast_metric"],
            filter_key="product_ids",
            description="Merchandise item or stock keeping unit offered in the retail catalog.",
        ))

        self.register_dimension(Dimension(
            dimension_name="category",
            display_name="Product Category",
            source_table="products",
            column_name="category",
            aliases=["department", "product category", "product family", "by category", "by department", "per category"],
            applicable_tools=["get_category_breakdown", "get_financial_summary", "get_inventory_overview", "run_variance_analysis", "forecast_metric"],
            filter_key="categories",
            description="Commercial merchandise taxonomy or catalog department grouping items.",
        ))

        self.register_dimension(Dimension(
            dimension_name="customer_segment",
            display_name="Customer Segment",
            source_table="customers",
            column_name="customer_segment",
            allowed_values=["Retail", "Wholesale", "VIP", "Corporate"],
            aliases=["segment", "customer tier", "tier", "cohort", "by segment", "by customer segment", "per segment"],
            applicable_tools=["get_customer_segments", "run_variance_analysis", "run_hypothesis_test"],
            filter_key="customer_segment",
            description="Market segmentation grouping buyers by volume, commitment, and purchasing characteristics.",
        ))

        self.register_dimension(Dimension(
            dimension_name="customer",
            display_name="Customer / Account",
            source_table="customers",
            column_name="customer_code",
            aliases=["client", "buyer", "account", "by customer", "per customer"],
            applicable_tools=["get_financial_summary", "get_rfm_analysis", "run_pareto_concentration"],
            filter_key="customer_ids",
            description="Individual or corporate purchasing entity in the business ledger.",
        ))

        self.register_dimension(Dimension(
            dimension_name="warehouse",
            display_name="Warehouse / Facility",
            source_table="inventory",
            column_name="warehouse_location",
            aliases=["location", "facility", "storage location", "warehouse location", "by warehouse", "per warehouse"],
            applicable_tools=["get_inventory_overview"],
            filter_key="warehouse",
            description="Physical storage facility or distribution center holding inventory stock.",
        ))

        self.register_dimension(Dimension(
            dimension_name="time_granularity",
            display_name="Time Granularity",
            source_table="sales",
            column_name="transaction_date",
            allowed_values=["daily", "weekly", "monthly", "quarterly"],
            aliases=["granularity", "frequency", "interval", "time bucket", "by day", "by week", "by month", "by quarter", "daily", "weekly", "monthly", "quarterly"],
            applicable_tools=["get_revenue_timeseries", "forecast_metric"],
            filter_key="granularity",
            description="Temporal aggregation interval for time-series trend analysis.",
        ))

        # -------------------------------------------------------------
        # 0B. DOCUMENTED ACCOUNTING & BUSINESS GOVERNANCE RULES
        # -------------------------------------------------------------
        self.register_rule(BusinessRule(
            rule_id="REV-001",
            name="Net Revenue Determination",
            domain=BusinessDomain.FINANCE,
            description="Net revenue is determined as Gross Sales minus promotional discounts. Sales tax is an operational liability collected on behalf of taxing authorities and is strictly excluded from recognized revenue.",
            policy_reference="METRIC_DEFINITIONS: net_sales formula (sum(sales.subtotal - sales.discount_amount))",
        ))

        self.register_rule(BusinessRule(
            rule_id="GP-001",
            name="Gross Profit Determination",
            domain=BusinessDomain.FINANCE,
            description="Gross profit equals Net Revenue minus Cost of Goods Sold (COGS). COGS reflects direct inventory unit procurement cost at transaction time.",
            policy_reference="METRIC_DEFINITIONS: gross_profit formula (Net Sales - COGS)",
        ))

        self.register_rule(BusinessRule(
            rule_id="OP-001",
            name="Operating Profit Determination",
            domain=BusinessDomain.FINANCE,
            description="Net operating profit equals Gross Profit minus Operating Expenses (OPEX). Interest, income taxes, and non-cash asset depreciation are excluded from this operational metric.",
            policy_reference="METRIC_DEFINITIONS: net_profit formula (Gross Profit - Operating Expenses)",
        ))

        self.register_rule(BusinessRule(
            rule_id="INV-001",
            name="Inventory Turnover Policy",
            domain=BusinessDomain.INVENTORY,
            description="Inventory turnover ratio is calculated as annualized COGS divided by total current inventory valuation (stock_quantity * unit_cost).",
            policy_reference="METRIC_DEFINITIONS: inventory_turnover formula",
        ))

        self.register_rule(BusinessRule(
            rule_id="CUST-001",
            name="Repeat Customer Policy",
            domain=BusinessDomain.CUSTOMER,
            description="Repeat purchase rate measures the percentage of ordering customers who completed two or more distinct purchases during the evaluation window.",
            policy_reference="METRIC_DEFINITIONS: repeat_purchase_rate formula",
        ))

        self.register_rule(BusinessRule(
            rule_id="EXP-001",
            name="Operating Expense Classification",
            domain=BusinessDomain.EXPENSES,
            description="Operating expenses are segregated into recurring fixed overhead (rent, utilities, salaries) versus non-recurring variable activity costs (marketing campaigns, freight logistics).",
            policy_reference="METRIC_DEFINITIONS: operating_expenses formula and Expense model recurring flag",
        ))

        # -------------------------------------------------------------
        # 1. FINANCIAL DOMAIN (get_financial_summary)
        # -------------------------------------------------------------
        self.register_kpi(KPI(
            canonical_name="gross_sales",
            display_name="Gross Sales",
            description="Total unadjusted sales value before discounts, allowances, or returns.",
            synonyms=["gross revenue", "total sales value", "unadjusted sales", "topline sales"],
            analytics_tool="get_financial_summary",
            metric_field="gross_sales",
            calculation_reference="SUM(unit_price * quantity)",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["product", "category", "customer_segment", "customer", "time_granularity"],
            supported_filters=["product_ids", "categories", "customer_ids", "date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="discounts",
            display_name="Discounts",
            description="Total price concessions, promotional rebates, and coupon deductions.",
            synonyms=["total discounts", "price reductions", "promotions", "rebates"],
            analytics_tool="get_financial_summary",
            metric_field="total_discounts",
            calculation_reference="SUM(discount_amount)",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["product", "category", "customer_segment", "customer", "time_granularity"],
            supported_filters=["product_ids", "categories", "customer_ids", "date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="net_revenue",
            display_name="Net Revenue",
            description="Total operational revenue realized after deducting discounts and adjustments.",
            synonyms=["net sales", "sales revenue", "topline revenue", "actual revenue", "revenue"],
            analytics_tool="get_financial_summary",
            metric_field="net_revenue",
            calculation_reference="gross_sales - discounts",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["product", "category", "customer_segment", "customer", "time_granularity"],
            supported_filters=["product_ids", "categories", "customer_ids", "date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="units_sold",
            display_name="Units Sold",
            description="Total physical quantity of product items fulfilled across transactions.",
            synonyms=["volume", "total units", "quantity sold", "items sold", "order volume"],
            analytics_tool="get_financial_summary",
            metric_field="units_sold",
            calculation_reference="SUM(quantity)",
            unit=MetricUnit.UNITS,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["product", "category", "time_granularity"],
            supported_filters=["product_ids", "categories", "date_from", "date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="orders",
            display_name="Orders",
            description="Total distinct sales orders placed and processed within the period.",
            synonyms=["total orders", "order count", "number of orders", "transactions"],
            analytics_tool="get_financial_summary",
            metric_field="orders_count",
            calculation_reference="COUNT(DISTINCT order_id)",
            unit=MetricUnit.COUNT,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["customer_segment", "time_granularity"],
            supported_filters=["customer_ids", "date_from", "date_to"],
            default_dimension="time_granularity",
        ))

        self.register_kpi(KPI(
            canonical_name="average_order_value",
            display_name="Average Order Value (AOV)",
            description="Mean net revenue generated per distinct customer transaction.",
            synonyms=["aov", "average basket size", "order average", "mean order value"],
            analytics_tool="get_financial_summary",
            metric_field="average_order_value",
            calculation_reference="net_revenue / orders",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["customer_segment", "time_granularity"],
            supported_filters=["customer_ids", "date_from", "date_to"],
            default_dimension="customer_segment",
        ))

        self.register_kpi(KPI(
            canonical_name="cogs",
            display_name="Cost of Goods Sold (COGS)",
            description="Direct inventory acquisition and unit procurement costs for products sold.",
            synonyms=["cost of goods sold", "product costs", "inventory cost", "direct cost"],
            analytics_tool="get_financial_summary",
            metric_field="cogs",
            calculation_reference="SUM(cost_price * quantity)",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["product", "category", "time_granularity"],
            supported_filters=["product_ids", "categories", "date_from", "date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="gross_profit",
            display_name="Gross Profit",
            description="Operational profit remaining after deducting direct product procurement costs.",
            synonyms=["gross income", "gross contribution", "trading profit"],
            analytics_tool="get_financial_summary",
            metric_field="gross_profit",
            calculation_reference="net_revenue - cogs",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["product", "category", "customer_segment", "time_granularity"],
            supported_filters=["product_ids", "categories", "date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="gross_margin",
            display_name="Gross Margin",
            description="Ratio of gross profit to net revenue, representing product profitability percentage.",
            synonyms=["gross profit margin", "gross margin percentage", "gpm"],
            analytics_tool="get_financial_summary",
            metric_field="gross_margin_pct",
            calculation_reference="(gross_profit / net_revenue) * 100",
            unit=MetricUnit.PERCENTAGE,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["product", "category", "time_granularity"],
            supported_filters=["product_ids", "categories", "date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="opex",
            display_name="Operating Expenses (OPEX)",
            description="Total overhead expenses including facilities, logistics, marketing, and utilities.",
            synonyms=["overhead", "operating costs", "operating expenditures"],
            analytics_tool="get_financial_summary",
            metric_field="operating_expenses",
            calculation_reference="SUM(operating_expenses.amount)",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.EXPENSES,
            supported_dimensions=["category", "time_granularity"],
            supported_filters=["date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="net_profit",
            display_name="Net Profit",
            description="Operating net earnings after deducting both COGS and operating overhead.",
            synonyms=["net income", "operating profit", "bottom line", "net earnings"],
            analytics_tool="get_financial_summary",
            metric_field="net_profit",
            calculation_reference="gross_profit - opex",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["category", "time_granularity"],
            supported_filters=["date_from", "date_to"],
            default_dimension="time_granularity",
        ))

        self.register_kpi(KPI(
            canonical_name="net_margin",
            display_name="Net Margin",
            description="Net profit expressed as a percentage of net revenue.",
            synonyms=["net profit margin", "operating margin", "net margin percentage", "npm"],
            analytics_tool="get_financial_summary",
            metric_field="net_margin_pct",
            calculation_reference="(net_profit / net_revenue) * 100",
            unit=MetricUnit.PERCENTAGE,
            business_domain=BusinessDomain.FINANCE,
            supported_dimensions=["category", "time_granularity"],
            supported_filters=["date_from", "date_to"],
            default_dimension="time_granularity",
        ))

        # -------------------------------------------------------------
        # 2. CUSTOMER DOMAIN (get_customer_segments, get_repeat_purchase, get_rfm_analysis)
        # -------------------------------------------------------------
        self.register_kpi(KPI(
            canonical_name="active_customer",
            display_name="Active Customers",
            description="Unique customers who have completed at least one verified order within the evaluation period.",
            synonyms=["active buyers", "transacting customers", "active accounts", "customer count"],
            analytics_tool="get_customer_segments",
            metric_field="active_customers_count",
            calculation_reference="COUNT(DISTINCT customer_id) in period",
            unit=MetricUnit.COUNT,
            business_domain=BusinessDomain.CUSTOMER,
            supported_dimensions=["customer_segment"],
            supported_filters=["date_from", "date_to"],
            default_dimension="customer_segment",
        ))

        self.register_kpi(KPI(
            canonical_name="repeat_customer",
            display_name="Repeat Customers",
            description="Customers with two or more historical completed orders across their lifetime.",
            synonyms=["returning customers", "multi-order customers", "loyal customers"],
            analytics_tool="get_repeat_purchase",
            metric_field="repeat_customers_count",
            calculation_reference="COUNT(customers with lifetime orders >= 2)",
            unit=MetricUnit.COUNT,
            business_domain=BusinessDomain.CUSTOMER,
            supported_dimensions=["customer_segment"],
            supported_filters=["date_from", "date_to"],
            default_dimension="customer_segment",
        ))

        self.register_kpi(KPI(
            canonical_name="repeat_purchase_rate",
            display_name="Repeat Purchase Rate",
            description="Percentage of transacting customers who have completed more than one purchase.",
            synonyms=["repeat rate", "reorder rate", "retention rate", "customer loyalty rate"],
            analytics_tool="get_repeat_purchase",
            metric_field="repeat_purchase_rate",
            calculation_reference="(repeat_customers / total_customers) * 100",
            unit=MetricUnit.PERCENTAGE,
            business_domain=BusinessDomain.CUSTOMER,
            supported_dimensions=["customer_segment"],
            supported_filters=["date_from", "date_to"],
            default_dimension="customer_segment",
        ))

        self.register_kpi(KPI(
            canonical_name="recency",
            display_name="Recency",
            description="Days elapsed between the customer's most recent completed order and analysis snapshot date.",
            synonyms=["recency score", "days since last order", "last active days"],
            analytics_tool="get_rfm_analysis",
            metric_field="recency_days",
            calculation_reference="reference_date - MAX(order_date)",
            unit=MetricUnit.DAYS,
            business_domain=BusinessDomain.CUSTOMER,
            supported_dimensions=["customer", "customer_segment"],
            supported_filters=["customer_ids"],
            default_dimension="customer_segment",
        ))

        self.register_kpi(KPI(
            canonical_name="frequency",
            display_name="Frequency",
            description="Total number of distinct completed orders placed by a customer over their history.",
            synonyms=["order frequency", "purchase count", "transaction frequency"],
            analytics_tool="get_rfm_analysis",
            metric_field="frequency_count",
            calculation_reference="COUNT(order_id) per customer",
            unit=MetricUnit.COUNT,
            business_domain=BusinessDomain.CUSTOMER,
            supported_dimensions=["customer", "customer_segment"],
            supported_filters=["customer_ids"],
            default_dimension="customer_segment",
        ))

        self.register_kpi(KPI(
            canonical_name="monetary_value",
            display_name="Monetary Value",
            description="Aggregate cumulative net spend generated by a customer across all transactions.",
            synonyms=["total customer spend", "cumulative spend", "customer monetary score"],
            analytics_tool="get_rfm_analysis",
            metric_field="monetary_value",
            calculation_reference="SUM(net_revenue) per customer",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.CUSTOMER,
            supported_dimensions=["customer", "customer_segment"],
            supported_filters=["customer_ids"],
            default_dimension="customer_segment",
        ))

        self.register_kpi(KPI(
            canonical_name="customer_segment",
            display_name="Customer Segment",
            description="Categorization of customers (e.g., VIP, Regular, Wholesale, Inactive) based on RFM or business rules.",
            synonyms=["tier", "customer tier", "rfm segment", "cohort segment"],
            analytics_tool="get_customer_segments",
            metric_field="segments",
            calculation_reference="RFM Quintiles or Tier Classification",
            unit=MetricUnit.COUNT,
            business_domain=BusinessDomain.CUSTOMER,
            supported_dimensions=["customer_segment"],
            supported_filters=["customer_segment"],
            default_dimension="customer_segment",
        ))

        # -------------------------------------------------------------
        # 3. PRODUCT DOMAIN (get_product_rankings, get_category_breakdown)
        # -------------------------------------------------------------
        self.register_kpi(KPI(
            canonical_name="product_revenue",
            display_name="Product Revenue",
            description="Net revenue generated by individual product items or SKUs.",
            synonyms=["sku revenue", "item revenue", "product sales"],
            analytics_tool="get_product_rankings",
            metric_field="product_revenue",
            calculation_reference="SUM(unit_price * quantity - discounts) GROUP BY product_id",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.PRODUCT,
            supported_dimensions=["product", "category"],
            supported_filters=["product_ids", "categories", "date_from", "date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="product_profit",
            display_name="Product Profit",
            description="Net gross profit contribution produced by an individual product item.",
            synonyms=["product margin contribution", "sku profit", "item profit"],
            analytics_tool="get_product_rankings",
            metric_field="product_profit",
            calculation_reference="SUM((unit_price - cost_price) * quantity) GROUP BY product_id",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.PRODUCT,
            supported_dimensions=["product", "category"],
            supported_filters=["product_ids", "categories", "date_from", "date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="product_margin",
            display_name="Product Margin",
            description="Gross profit percentage earned on a specific product item.",
            synonyms=["product margin percentage", "sku margin"],
            analytics_tool="get_product_rankings",
            metric_field="product_margin_pct",
            calculation_reference="(product_profit / product_revenue) * 100",
            unit=MetricUnit.PERCENTAGE,
            business_domain=BusinessDomain.PRODUCT,
            supported_dimensions=["product", "category"],
            supported_filters=["product_ids", "categories", "date_from", "date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="category_revenue",
            display_name="Category Revenue",
            description="Aggregated net sales revenue categorized by catalog product department or taxonomy.",
            synonyms=["department revenue", "category sales", "department sales"],
            analytics_tool="get_category_breakdown",
            metric_field="category_revenue",
            calculation_reference="SUM(net_revenue) GROUP BY category_name",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.PRODUCT,
            supported_dimensions=["category"],
            supported_filters=["categories", "date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="category_profit",
            display_name="Category Profit",
            description="Total gross profit contribution generated across an entire product category.",
            synonyms=["category contribution", "department profit"],
            analytics_tool="get_category_breakdown",
            metric_field="category_profit",
            calculation_reference="SUM(gross_profit) GROUP BY category_name",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.PRODUCT,
            supported_dimensions=["category"],
            supported_filters=["categories", "date_from", "date_to"],
            default_dimension="category",
        ))

        # -------------------------------------------------------------
        # 4. INVENTORY DOMAIN (get_inventory_overview, get_inventory_turnover, get_inventory_velocity)
        # -------------------------------------------------------------
        self.register_kpi(KPI(
            canonical_name="stock_value",
            display_name="Stock Value",
            description="Total current valuation of on-hand inventory evaluated at cost price.",
            synonyms=["inventory value", "total inventory valuation", "warehouse valuation", "stock valuation"],
            analytics_tool="get_inventory_overview",
            metric_field="total_inventory_value",
            calculation_reference="SUM(current_stock * cost_price)",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.INVENTORY,
            supported_dimensions=["warehouse", "category", "product"],
            supported_filters=["warehouse", "category"],
            default_dimension="warehouse",
        ))

        self.register_kpi(KPI(
            canonical_name="inventory_turnover",
            display_name="Inventory Turnover",
            description="Number of times average inventory is cycled, sold, and replenished over a period.",
            synonyms=["stock turn", "inventory turns", "stock turnover ratio"],
            analytics_tool="get_inventory_turnover",
            metric_field="inventory_turnover_ratio",
            calculation_reference="annualized_cogs / average_inventory_value",
            unit=MetricUnit.RATIO,
            business_domain=BusinessDomain.INVENTORY,
            supported_dimensions=["product", "category"],
            supported_filters=["date_from", "date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="days_sales_inventory",
            display_name="Days Sales of Inventory (DSI)",
            description="Average number of days required to convert physical inventory into realized sales.",
            synonyms=["dsi", "days of supply", "days sales in inventory", "inventory days"],
            analytics_tool="get_inventory_turnover",
            metric_field="days_sales_of_inventory",
            calculation_reference="(average_inventory_value / annualized_cogs) * 365",
            unit=MetricUnit.DAYS,
            business_domain=BusinessDomain.INVENTORY,
            supported_dimensions=["product", "category"],
            supported_filters=["date_from", "date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="sales_velocity",
            display_name="Sales Velocity",
            description="Daily or weekly burn rate of physical units sold per SKU, categorizing items into fast/slow/dormant.",
            synonyms=["run rate", "stock velocity", "unit velocity", "sku velocity"],
            analytics_tool="get_inventory_velocity",
            metric_field="daily_run_rate",
            calculation_reference="units_sold / period_days",
            unit=MetricUnit.UNITS,
            business_domain=BusinessDomain.INVENTORY,
            supported_dimensions=["product", "category"],
            supported_filters=["date_from", "date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="reorder_alert",
            display_name="Reorder Alerts",
            description="Count and list of inventory SKUs whose current on-hand stock is at or below defined safety reorder thresholds.",
            synonyms=["low stock alert", "stockout risk", "reorder threshold alerts", "understocked items"],
            analytics_tool="get_inventory_overview",
            metric_field="low_stock_items_count",
            calculation_reference="COUNT(skus WHERE current_stock <= reorder_level)",
            unit=MetricUnit.COUNT,
            business_domain=BusinessDomain.INVENTORY,
            supported_dimensions=["warehouse", "category"],
            supported_filters=["warehouse", "category"],
            default_dimension="warehouse",
        ))

        # -------------------------------------------------------------
        # 5. EXPENSES DOMAIN (get_expense_analytics)
        # -------------------------------------------------------------
        self.register_kpi(KPI(
            canonical_name="operating_expense",
            display_name="Operating Expenses",
            description="Day-to-day administrative, marketing, facility, and operational costs.",
            synonyms=["total expenses", "business overhead", "operating expenditure"],
            analytics_tool="get_expense_analytics",
            metric_field="total_expenses",
            calculation_reference="SUM(amount) from operating_expenses",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.EXPENSES,
            supported_dimensions=["category", "time_granularity"],
            supported_filters=["date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="fixed_expense",
            display_name="Fixed Expenses",
            description="Static operating expenses incurred regardless of production or sales volume (e.g. rent, salaries).",
            synonyms=["fixed costs", "overhead rent", "contractual expenses"],
            analytics_tool="get_expense_analytics",
            metric_field="fixed_expenses",
            calculation_reference="SUM(amount) WHERE is_recurring = TRUE",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.EXPENSES,
            supported_dimensions=["category", "time_granularity"],
            supported_filters=["date_from", "date_to"],
            default_dimension="category",
        ))

        self.register_kpi(KPI(
            canonical_name="variable_expense",
            display_name="Variable Expenses",
            description="Operational costs that fluctuate directly with business activity and order volume (e.g. shipping, marketing spend).",
            synonyms=["variable costs", "fluctuating expenses", "activity costs"],
            analytics_tool="get_expense_analytics",
            metric_field="variable_expenses",
            calculation_reference="SUM(amount) WHERE is_recurring = FALSE",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.EXPENSES,
            supported_dimensions=["category", "time_granularity"],
            supported_filters=["date_from", "date_to"],
            default_dimension="category",
        ))

        # -------------------------------------------------------------
        # 6. DIAGNOSTIC DOMAIN (run_variance_analysis, run_price_volume_mix)
        # -------------------------------------------------------------
        self.register_kpi(KPI(
            canonical_name="revenue_variance",
            display_name="Revenue Variance",
            description="Absolute and percentage delta between current period and comparison period net revenues.",
            synonyms=["sales delta", "revenue difference", "variance", "period over period variance"],
            analytics_tool="run_variance_analysis",
            metric_field="revenue_change",
            calculation_reference="current_revenue - prior_revenue",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.DIAGNOSTIC,
            supported_dimensions=["product", "category", "customer_segment"],
            supported_filters=["dimension", "date_from", "date_to", "comparison_date_from", "comparison_date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="price_effect",
            display_name="Price Effect",
            description="Proportion of revenue variance driven by unit price changes independent of volume.",
            synonyms=["price variance", "pricing impact"],
            analytics_tool="run_price_volume_mix",
            metric_field="price_effect",
            calculation_reference="(P1 - P0) * Q1",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.DIAGNOSTIC,
            supported_dimensions=["product", "category"],
            supported_filters=["date_from", "date_to", "comparison_date_from", "comparison_date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="volume_effect",
            display_name="Volume Effect",
            description="Proportion of revenue variance driven by change in quantity of units sold at prior prices.",
            synonyms=["volume variance", "quantity impact"],
            analytics_tool="run_price_volume_mix",
            metric_field="volume_effect",
            calculation_reference="(Q1 - Q0) * P0",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.DIAGNOSTIC,
            supported_dimensions=["product", "category"],
            supported_filters=["date_from", "date_to", "comparison_date_from", "comparison_date_to"],
            default_dimension="product",
        ))

        self.register_kpi(KPI(
            canonical_name="mix_effect",
            display_name="Mix Effect",
            description="Variance impact resulting from shifts in the proportion of higher-margin vs lower-margin items sold.",
            synonyms=["mix variance", "product mix impact", "portfolio mix"],
            analytics_tool="run_price_volume_mix",
            metric_field="mix_effect",
            calculation_reference="Total Variance - (Price Effect + Volume Effect)",
            unit=MetricUnit.CURRENCY,
            business_domain=BusinessDomain.DIAGNOSTIC,
            supported_dimensions=["product", "category"],
            supported_filters=["date_from", "date_to", "comparison_date_from", "comparison_date_to"],
            default_dimension="product",
        ))

        # -------------------------------------------------------------
        # 7. STATISTICS DOMAIN (run_correlation, run_hypothesis_test)
        # -------------------------------------------------------------
        self.register_kpi(KPI(
            canonical_name="correlation",
            display_name="Correlation Coefficient",
            description="Statistical measure of linear association (Pearson r) or monotonic rank relationship (Spearman rho).",
            synonyms=["correlation analysis", "bivariate correlation", "pearson r", "spearman rho"],
            analytics_tool="run_correlation",
            metric_field="coefficient",
            calculation_reference="Cov(X, Y) / (Std(X) * Std(Y))",
            unit=MetricUnit.RATIO,
            business_domain=BusinessDomain.STATISTICS,
            supported_dimensions=["customer", "product"],
            supported_filters=["date_from", "date_to"],
            default_dimension="customer",
        ))

        self.register_kpi(KPI(
            canonical_name="p_value",
            display_name="P-Value",
            description="Probability of observing test results under the null hypothesis of no statistical difference or relationship.",
            synonyms=["statistical significance", "p value", "significance level"],
            analytics_tool="run_hypothesis_test",
            metric_field="p_value",
            calculation_reference="Two-tailed Welch's t-test p-value",
            unit=MetricUnit.RATIO,
            business_domain=BusinessDomain.STATISTICS,
            supported_dimensions=["customer_segment"],
            supported_filters=["group1_segment", "group2_segment", "metric"],
            default_dimension="customer_segment",
        ))

        self.register_kpi(KPI(
            canonical_name="hypothesis_test",
            display_name="Hypothesis Test",
            description="Rigorous two-sample Welch's t-test comparing metric distributions across customer segments or groups.",
            synonyms=["ab test", "welch test", "difference test", "t test", "segment comparison test"],
            analytics_tool="run_hypothesis_test",
            metric_field="t_statistic",
            calculation_reference="(Mean1 - Mean2) / sqrt(s1^2/n1 + s2^2/n2)",
            unit=MetricUnit.RATIO,
            business_domain=BusinessDomain.STATISTICS,
            supported_dimensions=["customer_segment"],
            supported_filters=["group1_segment", "group2_segment", "metric"],
            default_dimension="customer_segment",
        ))

        # -------------------------------------------------------------
        # EXPANDED AMBIGUOUS TERMS CONFIGURATION (Phase 25D.2)
        # -------------------------------------------------------------
        self._ambiguous_terms = {
            "turnover": {
                "candidates": ["net_revenue", "inventory_turnover"],
                "prompt": "The term 'turnover' is ambiguous in retail. Do you mean Net Revenue (sales turnover) or Inventory Turnover (stock velocity)?",
            },
            "sales": {
                "candidates": ["gross_sales", "net_revenue", "units_sold", "orders"],
                "prompt": "The term 'sales' can refer to Gross Sales (before discounts), Net Revenue (after discounts), Units Sold, or Orders. Which metric would you like to analyze?",
            },
            "margin": {
                "candidates": ["gross_margin", "net_margin", "product_margin"],
                "prompt": "The term 'margin' can mean Gross Margin (product profitability), Net Margin (after operating overhead), or Product Margin percentage. Which would you like to inspect?",
            },
            "profit": {
                "candidates": ["gross_profit", "net_profit", "product_profit"],
                "prompt": "The term 'profit' can refer to Gross Profit (revenue minus COGS), Net Profit (operating profit after OPEX), or individual Product Profit. Which would you like to analyze?",
            },
            "cost": {
                "candidates": ["cogs", "operating_expense", "fixed_expense", "variable_expense"],
                "prompt": "The term 'cost' can refer to Cost of Goods Sold (COGS), Total Operating Expenses, Fixed Costs, or Variable Costs. Which cost metric would you like to examine?",
            },
            "expenses": {
                "candidates": ["operating_expense", "fixed_expense", "variable_expense"],
                "prompt": "The term 'expenses' can refer to Total Operating Expenses, Fixed Recurring Expenses, or Variable Expenses. Which expense category would you like to analyze?",
            },
            "retention": {
                "candidates": ["repeat_purchase_rate", "active_customer"],
                "prompt": "The term 'retention' can refer to Repeat Purchase Rate (percentage of returning buyers) or Active Customer count. Which retention metric would you like to examine?",
            },
            "volume": {
                "candidates": ["units_sold", "orders"],
                "prompt": "The term 'volume' can refer to Units Sold (physical product quantity) or Order Count (transaction volume). Which volume metric would you like to analyze?",
            },
        }

        # -------------------------------------------------------------
        # EXPLICIT UNSUPPORTED METRICS (Guardrails against hallucination)
        # -------------------------------------------------------------
        self._unsupported_terms = {
            "customer lifetime value": "Customer Lifetime Value (CLV) is not currently supported by the NEXUS metric catalog.",
            "clv": "Customer Lifetime Value (CLV) is not currently supported by the NEXUS metric catalog.",
            "cltv": "Customer Lifetime Value (CLV) is not currently supported by the NEXUS metric catalog.",
            "ltv": "Customer Lifetime Value (LTV) is not currently supported by the NEXUS metric catalog.",
            "churn rate": "Customer Churn Prediction and Churn Rate are scheduled for a future release and not currently supported in Phase 5.",
            "churn": "Customer Churn Prediction is scheduled for a future release and not currently supported in Phase 5.",
            "customer acquisition cost": "Customer Acquisition Cost (CAC) is not currently tracked by the NEXUS metric catalog.",
            "cac": "Customer Acquisition Cost (CAC) is not currently tracked by the NEXUS metric catalog.",
            "net promoter score": "Net Promoter Score (NPS) is not currently integrated into the NEXUS telemetry catalog.",
            "nps": "Net Promoter Score (NPS) is not currently integrated into the NEXUS telemetry catalog.",
        }


class SemanticResolver:
    """
    Deterministic resolution engine matching natural language business queries
    to approved KPIs, dimensions, filters, and temporal intervals, detecting ambiguities
    and rejecting unsupported metrics.
    """

    def __init__(self, ontology: KPIOntology | None = None) -> None:
        self.ontology = ontology or KPIOntology()

    def resolve(self, query: str, reference_date: date | None = None) -> SemanticResolutionResult:
        """
        Deterministically resolve user query against the KPI ontology.
        
        Priority:
        1. Explicit unsupported metric rejection (confidence=0.0).
        2. Analytical dimension and alias extraction.
        3. Validated filter and temporal context extraction (via DateInterpreter).
        4. Known ambiguous term detection with candidate qualifier disambiguation.
        5. Exact canonical or synonym match (longest matching phrase first).
        6. Clean empty fallback resolution (confidence=0.0).
        """
        clean_query = query.lower().strip()
        clean_query = re.sub(r"[?!.,;:]+$", "", clean_query)

        # 1. Check for explicit unsupported terms
        for term, message in self.ontology._unsupported_terms.items():
            pattern = rf"\b{re.escape(term)}\b"
            if re.search(pattern, clean_query):
                return SemanticResolutionResult(
                    query=query,
                    is_supported=False,
                    unsupported_message=message,
                    confidence=0.0,
                )

        # 2. Extract dimensions and dimension aliases
        resolved_dimensions: list[str] = []
        matched_dimension_aliases: dict[str, str] = {}
        for alias, dim_name in sorted(
            self.ontology._dimension_alias_map.items(), key=lambda x: len(x[0]), reverse=True
        ):
            pattern = rf"\b{re.escape(alias)}\b"
            if re.search(pattern, clean_query) and dim_name not in resolved_dimensions:
                resolved_dimensions.append(dim_name)
                matched_dimension_aliases[alias] = dim_name

        # Detect explicitly requested grouping terms that are unsupported dimensions
        unsupported_dimensions: list[str] = []
        by_terms = re.findall(r"\bby\s+([a-zA-Z_]+)\b", clean_query)
        for bt in by_terms:
            bt_clean = bt.lower()
            if (
                bt_clean not in self.ontology._dimension_alias_map
                and bt_clean not in ("month", "quarter", "year", "day", "week", "date")
                and bt_clean not in unsupported_dimensions
            ):
                unsupported_dimensions.append(bt_clean)

        # 3. Extract validated entity filters and temporal context
        extracted_filters: dict[str, Any] = {}
        
        # Check customer segments
        cust_dim = self.ontology.get_dimension("customer_segment")
        if cust_dim and cust_dim.allowed_values:
            for seg in cust_dim.allowed_values:
                if re.search(rf"\b{re.escape(seg.lower())}\b", clean_query):
                    extracted_filters["customer_segment"] = seg

        # Check warehouse locations
        if "main warehouse" in clean_query:
            extracted_filters["warehouse"] = "Main Warehouse"

        # Check temporal context via existing DateInterpreter
        temporal_ctx: dict[str, Any] | None = None
        try:
            from app.agents.tools.date_interpreter import DateInterpreter
            date_res = DateInterpreter.interpret(query, reference_date=reference_date)
            if date_res.get("matched_expression") is not None or date_res.get("date_from") is not None:
                temporal_ctx = dict(date_res)
                if date_res.get("date_from"):
                    extracted_filters["date_from"] = str(date_res["date_from"])
                if date_res.get("date_to"):
                    extracted_filters["date_to"] = str(date_res["date_to"])
                if date_res.get("granularity") and "time_granularity" not in resolved_dimensions:
                    resolved_dimensions.append("time_granularity")
        except (ValueError, TypeError, KeyError, AttributeError):
            temporal_ctx = None

        # 4. Check for known ambiguous terms
        for ambig_term, info in self.ontology._ambiguous_terms.items():
            pattern = rf"\b{re.escape(ambig_term)}\b"
            if re.search(pattern, clean_query):
                # Check if query has a qualifying phrase that directly disambiguates to a candidate
                has_qualifier = False
                matched_candidate: KPI | None = None
                matched_qualifier_phrase: str = ""
                for cand_name in info["candidates"]:
                    cand_kpi = self.ontology.get_kpi(cand_name)
                    if not cand_kpi:
                        continue
                    candidate_phrases = (
                        [cand_kpi.canonical_name.replace("_", " "), cand_kpi.display_name]
                        + cand_kpi.synonyms
                    )
                    # Check longest matching candidate phrase first
                    for syn in sorted(candidate_phrases, key=len, reverse=True):
                        syn_clean = syn.lower()
                        if syn_clean != ambig_term and re.search(rf"\b{re.escape(syn_clean)}\b", clean_query):
                            has_qualifier = True
                            matched_candidate = cand_kpi
                            matched_qualifier_phrase = syn_clean
                            break
                    if has_qualifier:
                        break

                if has_qualifier and matched_candidate:
                    is_exact = (
                        matched_qualifier_phrase == matched_candidate.canonical_name.lower().replace("_", " ")
                        or matched_qualifier_phrase == matched_candidate.display_name.lower()
                    )
                    provenance = {
                        "analytics_tool": matched_candidate.analytics_tool,
                        "metric_field": matched_candidate.metric_field,
                        "calculation_reference": matched_candidate.calculation_reference,
                        "business_domain": matched_candidate.business_domain.value,
                        "lineage_verified": True,
                    }
                    return SemanticResolutionResult(
                        query=query,
                        resolved_kpi=matched_candidate,
                        canonical_name=matched_candidate.canonical_name,
                        analytics_tool=matched_candidate.analytics_tool,
                        metric_field=matched_candidate.metric_field,
                        is_ambiguous=False,
                        is_supported=True,
                        confidence=1.0 if is_exact else 0.95,
                        resolved_dimensions=resolved_dimensions,
                        extracted_filters=extracted_filters,
                        temporal_context=temporal_ctx,
                        evidence_provenance=provenance,
                        matched_dimension_aliases=matched_dimension_aliases,
                        matched_synonym=matched_qualifier_phrase,
                    )

                # Otherwise, it IS ambiguous!
                candidates = [
                    self.ontology.get_kpi(c) for c in info["candidates"]
                    if self.ontology.get_kpi(c) is not None
                ]
                return SemanticResolutionResult(
                    query=query,
                    is_ambiguous=True,
                    candidate_kpis=candidates,  # type: ignore
                    clarification_prompt=info["prompt"],
                    is_supported=True,
                    confidence=0.0,
                    resolved_dimensions=resolved_dimensions,
                    extracted_filters=extracted_filters,
                    temporal_context=temporal_ctx,
                    evidence_provenance=None,
                    matched_dimension_aliases=matched_dimension_aliases,
                )

        # 5. Match against canonical names and synonyms
        sorted_synonyms = sorted(
            self.ontology._synonym_map.keys(), key=lambda s: len(s), reverse=True
        )

        for syn in sorted_synonyms:
            pattern = rf"\b{re.escape(syn)}\b"
            if re.search(pattern, clean_query):
                canonical = self.ontology._synonym_map[syn]
                kpi = self.ontology.get_kpi(canonical)
                if kpi:
                    is_exact = (
                        syn == kpi.canonical_name.lower()
                        or syn == kpi.canonical_name.lower().replace("_", " ")
                        or syn == kpi.display_name.lower()
                    )
                    provenance = {
                        "analytics_tool": kpi.analytics_tool,
                        "metric_field": kpi.metric_field,
                        "calculation_reference": kpi.calculation_reference,
                        "business_domain": kpi.business_domain.value,
                        "lineage_verified": True,
                    }
                    all_unsupp = list(unsupported_dimensions)
                    for d in resolved_dimensions:
                        if kpi.supported_dimensions and d not in kpi.supported_dimensions and d not in all_unsupp:
                            all_unsupp.append(d)

                    return SemanticResolutionResult(
                        query=query,
                        resolved_kpi=kpi,
                        canonical_name=kpi.canonical_name,
                        analytics_tool=kpi.analytics_tool,
                        metric_field=kpi.metric_field,
                        is_ambiguous=False,
                        is_supported=True,
                        matched_synonym=syn,
                        confidence=1.0 if is_exact else 0.95,
                        resolved_dimensions=resolved_dimensions,
                        extracted_filters=extracted_filters,
                        temporal_context=temporal_ctx,
                        evidence_provenance=provenance,
                        matched_dimension_aliases=matched_dimension_aliases,
                        unsupported_dimensions=all_unsupp,
                    )

        # 6. Fallback: No deterministic KPI detected
        return SemanticResolutionResult(
            query=query,
            is_ambiguous=False,
            is_supported=True,
            confidence=0.0,
            resolved_dimensions=resolved_dimensions,
            extracted_filters=extracted_filters,
            temporal_context=temporal_ctx,
            evidence_provenance=None,
            matched_dimension_aliases=matched_dimension_aliases,
            unsupported_dimensions=unsupported_dimensions,
        )


# Global singleton ontology and resolver instances
kpi_ontology = KPIOntology()
semantic_resolver = SemanticResolver(kpi_ontology)

