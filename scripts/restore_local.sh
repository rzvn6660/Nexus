#!/usr/bin/env bash
# ==============================================================================
# NEXUS — Zero-Cost Local Restore Script (Bash)
# ==============================================================================
set -euo pipefail

BACKUP_DIR="${1:-./backups/local}"
DUMP_FILE="${2:-}"

echo "=================================================================="
echo " NEXUS — Coordinated Local Restore Drill"
echo "=================================================================="

if [ -z "$DUMP_FILE" ]; then
    DUMP_FILE=$(ls -t "$BACKUP_DIR"/nexus_postgres_*.dump 2>/dev/null | head -n 1 || true)
    if [ -z "$DUMP_FILE" ]; then
        echo " [ERROR] No backup dump found in $BACKUP_DIR." >&2
        exit 1
    fi
fi

echo ""
echo "[1/4] Selected dump: $DUMP_FILE"
TS=$(basename "$DUMP_FILE" | sed -e 's/nexus_postgres_//' -e 's/\.dump//')
CHECKSUM_FILE="$BACKUP_DIR/nexus_backup_${TS}.sha256"

if [ -f "$CHECKSUM_FILE" ]; then
    EXPECTED_HASH=$(awk '{print $1}' "$CHECKSUM_FILE")
    ACTUAL_HASH=$(sha256sum "$DUMP_FILE" | awk '{print $1}')
    if [ "$EXPECTED_HASH" != "$ACTUAL_HASH" ]; then
        echo " [ERROR] Cryptographic mismatch! Expected $EXPECTED_HASH, got $ACTUAL_HASH." >&2
        exit 1
    fi
    echo "      [OK] SHA-256 integrity verified ($ACTUAL_HASH)."
fi

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
echo ""
echo "[2/4] Target PostgreSQL container: $PG_CONTAINER"

echo ""
echo "[3/4] Restoring PostgreSQL database from dump..."
CONTAINER_TMP="/tmp/pg_restore_${TS}.dump"
docker cp "$DUMP_FILE" "${PG_CONTAINER}:${CONTAINER_TMP}"
docker exec "$PG_CONTAINER" pg_restore -U nexus_staging_user -d nexus_staging_db --clean --if-exists --no-owner "$CONTAINER_TMP"
docker exec "$PG_CONTAINER" rm -f "$CONTAINER_TMP"
echo "      [OK] Database restore command finished."

STORAGE_ZIP="$BACKUP_DIR/nexus_storage_${TS}.zip"
if [ -f "$STORAGE_ZIP" ]; then
    echo ""
    echo "[4/4] Restoring local storage archive..."
    unzip -q -o "$STORAGE_ZIP" -d "./data"
    echo "      [OK] Storage archive restored."
else
    echo ""
    echo "[4/4] No storage archive found for timestamp $TS."
fi

echo "=================================================================="
echo " RESTORE COMPLETED SUCCESSFULLY"
echo "=================================================================="
