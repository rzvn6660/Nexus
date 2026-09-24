# Diagnostic Analytics & Price/Volume/Mix Decomposition

Diagnostic analytics identify what dimensional entities or economic mechanisms contributed to an observed variance between two periods.

---

## 1. Variance Analysis Dissection

When comparing Metric $M$ between Period 0 (baseline) and Period 1 (current):

$$\Delta M = M_1 - M_0$$

For each dimensional entity $e$ (e.g. SKU, Category, Customer Segment):

$$\Delta M_e = M_{e,1} - M_{e,0}$$

$$\text{Contribution to Change (\%)} = \left( \frac{\Delta M_e}{|\Delta M|} \right) \times 100\%$$

### Non-Causal Framing Rule
The engine explicitly reports entities as **contributors to the observed variance**, never asserting that an entity *caused* the change. Causality requires controlled experiment designs or external econometric proof.

---

## 2. Price / Volume / Mix (PVM) Decomposition

Price / Volume / Mix analysis decomposes total revenue variance into three additive drivers:

$$\Delta \text{Revenue} = \text{Volume Effect} + \text{Price Effect} + \text{Mix Effect}$$

### Mathematical Definitions:
Let:
- $Q_0, Q_1$: Total units sold across all products in Period 0 and Period 1.
- $q_{i,0}, q_{i,1}$: Units sold of product $i$.
- $p_{i,0}, p_{i,1}$: Realized average selling price of product $i$ ($\text{Revenue}_i / q_i$).
- $P_0$: Average portfolio selling price in Period 0 ($R_0 / Q_0$).

1. **Volume Effect**:
   The revenue impact if total unit volume changed, holding the product mix and pricing constant at baseline portfolio average:
   $$\text{Volume Effect} = (Q_1 - Q_0) \times P_0$$

2. **Price Effect**:
   The revenue impact directly attributable to shifts in per-unit realized selling price for each product:
   $$\text{Price Effect} = \sum_i q_{i,1} \times (p_{i,1} - p_{i,0})$$

3. **Mix Effect**:
   The residual revenue impact driven by changes in the proportion of high-value versus low-value merchandise:
   $$\text{Mix Effect} = \Delta \text{Revenue} - (\text{Volume Effect} + \text{Price Effect})$$

### Reconciliation Guarantee
Because Mix Effect is computed as the exact algebraic residual of the portfolio pricing identity, the three effects are mathematically guaranteed to reconcile 100% to the penny with the observed revenue variance.
