# NEXUS — Local Backup & Disaster Recovery Runbook

**Document Version:** 1.0.0
**Target Environment:** Zero-Cost Local-First Operations (Docker Compose, Windows PowerShell & POSIX Bash)
**Monthly Operational Cost:** ₹0.00 / month
**Storage Target:** Local Filesystem (`./backups/local/`)

---

## 1. Operational Overview

NEXUS local operations provide complete operational resilience without relying on cloud-managed snapshot services (such as AWS RDS automated backups or AWS S3 cross-region replication). All business intelligence, customer retention models, decision records, and automated management reports (NEXUS Pulse) are protected through coordinated local backup and restore scripts.

### Core Principles
1. **Zero External Spend:** Backup archives and cryptographic sidecars are generated and stored strictly on local disk. Zero AWS S3 API charges, zero cloud storage egress or storage fees.
2. **Coordinated Consistency:** PostgreSQL database snapshots and filesystem artifacts (PDF reports and uploads) are captured with synchronized timestamps.
3. **Cryptographic Integrity:** Every backup set generates an authoritative SHA-256 sidecar (`.sha256`) and an immutable JSON metadata manifest (`.json`). Restore operations automatically verify hashes before executing.
4. **Automated Retention:** Backup scripts enforce a retention window (default: 7 backup generations) to prevent uncontrolled disk consumption.

---

## 2. Directory Layout & Artifact Specification

All backup artifacts reside in `backups/local/` within the repository root:

| Artifact | Format | Purpose |
| :--- | :--- | :--- |
| `nexus_postgres_<timestamp>.dump` | Custom Format (`pg_dump -F c`) | Compressed, consistent PostgreSQL 16 database binary archive containing schema, tables, vector extensions, and Alembic migration state. |
| `nexus_storage_<timestamp>.zip` | ZIP Archive | Compressed snapshot of `./data/reports` (generated Pulse PDF reports) and `./data/uploads`. |
| `nexus_manifest_<timestamp>.json` | JSON | Machine-readable manifest containing backup ID, ISO 8601 UTC timestamp, engine metadata, and byte sizes. |
| `nexus_backup_<timestamp>.sha256` | Standard sha256sum | Checksum sidecar used for automated tamper detection and corruption verification prior to restoration. |

---

## 3. Creating a Backup

### Windows (PowerShell)
Execute the zero-cost coordinated backup script:
```powershell
.\scripts\backup_local.ps1
```
*Optional parameters:*
- `-BackupDir "./custom/path"`: Custom destination folder.
- `-RetentionCount 14`: Adjust the number of historical backup sets to keep (default: 7).

### Linux / macOS / WSL (Bash)
```bash
./scripts/backup_local.sh [backup_dir] [retention_count]
```

### Verification
Upon completion, the script outputs the exact dump path, size, and cryptographic SHA-256 hash:
```text
==================================================================
 BACKUP SUCCESSFUL - Artifacts Verified (Zero Cost Local Storage)
 Database dump: ./backups/local/nexus_postgres_20261103_225030.dump (673.67 KB)
 SHA-256:       F21F32D9406F54B5AE0B5DCAA5AC9EEA8A4E5F53F20A36ACACEE6D1CE41EB1FE
==================================================================
```

---

## 4. Restoring from a Backup

The restore script automatically locates the latest backup set, performs cryptographic pre-flight verification, and restores the database and storage assets.

### Windows (PowerShell)
Restore latest available backup:
```powershell
.\scripts\restore_local.ps1
```

Restore a specific historical dump:
```powershell
.\scripts\restore_local.ps1 -DumpFile "backups/local/nexus_postgres_20261103_225030.dump"
```

### Linux / macOS / WSL (Bash)
```bash
./scripts/restore_local.sh [backup_dir] [dump_file_path]
```

### Restore Lifecycle Stages:
1. **Pre-flight Cryptographic Verification:** The script computes the SHA-256 hash of the target dump and compares it against `nexus_backup_<timestamp>.sha256`. If hashes mismatch, execution immediately halts to prevent corrupt data restoration.
2. **Container Discovery:** Automatically targets `nexus_postgres_local` (or `nexus_postgres_staging`).
3. **Database Restoration:** The dump is copied into the container's isolated `/tmp` workspace and restored via `pg_restore --clean --if-exists --no-owner`, preserving Alembic migration revisions (`022_pulse_reporting_and_automation`).
4. **Storage Restoration:** Expands `nexus_storage_<timestamp>.zip` back into `./data/`.

---

## 5. Verified Disaster Recovery Drill Results

On November 3, 2026, a live restore drill was executed against the running PostgreSQL 16 container (`nexus_postgres_staging`):

- **Dump File:** `nexus_postgres_20261103_225030.dump` (689,843 bytes / 673.67 KB)
- **Verified SHA-256:** `F21F32D9406F54B5AE0B5DCAA5AC9EEA8A4E5F53F20A36ACACEE6D1CE41EB1FE`
- **Integrity Pre-check:** PASSED (Exact match with sidecar)
- **Restoration Duration:** ~1.4 seconds
- **Database Schema Validation Post-Restore:**
  ```sql
  SELECT version_num FROM alembic_version;
  -- Result: 022_pulse_reporting_and_automation (1 row)
  ```
- **Post-Restore Pytest Regression:** 36 of 36 targeted tests passed with zero failures.

---

## 6. Scheduled Automation (Zero-Cost Recurring Backups)

To run unattended daily backups at ₹0 cost, configure native operating system scheduling.

### Windows Task Scheduler
Create a scheduled task running daily at 02:00 AM:
1. Open PowerShell as Administrator.
2. Register the scheduled task:
```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Users\rizvi\nexus\scripts\backup_local.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "NexusDailyLocalBackup" -Description "Daily Zero-Cost NEXUS Database and Storage Backup"
```

### Linux / macOS Cron
Add to crontab (`crontab -e`):
```cron
0 2 * * * /bin/bash /path/to/nexus/scripts/backup_local.sh >> /path/to/nexus/backups/local/cron_backup.log 2>&1
```

---

## 7. Emergency Failure Scenarios & Troubleshooting

### Scenario A: Checksum Mismatch Error
- **Symptom:** `[ERROR] Cryptographic mismatch! Expected <HASH1>, got <HASH2>.`
- **Root Cause:** The dump file was modified, truncated, or subjected to disk corruption.
- **Resolution:** Do not force restoration. Select an earlier verified backup generation from `backups/local/` by passing `-DumpFile`.

### Scenario B: Active Container Not Found
- **Symptom:** `[ERROR] No running PostgreSQL container found.`
- **Resolution:** Start the local stack using `.\scripts\start_local.ps1`, verify container status with `docker ps`, and re-run restore.
