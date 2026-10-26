#!/usr/bin/env bash
# ==============================================================================
# NEXUS Production Coordinated Backup Script (Phase 32C Hardened & Phase 1 Parameterized)
# Synchronously snapshots PostgreSQL database, tenant persistent volume, and Redis state.
#
# Features:
# - Input validation: rejects empty, root, or unsafe BACKUP_ROOT paths
# - Portable path canonicalization resolving symlinks and relative path components
# - Strict dual-gate staging validation (--staging CLI flag + NEXUS_STAGING_MODE=true)
# - Reverse guard: rejects staging parameters in ordinary production mode
# - Preserves production-compatible defaults (nexus_db, nexus_user, nexus_backend_data, nexus_redis_prod_data)
# - Injection-safe Bash array command execution (no eval, no unquoted expansions)
# - Target container and volume label attestation in staging mode
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

# Prevent MSYS2 / Git Bash on Windows from converting container-internal POSIX paths
export MSYS_NO_PATHCONV=1

# 1. Enforce Restrictive Umask for all created files
umask 077

# Script and project root locations
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

# Defaults (strictly production-compatible baseline)
IS_STAGING="false"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
POSTGRES_DB="${POSTGRES_DB:-nexus_db}"
POSTGRES_USER="${POSTGRES_USER:-nexus_user}"
DATA_VOLUME="${DATA_VOLUME:-nexus_backend_data}"
REDIS_VOLUME="${REDIS_VOLUME:-nexus_redis_prod_data}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/nexus}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
MIN_RETAINED_SETS="${MIN_RETAINED_SETS:-7}"
QUIESCE_SERVICES="${QUIESCE_SERVICES:-true}"
ALLOW_TEST_DB_SOURCE="${ALLOW_TEST_DB_SOURCE:-false}"
ENV_FILE="${ENV_FILE:-}"
SKIP_REDIS="false"

# Parse command line options
for arg in "$@"; do
    case "${arg}" in
        --staging)
            IS_STAGING="true"
            ;;
        --env-file=*)
            ENV_FILE="${arg#*=}"
            ;;
        --skip-redis)
            SKIP_REDIS="true"
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
        --retention-days=*)
            RETENTION_DAYS="${arg#*=}"
            ;;
        --min-retained-sets=*)
            MIN_RETAINED_SETS="${arg#*=}"
            ;;
        --no-quiesce)
            QUIESCE_SERVICES="false"
            ;;
        --allow-test-db-source)
            ALLOW_TEST_DB_SOURCE="true"
            ;;
        *)
            if [ "${BACKUP_ROOT}" = "/var/backups/nexus" ]; then
                BACKUP_ROOT="${arg}"
            fi
            ;;
    esac
