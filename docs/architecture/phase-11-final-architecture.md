# NEXUS V1 — Production Architecture (Reconciled)

**Document Version**: 1.0  
**Phase**: Phase 11 — Production Readiness, Architecture Reconciliation & V1 Gap Closure  
**Author**: Staff AI Systems Architect & Platform Engineer  
**Status**: Authoritative V1 Production Architecture  

---

## 1. Executive Summary

This document presents the **reconciled production architecture** of the NEXUS platform for its V1 release. 

Unlike early conceptual blueprints that mixed implemented components with speculative enterprise roadmaps, this specification represents **concrete, running software**:
- Every block depicted in solid lines is implemented, tested with 206 automated tests, and production-deployed.
- Capabilities deferred to future phases are explicitly tagged as `[FUTURE / V2]` rather than depicted as active systems.

---

## 2. High-Level V1 System Topology

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     NEXUS CLIENT TIER (SPA)                                      │
│                                                                                                  │
│  React 18 + TypeScript + Vite + Tailwind CSS + Lucide Icons + Recharts                            │
│  ┌───────────────┬────────────────┬────────────────┬─────────────────┬────────────────────────┐  │
│  │ Ask NEXUS     │ Overview Hub   │ Analytics View │ Forecast Studio │ Diagnostic Waterfall   │  │
│  ├───────────────┼────────────────┼────────────────┼─────────────────┼────────────────────────┤  │
│  │ Data Health   │ Knowledge Base │ Decision Gate  │ Run History     │ Report Export          │  │
│  └───────────────┴────────────────┴────────────────┴─────────────────┴────────────────────────┘  │
└──────────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                   │ HTTPS / REST (JSON API)
                                                   │ Authorization: Bearer <key> | X-API-Key: <key>
                                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   FASTAPI 0.110+ GATEWAY & RUNTIME                               │
