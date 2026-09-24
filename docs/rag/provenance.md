# NEXUS Dual Provenance Architecture

## 1. Provenance Invariant

In NEXUS, analytical integrity requires verifiable proof for both mathematical outcomes and contextual explanations:

```
                              ┌──────────────────────────────────────────────┐
                              │                 USER QUERY                   │
                              └──────────────────────┬───────────────────────┘
                                                     │
                                                     ▼
                               ┌──────────────────────────────────────────────┐
                               │                AgentResponse                 │
                               └──────┬───────────────────────────────┬───────┘
                                      │                               │
                                      ▼                               ▼
                 ┌──────────────────────────────────────┐   ┌──────────────────────────────────────┐
                 │       Analytics EvidenceRecord       │   │             RAGEvidence              │
                 ├──────────────────────────────────────┤   ├──────────────────────────────────────┤
                 │ • Metric: financial_summary          │   │ • Document ID: doc_retail_kpis      │
                 │ • Source Tables: [sales, items, ...] │   │ • Document: Retail KPI Definitions   │
                 │ • Aggregations: SUM, COUNT           │   │ • Section: Gross Margin Definition   │
                 │ • Formula: (gross_profit / rev) * 100│   │ • Similarity: 0.9412                 │
                 │ • Assumptions & Limitations          │   │ • Excerpt: Context passage           │
                 └──────────────────────────────────────┘   └──────────────────────────────────────┘
                                      ▲                               ▲
                                      │                               │
                       "Proves HOW numbers were computed"       "Proves WHERE definitions came from"
```

## 2. EvidenceRecord (Phase 3)

The Phase 3 `EvidenceRecord` remains unchanged:
- Bound to deterministic tool execution.
- Captures SQL source tables and columns.
- Records exact calculation formulas.
- Outlines business modeling assumptions and statistical limitations.

## 3. RAGEvidence (Phase 5)

The Phase 5 `RAGEvidence` provides governance and traceability for business definitions:
- Document ID, source filename, and title.
- Chunk ID and section heading.
- Cosine similarity score.
- Retrieval method and timestamp.
- Verified excerpt text.
