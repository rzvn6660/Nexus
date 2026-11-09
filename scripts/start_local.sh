#!/usr/bin/env bash
# ==============================================================================
# NEXUS — One-Command Zero-Cost Local Operations Startup Script (Bash)
# ==============================================================================
set -euo pipefail

echo "=================================================================="
echo " NEXUS — Zero-Cost Local Operations Startup (₹0 / Month)"
echo " Intelligence | Retention | Pulse"
echo "=================================================================="

# 1. Check Docker
if ! docker info > /dev/null 2>&1; then
    echo "[ERROR] Docker is not running. Please start Docker before launching." >&2
    exit 1
fi
echo "[1/4] Docker daemon verified."

# 2. Verify Local Environment Configuration (.env)
if [ ! -f ".env" ]; then
    echo "[2/5] Initializing local .env from .env.zero_cost.template..."
    PG_PASS=$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(16))')
    SEC_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')
    JWT_SEC=$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')
    KMS_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')
    sed -e "s/GENERATE_LOCAL_POSTGRES_PASSWORD_MIN_16_CHARS/$PG_PASS/g" \
        -e "s/GENERATE_LOCAL_SECRET_KEY_MIN_32_CHARS/$SEC_KEY/g" \
        -e "s/GENERATE_LOCAL_JWT_SECRET_KEY_MIN_32_CHARS/$JWT_SEC/g" \
        -e "s/GENERATE_LOCAL_DEV_KMS_MASTER_KEY_256BITS/$KMS_KEY/g" \
        .env.zero_cost.template > .env
    echo "      ✓ Created local .env with generated secrets."
else
    echo "[2/5] Local .env verified."
fi

# 3. Storage Dirs
mkdir -p ./data/reports ./data/uploads ./backups/local
echo "[3/5] Storage directories initialized."

# 4. Launch Docker Compose Stack
echo "[4/5] Starting zero-cost infrastructure..."
docker compose -f docker-compose.local.yml up -d

# 5. Wait for PostgreSQL
echo "[5/5] Waiting for services to become healthy..."
until [ "$(docker inspect --format='{{json .State.Health.Status}}' nexus_postgres_local 2>/dev/null)" = '"healthy"' ]; do
    sleep 2
    echo "      Waiting for PostgreSQL..."
done

echo "=================================================================="
echo " NEXUS IS FULLY OPERATIONAL (Zero Cost / Local-First)"
echo "=================================================================="
echo " Dashboard (Web UI):       http://localhost:3000"
echo " Backend REST API Docs:    http://localhost:8000/docs"
echo " Mailpit Email Inspector:  http://localhost:8025"
echo " PostgreSQL Connection:    127.0.0.1:5433 (nexus_staging_db)"
echo " Redis Connection:         127.0.0.1:6380"
echo "------------------------------------------------------------------"
echo " Demo Login: demo.owner@nexus.local / Password123!"
echo " Stop stack: ./scripts/stop_local.sh"
echo "=================================================================="
