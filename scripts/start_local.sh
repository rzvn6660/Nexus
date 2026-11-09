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

# 2. Storage Dirs
mkdir -p ./data/reports ./data/uploads ./backups/local
echo "[2/4] Storage directories initialized."

# 3. Launch Docker Compose Stack
echo "[3/4] Starting zero-cost infrastructure..."
docker compose -f docker-compose.local.yml up -d

# 4. Wait for PostgreSQL
echo "[4/4] Waiting for services to become healthy..."
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
