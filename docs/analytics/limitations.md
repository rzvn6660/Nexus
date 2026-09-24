# Phase 3 Analytical Boundaries & Known Limitations

To maintain deterministic reliability and avoid pulling future roadmap phases ahead of schedule, Phase 3 explicitly enforces architectural boundaries.

---

## 1. Roadmap Enforcements (What Was Excluded)

1. **Zero Large Language Models**: No OpenAI, Anthropic, Gemini, or local LLMs are invoked during calculations.
2. **Zero Agent Orchestration**: LangChain, LangGraph, and autonomous multi-agent reasoning are reserved for Phase 4.
3. **Zero Semantic Embeddings / RAG**: Vector databases (Chroma, PGVector) and semantic retrieval are deferred to Phase 5.
4. **Zero Predictive ML**: Machine learning models for future demand forecasting, churn prediction, or prescriptive optimization belong to Phase 7.
5. **Zero Product UI Redesigns**: Product-level visual dashboard overhauls belong to Phase 8.

---

## 2. Analytical Limitations in Phase 2 Data Schema

1. **Inventory Valuation as Snapshot**:
   - The Phase 2 schema stores point-in-time `Inventory.stock_quantity`.
   - Inventory turnover uses current stock levels as a proxy for periodic average inventory.
2. **Static Catalog Unit Cost**:
   - `Product.unit_cost` reflects the catalog standard cost.
   - Batch-specific FIFO/LIFO or moving-average landed procurement costs are not tracked in the initial retail schema.
3. **Linearity in Correlation**:
   - Pearson correlation captures strictly linear associations. Non-linear relationships are flagged in `CorrelationResult.limitations`.
4. **Association vs. Causation**:
   - Statistical significance ($p < 0.05$) in hypothesis tests confirms that sample differences are unlikely due to chance, but does not prove causal attribution.
