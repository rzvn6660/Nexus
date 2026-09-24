# NEXUS Business Data Validation Rules

## 1. Scope & Purpose
This document defines the strict, non-negotiable data validation rules enforced across the NEXUS Data Layer. 

Every record entering the platform must pass these checks prior to persistent analytical storage.

---

## 2. Invariant Validation Matrix

### 2.1 Customer Rules
1. **`customer_code` Format**: Must match standard alphanumeric identifier (3 to 32 characters), non-null, unique across the enterprise.
2. **`email` Format**: Must be RFC-5322 compliant, unique, non-null.
3. **`acquisition_date` Sanity**: Must be a valid date $\le \text{Current Date}$. Cannot be in the future.

### 2.2 Product Rules
1. **`sku` Uniqueness**: Catalog SKU must be unique across all active and inactive products.
2. **`unit_cost` Non-Negativity**: $\text{unit\_cost} \ge 0.00$. Zero cost permitted for promotional free items or digital collateral.
3. **`selling_price` Non-Negativity**: $\text{selling\_price} \ge 0.00$.

### 2.3 Sales & Transaction Rules
1. **`transaction_number` Uniqueness**: Globally unique invoice receipt string.
2. **Temporal Precedence**: Order $\text{transaction\_date} \ge \text{customer.acquisition\_date}$. A customer cannot execute a transaction prior to their documented acquisition date.
3. **Line Total Arithmetic**: For every line item $j$:
   $$\text{line\_total}_j = (\text{quantity}_j \times \text{unit\_price}_j) - \text{discount\_amount}_j$$
   Enforced with an absolute tolerance of $\$0.02$ to accommodate currency fractional cents rounding.
4. **Order Total Arithmetic**: For every sale transaction:
   $$\text{total\_amount} = \text{subtotal} - \text{discount\_amount} + \text{tax\_amount}$$
5. **Positive Quantity**: Ordered units must strictly satisfy $\text{quantity} > 0$. Return transactions with negative units must be registered as formal refunds, not negative sales.

### 2.4 Inventory Rules
1. **Non-Negative Physical Stock**: $\text{stock\_quantity} \ge 0$. Stock levels cannot fall below zero.
2. **One-to-One Product Mapping**: Each product SKU has exactly one primary warehouse inventory control record.

### 2.5 Expense Rules
1. **Non-Negative Amount**: Incurred expense amounts must satisfy $\text{amount} \ge 0.00$.
2. **Categorical Conformance**: Category must match approved chart of accounts taxonomy (`Rent`, `Payroll`, `Utilities`, `Logistics`, `Marketing`, `Warehouse Supplies`).
