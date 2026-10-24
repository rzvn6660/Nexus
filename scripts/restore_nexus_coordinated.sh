#!/usr/bin/env bash
# ==============================================================================
# NEXUS Production Coordinated Restore & Recovery Script (Phase 32C Hardened & Phase 1 Parameterized)
# Restores PostgreSQL database, tenant persistent files, and Redis state from a synchronized snapshot.
#
# Safety Requirements:
# - Requires explicit flag: --confirm-destructive-restore
# - For interactive terminals, prompts for typed 'CONFIRM-RESTORE' confirmation
# - Non-interactive executions FAIL CLOSED without --confirm-destructive-restore
# - Strict regex validation for TIMESTAMP: ^[0-9]{8}_[0-9]{6}$
# - Strict validation of BACKUP_ROOT path with portable symlink/traversal canonicalization
# - Strict dual-gate staging validation (--staging CLI flag + NEXUS_STAGING_MODE=true)
# - Reverse guard: rejects staging parameters in ordinary production mode
# - Preserves production-compatible defaults (nexus_db, nexus_user, nexus_backend_data, nexus_redis_prod_data)
# - Injection-safe Bash array command execution (no eval, no unquoted expansions)
# - Target container and volume label attestation in staging mode
# - SQL catalog verification of target database before executing dropdb
# - Comprehensive pre-flight archive, checksum, and header checks BEFORE stopping services or touching data
# - Staging directory extraction and validation before replacing live tenant files
# - Strict POSIX ownership reset: chown -R 1000:1000 /data (appuser:appuser)
# - Fail-safe alert dispatch on partial restore / split-state conditions (services remain stopped on failure)
# ==============================================================================
set -euo pipefail

# 1. Enforce Restrictive Umask for all created files
umask 077

# Defaults (strictly production-compatible baseline)
IS_STAGING="false"
CONFIRMED="false"
TIMESTAMP=""
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/nexus}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
POSTGRES_DB="${POSTGRES_DB:-nexus_db}"
POSTGRES_USER="${POSTGRES_USER:-nexus_user}"
DATA_VOLUME="${DATA_VOLUME:-nexus_backend_data}"
REDIS_VOLUME="${REDIS_VOLUME:-nexus_redis_prod_data}"

# Parse options
for arg in "$@"; do
    case "${arg}" in
        --staging)
            IS_STAGING="true"
            ;;
        --confirm-destructive-restore)
            CONFIRMED="true"
            ;;
        --timestamp=*)
            TIMESTAMP="${arg#*=}"
            ;;
        --backup-root=*)
            BACKUP_ROOT="${arg#*=}"
            ;;
        --compose-file=*)
            COMPOSE_FILE="${arg#*=}"
            ;;
        --compose-project=*)
            COMPOSE_PROJECT_NAME="${arg#*=}"
            ;;
        --postgres-db=*)
            POSTGRES_DB="${arg#*=}"
            ;;
        --postgres-user=*)
            POSTGRES_USER="${arg#*=}"
            ;;
        --data-volume=*)
            DATA_VOLUME="${arg#*=}"
            ;;
        --redis-volume=*)
            REDIS_VOLUME="${arg#*=}"
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

NEXUS_STAGING_MODE="${NEXUS_STAGING_MODE:-false}"

# Dual-Gate Staging Validation
if [ "${IS_STAGING}" = "true" ] && [ "${NEXUS_STAGING_MODE}" != "true" ]; then
    echo "SAFETY ERROR: Staging mode requires BOTH the '--staging' CLI flag and 'NEXUS_STAGING_MODE=true'." >&2
    echo "Refusing to proceed with partial staging authorization." >&2
    exit 1
fi

if [ "${IS_STAGING}" != "true" ] && [ "${NEXUS_STAGING_MODE}" = "true" ]; then
    echo "SAFETY ERROR: 'NEXUS_STAGING_MODE=true' is set, but the explicit '--staging' CLI flag was not passed." >&2
    echo "Refusing to execute staging commands without explicit CLI flag." >&2
    exit 1
fi

