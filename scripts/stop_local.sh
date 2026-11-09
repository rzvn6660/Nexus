#!/usr/bin/env bash
# ==============================================================================
# NEXUS — Zero-Cost Local Operations Shutdown Script (Bash)
# ==============================================================================
set -euo pipefail

echo "Stopping NEXUS Zero-Cost Local Operations stack..."
docker compose -f docker-compose.local.yml stop

echo "✓ NEXUS services stopped successfully."
echo "  Persistent data volumes are preserved intact."
echo "  To restart: ./scripts/start_local.sh"
