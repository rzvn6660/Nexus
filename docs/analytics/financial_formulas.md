# Financial Formulas and Period Comparisons

This specification describes the mathematical methodology and edge case rules governing financial calculations in the NEXUS Analytics Engine.

---

## 1. Core Financial Identity

```
Gross Sales = sum(sale_items.quantity × sale_items.unit_price) OR sum(sales.subtotal)
Discounts   = sum(sales.discount_amount)
Net Sales   = Gross Sales - Discounts  (Revenue)
COGS        = sum(sale_items.quantity × products.unit_cost)

Gross Profit = Net Sales - COGS
Gross Margin = (Gross Profit / Net Sales) × 100%

Operating Expenses (OPEX) = sum(expenses.amount)

Net Profit = Gross Profit - OPEX
Net Margin = (Net Profit / Net Sales) × 100%
```

---

## 2. Period-Over-Period Comparison

When comparing a primary interval (e.g. current month) with a baseline interval (e.g. prior month):

$$\text{Absolute Change} = \text{Value}_{\text{current}} - \text{Value}_{\text{previous}}$$

$$\text{Percentage Change} = \left( \frac{\text{Value}_{\text{current}} - \text{Value}_{\text{previous}}}{|\text{Value}_{\text{previous}}|} \right) \times 100\%$$

### Edge Cases and Safe Denominator Handling
- **Zero in Previous Period, Positive in Current**: Direction is `INCREASE`, percentage change is mathematically `None` (`undefined`), and a descriptive explanation is recorded: *"Baseline value was 0; percentage growth is mathematically undefined."*
- **Zero in Both Periods**: Direction is `UNCHANGED`, percentage change is `0.0%`.
- **Missing Baseline Interval**: Direction is `UNDEFINED`, percentage change is `None`.

All calculations are evaluated with `decimal.Decimal` using `ROUND_HALF_UP` to two decimal places for currency and four decimal places for percentages.
