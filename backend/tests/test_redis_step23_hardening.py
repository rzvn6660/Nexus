"""Tests for Phase 31B Step 2.3 — JWT Revocation and Rate-Limit Shared-State Hardening.

Coverage:
1. Startup Redis outage: fail closed on revocation, check, decode, rate-limit.
2. Reconnect cooldown: non-blocking immediate 503 failure during backoff window.
3. Mid-operation disconnect: ConnectionError/TimeoutError during set/exists/incr_with_ttl.
4. Redis OOM / write failures: ResponseError("OOM...") triggers fail-closed 503.
5. Multi-worker revocation assumptions: process-local store is not authoritative in production.
6. Rate-limit expiry atomicity: Lua script INCR + EXPIRE and TTL repair for TTL < 0.
7. Multi-backend reset: RateLimiter.reset() clears both local memory and Redis bucket.
8. Fail-open vs fail-closed: Graceful degradation in dev mode vs strict 503 in prod mode.
9. Security hygiene: No token strings or secrets logged; LLM_ALLOW_EXTERNAL_CALLS=False.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import redis
from fastapi import HTTPException

from app.core.cache import (
    CacheClient,
    _LocalCacheBackend,
    _RedisCacheBackend,
    _reset_cache_for_testing,
)
from app.core.config import settings
from app.core.rate_limit import RateLimiter, auth_rate_limiter
from app.services.auth_service import AuthService


@pytest.fixture(autouse=True)
def cleanup_cache_and_state():
    """Ensure clean singleton and state before and after each test."""
    _reset_cache_for_testing(None)
    auth_rate_limiter.clear_all()
    AuthService._local_revoked_tokens.clear()
    yield
    _reset_cache_for_testing(None)
    auth_rate_limiter.clear_all()
    AuthService._local_revoked_tokens.clear()


# ===========================================================================
# 1. Startup Redis outage
# ===========================================================================


def test_jwt_revocation_fail_closed_on_startup_outage():
    """When Redis is unreachable at startup and REDIS_FAIL_CLOSED=True, all auth ops fail closed."""
    # Simulate client whose Redis backend failed at startup (is_shared_backend is False)
    client = CacheClient(redis_url="redis://nonexistent-host:6379/0", min_cooldown=1.0)
    _reset_cache_for_testing(client)
    assert client.is_shared_backend is False

    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        # 1. Revoke token must fail closed
        with pytest.raises(HTTPException) as exc_info:
            AuthService.revoke_token("test-jti-startup-1")
        assert exc_info.value.status_code == 503
        assert "temporarily unavailable" in exc_info.value.detail

        # 2. Check token revoked must fail closed
        with pytest.raises(HTTPException) as exc_info:
            AuthService.is_token_revoked("test-jti-startup-1")
        assert exc_info.value.status_code == 503

        # 3. Decode access token must fail closed (cannot verify revocation)
        valid_token = AuthService.create_access_token(
            user_id="u-startup-1",
            email="startup@example.com",
            expires_delta=timedelta(minutes=15),
        )
        with pytest.raises(HTTPException) as exc_info:
            AuthService.decode_access_token(valid_token)
        assert exc_info.value.status_code == 503


def test_rate_limiter_fail_closed_on_startup_outage():
    """When Redis is unreachable at startup and REDIS_FAIL_CLOSED=True, rate limit fails closed."""
    client = CacheClient(redis_url="redis://nonexistent-host:6379/0", min_cooldown=1.0)
    _reset_cache_for_testing(client)
    rl = RateLimiter()

    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            rl.check_rate_limit("ip:192.168.1.1", max_requests=5, window_seconds=60)
        assert exc_info.value.status_code == 503
        assert "Rate limiting service unavailable" in exc_info.value.detail

        with pytest.raises(HTTPException) as exc_info:
            rl.record_attempt("ip:192.168.1.1", max_requests=5, window_seconds=60)
        assert exc_info.value.status_code == 503


# ===========================================================================
# 2. Recovery cooldown
# ===========================================================================


def test_jwt_revocation_during_reconnect_cooldown():
    """During reconnect cooldown, auth ops fail closed immediately without probing Redis."""
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = redis.ConnectionError("Redis down")

    with patch("redis.Redis.from_url", return_value=mock_redis):
        client = CacheClient(redis_url="redis://localhost:6379/0", min_cooldown=5.0)
        _reset_cache_for_testing(client)

        # Confirm client is in failure cooldown
        assert client.get_status()["consecutive_failures"] > 0
        assert client.is_shared_backend is False

        with patch.object(settings, "REDIS_FAIL_CLOSED", True):
            with pytest.raises(HTTPException) as exc_info:
                AuthService.is_token_revoked("jti-cooldown-1")
            assert exc_info.value.status_code == 503

            with pytest.raises(HTTPException) as exc_info:
                AuthService.revoke_token("jti-cooldown-1")
            assert exc_info.value.status_code == 503

            rl = RateLimiter()
            with pytest.raises(HTTPException) as exc_info:
                rl.check_rate_limit("cooldown-key", 5, 60)
            assert exc_info.value.status_code == 503


# ===========================================================================
# 3. Mid-operation disconnect
# ===========================================================================


def test_jwt_revocation_mid_operation_disconnect_on_set():
    """If Redis disconnects during cache.set in revoke_token, fails closed with 503."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.set.side_effect = redis.ConnectionError("Connection lost mid-write")
    _reset_cache_for_testing(mock_cache)

    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            AuthService.revoke_token("jti-mid-disconnect-1")
        assert exc_info.value.status_code == 503
        assert "Token revocation could not be persisted" in exc_info.value.detail


