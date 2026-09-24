# NEXUS Semantic Layer Concept (Planned — Phase 3)

## 1. The Core Problem
When non-technical users ask:
> *"What was our total revenue last month?"*

A generic LLM might query `SELECT SUM(total) FROM orders WHERE date ...`.
However, in a real retail business:
- Do "orders" include pending orders?
- Are cancelled orders filtered out?
- Are refunds and return credits deducted?
- Is shipping revenue included or segregated from merchandise revenue?
- Are taxes (VAT/Sales Tax) excluded from top-line revenue?

Leaving metric interpretations to the probabilistic discretion of an LLM creates catastrophic financial discrepancies.

---

## 2. Explicit Metrics as Code
In NEXUS, all business definitions are **explicitly defined as code** rather than guessed by an agent.

```yaml
# Conceptual Semantic KPI Definition
metrics:
  - name: net_revenue
    display_name: "Net Revenue"
    description: "Total recognized merchandise revenue net of customer discounts, promotional vouchers, and customer refunds."
    formula: "gross_sales - discounts - refunds"
    sql_expression: "SUM(sales.gross_amount) - SUM(COALESCE(sales.discount_amount, 0)) - SUM(COALESCE(refunds.amount, 0))"
    required_dimensions:
      - date
    optional_dimensions:
      - product_category
      - store_branch
      - customer_segment
    owner: "Finance & Accounting"

  - name: active_customer
    display_name: "Active Customer"
    description: "Unique customer who completed at least one verified non-refunded purchase within trailing 90 days."
    sql_filter: "orders.status = 'COMPLETED' AND orders.order_date >= CURRENT_DATE - INTERVAL '90 days'"
    owner: "Growth & Retention"
```

---

## 3. Integration with the Agent Workflow
1. The **Understand Node** extracts desired business entities and looks up matching metrics in the Semantic Registry.
2. The agent cannot invent SQL aggregations for registered KPIs; it is forced to compile the pre-approved `sql_expression` into the generated database query.
3. Every analytical response explicitly cites the metric definition used:
   - *"Calculated using corporate metric 'Net Revenue' (v1.2, Finance-approved), excluding VAT and including returns."*
