# Stopping Rules & Adaptive Branching

## Bounded Execution
Investigations are guaranteed to terminate through explicit stopping invariants:

1. **Iteration Boundary (`ITERATION_LIMIT_REACHED`)**:
   - Every plan enforces `max_steps` (default 8, configurable via `MAX_INVESTIGATION_STEPS`).
   - The engine halts once `len(executed_steps) >= max_steps`.

2. **Evidence Completeness (`SUFFICIENT_EVIDENCE`)**:
   - The step queue empties after executing all scheduled diagnostic and adaptive steps.
   - Primary hypotheses have been definitively evaluated.

3. **Missing Data Barrier (`MISSING_REQUIRED_DATA`)**:
   - Required baseline data or records are unavailable.
   - Recorded as an `EvidenceGap` without fabricating data.

4. **Ambiguity Barrier (`CLARIFICATION_NEEDED`)**:
   - User inquiry references ambiguous business terminology or intervals.
   - Halts immediately and requests user disambiguation.

---

## Adaptive Branching Mechanics
- When `run_variance_analysis(dimension="category")` identifies a dominant category with variance contribution $\ge 35\%$, the engine dynamically injects a follow-up step: `run_variance_analysis(dimension="product")`.
- When `run_price_volume_mix` determines that volume effect explains $\ge 60\%$ of total variance, the engine dynamically appends a customer segment audit: `get_customer_segments`.
- Branching is bounded by `max_steps` to prevent recursion loops.
