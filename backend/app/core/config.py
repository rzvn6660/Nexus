"""Core configuration management for NEXUS using Pydantic v2."""

from functools import lru_cache

from pydantic import Field, field_validator
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

    # Database Connection Pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

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

    # Phase 25C.3 Reranking & Ingestion Bounds
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

    # Operational Boundaries & Timeouts (Phase 10)
    REQUEST_TIMEOUT_SECONDS: int = 60
    METRICS_ENABLED: bool = True
    UPLOAD_DIR: str = "./data/uploads"

    @property
    def is_production(self) -> bool:
        """Helper to verify if running in production mode."""
        return self.APP_ENV.lower() == "production"

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
