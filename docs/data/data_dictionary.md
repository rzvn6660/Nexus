# NEXUS Business Data Dictionary

This data dictionary establishes the canonical semantic meaning, domain business rules, and analytical considerations for every core field in NEXUS. This document forms the direct bridge to Phase 5's Semantic Layer.

---

## 1. Customers Domain

### `customer_code`
- **Definition**: The durable external enterprise account code assigned upon customer registration.
- **Business Purpose**: Used for ERP, CRM, and cross-channel tracking. Unlike surrogate database IDs, this identifier is immutable and externally visible.
- **Analytical Use**: Primary grouping dimension for Customer Lifetime Value (LTV), cohort retention curves, and repeat purchase analysis.

### `customer_segment`
- **Definition**: Market categorization governing credit terms, ordering expectations, and volume pricing.
- **Values**:
  - `Retail`: General individual consumer making low-frequency, single-unit orders.
  - `Wholesale`: Business distributor purchasing in bulk cartons with pre-negotiated tier discounts.
  - `Corporate`: B2B operational clients requiring predictable procurement and monthly invoicing.
  - `VIP`: High-margin, frequent individual purchasers who receive priority customer service.
- **Analytical Use**: Critical dimension for customer segmentation, churn propensity, and margin contribution analysis.

### `acquisition_date`
- **Definition**: The calendar date on which the customer completed their first valid interaction or registration.
- **Analytical Use**: Serves as the anchor date ($t_0$) for monthly customer acquisition cohorts and retention matrices.

---

## 2. Products Domain

### `sku`
- **Definition**: Stock Keeping Unit code formatting category and numerical sequence (e.g. `SKU-ELE-0042`).
- **Analytical Use**: Atomic unit for sales velocity, ABC inventory analysis, and product mix shift decomposition.

### `unit_cost`
- **Definition**: Landed Cost of Goods Sold (COGS) to acquire, manufacture, or import a single unit of the product.
- **Currency**: Exact fixed-point numeric ($USD).
- **Analytical Use**: Base cost subtrahend in gross margin calculations:  
  $$\text{Gross Profit} = \text{Net Revenue} - (\text{Quantity} \times \text{unit\_cost})$$

### `selling_price`
- **Definition**: Standard baseline catalog price per unit before any order-level or customer-specific volume discounts.
- **Analytical Use**: Serves as the benchmark price when measuring realized price decay and discount dilution.

### `active`
- **Definition**: Boolean flag denoting whether the SKU is currently available for active retail sales. Inactive products cannot appear on new purchase orders.

---

## 3. Sales & Sale Items Domain

### `transaction_number`
- **Definition**: Formal invoice or receipt identifier formatted as `TXN-{YYYYMM}-{sequence}`.
- **Analytical Use**: Count of distinct transaction numbers represents total completed order volume.

### `status`
- **Definition**: Lifecycle state of the transaction.
- **Values**:
  - `completed`: Goods transferred and payment settled. (Included in top-line revenue).
  - `pending`: Order placed, pending fulfillment or payment settlement. (Excluded from realized revenue).
  - `cancelled`: Order aborted prior to fulfillment. (Excluded from all revenue metrics).
  - `refunded`: Order returned post-fulfillment. (Deducted from net sales).
- **Semantic Rule**: Revenue metrics must explicitly declare which transaction statuses are included.

### `subtotal`
- **Definition**: Gross aggregate sum of all line item totals prior to order-level coupons or taxes.

### `discount_amount` (Sale & SaleItem)
- **Definition**: Total price concession granted to the buyer.
- **At Item Level**: Volume-based or product-specific discount.
- **At Sale Level**: Order-wide promotional coupon or loyalty voucher.
- **Analytical Use**: Quantifies margin erosion and promotional efficacy.

### `tax_amount`
- **Definition**: Sales tax or Value Added Tax (VAT) collected on behalf of government authorities.
- **Semantic Rule**: Tax collections are balance sheet liabilities and are strictly excluded from recognized revenue.

### `total_amount`
- **Definition**: Final billed settlement invoice value:
  $$\text{total\_amount} = \text{subtotal} - \text{discount\_amount} + \text{tax\_amount}$$

### `quantity`
- **Definition**: Number of discrete units sold in a line item. Must be strictly positive ($> 0$).

### `line_total`
- **Definition**: Net financial value of the individual line item:
  $$\text{line\_total} = (\text{quantity} \times \text{unit\_price}) - \text{discount\_amount}$$

---

## 4. Inventory Domain

### `stock_quantity`
- **Definition**: Physical inventory units on hand in the warehouse ready for picking and fulfillment.
- **Analytical Use**: Stockout risk modeling, inventory valuation ($stock \times unit\_cost$), and days of inventory on hand (DOH).

### `reorder_threshold`
- **Definition**: Policy safety stock parameter representing the minimum unit threshold at which replenishment purchase orders must be dispatched to suppliers.

---

## 5. Expenses Domain

### `category`
- **Definition**: General ledger operating expense classification.
- **Standard Classes**: `Rent`, `Payroll`, `Utilities`, `Logistics`, `Marketing`, `Warehouse Supplies`.
- **Analytical Use**: Subtracted from gross profit to compute Earnings Before Interest & Taxes (Operating Profit / EBITDA):
  $$\text{Operating Profit} = \text{Gross Profit} - \sum \text{Operating Expenses}$$

### `recurring`
- **Definition**: Boolean flag designating non-discretionary contractual overhead (e.g. lease agreements, permanent payroll).
