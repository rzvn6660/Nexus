# NEXUS Production Observability & Monitoring

**Document Version**: 1.0  
**Phase**: Phase 10 — Production & Deployment  
**Classification**: Engineering Operational Document  

---

## 1. Overview

Production observability for NEXUS is designed around three foundational principles:
1. **Traceability**: Every HTTP request receives an end-to-end correlation ID (`X-Request-ID`) propagated through FastAPI middlewares, agent graph nodes, and database queries.
2. **Structural Transparency**: Logs are formatted for machine parsing, structured filtering, and latency monitoring without leaking sensitive credentials or raw PII.
3. **Multi-Tiered Health Probing**: Health endpoints distinguish between process liveness, database readiness, and degraded analytical dependencies.

---

## 2. Structured Logging Architecture

### 2.1 Log Format Specification

The root application logger (`app.core.logging`) emits structured, single-line log entries with fixed metadata tags:

```text
[YYYY-MM-DD HH:MM:SS] [LEVEL] [CORRELATION_ID] [LOGGER_NAME:FUNCTION:LINE] - MESSAGE
```

#### Example Production Log Entry:
```text
[2026-09-26 10:15:32] [INFO] [a8f93e21-0d32-4e4b-9c71-081498b3c102] [nexus.middleware:dispatch:33] - POST /api/v1/agent/analyze -> 200 (42.15ms)
```

### 2.2 Correlation Filter

A custom `CorrelationFilter` attaches the active request correlation ID to all log records. If a log is emitted outside an active HTTP request context (such as during system startup or cron tasks), the correlation ID defaults to `-`.

### 2.3 Noise Suppression

In production mode, verbose third-party loggers are automatically suppressed:
- `uvicorn.access`: Set to `WARNING` to prevent duplicate unformatted request logs.
- `sqlalchemy.engine`: Suppressed to `WARNING` (unless `DB_ECHO=true` is explicitly enabled for debugging).
- `httpx` / `urllib3`: Suppressed to `WARNING`.

---

## 3. Request Correlation Middleware

The `RequestCorrelationMiddleware` (`app.core.middleware`) wraps every inbound request:

1. **Header Ingestion**: Reads `X-Request-ID` from client headers if provided (e.g. from an upstream load balancer or API gateway).
2. **UUID4 Generation**: If missing, generates a cryptographic UUID4 correlation ID.
3. **State Binding**: Stores the correlation ID in `request.state.correlation_id`.
4. **Response Headers**: Returns headers to the caller:
   - `X-Request-ID`: The assigned correlation identifier.
   - `X-Process-Time-Ms`: High-resolution execution duration in milliseconds.
5. **Request Tracing**: Emits a structured log on request completion containing HTTP method, path, status code, latency, and correlation ID.

---

## 4. Agent Operational Telemetry

For multi-stage agentic analysis (`/api/v1/agent/analyze`, `/api/v1/investigation/analyze`), operational diagnostics capture:

| Telemetry Field | Source | Purpose |
|---|---|---|
| `correlation_id` | Middleware | Trace query across entire LangGraph execution |
| `intent` | Agent State | Classifies business intent (e.g., `metric_lookup`, `forecasting`) |
| `selected_tools` | Tool Execution Node | Records analytical tools invoked (`get_product_rankings`, etc.) |
| `evidence_status` | Evidence Synthesizer | Validates presence of source tables, columns, date ranges |
| `iterations` | Graph Router | Counts agent reasoning loops to detect cyclical bounds |
| `status` | Response Serializer | Execution outcome (`success`, `clarification_needed`, `error`) |

---

## 5. Security & Privacy Guardrails (Redaction)

NEXUS strictly enforces data sanitization in production logging:

### NEVER Logged:
- API Keys (`X-API-Key`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)
- Passwords & Connection Strings (`DATABASE_URL`, `POSTGRES_PASSWORD`)
- Authorization Headers (`Authorization: Bearer ...`)
- Raw Customer PII (customer email, phone numbers, exact residential address)
- Raw Unbounded Document Content (entire uploaded PDF/TXT files)

### Permitted for Diagnostics:
- Normalized business queries and intent classifications
- Document IDs, content hashes, and chunk counts
- Aggregated numerical metrics and variance calculations
- Error categories, status codes, and anonymized SKU references

---

## 6. Health & Readiness Semantics

NEXUS provides three health endpoints designed for load balancers, Kubernetes, and Docker healthchecks:

### 6.1 Unified Health Check: `GET /api/v1/health` (and `GET /api/health`)
Provides complete system health status and database latency.
- **Healthy**: Returns HTTP 200 with `"status": "healthy"` when the API is running and database is reachable.
- **Degraded**: Returns HTTP 200 with `"status": "degraded"` when the API is running but database connection is unavailable.

```json
{
  "status": "healthy",
  "service": "nexus",
  "version": "0.1.0",
  "environment": "production",
  "timestamp": "2026-09-26T10:15:30.123456Z",
  "database": {
    "status": "connected",
    "latency_ms": 1.42,
    "error": null
  }
}
```

### 6.2 Liveness Probe: `GET /api/v1/health/live`
- Lightweight process check that does not touch the database.
- Used by container orchestrators to detect process crashes or deadlocks.
- Always returns HTTP 200 `{"status": "alive"}` if ASGI server is processing events.

### 6.3 Readiness Probe: `GET /api/v1/health/ready`
- Probes database socket connectivity and executes `SELECT 1`.
- Returns HTTP 200 `{"status": "ready"}` if database is operational.
- Returns HTTP 503 `{"status": "not_ready", "error": "..."}` if database is unreachable, removing the instance from active load balancer traffic.

---

## 7. Recommended External Monitoring Integrations

| System | Recommended Tool | Integration Path |
|---|---|---|
| **Exception Tracking** | Sentry | Configure `SENTRY_DSN` in `.env` |
| **Log Aggregation** | Datadog / Grafana Loki | Ingest stdout JSON/text logs |
| **Uptime Monitoring** | BetterUptime / UptimeRobot | Ping `/api/v1/health/live` every 30s |
| **APM / Tracing** | OpenTelemetry | Set `OTEL_EXPORTER_OTLP_ENDPOINT` |