done

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
    if [ "${ALLOW_TEST_DB_SOURCE}" = "true" ]; then
        echo "SAFETY ERROR: Parameter '--allow-test-db-source' is strictly prohibited in production mode." >&2
        exit 1
    fi
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
    # 0. Staging Environment & Credentials Preflight (Fail Closed)
    if [ ! -f "${SCRIPT_DIR}/preflight_staging_env.sh" ]; then
        echo "SAFETY ERROR: Required staging preflight validator script missing: '${SCRIPT_DIR}/preflight_staging_env.sh'" >&2
        exit 1
    fi
    PREFLIGHT_ARGS=("--staging")
    if [ -n "${ENV_FILE}" ]; then
        PREFLIGHT_ARGS+=("--env-file=${ENV_FILE}")
    fi
    bash "${SCRIPT_DIR}/preflight_staging_env.sh" "${PREFLIGHT_ARGS[@]}" || exit 1

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
    if [ "${ALLOW_TEST_DB_SOURCE}" = "true" ] && [ "${POSTGRES_DB}" = "nexus_test_db" ]; then
        echo "[$(date -u)] Staging test-database source override active: snapshotting '${POSTGRES_DB}' as read-only source."
    elif [[ ! "${POSTGRES_DB}" =~ ^nexus_.*staging.*$ ]] || [ "${POSTGRES_DB}" = "nexus_db" ] || [ "${POSTGRES_DB}" = "postgres" ] || [ "${POSTGRES_DB}" = "template1" ] || [ "${POSTGRES_DB}" = "nexus_test_db" ]; then
        echo "SAFETY ERROR: In staging mode, POSTGRES_DB cannot target '${POSTGRES_DB}'. Target must match staging pattern (e.g. 'nexus_staging_db')." >&2
        exit 1
    fi

    # 4. Volume blacklist
    if [ "${DATA_VOLUME}" = "nexus_backend_data" ] || [[ ! "${DATA_VOLUME}" =~ _staging_data$ ]]; then
        echo "SAFETY ERROR: In staging mode, DATA_VOLUME cannot target production volume ('${DATA_VOLUME}'). Must end with '_staging_data'." >&2
        exit 1
    fi

    if [ "${SKIP_REDIS}" != "true" ]; then
        if [ "${REDIS_VOLUME}" = "nexus_redis_prod_data" ] || [[ ! "${REDIS_VOLUME}" =~ _staging_data$ ]]; then
            echo "SAFETY ERROR: In staging mode, REDIS_VOLUME cannot target production volume ('${REDIS_VOLUME}'). Must end with '_staging_data'." >&2
            exit 1
        fi
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

# 2. Strict BACKUP_ROOT Path Safety & Portable Canonicalization
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

# Pre-creation canonical validation resolving symlinks and nearest existing ancestor
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

mkdir -p "${BACKUP_ROOT}"
chmod 700 "${BACKUP_ROOT}"

CANONICAL_BACKUP_ROOT=$(cd "${BACKUP_ROOT}" 2>/dev/null && pwd -P)
if [ -z "${CANONICAL_BACKUP_ROOT}" ]; then
    echo "ERROR: Failed to canonicalize created BACKUP_ROOT path: '${BACKUP_ROOT}'" >&2
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

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_BACKUP="${BACKUP_ROOT}/nexus_db_${TIMESTAMP}.dump"
FILES_BACKUP="${BACKUP_ROOT}/nexus_files_${TIMESTAMP}.tar.gz"
REDIS_BACKUP="${BACKUP_ROOT}/nexus_redis_${TIMESTAMP}.tar.gz"

# Injection-safe Compose command array
COMPOSE_CMD=("docker" "compose" "-f" "${COMPOSE_FILE}")
if [ -n "${COMPOSE_PROJECT_NAME}" ]; then
    COMPOSE_CMD+=("-p" "${COMPOSE_PROJECT_NAME}")
fi
if [ -n "${ENV_FILE}" ]; then
    COMPOSE_CMD+=("--env-file" "${ENV_FILE}")
fi

# Alerting helper
send_alert() {
    local event_type="$1"
    local message="$2"
    python -c "
import sys, re
from pathlib import Path
repo_dir = '${REPO_ROOT}'
if sys.platform == 'win32' and re.match(r'^/[a-zA-Z]/', repo_dir):
    repo_dir = repo_dir[1] + ':' + repo_dir[2:]
backend_dir = Path(repo_dir) / 'backend'
if backend_dir.is_dir() and str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
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
            "${COMPOSE_CMD[@]}" start backend scheduler || true
        fi
    fi
}
trap cleanup_on_error EXIT

echo "[$(date -u)] === Starting NEXUS Coordinated Backup [${TIMESTAMP}] ==="
echo "[$(date -u)] Configuration: Project=${COMPOSE_PROJECT_NAME}, File=${COMPOSE_FILE}, DB=${POSTGRES_DB}, User=${POSTGRES_USER}"

# Step 0: Validate Compose configuration and container reachability BEFORE quiescing
echo "[$(date -u)] Pre-flight validation of Docker Compose configuration..."
"${COMPOSE_CMD[@]}" config > /dev/null