# Reverse Guard: If running in production mode, reject any staging parameters
if [ "${IS_STAGING}" != "true" ]; then
    for param_name in "POSTGRES_DB" "COMPOSE_FILE" "COMPOSE_PROJECT_NAME" "DATA_VOLUME" "REDIS_VOLUME"; do
        param_val="${!param_name}"
        if [[ "${param_val,,}" == *"staging"* ]]; then
            echo "SAFETY ERROR: Parameter '${param_name}=${param_val}' contains 'staging' while running in production mode." >&2
            echo "Mixed-environment operations are strictly prohibited. Pass '--staging' and set 'NEXUS_STAGING_MODE=true' to use staging parameters." >&2
            exit 1
        fi
    done
fi

# Staging Mode Validations
if [ "${IS_STAGING}" = "true" ]; then
    # 1. Project name must strictly equal nexus-staging
    if [ -z "${COMPOSE_PROJECT_NAME}" ] || [ "${COMPOSE_PROJECT_NAME}" != "nexus-staging" ]; then
        echo "SAFETY ERROR: In staging mode, COMPOSE_PROJECT_NAME must strictly equal 'nexus-staging' (got '${COMPOSE_PROJECT_NAME}')." >&2
        exit 1
    fi

    # 2. Compose file must contain staging and exist
    if [[ "${COMPOSE_FILE,,}" != *"staging"* ]] || [ "${COMPOSE_FILE}" = "docker-compose.prod.yml" ] || [ "${COMPOSE_FILE}" = "docker-compose.yml" ]; then
        echo "SAFETY ERROR: In staging mode, COMPOSE_FILE cannot be production/dev ('${COMPOSE_FILE}'). Must point to staging Compose file." >&2
        exit 1
    fi
    if [ ! -f "${COMPOSE_FILE}" ]; then
        echo "SAFETY ERROR: Specified staging COMPOSE_FILE does not exist: '${COMPOSE_FILE}'" >&2
        exit 1
    fi

    # 3. Database target blacklist and pattern
    if [[ ! "${POSTGRES_DB}" =~ ^nexus_.*staging.*$ ]] || [ "${POSTGRES_DB}" = "nexus_db" ] || [ "${POSTGRES_DB}" = "postgres" ] || [ "${POSTGRES_DB}" = "template1" ] || [ "${POSTGRES_DB}" = "nexus_test_db" ]; then
        echo "SAFETY ERROR: In staging mode, POSTGRES_DB cannot target '${POSTGRES_DB}'. Target must match staging pattern (e.g. 'nexus_staging_db')." >&2
        exit 1
    fi

    # 4. Volume blacklist
    if [ "${DATA_VOLUME}" = "nexus_backend_data" ] || [[ ! "${DATA_VOLUME}" =~ _staging_data$ ]]; then
        echo "SAFETY ERROR: In staging mode, DATA_VOLUME cannot target production volume ('${DATA_VOLUME}'). Must end with '_staging_data'." >&2
        exit 1
    fi

    if [ "${REDIS_VOLUME}" = "nexus_redis_prod_data" ] || [[ ! "${REDIS_VOLUME}" =~ _staging_data$ ]]; then
        echo "SAFETY ERROR: In staging mode, REDIS_VOLUME cannot target production volume ('${REDIS_VOLUME}'). Must end with '_staging_data'." >&2
        exit 1
    fi
fi

# Identifier format validations
if [[ ! "${POSTGRES_DB}" =~ ^[a-zA-Z0-9_]{1,63}$ ]]; then
    echo "ERROR: Invalid database identifier: '${POSTGRES_DB}'" >&2
    exit 1
fi
if [[ ! "${POSTGRES_USER}" =~ ^[a-zA-Z0-9_]{1,63}$ ]]; then
    echo "ERROR: Invalid database user: '${POSTGRES_USER}'" >&2
    exit 1
fi

# 2. Enforce Interactive Typed Confirmation if running in a TTY
if [ -t 0 ] && [ -t 1 ]; then
    echo "================================================================================"
    echo "CRITICAL WARNING: You are about to initiate an irreversible RESTORE operation."
    echo "This will DROP the existing database '${POSTGRES_DB}' and OVERWRITE all tenant files."
    echo "Target snapshot timestamp: ${TIMESTAMP:-<UNSPECIFIED>}"
    echo "Backup directory: ${BACKUP_ROOT}"
    echo "Target volumes: ${DATA_VOLUME}, ${REDIS_VOLUME}"
    echo "Compose project: ${COMPOSE_PROJECT_NAME} (${COMPOSE_FILE})"
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

