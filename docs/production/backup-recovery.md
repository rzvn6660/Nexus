# NEXUS Database & Persistent Storage Backup & Disaster Recovery Guide

**Document Version**: 2.0  
**Phase**: Phase 31B — Production Infrastructure Hardening  
**Classification**: Operational Runbook  

---

## 1. Overview & Operational Scope

This document specifies standard operating procedures for data persistence, scheduled backups, point-in-time recovery, schema rollback, and volume integrity validation for the **NEXUS Agentic Business Intelligence Platform**.

NEXUS stores two distinct, interdependent categories of production data:
1. **Relational & Vector Database State (PostgreSQL 16 + pgvector)**: Organizations, user accounts, business profiles, ingested business entities (Sales, Products, Customers, Items, Expenses, Inventory), causal graph relationships, knowledge base chunks, and vector embeddings.
2. **Raw Tenant Files & Dataset Storage (Filesystem Volume)**: Uploaded CSV/Excel datasets, profiling snapshots, and structured data files under `/app/data/tenants/<organization_id>/<business_id>/<dataset_id>/<clean_name>`.

> [!IMPORTANT]
> **Operational Consistency Requirement & Non-Atomicity Disclosure**:
> Database metadata records in `uploaded_datasets` store relative filesystem paths in the `storage_key` column (e.g., `data/tenants/<org>/<biz>/<dataset>/<file>.csv`). **Database backups and tenant file backups must be coordinated with synchronized timestamps** to prevent dangling database references (metadata with missing disk files) or orphaned disk files (files without database records).
>
> POSIX filesystem writes and PostgreSQL RDBMS transactions **do not share a two-phase commit (2PC) coordinator**. The platform mitigates this via an application-level write-then-commit pattern with automatic file unlink on database rollback, supported by operational reconciliation procedures.

> [!NOTE]
> **Manual / Operator Execution Scope**:
> All procedures documented herein are **manual operational runbooks and host-level shell scripts** intended for system administrators or host cron schedulers. NEXUS does **not** feature an internal, self-driving automated backup daemon. All backup execution must be operator-configured, monitored, and tested.

---

## 2. Persistence Architecture

### 2.1 Production Storage Topography

In Docker Compose and containerized production environments (`docker-compose.prod.yml`):

| Volume Name | Container Mount Path | Target Service(s) | Contents |
|---|---|---|---|
| `nexus_postgres_prod_data` | `/var/lib/postgresql/data` | `postgres` | PostgreSQL 16 cluster, WAL logs, relational tables, pgvector indexes |
| `nexus_backend_data` | `/app/data` | `backend`, `scheduler` (future) | Raw tenant file uploads, profiling datasets, temporary upload staging |

### 2.2 Tenant Data Isolation Hierarchy

Tenant datasets are written to deterministic, isolated filesystem paths:
```text
/app/data/
├── uploads/                              # Temporary upload staging (transient)
└── tenants/                              # Tenant-isolated dataset directory
    └── <organization_id>/                # Top-level SaaS Organization UUID
        └── <business_id>/                # Business Workspace UUID
            └── <dataset_id>/             # Unique Dataset UUID
                └── <clean_name>          # Sanitized file name (e.g. sales_data.csv)
```

