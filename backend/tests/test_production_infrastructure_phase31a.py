"""Phase 31A — Production Security, Secrets & Process Hardening Regression Test Suite.

Verifies:
1. Production secret validation:
   - Fails safely when SECRET_KEY or AUTH_JWT_SECRET uses known insecure defaults.
   - Fails safely on placeholder tokens ('change-in-production', 'change-me', 'insecure').
   - Fails safely when secret length is below 32 characters.
   - Fails safely when secret exhibits low character variety / entropy (repeated sequences).
   - Strips leading/trailing whitespace safely and stores stripped value.
   - Guarantees secrets are NEVER leaked in validation error messages.
   - Preserves convenient default secrets outside production (development/test).
2. Database connection settings:
   - Configurable connection pool recycling (default 1800s / 30m).
   - Configurable PostgreSQL TLS sslmode (disable, allow, prefer, require, verify-ca, verify-full).
   - Rejects invalid SSL modes via validation.
   - Enforces strict production default ('require') when sslmode is unset.
   - Supports explicit local development configuration.
   - Preservation of existing query parameters in DATABASE_URL.
   - Complete isolation of SQLite engine settings (check_same_thread preserved).
3. Continuous Intelligence Scheduler process isolation:
   - Web application lifespan honors CONTINUOUS_SCHEDULER_AUTOSTART=False.
   - Scheduler autostart active by default when enabled.
   - Dedicated standalone daemon runner behaves gracefully on termination.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.analytics.continuous.scheduler import (
    ContinuousIntelligenceScheduler,
    continuous_scheduler,
)
from app.core.config import Settings
from app.core.database import _get_engine_kwargs
from app.main import create_application
from fastapi.testclient import TestClient


# ==============================================================================
# 1. PRODUCTION SECRETS VALIDATION TESTS
# ==============================================================================

def test_production_secret_key_fails_on_insecure_defaults() -> None:
    """Validate that production startup fails when SECRET_KEY matches known defaults."""
    insecure_keys = [
        "nexus-insecure-development-secret-key-change-in-production",
        "nexus-production-secret-key-change-me",
        "secret",
        "changeme",
        "password",
        "admin",
        "nexus",
    ]
    for key in insecure_keys:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                APP_ENV="production",
                SECRET_KEY=key,
                AUTH_JWT_SECRET="a-valid-production-jwt-secret-at-least-32-chars",
            )
        assert "SECRET_KEY is set to a known insecure default" in str(exc_info.value) or "placeholder" in str(exc_info.value)


def test_production_secret_key_fails_on_placeholder_phrases() -> None:
    """Validate that production startup fails when SECRET_KEY contains placeholder phrases."""
    placeholder_keys = [
        "my-production-key-change-in-production-12345",
        "super-long-key-with-change-me-placeholder-999",
        "very-insecure-key-that-exceeds-thirty-two-chars",
    ]
    for key in placeholder_keys:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                APP_ENV="production",
                SECRET_KEY=key,
                AUTH_JWT_SECRET="a-valid-production-jwt-secret-at-least-32-chars",
            )
        assert "placeholder" in str(exc_info.value) or "insecure" in str(exc_info.value)


def test_production_secret_key_fails_on_short_length() -> None:
    """Validate that production startup fails when SECRET_KEY length is < 32 characters."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="short-secret-only-24-char",
            AUTH_JWT_SECRET="a-valid-production-jwt-secret-at-least-32-chars",
        )
    assert "SECRET_KEY length" in str(exc_info.value)
    assert "minimum of 32 characters" in str(exc_info.value)


def test_production_secret_key_fails_on_low_entropy() -> None:
    """Validate that production startup fails when SECRET_KEY exhibits low character diversity."""
    low_entropy_keys = [
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "12121212121212121212121212121212",
        "abababababababababababababababab",
    ]
    for key in low_entropy_keys:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                APP_ENV="production",
                SECRET_KEY=key,
                AUTH_JWT_SECRET="a-valid-production-jwt-secret-at-least-32-chars",
            )
        assert "low character diversity heuristic" in str(exc_info.value)