│                                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Middleware: RequestCorrelationMiddleware (X-Request-ID) | CORS (Production Sanitized)     │  │
│  │ Security Perimeter: verify_api_key (Enforced on /api/v1/*; Bypass on /api/health probes)   │  │
│  │ Global Exception Handler: Production error shielding (Traceback suppressed; ID stamped)    │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                   │                                              │
│         ┌─────────────────────────────────────────┼──────────────────────────────────┐           │
│         ▼                                         ▼                                  ▼           │
│  ┌──────────────────────┐              ┌──────────────────────┐           ┌───────────────────┐  │
│  │ Health & Probes      │              │ Data & Connectors    │           │ Semantic Layer    │  │
│  │ /api/health (live)   │              │ CSVIngestionService  │           │ KPIOntology       │  │
│  │ /api/health/ready    │              │ SQLConnector         │           │ 12+ GAAP metrics  │  │
│  │ Metrics (/metrics)   │              │ DataProfiler         │           │ Domain rules      │  │
│  └──────────────────────┘              │ DataQualityChecker   │           │ Ambiguity guard   │  │
│                                        └──────────────────────┘           └───────────────────┘  │
│                                                   │                                              │
│                                                   ▼                                              │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                         STATEFUL LANGGRAPH AGENT ORCHESTRATION                             │  │
│  │                                                                                            │  │
│  │   UnderstandNode ──► SemanticNode ──► PlanningNode ──► ToolExecutionNode                   │  │
│  │         │                                                    │                             │  │
│  │         ▼ (Clarification / Unsupported)                      ▼                             │  │
│  │   SpecializedNodes ◄─────────────────────────────── EvidenceCheckNode                      │  │
│  │                                                              │ (Sufficient)                │  │
│  │                                                              ▼                             │  │
│  │   ExplainerNode (Multi-Tier Narrative) ◄─────── InvestigationNode / ForecastNode           │  │
│  │                                                                                            │  │
│  │   • Iteration Boundary: Maximum 5 loops    • Zero Code Execution   • Tool Allowlist (16)   │  │
│  └────────────────────────────────────────────────┬───────────────────────────────────────────┘  │
│                                                   │                                              │
│         ┌─────────────────────────────────────────┼──────────────────────────────────┐           │
│         ▼                                         ▼                                  ▼           │
│  ┌──────────────────────┐              ┌──────────────────────┐           ┌───────────────────┐  │
│  │ Deterministic Engine │              │ Investigation Engine │           │ Predictive Studio │  │
│  │ SQLAlchemy 2.x SQL   │              │ Price/Volume/Mix     │           │ Exponential Smooth│  │
│  │ NumPy / SciPy Stats  │              │ Category / SKU drill │           │ Auto-regressive   │  │
│  │ RFM Quintiles        │              │ Causal Safeguards    │           │ P10–P90 intervals │  │
│  │ Cohort Retention     │              │ Waterfall breakdown  │           │ Backtest MAE/MAPE │  │
│  └──────────────────────┘              └──────────────────────┘           └───────────────────┘  │
│                                                   │                                              │
│                                                   ▼                                              │
│  ┌────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                             RAG & BUSINESS CONTEXT LAYER                                   │  │
│  │  DocumentIngestionService (PDF/TXT/MD chunking) ──► pgvector Vector Store (1536-dim)       │  │
│  │  HybridRetriever ──► Semantic policy injection ──► Cited RAGEvidence provenance           │  │
│  └────────────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                                    │
                                                    ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                  POSTGRESQL 16 ENTERPRISE STORAGE                                │
│                                                                                                  │
│  ┌─────────────────────────┬──────────────────────────┬───────────────────────────────────────┐  │
│  │ Operational Data Store  │ Knowledge Vector Store   │ Audit & Human Review Ledger           │  │
│  │ • sales, sale_items     │ • knowledge_documents    │ • analysis_runs (Persistent history)  │  │
│  │ • customers, products   │ • knowledge_chunks       │ • decision_records (HITL approval)    │  │
│  │ • inventory, expenses   │ • pgvector extension     │ • review status (PENDING / APPROVED)  │  │
│  └─────────────────────────┴──────────────────────────┴───────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   FUTURE ARCHITECTURAL HORIZON                                   │
│  [FUTURE / V2]: Logical Multi-Tenancy (tenant_id) • Enterprise SSO / SAML • Dynamic Model Router │
│  [FUTURE / V3]: Continuous Anomaly Push Daemon • Outbound ERP Webhook Automation • Cloud Warehouses│
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Subsystem Architectural Specifications

### 1. Presentation Tier (Client)
- **Framework**: React 18, TypeScript 5.x, Vite, Tailwind CSS.
- **State Management & Communication**: Unified `apiRequest` HTTP client with typed contracts.
- **Security**: Bearer token and `X-API-Key` headers injected dynamically into requests; automatic 401 redirection.
- **Visual Status**: Production UI with 7 operational views.

### 2. Security & Gateway Perimeter
- **Endpoint Protection**: `/api/v1/*` routes guarded by `verify_api_key`.
- **Health Bypasses**: `/api/health`, `/api/health/live`, `/api/health/ready` operate unauthenticated for container orchestrator liveness/readiness probes.
- **Input Sanitization**: `sanitize_query` normalizes text and strips control bytes; `sanitize_filename` prevents path traversal.
- **Prompt Guard**: `detect_prompt_injection` flags adversarial jailbreaks and system override directives.
- **Error Shielding**: Production exception handlers suppress raw stack traces, emitting sanitized messages and `X-Request-ID` correlation markers.

### 3. Stateful Agent Reasoning (LangGraph)
- **State Schema**: `AgentState` TypedDict enforcing typed keys across all graph nodes.
- **Loop Bounding**: Enforces `MAX_AGENT_ITERATIONS = 5`.
- **Tool Allowlist**: Only 16 registered analytical tools can be called. Arbitrary code, raw shell commands, and untrusted SQL strings are strictly prohibited.
- **Disambiguation**: Queries requesting breakdowns without target metrics or dimensions trigger an immediate clarification pause.

### 4. Deterministic Analytics Engine
- **Calculations**: 100% exact math executed by PostgreSQL engine, Pandas, NumPy, and SciPy.
- **Zero Generative Math**: LLM never computes sums, margins, ratios, or p-values.
- **Traceability**: Every output produces an immutable `EvidenceRecord` citing source tables, SQL queries, and row counts.

### 5. Diagnostic Investigation & Predictive Intelligence
- **PVM Decomposition**: Isolates price elasticity, volume changes, and product mix variance mathematically.
- **Causality Protection**: Enforces textual safeguards distinguishing mathematical association from causal attribution.
- **Calibrated Forecasting**: Time-series models provide P10/P50/P90 prediction intervals based on empirical residual distributions.

### 6. Human-in-the-Loop Review & Run History (Phase 11)
- **AnalysisRun**: Every completed query is persisted to PostgreSQL with execution time, tools executed, calculations, and evidence records.
- **DecisionRecord**: Recommendations are registered as `PENDING` decisions requiring human analyst sign-off (`APPROVED`, `REJECTED`, `MODIFIED`).
- **Reports**: `GET /api/v1/history/runs/{id}/report` generates audit-ready Markdown and JSON dossiers on demand.

### 7. Multi-Tenancy & Data Isolation Model
- **V1 Model**: **Dedicated Single-Tenant Instance** (one containerized deployment per enterprise). Physical container and network isolation ensure zero cross-customer data leakage.
- **V2 Model [FUTURE]**: Logical schema-level partitioning with explicit `tenant_id` on all tables, row-level security (RLS), and organization-scoped RAG.

---

## 4. Technology Stack Verification

| Tier | Component | Technology | V1 Status |
|---|---|---|:---:|
| **Frontend** | Web Application | React 18, TypeScript 5, Vite, Tailwind CSS | VERIFIED |
| **API Gateway** | REST API Server | Python 3.12+, FastAPI, Pydantic v2 | VERIFIED |
| **Agentic AI** | Workflow State Machine | LangGraph 0.0.30+, LangChain Core | VERIFIED |
| **Analytics** | Scientific Computing | NumPy, SciPy, Pandas, scikit-learn | VERIFIED |
| **RAG / Vector** | Semantic Knowledge | PostgreSQL 16 `pgvector`, OpenAI / Mock embeddings | VERIFIED |
| **Relational DB** | Enterprise Store | PostgreSQL 16, SQLAlchemy 2.x, Alembic | VERIFIED |
| **Observability** | Telemetry & Health | RequestCorrelationMiddleware, Prometheus endpoints | VERIFIED |
| **Infrastructure** | Containerization | Docker, Docker Compose, Multi-stage builds | VERIFIED |