- **Path Isolation**: Files belonging to Tenant A (`org_a/biz_a`) and Tenant B (`org_b/biz_b`) reside in completely separate directory branches.
- **Path Traversal Defense**: All uploaded filenames are stripped of null bytes, directory separators (`/`, `\`), and directory traversal tokens (`..`) prior to path construction.
- **Container Permissions**: The `backend` container executes as non-root user `appuser` (`UID 1000`, `GID 1000`). All persistent directories in `/app/data` are owned by `appuser:appuser` with `0755` permissions for directories and `0644` for files.
- **Shared Worker Access**: The future dedicated background scheduler service (`nexus_scheduler_prod`) runs as `appuser` (UID 1000) and mounts the same `nexus_backend_data` volume at `/app/data`, allowing background causal analysis and continuous intelligence routines to read tenant files without network overhead.

> [!WARNING]
> **Destruction Warning**: Executing `docker compose down -v` permanently removes named volumes (`nexus_postgres_prod_data` and `nexus_backend_data`). Operators must **never** pass the `-v` flag in production environments.

---

## 3. Coordinated Backup Procedures

To guarantee referential integrity between PostgreSQL `storage_key` pointers and disk files, backup both components in close temporal proximity.

### 3.1 Mutation Prevention & Quiescence Strategies

To prevent inflight upload requests, continuous intelligence scans, or background ingestion jobs from mutating database state or filesystem files between the database dump and volume archive, observe the following operational requirements:

1. **Quiesce All Mutating Services (Backend API & Dedicated Schedulers/Workers)**:
   > [!IMPORTANT]
   > **Process Scope Warning**: Stopping the `backend` container halts HTTP API traffic. However, if a dedicated background scheduler or worker process is running (e.g. standalone `scheduler` container, systemd worker service, or background Python process), stopping `backend` **alone does not prevent mutations**! The scheduler can still generate anomalies, update business data readiness, and insert analysis runs into PostgreSQL. Operators must stop **both** the backend and all background workers:
   ```bash
   # Stop API backend and any running scheduler/worker service
   docker compose -f docker-compose.prod.yml stop backend $(docker compose -f docker-compose.prod.yml ps --services | grep scheduler || true)
   ```
   After executing `pg_dump` and volume archive, immediately resume the services:
   ```bash
   docker compose -f docker-compose.prod.yml start backend $(docker compose -f docker-compose.prod.yml ps --services | grep scheduler || true)
   ```
   This guarantees **zero mutations** across both the database and the filesystem volume.

2. **Ingress Maintenance Mode (Zero-Downtime Drain)**:
   If taking an online snapshot without stopping containers, set an upstream reverse proxy (Nginx or cloud load balancer) to return an HTTP 503 maintenance response for `POST /api/v1/data-gateway/` and `POST /api/v1/tenant-data/` routes during the backup script execution, preventing new file uploads while permitting read-only analytical dashboards.

### 3.2 Logical Database Backup (`pg_dump`)

#### Execute Backup from Container:
```bash
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump \
  -U nexus_user \
  -d nexus_db \
  -F c \
  -b \
  -v > /var/backups/nexus/nexus_db_$(date +%Y%m%d_%H%M%S).dump
```

### 3.3 Tenant Data Volume Backup (`nexus_backend_data`)

To safely snapshot the named volume without altering running containers, run an ephemeral container mounting the volume in read-only (`:ro`) mode:

```bash
docker run --rm \
  -v nexus_backend_data:/data:ro \
  -v /var/backups/nexus:/backup \
  alpine tar -czf /backup/nexus_files_$(date +%Y%m%d_%H%M%S).tar.gz -C /data .
```

### 3.4 Coordinated Production Backup Script

Place this coordinated backup script on the production host at `/opt/nexus/scripts/backup_nexus_coordinated.sh`:

```bash
#!/usr/bin/env bash
# ==============================================================================
# NEXUS Production Coordinated Backup Script
# Backs up PostgreSQL database and persistent tenant volume synchronously.
# ==============================================================================
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/nexus}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_BACKUP="${BACKUP_ROOT}/nexus_db_${TIMESTAMP}.dump"
FILES_BACKUP="${BACKUP_ROOT}/nexus_files_${TIMESTAMP}.tar.gz"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/nexus/docker-compose.prod.yml}"
QUIESCE_SERVICES="${QUIESCE_SERVICES:-false}"

mkdir -p "${BACKUP_ROOT}"

# Trap to clean up incomplete or corrupt artifacts if backup aborts mid-flight
cleanup_on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "[$(date)] ERROR: Backup failed with exit code ${exit_code}. Purging incomplete artifacts..."
        rm -f "${DB_BACKUP}" "${FILES_BACKUP}" "${DB_BACKUP}.sha256" "${FILES_BACKUP}.sha256"
        # Always resume services if quiescence was enabled
        if [ "${QUIESCE_SERVICES}" = "true" ]; then
            echo "[$(date)] Resuming services after error..."
            docker compose -f "${COMPOSE_FILE}" start backend $(docker compose -f "${COMPOSE_FILE}" ps --services | grep scheduler || true) || true
        fi
    fi
}
trap cleanup_on_error EXIT

echo "[$(date)] === Starting NEXUS Coordinated Backup [${TIMESTAMP}] ==="

# Optional Quiescence: Stop backend and workers to guarantee zero mutation during backup
if [ "${QUIESCE_SERVICES}" = "true" ]; then
    echo "[$(date)] Quiescing backend and background worker containers..."
    docker compose -f "${COMPOSE_FILE}" stop backend $(docker compose -f "${COMPOSE_FILE}" ps --services | grep scheduler || true)