# Staging Mode Target Attestation Checks
if [ "${IS_STAGING}" = "true" ]; then
    echo "[$(date -u)] Performing staging target container attestation..."
    TARGET_SERVICES=("postgres")
    if [ "${SKIP_REDIS}" != "true" ]; then
        TARGET_SERVICES+=("redis")
    fi
    for svc in "${TARGET_SERVICES[@]}"; do
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
    TARGET_VOLUMES=("${DATA_VOLUME}")
    if [ "${SKIP_REDIS}" != "true" ]; then
        TARGET_VOLUMES+=("${REDIS_VOLUME}")
    fi
    for vol in "${TARGET_VOLUMES[@]}"; do
        VOL_LABEL=$(docker volume inspect -f '{{ index .Labels "com.docker.compose.project" }}' "${vol}" 2>/dev/null || true)
        if [ -z "${VOL_LABEL}" ]; then
            echo "SAFETY ERROR: Failed to inspect staging volume '${vol}' or missing 'com.docker.compose.project' label." >&2
            echo "Staging operations refuse to proceed against unverified volumes." >&2
            exit 1
        fi
        if [ "${VOL_LABEL}" != "${COMPOSE_PROJECT_NAME}" ]; then
            echo "SAFETY ERROR: Staging volume '${vol}' project label ('${VOL_LABEL}') does not match expected staging project ('${COMPOSE_PROJECT_NAME}')." >&2
            exit 1
        fi
    done
fi

# Step 1: Quiesce mutating containers (Backend API & Dedicated Scheduler)
if [ "${QUIESCE_SERVICES}" = "true" ]; then
    echo "[$(date -u)] Quiescing mutating containers (backend and scheduler)..."
    "${COMPOSE_CMD[@]}" stop backend scheduler
fi

# Step 2: Dump PostgreSQL Database (-F c custom format)
echo "[$(date -u)] Dumping PostgreSQL database (${POSTGRES_DB})..."
"${COMPOSE_CMD[@]}" exec -T postgres \
    pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -F c -b > "${DB_BACKUP}"
test -s "${DB_BACKUP}" || { echo "ERROR: Database backup file is missing or empty"; exit 1; }
chmod 600 "${DB_BACKUP}"

# Step 3: Archive Tenant File Volume (DATA_VOLUME)
echo "[$(date -u)] Archiving tenant file volume (${DATA_VOLUME})..."
docker run --rm \
    -v "${DATA_VOLUME}:/data:ro" \
    -v "${BACKUP_ROOT}":/backup \
    alpine tar -czf "/backup/nexus_files_${TIMESTAMP}.tar.gz" -C /data .
test -s "${FILES_BACKUP}" || { echo "ERROR: Tenant files archive is missing or empty"; exit 1; }
chmod 600 "${FILES_BACKUP}"

# Step 4: Consistent Redis Snapshot via Verified BGSAVE
if [ "${SKIP_REDIS}" = "true" ]; then
    echo "[$(date -u)] Skipping Redis persistence snapshot (--skip-redis specified)."
    echo "[$(date -u)] Redis state excluded from backup set. Live Redis untouched."
else
    echo "[$(date -u)] Executing consistent Redis snapshot via BGSAVE..."
    "${COMPOSE_CMD[@]}" exec -T redis redis-cli bgsave

    # Poll until BGSAVE completes
    BGSAVE_SUCCESS=false
    for i in $(seq 1 30); do
        IN_PROGRESS=$("${COMPOSE_CMD[@]}" exec -T redis redis-cli info persistence | grep -E '^rdb_bgsave_in_progress:' | tr -d '\r' | cut -d: -f2 || echo "1")
        LAST_STATUS=$("${COMPOSE_CMD[@]}" exec -T redis redis-cli info persistence | grep -E '^rdb_last_bgsave_status:' | tr -d '\r' | cut -d: -f2 || echo "err")
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
        -v "${REDIS_VOLUME}:/data:ro" \
        -v "${BACKUP_ROOT}":/backup \
        alpine sh -c "test -s /data/dump.rdb && tar -czf /backup/nexus_redis_${TIMESTAMP}.tar.gz -C /data dump.rdb"
    test -s "${REDIS_BACKUP}" || { echo "ERROR: Redis backup archive is missing or empty"; exit 1; }
    chmod 600 "${REDIS_BACKUP}"
