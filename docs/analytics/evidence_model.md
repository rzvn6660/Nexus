# Audit Evidence Model & Analytical Traceability

Every quantitative response produced by the NEXUS Analytics Engine is paired with an `EvidenceRecord`. This structure guarantees end-to-end auditability and establishes the provenance necessary for Phase 4 autonomous agents to explain results to users.

---

## 1. EvidenceRecord Schema

```json
{
  "analysis_id": "c1f7b0f2-e22f-4c54-9467-33bf26bbbfcf",
  "metric": "financial_summary",
  "source_tables": ["sales", "sale_items", "products", "expenses"],
  "source_columns": ["subtotal", "discount_amount", "quantity", "unit_cost", "amount", "status"],
  "filters": {
    "date_from": "2023-06-01T00:00:00+00:00",
    "date_to": "2023-06-30T23:59:59+00:00",
    "statuses": ["completed", "shipped"],
    "granularity": "monthly"
  },
  "date_range": {
    "start": "2023-06-01T00:00:00+00:00",
    "end": "2023-06-30T23:59:59+00:00"
  },
  "comparison_period": {
    "start": "2023-05-01T00:00:00+00:00",
    "end": "2023-05-31T23:59:59+00:00"
  },
  "calculation": "Evaluates 12 core GAAP-aligned retail metrics...",
  "method": "deterministic_sql_aggregation",
  "assumptions": [
    "Sales tax is excluded from commercial revenue.",
    "COGS calculated using catalog product unit_cost."
  ],
  "data_quality_status": "verified",
  "limitations": [
    "Does not incorporate non-cash depreciation or income taxes."
  ],
  "result_summary": {
    "net_sales": 340.0,
    "gross_profit": 220.0,
    "net_profit": 100.0,
    "orders": 2
  },
  "generated_at": "2026-09-24T22:15:00Z"
}
```

---

## 2. Core Evidence Rules

1. **No Number Without Lineage**: Every computed metric must know its originating table and column sources.
2. **Formula Transparency**: Mathematical formulas and SQL aggregation methods are stated in human-readable terms.
3. **Boundary Traceability**: Active filter constraints and time windows are captured explicitly.
4. **Agent Consumability**: When the Phase 4 LangGraph agent generates explanations, it references `evidence.calculation` and `evidence.assumptions` to answer:
   - *"What was calculated?"*
   - *"What data was used?"*
   - *"What assumptions were made?"*
