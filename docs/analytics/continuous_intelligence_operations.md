# NEXUS Continuous Intelligence — Operational Runbook & Reconciliation Contract

**Status**: Active Operational Contract (Phase 29 Stage 3 — Scheduled Continuous Intelligence)  
**Scope**: Autonomous Background Scanning, Multi-Instance Worker Safety, Ingestion Reconciliation, and Operations Telemetry  

---

## 1. Operational Overview

NEXUS Continuous Intelligence monitors active business metrics for statistical shifts, anomalies, and dimensional segment contributions. In Phase 29 Stage 3, scans execute through two complementary mechanisms:

1. **Autonomous Background Scheduler (`ContinuousIntelligenceScheduler`)**: An in-process, non-blocking `asyncio` background loop embedded within the FastAPI application lifespan. At configurable intervals, it claims active workspaces, checks for un-scanned or failed ingestion jobs, and reconciles scans without human intervention.
2. **On-Demand Operational Trigger (`POST /api/v1/continuous/reconcile`)**: A secured REST endpoint allowing platform administrators, CI/CD pipelines, or incident runbooks to immediately force reconciliation for a specific tenant workspace.

### 1.1 Ingestion Decoupling
Ingestion transactions in `DataGatewayService.ingest_into_core_models` remain strictly decoupled from scan execution:
- The uploaded dataset and core records commit first.
- If a server process crashes, runs out of memory, or restarts immediately post-commit, the core data is safely preserved.
- The background scheduler automatically detects the unscanned ingestion job during its next tick and completes the scan.

---

## 2. Configuration & Environment Variables

The scheduler is configured via environment variables or `.env` file (parsed by `app/core/config.py`):

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `CONTINUOUS_SCHEDULER_ENABLED` | bool | `true` | Master switch enabling autonomous background execution. Set to `false` in worker-only nodes or test runners. |
| `CONTINUOUS_SCHEDULER_INTERVAL_SECONDS` | int | `60` | Cadence (in seconds) between reconciliation ticks. |
| `CONTINUOUS_SCHEDULER_BATCH_SIZE` | int | `10` | Maximum candidate ingestion jobs evaluated per business in a single tick. |
| `CONTINUOUS_SCHEDULER_STARTUP_DELAY_SECONDS` | int | `5` | Grace period on startup before the first tick executes, allowing database pools to stabilize. |
| `CONTINUOUS_SCHEDULER_MAX_BUSINESSES_PER_TICK` | int | `50` | Maximum active businesses evaluated per tick to prevent database connection starvation. |

---

## 3. Multi-Instance Concurrency & Locking Contract

In multi-instance production environments (e.g., multiple FastAPI containers, Uvicorn worker processes behind an ALB):

1. **Per-Ingestion-Job Exclusivity**: Ingestion scans are event-driven audits of metric shifts tied to specific ingestion jobs. Multi-instance exclusivity is enforced at the individual `IngestionJob` row level in PostgreSQL:
   ```sql
   SELECT * FROM ingestion_jobs 
   WHERE id = :job_id AND business_id = :biz_id AND status = 'COMPLETED'
   FOR UPDATE SKIP LOCKED;
   ```
2. **Unified Locking Protocol Across All Pathways**:
   - **Background Scheduler (`ContinuousIntelligenceScheduler`)**: Iterates businesses, discovers candidate completed jobs, and claims each job via `SELECT ... FOR UPDATE SKIP LOCKED`.
   - **Manual Reconciliation (`POST /api/v1/continuous/reconcile`)**: Claims candidate jobs for the target business via `SELECT ... FOR UPDATE SKIP LOCKED`.
   - **Direct Ingestion Trigger (`DataGatewayService.ingest_into_core_models`)**: Claims the completed job via `SELECT ... FOR UPDATE SKIP LOCKED` before launching the scan.
   Because all three pathways use the identical atomic claim mechanism on `IngestionJob`, concurrent workers cannot process the same job simultaneously.
3. **Multi-Job Parallelism Without Deadlocks**: Different ingestion jobs belonging to the same business (e.g., Job A for Sales data and Job B for Inventory data) can be processed concurrently by separate workers or sequentially by one worker. Finding deduplication uses deterministic fingerprint indexing with SQL savepoints (`SAVEPOINT` with `IntegrityError` recovery), guaranteeing zero finding corruption or duplicate scan runs.
4. **Transaction Lifecycle Alignment**:
   - The transaction begins when the worker claims the candidate `IngestionJob`.
   - The scan evaluates metric shifts and writes findings.
   - At the completion of the scan, `db.commit()` commits the `FindingScanRun(status="COMPLETED")` and releases the `IngestionJob` row lock simultaneously.
   - If an error occurs, `db.rollback()` undoes uncommitted finding changes, persists `FindingScanRun(status="FAILED")` in a clean transaction, and commits, releasing the lock.
   - The transaction lifetime matches the lock duration with 100% precision without unsafe transaction manipulation.