def test_jwt_revocation_mid_operation_disconnect_on_exists():
    """If Redis disconnects during cache.exists in is_token_revoked, fails closed with 503."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.exists.side_effect = redis.TimeoutError("Timeout reading from Redis")
    _reset_cache_for_testing(mock_cache)

    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            AuthService.is_token_revoked("jti-mid-disconnect-2")
        assert exc_info.value.status_code == 503
        assert "temporarily unavailable" in exc_info.value.detail


def test_rate_limiter_mid_operation_disconnect():
    """If Redis disconnects during incr_with_ttl, rate limiter fails closed with 503."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.incr_with_ttl.side_effect = redis.ConnectionError("Connection reset by peer")
    _reset_cache_for_testing(mock_cache)

    rl = RateLimiter()
    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            rl.check_rate_limit("mid-disconnect-ip", max_requests=10, window_seconds=60)
        assert exc_info.value.status_code == 503


# ===========================================================================
# 4. Redis OOM / write failures
# ===========================================================================


def test_jwt_revocation_redis_oom_write_failure():
    """Redis OOM response error during revoke_token fails closed with 503."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.set.side_effect = redis.ResponseError(
        "OOM command not allowed when used memory > 'maxmemory'"
    )
    _reset_cache_for_testing(mock_cache)

    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            AuthService.revoke_token("jti-oom-1")
        assert exc_info.value.status_code == 503
        assert "Token revocation could not be persisted" in exc_info.value.detail


def test_rate_limiter_redis_oom_failure():
    """Redis OOM response error during rate-limit increment fails closed with 503."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.incr_with_ttl.side_effect = redis.ResponseError(
        "OOM command not allowed when used memory > 'maxmemory'"
    )
    _reset_cache_for_testing(mock_cache)

    rl = RateLimiter()
    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            rl.check_rate_limit("oom-ip", max_requests=10, window_seconds=60)
        assert exc_info.value.status_code == 503


# ===========================================================================
# 5. Multi-worker revocation assumptions (non-authoritative local state)
# ===========================================================================


def test_multi_worker_revocation_not_bypassed_by_empty_local_store():
    """In fail-closed production mode, empty local store is NEVER treated as proof token is valid.

    If Redis is down, Worker 2 must raise 503, never return False (allow).
    """
    # Simulate Worker 2 with empty local store and unavailable Redis
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = False
    _reset_cache_for_testing(mock_cache)

    # Worker 2 local store has never seen this JTI
    assert "jti-revoked-by-worker-1" not in AuthService._local_revoked_tokens

    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            AuthService.is_token_revoked("jti-revoked-by-worker-1")
        assert exc_info.value.status_code == 503