fi

# Step 1: Dump PostgreSQL database metadata and core tables
echo "[$(date)] Backing up PostgreSQL database..."
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  pg_dump -U nexus_user -d nexus_db -F c -b > "${DB_BACKUP}"
test -s "${DB_BACKUP}" || { echo "ERROR: Database backup file is missing or empty"; exit 1; }
echo "[$(date)] Database backup completed: ${DB_BACKUP} ($(du -h "${DB_BACKUP}" | cut -f1))"

# Step 2: Archive tenant persistent volume (read-only mount)
echo "[$(date)] Backing up tenant persistent file volume (nexus_backend_data)..."
docker run --rm \
  -v nexus_backend_data:/data:ro \
  -v "${BACKUP_ROOT}":/backup \
  alpine tar -czf "/backup/nexus_files_${TIMESTAMP}.tar.gz" -C /data .
test -s "${FILES_BACKUP}" || { echo "ERROR: Tenant files archive is missing or empty"; exit 1; }
echo "[$(date)] Tenant files backup completed: ${FILES_BACKUP} ($(du -h "${FILES_BACKUP}" | cut -f1))"

# Resume services immediately if quiescence was enabled
if [ "${QUIESCE_SERVICES}" = "true" ]; then
    echo "[$(date)] Resuming backend and worker containers..."
    docker compose -f "${COMPOSE_FILE}" start backend $(docker compose -f "${COMPOSE_FILE}" ps --services | grep scheduler || true)
fi

# Step 3: Compute SHA-256 checksums for backup verification
sha256sum "${DB_BACKUP}" > "${DB_BACKUP}.sha256"
sha256sum "${FILES_BACKUP}" > "${FILES_BACKUP}.sha256"
echo "[$(date)] Checksums computed."

# Step 4: Prune local archives older than retention window
find "${BACKUP_ROOT}" -type f \( -name "nexus_db_*.dump*" -o -name "nexus_files_*.tar.gz*" \) -mtime +${RETENTION_DAYS} -delete
echo "[$(date)] Retention pruning complete (retained ${RETENTION_DAYS} days)."