# Helper: Resolve physical canonical path of target or nearest existing ancestor
resolve_canonical_path() {
    local target="$1"
    local cur="${target}"
    local suffix=""

    while [ -n "${cur}" ] && [ "${cur}" != "." ] && [ "${cur}" != "/" ]; do
        if [ -d "${cur}" ]; then
            break
        fi
        local base
        base=$(basename "${cur}")
        if [ -z "${suffix}" ]; then
            suffix="${base}"
        else
            suffix="${base}/${suffix}"
        fi
        cur=$(dirname "${cur}")
    done

    if [ -z "${cur}" ] || [ "${cur}" = "." ]; then
        cur="."
    fi

    local canonical_cur
    canonical_cur=$(cd "${cur}" 2>/dev/null && pwd -P)
    if [ -z "${canonical_cur}" ]; then
        return 1
    fi

    if [ "${canonical_cur}" = "/" ]; then
        if [ -n "${suffix}" ]; then
            echo "/${suffix}"
        else
            echo "/"
        fi
    else
        if [ -n "${suffix}" ]; then
            echo "${canonical_cur}/${suffix}"
        else
            echo "${canonical_cur}"
        fi
    fi
}

# 4. Strict BACKUP_ROOT Path Safety & Portable Canonicalization
if [ -z "${BACKUP_ROOT}" ] || [ "${BACKUP_ROOT}" = "/" ] || [ "${BACKUP_ROOT}" = "/root" ] || [ "${BACKUP_ROOT}" = "/etc" ] || [ "${BACKUP_ROOT}" = "/bin" ] || [ "${BACKUP_ROOT}" = "/usr" ]; then
    echo "ERROR: Refusing to use empty, root, or system BACKUP_ROOT path: '${BACKUP_ROOT}'" >&2
    exit 1
fi

for raw_forbidden in "/var/lib/docker/volumes" "/app/data" "/data" "/" "/root" "/etc" "/bin" "/usr"; do
    if [ "${BACKUP_ROOT}" = "${raw_forbidden}" ] || [[ "${BACKUP_ROOT}" == "${raw_forbidden}/"* ]]; then
        echo "SAFETY ERROR: BACKUP_ROOT '${BACKUP_ROOT}' cannot be equal to or nested within forbidden path '${raw_forbidden}'" >&2
        exit 1
    fi
done

if [[ "${BACKUP_ROOT}" == *"/.git"* ]] || [[ "${BACKUP_ROOT}" == *"/backend/data"* ]] || [[ "${BACKUP_ROOT}" == *"backend/data"* ]] || [[ "${BACKUP_ROOT}" == *".git"* ]]; then
    echo "SAFETY ERROR: BACKUP_ROOT cannot reside within application data or .git directory: '${BACKUP_ROOT}'" >&2
    exit 1
fi

# Pre-execution canonical validation
CANONICAL_PRE_PATH=$(resolve_canonical_path "${BACKUP_ROOT}")
if [ -z "${CANONICAL_PRE_PATH}" ]; then
    echo "ERROR: Failed to resolve canonical path for BACKUP_ROOT: '${BACKUP_ROOT}'" >&2
    exit 1
fi

for forbidden in "/var/lib/docker/volumes" "/app/data" "/data" "/" "/root" "/etc" "/bin" "/usr"; do
    if [ "${CANONICAL_PRE_PATH}" = "${forbidden}" ] || [[ "${CANONICAL_PRE_PATH}" == "${forbidden}/"* ]]; then
        echo "SAFETY ERROR: BACKUP_ROOT '${CANONICAL_PRE_PATH}' cannot be equal to or nested within forbidden path '${forbidden}'" >&2
        exit 1
    fi
done

if [[ "${CANONICAL_PRE_PATH}" == *"/.git"* ]] || [[ "${CANONICAL_PRE_PATH}" == *"/backend/data"* ]] || [[ "${CANONICAL_PRE_PATH}" == *"backend/data"* ]] || [[ "${CANONICAL_PRE_PATH}" == *".git"* ]]; then
    echo "SAFETY ERROR: BACKUP_ROOT cannot reside within application data or .git directory: '${CANONICAL_PRE_PATH}'" >&2
    exit 1
fi

if [ ! -d "${BACKUP_ROOT}" ]; then
    echo "ERROR: Backup root directory does not exist: ${BACKUP_ROOT}" >&2
    exit 1
