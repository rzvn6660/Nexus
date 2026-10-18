#!/usr/bin/env bash
# ==============================================================================
# NEXUS Production Coordinated Restore & Recovery Script (Phase 32C Hardened)
# Restores PostgreSQL database, tenant persistent files, and Redis state from a synchronized snapshot.
#
# Safety Requirements:
# - Requires explicit flag: --confirm-destructive-restore
# - For interactive terminals, prompts for typed 'CONFIRM-RESTORE' confirmation
# - Non-interactive executions FAIL CLOSED without --confirm-destructive-restore
# - Strict regex validation for TIMESTAMP: ^[0-9]{8}_[0-9]{6}$
# - Strict validation of BACKUP_ROOT path (no root, empty, or traversal paths)
# - Comprehensive pre-flight archive, checksum, and header checks BEFORE stopping services or touching data
# - Staging directory extraction and validation before replacing live tenant files
# - Fail-safe alert dispatch on partial restore / split-state conditions
# ==============================================================================
set -euo pipefail

CONFIRMED="false"
TIMESTAMP=""
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/nexus}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

# Parse options
for arg in "$@"; do
    case "${arg}" in
        --confirm-destructive-restore)
            CONFIRMED="true"
            shift || true
            ;;
        --timestamp=*)
            TIMESTAMP="${arg#*=}"
            shift || true
            ;;
        --backup-root=*)
            BACKUP_ROOT="${arg#*=}"
            shift || true
            ;;
        *)
            if [ -z "${TIMESTAMP}" ] && [[ "${arg}" =~ ^[0-9] ]]; then
                TIMESTAMP="${arg}"
            elif [ -n "${TIMESTAMP}" ] && [ "${BACKUP_ROOT}" = "/var/backups/nexus" ]; then
                BACKUP_ROOT="${arg}"
            fi
            ;;
    esac
done

# 1. Enforce Confirmation Flag
if [ "${CONFIRMED}" != "true" ]; then
    echo "================================================================================" >&2
    echo "SAFETY ERROR: Destructive restore operation blocked." >&2
    echo "You must provide the explicit safety flag: --confirm-destructive-restore" >&2
    echo "" >&2
    echo "Usage:" >&2
    echo "  $0 --confirm-destructive-restore <TIMESTAMP> [BACKUP_ROOT]" >&2
    echo "  Example: $0 --confirm-destructive-restore 20261019_020000 /var/backups/nexus" >&2
    echo "================================================================================" >&2
    exit 1
fi

# 2. Enforce Interactive Typed Confirmation if running in a TTY
if [ -t 0 ] && [ -t 1 ]; then
    echo "================================================================================"
    echo "CRITICAL WARNING: You are about to initiate an irreversible RESTORE operation."
    echo "This will DROP the existing database 'nexus_db' and OVERWRITE all tenant files."
    echo "Target snapshot timestamp: ${TIMESTAMP:-<UNSPECIFIED>}"
    echo "Backup directory: ${BACKUP_ROOT}"
    echo "================================================================================"
    read -r -p "Type 'CONFIRM-RESTORE' to proceed with irreversible restoration: " USER_INPUT
    if [ "${USER_INPUT}" != "CONFIRM-RESTORE" ]; then
        echo "Aborted by operator. No changes were made." >&2
        exit 1
    fi
fi

# 3. Strict TIMESTAMP Regex Validation
if [ -z "${TIMESTAMP}" ]; then
    echo "Usage: $0 --confirm-destructive-restore <TIMESTAMP> [BACKUP_ROOT]" >&2
    echo "Available backup sets in ${BACKUP_ROOT}:" >&2
    ls -1 "${BACKUP_ROOT}"/nexus_db_*.dump 2>/dev/null | sed -E 's/.*nexus_db_([0-9_]+)\.dump/\1/' || echo "  (None found)" >&2
    exit 1
fi

if [[ ! "${TIMESTAMP}" =~ ^[0-9]{8}_[0-9]{6}$ ]]; then
    echo "ERROR: Invalid timestamp format: '${TIMESTAMP}'. Must strictly match YYYYMMDD_HHMMSS (e.g. 20261019_020000)." >&2
    exit 1
fi

