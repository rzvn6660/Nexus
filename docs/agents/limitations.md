# Phase 4 Agent Boundaries & Limitations

## Current Capabilities (Phase 4)

In Phase 4, the NEXUS agent successfully implements:
- Intent classification across 10 structured business categories.
- Stateful LangGraph orchestration with multi-step loops and iteration ceilings.
- Deterministic execution of 16 analytical tools wrapping `AnalyticsService`.
- Provenance tracking with `EvidenceRecord` propagation.
- Grounded explanation synthesis with zero arithmetic hallucination.
- Parameterized date interpretation for relative business terms.
- Single analysis session endpoint `POST /api/v1/agent/analyze`.

---

## Known Boundaries & Limitations

### 1. No External Knowledge or Semantic Layer (Reserved for Phase 5)
- **Current state**: The agent relies exclusively on deterministic SQL and Phase 3 metric definitions. It does not possess company-specific document retrieval, policy manuals, or vector search.
- **Future plan**: Phase 5 will introduce the Semantic Layer, KPI ontology, vector embeddings, and RAG retrieval over domain documents.

### 2. No Autonomous Proactive Anomaly Investigation (Reserved for Phase 6)
- **Current state**: The agent is purely request-driven. It analyzes variances when asked, but does not autonomously scan the database in the background to detect unprompted business anomalies.
- **Future plan**: Phase 6 will implement the autonomous investigation engine, hypothesis generation, and evidence chain builder.

### 3. No Predictive ML or Forecasting (Reserved for Phase 7)
- **Current state**: All analysis is descriptive (what happened) and diagnostic (what contributed). Time series methods evaluate historical periods; no forward-looking ARIMA, Prophet, or churn prediction models are present.
- **Future plan**: Phase 7 will integrate predictive time series forecasting and customer churn risk classification.

### 4. No Dedicated UI Dashboard (Reserved for Phase 8)
- **Current state**: The agent interface is exposed via versioned REST API (`POST /api/v1/agent/analyze`). No new frontend dashboard or chat components were introduced in Phase 4.
- **Future plan**: Phase 8 will deliver the analyst workbench and executive visualization dashboard.

### 5. Single-Turn Request Scope
- **Current state**: The agent maintains state throughout a single analysis workflow (from understanding through multi-step tool calls to explanation). It does not retain cross-session long-term conversational memory or user personal reminders.

---

## Recommended Scope for Phase 5 (RAG + Semantic Layer)

When entering Phase 5:
1. **Semantic Metric Layer**: Map high-level business concepts and synonyms to deterministic metrics.
2. **Document Ingestion & Chunking**: Index internal business documentation, policies, and product catalogs.
3. **Vector Database**: Integrate pgvector with embeddings for semantic retrieval.
4. **Context Injection**: Enrich agent reasoning plans with business policy context and semantic definitions.