echo "[$(date)] === Coordinated Backup Completed Successfully ==="
```

Make executable and schedule in system crontab:
```bash
chmod +x /opt/nexus/scripts/backup_nexus_coordinated.sh
# Run daily at 02:00 UTC
# 0 2 * * * /opt/nexus/scripts/backup_nexus_coordinated.sh >> /var/log/nexus_backup.log 2>&1
```

### 3.5 Backup Encryption & Off-Host Replication

1. **At-Rest Encryption**:
   Encrypt backup archives prior to transmission using GPG (symmetric AES-256 or recipient public key):
   ```bash
   gpg --symmetric --cipher-algo AES256 --batch --passphrase-file /opt/nexus/secrets/backup_passphrase.txt "${DB_BACKUP}"
   gpg --symmetric --cipher-algo AES256 --batch --passphrase-file /opt/nexus/secrets/backup_passphrase.txt "${FILES_BACKUP}"
   ```
2. **Off-Host Replication**:
   Never store backups exclusively on the production Docker host. Replicate encrypted archives to off-host storage (e.g. AWS S3 Glacier, Google Cloud Storage coldline, or dedicated remote rsync target):
   ```bash
   aws s3 cp "${DB_BACKUP}.gpg" s3://nexus-production-backups/postgres/
   aws s3 cp "${FILES_BACKUP}.gpg" s3://nexus-production-backups/tenant-files/
   ```
3. **Retention Schedule**:
   - Daily backups: Retain 14 to 30 days.
   - Weekly snapshots: Retain 90 days.
   - Monthly snapshots: Retain 365 days for regulatory/audit compliance.

### 3.6 Redis Persistence, BGSAVE Backup & JWT-Secret Rotation Fallback

1. **Redis Persistence Policy**:
   Redis runs with Append-Only File (AOF) persistence:
   - `--appendonly yes`
   - `--appendfsync everysec`
   - `--maxmemory 256mb`
   - `--maxmemory-policy noeviction`
   Redis data is mounted on named volume `nexus_redis_prod_data` at `/data`.

2. **Redis Backup Procedure (Verified BGSAVE)**:
   > [!IMPORTANT]
   > Do NOT copy a live AOF volume while Redis is actively writing, as torn blocks can corrupt the restored archive.
   Coordinated backups trigger an explicit Redis background save (`BGSAVE`), poll until `rdb_bgsave_in_progress:0` and `rdb_last_bgsave_status:ok`, and archive the verified `dump.rdb` snapshot:
   ```bash
   docker compose -f docker-compose.prod.yml exec -T redis redis-cli bgsave
   # Verify completion via info persistence, then archive dump.rdb
   docker run --rm \
     -v nexus_redis_prod_data:/data:ro \
     -v /var/backups/nexus:/backup \
     alpine sh -c "test -s /data/dump.rdb && tar -czf /backup/nexus_redis_${TIMESTAMP}.tar.gz -C /data dump.rdb"
   ```

3. **Disaster Recovery Fallback (JWT-Secret Rotation)**:
   > [!IMPORTANT]
   > **Security Invariant**: Redis stores rate-limiting counters, active token revocation lists (blocklists), and shared session states.
   > If the Redis volume or AOF state is destroyed or cannot be recovered from backup:
   > - Any JWT tokens that were revoked in the blocklist would no longer be recognized as revoked by the backend.
   > - **Mandatory Recovery Action**: If Redis state cannot be restored, the operator **MUST immediately rotate `AUTH_JWT_SECRET`** across all backend and scheduler environment configurations and restart the services.
   > - Rotating `AUTH_JWT_SECRET` immediately invalidates all outstanding JWT tokens, protecting against the replay of revoked or compromised session credentials.

4. **Fail-Safe Retention Policy**:
   - Backup retention is managed by `app.core.backup.enforce_retention`.
   - **Safety Invariant**: Under no circumstances will older backups be pruned if there are **seven or fewer (<= 7)** valid coordinated backup sets available.
   - **Safety Invariant**: The single most recent known-good backup set is **never** deleted, regardless of age or configured retention window.

5. **Operational Failure Alerting**:
   - Backup failures automatically report to Sentry (tag `service=backup`).
   - If `BACKUP_ALERT_WEBHOOK_URL` is configured, an automated JSON alert payload is dispatched to the incident response webhook on any backup or restore failure.

---

## 4. Coordinated Restore & Recovery Procedures

To restore both database metadata and raw tenant files to a synchronized point in time, execute `scripts/restore_nexus_coordinated.sh` with the explicit safety confirmation flag:

```bash
./scripts/restore_nexus_coordinated.sh --confirm-destructive-restore <TIMESTAMP> [BACKUP_ROOT]
```

### Safety Controls & Invariants:
1. **Explicit Confirmation**: Non-interactive executions fail closed unless `--confirm-destructive-restore` is provided. Interactive TTY executions additionally require typing `CONFIRM-RESTORE`.
2. **Pre-Flight Validation**: Database dump magic bytes (`PGDMP`), tar archive integrity (`tar -tzf`), and SHA-256 sidecars are verified before stopping services or mutating data.
3. **Staged Tenant File Extraction**: Files are extracted to a staging directory (`/data/staging_<TIMESTAMP>`) and validated prior to replacing live data.
4. **Split-State Recovery Strategy**: If database restoration succeeds but tenant file extraction fails:
   - Restoration aborts and immediately fires a `RESTORE_SPLIT_STATE` alert to Sentry and `BACKUP_ALERT_WEBHOOK_URL`.
   - The original tenant files remain uncorrupted because changes occur through the staging directory.
   - Operators can inspect `/data/staging_<TIMESTAMP>` or rerun storage reconciliation with `python scripts/reconcile_storage.py` before resuming services.

### Manual Step-by-Step Restoration (Runbook Reference)

### Step 1: Pre-Flight Integrity Verification
```bash
sha256sum -c "/var/backups/nexus/nexus_db_${TIMESTAMP}.dump.sha256"
sha256sum -c "/var/backups/nexus/nexus_files_${TIMESTAMP}.tar.gz.sha256"
tar -tzf "/var/backups/nexus/nexus_files_${TIMESTAMP}.tar.gz" > /dev/null
```

### Step 2: Quiesce Traffic & Stop Ingestion
Stop the application backend and any standalone scheduler workers to prevent inbound writes during restoration:
```bash
docker compose -f docker-compose.prod.yml stop backend $(docker compose -f docker-compose.prod.yml ps --services | grep scheduler || true)
```

### Step 3: Restore PostgreSQL Database
```bash
# Terminate any remaining database connections
docker compose -f docker-compose.prod.yml exec postgres psql -U nexus_user -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'nexus_db' AND pid <> pg_backend_pid();"