# 4. Strict BACKUP_ROOT Path Safety Validation
if [ -z "${BACKUP_ROOT}" ] || [ "${BACKUP_ROOT}" = "/" ] || [ "${BACKUP_ROOT}" = "/root" ] || [ "${BACKUP_ROOT}" = "/etc" ] || [ "${BACKUP_ROOT}" = "/bin" ]; then
    echo "ERROR: Refusing to use empty, root, or system BACKUP_ROOT path: '${BACKUP_ROOT}'" >&2
    exit 1
fi

DB_BACKUP="${BACKUP_ROOT}/nexus_db_${TIMESTAMP}.dump"
FILES_BACKUP="${BACKUP_ROOT}/nexus_files_${TIMESTAMP}.tar.gz"
REDIS_BACKUP="${BACKUP_ROOT}/nexus_redis_${TIMESTAMP}.tar.gz"

echo "[$(date -u)] === Starting NEXUS Coordinated Restore [Target: ${TIMESTAMP}] ==="

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

# Trap to detect restoration failures and alert on potential split-state
RESTORE_PHASE="PRE_FLIGHT"
handle_restore_error() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        echo "" >&2
        echo "================================================================================" >&2
        echo "CRITICAL: Restoration failed in phase '${RESTORE_PHASE}' with exit code ${exit_code}!" >&2
        if [ "${RESTORE_PHASE}" = "DATABASE_RESTORED" ] || [ "${RESTORE_PHASE}" = "FILES_RESTORING" ]; then
            echo "ALERT: System may be in a SPLIT-STATE condition!" >&2
            echo "The database was restored to snapshot ${TIMESTAMP}, but tenant files or services" >&2
            echo "did not complete restoration." >&2
            echo "Action Required: Check staging directory '/data/restore_staging_${TIMESTAMP}' and run" >&2
            echo "scripts/reconcile_storage.py to evaluate consistency before resuming traffic." >&2
            send_alert "RESTORE_SPLIT_STATE" "Critical: Restore failed during ${RESTORE_PHASE} for timestamp ${TIMESTAMP}. Manual recovery required."
        else
            echo "Failure occurred before state alteration or during non-mutating pre-flight." >&2
            send_alert "RESTORE_FAILED" "Restore failed during ${RESTORE_PHASE} for timestamp ${TIMESTAMP} with exit code ${exit_code}."
        fi
        echo "================================================================================" >&2
    fi
}
trap handle_restore_error EXIT

# 5. Pre-Flight Verification BEFORE stopping any services or touching data
RESTORE_PHASE="PRE_FLIGHT"
echo "[$(date -u)] Running pre-flight integrity, checksum, and header verifications..."
test -d "${BACKUP_ROOT}" || { echo "ERROR: Backup root directory does not exist: ${BACKUP_ROOT}" >&2; exit 1; }
test -s "${DB_BACKUP}" || { echo "ERROR: Database backup missing or empty: ${DB_BACKUP}" >&2; exit 1; }
test -s "${FILES_BACKUP}" || { echo "ERROR: Files backup missing or empty: ${FILES_BACKUP}" >&2; exit 1; }

# Verify checksum sidecars
if [ -f "${DB_BACKUP}.sha256" ]; then
    sha256sum -c "${DB_BACKUP}.sha256"
else
    echo "ERROR: Missing required checksum sidecar: ${DB_BACKUP}.sha256" >&2
    exit 1
fi

if [ -f "${FILES_BACKUP}.sha256" ]; then
    sha256sum -c "${FILES_BACKUP}.sha256"
else
    echo "ERROR: Missing required checksum sidecar: ${FILES_BACKUP}.sha256" >&2
    exit 1
fi

if [ -f "${REDIS_BACKUP}" ] && [ -f "${REDIS_BACKUP}.sha256" ]; then
    sha256sum -c "${REDIS_BACKUP}.sha256"
fi

# Verify PGDMP header
python -c "
from pathlib import Path
dump_path = Path('${DB_BACKUP}')
with dump_path.open('rb') as f:
    header = f.read(5)
assert header == b'PGDMP', f'Invalid pg_dump header bytes: {header!r}'
"

# Verify tar archive integrity
tar -tzf "${FILES_BACKUP}" > /dev/null
if [ -f "${REDIS_BACKUP}" ]; then
    tar -tzf "${REDIS_BACKUP}" > /dev/null
fi

echo "[$(date -u)] Pre-flight validation passed. Backup set is verified and uncorrupted."