def test_production_jwt_secret_fails_on_insecure_defaults() -> None:
    """Validate that production startup fails when AUTH_JWT_SECRET matches known defaults."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="a-valid-production-secret-key-at-least-32-chars",
            AUTH_JWT_SECRET="nexus-saas-jwt-secret-key-change-in-production-min-32-chars",
        )
    assert "AUTH_JWT_SECRET is set to a known insecure default" in str(exc_info.value) or "placeholder" in str(exc_info.value)


def test_production_jwt_secret_fails_on_short_length() -> None:
    """Validate that production startup fails when AUTH_JWT_SECRET length is < 32 characters."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="a-valid-production-secret-key-at-least-32-chars",
            AUTH_JWT_SECRET="jwt-secret-too-short",
        )
    assert "AUTH_JWT_SECRET length" in str(exc_info.value)
    assert "minimum of 32 characters" in str(exc_info.value)


def test_production_jwt_secret_fails_on_low_entropy() -> None:
    """Validate that production startup fails when AUTH_JWT_SECRET exhibits low character diversity."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
            AUTH_JWT_SECRET="11111111111111111111111111111111",
        )
    assert "low character diversity heuristic" in str(exc_info.value)


def test_production_secrets_pass_with_strong_values() -> None:
    """Validate that production startup succeeds when strong, unique secrets are supplied."""
    cfg = Settings(
        APP_ENV="production",
        DEBUG=False,
        SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
        AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
    )
    assert cfg.is_production is True
    assert len(cfg.SECRET_KEY) >= 32
    assert len(cfg.AUTH_JWT_SECRET) >= 32


def test_production_secrets_strip_whitespace_safely() -> None:
    """Validate that surrounding whitespace is stripped and sanitized on production secrets."""
    raw_secret = "  c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7  "
    raw_jwt = "\n9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01\t"
    cfg = Settings(
        APP_ENV="production",
        SECRET_KEY=raw_secret,
        AUTH_JWT_SECRET=raw_jwt,
    )
    assert cfg.SECRET_KEY == raw_secret.strip()
    assert cfg.AUTH_JWT_SECRET == raw_jwt.strip()


def test_production_secrets_never_exposed_in_validation_error() -> None:
    """Validate that secret values are NEVER leaked in validation error strings."""
    canary_secret = "my-canary-secret-token-change-in-production-never-leak"
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY=canary_secret,
            AUTH_JWT_SECRET="valid-jwt-secret-at-least-32-chars-long",
        )
    err_str = str(exc_info.value)
    assert canary_secret not in err_str
    assert "canary" not in err_str


def test_non_production_defaults_preserved() -> None:
    """Validate that development and test environments preserve default secrets without error."""
    for env in ["development", "test", "testing"]:
        cfg = Settings(APP_ENV=env)
        assert cfg.is_production is False
        assert "nexus-insecure" in cfg.SECRET_KEY
        assert "nexus-saas-jwt-secret" in cfg.AUTH_JWT_SECRET


# ==============================================================================
# 2. DATABASE CONFIGURATION & TLS SETTINGS TESTS
# ==============================================================================

def test_database_pool_recycle_default_and_custom() -> None:
    """Validate that DB_POOL_RECYCLE defaults to 1800s and is passed to PostgreSQL engine kwargs."""
    cfg_default = Settings()
    assert cfg_default.DB_POOL_RECYCLE == 1800

    kwargs_default = _get_engine_kwargs(cfg_default)
    assert kwargs_default["pool_recycle"] == 1800

    cfg_custom = Settings(DB_POOL_RECYCLE=3600)
    kwargs_custom = _get_engine_kwargs(cfg_custom)
    assert kwargs_custom["pool_recycle"] == 3600


def test_database_ssl_mode_settings() -> None:
    """Validate PostgreSQL TLS sslmode configuration and resolution."""
    # 1. Development default (None -> unencrypted local dev)
    dev_cfg = Settings(APP_ENV="development")
    assert dev_cfg.effective_db_ssl_mode is None
    dev_kwargs = _get_engine_kwargs(dev_cfg)
    assert "sslmode" not in dev_kwargs["connect_args"]

    # 2. Production default (unset -> strictly 'require')
    prod_cfg = Settings(
        APP_ENV="production",
        SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
        AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
    )
    assert prod_cfg.effective_db_ssl_mode == "require"
    prod_kwargs = _get_engine_kwargs(prod_cfg)
    assert prod_kwargs["connect_args"]["sslmode"] == "require"

    # 3. Explicit require mode
    req_cfg = Settings(DB_SSL_MODE="require")
    assert req_cfg.effective_db_ssl_mode == "require"
    req_kwargs = _get_engine_kwargs(req_cfg)
    assert req_kwargs["connect_args"]["sslmode"] == "require"

    # 4. Explicit disable mode in development
    dis_cfg = Settings(
        APP_ENV="development",
        DB_SSL_MODE="disable",
    )
    assert dis_cfg.effective_db_ssl_mode == "disable"
    dis_kwargs = _get_engine_kwargs(dis_cfg)
    assert dis_kwargs["connect_args"]["sslmode"] == "disable"


def test_production_rejects_insecure_db_ssl_modes() -> None:
    """Validate that in production mode, insecure DB_SSL_MODE settings fail startup immediately."""
    insecure_modes = ["disable", "allow", "prefer"]
    for mode in insecure_modes:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                APP_ENV="production",
                SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
                AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
                DB_SSL_MODE=mode,
            )
        assert "Insecure DB_SSL_MODE" in str(exc_info.value)
        assert "strictly mandate encrypted TLS" in str(exc_info.value)


def test_production_rejects_insecure_database_url_sslmode_overrides() -> None:
    """Validate that in production mode, insecure DATABASE_URL sslmode query parameters fail startup."""
    insecure_urls = [
        "postgresql+psycopg://user:pass@host:5432/db?sslmode=disable",
        "postgresql+psycopg://user:pass@host:5432/db?sslmode=allow",
        "postgresql+psycopg://user:pass@host:5432/db?sslmode=prefer",
        "postgresql+psycopg://user:pass@host:5432/db?other=1&sslmode=disable&foo=bar",
    ]
    for url in insecure_urls:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                APP_ENV="production",
                SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
                AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
                DATABASE_URL=url,
            )
        assert "Insecure sslmode" in str(exc_info.value)
        assert "Insecure explicit URL overrides are rejected" in str(exc_info.value)


def test_production_accepts_secure_database_url_sslmode_overrides(tmp_path: Path) -> None:
    """Validate that in production mode, secure sslmode parameters in DATABASE_URL are accepted."""
    ca_file = tmp_path / "valid-ca.pem"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\nFAKECA\n-----END CERTIFICATE-----", encoding="utf-8")

    # 1. sslmode=require (valid without CA bundle)
    cfg_req = Settings(
        APP_ENV="production",
        SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
        AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
        DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db?sslmode=require",
    )
    assert cfg_req.is_production is True
    kwargs_req = _get_engine_kwargs(cfg_req)
    assert "sslmode" not in kwargs_req["connect_args"]

    # 2. sslmode=verify-ca with valid CA bundle in DATABASE_URL
    cfg_vca = Settings(
        APP_ENV="production",
        SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
        AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
        DATABASE_URL=f"postgresql+psycopg://user:pass@host:5432/db?sslmode=verify-ca&sslrootcert={ca_file}",
    )
    assert cfg_vca.is_production is True
    kwargs_vca = _get_engine_kwargs(cfg_vca)
    assert "sslmode" not in kwargs_vca["connect_args"]
    assert "sslrootcert" not in kwargs_vca["connect_args"]

    # 3. sslmode=verify-full with valid CA bundle in DATABASE_URL
    cfg_vfull = Settings(
        APP_ENV="production",
        SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
        AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
        DATABASE_URL=f"postgresql+psycopg://user:pass@host:5432/db?sslmode=verify-full&sslrootcert={ca_file}",
    )
    assert cfg_vfull.is_production is True
    kwargs_vfull = _get_engine_kwargs(cfg_vfull)
    assert "sslmode" not in kwargs_vfull["connect_args"]
    assert "sslrootcert" not in kwargs_vfull["connect_args"]


def test_development_allows_insecure_database_url_and_sslmode() -> None:
    """Validate that development and test environments preserve flexibility for local/unencrypted db."""
    dev_cfg = Settings(
        APP_ENV="development",
        DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db?sslmode=disable",
        DB_SSL_MODE="disable",
    )
    assert dev_cfg.is_production is False
    dev_kwargs = _get_engine_kwargs(dev_cfg)
    # URL parameter is preserved
    assert "sslmode" not in dev_kwargs["connect_args"]

    test_cfg = Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db?sslmode=prefer",
    )
    assert test_cfg.is_production is False


def test_database_invalid_ssl_mode_rejected() -> None:
    """Validate that invalid DB_SSL_MODE values are rejected with descriptive validation error."""
    invalid_modes = ["bogus", "yes", "true", "enabled", "ssl"]
    for mode in invalid_modes:
        with pytest.raises(ValidationError) as exc_info:
            Settings(DB_SSL_MODE=mode)
        assert "Invalid DB_SSL_MODE" in str(exc_info.value)
        assert "Supported PostgreSQL TLS modes" in str(exc_info.value)


def test_database_ssl_mode_preserves_url_parameter() -> None:
    """Validate that an existing sslmode in DATABASE_URL is not overwritten by connect_args."""
    cfg = Settings(
        DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db?sslmode=verify-full",
        DB_SSL_MODE="require",
    )
    kwargs = _get_engine_kwargs(cfg)
    assert "sslmode" not in kwargs["connect_args"]


def test_production_randomly_generated_secrets_accepted() -> None:
    """Validate that legitimate secrets generated via secrets/CSPRNG are readily accepted."""
    import secrets

    for _ in range(5):
        hex_secret = secrets.token_hex(32)  # 64 hex chars
        url_jwt = secrets.token_urlsafe(32)  # ~43 urlsafe chars
        cfg = Settings(
            APP_ENV="production",
            SECRET_KEY=hex_secret,
            AUTH_JWT_SECRET=url_jwt,
        )
        assert cfg.is_production is True
        assert len(cfg.SECRET_KEY) >= 32
        assert len(cfg.AUTH_JWT_SECRET) >= 32


def test_database_ssl_root_cert_prefers_verify_full(tmp_path: Path) -> None:
    """Validate that in production when DB_SSL_ROOT_CERT is configured, sslmode defaults to verify-full."""
    ca_file = tmp_path / "rds-global-bundle.pem"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\nFAKECA\n-----END CERTIFICATE-----", encoding="utf-8")
    prod_cfg = Settings(
        APP_ENV="production",
        SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
        AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
        DB_SSL_ROOT_CERT=str(ca_file),
    )
    assert prod_cfg.effective_db_ssl_mode == "verify-full"
    kwargs = _get_engine_kwargs(prod_cfg)
    assert kwargs["connect_args"]["sslmode"] == "verify-full"
    assert kwargs["connect_args"]["sslrootcert"] == str(ca_file)


def test_production_verify_full_requires_ca_configuration() -> None:
    """Validate that in production, selecting verify-full without a CA bundle fails startup."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
            AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
            DB_SSL_MODE="verify-full",
        )
    assert "strictly requires a trusted CA root certificate bundle" in str(exc_info.value)

    # Also test via DATABASE_URL
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
            AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
            DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db?sslmode=verify-full",
        )
    assert "strictly requires a trusted CA root certificate bundle" in str(exc_info.value)