# Recreate fresh database
docker compose -f docker-compose.prod.yml exec postgres dropdb -U nexus_user --if-exists nexus_db
docker compose -f docker-compose.prod.yml exec postgres createdb -U nexus_user nexus_db

# Restore dump
docker compose -f docker-compose.prod.yml exec -T postgres pg_restore \
  -U nexus_user \
  -d nexus_db \
  -v \
  < /var/backups/nexus/nexus_db_${TIMESTAMP}.dump
```

### Step 4: Staged Restoration of Persistent File Volume (`nexus_backend_data`)
Restore tenant files via staging, ensuring ownership is restored to `appuser` (`1000:1000`):

```bash
docker run --rm \
  -v nexus_backend_data:/data \
  -v /var/backups/nexus:/backup:ro \
  alpine sh -c "
    set -e
    mkdir -p /data/staging_${TIMESTAMP}
    tar -xzf /backup/nexus_files_${TIMESTAMP}.tar.gz -C /data/staging_${TIMESTAMP}
    mkdir -p /data/tenants
    rm -rf /data/tenants/*
    if [ -d /data/staging_${TIMESTAMP}/tenants ]; then
      cp -a /data/staging_${TIMESTAMP}/tenants/* /data/tenants/ 2>/dev/null || true
    fi
    rm -rf /data/staging_${TIMESTAMP}
    chown -R 1000:1000 /data
    chmod 755 /data
    chmod -R u=rwX,go=rX /data
  "
```

### Step 4: Post-Restore Integrity & Reconciliation Verification

Execute the following verification checklist before resuming production traffic:

1. **Verify Volume Permissions**:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm backend sh -c "
     id && \
     ls -la /app/data && \
     ls -la /app/data/tenants 2>/dev/null || true
   "
   # Verify: appuser (uid 1000) owns /app/data, /app/data/tenants, /app/data/uploads
   ```

2. **Verify Database Extensions & Migrations**:
   ```bash
   docker compose -f docker-compose.prod.yml exec postgres psql -U nexus_user -d nexus_db -c "\dx"
   # Verify: 'vector' extension is present
   ```

3. **Reconcile `storage_key` References against Filesystem**:
   Run a reconciliation check to confirm all database `storage_key` records exist on disk (or use `scripts/reconcile_storage.py`):
   ```bash
   docker compose -f docker-compose.prod.yml run --rm backend python -c "
from app.core.database import SessionLocal
from app.models.tenant import UploadedDataset
from app.services.data_gateway_service import DataGatewayService
from pathlib import Path

db = SessionLocal()
datasets = db.query(UploadedDataset).all()
print(f'Validating {len(datasets)} dataset storage keys...')
missing = []
for ds in datasets:
    resolved = DataGatewayService.resolve_storage_path(ds.storage_key)
    if not resolved.exists():
        missing.append((ds.id, ds.filename, ds.storage_key))

if missing:
    print(f'WARNING: {len(missing)} datasets have missing storage files:')
    for m in missing[:5]:
        print(f'  ID: {m[0]}, file: {m[1]}, key: {m[2]}')
else:
    print('SUCCESS: 100% of dataset storage keys resolved successfully on disk.')
db.close()
"
   ```

4. **Verify Tenant Boundary Isolation**:
   Confirm that directory paths strictly match the format:
   `/app/data/tenants/<org_id>/<business_id>/<dataset_id>/<filename>`
   and no files exist outside their assigned tenant trees.

5. **Reconcile and Prune Unmanaged/Orphaned Disk Files**:
   Because filesystem writes and database transactions do not share a two-phase commit (2PC) coordinator, unexpected host crashes, container kills, or storage cleanup failures during rollback can leave unindexed dataset files on disk.

   > [!IMPORTANT]
   > **Authoritative Schema vs. Unverified Directory Assumptions**:
   > The PostgreSQL table `uploaded_datasets` stores the authoritative location of each file in the `storage_key` column (e.g. `data/tenants/<org>/<biz>/<dataset_id>/<filename>`).
   > Reconciliation must **never** delete directories based on the unverified assumption that directory names match `UploadedDataset.id`, as custom fixtures, legacy migrations, or alternative path formats could be catastrophically wiped.
   > The procedure below:
   > 1. Queries all authoritative `storage_key` records from `uploaded_datasets`.
   > 2. Resolves each `storage_key` to its canonical absolute filesystem path using `DataGatewayService.resolve_storage_path()`.
   > 3. Scans the configured `settings.DATA_DIR / "tenants"` tree for actual files on disk.
   > 4. Identifies files whose resolved path is not referenced in any `storage_key` record.
   > 5. **Defaults to DRY-RUN / AUDIT mode** (`DELETE_ORPHANS=false`), reporting orphaned files without modifying disk state.
   > 6. Requires explicit operator confirmation (`DELETE_ORPHANS=true`) to delete unindexed files and prune empty parent directories up to the tenant root.

   Run the reconciliation check via `scripts/reconcile_storage.py` or inline:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm \
     -e DELETE_ORPHANS=false \
     backend python -c "
import os
from pathlib import Path
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tenant import UploadedDataset
from app.services.data_gateway_service import DataGatewayService

delete_enabled = os.environ.get('DELETE_ORPHANS', 'false').lower() == 'true'

db = SessionLocal()
try:
    datasets = db.query(UploadedDataset.id, UploadedDataset.storage_key).all()
    indexed_paths = set()
    for ds_id, storage_key in datasets:
        if storage_key:
            resolved = DataGatewayService.resolve_storage_path(storage_key).resolve()
            indexed_paths.add(resolved)
finally:
    db.close()

base_dir = Path(getattr(settings, 'DATA_DIR', 'data')).resolve()
tenants_root = base_dir / 'tenants'

if not tenants_root.exists():
    print(f'Tenants storage root does not exist: {tenants_root}')
    exit(0)

print(f'=== Tenant Storage Reconciliation ===')
print(f'Authoritative database records: {len(indexed_paths)} files registered')
print(f'Scanning disk tree: {tenants_root}')

disk_files = [f.resolve() for f in tenants_root.rglob('*') if f.is_file()]
orphan_files = [f for f in disk_files if f not in indexed_paths]

print(f'Total files on disk: {len(disk_files)}')
print(f'Unindexed (orphaned) files detected: {len(orphan_files)}')

if not orphan_files:
    print('SUCCESS: Storage is completely consistent. Zero orphaned files.')
    exit(0)

for orphan in orphan_files:
    size = orphan.stat().st_size
    print(f'  [ORPHAN] {orphan} ({size} bytes)')

if not delete_enabled:
    print('\n[DRY RUN] No files were removed. To prune orphaned files, rerun with DELETE_ORPHANS=true.')
else:
    print('\n[PURGE] Operator confirmed purge. Removing orphaned files...')
    purged_count = 0
    for orphan in orphan_files:
        try:
            orphan.unlink()
            purged_count += 1
            parent = orphan.parent
            while parent != tenants_root and parent.is_relative_to(tenants_root):
                if not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
                else:
                    break
        except OSError as e:
            print(f'  ERROR removing {orphan}: {e}')
    print(f'Purged {purged_count} orphaned files and empty directories.')
"
   ```

### Step 5: Resume Inbound Traffic
```bash
docker compose -f docker-compose.prod.yml start backend $(docker compose -f docker-compose.prod.yml ps --services | grep scheduler || true)
curl -f http://localhost:8000/api/health/ready
```

---

## 5. Architectural Roadmap: Local Docker Volume vs. Cloud Object Storage

It is critical to distinguish the current local Docker volume design from multi-node object storage:

```
+-----------------------------------------------------------------------------------+
| SINGLE-HOST DEPLOYMENT (CURRENT PHASE 31B)                                        |
|                                                                                   |
|  +--------------------+         +-----------------------+                         |
|  | nexus_backend_prod |         | nexus_scheduler_prod  |                         |
|  | (FastAPI API Pod)  |         | (Continuous Worker)   |                         |
|  +---------+----------+         +-----------+-----------+                         |
|            |                                |                                     |
|            +--------------+  +--------------+                                     |
|                           |  |                                                    |
|                           v  v                                                    |
|            +-------------------------------+                                      |
|            |   nexus_backend_data (Volume) | (Local Docker Driver on Host)        |
|            |   /app/data                   |                                      |
|            +-------------------------------+                                      |
+-----------------------------------------------------------------------------------+

+-----------------------------------------------------------------------------------+
| MULTI-NODE CLUSTER DEPLOYMENT (FUTURE ROADMAP)                                    |
|                                                                                   |
|  [ Host Node 1 ]                [ Host Node 2 ]                [ Host Node 3 ]    |
|  +-------------------+          +-------------------+          +----------------+ |
|  | backend-replica-1 |          | backend-replica-2 |          | scheduler-pod  | |
|  +---------+---------+          +---------+---------+          +--------+-------+ |
|            |                              |                             |         |
|            +------------------------------+-----------------------------+         |
|                                           |                                       |
|                                           v                                       |
|                  +----------------------------------+                             |
|                  | S3 / GCS / Azure Blob Storage    |                             |
|                  | s3://nexus-prod-tenant-storage/  |                             |
|                  +----------------------------------+                             |
+-----------------------------------------------------------------------------------+
```

### Current Single-Host Scope (Phase 31B):
- The named Docker volume `nexus_backend_data` with `driver: local` stores files on the local Docker host filesystem (`/var/lib/docker/volumes/nexus_backend_data/_data`).
- This design is simple, performant, has zero network latency, and allows the API `backend` and background `scheduler` containers to share tenant datasets seamlessly on the same host.

### Future Multi-Node Cluster Scope:
- When NEXUS is horizontally scaled across multiple compute nodes (Kubernetes, AWS ECS, Docker Swarm), a local Docker volume **cannot** be shared across physical hosts.
- At that scale, NEXUS will implement an abstracted `StorageBackend` protocol (e.g., `S3StorageBackend`, `GCSStorageBackend`) to store raw tenant files in cloud object storage while keeping relational indexing in PostgreSQL.

---

## 6. Migration Recovery & Rollback

Alembic migrations (`backend/alembic/versions/`) maintain schema history:

### Check Current Migration Status:
```bash
cd backend
python -m alembic current
```

### Rollback the Most Recent Migration Revision:
```bash
python -m alembic downgrade -1
```

### Rollback to Base:
```bash
python -m alembic downgrade base
```

### Repairing Out-of-Sync Migration State:
If a migration was applied manually or interrupted during execution:
```bash
python -m alembic stamp head
```

---

## 7. Operational Recovery Matrix

| Data Asset | Persistence Mechanism | Backup Method | Restore Method | Recovery Point Objective (RPO) | Recovery Time Objective (RTO) |
|---|---|---|---|---|---|
| **Relational Database** (Users, Orgs, Entities) | `nexus_postgres_prod_data` volume | `pg_dump -F c` via cron | `pg_restore` | 24 hours (or snapshot frequency) | < 15 minutes |
| **Vector Embeddings** (`pgvector` tables) | `nexus_postgres_prod_data` volume | `pg_dump -F c` via cron | `pg_restore` | 24 hours | < 15 minutes |
| **Raw Tenant Files** (Uploaded CSV/Excel) | `nexus_backend_data` volume | `tar -czf` via ephemeral container | `tar -xzf` + chown | 24 hours (coordinated with DB) | < 10 minutes |
| **Alembic Version State** | `alembic_version` table | Part of `pg_dump` | Part of `pg_restore` | Synchronized with DB | Immediate |
| **Multi-Host Shared Storage** | S3/GCS Object Store (Roadmap) | Cloud provider versioning/replication | Point-in-time bucket restore | Continuous / Versioned | < 30 minutes |

---

## 8. CI Recovery Mechanics Drill (Manual Workflow)

To continuously test and verify coordinated dump, restore, and storage reconciliation mechanics without incurring hosting costs, NEXUS provides a dedicated, isolated GitHub Actions workflow: [`.github/workflows/backup-restore-drill.yml`](../../.github/workflows/backup-restore-drill.yml).

### 8.1 How to Manually Trigger the Workflow

1. Navigate to the repository's **Actions** tab on GitHub.
2. Under **All workflows**, select **NEXUS Coordinated Backup & Restore Mechanics Drill**.
3. Click the **Run workflow** dropdown on the `main` branch.
4. Click the green **Run workflow** button to initiate execution.

Execution takes approximately **35–50 seconds** and runs on an ephemeral GitHub-hosted Ubuntu runner with an isolated `pgvector/pgvector:pg16` service container at ₹0 incremental infrastructure cost.

### 8.2 What the CI Drill Verifies

The CI drill executes [`backend/tests/test_backup_restore_phase32c.py::test_live_postgres_backup_restore_and_storage_reconciliation_drill`](../../backend/tests/test_backup_restore_phase32c.py#L572-L875) under strict `REQUIRE_POSTGRES=true` and `LLM_ALLOW_EXTERNAL_CALLS=false` settings:

1. **Source Target Validation**: Confirms the target database name is strictly `nexus_test_db` before connecting (fails closed against any non-test database name).
2. **PostgreSQL 16 Client Toolchain**: Certifies that host `pg_dump` and `pg_restore` binaries match PostgreSQL 16.
3. **Real Custom Dump Generation**: Executes `pg_dump -F c` against the seeded source database and asserts the `PGDMP` header magic bytes.
4. **Tenant File Volume Snapshot**: Bundles seeded tenant files into a compressed tar archive and computes SHA-256 sidecars.
5. **Disposable Target Lifecycle**: Dynamically creates a disposable target database (`nexus_restore_verify_<uid>`), strictly validating the database identifier against `^nexus_restore_verify_[a-zA-Z0-9_]{1,40}$`.
6. **Real Custom Restore**: Executes `pg_restore` into the disposable database.
7. **Schema & Vector Verification**: Connects to the restored database and verifies table presence, row counts, sequences, foreign key constraints, JSONB data fidelity, and executes a live `pgvector` distance query (`<->`).
8. **File Restoration & Hash Matching**: Extracts tenant files into a temporary directory and validates file byte size and SHA-256 digest against restored database records.
9. **Storage Reconciliation**: Runs `reconcile_tenant_storage()` to confirm zero missing files and zero unindexed orphans.
10. **Fail-Closed Teardown**: Terminates active sessions, drops `nexus_restore_verify_<uid>`, and cleans seeded records without masking primary test assertions.

### 8.3 What the CI Drill Does NOT Verify (Disaster Recovery Boundary)

> [!CAUTION]
> **Operational Boundary & Non-Certification Notice**:
> A successful run of the CI recovery mechanics drill validates code, schema, and toolchain mechanics in an ephemeral container sandbox. **It does NOT certify production disaster recovery readiness.**
>
> The CI drill does **NOT** verify:
> 1. **Persistent Host Block Durability**: CI disks and containers are ephemeral; it does not test physical block volumes (e.g., AWS EBS / NVMe) or POSIX ownership permissions (`appuser:1000:1000`) across host reboots.
> 2. **Multi-Process Service Quiescence**: CI runs in a quiescent single-job environment; it does not test stopping live multi-worker Uvicorn APIs and background continuous scheduler daemons under active user traffic.
> 3. **Production Data Volume Scale**: CI tests with seed fixtures (< 1 MB); it does not test multi-gigabyte table dumps, network transfer bottlenecks, RAM constraints, or database lock timeouts.
> 4. **Off-Host Replication**: CI does not test automated replication of encrypted snapshots to remote cloud storage (AWS S3 Glacier, Google Cloud Storage).
>
> A real, authorized staging backup/restore drill on isolated staging infrastructure remains mandatory prior to accepting commercial production workloads.

### 8.4 Verified CI Mechanics Drill Execution Record

On **2026-10-23**, the manual recovery mechanics workflow was executed and verified on GitHub Actions:

- **Workflow**: `NEXUS Coordinated Backup & Restore Mechanics Drill` ([`.github/workflows/backup-restore-drill.yml`](../../.github/workflows/backup-restore-drill.yml))
- **Run ID**: `39988258994`
- **Run URL**: [https://github.com/rzvn6660/Nexus/actions/runs/39988258994](https://github.com/rzvn6660/Nexus/actions/runs/39988258994)
- **Commit Tested**: `e75627767d13130f3c2695ecb19265d2ddedf7f7`
- **Client Toolchain**: PostgreSQL 16.15 (`pg_dump` and `pg_restore`)
- **Test Result**: **1 passed, 0 failed, 0 skipped** (duration: 55s)
- **Cleanup Gate Verification**: **0 leftover databases** (`nexus_restore_verify_%`), **0 leftover seeded records** (`drill-org-%` / `Restore Drill Org %`)
- **Operational Scope**: This execution certifies code execution, dump/restore mechanics, and storage reconciliation in an ephemeral container environment only. It does **not** certify persistent staging storage durability, off-host backup replication, or commercial production disaster-recovery readiness.
