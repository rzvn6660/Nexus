# NEXUS Phase 1G.0 / 1G.0.1 — Watermark Migration Readiness & PostgreSQL 16 CI Verification Report

**Date**: 2026-10-29
**Repository**: [rzvn6660/Nexus](https://github.com/rzvn6660/Nexus)
**Branch**: [`feat/phase1g-watermark-migration-rehearsal`](https://github.com/rzvn6660/Nexus/tree/feat/phase1g-watermark-migration-rehearsal)
**Base Branch**: `main` (`580fe7ae9b734fe0d13bb2227d8ce6692795f519`)
**Feature Commits**:
- `822f1df` (`feat(watermark): implement authoritative ingestion watermark and PostgreSQL 16 migration 017 rehearsal`)
- `3cc91a1` (`fix(tests): update alembic head assertions in test_config and phase30 integration for revision 017`)
**Starting Schema Revision**: `016_phase1c2_tenant_scoped_customer_identity`
**Target Migration**: `017_phase1f2_authoritative_ingestion_watermark`
**Target Migration File**: [`backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py`](file:///C:/Users/rizvi/nexus/backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py)
**Rehearsal Test Suite**: [`backend/tests/test_postgres_migration_017_rehearsal.py`](file:///C:/Users/rizvi/nexus/backend/tests/test_postgres_migration_017_rehearsal.py)
**CI Workflow Run**: [GitHub Actions Run #40836405737](https://github.com/rzvn6660/Nexus/actions/runs/40836405737)
**Final Verdict**: **GO (VERIFIED ON REAL POSTGRESQL 16 IN CI — READY FOR PR MERGE & STAGING ROLLOUT)**

---

> [!IMPORTANT]
> **STAGING INVARIANT PROTECTION & SAFETY STATUS**:
> 1. **Zero Changes to Staging**: Migration 017 has **NOT** been applied to the live staging database (`nexus_staging_db` on host `127.0.0.1:5433`). The staging database remains strictly at revision `016_phase1c2_tenant_scoped_customer_identity`.
> 2. **Tenant Data Untouched**: Staging tenant `Apex Specialty Commerce` (1,000 customers, 3,500 sales, 11,221 line items) was preserved completely intact.
> 3. **PostgreSQL 16 Verification Isolated to CI**: All real PostgreSQL 16 migration, index catalog, unique violation SQLSTATE `23505`, downgrade, and re-upgrade assertions were executed strictly inside the ephemeral GitHub Actions service container (`pgvector/pgvector:pg16`).

---

## 1. Executive Summary

Phase 1G.0 and Phase 1G.0.1 establish the authoritative migration readiness gate for Alembic migration `017_phase1f2_authoritative_ingestion_watermark`. This migration implements the relational storage and integrity guarantees required by the Phase 1F.2 Authoritative Ingestion Watermark architecture.

In Phase 1G.0, the schema design, static DDL, transaction lifecycles, and SQLite disposable rehearsals were completed. However, because local Docker was unavailable on the Windows host, the live PostgreSQL verification was placed under a **CONDITIONAL GO** gate pending real CI verification.

In Phase 1G.0.1, the complete implementation and dedicated rehearsal suite were packaged onto feature branch `feat/phase1g-watermark-migration-rehearsal` and submitted to the GitHub Actions CI pipeline. CI run **#40836405737** executed against an isolated `pgvector/pgvector:pg16` container with `REQUIRE_POSTGRES=true`. All 10 PostgreSQL migration 017 rehearsal tests passed, 54/54 PostgreSQL integration tests passed, and 1,413/1,413 backend tests passed.

With real PostgreSQL 16 catalog verification successfully established, the migration readiness verdict is upgraded to **GO**.

---

## 2. GitHub Actions CI Verification Evidence (PostgreSQL 16 Container)

### 2.1 Workflow Run Overview
- **Run ID**: `40836405737`
- **Run URL**: [https://github.com/rzvn6660/Nexus/actions/runs/40836405737](https://github.com/rzvn6660/Nexus/actions/runs/40836405737)
- **Head Commit**: `3cc91a13fa4358a5da983fdd82c8172c72b84ef9` (`fix(tests): update alembic head assertions in test_config and phase30 integration for revision 017`)
- **Workflow**: `CI/CD Pipeline` (`.github/workflows/ci.yml`)
- **Status**: **Success** (Conclusion: `success`)
- **Total Duration**: 3m 48s

### 2.2 CI Job Results Matrix

| Job Name | Environment / Service Container | Duration | Result | Key Steps Completed |
| :--- | :--- | :--- | :--- | :--- |
| **Frontend Build & Typecheck** | Node 20 (`ubuntu-latest`) | 35s | **PASS** | `npm ci`, `npm run typecheck`, `npm run build` |
| **Backend Test Suite & Smoke Verification** | Python 3.12 (`ubuntu-latest`) + `pgvector/pgvector:pg16` | 3m 27s | **PASS** | `alembic upgrade head`, PostgreSQL Integration Tests (`54 passed`), Backend Tests (`1413 passed`), Evaluation Benchmarks, Production Smoke Test |

### 2.3 Step-by-Step Backend Execution Log Analysis

1. **PostgreSQL Service Container Health**:
   - Container Image: `pgvector/pgvector:pg16`
   - Ports: `5432:5432` mapped to runner localhost
   - Health check: `pg_isready -U nexus_user -d nexus_test_db` verified healthy before runner steps commenced.
2. **Alembic Forward Migration Execution**:
   - Executed: `alembic upgrade head`
   - Successfully ran migration chain from `001_initial` through `016_phase1c2_tenant_scoped_customer_identity` to `017_phase1f2_authoritative_ingestion_watermark`.
3. **Live PostgreSQL Integration Tests Step**:
   - Executed:
     ```bash
     REQUIRE_POSTGRES=true \
     TEST_DATABASE_URL="postgresql+psycopg://nexus_user:nexus_password@localhost:5432/nexus_test_db" \
     pytest backend/tests/test_postgres_integration_phase30.py \
            backend/tests/test_postgres_migration_016_rehearsal.py \
            backend/tests/test_postgres_migration_017_rehearsal.py -v
     ```
   - **Result**: `54 passed in 13.97s`
   - All 10 tests in `test_postgres_migration_017_rehearsal.py` executed against live PostgreSQL 16 with zero skips.
4. **General Backend Test Suite**:
   - Executed:
     ```bash
     pytest backend/tests -v --ignore=backend/tests/test_postgres_migration_016_rehearsal.py \
                             --ignore=backend/tests/test_postgres_migration_017_rehearsal.py
     ```
   - **Result**: `1413 passed, 1 skipped in 97.79s`
5. **Benchmarks & Smoke Verification**:
   - Evaluation benchmark checks passed.
   - Production smoke verification passed.

---

## 3. PostgreSQL 16 Migration 017 Rehearsal Test Catalog

The rehearsal test suite [`backend/tests/test_postgres_migration_017_rehearsal.py`](file:///C:/Users/rizvi/nexus/backend/tests/test_postgres_migration_017_rehearsal.py) contains 10 rigorous, catalog-level test scenarios executed against PostgreSQL 16:

| Test ID | Test Function Name | PostgreSQL 16 Catalog Verification Performed | CI Result |
| :--- | :--- | :--- | :--- |
| **01** | `test_01_postgres_connection_and_environment_guard` | Queries `SELECT version();` and asserts engine dialect is `postgresql`. Enforces that `REQUIRE_POSTGRES=true` fails hard if PostgreSQL is unreachable. | **PASSED** |
| **02** | `test_02_postgres_alembic_chain_upgrade_to_017` | Queries `SELECT version_num FROM alembic_version;` on PostgreSQL to confirm the database head is exactly `017_phase1f2_authoritative_ingestion_watermark`. | **PASSED** |
| **03** | `test_03_postgres_table_columns_types_and_defaults` | Inspects `information_schema.columns` for `tenant_ingestion_watermarks`. Verifies all 13 columns, data types (`character varying`, `timestamp with time zone`, `boolean`, `json`), nullability, and default expressions. | **PASSED** |
| **04** | `test_04_postgres_foreign_key_constraints_and_cascades` | Queries `information_schema.table_constraints` and `referential_constraints`. Confirms FK to `businesses.id` has `delete_rule = 'CASCADE'` and FK to `ingestion_jobs.id` has `delete_rule = 'SET NULL'`. | **PASSED** |
| **05** | `test_05_postgres_indexes_and_partial_unique_index_catalog` | Inspects `pg_catalog.pg_indexes` for table `tenant_ingestion_watermarks`. Confirms all five secondary b-tree indexes exist, and verifies index `uq_tenant_watermarks_active_source` has definition matching `WHERE (is_active = true)`. | **PASSED** |
| **06** | `test_06_postgres_active_watermark_unique_rejection_sqlstate` | Inserts an active watermark `(tenant_A, source_1, is_active=true)`. Attempts to insert a second active watermark for the same tenant and source. Verifies PostgreSQL raises `IntegrityError` with SQLSTATE `23505` (`unique_violation`). | **PASSED** |
| **07** | `test_07_postgres_permitted_historical_inactive_records` | Inserts an active watermark and multiple superseded inactive watermarks (`is_active=false`) for the same tenant and source. Proves PostgreSQL permits multiple inactive audit records without collision. | **PASSED** |
| **08** | `test_08_postgres_cross_tenant_source_isolation` | Inserts active watermarks for `source_shopify` across two distinct tenants (`tenant_A` and `tenant_B`). Confirms cross-tenant source isolation operates without constraint collisions. | **PASSED** |
| **09** | `test_09_postgres_orm_reads_writes_and_rollback_preservation` | Exercises `TenantIngestionWatermark` ORM queries, updates, and rolls back an uncommitted transaction. Confirms PostgreSQL rolls back uncommitted watermark changes atomically. | **PASSED** |
| **10** | `test_10_postgres_downgrade_and_reupgrade_lifecycle` | Executes programmatic downgrade `017 -> 016` using Alembic `command.downgrade`. Confirms via `information_schema.tables` and `pg_indexes` that table and all indexes are dropped, and `alembic_version` rewinds to `016`. Then executes `command.upgrade` back to `017` and confirms complete catalog restoration. | **PASSED** |

---

## 4. Implementation Audit & Architectural Findings

Prior to migration authoring, all eight architectural and data integrity probes were audited and validated across the codebase:

| Audit Question | Investigation Finding | Architectural Implementation & Safeguard | Status |
| :--- | :--- | :--- | :--- |
| **1. Ingestion Source Scoping** | How are required sources configured and scoped per tenant? | In `WatermarkContract`, each watermark explicitly requires `business_id` (FK to `businesses.id`) and `source_id`. `WatermarkService.get_effective_tenant_watermark` supports passing `required_sources: list[str]`. If any required source lacks an active verified watermark, status is `incomplete_watermark_gap`. When omitted, it takes $\min(T_s)$ across all active verified sources recorded for that tenant. In `DataGatewayService`, `source_id` checks `dataset.schema_json.get("source_id")` before falling back to filename. | **VERIFIED** |
| **2. In-Flight / Failed Pipelines** | Can failed, partial, or in-flight ingestion incorrectly certify completeness? | **No.** Gate 1 in `WatermarkService.get_effective_tenant_watermark` queries `IngestionJob` for statuses `['PENDING', 'PROCESSING', 'FAILED', 'REQUIRES_REVIEW']`. If count $> 0$, it immediately halts evaluation with `status="incomplete_in_flight"`, `is_verified=False`, and returns `None` for the effective watermark. | **VERIFIED** |
| **3. Backfill & Refund Invalidation** | Does late-arriving data, refund, or correction invalidate the watermark? | **Yes.** In `DataGatewayService.commit_mapped_data`, the earliest incoming transaction date $\tau_{\min}$ is evaluated via `WatermarkService.detect_backfill_and_handle`. If $\tau_{\min} \le T_{\text{active}}$, `verification_status` transitions to `invalidated` with an explicit reason citing the date and triggering job ID. | **VERIFIED** |
| **4. Reactivation Prevention** | Can invalidated watermarks be reactivated without fresh verification? | **No.** `WatermarkService` contains no method to reactivate an invalidated watermark. A source can only become verified through `record_watermark(...)` with a newly certified contract, which marks the old watermark `is_active=False` and inserts a new verified entity. | **VERIFIED** |
| **5. Audit History Preservation** | Do historical audit records remain intact when a new certification is issued? | **Yes.** In `record_watermark(...)`, previous active watermarks are updated to `is_active=False`. Rows are **never deleted**. The entire trajectory of certified boundaries remains in `tenant_ingestion_watermarks` for compliance auditing. | **VERIFIED** |
| **6. Transaction Rollback Safety** | Does DB rollback also roll back watermark invalidation when ingestion fails? | **Yes.** `detect_backfill_and_handle` issues `session.flush()`, NOT `session.commit()`. If the surrounding ingestion job fails and triggers `db.rollback()`, the watermark status change in the session is rolled back atomically with the uncommitted sales records. | **VERIFIED** |
| **7. Identity Consistency** | Are tenant and source identifiers consistently validated? | **Yes.** `TenantIngestionWatermark.business_id` is a database foreign key to `businesses.id` with `ON DELETE CASCADE`. All ORM and query filters strictly isolate records by `business_id`. | **VERIFIED** |
| **8. Outcome Safety Invariant** | Can an unverified watermark ever be interpreted as proof of no purchase? | **No.** When `is_verified=False`, `CustomerOutcomeRecord.unverified_negative_outcome` is set to `True`, `is_followup_verified` is set to `False`, and an `UNVERIFIED OUTCOMES NOTICE` is logged. With `require_verified_watermark=True`, unverified follow-ups are censored (`is_censored=True`, `outcome_no_purchase=None`), preventing false churn bias. | **VERIFIED** |

---

## 5. Migration 017 DDL & Relational Specification

### 5.1 Migration Metadata
- **File**: [`backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py`](file:///C:/Users/rizvi/nexus/backend/alembic/versions/017_phase1f2_authoritative_ingestion_watermark.py)
- **Revision ID**: `017_phase1f2_authoritative_ingestion_watermark`
- **Parent Revision**: `016_phase1c2_tenant_scoped_customer_identity`
- **Offline SQL Generation**: Confirmed clean generation with `alembic upgrade 016:017 --sql` and `alembic downgrade 017:016 --sql`. Mock-connection inspection safety handled cleanly.

### 5.2 Relational Schema (`tenant_ingestion_watermarks`)

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

### 5.3 Indexes & Constraint Catalog

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

### 5.4 Static Forward SQL (`alembic upgrade 016:017 --sql`)

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

### 5.5 Static Rollback SQL (`alembic downgrade 017:016 --sql`)

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

## 6. Migration Readiness Verdict & Staging Rollout Authorization

### Final Verdict: **GO**

#### Authoritative Rationale:
1. **Real PostgreSQL 16 CI Rehearsal Green**: All 10 catalog-level rehearsal tests passed against an official `pgvector/pgvector:pg16` container under `REQUIRE_POSTGRES=true`. PostgreSQL 16 natively supports the DDL, foreign keys, cascade rules, composite indexes, and partial unique index (`WHERE (is_active = true)`).
2. **Duplicate Active Record Prevention Enforced**: Live testing confirmed that PostgreSQL engine raises SQLSTATE `23505` (`unique_violation`) when duplicate active watermarks are inserted, while permitting multiple historical inactive records for the same tenant and source.
3. **Clean Downgrade and Re-Upgrade Lifecycle**: Full transactional rollback `017 -> 016` and re-upgrade `016 -> 017` were verified on PostgreSQL 16.
4. **Zero Regressions in Engine**: 54/54 PostgreSQL integration tests passed; 1,413 backend tests passed; frontend build and typecheck passed; production smoke test passed.
5. **Staging Invariants Preserved**: Staging database `nexus_staging_db` remains completely untouched at revision `016` with all 1,000 customers and 3,500 sales intact.

---

## 7. Recommended Staging Rollout Runbook (Next Action)

To apply migration 017 to staging in Phase 1G.1:

```bash
# Step 1: Merge PR to main
# Open and merge PR for branch feat/phase1g-watermark-migration-rehearsal -> main

# Step 2: Fetch and pull latest main on staging host
git checkout main
git pull origin main

# Step 3: Run preflight inspection on staging PostgreSQL database
DATABASE_URL="postgresql+psycopg://nexus_staging_user:<password>@127.0.0.1:5433/nexus_staging_db" \
python -c "
import sqlalchemy as sa
engine = sa.create_engine('postgresql+psycopg://nexus_staging_user:<password>@127.0.0.1:5433/nexus_staging_db')
with engine.connect() as conn:
    res = conn.execute(sa.text('SELECT version_num FROM alembic_version;')).scalar()
    print('Current Staging Alembic Revision:', res)
    assert res == '016_phase1c2_tenant_scoped_customer_identity'
"

# Step 4: Take pre-migration staging database backup
pg_dump -h 127.0.0.1 -p 5433 -U nexus_staging_user -F c -b -v \
  -f "backups/nexus_staging_pre_017_$(date +%Y%m%d_%H%M%S).dump" nexus_staging_db

# Step 5: Execute Alembic migration on staging
DATABASE_URL="postgresql+psycopg://nexus_staging_user:<password>@127.0.0.1:5433/nexus_staging_db" \
alembic upgrade head

# Step 6: Post-migration verification
DATABASE_URL="postgresql+psycopg://nexus_staging_user:<password>@127.0.0.1:5433/nexus_staging_db" \
python -c "
import sqlalchemy as sa
engine = sa.create_engine('postgresql+psycopg://nexus_staging_user:<password>@127.0.0.1:5433/nexus_staging_db')
with engine.connect() as conn:
    rev = conn.execute(sa.text('SELECT version_num FROM alembic_version;')).scalar()
    assert rev == '017_phase1f2_authoritative_ingestion_watermark'
    print('Staging migration verified at head:', rev)
"
```
