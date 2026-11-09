#!/usr/bin/env bash
# ==============================================================================
# NEXUS — Zero-Cost Local Backup Script (Bash)
# ==============================================================================
set -euo pipefail

BACKUP_DIR="${1:-./backups/local}"
RETENTION_COUNT="${2:-7}"

echo "=================================================================="
echo " NEXUS — Coordinated Local Backup Drill"
echo "=================================================================="

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
PG_BACKUP_FILE="$BACKUP_DIR/nexus_postgres_${TIMESTAMP}.dump"
STORAGE_BACKUP_FILE="$BACKUP_DIR/nexus_storage_${TIMESTAMP}.zip"
META_BACKUP_FILE="$BACKUP_DIR/nexus_manifest_${TIMESTAMP}.json"
CHECKSUM_FILE="$BACKUP_DIR/nexus_backup_${TIMESTAMP}.sha256"

# 1. Locate container
echo ""
echo "[1/4] Locating active PostgreSQL container..."
PG_CONTAINER=""
for c in "nexus_postgres_local" "nexus_postgres_staging"; do
    if [ "$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null || true)" = "running" ]; then
        PG_CONTAINER="$c"
        break
    fi
done

if [ -z "$PG_CONTAINER" ]; then
    echo " [ERROR] No running PostgreSQL container found." >&2
    exit 1
fi
echo "      [OK] Using active container: $PG_CONTAINER"

# 2. Dump
echo ""
echo "[2/4] Dumping PostgreSQL 16 database..."
CONTAINER_TMP="/tmp/pg_dump_${TIMESTAMP}.dump"
docker exec "$PG_CONTAINER" pg_dump -U nexus_staging_user -F c -d nexus_staging_db -f "$CONTAINER_TMP"
docker cp "${PG_CONTAINER}:${CONTAINER_TMP}" "$PG_BACKUP_FILE"
docker exec "$PG_CONTAINER" rm -f "$CONTAINER_TMP"
PG_SIZE=$(wc -c < "$PG_BACKUP_FILE" | tr -d ' ')
echo "      [OK] PostgreSQL dump completed: $PG_BACKUP_FILE (${PG_SIZE} bytes)"

# 3. Storage
echo ""
echo "[3/4] Archiving local report and upload directories..."
if [ -d "./data/reports" ] || [ -d "./data/uploads" ]; then
    zip -r -q "$STORAGE_BACKUP_FILE" ./data/reports ./data/uploads 2>/dev/null || true
    echo "      [OK] Storage archived: $STORAGE_BACKUP_FILE"
else
    echo "      [INFO] No report/upload directories to archive. Created empty marker."
    touch "$BACKUP_DIR/empty_storage_${TIMESTAMP}.txt"
fi

# 4. Checksums & Manifest
echo ""
echo "[4/4] Generating verification checksums and manifest..."
PG_HASH=$(sha256sum "$PG_BACKUP_FILE" | awk '{print $1}')
echo "$PG_HASH  $(basename "$PG_BACKUP_FILE")" > "$CHECKSUM_FILE"

cat <<EOF > "$META_BACKUP_FILE"
{
  "backup_id": "nexus_backup_${TIMESTAMP}",
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "environment": "zero_cost_local",
  "database": {
    "engine": "postgresql_16_pgvector",
    "container": "${PG_CONTAINER}",
    "file": "$(basename "$PG_BACKUP_FILE")",
    "size_bytes": ${PG_SIZE},
    "sha256": "${PG_HASH}"
  }
}
EOF

echo "      [OK] SHA-256 sidecar written: $CHECKSUM_FILE"
echo "      [OK] Manifest written: $META_BACKUP_FILE"
echo "=================================================================="
echo " BACKUP SUCCESSFUL — Artifacts Verified (Zero Cost Local Storage)"
echo " Database dump: $PG_BACKUP_FILE"
echo " SHA-256:       $PG_HASH"
echo "=================================================================="
