# NEXUS Phase 11 — V1 Scope Decisions & Gap Prioritization

**Document Version**: 1.0  
**Phase**: Phase 11 — Production Readiness, Architecture Reconciliation & V1 Gap Closure  
**Author**: Staff AI Systems Architect & Product Engineering Lead  
**Status**: Official Architectural Decision Record (ADR)  

---

## 1. Executive Decision Summary

The purpose of Phase 11 is **not** to implement every theoretical feature conceived in early blueprints. The purpose is to:
> *"Make the product coherent, safe, honest, and production-capable within a clearly defined V1 boundary."*

This document classifies every identified architectural gap into four priority tiers:
- **P0 (Must Fix Before V1)**: Non-negotiable blockers that threaten security, data integrity, correctness, or essential functionality.
- **P1 (Should Fix for V1)**: High-value capabilities required to complete the core user and analyst workflow.
- **P2 (V2 Roadmap)**: Complex enterprise features (e.g. multi-tenancy, RBAC, dynamic model routing) that belong to a mature V2 milestone.
- **P3 (Future Horizon)**: Long-term capabilities (continuous push monitoring, outbound autonomous execution) that are speculative or out-of-scope.

---

## 2. Gap Prioritization Matrix

```
PRIORITY DISTRIBUTION
┌───────────────────────────────────────┬───────┬───────────────────────────────────────────┐
│ Priority Tier                         │ Count │ Action Strategy                           │
├───────────────────────────────────────┼───────┼───────────────────────────────────────────┤
│ P0 — Must Fix Before V1               │ 4     │ Fully implement and verify in Phase 11    │
│ P1 — Should Fix for V1                │ 3     │ Fully implement and verify in Phase 11    │
│ P2 — V2 Roadmap                       │ 5     │ Document as formal V2 specifications      │
│ P3 — Future Horizon                   │ 3     │ Document as future architectural roadmap  │
└───────────────────────────────────────┴───────┴───────────────────────────────────────────┘
```

---

## 3. Detailed Gap Classification

### P0 — Must Fix Before V1 (Non-Negotiable Blockers)

#### P0-1: Wire Authentication & Bearer/API Key Protection to All `/api/v1` Routes
- **Rationale**: Having an authentication validator in `app/core/security.py` without attaching it to API routers means the platform cannot be secured in production.
- **Implementation**: Wire `verify_api_key` as a shared router dependency in `app/api/v1/api.py`. Support both `X-API-Key` and `Authorization: Bearer <key>`. Keep `/api/health` unauthenticated for container orchestrator probes.

#### P0-2: Implement Persistent Human-in-the-Loop Decision & Approval Ledger
- **Rationale**: The core philosophical tenet of NEXUS is *"AI augments analysts; AI does not replace human judgment."* The approval workflow was detailed in `docs/architecture/human_in_the_loop.md` but had zero database models or API routes.
- **Implementation**: Create `DecisionRecord` model (`PENDING`, `APPROVED`, `REJECTED`, `MODIFIED`), Alembic migration, and API endpoints (`POST /api/v1/agent/decisions`, `GET /api/v1/agent/decisions`, `PATCH /api/v1/agent/decisions/{id}`).

#### P0-3: Implement Persistent Analysis Run History
- **Rationale**: NEXUS cannot claim auditable business intelligence if completed analyses vanish into memory after HTTP responses are sent. Analysis runs must be stored as first-class product entities.
- **Implementation**: Create `AnalysisRun` model, persist execution metadata, executed SQL, and final answers, and expose `GET /api/v1/agent/history` and `GET /api/v1/agent/history/{id}`.

#### P0-4: Correctness Fix — Far-Future Date Boundaries & Ambiguity Disambiguation
- **Rationale**: Asking for "December 2099" silently returned $0 revenue; asking for "Give me a breakdown" without metrics or dimensions attempted invalid execution.
- **Implementation**: Add explicit temporal horizon detection in `DateInterpreter` and ambiguity checks in `understand_request_node` that immediately prompt for clarification.

---

### P1 — Should Fix for V1 (High-Value Polish & Safety)

