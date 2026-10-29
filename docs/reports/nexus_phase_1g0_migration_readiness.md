# NEXUS Phase 1G.0 — Watermark Migration Readiness Gate Report

**Date**: 2026-10-29  
**Repository**: [rzvn6660/Nexus](https://github.com/rzvn6660/Nexus)  
**Branch**: `main`  
**Starting Schema Revision**: `016_phase1c2_tenant_scoped_customer_identity`  
**Target Migration**: `017_phase1f2_authoritative_ingestion_watermark`  
**Target File**: [`backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py`](file:///C:/Users/rizvi/nexus/backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py)  
**Verdict**: **CONDITIONAL GO (MIGRATION ARTIFACTS VERIFIED; AWAITING CI / CONTAINERIZED POSTGRESQL REHEARSAL GATE)**

---

> [!IMPORTANT]
> **STAGING INVARIANT PROTECTION & SAFETY STATUS**:
> 1. **Zero Changes to Staging**: Migration 017 has **NOT** been applied to `nexus_staging_db`. The staging database remains strictly at revision `016_phase1c2_tenant_scoped_customer_identity`.
> 2. **Tenant Data Untouched**: Staging tenant `Apex Specialty Commerce` (1,000 customers, 3,500 sales, 11,221 line items) was preserved completely intact.
> 3. **Disposable / In-Memory Isolation**: All upgrade, downgrade, re-upgrade, and constraint verification tests were conducted against isolated disposable engines without modifying staging or production data.

---

## 1. Executive Summary

Phase 1G.0 acts as the formal migration readiness gate for the Phase 1F.2 Authoritative Ingestion Watermark implementation. Its objective is to audit the data model, service boundaries, transaction lifecycles, and downstream analytical integrations before creating and authoritatively verifying Alembic migration `017`.

### Key Outcomes:
1. **Architectural & Transaction Audit Completed**: Audited [`TenantIngestionWatermark`](file:///C:/Users/rizvi/nexus/backend/app/models/watermark.py), [`WatermarkService`](file:///C:/Users/rizvi/nexus/backend/app/services/watermark_service.py), [`DataGatewayService`](file:///C:/Users/rizvi/nexus/backend/app/services/data_gateway_service.py), [`CustomerDataReadinessAssessor`](file:///C:/Users/rizvi/nexus/backend/app/analytics/customer/readiness.py), and [`HistoricalCadenceValidator`](file:///C:/Users/rizvi/nexus/backend/app/analytics/customer/validation.py). Addressed all eight explicit audit probes (source configuration, in-flight blocking, backfill invalidation, reactivation prevention, audit retention, transaction rollback, tenant isolation, and outcome safety).
2. **Database-Level Active Watermark Exclusivity**: Enhanced both the ORM model and migration DDL with a partial unique index:
   ```sql
   CREATE UNIQUE INDEX uq_tenant_watermarks_active_source 
   ON tenant_ingestion_watermarks (business_id, source_id) 
   WHERE is_active = true;
   ```
   This guarantees at the storage engine level that multiple active watermarks can never coexist for the same tenant and source, while preserving full audit ledger history for inactive superseded records.
3. **Migration 017 Implemented**: Authored [`backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py`](file:///C:/Users/rizvi/nexus/backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py) with revision ID `017_phase1f2_authoritative_ingestion_watermark` chained to parent `016_phase1c2_tenant_scoped_customer_identity`.
4. **Static DDL & Dialect Verification**: Verified both forward static SQL generation (`alembic upgrade 016:017 --sql`) and backward static SQL generation (`alembic downgrade 017:016 --sql`). Confirmed transactional DDL blocks (`BEGIN ... COMMIT`).
5. **Programmatic Migration Lifecycle Test**: Executed automated programmatic upgrade, schema inspection, downgrade, and re-upgrade test ([`test_alembic_migration_017_upgrade_downgrade_sqlite`](file:///C:/Users/rizvi/nexus/backend/tests/test_analytics_watermark.py)). Verified that the table and all six indexes are created and dropped cleanly.
6. **Live PostgreSQL Rehearsal Suite Created**: Authored [`backend/tests/test_postgres_migration_017_rehearsal.py`](file:///C:/Users/rizvi/nexus/backend/tests/test_postgres_migration_017_rehearsal.py) covering all 10 target validation scenarios.
7. **Environmental Status & Blocker**: Docker Desktop daemon was not running on the Windows host, preventing local containerized PostgreSQL instantiation. Tests appropriately skipped with explicit diagnostic messaging.
8. **Comprehensive Regression Suite**: Executed 93 tests across customer analytics, watermarks, synthetic generators, and data gateway: **91 passed, 2 skipped (PostgreSQL daemon guard), 0 failed**. Static analysis (`ruff check`) and whitespace audit (`git diff --check`) reported **0 errors**.

---

## 2. Implementation Audit & Architectural Findings

We conducted an exhaustive audit of the Phase 1F.2 watermark components prior to finalizing migration 017:

### 2.1 Audit Checklist & Resolution

| Audit Question | Investigation Finding | Architectural Implementation & Safeguard | Status |
| :--- | :--- | :--- | :--- |
| **1. Ingestion Source Scoping** | How are required sources configured and scoped per tenant? | In `WatermarkContract`, each watermark explicitly requires `business_id` (FK to `businesses.id`) and `source_id`. `WatermarkService.get_effective_tenant_watermark` supports passing `required_sources: list[str]`. If any required source lacks an active verified watermark, status is `incomplete_watermark_gap`. When omitted, it takes $\min(T_s)$ across all active verified sources recorded for that tenant. In `DataGatewayService`, `source_id` now checks `dataset.schema_json.get("source_id")` before falling back to filename. | **VERIFIED** |
| **2. In-Flight / Failed Pipelines** | Can failed, partial, or in-flight ingestion incorrectly certify completeness? | **No.** Gate 1 in `WatermarkService.get_effective_tenant_watermark` queries `IngestionJob` for statuses `['PENDING', 'PROCESSING', 'FAILED', 'REQUIRES_REVIEW']`. If count $> 0$, it immediately halts evaluation with `status="incomplete_in_flight"`, `is_verified=False`, and returns `None` for the effective watermark. | **VERIFIED** |
| **3. Backfill & Refund Invalidation** | Does late-arriving data, refund, or correction invalidate the watermark? | **Yes.** In `DataGatewayService.commit_mapped_data`, the earliest incoming transaction date $\tau_{\min}$ is evaluated via `WatermarkService.detect_backfill_and_handle`. If $\tau_{\min} \le T_{\text{active}}$, `verification_status` transitions to `invalidated` with an explicit reason citing the date and triggering job ID. | **VERIFIED** |
| **4. Reactivation Prevention** | Can invalidated watermarks be reactivated without fresh verification? | **No.** `WatermarkService` contains no method to reactivate an invalidated watermark. A source can only become verified through `record_watermark(...)` with a newly certified contract, which marks the old watermark `is_active=False` and inserts a new verified entity. | **VERIFIED** |
| **5. Audit History Preservation** | Do historical audit records remain intact when a new certification is issued? | **Yes.** In `record_watermark(...)`, previous active watermarks are updated to `is_active=False`. Rows are **never deleted**. The entire trajectory of certified boundaries remains in `tenant_ingestion_watermarks` for compliance auditing. | **VERIFIED** |
| **6. Transaction Rollback Safety** | Does DB rollback also roll back watermark invalidation when ingestion fails? | **Yes.** `detect_backfill_and_handle` issues `session.flush()`, NOT `session.commit()`. If the surrounding ingestion job fails and triggers `db.rollback()`, the watermark status change in the session is rolled back atomically with the uncommitted sales records. | **VERIFIED** |
| **7. Identity Consistency** | Are tenant and source identifiers consistently validated? | **Yes.** `TenantIngestionWatermark.business_id` is a database foreign key to `businesses.id` with `ON DELETE CASCADE`. All ORM and query filters strictly isolate records by `business_id`. | **VERIFIED** |
| **8. Outcome Safety Invariant** | Can an unverified watermark ever be interpreted as proof of no purchase? | **No.** When `is_verified=False`, `CustomerOutcomeRecord.unverified_negative_outcome` is set to `True`, `is_followup_verified` is set to `False`, and an `UNVERIFIED OUTCOMES NOTICE` is logged. With `require_verified_watermark=True`, unverified follow-ups are censored (`is_censored=True`, `outcome_no_purchase=None`), preventing false churn bias. | **VERIFIED** |

### 2.2 Unresolved Design Consideration & Future Recommendation
- **Tenant Mandatory Sources Registry**: Currently, `required_sources` can be passed dynamically by analytical callers (such as `CustomerDataReadinessAssessor` or `HistoricalCadenceValidator`). However, the database does not currently maintain a dedicated `tenant_required_sources` table or `business.settings["required_sources"]` registry.
- *Recommendation for Phase 2*: Add a tenant configuration field specifying mandatory channels (e.g. `["shopify", "pos_primary"]`) so that background scanners automatically enforce multi-source minimums without requiring manual caller specification.

---

## 3. Migration 017 Design & Schema Specification

The migration script was created at:  
[`backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py`](file:///C:/Users/rizvi/nexus/backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py)

### 3.1 Migration Metadata
- **Revision ID**: `017_phase1f2_authoritative_ingestion_watermark`
- **Parent Revision**: `016_phase1c2_tenant_scoped_customer_identity`
- **Chain Verification**: Verified with `alembic history -r 015:017`:
  ```text
  015_phase29_continuous_intelligence -> 016_phase1c2_tenant_scoped_customer_identity -> 017_phase1f2_authoritative_ingestion_watermark (head)
  ```

### 3.2 Relational Schema (`tenant_ingestion_watermarks`)

```text
Table: tenant_ingestion_watermarks
===================================================================================================
Column Name          Type                     Nullable  Default / Server Default
---------------------------------------------------------------------------------------------------
id                   VARCHAR(36)              NO        PRIMARY KEY (UUID v4)
business_id          VARCHAR(36)              NO        FK -> businesses(id) ON DELETE CASCADE
source_id            VARCHAR(64)              NO        DEFAULT 'default'
complete_through_dt  TIMESTAMP WITH TIME ZONE NO        --
recorded_at          TIMESTAMP WITH TIME ZONE NO        --
ingestion_job_id     VARCHAR(36)              YES       FK -> ingestion_jobs(id) ON DELETE SET NULL
provenance_type      VARCHAR(64)              NO        DEFAULT 'manual_close'
verification_status  VARCHAR(32)              NO        DEFAULT 'verified'
invalidation_reason  VARCHAR(512)             YES       --
is_active            BOOLEAN                  NO        DEFAULT true
metadata_json        JSON                     YES       --
created_at           TIMESTAMP WITH TIME ZONE NO        DEFAULT now()
updated_at           TIMESTAMP WITH TIME ZONE NO        DEFAULT now()
===================================================================================================
```

### 3.3 Indexes & Constraint Catalog

```text
1. ix_tenant_ingestion_watermarks_business_id
   ON tenant_ingestion_watermarks (business_id)

2. ix_tenant_ingestion_watermarks_source_id
   ON tenant_ingestion_watermarks (source_id)

3. ix_tenant_ingestion_watermarks_ingestion_job_id
   ON tenant_ingestion_watermarks (ingestion_job_id)

4. ix_tenant_wm_biz_source_active
   ON tenant_ingestion_watermarks (business_id, source_id, is_active)

5. ix_tenant_wm_biz_complete_dt
   ON tenant_ingestion_watermarks (business_id, complete_through_dt)

6. uq_tenant_watermarks_active_source [PARTIAL UNIQUE INDEX]
   ON tenant_ingestion_watermarks (business_id, source_id) WHERE is_active = true;
```

### 3.4 Forward Static SQL (`alembic upgrade 016:017 --sql`)

```sql
BEGIN;

-- Running upgrade 016_phase1c2_tenant_scoped_customer_identity -> 017_phase1f2_authoritative_ingestion_watermark

CREATE TABLE tenant_ingestion_watermarks (
    id VARCHAR(36) NOT NULL, 
    business_id VARCHAR(36) NOT NULL, 
    source_id VARCHAR(64) DEFAULT 'default' NOT NULL, 
    complete_through_dt TIMESTAMP WITH TIME ZONE NOT NULL, 
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    ingestion_job_id VARCHAR(36), 
    provenance_type VARCHAR(64) DEFAULT 'manual_close' NOT NULL, 
    verification_status VARCHAR(32) DEFAULT 'verified' NOT NULL, 
    invalidation_reason VARCHAR(512), 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    metadata_json JSON, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE CASCADE, 
    FOREIGN KEY(ingestion_job_id) REFERENCES ingestion_jobs (id) ON DELETE SET NULL
);

CREATE INDEX ix_tenant_ingestion_watermarks_business_id ON tenant_ingestion_watermarks (business_id);
CREATE INDEX ix_tenant_ingestion_watermarks_source_id ON tenant_ingestion_watermarks (source_id);
CREATE INDEX ix_tenant_ingestion_watermarks_ingestion_job_id ON tenant_ingestion_watermarks (ingestion_job_id);
CREATE INDEX ix_tenant_wm_biz_source_active ON tenant_ingestion_watermarks (business_id, source_id, is_active);
CREATE INDEX ix_tenant_wm_biz_complete_dt ON tenant_ingestion_watermarks (business_id, complete_through_dt);
CREATE UNIQUE INDEX uq_tenant_watermarks_active_source ON tenant_ingestion_watermarks (business_id, source_id) WHERE is_active = true;

UPDATE alembic_version SET version_num='017_phase1f2_authoritative_ingestion_watermark' WHERE alembic_version.version_num = '016_phase1c2_tenant_scoped_customer_identity';

COMMIT;
```

### 3.5 Rollback Static SQL (`alembic downgrade 017:016 --sql`)

```sql
BEGIN;

-- Running downgrade 017_phase1f2_authoritative_ingestion_watermark -> 016_phase1c2_tenant_scoped_customer_identity

DROP INDEX uq_tenant_watermarks_active_source;
DROP INDEX ix_tenant_wm_biz_complete_dt;
DROP INDEX ix_tenant_wm_biz_source_active;
DROP INDEX ix_tenant_ingestion_watermarks_ingestion_job_id;
DROP INDEX ix_tenant_ingestion_watermarks_source_id;
DROP INDEX ix_tenant_ingestion_watermarks_business_id;

DROP TABLE tenant_ingestion_watermarks;

UPDATE alembic_version SET version_num='016_phase1c2_tenant_scoped_customer_identity' WHERE alembic_version.version_num = '017_phase1f2_authoritative_ingestion_watermark';

COMMIT;
```

---

## 4. Disposable Database Rehearsal & Environmental Blocker

### 4.1 Automated Programmatic Rehearsal Execution
We validated the complete migration upgrade, inspection, downgrade, and re-upgrade lifecycle in [`test_alembic_migration_017_upgrade_downgrade_sqlite`](file:///C:/Users/rizvi/nexus/backend/tests/test_analytics_watermark.py):
1. **Upgrade**: Created `tenant_ingestion_watermarks` table and all six indexes. Verified columns and nullability.
2. **Downgrade**: Cleanly dropped all six indexes and dropped the table without leaving orphan database artifacts.
3. **Re-Upgrade**: Re-executed `upgrade()`, confirming idempotency and clean re-application.
4. **Active Watermark Exclusivity**: In [`test_database_level_active_watermark_unique_constraint`](file:///C:/Users/rizvi/nexus/backend/tests/test_analytics_watermark.py), inserting two active records for the same `(business_id, source_id)` was blocked by the database engine with `IntegrityError`, while inserting an inactive record (`is_active=False`) succeeded immediately.

### 4.2 Environmental Status: Local Docker / PostgreSQL Blocker
In accordance with prompt instructions:
> "If PostgreSQL or Docker is unavailable, report the blocker and provide the exact commands and evidence still needed. Do not describe unexecuted checks as passed."

- **Inspection Finding**: When executing `docker info` and `docker ps`, the Docker CLI reported:
  ```text
  failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine: 
  The system cannot find the file specified.
  ```
- **Blocker Root Cause**: The Docker Desktop Linux VM daemon is not running on the Windows host.
- **Handling**: In [`backend/tests/test_postgres_migration_017_rehearsal.py`](file:///C:/Users/rizvi/nexus/backend/tests/test_postgres_migration_017_rehearsal.py), `test_postgres_available_or_skipped` passed and the two live PostgreSQL tests were skipped with the explicit reason:
  ```text
  SKIPPED: Live PostgreSQL daemon is not reachable on configured database URL. 
  Set REQUIRE_POSTGRES=true or start PostgreSQL/Docker to run live rehearsal.
  ```

### 4.3 Exact Verification Command for Containerized CI Environment
To execute the live rehearsal against PostgreSQL 16 (matching the CI pgvector container or local docker daemon):

```bash
# 1. Start disposable PostgreSQL 16 container
docker run -d --name nexus-rehearsal-pg16 \
  -e POSTGRES_USER=nexus_user \
  -e POSTGRES_PASSWORD=nexus_password \
  -e POSTGRES_DB=nexus_test_db \
  -p 5432:5432 pgvector/pgvector:pg16

# 2. Run the strict PostgreSQL rehearsal test suite
REQUIRE_POSTGRES=true \
TEST_DATABASE_URL="postgresql+psycopg://nexus_user:nexus_password@localhost:5432/nexus_test_db" \
pytest backend/tests/test_postgres_migration_017_rehearsal.py -v
```

---

## 5. Comprehensive Regression Test Evidence

### 5.1 Test Execution Summary

| Test Suite Module | Command Line | Tests Executed | Passed | Skipped | Failed | Duration |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Watermarks & Ingestion Contracts** | `pytest backend/tests/test_analytics_watermark.py` | 13 | 13 | 0 | 0 | 0.44s |
| **PostgreSQL 017 Rehearsal Guard** | `pytest backend/tests/test_postgres_migration_017_rehearsal.py` | 3 | 1 | 2 (Guard) | 0 | 0.05s |
| **Synthetic Cadence Generation** | `pytest backend/tests/test_data_synthetic_cadence.py` | 14 | 14 | 0 | 0 | 4.88s |
| **Customer Cadence Analytics** | `pytest backend/tests/test_analytics_customer_cadence.py` | 19 | 19 | 0 | 0 | 0.81s |
| **Customer Readiness Assessor** | `pytest backend/tests/test_analytics_customer_readiness.py` | 7 | 7 | 0 | 0 | 1.12s |
| **Historical Cadence Validation** | `pytest backend/tests/test_analytics_customer_validation.py` | 13 | 13 | 0 | 0 | 8.44s |
| **Data Gateway Ingestion** | `pytest backend/tests/test_data_gateway.py` | 24 | 24 | 0 | 0 | 5.08s |
| **Total Test Runs** | **Combined Regression Execution** | **93** | **91** | **2** | **0** | **20.77s** |

### 5.2 Code Quality & Static Analysis
- **Ruff Linter**:
  ```text
  ruff check backend/app/models/watermark.py backend/app/models/__init__.py backend/app/services/watermark_service.py backend/app/analytics/customer/readiness.py backend/app/analytics/customer/validation.py backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py backend/tests/test_analytics_watermark.py backend/tests/test_postgres_migration_017_rehearsal.py
  Result: All checks passed! (0 errors)
  ```
- **Git Diff Whitespace Check**:
  ```text
  git diff --check
  Result: 0 errors
  ```

---

## 6. Current Working Tree & File Status

All changes are preserved uncommitted and unpushed:

```text
Changes not staged for commit:
  modified:   backend/app/analytics/customer/readiness.py
  modified:   backend/app/analytics/customer/validation.py
  modified:   backend/app/data/synthetic/cadence_generator.py
  modified:   backend/app/models/__init__.py
  modified:   backend/app/services/data_gateway_service.py
  modified:   backend/tests/test_data_synthetic_cadence.py

Untracked files:
  backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py
  backend/app/models/watermark.py
  backend/app/services/watermark_service.py
  backend/tests/test_analytics_watermark.py
  backend/tests/test_postgres_migration_017_rehearsal.py
  docs/reports/nexus_phase_1e_staging_execution_report.md
  docs/reports/nexus_phase_1f2_watermark_design.md
  docs/reports/nexus_phase_1f_synthetic_cadence_validation.md
  docs/reports/nexus_phase_1g0_migration_readiness.md
```

---

## 7. Migration Readiness Verdict & Precise Next Action

### Verdict: **CONDITIONAL GO**

#### Rationale:
1. **Migration Artifact Ready**: Migration `017_phase1f2_authoritative_ingestion_watermark` is fully implemented, correctly chained to revision `016`, verified in offline static SQL generation, and programmatically validated for upgrade, downgrade, and re-upgrade.
2. **Schema Integrity Verified**: All column definitions, foreign keys, cascade rules, composite indexes, and partial unique active constraints are mathematically consistent between ORM metadata and Alembic DDL.
3. **Regression Suite Green**: 91 passing unit, analytical, gateway, and migration tests confirm zero behavioral regressions.
4. **Condition**: Before executing `alembic upgrade head` on `nexus_staging_db`, the rehearsal test suite [`test_postgres_migration_017_rehearsal.py`](file:///C:/Users/rizvi/nexus/backend/tests/test_postgres_migration_017_rehearsal.py) must be executed in CI (or with an active disposable PostgreSQL 16 container) with `REQUIRE_POSTGRES=true`.

### Precise Next Action:
Do **NOT** apply migration 017 to staging yet. Submit the feature branch to CI to execute the live PostgreSQL 16 container rehearsal gate. Upon green CI run, proceed to the authorized staging migration execution phase.

