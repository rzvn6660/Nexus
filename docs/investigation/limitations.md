# Limitations & Phase 7 Boundaries

## Current Capabilities (Phase 6)
- Multi-step, adaptive diagnostic variance decomposition.
- Price/Volume/Mix economic driver quantification.
- Categorical, product, customer segment, inventory, and expense contribution analysis.
- Transparent hypothesis testing and causality-safeguarded narratives.

---

## Technical & Analytical Limitations
1. **Historical Inventory Snapshots**:
   The current operational schema tracks real-time inventory balances; historical daily inventory logs are unobserved. The engine documents this as an explicit `EvidenceGap` rather than speculating on past stockouts.
2. **Exogenous Market Telemetry**:
   Macroeconomic variables, competitor pricing, and weather events are not present in the internal transaction ledger.
3. **Qualitative Telemetry**:
   Customer service tickets, churn surveys, and sentiment scores are outside the current database boundaries.

---

## Phase 7 Boundary
**Predictive intelligence, ML forecasting (e.g. ARIMA, Prophet), churn prediction models, and automated recommendations are strictly locked out of Phase 6.**
No predictive or prescriptive capabilities have been added.