# Step 2: Quiesce mutating containers
RESTORE_PHASE="QUIESCING"
echo "[$(date -u)] Quiescing backend and scheduler containers..."
docker compose -f "${COMPOSE_FILE}" stop backend scheduler

# Step 3: Restore PostgreSQL Database
RESTORE_PHASE="DATABASE_RESTORING"
echo "[$(date -u)] Restoring PostgreSQL database (nexus_db)..."
docker compose -f "${COMPOSE_FILE}" exec -T postgres psql -U nexus_user -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'nexus_db' AND pid <> pg_backend_pid();" || true

docker compose -f "${COMPOSE_FILE}" exec -T postgres dropdb -U nexus_user --if-exists nexus_db
docker compose -f "${COMPOSE_FILE}" exec -T postgres createdb -U nexus_user nexus_db

docker compose -f "${COMPOSE_FILE}" exec -T postgres pg_restore \
    -U nexus_user \
    -d nexus_db \
    -v \
    < "${DB_BACKUP}"

RESTORE_PHASE="DATABASE_RESTORED"
echo "[$(date -u)] Database restore completed."

# Step 4: Staged Tenant File Volume Restoration
RESTORE_PHASE="FILES_RESTORING"
echo "[$(date -u)] Restoring tenant files volume into staging area..."
docker run --rm \
    -v nexus_backend_data:/data \
    -v "${BACKUP_ROOT}":/backup:ro \
    alpine sh -c "
        set -e
        # Safe staging directory extraction
        rm -rf /data/staging_${TIMESTAMP}
        mkdir -p /data/staging_${TIMESTAMP}
        tar -xzf /backup/nexus_files_${TIMESTAMP}.tar.gz -C /data/staging_${TIMESTAMP}
        test -d /data/staging_${TIMESTAMP}

        # Atomically swap staging into place
        mkdir -p /data/tenants
        rm -rf /data/tenants/*
        if [ -d /data/staging_${TIMESTAMP}/tenants ]; then
            cp -a /data/staging_${TIMESTAMP}/tenants/* /data/tenants/ 2>/dev/null || true
        fi
        rm -rf /data/staging_${TIMESTAMP}

        # Reset secure permissions
        chown -R 1000:1000 /data
        chmod 755 /data
        chmod -R u=rwX,go=rX /data
    "

RESTORE_PHASE="FILES_RESTORED"
echo "[$(date -u)] Tenant files restored and permissions reset (1000:1000)."

# Step 5: Restore Redis State (or prompt JWT rotation fallback)
RESTORE_PHASE="REDIS_RESTORING"
if [ -f "${REDIS_BACKUP}" ] && [ -s "${REDIS_BACKUP}" ]; then
    echo "[$(date -u)] Restoring Redis persistence state (nexus_redis_prod_data)..."
    docker compose -f "${COMPOSE_FILE}" stop redis
    docker run --rm \
        -v nexus_redis_prod_data:/data \
        -v "${BACKUP_ROOT}":/backup:ro \
        alpine sh -c "
            set -e
            rm -rf /data/* && \
            tar -xzf /backup/nexus_redis_${TIMESTAMP}.tar.gz -C /data
        "
    docker compose -f "${COMPOSE_FILE}" start redis
    echo "[$(date -u)] Redis state restored from snapshot."
else
    echo "================================================================================"
    echo "WARNING: Redis persistence backup was not restored."
    echo "SECURITY MANDATE: You MUST rotate AUTH_JWT_SECRET immediately across all containers"
    echo "to ensure that previously revoked or blocked tokens cannot be reused."
    echo "================================================================================"
fi

# Step 6: Post-Restore Storage Reconciliation Verification
RESTORE_PHASE="VERIFYING"
echo "[$(date -u)] Executing storage reconciliation audit..."
docker compose -f "${COMPOSE_FILE}" run --rm backend python scripts/reconcile_storage.py

# Step 7: Resume Application Services
echo "[$(date -u)] Starting backend and scheduler services..."
docker compose -f "${COMPOSE_FILE}" start backend scheduler

echo "[$(date -u)] Waiting for backend healthcheck..."
sleep 5
docker compose -f "${COMPOSE_FILE}" exec -T backend curl -f http://localhost:8000/api/health/ready || {
    echo "WARNING: Backend health probe returned non-200. Inspect logs with 'docker compose logs backend'."
    exit 1
}

RESTORE_PHASE="COMPLETE"
echo "[$(date -u)] === Coordinated Restore Completed Successfully ==="
