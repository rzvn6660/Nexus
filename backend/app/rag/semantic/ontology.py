"""KPI Ontology and Deterministic Semantic Resolution for NEXUS.

Maps business terms, synonyms, and conversational language to Phase 3 deterministic
analytics tools, ensuring numbers are only ever computed by AnalyticsService.
"""

import re
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

    def _register_default_ontology(self) -> None:
        """Populate the retail & distribution KPI catalog backed by Phase 3."""

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
        ))

        # -------------------------------------------------------------
        # AMBIGUOUS TERMS CONFIGURATION
        # -------------------------------------------------------------
        self._ambiguous_terms = {
            "turnover": {
                "candidates": ["net_revenue", "inventory_turnover"],
                "prompt": "The term 'turnover' is ambiguous in retail. Do you mean Net Revenue (sales turnover) or Inventory Turnover (stock velocity)?",
            },
            "sales": {
                "candidates": ["net_revenue", "gross_sales"],
                "prompt": "The term 'sales' can refer to Gross Sales (before discounts) or Net Revenue (after discounts). Which metric would you like to analyze?",
            },
            "margin": {
                "candidates": ["gross_margin", "net_margin"],
                "prompt": "The term 'margin' can mean Gross Margin (product profitability) or Net Margin (after operating overhead). Which would you like to inspect?",
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
    to approved KPIs, detecting ambiguities, and rejecting unsupported metrics.
    """

    def __init__(self, ontology: KPIOntology | None = None) -> None:
        self.ontology = ontology or KPIOntology()

    def resolve(self, query: str) -> SemanticResolutionResult:
        """
        Deterministically resolve user query against the KPI ontology.
        
        Priority:
        1. Explicit unsupported metric rejection (prevents hallucinating unsupported formulas).
        2. Known ambiguous term detection (prevents guessing when meaning is material).
        3. Exact canonical or synonym match (longest matching phrase first).
        4. No resolution (returns clean empty resolution).
        """
        clean_query = query.lower().strip()
        # Strip trailing punctuation
        clean_query = re.sub(r"[?!.,;:]+$", "", clean_query)

        # 1. Check for explicit unsupported terms
        for term, message in self.ontology._unsupported_terms.items():
            # Check whole word / phrase match
            pattern = rf"\b{re.escape(term)}\b"
            if re.search(pattern, clean_query):
                return SemanticResolutionResult(
                    query=query,
                    is_supported=False,
                    unsupported_message=message,
                )

        # 2. Check for known ambiguous terms
        # But if query contains qualifying words (e.g. "inventory turnover" or "gross sales"),
        # specific phrases take precedence over ambiguous single words.
        for ambig_term, info in self.ontology._ambiguous_terms.items():
            # Check if ambiguous term appears
            pattern = rf"\b{re.escape(ambig_term)}\b"
            if re.search(pattern, clean_query):
                # Check if query has a more specific qualifier that resolves it directly!
                # For instance: "inventory turnover" or "stock turnover" -> inventory_turnover
                # "net sales" or "gross sales" -> specific KPI
                has_qualifier = False
                matched_candidate: KPI | None = None
                for cand_name in info["candidates"]:
                    cand_kpi = self.ontology.get_kpi(cand_name)
                    if not cand_kpi:
                        continue
                    # Check if any synonym of this candidate (other than the bare ambiguous term) is in query
                    for syn in [cand_kpi.canonical_name.replace("_", " "), cand_kpi.display_name] + cand_kpi.synonyms:
                        syn_clean = syn.lower()
                        if syn_clean != ambig_term and syn_clean in clean_query:
                            has_qualifier = True
                            matched_candidate = cand_kpi
                            break
                    if has_qualifier:
                        break

                if has_qualifier and matched_candidate:
                    return SemanticResolutionResult(
                        query=query,
                        resolved_kpi=matched_candidate,
                        canonical_name=matched_candidate.canonical_name,
                        analytics_tool=matched_candidate.analytics_tool,
                        metric_field=matched_candidate.metric_field,
                        is_ambiguous=False,
                        is_supported=True,
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
                )

        # 3. Match against canonical names and synonyms
        # Sort synonyms by length descending so longer phrases match before subphrases
        sorted_synonyms = sorted(
            self.ontology._synonym_map.keys(), key=lambda s: len(s), reverse=True
        )

        for syn in sorted_synonyms:
            pattern = rf"\b{re.escape(syn)}\b"
            if re.search(pattern, clean_query):
                canonical = self.ontology._synonym_map[syn]
                kpi = self.ontology.get_kpi(canonical)
                if kpi:
                    return SemanticResolutionResult(
                        query=query,
                        resolved_kpi=kpi,
                        canonical_name=kpi.canonical_name,
                        analytics_tool=kpi.analytics_tool,
                        metric_field=kpi.metric_field,
                        is_ambiguous=False,
                        is_supported=True,
                        matched_synonym=syn,
                    )

        # 4. Fallback: No deterministic KPI detected
        return SemanticResolutionResult(
            query=query,
            is_ambiguous=False,
            is_supported=True,
        )


# Global singleton ontology and resolver instances
kpi_ontology = KPIOntology()
semantic_resolver = SemanticResolver(kpi_ontology)
