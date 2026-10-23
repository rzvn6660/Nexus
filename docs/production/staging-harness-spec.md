# NEXUS — Isolated Local Staging Recovery Harness Design Specification

- **Document Version**: 1.1 (PROPOSED SPECIFICATION — SAFETY-AUDITED & UNIMPLEMENTED)
- **Authoritative Date**: 2026-10-23
- **Status**: Revised Draft for Product-Owner Review
- **Operational Target**: Isolated Local Multi-Container Staging Environment
- **Budgetary Constraint**: ₹0 Incremental Infrastructure Cost

> [!IMPORTANT]
> **Specification & Non-Execution Notice**:
> This document is an architectural and operational design specification. **No staging environment, container stack, script modification, database migration, or recovery test has been executed or provisioned as part of this specification.** All proposed behaviors, scripts, and Compose files described herein are design proposals awaiting explicit product-owner approval.

---

## 1. Purpose and Scope

### 1.1 Objective
The purpose of this specification is to define a safe, zero-cost (₹0), fully isolated local staging recovery harness for the NEXUS platform. This harness will enable engineering to validate the actual coordinated backup and restore scripts ([`scripts/backup_nexus_coordinated.sh`](../../scripts/backup_nexus_coordinated.sh) and [`scripts/restore_nexus_coordinated.sh`](../../scripts/restore_nexus_coordinated.sh)) against real multi-container services, persistent volumes, and non-trivial synthetic datasets.

