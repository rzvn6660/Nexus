# NEXUS Semantic Layer & KPI Ontology

## 1. Overview

The Semantic Layer acts as the dictionary and translation bridge between conversational natural language and deterministic Phase 3 calculations. It ensures that when a user asks about "sales", "margin", or "turnover", the system deterministically resolves the intended meaning rather than letting an LLM guess or fabricate arithmetic.

## 2. KPI Ontology Registry

The `KPIOntology` maintains canonical definitions, units, synonyms, and deterministic tool bindings across seven core business domains:

| Domain | Canonical KPI | Display Name | Unit | Analytics Tool | Calculation Reference |
|---|---|---|---|---|---|
| **Finance** | `gross_sales` | Gross Sales | Currency | `get_financial_summary` | `SUM(unit_price * quantity)` |
| **Finance** | `discounts` | Discounts | Currency | `get_financial_summary` | `SUM(discount_amount)` |
| **Finance** | `net_revenue` | Net Revenue | Currency | `get_financial_summary` | `gross_sales - discounts` |
| **Finance** | `units_sold` | Units Sold | Units | `get_financial_summary` | `SUM(quantity)` |
| **Finance** | `orders` | Orders | Count | `get_financial_summary` | `COUNT(DISTINCT order_id)` |
| **Finance** | `average_order_value`| Average Order Value | Currency | `get_financial_summary` | `net_revenue / orders` |
| **Finance** | `cogs` | Cost of Goods Sold | Currency | `get_financial_summary` | `SUM(cost_price * quantity)` |
| **Finance** | `gross_profit` | Gross Profit | Currency | `get_financial_summary` | `net_revenue - cogs` |
| **Finance** | `gross_margin` | Gross Margin | Percentage| `get_financial_summary` | `(gross_profit / net_revenue) * 100` |
| **Finance** | `net_profit` | Net Profit | Currency | `get_financial_summary` | `gross_profit - opex` |
| **Finance** | `net_margin` | Net Margin | Percentage| `get_financial_summary` | `(net_profit / net_revenue) * 100` |
| **Customer** | `active_customer` | Active Customers | Count | `get_customer_segments` | `COUNT(DISTINCT customer_id)` in period |
| **Customer** | `repeat_customer` | Repeat Customers | Count | `get_repeat_purchase` | Lifetime completed orders >= 2 |
| **Customer** | `repeat_purchase_rate`| Repeat Purchase Rate | Percentage| `get_repeat_purchase` | `(repeat_customers / total_customers) * 100` |
| **Customer** | `recency` | Recency | Days | `get_rfm_analysis` | `snapshot_date - MAX(order_date)` |
| **Customer** | `frequency` | Frequency | Count | `get_rfm_analysis` | Orders per customer |
| **Customer** | `monetary_value` | Monetary Value | Currency | `get_rfm_analysis` | Cumulative spend |
| **Customer** | `customer_segment`| Customer Segment | Count | `get_customer_segments` | RFM quintiles or tiers |
| **Product** | `product_revenue` | Product Revenue | Currency | `get_product_rankings` | Net revenue grouped by product |
| **Product** | `product_profit` | Product Profit | Currency | `get_product_rankings` | Gross profit grouped by product |
| **Product** | `product_margin` | Product Margin | Percentage| `get_product_rankings` | `(product_profit / product_revenue) * 100` |
| **Product** | `category_revenue`| Category Revenue | Currency | `get_category_breakdown` | Net revenue grouped by category |
| **Product** | `category_profit` | Category Profit | Currency | `get_category_breakdown` | Gross profit grouped by category |
| **Inventory**| `stock_value` | Stock Value | Currency | `get_inventory_overview` | `SUM(current_stock * cost_price)` |
| **Inventory**| `inventory_turnover`| Inventory Turnover | Ratio | `get_inventory_turnover` | `annualized_cogs / average_inventory_value` |
| **Inventory**| `days_sales_inventory`| Days Sales Inventory | Days | `get_inventory_turnover` | `(average_inventory_value / annualized_cogs) * 365` |
| **Inventory**| `sales_velocity` | Sales Velocity | Units | `get_inventory_velocity` | Daily run rate of units sold |
| **Inventory**| `reorder_alert` | Reorder Alerts | Count | `get_inventory_overview` | `current_stock <= reorder_level` |
| **Expenses** | `operating_expense`| Operating Expenses | Currency | `get_expense_analytics` | `SUM(amount)` from expenses |
| **Expenses** | `fixed_expense` | Fixed Expenses | Currency | `get_expense_analytics` | Recurring expenses |
| **Expenses** | `variable_expense`| Variable Expenses | Currency | `get_expense_analytics` | Non-recurring expenses |
| **Diagnostic**| `revenue_variance`| Revenue Variance | Currency | `run_variance_analysis` | `current_revenue - prior_revenue` |
| **Diagnostic**| `price_effect` | Price Effect | Currency | `run_price_volume_mix` | `(P1 - P0) * Q1` |
| **Diagnostic**| `volume_effect`| Volume Effect | Currency | `run_price_volume_mix` | `(Q1 - Q0) * P0` |
| **Diagnostic**| `mix_effect` | Mix Effect | Currency | `run_price_volume_mix` | Portfolio margin shift |
| **Statistics**| `correlation` | Correlation Coefficient | Ratio | `run_correlation` | Pearson r or Spearman rho |
| **Statistics**| `p_value` | P-Value | Ratio | `run_hypothesis_test` | Significance level |
| **Statistics**| `hypothesis_test`| Hypothesis Test | Ratio | `run_hypothesis_test` | Welch's two-sample t-test |

## 3. Ambiguity Resolution

The semantic layer explicitly detects ambiguous terminology when context does not qualify it:
- **"turnover"**: Ambiguous between Net Revenue (sales turnover) and Inventory Turnover (stock turns).
- **"sales"**: Ambiguous between Gross Sales (pre-discount) and Net Revenue (realized).
- **"margin"**: Ambiguous between Gross Margin and Net Margin.

When ambiguity is detected, the resolver sets `is_ambiguous=True` and returns a structured clarification prompt rather than guessing.

## 4. Unsupported Term Rejection

The ontology explicitly defines unsupported metrics (e.g., Customer Lifetime Value, Churn Rate, Customer Acquisition Cost) to prevent the LLM from hallucinating speculative calculations outside Phase 5.