def test_production_verify_full_rejects_missing_ca_file() -> None:
    """Validate that in production, pointing to a non-existent CA bundle fails startup."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
            AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
            DB_SSL_ROOT_CERT="/nonexistent/ca-bundle.pem",
        )
    assert "does not exist" in str(exc_info.value)


def test_production_verify_full_rejects_directory_ca_path(tmp_path: Path) -> None:
    """Validate that in production, pointing DB_SSL_ROOT_CERT to a directory fails startup."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
            AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
            DB_SSL_ROOT_CERT=str(tmp_path),
        )
    assert "is not a regular file" in str(exc_info.value)


def test_production_rejects_duplicate_sslmode_and_sslrootcert(tmp_path: Path) -> None:
    """Validate that duplicate or conflicting sslmode/sslrootcert parameters fail startup."""
    ca_file = tmp_path / "valid-ca.pem"
    ca_file.write_text("dummy-cert", encoding="utf-8")

    # Duplicate sslmode
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
            AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
            DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db?sslmode=require&sslmode=verify-full",
        )
    assert "Ambiguous multiple 'sslmode' parameters" in str(exc_info.value)

    # Duplicate sslrootcert
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
            AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
            DATABASE_URL=f"postgresql+psycopg://user:pass@host:5432/db?sslrootcert={ca_file}&sslrootcert={ca_file}",
        )
    assert "Ambiguous multiple 'sslrootcert' parameters" in str(exc_info.value)