### 1.2 Boundary with Existing CI Verification
On October 23, 2026, the dedicated manual GitHub Actions workflow [`.github/workflows/backup-restore-drill.yml`](../../.github/workflows/backup-restore-drill.yml) successfully passed on ephemeral CI runner infrastructure ([Run #39988258994](https://github.com/rzvn6660/Nexus/actions/runs/39988258994)). That run certified:
1. Compatibility with PostgreSQL 16.15 client tools and `pgvector/pgvector:pg16`.
2. Python-level restore mechanics, vector queries (`<->`), JSONB fidelity, sequence alignment, and referential constraints.
3. Fail-closed cleanup gate verification leaving zero leftover databases or seeded tenant records.

### 1.3 Production Disaster Recovery Non-Certification
As documented in [`docs/production/backup-recovery.md`](backup-recovery.md#L596-L609), **the successful CI mechanics drill does NOT certify production or staging disaster recovery readiness**. The CI run executed inside an ephemeral GitHub Actions container sandbox on a single process without testing:
- Persistent host block durability across host reboots.
- POSIX file ownership (`appuser:appuser`, UID/GID `1000:1000`) across persistent Docker volume mounts.
- Multi-process service quiescence with concurrent API web workers (`WEB_CONCURRENCY=2`) and the dedicated continuous scheduler worker (`nexus_scheduler_prod`).
- True disaster recovery: total loss and restoration of physical database volumes.
- Off-host backup replication to secure remote secondary storage.

The proposed local staging harness bridges the gap between ephemeral CI mechanics and full production disaster recovery certification without incurring cloud infrastructure costs.

---

## 2. Current Implementation Constraints & Audit Findings

A read-only safety audit of the existing recovery scripts, Compose configurations, and backend source files revealed critical constraints that currently prevent running the scripts directly against a staging environment.

### 2.1 Audited Entities and Source Verification

| Entity | Audited Source Location | Current Production Value | Staging Impact if Run Directly |
|---|---|---|---|
| **Database Target** | [`scripts/backup_nexus_coordinated.sh:L89-L90`](../../scripts/backup_nexus_coordinated.sh#L89-L90)<br>[`scripts/restore_nexus_coordinated.sh:L190-L200`](../../scripts/restore_nexus_coordinated.sh#L190-L200) | `nexus_db` (user `nexus_user`) | **CRITICAL**: Hardcoded literal; restore executes `dropdb -U nexus_user nexus_db` and `createdb` |
| **Tenant Data Volume** | [`scripts/backup_nexus_coordinated.sh:L97`](../../scripts/backup_nexus_coordinated.sh#L97)<br>[`scripts/restore_nexus_coordinated.sh:L209`](../../scripts/restore_nexus_coordinated.sh#L209) | `nexus_backend_data` | **CRITICAL**: Hardcoded literal; restore mounts `nexus_backend_data` and executes `rm -rf /data/tenants/*` |
| **Redis Persistence Volume** | [`scripts/backup_nexus_coordinated.sh:L127`](../../scripts/backup_nexus_coordinated.sh#L127)<br>[`scripts/restore_nexus_coordinated.sh:L242`](../../scripts/restore_nexus_coordinated.sh#L242) | `nexus_redis_prod_data` | **CRITICAL**: Hardcoded literal; restore mounts `nexus_redis_prod_data` and executes `rm -rf /data/*` |
| **Compose Project & File** | [`scripts/backup_nexus_coordinated.sh:L37`](../../scripts/backup_nexus_coordinated.sh#L37)<br>[`scripts/restore_nexus_coordinated.sh:L21`](../../scripts/restore_nexus_coordinated.sh#L21) | `docker-compose.prod.yml`<br>(project default: `nexus`) | Operates against default project containers (`backend`, `scheduler`, `redis`, `postgres`), colliding with production/dev |
| **Container User & Ownership** | [`infra/docker/Dockerfile.backend:L43-L47`](../../infra/docker/Dockerfile.backend#L43-L47)<br>[`scripts/restore_nexus_coordinated.sh:L228`](../../scripts/restore_nexus_coordinated.sh#L228) | User `appuser` (UID 1000, GID 1000)<br>`chown -R 1000:1000 /data` | Application executes as non-root user `appuser` (1000:1000); permissions must remain strictly aligned |
| **Dedicated Test Gate DB Target** | [`backend/tests/test_backup_restore_phase32c.py:L449-L453`](../../backend/tests/test_backup_restore_phase32c.py#L449-L453) | `nexus_test_db` | Pytest fail-closed guard strictly refuses to execute live restore drill against any DB other than `nexus_test_db` |

### 2.2 Safety Finding: Direct Script Execution is Unsafe
> [!CAUTION]
> **Severe Data Hazard**:
> Because volume names (`nexus_backend_data`, `nexus_redis_prod_data`) and the database name (`nexus_db`) are hardcoded string literals in [`scripts/backup_nexus_coordinated.sh`](../../scripts/backup_nexus_coordinated.sh) and [`scripts/restore_nexus_coordinated.sh`](../../scripts/restore_nexus_coordinated.sh), executing these scripts against an unparameterized staging stack would **bypass staging volumes and overwrite or destroy existing development or production volumes**.
>
> Introducing parameterization with strict multi-factor fail-closed validation is a mandatory prerequisite before any staging execution.

### 2.3 Distinction: Facts vs. Proposed Controls vs. Unknowns

```text
[ SOURCE-VERIFIED FACTS ]
├── Database user is 'nexus_user' across docker-compose.yml, docker-compose.prod.yml, .env.example, and config.py.
├── Database name is 'nexus_db' in production and development; test guard requires 'nexus_test_db'.
├── Container user is 'appuser' with UID 1000 and GID 1000 in infra/docker/Dockerfile.backend.
├── Existing restore script explicitly enforces 'chown -R 1000:1000 /data' (line 228).
├── Backup script trap restarts quiesced services on error (lines 58–73).
├── Restore script trap intentionally leaves mutating services stopped on error to prevent split-state mutation (lines 117–137).
├── Redis runs with '--appendonly yes' in docker-compose.prod.yml; restore script wipes '/data/*' before unpacking dump.rdb.
└── Dedicated test suite 'test_backup_restore_phase32c.py' mandates source DB name 'nexus_test_db'.

[ PROPOSED CONTROLS (THIS SPECIFICATION — UNIMPLEMENTED) ]
├── Dual-gate staging invocation requiring BOTH '--staging' CLI flag AND 'NEXUS_STAGING_MODE=true'.
├── Target container and volume Docker label attestation ('com.docker.compose.project == nexus-staging').
├── Strict fail-closed blacklist rejecting production/development names in staging mode.
├── Reverse guard in production mode rejecting staging parameters.
├── Dedicated staging Compose stack 'infra/staging/docker-compose.staging.yml' on offset ports (5433, 6380, 8001, 3001).
└── Safe bash quoted array expansion ("${CMD[@]}") eliminating eval and word-splitting hazards.

[ UNKNOWNS REQUIRING CONTROLLED LIVE TESTING ]
├── Uvicorn worker behavior when SIGTERM is received during active multipart upload in Docker Desktop.
├── Host I/O throughput and tar archive latency under Windows/macOS filesystem translation layers (WSL2 / virtiofs).
└── Redis memory reload latency when switching from cleared AOF state to restored dump.rdb.
```

---

## 3. Isolation Architecture

The proposed staging harness is physically and logically separated from all existing development and production containers, networks, volumes, and ports.

```text
                         Host / Operator Environment
                                      │
       ┌──────────────────────────────┴──────────────────────────────┐
       ▼                                                             ▼
┌─────────────────────────────────────────┐     ┌─────────────────────────────────────────┐
│     Existing Dev/Prod Environments      │     │      Isolated Staging Harness           │
│                                         │     │                                         │
│  Projects: nexus (dev), nexus-prod      │     │  Project: -p nexus-staging              │
│  Ports: 5432, 6379, 8000, 3000          │     │  Ports: 5433, 6380, 8001, 3001          │
│  Volumes:                               │     │  Compose: docker-compose.staging.yml    │
│  - postgres_data                        │     │                                         │
│  - nexus_postgres_prod_data             │     │  Isolated Staging Volumes:              │
│  - nexus_backend_data                   │     │  - nexus_postgres_staging_data          │
│  - nexus_redis_prod_data                │     │  - nexus_backend_staging_data           │
│                                         │     │  - nexus_redis_staging_data             │
└─────────────────────────────────────────┘     └────────────────────┬────────────────────┘
                                                                     │
                                                                     ▼
                                                ┌─────────────────────────────────────────┐
                                                │    Independent Host Backup Storage      │
                                                │  Path: ./backups/staging/               │
                                                │  (Completely detached from volumes)     │
                                                └─────────────────────────────────────────┘
```

### 3.1 Proposed Configuration: `infra/staging/docker-compose.staging.yml`
The proposed staging Compose file defines an isolated replica of the production multi-container architecture:

1. **Service `postgres`**:
   - Image: `pgvector/pgvector:pg16`
   - Container Name: `nexus_postgres_staging`
   - Port Mapping: `127.0.0.1:5433:5432` (strictly bound to localhost; offsets production 5432)
   - Volume: `nexus_postgres_staging_data:/var/lib/postgresql/data`
   - Environment: `POSTGRES_USER=nexus_staging_user`, `POSTGRES_DB=nexus_staging_db`, disposable password.
   - Healthcheck: `pg_isready -U nexus_staging_user -d nexus_staging_db`
2. **Service `redis`**:
   - Image: `redis:7-alpine`
   - Container Name: `nexus_redis_staging`
   - Port Mapping: `127.0.0.1:6380:6379` (offsets production 6379)
   - Command: `redis-server --appendonly yes --appendfsync everysec --maxmemory 256mb --maxmemory-policy noeviction`
   - Volume: `nexus_redis_staging_data:/data`
3. **Service `backend`**:
   - Build: Multi-stage Dockerfile ([`infra/docker/Dockerfile.backend`](../../infra/docker/Dockerfile.backend))
   - Container Name: `nexus_backend_staging`
   - User: `appuser` (UID 1000, GID 1000)
   - Port Mapping: `127.0.0.1:8001:8000` (offsets production 8000)
   - Environment:
     - `APP_ENV=staging`
     - `DEBUG=false`
     - `WEB_CONCURRENCY=2` (validates multi-worker quiescence)
     - `CONTINUOUS_SCHEDULER_AUTOSTART=false`
     - `DATABASE_URL=postgresql+psycopg://nexus_staging_user:nexus_staging_password@postgres:5432/nexus_staging_db`
     - `REDIS_URL=redis://redis:6379/0`
     - `REQUIRE_POSTGRES=true`
     - `LLM_ALLOW_EXTERNAL_CALLS=false`
   - Volume: `nexus_backend_staging_data:/app/data`
4. **Service `scheduler`**:
   - Container Name: `nexus_scheduler_staging`
   - User: `appuser` (UID 1000, GID 1000)
   - Command: `["python", "-m", "app.scheduler_runner"]`
   - Environment: `CONTINUOUS_SCHEDULER_ENABLED=true`, `CONTINUOUS_SCHEDULER_AUTOSTART=true`
   - Volume: `nexus_backend_staging_data:/app/data`
5. **Networks & Volumes**:
   - Network: `nexus-staging-network` (bridge, isolated from `nexus-network` and `nexus-prod-network`).
   - Volumes: Explicitly named `nexus_postgres_staging_data`, `nexus_backend_staging_data`, `nexus_redis_staging_data`.

### 3.2 Independent Backup Storage Architecture
- Backup directory: Located on the host filesystem at `./backups/staging/` (or operator-configured path).
- **Separation Guarantee**: Backup files reside outside Docker's volume storage (`/var/lib/docker/volumes`).
- **Disaster Simulation Capability**: The harness tests recovery from catastrophic volume deletion (`docker volume rm nexus_postgres_staging_data nexus_backend_staging_data`) while backup archives remain completely untouched and intact on the host.

---

## 4. Script Parameterization Contract

To safely support both production and staging without maintaining divergent script forks, [`scripts/backup_nexus_coordinated.sh`](../../scripts/backup_nexus_coordinated.sh) and [`scripts/restore_nexus_coordinated.sh`](../../scripts/restore_nexus_coordinated.sh) must implement a strict parameterization contract.

### 4.1 Production-Compatible Parameter Contract Table

| Parameter | Environment Variable | Default (Production-Compatible) | Audited Source Grounding | Proposed Staging Value | Validation Guard |
|---|---|---|---|---|---|
| **Compose Project** | `COMPOSE_PROJECT_NAME` | `nexus` (or directory name) | Default Docker Compose directory project naming | `nexus-staging` | Matches `^[a-zA-Z0-9_-]+$` |
| **Compose File** | `COMPOSE_FILE` | `docker-compose.prod.yml` | [`backup:L37`](../../scripts/backup_nexus_coordinated.sh#L37), [`restore:L21`](../../scripts/restore_nexus_coordinated.sh#L21) | `infra/staging/docker-compose.staging.yml` | File exists; passes `docker compose config` |
| **Database Name** | `POSTGRES_DB` | `nexus_db` | [`backup:L89`](../../scripts/backup_nexus_coordinated.sh#L89), [`restore:L190`](../../scripts/restore_nexus_coordinated.sh#L190), [`compose.prod:L32`](../../docker-compose.prod.yml#L32) | `nexus_staging_db` | Matches `^[a-zA-Z0-9_]{1,63}$` |
| **Database User** | `POSTGRES_USER` | `nexus_user` | [`compose:L12`](../../docker-compose.yml#L12), [`compose.prod:L30`](../../docker-compose.prod.yml#L30), [`.env.example:L32`](../../.env.example#L32) | `nexus_staging_user` | Matches `^[a-zA-Z0-9_]{1,63}$` |
| **Tenant Data Volume** | `DATA_VOLUME` | `nexus_backend_data` | [`backup:L97`](../../scripts/backup_nexus_coordinated.sh#L97), [`restore:L209`](../../scripts/restore_nexus_coordinated.sh#L209), [`compose.prod:L209`](../../docker-compose.prod.yml#L209) | `nexus_backend_staging_data` | Must exist; cannot equal prod volume if in staging |
| **Redis Data Volume** | `REDIS_VOLUME` | `nexus_redis_prod_data` | [`backup:L127`](../../scripts/backup_nexus_coordinated.sh#L127), [`restore:L242`](../../scripts/restore_nexus_coordinated.sh#L242), [`compose.prod:L213`](../../docker-compose.prod.yml#L213) | `nexus_redis_staging_data` | Must exist; cannot equal prod volume if in staging |
| **Backup Root** | `BACKUP_ROOT` | `/var/backups/nexus` | [`backup:L23`](../../scripts/backup_nexus_coordinated.sh#L23), [`restore:L20`](../../scripts/restore_nexus_coordinated.sh#L20) | `./backups/staging` | Must not be empty, root, or contain `..` |
| **Staging Mode Guard** | `NEXUS_STAGING_MODE` | `false` | Baseline production guard | `true` | Boolean flag enforcing strict cross-check safety |

### 4.2 Proposed Dual-Gate Staging Validation Rules (Unimplemented)
An environment variable alone (`NEXUS_STAGING_MODE=true`) is **insufficient protection** against terminal session pollution or accidental misconfiguration. The proposed parameterization enforces dual-gate attestation:

1. **Dual Invocation Requirement**:
   Entering staging mode requires **BOTH**:
   - Explicit CLI flag: `--staging`
   - Explicit environment variable: `NEXUS_STAGING_MODE=true`
   If only one is set, the script immediately aborts with an informative error.

2. **Pre-Execution Attestation Checks (Staging Mode)**:
   When running with `--staging` and `NEXUS_STAGING_MODE=true`:
   - **Compose Project**: Must equal `nexus-staging`.
   - **Compose File**: Must resolve to a path containing `staging`.
   - **Container Label Attestation**: Queries `docker inspect` on the target containers to verify label `com.docker.compose.project == "nexus-staging"`.
   - **Target Database Blacklist**: If `POSTGRES_DB` is `nexus_db`, `postgres`, `template1`, or `nexus_test_db`, execution immediately halts with exit code 1.
   - **Target Volume Blacklist**: If `DATA_VOLUME` matches `nexus_backend_data` or `REDIS_VOLUME` matches `nexus_redis_prod_data`, execution immediately halts with exit code 1.
   - **Volume Label Verification**: Inspects target volumes via `docker volume inspect` to confirm label `com.docker.compose.project == "nexus-staging"`.
   - **Backup Directory Canonicalization**:
     - The path must be canonicalized to resolve all relative path components (`.`, `..`) and symlinks before any comparisons are performed.
     - When the leaf backup directory does not yet exist, scripts must not assume non-portable flags (such as GNU `realpath -m`) exist across different OS environments (e.g., minimal Alpine, macOS, or custom host shells). Instead, scripts must use a portable canonicalization strategy (such as creating the directory beforehand via `mkdir -p` or resolving the closest existing parent directory using `pwd -P` and appending the validated basename).
     - Paths equal to, or nested beneath, forbidden directories must be rejected:
       - Docker volume storage roots (e.g. `/var/lib/docker/volumes`).
       - Application and container data directories (e.g. `/data`, `/app/data`, `./backend/data`).
       - Version control metadata (e.g. `.git`).
       - System directories (e.g. `/`, `/bin`, `/etc`, `/usr`, `/root`).
     - **Fail-Closed Guard**: If path resolution, canonicalization, or validation fails, or if the canonical path cannot be definitively validated as external to data volumes, execution must immediately abort with exit code 1.

3. **Reverse Guard (Production Mode)**:
   When `--staging` is NOT passed:
   - If `NEXUS_STAGING_MODE=true` is detected, or if any parameter contains `staging`, the script immediately fails closed and refuses to execute to prevent mixed-environment operations.

4. **Safe Shell Argument Handling**:
   All Docker and Compose commands must use safely quoted array expansion:
   ```bash
   compose_args=(-f "${COMPOSE_FILE}")
   if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
       compose_args+=(-p "${COMPOSE_PROJECT_NAME}")
   fi
   docker compose "${compose_args[@]}" ...
   ```
   **Never use `eval` or dynamic unquoted command-string expansion.**

---

## 5. Recovery & Destructive-Operation Safeguards

Destructive operations (dropping databases, unlinking files, stopping containers) must be rigorously bounded:

### 5.1 Exact Target Identity Verification
Prior to executing `dropdb` or deleting tenant files, [`scripts/restore_nexus_coordinated.sh`](../../scripts/restore_nexus_coordinated.sh) must verify the exact target database identity against PostgreSQL's system catalog (`pg_database`):

- **Target vs. Maintenance Connection Distinction**:
  Administrative commands like `dropdb` and backend connection termination run through an administrative connection to the maintenance database (`-d postgres`). A session connection to `postgres` must **never** be mistaken for verification of the target database itself (where `SELECT current_database();` merely confirms connectivity to the maintenance database).
- **Catalog Verification Requirement**:
  The pre-restore validation must explicitly query the catalog using the intended staging database variable (`${POSTGRES_DB}`):
  ```sql
  SELECT datname FROM pg_database WHERE datname = 'nexus_staging_db';
  ```
  The script must verify that:
  1. The target database name strictly matches the expected staging naming convention (`^nexus_.*staging.*$`).
  2. The target database is not on the prohibited blacklist (`nexus_db`, `postgres`, `template1`, `nexus_test_db`).
- **Fail-Closed Behavior**:
  If the target database cannot be queried, returns unexpected results, is missing when required, or triggers any connection or query errors, the restore script must **fail closed immediately with exit code 1** before issuing any `dropdb`, `createdb`, or file deletion commands.
- **SQL Injection Safety Contract**:
  SQL quoting and injection-safe parameter construction (preventing arbitrary SQL execution via `${POSTGRES_DB}`) must be rigorously addressed and implemented during Phase 1.

### 5.2 Preservation of Existing Restore Guards
The staging harness retains all existing restore safety mechanisms:
- Mandatory `--confirm-destructive-restore` flag.
- Typed `CONFIRM-RESTORE` confirmation prompt if running in an interactive terminal.
- Strict timestamp regex (`^[0-9]{8}_[0-9]{6}$`).
- Preflight archive validation (SHA-256 sidecars, `PGDMP` header magic, tar header inspection) **before** stopping containers or touching databases.
- Staged tenant file extraction (`/data/staging_<TIMESTAMP>`) before swap.
- Strict POSIX ownership reset: `chown -R 1000:1000 /data` matching container user `appuser` ([`infra/docker/Dockerfile.backend:L43`](../../infra/docker/Dockerfile.backend#L43)).

### 5.3 Redis Persistence & Recovery Semantics
- **Audited Configuration**: In [`docker-compose.prod.yml:L60-66`](../../docker-compose.prod.yml#L60-L66), Redis runs with `--appendonly yes`, `--appendfsync everysec`, and volume `nexus_redis_prod_data:/data`.
- **Operational Reality**: Redis maintains both AOF and RDB persistence. On startup, Redis **preferentially loads AOF files over `dump.rdb`** if AOF files are present. If stale AOF files remain in the data directory, Redis will ignore the restored snapshot `dump.rdb`.
- **Preserved Restore Mechanic**: [`scripts/restore_nexus_coordinated.sh:L246`](../../scripts/restore_nexus_coordinated.sh#L246) safely purges `/data/*` in the Redis volume before extracting `nexus_redis_${TIMESTAMP}.tar.gz` (`dump.rdb`). This ensures Redis starts from the restored snapshot cleanly.
- **Harness Verification Requirement**: The recovery harness must test the restore result (e.g. verifying key presence or token revocation state) before declaring recovery successful.

### 5.4 Asymmetric Error Handling & Failure Safeguards
The repository implements deliberate asymmetric error handling between backup and restore:
- **Backup Failure**: [`scripts/backup_nexus_coordinated.sh:L58-L73`](../../scripts/backup_nexus_coordinated.sh#L58-L73) traps errors, removes incomplete run artifacts (`rm -f ${DB_BACKUP} ...`), dispatches an alert, and **restarts quiesced services** (`docker compose start backend scheduler`) to maintain platform availability.
- **Restore Failure**: [`scripts/restore_nexus_coordinated.sh:L117-L137`](../../scripts/restore_nexus_coordinated.sh#L117-L137) traps errors, dispatches a `RESTORE_SPLIT_STATE` alert, and **intentionally leaves mutating services stopped**. Automatically restarting services after a failed restore is strictly avoided, because starting application workers against a dropped, partially restored, or unsynchronized database causes severe data corruption.
- **Harness Cleanup Restriction**: Future test harness automation must confine cleanup strictly to verified disposable staging resources (`nexus-staging`), and must **never** automatically restart an application in an unverified state.

### 5.5 Non-Destruction of Existing Volumes
Under no circumstances shall the harness script issue `docker volume rm` against unconfirmed volumes. Destruction testing in staging is strictly confined to explicitly named staging volumes:
```bash
docker volume rm nexus_postgres_staging_data nexus_backend_staging_data nexus_redis_staging_data
```

---

## 6. Acceptance and Evidence Matrix

| # | Domain | Verification Requirement | Test Method | Expected Evidence | Pass/Fail Gate Criteria | Pre-Run Statically Checkable? |
|---|---|---|---|---|---|:---:|
| **1** | **Database & Engine** | PostgreSQL 16 + pgvector availability | `SELECT version();` and `SELECT extname FROM pg_extension;` | `PostgreSQL 16.x`, extension `vector` active | Exact PostgreSQL 16, pgvector loaded | **YES** (via Compose definition) |
| **2** | **Strict Environment** | Mandatory fail-closed settings | Inspect container environment variables | `REQUIRE_POSTGRES=true`, `LLM_ALLOW_EXTERNAL_CALLS=false` | Zero external LLM calls, zero mock fallbacks | **YES** (via Compose definition) |
| **3** | **Dedicated Test Gate** | Execution of dedicated backup/restore test suite | Run `pytest backend/tests/test_backup_restore_phase32c.py` | Pytest console output | Exactly 0 failed, 0 skipped | NO (Requires running containers & `nexus_test_db`) |
| **4** | **Schema & Constraints** | Full table schema, sequences, and foreign keys | Alembic migration + restore dump | All tables present, sequence PKs preserved, FK violations raise `IntegrityError` | 100% schema parity between source and restored DB | NO (Requires running containers) |
| **5** | **Vector Query Fidelity** | Vector embeddings & similarity search | SQL query with `<->` operator on restored database | Cosine/L2 distance query returns expected scalar float | Query succeeds; distance within `1e-5` of expected | NO (Requires running containers) |
| **6** | **Tenant Storage Audit** | Referential consistency between DB and disk | Run `python scripts/reconcile_storage.py` on restored volume | Console audit summary report | `missing_files: 0`, `orphan_files: 0`, `is_consistent: true` | NO (Requires running containers) |
| **7** | **Filesystem Permissions** | Non-root container security | Container inspection of `/app/data` | Ownership `1000:1000` (`appuser:appuser`), permissions `755` dirs, `644` files | Zero `root:root` files in tenant directories | NO (Requires running containers) |
| **8** | **Service Quiescence** | Multi-worker and scheduler graceful stop | Execute `backup_nexus_coordinated.sh` under synthetic API load | Container logs show clean SIGTERM; zero active queries in `pg_stat_activity` | Services stop cleanly; zero in-flight data corruption | NO (Requires running containers) |
| **9** | **Redis Recovery** | Persistence reload and clean state | Restart Redis after restore; inspect keys via `redis-cli` | Keys present; AOF rewritten from restored RDB | Expected keys intact; zero stale AOF override | NO (Requires running containers) |
| **10** | **Volume Loss Disaster** | Recovery from total volume wipe | Stop stack, delete staging volumes, recreate, execute restore | Restored services pass `/api/health/ready` probe; all data restored | HTTP 200 on health probe; all synthetic records intact | NO (Requires running containers) |
| **11** | **Teardown & Cleanup** | Safe staging teardown | Execute `docker compose -p nexus-staging down -v` | Docker volume list shows staging volumes purged | Zero leftover staging containers, networks, or volumes | NO (Requires running containers) |

---

## 7. Phased Execution Plan

Execution of the staging recovery harness must follow a strict, gated, multi-phase plan:

```mermaid
graph TD
    P0[Phase 0: Spec Review & Owner Approval] --> P1[Phase 1: Safe Script Parameterization]
    P1 --> P2[Phase 2: Staging Compose Configuration]
    P2 --> P3[Phase 3: Synthetic Backup & Restore Drill]
    P3 --> P4[Phase 4: Disaster Loss Recovery & Audit Review]
```

### Phase 0: Specification Review & Owner Approval (CURRENT)
- **Deliverable**: This specification document ([`docs/production/staging-harness-spec.md`](staging-harness-spec.md)).
- **Action**: Product-owner review and explicit approval of architectural parameters, safety rules, and validation criteria.
- **Strict Limitation**: No implementation, script modification, or container execution is authorized in Phase 0.

### Phase 1: Safe Script Parameterization
- **Deliverable**: Non-breaking PR parameterizing [`scripts/backup_nexus_coordinated.sh`](../../scripts/backup_nexus_coordinated.sh) and [`scripts/restore_nexus_coordinated.sh`](../../scripts/restore_nexus_coordinated.sh).
- **Validation**: Static bash validation, linting (`shellcheck`), and automated regression tests verifying that default production behavior is 100% preserved.

### Phase 2: Isolated Staging Compose Configuration & Preflight
- **Deliverable**: Creation of `infra/staging/docker-compose.staging.yml` and disposable environment configuration `.env.staging`.
- **Validation**: `docker compose -f infra/staging/docker-compose.staging.yml config` preflight check confirming port offsets, volume naming, and service boundaries.

### Phase 3: Synthetic-Data Backup & Restore Drill
- **Deliverable**: Automated seeding of synthetic multi-tenant financial datasets, execution of coordinated backup, verification of archives and sidecars.
- **Validation**: Execution of coordinated restore into staging stack; validation of database, pgvector, Redis state, and storage reconciliation.

### Phase 4: Disaster Volume Loss Recovery & Review
- **Deliverable**: Simulation of total volume loss (`docker volume rm`), execution of cold restore from host backup directory, healthcheck verification.
- **Validation**: Final evidence audit report presented to product owner.

---

## 8. Known Limitations & Operational Realities

1. **Host Durability vs. Ephemeral Containers**:
   Testing on a local workstation (e.g., Docker Desktop on Windows/macOS) exercises container filesystem drivers (WSL2 / Hyper-V / virtiofs), which behave differently from Linux production bare-metal or cloud block devices (AWS EBS / NVMe).
2. **Off-Host Replication Gap**:
   This staging harness verifies local backup creation and restoration. It does **not** test automated off-host replication to remote object stores (AWS S3, Google Cloud Storage). Off-host backup sync remains an unverified Roadmap item.
3. **Scale & Lock Contention Limits**:
   Synthetic staging datasets (~10 MB to 100 MB) validate schema correctness and referential integrity, but do not simulate multi-hour `pg_dump` locks, gigabyte-scale transfer I/O bottlenecks, or network partition timeouts.
4. **Non-Certification Statement**:
   Successful execution of this local staging harness proves software and recovery script mechanics. It **does not constitute legal or operational certification of production disaster recovery readiness**. A live drill on production-grade infrastructure remains mandatory prior to accepting commercial production workloads.

---

## 9. Decision Log (Owner Approvals Required)

The following architectural decisions require explicit product-owner approval prior to proceeding to Phase 1:

| # | Architectural Decision | Proposed Recommendation | Risk / Tradeoff | Approval Status |
|---|---|---|---|:---:|
| **D-01** | **Port Offsets** | Use `5433` (Postgres), `6380` (Redis), `8001` (Backend API), `3001` (Frontend) | Eliminates port collisions with local development; requires operator awareness | **PENDING REVIEW** |
| **D-02** | **Script Parameterization Approach** | Parameterize existing production scripts via environment variables rather than maintaining a separate staging fork; default `POSTGRES_USER` to `nexus_user` | Preserves single source of truth for disaster recovery logic; requires strict fail-closed validation | **PENDING REVIEW** |
| **D-03** | **Dual-Gate Staging Guard** | Require BOTH `--staging` CLI flag AND `NEXUS_STAGING_MODE=true` | Eliminates accidental execution from session pollution; fails closed if misconfigured | **PENDING REVIEW** |
| **D-04** | **Synthetic Seeding Scope** | Generate 2 synthetic organizations, 3 businesses, 5 CSV datasets (< 10 MB), and 100 vector chunks | Sufficient to prove schema, foreign keys, vectors, and storage reconciliation at ₹0 cost | **PENDING REVIEW** |
| **D-05** | **Backup Directory Location** | Place staging backup archives in host directory `./backups/staging/` | Outside container volume lifecycle; enables testing total volume loss recovery | **PENDING REVIEW** |
| **D-06** | **Dedicated Test Gate Database Strategy** | **Option A**: Provision `nexus_test_db` alongside `nexus_staging_db` in the staging container to satisfy the test guard without code changes.<br>**Option B**: Submit a separate PR parameterizing the test's source database guard under strict staging mode. | Option A requires zero test code modifications; Option B requires modifying test code but keeps a single database in staging | **PENDING REVIEW** |
| **D-07** | **Redis Post-Restore Test Scope** | Verify Redis snapshot restoration by asserting key existence and testing rate-limit token revocation persistence | Ensures restored `dump.rdb` is actively serving data rather than relying solely on container healthchecks | **PENDING REVIEW** |