5. **Idempotency & Retries**:
   - Once a scan completes (`FindingScanRun.status == "COMPLETED"`), any subsequent check under lock discovers the completed record and treats it as an idempotent no-op.
   - Failed scans (`FindingScanRun.status == "FAILED"`) remain eligible for automatic retry on subsequent scheduler ticks or operational triggers.

*Note: In SQLite test environments, `SKIP LOCKED` is safely bypassed, falling back to transaction savepoints.*

---

## 4. Lifecycle & Graceful Shutdown

1. **Application Startup**:
   - `FastAPI.lifespan` initializes database connectivity.
   - If `settings.CONTINUOUS_SCHEDULER_ENABLED` is `true`, `continuous_scheduler.start()` creates the background `asyncio` task.
   - The scheduler waits `CONTINUOUS_SCHEDULER_STARTUP_DELAY_SECONDS` before its initial run.
2. **Application Shutdown**:
   - On SIGTERM or SIGINT, `lifespan` calls `await continuous_scheduler.stop(timeout_seconds=5.0)`.
   - The scheduler sets its internal `_shutdown_event`, cancels pending waits, and cooperatively terminates before database connections are disposed via `engine.dispose()`.

---

## 5. Observability & Monitoring

### 5.1 Telemetry API Endpoint
Operators can inspect scheduler health and execution metrics at runtime:

- **Path**: `GET /api/v1/continuous/scheduler/status`
- **Headers**: `Authorization: Bearer <JWT_ACCESS_TOKEN>` (Caller must have an `owner` or `admin` role in an active organization; regular members receive `403 Forbidden`)
- **Response**:
  ```json
  {
    "is_running": true,
    "enabled": true,
    "interval_seconds": 60,
    "batch_size": 10,
    "max_businesses": 50,
    "total_ticks": 42,
    "total_reconciled_scans": 7,
    "last_tick_at": 1728864000.12,
    "last_tick_duration_ms": 38.45,
    "last_tick_reconciled": 1,
    "last_tick_errors": 0
  }
  ```

### 5.2 Structured Logs
The scheduler logs under logger name `nexus.continuous.scheduler`:
- `Scheduler started: interval=60s, batch_size=10, max_biz=50, startup_delay=5s`
- `Continuous scheduler tick complete: 2 scans reconciled across 1 businesses (45.10ms)`
- `Candidate ingestion job <job_id> locked by concurrent worker - skipping.`
- `Stopping continuous intelligence scheduler (graceful timeout: 5.0s)...`

---

## 6. On-Demand Reconciliation API

If an immediate scan is needed without waiting for the next scheduler interval:

- **Path**: `POST /api/v1/continuous/reconcile?limit=20`
- **Headers**:
  - `Authorization: Bearer <JWT_ACCESS_TOKEN>`
  - `X-Business-ID: <BUSINESS_UUID>`
- **Example cURL**:
  ```bash
  curl -X POST "https://api.nexus.internal/api/v1/continuous/reconcile?limit=20" \
    -H "Authorization: Bearer $NEXUS_API_TOKEN" \
    -H "X-Business-ID: $TARGET_BUSINESS_ID" \
    -H "Content-Type: application/json"
  ```
- **Returns**: Array of `ContinuousScanResponse` objects for each reconciled job.

---

## 7. Retry Handling & Failure Isolation

- **Scan Failures**: If an error occurs during statistical detection or dimensional analysis:
  - The transaction rolls back.
  - A clean transaction persists a `FindingScanRun` with status `FAILED` and `error_message`.
  - The underlying `IngestionJob` remains `COMPLETED`.
- **Automatic Retry**: Because only `COMPLETED` and `RUNNING` scans block subsequent reconciliation, a job whose latest scan is `FAILED` remains eligible for retry on subsequent scheduler ticks or manual invocations.
- **Completed Idempotency**: Once a scan completes successfully (`COMPLETED`), it will never be re-scanned.

---

## 8. Identifying Pending Scans (SQL Queries)

Operators can inspect pending or failed scans directly:

### PostgreSQL:
```sql
SELECT 
    ij.id AS ingestion_job_id,
    ij.business_id,
    ij.dataset_id,
    ij.target_entity,
    ij.completed_at
FROM ingestion_jobs ij
LEFT JOIN continuous_scan_runs csr
    ON csr.business_id = ij.business_id
    AND csr.trigger_type = 'INGESTION'
    AND csr.metadata_json->>'ingestion_job_id' = ij.id::text
WHERE ij.status = 'COMPLETED'
  AND (csr.id IS NULL OR csr.status = 'FAILED')
ORDER BY ij.completed_at DESC;
```

### SQLite (Local Development):
```sql
SELECT 
    ij.id AS ingestion_job_id,
    ij.business_id,
    ij.dataset_id,
    ij.target_entity,
    ij.completed_at
FROM ingestion_jobs ij
LEFT JOIN continuous_scan_runs csr
    ON csr.business_id = ij.business_id
    AND csr.trigger_type = 'INGESTION'
    AND json_extract(csr.metadata_json, '$.ingestion_job_id') = ij.id
WHERE ij.status = 'COMPLETED'
  AND (csr.id IS NULL OR csr.status = 'FAILED')
ORDER BY ij.completed_at DESC;
```
