"""Core configuration management for NEXUS using Pydantic v2."""

import os
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application Metadata
    APP_NAME: str = "NEXUS"
    APP_TITLE: str = "NEXUS — Agentic Business Intelligence Platform"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "nexus-insecure-development-secret-key-change-in-production"

    # Server & Routing
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: list[str] | str = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse comma-separated origins string into list if necessary."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return []

    # Database Configuration (PostgreSQL)
    DATABASE_URL: str = Field(
        default="postgresql+psycopg://nexus_user:nexus_password@localhost:5432/nexus_db",
        description="PostgreSQL connection string (SQLAlchemy format)",
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, v: str) -> str:
        """Normalize generic postgresql:// to postgresql+psycopg:// for SQLAlchemy 2.x."""
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "nexus_db"
    POSTGRES_USER: str = "nexus_user"
    POSTGRES_PASSWORD: str = "nexus_password"

    # Database Connection Pool & SSL
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800  # Recycle idle/stale connections after 30 minutes
    DB_ECHO: bool = False
    DB_SSL_MODE: str | None = None  # None | "disable" | "allow" | "prefer" | "require" | "verify-ca" | "verify-full"
    DB_SSL_ROOT_CERT: str | None = None  # Optional path to trusted CA root bundle (e.g. /etc/ssl/certs/rds-global-bundle.pem)

    # AI / LLM Layer Configuration
    DEFAULT_LLM_PROVIDER: str = "mock"
    DEFAULT_LLM_MODEL: str = "gpt-4o"
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    QWEN_API_KEY: str | None = None
    DASHSCOPE_API_KEY: str | None = None
    KIMI_API_KEY: str | None = None
    MOONSHOT_API_KEY: str | None = None
    GROK_API_KEY: str | None = None
    XAI_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "phi3:latest"
    MAX_AGENT_ITERATIONS: int = 5
    DEFAULT_EXPLANATION_LEVEL: str = "manager"

    # Phase 24 — Intelligence 2.0 & Multi-Tier LLM Architecture
    LLM_ROUTING_ENABLED: bool = True
    LLM_DEFAULT_TIER: str = "low_cost"
    LLM_LOW_COST_PROVIDER: str = "mock"
    LLM_LOW_COST_MODEL: str = "mock-fast"
    LLM_STRONG_REASONING_PROVIDER: str = "mock"
    LLM_STRONG_REASONING_MODEL: str = "mock-reasoning"
    LLM_FALLBACK_PROVIDER: str = "mock"
    LLM_FALLBACK_MODEL: str = "mock-deterministic"
    LLM_ALLOW_EXTERNAL_CALLS: bool = (
        False  # Strict Guard: Prevent accidental external paid LLM calls
    )
    LLM_REQUEST_TIMEOUT_SECONDS: float = 10.0
    LLM_MAX_RETRIES: int = 2

    # Phase 24 Hardening — Free-First Quota & Budget Strategy
    LLM_FREE_TIER_DAILY_REQUEST_LIMIT: int = 1000
    LLM_FREE_TIER_DAILY_TOKEN_LIMIT: int = 1_000_000
    LLM_MONTHLY_BUDGET_USD: float = 50.0

    # Phase 12 Decision Gateway Configuration
    DECISION_PROVIDER: str = "structured_llm"
    DECISION_TIMEOUT_SECONDS: float = 10.0
    JEV_API_KEY: str | None = None
    JEV_MODEL: str = "jev-latest"

    # RAG / Semantic Layer Configuration (Phase 25B Production Settings)
    EMBEDDING_PROVIDER: str = "mock"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536
    EMBEDDING_VERSION: str = "v1"
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_TIMEOUT_SECONDS: float = 15.0
    EMBEDDING_MAX_RETRIES: int = 3
    LOCAL_EMBEDDING_BASE_URL: str | None = None
    LOCAL_EMBEDDING_MODEL: str = "BAAI/bge-m3"
    VECTOR_STORE_TYPE: str = "pgvector"
    RAG_TOP_K: int = 3
    RAG_SIMILARITY_THRESHOLD: float = 0.2
    RAG_HYBRID_SEARCH_ENABLED: bool = True
    RAG_HYBRID_SEMANTIC_WEIGHT: float = 0.7
    RAG_HYBRID_LEXICAL_WEIGHT: float = 0.3
    RAG_FUSION_METHOD: str = "rrf"  # "rrf" (Reciprocal Rank Fusion) or "linear"
    RAG_RRF_K: int = 60  # Smoothing parameter for reciprocal rank fusion
    RAG_LEXICAL_TOP_K: int = 10  # Candidate count for lexical stage
    MAX_DOCUMENT_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB max document size

    # Phase 31B: Ingress and Upload Ingestion Limits (reconciled across Nginx and backend)
    DATA_UPLOAD_MAX_MEMORY_SIZE_MB: int = 50
    DATA_UPLOAD_MAX_BYTES: int = 50 * 1024 * 1024  # 50 MB

    RAG_RERANK_ENABLED: bool = False  # Optional and disabled by default
    RAG_RERANK_PROVIDER: str = "none"  # "none", "local", "cohere"
    RAG_RERANK_MODEL: str = "local-cross-scorer-v1"
    RAG_RERANK_TOP_K: int = 3
    RAG_MAX_FALLBACK_SCAN_CHUNKS: int = 1000  # Explicit bound for in-memory BM25 fallback
    COHERE_API_KEY: str | None = None

    # Investigation / Diagnostic Intelligence Layer
    MAX_INVESTIGATION_STEPS: int = 8
    INVESTIGATION_ENABLED: bool = True

    # Phase 7 Predictive Intelligence & Forecasting
    MAX_FORECAST_HORIZON: int = 12
    DEFAULT_FORECAST_HORIZON: int = 3
    MIN_OBSERVATIONS_MONTHLY: int = 4
    MIN_OBSERVATIONS_DAILY: int = 14
    FORECASTING_ENABLED: bool = True

    # Security & Access Control (Phase 10)
    API_KEY_ENABLED: bool = False
    API_KEY: str | None = None

    # SaaS & Multi-Tenancy Identity (Phase 15)
    AUTH_JWT_SECRET: str = "nexus-saas-jwt-secret-key-change-in-production-min-32-chars"
    AUTH_JWT_ALGORITHM: str = "HS256"
    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    SUPABASE_URL: str | None = None
    SUPABASE_ANON_KEY: str | None = None
    MULTI_TENANCY_ENABLED: bool = True

    # Shared Cache / Redis (Phase 23.6 Production Hardening)
    # Set REDIS_URL to enable shared rate limiting and JWT revocation across workers.
    # Example: redis://localhost:6379/0  or  rediss://user:pass@host:6380/0
    REDIS_URL: str | None = None
    # When True (recommended for production), security-sensitive operations (token
    # revocation, rate limiting) fail-closed if the shared backend is unavailable.
    # Set to False only in single-worker development environments.
    REDIS_FAIL_CLOSED: bool = False
    # Explicit flag requiring shared Redis backend even if fail-closed is not enabled.
    REDIS_REQUIRED: bool = False

    # Operational Boundaries & Timeouts (Phase 10)
    REQUEST_TIMEOUT_SECONDS: int = 60
    UPLOAD_DIR: str = "./data/uploads"
    DATA_DIR: str = "data"

    # Phase 32A — Error Tracking (Sentry)
    SENTRY_DSN: str | None = None
    SENTRY_ENVIRONMENT: str | None = None
    SENTRY_RELEASE: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    SENTRY_SEND_DEFAULT_PII: bool = False

    # Phase 32A — Operational Metrics (Prometheus)
    METRICS_ENABLED: bool = True
    METRICS_AUTH_TOKEN: str | None = None

    # Phase 32A — Security Headers & Content Security Policy
    SECURE_HSTS_SECONDS: int = 0  # 0 = disabled (dev/HTTP default); set to e.g. 31536000 when HTTPS is active
    SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = True
    SECURE_HSTS_PRELOAD: bool = False
    SECURE_CSP_ENABLED: bool = True
    SECURE_CSP_REPORT_ONLY: bool = True  # Safe report-only rollout
    SECURE_CSP_DIRECTIVES: str = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' ws: wss:; "
        "object-src 'none'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    SECURE_CSP_REPORT_URI: str | None = None
    SECURE_PERMISSIONS_POLICY: str = "camera=(), microphone=(), geolocation=(), payment=()"

    # Phase 29 & 31 — Continuous Intelligence Scheduled Execution
    CONTINUOUS_SCHEDULER_ENABLED: bool = True
    CONTINUOUS_SCHEDULER_AUTOSTART: bool = True  # Autostart inside web application lifespan; set False in multi-worker web pods
    CONTINUOUS_SCHEDULER_INTERVAL_SECONDS: int = 60
    CONTINUOUS_SCHEDULER_BATCH_SIZE: int = 10
    CONTINUOUS_SCHEDULER_STARTUP_DELAY_SECONDS: int = 5
    CONTINUOUS_SCHEDULER_MAX_BUSINESSES_PER_TICK: int = 50

    @field_validator("DB_SSL_MODE", mode="before")
    @classmethod
    def validate_ssl_mode(cls, v: str | None) -> str | None:
        """Validate PostgreSQL TLS sslmode matches supported libpq/psycopg modes."""
        if v is None:
            return None
        v_clean = str(v).strip().lower()
        if not v_clean:
            return None
        valid_modes = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
        if v_clean not in valid_modes:
            raise ValueError(
                f"Invalid DB_SSL_MODE '{v}'. Supported PostgreSQL TLS modes: "
                f"{', '.join(sorted(valid_modes))}."
            )
        return v_clean

    @field_validator("SENTRY_TRACES_SAMPLE_RATE", mode="before")
    @classmethod
    def validate_sentry_sample_rate(cls, v: float | str | None) -> float:
        """Validate Sentry trace sample rate is bounded between 0.0 and 1.0."""
        if v is None:
            return 0.0
        val = float(v)
        if not (0.0 <= val <= 1.0):
            raise ValueError(f"SENTRY_TRACES_SAMPLE_RATE must be between 0.0 and 1.0, got {val}")
        return val

    @field_validator("SECURE_HSTS_SECONDS", mode="before")
    @classmethod
    def validate_hsts_seconds(cls, v: int | str | None) -> int:
        """Validate HSTS max-age seconds is non-negative."""
        if v is None:
            return 0
        val = int(v)
        if val < 0:
            raise ValueError(f"SECURE_HSTS_SECONDS must be non-negative, got {val}")
        return val

    @property
    def is_production(self) -> bool:
        """Helper to verify if running in production mode."""
        return self.APP_ENV.lower() == "production"

    @property
    def effective_db_ssl_mode(self) -> str | None:
        """Resolve effective PostgreSQL TLS sslmode.

        If explicitly set via DB_SSL_MODE, uses that validated value.
        In production with DB_SSL_MODE unset:
          - If DB_SSL_ROOT_CERT is configured, prefers 'verify-full' (certificate + hostname verification).
          - Otherwise, defaults to 'require' (strict transport encryption).
        Outside production with DB_SSL_MODE unset, returns None (allowing unencrypted local dev/test).
        """
        if self.DB_SSL_MODE is not None and self.DB_SSL_MODE.strip():
            return self.DB_SSL_MODE.strip().lower()
        if self.is_production:
            if self.DB_SSL_ROOT_CERT and self.DB_SSL_ROOT_CERT.strip():
                return "verify-full"
            return "require"
        return None

    @model_validator(mode="before")
    @classmethod
    def default_production_flags(cls, data: Any) -> Any:
        """In production, ensure DEBUG defaults safely to False if not explicitly provided."""
        if isinstance(data, dict):
            app_env = data.get("APP_ENV", os.getenv("APP_ENV", "development"))
            if str(app_env).strip().lower() == "production" and "DEBUG" not in data and "debug" not in data:
                data["DEBUG"] = False
        return data

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """Enforce strict secret safety when running in production mode.

        Fails application startup if SECRET_KEY or AUTH_JWT_SECRET match known insecure
        defaults, contain placeholder tokens, fail minimum length requirements (>= 32 chars),
        or exhibit low character variety (heuristic sanity check).
        Character diversity is evaluated as a heuristic sanity check to reject repeated patterns (e.g. 'aaaa...'),
        not as formal proof of cryptographic entropy. True entropy must be derived from a CSPRNG.
        Preserves convenient development and test defaults outside production.
        """
        if not self.is_production:
            return self

        # 0. Validate DEBUG mode in production
        if self.DEBUG:
            raise ValueError(
                "Production startup failed: DEBUG mode cannot be enabled when APP_ENV=production. "
                "Ensure DEBUG=false in production environments."
            )

        insecure_defaults = {
            "nexus-insecure-development-secret-key-change-in-production",
            "nexus-production-secret-key-change-me",
            "nexus-saas-jwt-secret-key-change-in-production-min-32-chars",
            "secret",
            "changeme",
            "change-me",
            "password",
            "admin",
            "nexus",
        }
        placeholder_substrings = ["change-in-production", "change-me", "insecure", "example"]

        # 1. Validate SECRET_KEY
        secret_val = (self.SECRET_KEY or "").strip()
        self.SECRET_KEY = secret_val
        if not secret_val or secret_val in insecure_defaults:
            raise ValueError(
                "Production startup failed: SECRET_KEY is set to a known insecure default. "
                "You must supply a cryptographically strong, non-default SECRET_KEY."
            )
        if any(token in secret_val.lower() for token in placeholder_substrings):
            raise ValueError(
                "Production startup failed: SECRET_KEY contains insecure placeholder tokens "
                "('change-in-production', 'change-me', 'insecure', or 'example')."
            )
        if len(secret_val) < 32:
            raise ValueError(
                f"Production startup failed: SECRET_KEY length ({len(secret_val)}) is below "
                "the mandatory minimum of 32 characters."
            )
        # Character diversity heuristic: rejects trivial repeated-character sequences
        if len(set(secret_val)) < 8:
            raise ValueError(
                "Production startup failed: SECRET_KEY exhibits low character diversity heuristic "
                f"(found {len(set(secret_val))} distinct characters; minimum 8 required)."
            )

        # 2. Validate AUTH_JWT_SECRET
        jwt_val = (self.AUTH_JWT_SECRET or "").strip()
        self.AUTH_JWT_SECRET = jwt_val
        if not jwt_val or jwt_val in insecure_defaults:
            raise ValueError(
                "Production startup failed: AUTH_JWT_SECRET is set to a known insecure default. "
                "You must supply a cryptographically strong, non-default AUTH_JWT_SECRET."
            )
        if any(token in jwt_val.lower() for token in placeholder_substrings):
            raise ValueError(
                "Production startup failed: AUTH_JWT_SECRET contains insecure placeholder tokens."
            )
        if len(jwt_val) < 32:
            raise ValueError(
                f"Production startup failed: AUTH_JWT_SECRET length ({len(jwt_val)}) is below "
                "the mandatory minimum of 32 characters."
            )
        # Character diversity heuristic: rejects trivial repeated-character sequences
        if len(set(jwt_val)) < 8:
            raise ValueError(
                "Production startup failed: AUTH_JWT_SECRET exhibits low character diversity heuristic "
                f"(found {len(set(jwt_val))} distinct characters; minimum 8 required)."
            )

        return self

    @model_validator(mode="after")
    def validate_production_database_tls(self) -> "Settings":
        """Enforce strict TLS encryption for PostgreSQL in production mode.

        In production:
        - Rejects insecure DB_SSL_MODE ('disable', 'allow', 'prefer').
        - Rejects DATABASE_URL query parameter overrides attempting to set
          sslmode to 'disable', 'allow', or 'prefer'.
        - Rejects duplicate, ambiguous 'sslmode' or 'sslrootcert' query parameters.
        - Rejects malformed DATABASE_URL strings.
        - Mandates a valid, readable CA certificate bundle when 'verify-full' or 'verify-ca' is selected.
        - Fails startup safely if configured CA certificate bundle does not exist or is unreadable.
        - Preserves unencrypted and custom configurations in non-production environments.
        """
        if not self.is_production:
            return self

        # 1. Validate DB_SSL_MODE in production
        if self.DB_SSL_MODE is not None and self.DB_SSL_MODE.strip():
            mode_clean = self.DB_SSL_MODE.strip().lower()
            if mode_clean in ("disable", "allow", "prefer"):
                raise ValueError(
                    f"Production startup failed: Insecure DB_SSL_MODE '{mode_clean}'. "
                    "Production PostgreSQL connections strictly mandate encrypted TLS ('require', 'verify-ca', or 'verify-full')."
                )

        # 2. Validate DATABASE_URL query parameters for PostgreSQL in production
        try:
            parsed_url = urlparse(self.DATABASE_URL)
        except Exception as exc:
            raise ValueError(f"Production startup failed: Malformed DATABASE_URL: {exc}") from exc

        scheme = (parsed_url.scheme or "").lower()
        if "postgres" in scheme:
            if not parsed_url.netloc and not parsed_url.path:
                raise ValueError("Production startup failed: Malformed DATABASE_URL missing host/database.")

            query_params = parse_qs(parsed_url.query)

            # Check duplicate / ambiguous sslmode parameters
            if len(query_params.get("sslmode", [])) > 1:
                raise ValueError(
                    f"Production startup failed: Ambiguous multiple 'sslmode' parameters in DATABASE_URL: {query_params['sslmode']}. "
                    "Specify exactly one sslmode parameter."
                )

            # Check duplicate / ambiguous sslrootcert parameters
            if len(query_params.get("sslrootcert", [])) > 1:
                raise ValueError(
                    f"Production startup failed: Ambiguous multiple 'sslrootcert' parameters in DATABASE_URL: {query_params['sslrootcert']}. "
                    "Specify exactly one sslrootcert parameter."
                )

            if "sslmode" in query_params:
                for mode_val in query_params["sslmode"]:
                    mode_clean = mode_val.strip().lower()
                    if mode_clean in ("disable", "allow", "prefer"):
                        raise ValueError(
                            f"Production startup failed: Insecure sslmode='{mode_clean}' in DATABASE_URL. "
                            "Production PostgreSQL connections strictly mandate encrypted TLS ('require', 'verify-ca', or 'verify-full'). "
                            "Insecure explicit URL overrides are rejected."
                        )
                    if mode_clean not in ("require", "verify-ca", "verify-full"):
                        raise ValueError(
                            f"Production startup failed: Unsupported sslmode='{mode_clean}' in DATABASE_URL. "
                            "Supported secure modes: 'require', 'verify-ca', or 'verify-full'."
                        )

            # 3. Determine active TLS mode and validate trusted CA configuration
            active_tls_mode = self.effective_db_ssl_mode
            if "sslmode" in query_params and query_params["sslmode"]:
                active_tls_mode = query_params["sslmode"][0].strip().lower()

            # Resolve CA certificate path (URL parameter takes precedence if both present)
            ca_path: str | None = None
            if "sslrootcert" in query_params and query_params["sslrootcert"]:
                ca_path = query_params["sslrootcert"][0].strip()
            elif self.DB_SSL_ROOT_CERT and self.DB_SSL_ROOT_CERT.strip():
                ca_path = self.DB_SSL_ROOT_CERT.strip()

            # verify-full and verify-ca strictly require a trusted CA certificate bundle
            if active_tls_mode in ("verify-full", "verify-ca") and not ca_path:
                raise ValueError(
                    f"Production startup failed: PostgreSQL TLS mode '{active_tls_mode}' strictly requires a trusted CA root certificate bundle. "
                    "Provide a valid CA bundle path via DB_SSL_ROOT_CERT or sslrootcert in DATABASE_URL."
                )

            # When CA path is configured, verify file existence, file type, and readability
            if ca_path:
                if not os.path.exists(ca_path):
                    raise ValueError(
                        f"Production startup failed: Configured CA root certificate bundle '{ca_path}' does not exist. "
                        "Ensure the trusted CA certificate file is mounted and accessible."
                    )
                if not os.path.isfile(ca_path):
                    raise ValueError(
                        f"Production startup failed: Configured CA root certificate bundle '{ca_path}' is not a regular file."
                    )
                if not os.access(ca_path, os.R_OK):
                    raise ValueError(
                        f"Production startup failed: Configured CA root certificate bundle '{ca_path}' is not readable. "
                        "Check file permissions."
                    )

        return self

    @model_validator(mode="after")
    def validate_production_redis(self) -> "Settings":
        """Enforce strict Redis configuration when running in production mode.

        In production:
        - When shared security state is mandatory (REDIS_FAIL_CLOSED=True or REDIS_REQUIRED=True),
          rejects missing or empty REDIS_URL.
        - Validates REDIS_URL scheme ('redis', 'rediss', or 'unix').
        - Rejects insecure placeholder tokens in REDIS_URL.
        - Redacts credentials in any error messages to prevent secret leakage.
        - Preserves local fallback for non-production environments.
        """
        if not self.is_production:
            return self

        is_redis_mandatory = self.REDIS_FAIL_CLOSED or getattr(self, "REDIS_REQUIRED", False)
        redis_val = (self.REDIS_URL or "").strip()

        # 1. Reject missing Redis configuration when shared security state is mandatory
        if is_redis_mandatory and not redis_val:
            raise ValueError(
                "Production startup failed: REDIS_URL is mandatory when shared security state is required "
                "(REDIS_FAIL_CLOSED=True or REDIS_REQUIRED=True). "
                "Multi-worker production deployments require a shared Redis instance for rate limiting and token revocation."
            )

        # 2. If REDIS_URL is configured in production, validate scheme and structure
        if redis_val:
            try:
                parsed = urlparse(redis_val)
            except Exception as exc:
                raise ValueError(f"Production startup failed: Malformed REDIS_URL: {exc}") from exc

            scheme = (parsed.scheme or "").lower()
            if scheme not in ("redis", "rediss", "unix"):
                raise ValueError(
                    f"Production startup failed: Unsupported REDIS_URL scheme '{scheme}'. "
                    "Supported schemes: 'redis://', 'rediss://', or 'unix://'."
                )

            # Check for obvious insecure placeholder substrings
            placeholder_substrings = ["change-me", "your-redis-password", "example.com"]
            for token in placeholder_substrings:
                if token in redis_val.lower():
                    raise ValueError(
                        f"Production startup failed: REDIS_URL contains insecure placeholder token '{token}'."
                    )

        return self

    @model_validator(mode="after")
    def validate_production_metrics_security(self) -> "Settings":
        """Enforce strict metrics authentication when running in production mode.

        In production:
        - When METRICS_ENABLED=True, METRICS_AUTH_TOKEN is strictly mandatory.
        - Fails application startup if METRICS_AUTH_TOKEN is None, empty, or whitespace-only.
        - Rejects insecure placeholder tokens ('change-me', 'token', 'secret', etc.).
        - Mandates minimum token length (>= 16 chars) in production.
        - Preserves convenient unauthenticated access in non-production environments (development, test).
        """
        if not self.is_production:
            return self

        if self.METRICS_ENABLED:
            token_val = (self.METRICS_AUTH_TOKEN or "").strip()
            if not token_val:
                raise ValueError(
                    "Production startup failed: METRICS_AUTH_TOKEN is mandatory when METRICS_ENABLED=True in production. "
                    "Configure a cryptographically strong scraper secret (minimum 16 characters) or set METRICS_ENABLED=False."
                )
            insecure_placeholders = [
                "change-me",
                "change-in-production",
                "your-metrics-token",
                "example",
                "token",
                "secret",
                "password",
            ]
            if any(p in token_val.lower() for p in insecure_placeholders):
                raise ValueError(
                    "Production startup failed: METRICS_AUTH_TOKEN contains an insecure placeholder token. "
                    "Provide a secure, non-default scraper authorization token."
                )
            if len(token_val) < 16:
                raise ValueError(
                    f"Production startup failed: METRICS_AUTH_TOKEN length ({len(token_val)}) is below "
                    "the mandatory production minimum of 16 characters."
                )

        return self

    def get_sanitized_cors_origins(self) -> list[str]:
        """Return allowed CORS origins, strictly stripping wildcards in production."""
        if self.is_production:
            return [o for o in self.BACKEND_CORS_ORIGINS if o != "*"]
        return list(self.BACKEND_CORS_ORIGINS)


@lru_cache
def get_settings() -> Settings:
    """Return cached instance of application settings."""
    return Settings()


settings = get_settings()
