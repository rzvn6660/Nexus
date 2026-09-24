# Centralized Metric Definitions (Metric Dictionary)

This document catalogues the business definitions, mathematical formulas, source schema columns, aggregation methods, and constraints for all metrics supported by the NEXUS Analytics Engine.

---

### 1. Financial Metrics

| Metric Key | Display Name | Unit | Formula | Source Tables & Columns | Default Filters | Limitations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `gross_sales` | Gross Sales | Currency | `sum(sales.subtotal)` | `sales.subtotal` | `status IN ('completed', 'shipped')` | Does not deduct order promotional discounts. |
| `discounts` | Total Discounts | Currency | `sum(sales.discount_amount)` | `sales.discount_amount` | `status IN ('completed', 'shipped')` | Reflects order-level promotional discounts. |
| `net_sales` | Net Sales (Revenue) | Currency | `sum(sales.subtotal - sales.discount_amount)` | `sales.subtotal`, `sales.discount_amount` | `status IN ('completed', 'shipped')` | Excludes sales tax / VAT (tax is a liability, not revenue). |
| `units_sold` | Units Sold | Units | `sum(sale_items.quantity)` | `sale_items.quantity` | `sales.status IN ('completed', 'shipped')` | Counts physical units fulfilled. |
| `orders` | Total Orders | Count | `count(distinct sales.id)` | `sales.id` | `status IN ('completed', 'shipped')` | Counts distinct transactions. |
| `average_order_value` | Average Order Value (AOV) | Currency | `Net Sales / Total Orders` | `sales.subtotal`, `sales.discount_amount`, `sales.id` | `status IN ('completed', 'shipped')` | Undefined if orders is zero. |
| `cogs` | Cost of Goods Sold | Currency | `sum(sale_items.quantity * products.unit_cost)` | `sale_items.quantity`, `products.unit_cost` | `sales.status IN ('completed', 'shipped')` | Uses catalog unit cost; batch tracking not in Phase 2 schema. |
| `gross_profit` | Gross Profit | Currency | `Net Sales - COGS` | Derived | `status IN ('completed', 'shipped')` | Excludes merchant payment fees and shipping costs. |
| `gross_margin` | Gross Margin Percentage | Percentage | `(Gross Profit / Net Sales) * 100` | Derived | `status IN ('completed', 'shipped')` | Undefined if Net Sales is zero. |
| `operating_expenses` | Operating Expenses (OPEX) | Currency | `sum(expenses.amount)` | `expenses.amount`, `expenses.expense_date` | None | Does not include depreciation or non-cash items. |
| `net_profit` | Net Operating Profit | Currency | `Gross Profit - Operating Expenses` | Derived | Combined | Income taxes and debt interest are not represented. |
| `net_margin` | Net Margin Percentage | Percentage | `(Net Profit / Net Sales) * 100` | Derived | Combined | Undefined if Net Sales is zero; can be negative. |

---

### 2. Operational & Behavioral Metrics

| Metric Key | Display Name | Unit | Formula | Source Tables & Columns | Default Filters | Limitations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `inventory_turnover` | Inventory Turnover Ratio | Ratio | `COGS / Inventory Valuation` | `sale_items.quantity`, `products.unit_cost`, `inventory.stock_quantity` | Products active | Uses snapshot inventory as proxy for period average. |
| `days_sales_of_inventory` | Days Sales of Inventory (DSI) | Days | `(Inventory Valuation / COGS) * Days` | Derived | Active products | Requires positive COGS and inventory valuation. |
| `sales_velocity` | Sales Velocity | Units/Day | `Units Sold / Days in Period` | `sale_items.quantity`, `sales.transaction_date` | `status IN ('completed', 'shipped')` | Evaluated across bounded time interval. |
| `repeat_purchase_rate` | Repeat Purchase Rate | Percentage | `(Customers with >= 2 orders / Total Ordering Customers) * 100` | `sales.customer_id`, `sales.id` | `status IN ('completed', 'shipped')` | Evaluated across bounded time interval. |
| `recency_days` | Customer Recency | Days | `Reference Date - Max(Transaction Date)` | `sales.transaction_date` | `status IN ('completed', 'shipped')` | Evaluated per customer in RFM analysis. |
