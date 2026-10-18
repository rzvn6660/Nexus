#!/usr/bin/env bash
# ==============================================================================
# NEXUS Production Coordinated Backup Script (Phase 32C Hardened)
# Synchronously snapshots PostgreSQL database, tenant persistent volume, and Redis state.
#
# Features:
# - Input validation: rejects empty, root, or unsafe BACKUP_ROOT paths
# - Restrictive umask 077 and strict file permissions (0600 on dumps/archives, 0644 sidecars)
# - Pre-flight Docker Compose validation before service quiescence
# - Coordinated quiescence to guarantee zero-mutation consistency
# - Redis BGSAVE with polling verification (never uses live torn AOF volume copy)
# - SHA-256 cryptographic verification sidecars
# - Post-backup integrity validation (PGDMP header, tar -tzf, and sha256sum -c)
# - Fail-safe retention: Preserves >= 7 valid sets, never deletes last known-good
# - Automated failure alerts via Sentry and optional BACKUP_ALERT_WEBHOOK_URL
# - Safe failure cleanup: purges ONLY current failed timestamp artifacts; never deletes prior backups
# ==============================================================================
set -euo pipefail

# 1. Enforce Restrictive Umask for all created files
umask 077

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/nexus}"

# 2. Strict BACKUP_ROOT Path Safety Validation
if [ -z "${BACKUP_ROOT}" ] || [ "${BACKUP_ROOT}" = "/" ] || [ "${BACKUP_ROOT}" = "/root" ] || [ "${BACKUP_ROOT}" = "/etc" ] || [ "${BACKUP_ROOT}" = "/bin" ] || [ "${BACKUP_ROOT}" = "/usr" ]; then
    echo "ERROR: Refusing to use empty, root, or system BACKUP_ROOT path: '${BACKUP_ROOT}'" >&2
    exit 1
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_BACKUP="${BACKUP_ROOT}/nexus_db_${TIMESTAMP}.dump"
FILES_BACKUP="${BACKUP_ROOT}/nexus_files_${TIMESTAMP}.tar.gz"
REDIS_BACKUP="${BACKUP_ROOT}/nexus_redis_${TIMESTAMP}.tar.gz"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
MIN_RETAINED_SETS="${MIN_RETAINED_SETS:-7}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
QUIESCE_SERVICES="${QUIESCE_SERVICES:-true}"

mkdir -p "${BACKUP_ROOT}"
chmod 700 "${BACKUP_ROOT}"

# Alerting helper
send_alert() {
    local event_type="$1"
    local message="$2"
    python -c "
import sys
try:
    from app.core.backup import send_backup_alert
    send_backup_alert('${event_type}', '${message}')
except Exception as e:
    sys.stderr.write(f'Alert dispatch failed: {e}\n')
" 2>/dev/null || true
}

# Trap to guarantee services resume and cleanup on failure (only removes current artifacts)
cleanup_on_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "[$(date -u)] ERROR: Backup failed with exit code ${exit_code}. Purging current run artifacts..."
        rm -f "${DB_BACKUP}" "${FILES_BACKUP}" "${REDIS_BACKUP}" \
              "${DB_BACKUP}.sha256" "${FILES_BACKUP}.sha256" "${REDIS_BACKUP}.sha256"

        send_alert "BACKUP_FAILED" "Coordinated backup failed at timestamp ${TIMESTAMP} with exit code ${exit_code}."

        if [ "${QUIESCE_SERVICES}" = "true" ]; then
            echo "[$(date -u)] Resuming services after backup failure..."
            docker compose -f "${COMPOSE_FILE}" start backend scheduler || true
        fi
    fi
}
trap cleanup_on_error EXIT

echo "[$(date -u)] === Starting NEXUS Coordinated Backup [${TIMESTAMP}] ==="

# Step 0: Validate Compose configuration and container reachability BEFORE quiescing
echo "[$(date -u)] Pre-flight validation of Docker Compose configuration..."
docker compose -f "${COMPOSE_FILE}" config > /dev/null

# Step 1: Quiesce mutating containers (Backend API & Dedicated Scheduler)
if [ "${QUIESCE_SERVICES}" = "true" ]; then
    echo "[$(date -u)] Quiescing mutating containers (backend and scheduler)..."
    docker compose -f "${COMPOSE_FILE}" stop backend scheduler
fi

# Step 2: Dump PostgreSQL Database (-F c custom format)
echo "[$(date -u)] Dumping PostgreSQL database (nexus_db)..."
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    pg_dump -U nexus_user -d nexus_db -F c -b > "${DB_BACKUP}"
test -s "${DB_BACKUP}" || { echo "ERROR: Database backup file is missing or empty"; exit 1; }
chmod 600 "${DB_BACKUP}"

