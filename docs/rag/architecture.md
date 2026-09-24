# NEXUS Phase 5 — Business Context RAG + Semantic Layer Architecture

## 1. Core Philosophy

NEXUS is **not a generic document chatbot** or "chat with PDFs" wrapper. In an enterprise Business Intelligence platform, language models must **never become the source of truth for numerical calculations**.

NEXUS establishes strict separation of responsibilities:
- **Semantic Layer**: Resolves business language, terms, and synonyms to canonical metrics.
- **Deterministic Analytics Engine**: Computes exact, reproducible numbers via SQL and Python statistics.
- **Business Context RAG**: Retrieves verified business definitions, policies, and accounting rules.
- **Evidence Layer**: Provides full mathematical and audit provenance for every figure.
- **LangGraph Agent / LLM**: Orchestrates the analysis flow and synthesizes grounded explanations.

```mermaid
graph TD
    User([User Request]) --> API[FastAPI / Agent API]
    API --> Agent[LangGraph Agent]
    
    subgraph "Phase 5 Semantic & Knowledge Layer"
        Agent --> SemanticNode[Semantic Resolution Node]
        SemanticNode --> Ontology[(KPI Ontology Registry)]
        SemanticNode --> RAGNode[Retrieve Context Node]
        RAGNode --> Retriever[Hybrid Retriever]
        Retriever --> VectorDB[(PostgreSQL + pgvector)]
    end
    
    subgraph "Phase 4 Agent Planning"
        RAGNode --> Plan[Analysis Planning Node]
        Plan --> Validate[Plan Validation Node]
    end
    
    subgraph "Phase 3 Deterministic Analytics Engine"
        Validate --> Exec[Tool Execution Node]
        Exec --> Tools[Deterministic Tool Registry]
        Tools --> AnalyticsSvc[AnalyticsService]
        AnalyticsSvc --> SQLDB[(Relational DB / SQL)]
        AnalyticsSvc --> MathProof[EvidenceRecord]
    end
    
    subgraph "Grounded Synthesis"
        MathProof --> Inspect[Inspect Result & Check Evidence]
        Inspect --> Explain[Generate Explanation Node]
        Explain --> Grounded[Grounded Explanation with Dual Provenance]
    end
    
    Grounded --> User
```

## 2. Dual Provenance Architecture

NEXUS distinguishes between two distinct types of evidence:
1. **Analytics Evidence (`EvidenceRecord`)**: Proves *how a number was calculated*, detailing source tables, aggregation formulas, SQL parameters, assumptions, and statistical caveats.
2. **RAG Evidence (`RAGEvidence`)**: Proves *where business context originated*, detailing document IDs, source filenames, section titles, chunk IDs, similarity scores, and retrieval timestamps.

Both evidence models coexist within every `AgentResponse` payload returned to users and API consumers.