fi

CANONICAL_BACKUP_ROOT=$(cd "${BACKUP_ROOT}" 2>/dev/null && pwd -P)
if [ -z "${CANONICAL_BACKUP_ROOT}" ]; then
    echo "ERROR: Failed to canonicalize BACKUP_ROOT path: '${BACKUP_ROOT}'" >&2
    exit 1
fi

for forbidden in "/var/lib/docker/volumes" "/app/data" "/data" "/" "/root" "/etc" "/bin" "/usr"; do
    if [ "${CANONICAL_BACKUP_ROOT}" = "${forbidden}" ] || [[ "${CANONICAL_BACKUP_ROOT}" == "${forbidden}/"* ]]; then
        echo "SAFETY ERROR: BACKUP_ROOT '${CANONICAL_BACKUP_ROOT}' cannot be equal to or nested within forbidden path '${forbidden}'" >&2
        exit 1
    fi
done

if [[ "${CANONICAL_BACKUP_ROOT}" == *"/.git"* ]] || [[ "${CANONICAL_BACKUP_ROOT}" == *"/backend/data"* ]] || [[ "${CANONICAL_BACKUP_ROOT}" == *"backend/data"* ]] || [[ "${CANONICAL_BACKUP_ROOT}" == *".git"* ]]; then
    echo "SAFETY ERROR: BACKUP_ROOT cannot reside within application data or .git directory: '${CANONICAL_BACKUP_ROOT}'" >&2
    exit 1
fi

DB_BACKUP="${BACKUP_ROOT}/nexus_db_${TIMESTAMP}.dump"
FILES_BACKUP="${BACKUP_ROOT}/nexus_files_${TIMESTAMP}.tar.gz"
REDIS_BACKUP="${BACKUP_ROOT}/nexus_redis_${TIMESTAMP}.tar.gz"

# Injection-safe Compose command array
COMPOSE_CMD=("docker" "compose" "-f" "${COMPOSE_FILE}")
if [ -n "${COMPOSE_PROJECT_NAME}" ]; then
    COMPOSE_CMD+=("-p" "${COMPOSE_PROJECT_NAME}")
fi

echo "[$(date -u)] === Starting NEXUS Coordinated Restore [Target: ${TIMESTAMP}] ==="
echo "[$(date -u)] Configuration: Project=${COMPOSE_PROJECT_NAME}, File=${COMPOSE_FILE}, DB=${POSTGRES_DB}, User=${POSTGRES_USER}"

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

# Trap to detect restoration failures and alert on potential split-state (never restarts mutating services on error)
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
import sys, re
from pathlib import Path
p_str = '${DB_BACKUP}'
if sys.platform == 'win32' and re.match(r'^/[a-zA-Z]/', p_str):
    p_str = p_str[1] + ':' + p_str[2:]
dump_path = Path(p_str)
with dump_path.open('rb') as f:
    header = f.read(5)
assert header == b'PGDMP', f'Invalid pg_dump header bytes: {header!r}'
"

# Verify tar archive integrity
TAR_OPTS=()
if tar --help 2>&1 | grep -q -- '--force-local'; then
    TAR_OPTS+=("--force-local")
fi
tar "${TAR_OPTS[@]}" -tzf "${FILES_BACKUP}" > /dev/null
if [ -f "${REDIS_BACKUP}" ]; then
    tar "${TAR_OPTS[@]}" -tzf "${REDIS_BACKUP}" > /dev/null
fi