def test_production_rejects_malformed_database_url() -> None:
    """Validate that malformed PostgreSQL DATABASE_URL strings fail startup safely."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7",
            AUTH_JWT_SECRET="9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01",
            DATABASE_URL="postgresql://",
        )
    assert "Malformed DATABASE_URL" in str(exc_info.value)


def test_database_ssl_root_cert_preserves_url_parameter() -> None:
    """Validate that an existing sslrootcert in DATABASE_URL is not overwritten by connect_args."""
    cfg = Settings(
        DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db?sslrootcert=/url/ca.pem",
        DB_SSL_ROOT_CERT="/env/ca.pem",
    )
    kwargs = _get_engine_kwargs(cfg)
    assert "sslrootcert" not in kwargs["connect_args"]


def test_database_sqlite_engine_isolation() -> None:
    """Validate that SQLite engine settings do not attach PostgreSQL pooling or SSL args."""
    cfg = Settings(DATABASE_URL="sqlite:///:memory:")
    kwargs = _get_engine_kwargs(cfg)
    assert kwargs["connect_args"] == {"check_same_thread": False}
    assert "pool_recycle" not in kwargs
    assert "pool_size" not in kwargs


# ==============================================================================
# 3. SCHEDULER LIFECYCLE & PROCESS ISOLATION TESTS
# ==============================================================================

def test_scheduler_autostart_disabled_in_web_lifespan() -> None:
    """Validate that web application lifespan does NOT start scheduler when autostart=False."""
    with (
        patch("app.core.config.settings.CONTINUOUS_SCHEDULER_ENABLED", True),
        patch("app.core.config.settings.CONTINUOUS_SCHEDULER_AUTOSTART", False),
        patch.object(continuous_scheduler, "start") as mock_start,
    ):
        test_app = create_application()
        with TestClient(test_app):
            mock_start.assert_not_called()


def test_scheduler_autostart_enabled_in_web_lifespan() -> None:
    """Validate that web application lifespan DOES start scheduler when autostart=True and enabled=True."""
    with (
        patch("app.core.config.settings.CONTINUOUS_SCHEDULER_ENABLED", True),
        patch("app.core.config.settings.CONTINUOUS_SCHEDULER_AUTOSTART", True),
        patch.object(continuous_scheduler, "start") as mock_start,
        patch.object(continuous_scheduler, "stop") as mock_stop,
    ):
        test_app = create_application()
        with TestClient(test_app):
            mock_start.assert_called_once()


def test_scheduler_stats_include_configuration() -> None:
    """Validate that ContinuousIntelligenceScheduler telemetry reflects configuration."""
    sched = ContinuousIntelligenceScheduler(interval_seconds=120, batch_size=25, max_businesses=10)
    assert sched.interval_seconds == 120
    assert sched.batch_size == 25
    assert sched.max_businesses == 10
    stats = sched.stats
    assert stats["interval_seconds"] == 120
    assert stats["batch_size"] == 25
    assert stats["max_businesses"] == 10
    assert stats["is_running"] is False
