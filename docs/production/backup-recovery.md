# NEXUS Database Backup & Disaster Recovery Guide

**Document Version**: 1.0  
**Phase**: Phase 10 — Production & Deployment  
**Classification**: Operational Runbook  

---

## 1. Overview & Operational Scope

This document specifies standard operating procedures for data persistence, scheduled backups, point-in-time recovery, and schema rollback for the **NEXUS Agentic Business Intelligence Platform**.

> [!IMPORTANT]
> **Scope Notice**: For the current startup-scale / prototype deployment, automated multi-region replication and automated disaster recovery failover are **NOT** pre-configured. Backup automation relies on host-level volume snapshots or cron-driven `pg_dump` operations as described herein.

---

## 2. Persistence Model

In Docker and containerized production environments:
- **Database Volume**: PostgreSQL data files reside on a named persistent volume (`nexus_postgres_prod_data` or `postgres_data`).
- **Volume Mount Path**: Mounted to `/var/lib/postgresql/data` inside the database container.
- **Persistence Guarantee**: Container recreation, image updates, or backend restarts preserve all relational tables, indexes, and vector embeddings in the persistent volume.
- **Destruction Warning**: Executing `docker compose down -v` removes named volumes. Operators must never pass the `-v` flag in production environments.

---

## 3. Database Backup Procedures

### 3.1 Logical Backup (`pg_dump`)

A logical dump extracts complete SQL DDL and table data into a compressed, transportable archive:

#### Execute Backup from Container:
```bash
docker compose exec postgres pg_dump \
  -U nexus_user \
  -d nexus_db \
  -F c \
  -b \
  -v \
  -f /tmp/nexus_db_backup_$(date +%Y%m%d_%H%M%S).dump

# Copy archive from container to host or remote storage:
docker cp nexus_postgres:/tmp/nexus_db_backup_*.dump ./backups/
```

#### Execute Backup from Host (Direct PostgreSQL Connection):
```bash
pg_dump \
  -h localhost \
  -p 5432 \
  -U nexus_user \
  -d nexus_db \
  -F c \
  -b \
  -v \
  -f ./backups/nexus_db_$(date +%Y%m%d_%H%M%S).dump
```

### 3.2 Automated Daily Cron Backup (Recommended Production Setup)

Place the following script in `/opt/nexus/scripts/backup_nexus.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/nexus"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/nexus_db_${TIMESTAMP}.dump"
RETENTION_DAYS=14

mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Starting NEXUS database backup..."
docker compose -f /opt/nexus/docker-compose.prod.yml exec -T postgres \
  pg_dump -U nexus_user -d nexus_db -F c -b > "${BACKUP_FILE}"

echo "[$(date)] Backup completed: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))"

# Prune archives older than retention window
find "${BACKUP_DIR}" -type f -name "nexus_db_*.dump" -mtime +${RETENTION_DAYS} -delete
echo "[$(date)] Retention pruning complete."
```

Schedule via crontab:
```text
0 2 * * * /opt/nexus/scripts/backup_nexus.sh >> /var/log/nexus_backup.log 2>&1
```

---

## 4. Database Restore Procedure

To restore a database snapshot into a clean or recovered instance:

### Step 1: Terminate Inbound Traffic
Temporarily stop or route backend traffic to maintenance mode:
```bash
docker compose stop backend
```

### Step 2: Drop Existing Active Connections
```bash
docker compose exec postgres psql -U nexus_user -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'nexus_db' AND pid <> pg_backend_pid();"
```

### Step 3: Restore Database Dump
```bash
# Drop and recreate clean database schema
docker compose exec postgres dropdb -U nexus_user --if-exists nexus_db
docker compose exec postgres createdb -U nexus_user nexus_db

# Restore archive using pg_restore
docker compose exec -T postgres pg_restore \
  -U nexus_user \
  -d nexus_db \
  -v \
  --clean \
  --if-exists \
  < ./backups/nexus_db_20260926_100000.dump
```

### Step 4: Validate Schema & Extension Integrity
```bash
docker compose exec postgres psql -U nexus_user -d nexus_db -c "\dx"
# Confirm that 'vector' (pgvector) extension is listed and active
```

### Step 5: Restart Backend Service
```bash
docker compose start backend
curl -f http://localhost:8000/api/v1/health/ready
```

---

## 5. Migration Recovery & Rollback

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
# Stamp database with target revision without running DDL
python -m alembic stamp head
```

---

## 6. What Is and Is Not Covered

| Item | Status | Notes |
|---|---|---|
| **Relational Data** | Covered | Customers, Products, Sales, Items, Expenses, Inventory |
| **RAG Knowledge Base** | Covered | Documents, text chunks, vector embeddings |
| **Alembic History** | Covered | `alembic_version` table in database |
| **Automated Failover** | **Not Covered** | Single-primary database topology |
| **Point-in-Time WAL Archiving** | **Not Covered** | WAL archiving requires dedicated cloud storage bucket |
| **Off-Site Replication** | **Operator Responsibility**| Backups must be synced to S3/GCS by hosting provider |
