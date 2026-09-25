# Causality Safeguards & Linguistic Guardrails

## Core Invariant
**Correlation and mathematical contribution do not constitute proof of independent causality.**

Traditional BI dashboards often mislead users by equating arithmetic shares with root causes. NEXUS explicitly distinguishes:
1. **Mathematical Contribution**: "Category A accounted for 62.4% of the measured variance."
2. **Statistical Correlation**: "Discount depth exhibited a moderate positive association with order volume (r = 0.42, p < 0.01)."
3. **Temporal Coincidence**: "Inventory reorder alerts occurred during the same calendar month as lower sales."
4. **Causality**: "Stockouts unilaterally caused customer order cancellations." (Requires controlled experimental or counterfactual proof).

---

## Linguistic Safeguards
The Investigation Engine includes `CausalitySafeguard` which inspects all conclusions and generated narratives:
- Banned expressions: `"caused"`, `"is the root cause of"`, `"directly caused"`, `"proves that X caused"`.
- Approved alternatives: `"contributed to the measured variance"`, `"was a primary measured factor in"`, `"accounted for X% of the change"`.
- Compulsory caveat: Every conclusion carries `causal_caveat`:
  > *"Contribution and association measure derived from deterministic decomposition; does not establish an isolated independent causal mechanism."*

---

## Prescriptive Boundaries
Phase 6 is strictly **Diagnostic**. The engine may recommend deeper analytical investigations (e.g., "Drill down into product-level SKU velocity"), but is strictly barred from issuing prescriptive operational advice:
- Disallowed: *"Raise prices on Category B"*, *"Reduce inventory"*, *"Fire supplier X"*, *"Discontinue slow SKUs"*.
- Allowed: *"Review product velocity and unit margins within Category B."*
