# Phase 6 — Investigation Engine / Diagnostic Intelligence Architecture

## Overview
The NEXUS Investigation Engine extends the agentic intelligence stack from **Descriptive Analytics** ("What happened?") into **Diagnostic Intelligence** ("Why did it happen?").

NEXUS rigorously segregates analytical reasoning horizons:
1. **Descriptive** (Phase 3 & 4): "What were our sales in August?" — exact factual quantification.
2. **Contextual** (Phase 5): "What does net revenue mean?" — verified business definitions and policy rules.
3. **Diagnostic** (Phase 6): "Why did net revenue decline in August?" — evidence-backed variance decomposition, hypothesis testing, and contribution analysis.
4. **Predictive** (Phase 7 - Future): "What is revenue expected to be next quarter?" — strictly locked out of Phase 6.
5. **Prescriptive** (Phase 8 - Future): "What operational actions should management take?" — strictly locked out of Phase 6.

---

## Architectural Topology

```
                         USER REQUEST
                              ↓
                      FastAPI Endpoints
             (/api/v1/investigation/analyze, /agent)
                              ↓
                       LangGraph Agent
                              ↓
                 ┌────────────┴────────────┐
                 ↓                         ↓
           Semantic Layer            Business RAG
         (KPI Ontology & Terms)    (Hybrid Retrieval)
                 ↓                         ↓
                 └────────────┬────────────┘
                              ↓
                    Investigation Planner
                 (Archetype & Baseline Dates)
                              ↓
                     Investigation Plan
               (Bounded, Schema-Validated Steps)
                              ↓
                   Tool Execution Loop
              (AnalyticsService via ToolRegistry)
                              ↓
                  Empirical Observations
                              ↓
                     Hypothesis Engine
               (Testing & Status Assignment)
                              ↓
                  Adaptive Branching Check
             (Dynamic Drill-Down if Warranted)
                              ↓
                    Evidence Synthesizer
                (Causality Safeguards & Audit)
                              ↓
                     Diagnostic Narrative
                              ↓
                            USER
```

---

## Separation of Concerns

- **Semantic Layer**: Determines what business terms mean.
- **RAG Layer**: Supplies verified corporate policies, accounting standards, and operational guidelines.
- **Analytics Engine**: Calculates exact, deterministic numbers using GAAP-aligned models.
- **Investigation Engine**: Formulates candidate explanations, tests them against empirical evidence, and isolates contributions.
- **LLM**: Orchestrates plan formulation and synthesizes human-readable narratives without performing independent arithmetic.