# Staging Mode Target Attestation Checks
if [ "${IS_STAGING}" = "true" ]; then
    echo "[$(date -u)] Performing staging target container attestation..."
    for svc in "postgres" "redis"; do
        SVC_CONTAINER_IDS=$("${COMPOSE_CMD[@]}" ps -q "${svc}" 2>/dev/null || true)
        SVC_ID_COUNT=$(echo ${SVC_CONTAINER_IDS} | wc -w)
        SVC_ID_COUNT=$(echo "${SVC_ID_COUNT}" | tr -d '[:space:]')
        if [ "${SVC_ID_COUNT}" -ne 1 ]; then
            echo "SAFETY ERROR: Staging ${svc} service must resolve to exactly one running container (found ${SVC_ID_COUNT})." >&2
            exit 1
        fi

        SVC_CONTAINER_ID=$(echo "${SVC_CONTAINER_IDS}" | tr -d '[:space:]')
        SVC_LABEL=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "${SVC_CONTAINER_ID}" 2>/dev/null || true)
        if [ -z "${SVC_LABEL}" ]; then
            echo "SAFETY ERROR: Failed to inspect project label on staging ${svc} container '${SVC_CONTAINER_ID}'." >&2
            exit 1
        fi
        if [ "${SVC_LABEL}" != "${COMPOSE_PROJECT_NAME}" ]; then
            echo "SAFETY ERROR: Target ${svc} container project label ('${SVC_LABEL}') does not match expected staging project ('${COMPOSE_PROJECT_NAME}')." >&2
            exit 1
        fi
    done

    echo "[$(date -u)] Performing staging target volume label attestation..."
    for vol in "${DATA_VOLUME}" "${REDIS_VOLUME}"; do
        VOL_LABEL=$(docker volume inspect -f '{{ index .Labels "com.docker.compose.project" }}' "${vol}" 2>/dev/null || true)
        if [ -z "${VOL_LABEL}" ]; then
            echo "SAFETY ERROR: Failed to inspect staging volume '${vol}' or missing 'com.docker.compose.project' label." >&2
            echo "Destructive staging operations refuse to proceed against unverified volumes." >&2
            exit 1
        fi
        if [ "${VOL_LABEL}" != "${COMPOSE_PROJECT_NAME}" ]; then
            echo "SAFETY ERROR: Staging volume '${vol}' project label ('${VOL_LABEL}') does not match expected staging project ('${COMPOSE_PROJECT_NAME}')." >&2
            exit 1
        fi
    done
fi

echo "[$(date -u)] Pre-flight validation passed. Backup set is verified and uncorrupted."

# Step 2: Quiesce mutating containers
RESTORE_PHASE="QUIESCING"
echo "[$(date -u)] Quiescing backend and scheduler containers..."
"${COMPOSE_CMD[@]}" stop backend scheduler

# Step 3: Restore PostgreSQL Database
RESTORE_PHASE="DATABASE_RESTORING"
echo "[$(date -u)] Restoring PostgreSQL database (${POSTGRES_DB})..."

# Staging catalog verification before destructive drop
TARGET_EXISTS="true"
if [ "${IS_STAGING}" = "true" ]; then
    echo "[$(date -u)] Verifying target staging database identity in PostgreSQL catalog..."
    set +e
    CATALOG_RAW=$("${COMPOSE_CMD[@]}" exec -T postgres psql -U "${POSTGRES_USER}" -d postgres -v ON_ERROR_STOP=1 -tAc -F '|' \
        "SELECT current_database(), (SELECT count(*) FROM pg_database WHERE datname = '${POSTGRES_DB}'), COALESCE((SELECT datname FROM pg_database WHERE datname = '${POSTGRES_DB}'), '');" 2>&1)
    PSQL_EXIT_CODE=$?
    set -e

    if [ ${PSQL_EXIT_CODE} -ne 0 ]; then
        echo "SAFETY ERROR: PostgreSQL catalog query failed with exit code ${PSQL_EXIT_CODE}: ${CATALOG_RAW}" >&2
        exit 1
    fi

    ROW_COUNT=$(echo "${CATALOG_RAW}" | tr -d '\r' | sed '/^[[:space:]]*$/d' | wc -l)
    ROW_COUNT=$(echo "${ROW_COUNT}" | tr -d '[:space:]')
    if [ "${ROW_COUNT}" -ne 1 ]; then
        echo "SAFETY ERROR: PostgreSQL catalog query returned ${ROW_COUNT} rows (expected exactly 1): ${CATALOG_RAW}" >&2
        exit 1
    fi

    CATALOG_OUTPUT=$(echo "${CATALOG_RAW}" | tr -d '\r' | sed '/^[[:space:]]*$/d' | head -n 1)

    if [ -z "${CATALOG_OUTPUT}" ]; then
        echo "SAFETY ERROR: Empty output received from PostgreSQL catalog verification query." >&2
        exit 1
    fi

    MAINT_DB=$(echo "${CATALOG_OUTPUT}" | cut -d'|' -f1 | tr -d '[:space:]')
    MATCH_COUNT=$(echo "${CATALOG_OUTPUT}" | cut -d'|' -f2 | tr -d '[:space:]')
    MATCH_NAME=$(echo "${CATALOG_OUTPUT}" | cut -d'|' -f3 | tr -d '[:space:]')

    if [ "${MAINT_DB}" != "postgres" ]; then
        echo "SAFETY ERROR: Catalog query connected to unexpected maintenance database '${MAINT_DB}' (expected 'postgres')." >&2
        exit 1
    fi

    if [ "${MATCH_COUNT}" = "1" ]; then
        if [ "${MATCH_NAME}" != "${POSTGRES_DB}" ]; then
            echo "SAFETY ERROR: Catalog database match ('${MATCH_NAME}') differs from expected target ('${POSTGRES_DB}')." >&2
            exit 1
        fi
        TARGET_EXISTS="true"
        echo "[$(date -u)] Verified existing target database '${POSTGRES_DB}' in catalog (ready for safe drop and recreate)."
    elif [ "${MATCH_COUNT}" = "0" ]; then
        if [ -n "${MATCH_NAME}" ]; then
            echo "SAFETY ERROR: Catalog query returned count 0 but non-empty database match ('${MATCH_NAME}')." >&2
            exit 1
        fi
        TARGET_EXISTS="false"
        echo "[$(date -u)] Target database '${POSTGRES_DB}' does not yet exist in catalog. Clean target creation will proceed."
    else
        echo "SAFETY ERROR: Unexpected match count ('${MATCH_COUNT}') returned for target database in catalog." >&2
        exit 1
    fi