#### P1-1: Centralized Security Controls Module (`app/security/`)
- **Rationale**: `backend/app/security/__init__.py` was empty. Security controls (input sanitization, prompt injection guardrails, upload path normalization) must be centralized and unit tested.
- **Implementation**: Implement `app/security/sanitizer.py` and `app/security/prompt_guard.py` with comprehensive test coverage.

#### P1-2: Structured Analysis Report Export Endpoint
- **Rationale**: Analysts and executives require exportable dossiers (Markdown / JSON) containing findings, evidence, calculations, and decision signatures.
- **Implementation**: Add `GET /api/v1/agent/history/{id}/report` returning a formatted, publication-ready intelligence dossier.

#### P1-3: Clean SQL / Database Connector Interface
- **Rationale**: While CSV ingestion is solid, providing an explicit relational SQL connector interface in `app/data/connectors/sql_connector.py` demonstrates clean extensibility beyond CSVs without overbuilding a cloud integration ecosystem.
- **Implementation**: Implement `SQLConnector` adhering to `BaseConnector`.

---

### P2 — V2 Roadmap (Intentionally Deferred to Preserve V1 Focus)

#### P2-1: Multi-Tenant Logical Schema Partitioning (`tenant_id` on all tables)
- **Decision**: Deferred to V2.
- **Justification**: V1 is deployed as a **dedicated single-tenant container instance** per organization. Adding `tenant_id` across 10 tables, rewriting all SQL aggregations, and re-indexing pgvector would destabilize verified Phase 1–10 logic. Dedicated instances provide superior physical data isolation for enterprise compliance.

#### P2-2: Granular Role-Based Access Control (RBAC) & Multi-User Accounts
- **Decision**: Deferred to V2.
- **Justification**: Single-instance token/API key authentication secures the perimeter for V1. Granular user login, password hashing, and user-level permissions require multi-user schemas that belong in V2 alongside enterprise SSO.

#### P2-3: Benchmark-Driven Dynamic Model Router
- **Decision**: Deferred to V2.
- **Justification**: The clean `LLMProvider` abstraction (`MockLLMProvider`, `OpenAIProvider`) satisfies V1 requirements. Dynamic routing across latency/cost benchmarks requires live production telemetry and multi-provider evaluation pipelines.

#### P2-4: Cloud Data Warehouse Connectors (Snowflake, BigQuery, Databricks)
- **Decision**: Deferred to V2.
- **Justification**: Adding cloud connectors introduces massive external dependencies, cloud billing, and OAuth complexity. CSV and direct SQL connectors satisfy the V1 retail analytics boundary.

#### P2-5: Enterprise SSO / OAuth2 / SAML Integration
- **Decision**: Deferred to V2.
- **Justification**: Standard API Key and Bearer token headers allow integration with enterprise API gateways (Kong, Envoy, AWS API Gateway) without embedding complex IdP logic in the core monolith.

---

### P3 — Future Horizon (Speculative / Long-Term)

#### P3-1: Continuous Background Intelligence & Anomaly Push Daemon
- **Decision**: Deferred to Future.
- **Justification**: NEXUS is designed as an interactive analytical copilot. Background schedulers with automated alerting increase operational overhead and alert fatigue.

#### P3-2: Autonomous Outbound Execution & Webhook Automation
- **Decision**: Deferred to Future.
- **Justification**: Autonomously modifying inventory levels or triggering ERP actions violates the human-in-the-loop doctrine. Human approval must precede operational action.

#### P3-3: Real-Time Stream Ingestion (Kafka / Flink)
- **Decision**: Deferred to Future.
- **Justification**: Business intelligence and diagnostic causal investigation are inherently batch/transactional operations, not sub-second stream analytics.

---

## 4. Implementation Boundary for Phase 11

In Phase 11, the engineering team will implement **only P0 and justified P1 items**:
1. Wire authentication into `/api/v1` routes.
2. Build persistent `AnalysisRun` and `DecisionRecord` models and API endpoints.
3. Fix far-future date boundaries and ambiguous query clarification in agent reasoning.
4. Implement centralized security guards in `app/security/`.
5. Implement structured report export.
6. Add `SQLConnector` interface.
7. Verify with zero regressions across the 193-test backend suite and Phase 9 evaluation.