def test_multi_worker_revocation_failure_does_not_silently_pretend_success():
    """Worker 1 must NOT report successful revocation if shared state write fails."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.set.side_effect = redis.ConnectionError("Redis network partition")
    _reset_cache_for_testing(mock_cache)

    with patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            AuthService.revoke_token("jti-fail-write")
        assert exc_info.value.status_code == 503


# ===========================================================================
# 6. Rate-limit expiry atomicity (Lua script & TTL behavior)
# ===========================================================================


def test_rate_limiter_lua_atomic_incr_with_ttl_logic():
    """Verify Lua script logic in _RedisCacheBackend and local backend."""
    # 1. Local backend atomicity test
    local = _LocalCacheBackend()
    c1 = local.incr_with_ttl("test:lua:key", 60)
    assert c1 == 1
    c2 = local.incr_with_ttl("test:lua:key", 60)
    assert c2 == 2

    # 2. Redis backend Lua evaluation test
    mock_redis = MagicMock()
    mock_redis.eval.return_value = 1
    backend = _RedisCacheBackend.__new__(_RedisCacheBackend)
    backend._client = mock_redis
    result = backend.incr_with_ttl("rl:test:1", 61)
    assert result == 1
    mock_redis.eval.assert_called_once_with(backend._INCR_WITH_TTL_SCRIPT, 1, "rl:test:1", 61)


def test_rate_limiter_reset_clears_both_local_and_redis():
    """RateLimiter.reset() clears in-memory records and active Redis key."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    _reset_cache_for_testing(mock_cache)

    rl = RateLimiter()
    # Add local record
    with rl._local_lock:
        rl._local_records["user:reset:1"] = [time.time()]

    # Reset with specific window
    rl.reset("user:reset:1", window_seconds=60)

    # Local record cleared
    assert "user:reset:1" not in rl._local_records
    # Redis delete called with window bucket
    mock_cache.delete.assert_called_once()
    deleted_key = mock_cache.delete.call_args[0][0]
    assert deleted_key.startswith("rl:user:reset:1:")


def test_rate_limiter_reset_without_window_clears_standard_buckets():
    """RateLimiter.reset() without window_seconds purges common buckets."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    _reset_cache_for_testing(mock_cache)

    rl = RateLimiter()
    rl.reset("user:reset:2")
    # Deletes across standard windows (60, 300, 900, 3600)
    assert mock_cache.delete.call_count == 4


# ===========================================================================
# 7. Fail-open versus fail-closed behavior
# ===========================================================================


def test_fail_open_in_development_mode():
    """When REDIS_FAIL_CLOSED=False and APP_ENV != production, system falls back gracefully."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = False
    _reset_cache_for_testing(mock_cache)

    with patch.object(settings, "REDIS_FAIL_CLOSED", False), patch.object(
        settings, "APP_ENV", "development"
    ):
        # Revoke falls back to local without raising 503
        AuthService.revoke_token("dev-jti-1")
        assert AuthService.is_token_revoked("dev-jti-1") is True
        assert AuthService.is_token_revoked("dev-jti-nonexistent") is False

        # Rate limiter falls back to local without raising 503
        rl = RateLimiter()
        allowed, retry_after = rl.check_rate_limit("dev-ip-1", max_requests=5, window_seconds=60)
        assert allowed is True
        assert retry_after == 0


def test_fail_closed_in_production_mode():
    """When APP_ENV == 'production', operations fail closed even if fail_closed flag is None."""
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = False
    _reset_cache_for_testing(mock_cache)

    with patch.object(settings, "APP_ENV", "production"), patch.object(
        settings, "REDIS_FAIL_CLOSED", False
    ):
        # Revoke fails closed in production
        with pytest.raises(HTTPException) as exc_info:
            AuthService.revoke_token("prod-jti-1")
        assert exc_info.value.status_code == 503

        # Revocation check fails closed in production
        with pytest.raises(HTTPException) as exc_info:
            AuthService.is_token_revoked("prod-jti-1")
        assert exc_info.value.status_code == 503

        # Rate limiter fails closed in production
        rl = RateLimiter()
        with pytest.raises(HTTPException) as exc_info:
            rl.check_rate_limit("prod-ip-1", max_requests=5, window_seconds=60)
        assert exc_info.value.status_code == 503


# ===========================================================================
# 8. Security and Secret Hygiene
# ===========================================================================


def test_security_tokens_and_secrets_never_logged(caplog):
    """Raw JWT tokens, passwords, and sensitive keys are never output to loggers."""
    secret_token = AuthService.create_access_token(
        user_id="u-secret-99",
        email="secret@example.com",
        expires_delta=timedelta(minutes=15),
    )

    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.set.side_effect = redis.ConnectionError("Network glitch")
    _reset_cache_for_testing(mock_cache)

    with caplog.at_level(logging.DEBUG), patch.object(settings, "REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException):
            AuthService.revoke_token(secret_token)

    # Verify secret_token is not in any logged record
    for record in caplog.records:
        assert secret_token not in record.message
        assert "secret@example.com" not in record.message


def test_llm_allow_external_calls_remains_false():
    """Strict guard: LLM_ALLOW_EXTERNAL_CALLS must remain False by default."""
    assert getattr(settings, "LLM_ALLOW_EXTERNAL_CALLS", False) is False
