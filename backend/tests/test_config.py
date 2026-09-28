"""Tests for configuration parsing and database connectivity check behavior."""

from sqlalchemy import create_engine
from app.core.config import Settings
from app.core.database import check_database_connection


def test_settings_defaults() -> None:
    """Validate default configuration settings."""
    cfg = Settings()
    assert cfg.APP_NAME == "NEXUS"
    assert "postgresql" in cfg.DATABASE_URL
    assert cfg.API_V1_PREFIX == "/api/v1"
    assert isinstance(cfg.BACKEND_CORS_ORIGINS, list)
    assert not cfg.is_production


def test_cors_origins_parsing() -> None:
    """Validate CORS string parsing into string list."""
    cfg = Settings(BACKEND_CORS_ORIGINS="http://example.com, https://nexus.ai")
    assert cfg.BACKEND_CORS_ORIGINS == ["http://example.com", "https://nexus.ai"]


def test_check_database_connection_connected() -> None:
    """Validate database connectivity check with an active in-memory SQLite engine."""
    sqlite_engine = create_engine("sqlite:///:memory:")
    res = check_database_connection(target_engine=sqlite_engine)
    assert res["status"] == "connected"
    assert "latency_ms" in res
    assert res["latency_ms"] >= 0.0


def test_check_database_connection_disconnected_graceful() -> None:
    """
    Validate that check_database_connection handles unreachable DB gracefully
    without raising an unhandled exception.
    """
    unreachable_engine = create_engine(
        "postgresql+psycopg://nexus_user:fake_password@127.0.0.1:59999/nonexistent",
        connect_args={"connect_timeout": 1},
    )
    res = check_database_connection(target_engine=unreachable_engine)
    assert isinstance(res, dict)
    assert res["status"] == "disconnected"
    assert "error" in res


def test_production_cors_sanitization() -> None:
    """Validate that in production mode, wildcard CORS origins are strictly stripped."""
    prod_cfg = Settings(
        APP_ENV="production",
        BACKEND_CORS_ORIGINS=["*", "https://nexus.ai", "http://localhost:3000"],
    )
    assert prod_cfg.is_production is True
    sanitized = prod_cfg.get_sanitized_cors_origins()
    assert "*" not in sanitized
    assert "https://nexus.ai" in sanitized
    assert "http://localhost:3000" in sanitized


def test_production_settings_isolation() -> None:
    """Validate production settings flags and secrets initialization."""
    prod_cfg = Settings(
        APP_ENV="production",
        DEBUG=False,
        SECRET_KEY="a-secure-production-random-secret-key-32-chars-long",
        AUTH_JWT_SECRET="a-secure-production-jwt-secret-key-32-chars-long",
    )
    assert prod_cfg.is_production is True
    assert prod_cfg.DEBUG is False
    assert len(prod_cfg.SECRET_KEY) >= 32
    assert len(prod_cfg.AUTH_JWT_SECRET) >= 32


def test_alembic_full_migration_chain() -> None:
    """Validate that the complete Alembic migration chain from 001 to 008 is linear with a single head."""
    import importlib.util
    from pathlib import Path

    versions_dir = Path("backend/alembic/versions")
    if not versions_dir.exists():
        versions_dir = Path("alembic/versions")

    files = sorted([f for f in versions_dir.glob("*.py") if f.name != "__init__.py"])
    assert len(files) >= 8, f"Expected at least 8 migration files, found {len(files)}"

    chain: dict[str, str | None] = {}
    for f in files:
        spec = importlib.util.spec_from_file_location(f.stem, f)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rev = getattr(mod, "revision", None)
        down = getattr(mod, "down_revision", None)
        assert rev is not None, f"Migration {f.name} missing revision"
        chain[rev] = down

    # Verify single head
    heads = [rev for rev, down in chain.items() if rev not in chain.values()]
    assert len(heads) == 1, f"Expected exactly 1 migration head, got: {heads}"
    assert heads[0] == "008_phase19_run_lifecycle_snapshots"

    # Walk from head to base None
    current = heads[0]
    count = 0
    while current is not None:
        count += 1
        current = chain.get(current)
    assert count == len(files), f"Disconnected migration chain: walked {count} of {len(files)} files"