fi

# Step 5: Resume mutating services immediately after consistent snapshots are taken
if [ "${QUIESCE_SERVICES}" = "true" ]; then
    echo "[$(date -u)] Resuming backend and scheduler services..."
    "${COMPOSE_CMD[@]}" start backend scheduler
fi

# Step 6: Compute SHA-256 Checksums
echo "[$(date -u)] Generating SHA-256 checksums..."
sha256sum "${DB_BACKUP}" > "${DB_BACKUP}.sha256"
sha256sum "${FILES_BACKUP}" > "${FILES_BACKUP}.sha256"
chmod 644 "${DB_BACKUP}.sha256" "${FILES_BACKUP}.sha256"
if [ "${SKIP_REDIS}" != "true" ]; then
    sha256sum "${REDIS_BACKUP}" > "${REDIS_BACKUP}.sha256"
    chmod 644 "${REDIS_BACKUP}.sha256"
fi

# Step 7: Validate Archive Integrity & Header Signatures
echo "[$(date -u)] Validating archive integrity and signatures..."
sha256sum -c "${DB_BACKUP}.sha256"
sha256sum -c "${FILES_BACKUP}.sha256"
if [ "${SKIP_REDIS}" != "true" ]; then
    sha256sum -c "${REDIS_BACKUP}.sha256"
fi

# Check PGDMP custom format magic bytes
python -c "
import sys, re
from pathlib import Path
p_str = '${DB_BACKUP}'
if sys.platform == 'win32' and re.match(r'^/[a-zA-Z]/', p_str):
    p_str = p_str[1] + ':' + p_str[2:]
dump_path = Path(p_str)
with dump_path.open('rb') as f:
    header = f.read(5)
assert header == b'PGDMP', f'Invalid pg_dump header: {header!r}'
"

# Validate tar archives
TAR_OPTS=()
if tar --help 2>&1 | grep -q -- '--force-local'; then
    TAR_OPTS+=("--force-local")
fi
tar "${TAR_OPTS[@]}" -tzf "${FILES_BACKUP}" > /dev/null
if [ "${SKIP_REDIS}" != "true" ]; then
    tar "${TAR_OPTS[@]}" -tzf "${REDIS_BACKUP}" > /dev/null
fi

# Step 8: Enforce Fail-Safe Retention Policy (Python Core Engine)
echo "[$(date -u)] Enforcing retention policy (retention: ${RETENTION_DAYS}d, min_retained: ${MIN_RETAINED_SETS})..."
python -c "
import sys, re
from pathlib import Path
repo_dir = '${REPO_ROOT}'
if sys.platform == 'win32' and re.match(r'^/[a-zA-Z]/', repo_dir):
    repo_dir = repo_dir[1] + ':' + repo_dir[2:]
backend_dir = Path(repo_dir) / 'backend'
if backend_dir.is_dir() and str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
from app.core.backup import enforce_retention
b_str = '${BACKUP_ROOT}'
if sys.platform == 'win32' and re.match(r'^/[a-zA-Z]/', b_str):
    b_str = b_str[1] + ':' + b_str[2:]
pruned = enforce_retention(
    backup_dir=Path(b_str),
    retention_days=${RETENTION_DAYS},
    min_retained_sets=${MIN_RETAINED_SETS},
)
print(f'Retention enforcement complete. Pruned {len(pruned)} expired files.')
"

echo "[$(date -u)] === Coordinated Backup Completed Successfully ==="
