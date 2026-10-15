# NEXUS Production Deployment Guide

**Document Version**: 1.0  
**Phase**: Phase 10 — Production & Deployment  
**Classification**: Operational Engineering Manual  

---

## 1. Architecture Overview

NEXUS is deployed as a hardened, multi-container production SaaS platform consisting of:
- **Frontend SPA**: React 18 / TypeScript application built via Vite, served via Nginx with reverse proxying, OWASP security headers, and gzip compression.
- **Backend API**: Python 3.12 FastAPI service executing deterministic analytics, diagnostic causal decomposition, statistical time-series forecasting, and LangGraph agent flows.
- **Continuous Intelligence Scheduler**: Dedicated background worker container running `python -m app.scheduler_runner` with cooperative shutdown and database lock avoidance.
- **Relational & Vector Database**: PostgreSQL 16 equipped with the `pgvector` extension and persistent data volume `nexus_postgres_prod_data`.
- **In-Memory Cache & Security Store**: Redis 7 Alpine with persistent AOF storage `nexus_redis_prod_data` for distributed rate limiting, JWT revocation, and atomic token checks.
- **Persistent Tenant Storage**: Shared persistent volume `nexus_backend_data` mounted at `/app/data` for tenant files, datasets, and audit trails.

```text
               HTTPS Requests (Port 443)
                          │
                          ▼
            ┌───────────────────────────┐
            │   Nginx Ingress Proxy     │
            │  (client_max_body: 50M)   │
            └─────────────┬─────────────┘
                          │
          ┌───────────────┴───────────────┐
          │                               │
   /api/* │                               │ /*
          ▼                               ▼
┌──────────────────┐            ┌──────────────────┐
│ FastAPI Backend  │            │ React Static SPA │
│   Port :8000     │            │    Port :3000    │
└─────────┬────────┘            └──────────────────┘
          │ (shared volume /app/data)
          ├───────────────────────────────┐
          │                               │
          ▼                               ▼
┌──────────────────┐            ┌──────────────────┐
│ PostgreSQL 16    │            │ Redis 7 (AOF)    │
│  + pgvector      │            │ RateLimit & Auth │
└─────────┬────────┘            └─────────┬────────┘
          │                               │
          └───────────────┬───────────────┘
                          │
                          ▼
            ┌───────────────────────────┐
            │ Dedicated Scheduler Worker│
            │  (Continuous Intelligence)│
            └───────────────────────────┘
```

---

## 2. Prerequisites

### Host Environment Requirements:
- **Operating System**: Linux (Ubuntu 22.04 LTS / Debian 12 / RHEL 9 recommended) or macOS / Windows with Docker Desktop.
- **Docker & Compose**: Docker Engine 24.0+ and Docker Compose v2.20+.
- **Hardware Sizing**:
  - Minimum: 2 vCPU, 4GB RAM, 20GB SSD.
  - Recommended: 4 vCPU, 8GB RAM, 50GB SSD.
- **Network**: Inbound ports 80/443 (HTTP/HTTPS) open; outbound connectivity to LLM API endpoints (if external providers enabled).

---

## 3. Environment Variables Configuration

Copy `.env.example` to `.env` on the host:
```bash
cp .env.example .env
chmod 600 .env
```

### Essential Production Variables:
```ini
# APPLICATION
APP_ENV="production"
DEBUG=false
LOG_LEVEL="INFO"
SECRET_KEY="generate-a-strong-random-64-character-hex-key"

# SERVER & CORS
BACKEND_HOST="0.0.0.0"
BACKEND_PORT=8000
BACKEND_CORS_ORIGINS="https://nexus.yourcompany.com,https://bi.yourcompany.com"

# DATABASE
POSTGRES_USER="nexus_admin"
POSTGRES_PASSWORD="secure_production_db_password"
POSTGRES_DB="nexus_production"
DATABASE_URL="postgresql+psycopg://nexus_admin:secure_production_db_password@postgres:5432/nexus_production"

# LLM & EMBEDDING PROVIDERS
DEFAULT_LLM_PROVIDER="openai"
DEFAULT_LLM_MODEL="gpt-4o"
OPENAI_API_KEY="sk-..."
EMBEDDING_PROVIDER="mock"  # or openai
EMBEDDING_MODEL="text-embedding-3-small"

# SECURITY
API_KEY_ENABLED=false     # Set to true to require X-API-Key header
API_KEY="your-secret-api-key-for-clients"
```