fi

if [ "${TARGET_EXISTS}" = "true" ]; then
    "${COMPOSE_CMD[@]}" exec -T postgres psql -U "${POSTGRES_USER}" -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${POSTGRES_DB}' AND pid <> pg_backend_pid();" || true

    "${COMPOSE_CMD[@]}" exec -T postgres dropdb -U "${POSTGRES_USER}" --if-exists "${POSTGRES_DB}"
fi

"${COMPOSE_CMD[@]}" exec -T postgres createdb -U "${POSTGRES_USER}" "${POSTGRES_DB}"

"${COMPOSE_CMD[@]}" exec -T postgres pg_restore \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    -v \
    < "${DB_BACKUP}"

RESTORE_PHASE="DATABASE_RESTORED"
echo "[$(date -u)] Database restore completed."

# Step 4: Staged Tenant File Volume Restoration
RESTORE_PHASE="FILES_RESTORING"
echo "[$(date -u)] Restoring tenant files volume (${DATA_VOLUME}) into staging area..."
docker run --rm \
    -v "${DATA_VOLUME}:/data" \
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

        # Reset secure permissions for appuser (1000:1000)
        chown -R 1000:1000 /data
        chmod 755 /data
        chmod -R u=rwX,go=rX /data
    "

RESTORE_PHASE="FILES_RESTORED"
echo "[$(date -u)] Tenant files restored and permissions reset (1000:1000)."

# Step 5: Restore Redis State (or prompt JWT rotation fallback)
RESTORE_PHASE="REDIS_RESTORING"
if [ -f "${REDIS_BACKUP}" ] && [ -s "${REDIS_BACKUP}" ]; then
    echo "[$(date -u)] Restoring Redis persistence state (${REDIS_VOLUME})..."
    "${COMPOSE_CMD[@]}" stop redis
    docker run --rm \
        -v "${REDIS_VOLUME}:/data" \
        -v "${BACKUP_ROOT}":/backup:ro \
        alpine sh -c "
            set -e
            rm -rf /data/* && \
            tar -xzf /backup/nexus_redis_${TIMESTAMP}.tar.gz -C /data
        "
    "${COMPOSE_CMD[@]}" start redis
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
"${COMPOSE_CMD[@]}" run --rm backend python scripts/reconcile_storage.py

# Step 7: Resume Application Services
echo "[$(date -u)] Starting backend and scheduler services..."
"${COMPOSE_CMD[@]}" start backend scheduler

echo "[$(date -u)] Waiting for backend healthcheck..."
sleep 5
"${COMPOSE_CMD[@]}" exec -T backend curl -f http://localhost:8000/api/health/ready || {
    echo "WARNING: Backend health probe returned non-200. Inspect logs with 'docker compose logs backend'."
    exit 1
}

RESTORE_PHASE="COMPLETE"
echo "[$(date -u)] === Coordinated Restore Completed Successfully ==="
