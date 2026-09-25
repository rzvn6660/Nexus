# NEXUS Production Deployment Guide

**Document Version**: 1.0  
**Phase**: Phase 10 — Production & Deployment  
**Classification**: Operational Engineering Manual  

---

## 1. Architecture Overview

NEXUS is deployed as a high-performance modular monolith consisting of:
- **Frontend SPA**: React 18 / TypeScript application built via Vite, served statically via Nginx or a global CDN.
- **Backend API**: Python 3.12 FastAPI service executing deterministic analytics, diagnostic causal decomposition, statistical time-series forecasting, and LangGraph agent flows.
- **Relational & Vector Database**: PostgreSQL 16 equipped with the `pgvector` extension.
- **Reverse Proxy**: Nginx terminating SSL/TLS, routing `/api/*` requests to FastAPI, and serving static assets with gzip compression and client-side caching.

```text
               HTTPS Requests (Port 443)
                          │
                          ▼
            ┌───────────────────────────┐
            │       Nginx Ingress       │
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
          │
          ▼
┌──────────────────┐
│ PostgreSQL 16    │
│  + pgvector      │
└──────────────────┘
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

## 7. Backend Deployment (FastAPI)

The backend runs as a non-root user (`appuser`) using an ASGI server:

### Container Process:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --no-access-log
```

### Process Management Notes:
- **Workers**: 2–4 workers per container (1 worker per vCPU).
- **Graceful Shutdown**: SIGTERM initiates graceful shutdown, waiting for active requests to finish before disposing the SQLAlchemy connection pool.

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