---

## 4. Local Production-Like Startup (Docker Compose)

NEXUS includes a dedicated production compose profile (`docker-compose.prod.yml`) that builds optimized multi-stage images, excludes developer source mounts, and enables production restarts:

```bash
# 1. Build and launch all production containers in background
docker compose -f docker-compose.prod.yml up -d --build

# 2. Verify container statuses and health probes
docker compose -f docker-compose.prod.yml ps

# 3. View unified logs
docker compose -f docker-compose.prod.yml logs -f
```

---

## 5. Database Setup & Initialization

The database container uses `pgvector/pgvector:pg16`.

On initial launch:
1. PostgreSQL initializes `/var/lib/postgresql/data` within the named volume.
2. The `pgvector` extension is installed into the container image.
3. Database permissions for `nexus_admin` are provisioned.

To inspect the database:
```bash
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U nexus_admin -d nexus_production -c "SELECT version();"
```

---

## 6. Migration Process (Alembic)

Production deployments must **never** execute raw schema overrides. Always use Alembic:

### Apply Pending Migrations:
```bash
docker compose -f docker-compose.prod.yml exec backend \
  python -m alembic upgrade head
```

### Verify Migration Version:
```bash
docker compose -f docker-compose.prod.yml exec backend \
  python -m alembic current
```
Expected output: `002_phase5_knowledge_schema (head)`.

---

## 7. Backend Deployment & Process Roles (FastAPI & Background Worker)

The backend runs as a non-root user (`appuser`) using decoupled web and worker processes:

