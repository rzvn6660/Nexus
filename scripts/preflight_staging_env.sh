#!/bin/bash
# ==============================================================================
# NEXUS Staging Environment & Credentials Preflight Validator
#
# Validates required environment variables and credentials before runtime operations.
# Strictly non-mutating and fail-closed: stops execution before any Docker,
# database, volume, backup, or restore mutation.
#
# NEVER prints or echoes secret values.
# ==============================================================================
set -euo pipefail

ENV_FILE=""
IS_STAGING="false"
REQUIRE_APP_SECRETS="true"

for arg in "$@"; do
    case "${arg}" in
        --env-file=*)
            ENV_FILE="${arg#*=}"
            ;;
        --staging)
            IS_STAGING="true"
            ;;
        --skip-app-secrets)
            REQUIRE_APP_SECRETS="false"
            ;;
        --require-app-secrets)
            REQUIRE_APP_SECRETS="true"
            ;;
        *)
            ;;
    esac
done

# If an env-file was provided, source it safely
if [ -n "${ENV_FILE}" ]; then
    if [ ! -f "${ENV_FILE}" ]; then
        echo "SAFETY ERROR: Specified --env-file does not exist: '${ENV_FILE}'" >&2
        exit 1
    fi
    # Export variables from file without printing contents
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

ERRORS=0

# Helper: Log validation error without revealing secrets
log_sec_error() {
    local var_name="$1"
    local reason="$2"
    echo "SAFETY ERROR: Environment variable '${var_name}' ${reason}." >&2
    ERRORS=$((ERRORS + 1))
}

# 1. Staging Mode Attestation
NEXUS_STAGING_MODE="${NEXUS_STAGING_MODE:-false}"
if [ "${IS_STAGING}" = "true" ] && [ "${NEXUS_STAGING_MODE}" != "true" ]; then
    echo "SAFETY ERROR: NEXUS_STAGING_MODE must be set to 'true' in staging environment." >&2
    ERRORS=$((ERRORS + 1))
fi

# 2. Invariants Check
REQUIRE_POSTGRES="${REQUIRE_POSTGRES:-true}"
if [ "${REQUIRE_POSTGRES}" != "true" ]; then
    echo "SAFETY ERROR: Invariant violation: REQUIRE_POSTGRES must be 'true' (got '${REQUIRE_POSTGRES}')." >&2
    ERRORS=$((ERRORS + 1))
fi

LLM_ALLOW_EXTERNAL_CALLS="${LLM_ALLOW_EXTERNAL_CALLS:-false}"
if [ "${LLM_ALLOW_EXTERNAL_CALLS}" != "false" ]; then
    echo "SAFETY ERROR: Invariant violation: LLM_ALLOW_EXTERNAL_CALLS must be 'false' (got '${LLM_ALLOW_EXTERNAL_CALLS}')." >&2
    ERRORS=$((ERRORS + 1))
fi

# Forbidden insecure default values / placeholders
FORBIDDEN_PASSWORDS=(
    "nexus_staging_password"
    "replace-with-disposable-staging-password"
    "GENERATE_SECURE_PASSWORD_MIN_16_CHARS"
    "password"
    "postgres"
    "admin"
    "nexus"
    "changeme"
    "123456"
    "12345678"
)

FORBIDDEN_APP_SECRETS=(
    "nexus-staging-secret-key-change-me"
    "replace-with-staging-secret-key-min-32-chars"
    "GENERATE_SECURE_SECRET_MIN_32_CHARS"
    "nexus-staging-jwt-secret-key-change-in-staging-min-32-chars"
    "replace-with-staging-jwt-secret-min-32-chars"
    "secret"
    "changeme"
)

# 3. Database Password Validation (POSTGRES_PASSWORD or STAGING_DB_PASSWORD)
DB_PASS="${POSTGRES_PASSWORD:-${STAGING_DB_PASSWORD:-}}"
DB_VAR_NAME="POSTGRES_PASSWORD"
if [ -z "${POSTGRES_PASSWORD:-}" ] && [ -n "${STAGING_DB_PASSWORD:-}" ]; then
    DB_VAR_NAME="STAGING_DB_PASSWORD"
fi

if [ -z "${DB_PASS}" ]; then
    log_sec_error "POSTGRES_PASSWORD (or STAGING_DB_PASSWORD)" "is unset or empty"
else
    # Check length
    PASS_LEN=$(printf "%s" "${DB_PASS}" | wc -c | tr -d '[:space:]')
    if [ "${PASS_LEN}" -lt 16 ]; then
        log_sec_error "${DB_VAR_NAME}" "length (${PASS_LEN}) is below required minimum of 16 characters"
    fi

    # Check against known insecure defaults
    for bad_val in "${FORBIDDEN_PASSWORDS[@]}"; do
        if [ "${DB_PASS}" = "${bad_val}" ]; then
            log_sec_error "${DB_VAR_NAME}" "matches known insecure default or placeholder value"
            break
        fi
    done
fi

# 4. App Secrets Validation (SECRET_KEY & AUTH_JWT_SECRET)
if [ "${REQUIRE_APP_SECRETS}" = "true" ]; then
    # SECRET_KEY
    if [ -z "${SECRET_KEY:-}" ]; then
        log_sec_error "SECRET_KEY" "is unset or empty"
    else
        SK_LEN=$(printf "%s" "${SECRET_KEY}" | wc -c | tr -d '[:space:]')
        if [ "${SK_LEN}" -lt 32 ]; then
            log_sec_error "SECRET_KEY" "length (${SK_LEN}) is below required minimum of 32 characters"
        fi
        for bad_val in "${FORBIDDEN_APP_SECRETS[@]}"; do
            if [ "${SECRET_KEY}" = "${bad_val}" ]; then
                log_sec_error "SECRET_KEY" "matches known insecure default or placeholder value"
                break
            fi
        done
    fi

    # AUTH_JWT_SECRET
    if [ -z "${AUTH_JWT_SECRET:-}" ]; then
        log_sec_error "AUTH_JWT_SECRET" "is unset or empty"
    else
        JWT_LEN=$(printf "%s" "${AUTH_JWT_SECRET}" | wc -c | tr -d '[:space:]')
        if [ "${JWT_LEN}" -lt 32 ]; then
            log_sec_error "AUTH_JWT_SECRET" "length (${JWT_LEN}) is below required minimum of 32 characters"
        fi
        for bad_val in "${FORBIDDEN_APP_SECRETS[@]}"; do
            if [ "${AUTH_JWT_SECRET}" = "${bad_val}" ]; then
                log_sec_error "AUTH_JWT_SECRET" "matches known insecure default or placeholder value"
                break
            fi
        done
    fi
fi

if [ "${ERRORS}" -gt 0 ]; then
    echo "================================================================================" >&2
    echo "SAFETY ERROR: Staging preflight check failed with ${ERRORS} error(s)." >&2
    echo "Operational staging runs require explicit, non-default, strong credentials." >&2
    echo "Please set valid secrets via staging.env or process environment before proceeding." >&2
    echo "================================================================================" >&2
    exit 1
fi

echo "[$(date -u)] Staging environment & credentials preflight passed (passwords/secrets verified, invariants intact)."
exit 0
