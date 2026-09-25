# Evidence Model & Provenance

## Evidence Strength Hierarchy

| Level | Definition | Example |
| :--- | :--- | :--- |
| **DIRECT** | Deterministic decomposition directly attributes a measurable share of variance. | Category A accounts for 62.4% of revenue variance. |
| **STRONG** | Multiple independent analytics models point in the same direction. | High COGS ratio confirmed alongside low gross margin in PVM. |
| **MODERATE** | A measurable association exists without proving causal direction. | Reorder alerts coincide with low product velocity. |
| **WEAK** | Plausible relationship with limited transactional proof. | General market trend mentioned in policy text without local sales data. |
| **INSUFFICIENT**| Required transactional telemetry is missing or unmeasured. | Daily stockout log not recorded in historical schema. |

---

## Dual Provenance
Every investigation response pairs:
1. **Analytics Evidence (`EvidenceRecord`)**: Formula, table inputs, parameters, and execution telemetry proving numerical calculations.
2. **RAG Evidence (`RAGEvidence`)**: Document name, chunk ID, source, and similarity score proving where business definitions originated.