### 7.1 Web API Process (FastAPI)
Handles REST API traffic, request correlation, authentication, and diagnostic causal flows:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --no-access-log
```

In multi-worker web pods or containers, set:
```ini
CONTINUOUS_SCHEDULER_AUTOSTART=false
```
This prevents duplicate background scheduler loops from running in each web worker process.

### 7.2 Dedicated Background Worker Process
Executes continuous intelligence detection scans, reconciliations, and scheduled autonomous analysis:
```bash
python -m app.analytics.continuous.scheduler
```

> [!IMPORTANT]
> **Dedicated Worker Requirement**: Setting `CONTINUOUS_SCHEDULER_AUTOSTART=false` disables the background loop in web worker processes to prevent duplicate execution across workers. When disabled, a separate, dedicated background scheduler process **must** be provisioned. Without this running worker, continuous intelligence scans, autonomous detections, and diagnostic reconciliations will not run.
> 
> **Provisioning Status**: The application codebase provides the executable standalone daemon runner (`python -m app.analytics.continuous.scheduler`), which handles signals (`SIGINT`, `SIGTERM`) and graceful shutdown. The container/cluster orchestration resource (e.g. dedicated Kubernetes Deployment, ECS task, or systemd service) is documented and designed here, and will be provisioned in the cluster infrastructure during Phase 31B.

### Process Management & Reliability:
- **Workers**: 2–4 web workers per container (1 worker per vCPU).
- **Graceful Shutdown**: SIGTERM initiates graceful shutdown, waiting for active requests to finish before disposing the SQLAlchemy connection pool.
- **Connection Pool Recycling**: `DB_POOL_RECYCLE=1800` automatically recycles idle connections after 30 minutes, preventing silent drops by cloud NAT gateways and load balancers.
- **TLS/SSL Encryption & Modes**:
  - `require`: Enforces encrypted in-transit communication, protecting against passive eavesdropping. (Default in production when no CA root certificate is supplied).
  - `verify-full`: Enforces encrypted in-transit communication, validates that the database certificate was signed by a trusted CA, and verifies that the hostname matches the certificate SAN. Strongly recommended for production when trusted CA bundles are available.
  - Set `DB_SSL_MODE=verify-full` and configure `DB_SSL_ROOT_CERT=/path/to/ca-bundle.pem`.
  - In non-production environments (`APP_ENV=development` or `test`), `DB_SSL_MODE` defaults to unencrypted for local developer ease.
- **CA Bundle Container Mounting Requirements**:
  - When using `DB_SSL_MODE=verify-full` or specifying `DB_SSL_ROOT_CERT`, the CA bundle must be mounted into the container filesystem at the exact path specified by `DB_SSL_ROOT_CERT` (e.g., `-v /etc/ssl/certs/rds-global-bundle.pem:/etc/ssl/certs/rds-global-bundle.pem:ro` in Docker, or via a Kubernetes `ConfigMap`/`Secret` volume mount).
  - The CA file must be a regular file readable by the non-root container user (`appuser`).
  - Startup validation strictly checks `os.path.exists`, `os.path.isfile`, and `os.access(..., os.R_OK)`; if the file is absent or unreadable, the application aborts startup immediately with a clear operational error.
- **Provider-Specific TLS & Proxy Architectures**:
  - **AWS RDS / Aurora**: Download the regional or global trust bundle (`global-bundle.pem`), configure `DB_SSL_MODE=verify-full`, and mount `DB_SSL_ROOT_CERT=/etc/ssl/certs/rds-global-bundle.pem`.
  - **Supabase**: Download the project CA root bundle, configure `DB_SSL_MODE=verify-full`, and mount `DB_SSL_ROOT_CERT=/etc/ssl/certs/supabase-ca.pem`.
  - **Direct Google Cloud SQL**: Provide the instance `server-ca.pem`, configure `DB_SSL_MODE=verify-full`, and mount `DB_SSL_ROOT_CERT=/etc/ssl/certs/server-ca.pem`.
  - **TLS-Terminating Database Proxies (Cloud SQL Auth Proxy, AWS RDS Proxy, PgBouncer)**:
    - Dedicated database proxies establish an encrypted, identity-authenticated mTLS tunnel to upstream managed database instances.
    - Production backends communicating with a database proxy over network TCP must preserve transport encryption (`DB_SSL_MODE=require` or `verify-ca` with proxy-issued CA certificate).
    - Setting `sslmode=disable` in production is strictly prohibited by application startup validation. If connecting over local UNIX domain sockets within the same container namespace where OS kernel file permissions govern transport, this must be an explicitly architected UNIX socket deployment (`DATABASE_URL=postgresql+psycopg://.../?host=/var/run/postgresql`) rather than unencrypted network TCP.
  - **Local Development / Docker Compose**: The default development image (`pgvector/pgvector:pg16`) operates without TLS; run in development mode (`APP_ENV=development`) where unencrypted local connections are permitted.
- **TLS Insecure Override Prevention**: In production, insecure explicit overrides (`sslmode=disable`, `allow`, `prefer`) via either `DB_SSL_MODE` or `DATABASE_URL` query parameters are strictly rejected at startup with an immediate failure to prevent accidental security degradation. Explicit secure overrides (`require`, `verify-ca`, `verify-full`) are permitted and preserved.
- **Trusted CA Verification**: In production, `DB_SSL_MODE=verify-full` strictly mandates a trusted CA root certificate bundle (`DB_SSL_ROOT_CERT` or `sslrootcert` in `DATABASE_URL`). If the CA bundle file is missing, not a regular file, or unreadable, the application fails startup immediately with a clear, safe operational error.
- **Production Secret Validation**: In production (`APP_ENV=production`), application startup fails immediately if `SECRET_KEY` or `AUTH_JWT_SECRET` uses default strings, placeholder phrases, fewer than 32 characters, or exhibits low character diversity (heuristic sanity check to reject trivial repeated patterns like `aaaa...`).