# Step 3: Archive Tenant File Volume (nexus_backend_data)
echo "[$(date -u)] Archiving tenant file volume (nexus_backend_data)..."
docker run --rm \
    -v nexus_backend_data:/data:ro \
    -v "${BACKUP_ROOT}":/backup \
    alpine tar -czf "/backup/nexus_files_${TIMESTAMP}.tar.gz" -C /data .
test -s "${FILES_BACKUP}" || { echo "ERROR: Tenant files archive is missing or empty"; exit 1; }
chmod 600 "${FILES_BACKUP}"

# Step 4: Consistent Redis Snapshot via Verified BGSAVE
echo "[$(date -u)] Executing consistent Redis snapshot via BGSAVE..."
docker compose -f "${COMPOSE_FILE}" exec -T redis redis-cli bgsave

# Poll until BGSAVE completes
BGSAVE_SUCCESS=false
for i in $(seq 1 30); do
    IN_PROGRESS=$(docker compose -f "${COMPOSE_FILE}" exec -T redis redis-cli info persistence | grep -E '^rdb_bgsave_in_progress:' | tr -d '\r' | cut -d: -f2 || echo "1")
    LAST_STATUS=$(docker compose -f "${COMPOSE_FILE}" exec -T redis redis-cli info persistence | grep -E '^rdb_last_bgsave_status:' | tr -d '\r' | cut -d: -f2 || echo "err")
    if [ "${IN_PROGRESS}" = "0" ] && [ "${LAST_STATUS}" = "ok" ]; then
        BGSAVE_SUCCESS=true
        echo "[$(date -u)] Redis BGSAVE verified successfully."
        break
    fi
    sleep 1
done

if [ "${BGSAVE_SUCCESS}" != "true" ]; then
    echo "ERROR: Redis BGSAVE failed or timed out (last status: ${LAST_STATUS:-unknown})" >&2
    exit 1
fi

# Archive the verified dump.rdb
docker run --rm \
    -v nexus_redis_prod_data:/data:ro \
    -v "${BACKUP_ROOT}":/backup \
    alpine sh -c "test -s /data/dump.rdb && tar -czf /backup/nexus_redis_${TIMESTAMP}.tar.gz -C /data dump.rdb"
test -s "${REDIS_BACKUP}" || { echo "ERROR: Redis backup archive is missing or empty"; exit 1; }
chmod 600 "${REDIS_BACKUP}"

# Step 5: Resume mutating services immediately after consistent snapshots are taken
if [ "${QUIESCE_SERVICES}" = "true" ]; then
    echo "[$(date -u)] Resuming backend and scheduler services..."
    docker compose -f "${COMPOSE_FILE}" start backend scheduler
fi

# Step 6: Compute SHA-256 Checksums
echo "[$(date -u)] Generating SHA-256 checksums..."
sha256sum "${DB_BACKUP}" > "${DB_BACKUP}.sha256"
sha256sum "${FILES_BACKUP}" > "${FILES_BACKUP}.sha256"
sha256sum "${REDIS_BACKUP}" > "${REDIS_BACKUP}.sha256"
chmod 644 "${DB_BACKUP}.sha256" "${FILES_BACKUP}.sha256" "${REDIS_BACKUP}.sha256"

# Step 7: Validate Archive Integrity & Header Signatures
echo "[$(date -u)] Validating archive integrity and signatures..."
sha256sum -c "${DB_BACKUP}.sha256"
sha256sum -c "${FILES_BACKUP}.sha256"
sha256sum -c "${REDIS_BACKUP}.sha256"

# Check PGDMP custom format magic bytes
python -c "
from pathlib import Path
dump_path = Path('${DB_BACKUP}')
with dump_path.open('rb') as f:
    header = f.read(5)
assert header == b'PGDMP', f'Invalid pg_dump header: {header!r}'
"

# Validate tar archives
tar -tzf "${FILES_BACKUP}" > /dev/null
tar -tzf "${REDIS_BACKUP}" > /dev/null

# Step 8: Enforce Fail-Safe Retention Policy (Python Core Engine)
echo "[$(date -u)] Enforcing retention policy (retention: ${RETENTION_DAYS}d, min_retained: ${MIN_RETAINED_SETS})..."
python -c "
from pathlib import Path
from app.core.backup import enforce_retention
pruned = enforce_retention(
    backup_dir=Path('${BACKUP_ROOT}'),
    retention_days=${RETENTION_DAYS},
    min_retained_sets=${MIN_RETAINED_SETS},
)
print(f'Retention enforcement complete. Pruned {len(pruned)} expired files.')
"

echo "[$(date -u)] === Coordinated Backup Completed Successfully ==="
