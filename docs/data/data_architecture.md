# NEXUS Data Layer Architecture

## 1. Architectural Scope
Phase 2 establishes the **NEXUS Data Layer** for a representative small retail and distribution enterprise. 

This layer transforms raw, noisy operational events into validated, strongly typed, and auditable relational data structures. It provides the empirical foundation upon which the future Phase 3 deterministic analytics engine and Phase 5 semantic layer will operate.

---

## 2. Ingestion to Validation Pipeline

```mermaid
flowchart LR
    subgraph IngestionSources ["1. Ingestion Sources"]
        CSVFiles["CSV Batch Streams"]
        FutureConnectors["Future DB & API Connectors"]
    end

    subgraph ConnectorsLayer ["2. Connectors & Parsing"]
        BaseConn["BaseConnector Interface"]
        CSVConn["CSVConnector (Delimited Parser)"]
    end

    subgraph ValidationEngine ["3. Contract Validation"]
        Schemas["Pydantic v2 Domain Schemas"]
        RowAuditor["Row-Level Error Diagnostician"]
    end

    subgraph RelationalStorage ["4. Relational Persistence"]
        PostgresDB[("PostgreSQL 16 Engine")]
        ORMModels["SQLAlchemy 2.x Normalized Models"]
    end

    subgraph TelemetryQuality ["5. Profiling & Quality Engine"]
        Profiler["DataProfiler (Stats, Nulls, Distributions)"]
        QualityChecker["DataQualityChecker (Business Rules & FKs)"]
        Scorecard["Structured QualityReport"]
    end

    CSVFiles --> CSVConn
    FutureConnectors --> BaseConn
    CSVConn --> Schemas
    Schemas --> RowAuditor
    RowAuditor -->|Clean Rows| ORMModels
    ORMModels --> PostgresDB
    PostgresDB --> Profiler
    PostgresDB --> QualityChecker
    QualityChecker --> Scorecard
```

---

## 3. Structural Tenets

1. **Fixed-Point Financial Arithmetic**:
   - Floating-point representations (`FLOAT`, `DOUBLE PRECISION`) are strictly forbidden for monetary transactions.
   - All currencies, line totals, discounts, taxes, and overhead costs utilize fixed-precision `NUMERIC(12, 2)` mapped to Python `Decimal`.
2. **Deterministic Validation**:
   - Zero LLM code execution is permitted during ingestion, profiling, or quality checks. All validations run deterministic Python rules and database constraint checks.
3. **Reconcilable Transaction Lineage**:
   - Every transaction item enforces $(quantity \times unit\_price) - discount\_amount = line\_total$.
   - Every transaction header enforces $subtotal - discount\_amount + tax\_amount = total\_amount$.
4. **Non-Destructive Ingestion**:
   - When raw records fail validation, malformed rows are isolated into structured diagnostics (`IngestionRowError`) rather than silently dropped or altered.