---

## 8. Frontend Deployment (React SPA)

The frontend is compiled into static production assets:
1. `npm ci` installs exact lockfile dependencies.
2. `npm run build` generates `/app/dist` with manual chunk splitting (`vendor`, `charts`, `icons`).
3. Assets are served by Nginx with gzip compression and browser caching for hashed JS/CSS assets.

---

## 9. Health & Monitoring Probes

Configure load balancer and container healthchecks:

| Endpoint | Protocol | Expected Status | Purpose |
|---|---|---|---|
| `/api/v1/health/live` | HTTP GET | 200 OK | Process liveness |
| `/api/v1/health/ready` | HTTP GET | 200 OK (503 if DB down) | Database readiness |
| `/api/v1/health` | HTTP GET | 200 OK | Detailed diagnostic state |

---

## 10. Logging & Monitoring

View structured logs filtered by correlation ID:
```bash
# Stream backend logs
docker compose -f docker-compose.prod.yml logs -f backend

# Search logs for a specific request ID
docker compose -f docker-compose.prod.yml logs backend | grep "a8f93e21"
```

---

## 11. Troubleshooting Guide

### Issue 1: Database Connection Timeout
- **Symptom**: `/api/v1/health/ready` returns 503 `{"status": "not_ready"}`.
- **Resolution**: Verify postgres container health:
  `docker compose -f docker-compose.prod.yml ps postgres`
  Check PostgreSQL credentials in `.env`.

### Issue 2: CORS Header Mismatch
- **Symptom**: Browser console reports blocked cross-origin request.
- **Resolution**: Add the exact frontend origin (including protocol and port) to `BACKEND_CORS_ORIGINS` in `.env`. Wildcard `*` is rejected in production mode.

### Issue 3: 413 Payload Too Large
- **Symptom**: File upload fails during knowledge or CSV ingestion.
- **Resolution**: Check `MAX_DOCUMENT_SIZE_BYTES` in backend config and `client_max_body_size` in `nginx.conf` (both set to 10MB by default).

---

## 12. Rollback Procedure

In the event of a faulty release:
1. Re-tag or check out the previous stable git commit:
   ```bash
   git checkout <PREVIOUS_COMMIT_SHA>
   ```
2. Revert the database migration if necessary:
   ```bash
   docker compose -f docker-compose.prod.yml exec backend \
     python -m alembic downgrade -1
   ```
3. Rebuild and restart services:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

---

## 13. Backup & Recovery Summary

- Nightly `pg_dump` backups are stored in `/var/backups/nexus`.
- See [docs/production/backup-recovery.md](file:///c:/Users/rizvi/nexus/docs/production/backup-recovery.md) for full restore and disaster recovery procedures.

---

## 14. Security Checklist

- [ ] `DEBUG` is set to `false` in `.env`.
- [ ] `SECRET_KEY` has been rotated to a 64-character random string.
- [ ] `BACKEND_CORS_ORIGINS` explicitly lists authorized production domains.
- [ ] PostgreSQL default password has been replaced.
- [ ] Backend container runs as non-root user (`appuser`).
- [ ] Port 5432 is not exposed directly to the public internet.
- [ ] TLS certificates are installed on the reverse proxy.
- [ ] `DB_SSL_MODE` is set to `verify-full` (or `require`) with trusted CA root bundle mounted into the container at `DB_SSL_ROOT_CERT`.
- [ ] Dedicated continuous intelligence scheduler worker (`python -m app.analytics.continuous.scheduler`) is provisioned if `CONTINUOUS_SCHEDULER_AUTOSTART=false`.
