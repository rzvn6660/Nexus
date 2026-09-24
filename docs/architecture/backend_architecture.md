# NEXUS Backend Architecture

## 1. Overview
The NEXUS backend is built as a modular, production-ready Python service utilizing **FastAPI**, **Pydantic v2**, and **SQLAlchemy 2.x**. It is engineered for strict loose coupling, high concurrency, and zero reliance on ad-hoc global state.

---

## 2. Directory Layout
```
backend/
├── app/
│   ├── api/             # HTTP endpoints and routing
│   │   ├── v1/          # Version 1 API endpoints
│   │   ├── deps.py      # Dependency injection providers (db, settings)
│   │   └── router.py    # Main API router mounting /api/health and /api/v1
│   ├── core/            # Core infrastructure (config, database, logging, middleware)
│   ├── models/          # SQLAlchemy 2.x ORM models and declarative bases
│   ├── schemas/         # Pydantic v2 validation and response schemas
│   ├── services/        # Decoupled business logic services
│   ├── agents/          # LangGraph orchestrator, nodes, tools, state (Phase 3)
│   ├── analytics/       # Deterministic math, stats, and forecasting (Phase 2)
│   ├── data/            # Ingestion, quality checkers, profiling, connectors
│   ├── rag/             # Vector retrieval, embeddings, and semantic layer
│   ├── knowledge/       # Static domain rules and retail taxonomy
│   ├── evaluation/      # Grader harnesses and benchmark runners
│   ├── security/        # Query sanitizer, rate limiter, credential guards
│   └── observability/   # Tracing, audit logs, and metrics
├── alembic/             # Database migration scripts and configuration
├── tests/               # Pytest test suite
├── Dockerfile           # Production container build
├── alembic.ini          # Alembic configuration
└── requirements.txt     # Python runtime dependencies
```

---

## 3. Configuration Management
Configuration is centralized in `app/core/config.py` using `pydantic-settings`:
- **Hierarchical Loading**: Loads from environment variables and an optional `.env` file.
- **Strong Typing**: Enforces type validation on application ports, boolean flags, and database URLs.
- **Immutable Cache**: Exposes `get_settings()` decorated with `@lru_cache()` for predictable, fast dependency injection.
- **Safe Secrets Handling**: No secrets or API credentials are hardcoded. Missing optional credentials default gracefully to `None`.

---

## 4. Database Layer (SQLAlchemy 2.x)
- **Engine Setup**: Initialized in `app/core/database.py` with `create_engine()`:
  - `pool_pre_ping=True`: Proactively verifies connections before handing them to requests, preventing stale socket errors.
  - Configurable pool parameters: `pool_size`, `max_overflow`, and `pool_timeout`.
- **Declarative Base**: Uses SQLAlchemy 2.x's `DeclarativeBase` in `app/models/base.py`.
- **Auditing Mixin**: Provides `TimestampMixin` standardizing UTC `created_at` and `updated_at` across all relational entities.
- **Non-Fatal Health Checks**: `check_database_connection()` executes a lightweight `SELECT 1` query inside an isolated transaction. If PostgreSQL is unreachable, the function returns a structured `{"status": "disconnected"}` dictionary rather than letting unhandled connection exceptions crash the application.

---

## 5. Middleware & Observability
- **Request Correlation**: `RequestCorrelationMiddleware` checks incoming requests for `X-Request-ID` or generates a UUID4.
- **Trace Context**: Injects the correlation ID into response headers and Python logging filters so all log lines for a single HTTP transaction can be correlated effortlessly.
- **Execution Timing**: Records process duration (`X-Process-Time-Ms`) on every outbound response.

---

## 6. API Routing & Versioning
- **Root Health**: `GET /api/health` conforms directly to platform baseline requirements, returning service health, version, environment, and database state.
- **Versioned Routes**: Future endpoints are isolated under `app/api/v1/`, mounted under the prefix `/api/v1/`.
- **Dependency Injection**: Database sessions (`get_db`) and settings (`get_current_settings`) are injected into route handlers using FastAPI's `Depends` system, ensuring clean test mockability.
