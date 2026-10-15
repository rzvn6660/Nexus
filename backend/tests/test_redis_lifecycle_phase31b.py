"""Phase 31B Step 2: Redis Shared State Lifecycle & Reliability Tests.

Verifies:
1. Redis startup delay followed by recovery (no permanent local latch).
2. Redis disconnection and reconnection with exponential backoff.
3. Retry storm prevention during outage (bounded cooldowns, zero socket hammering).
4. Bounded connection and socket timeouts.
5. Clean client and connection pool disposal during shutdown.
6. Local mode explicitly configured for development and tests.
7. Production startup validation rejecting missing/invalid Redis configuration.
8. Observable backend status with strict credential redaction.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.cache import (
    CacheClient,
    CacheUnavailableError,
    _LocalCacheBackend,
    _RedisCacheBackend,
    _reset_cache_for_testing,
    close_cache,
    get_cache,
    redact_redis_url,
)
from app.core.config import Settings


# ==============================================================================
# 1. Startup Delay Followed by Recovery (Elimination of Permanent Local Latch)
# ==============================================================================


def test_redis_startup_delay_recovers_when_available():
    """Verify that a startup Redis failure falls back to local temporarily,
    and automatically transitions to Redis once it becomes available
    (eliminating the permanent local-backend latch).
    """
    mock_redis_client = MagicMock()
    # Initial probe fails (simulating Redis not ready yet)
    mock_redis_client.ping.side_effect = ConnectionError("Connection refused: Redis starting up")

    with patch("redis.Redis.from_url", return_value=mock_redis_client):
        client = CacheClient(redis_url="redis://localhost:6379/0", min_cooldown=0.1)

        # Startup probe failed -> local fallback active
        assert client.backend_mode == "redis"
        assert client.is_shared_backend is False
        assert isinstance(client.raw_backend, _LocalCacheBackend)

        # Local write works
        client.set("startup_key", "temporary_val", ttl_seconds=60)
        assert client.get("startup_key") == "temporary_val"

        # Now simulate Redis becoming ready
        mock_redis_client.ping.side_effect = None
        mock_redis_client.ping.return_value = True
        mock_redis_client.get.return_value = "redis_val"

        # Advance past cooldown
        time.sleep(0.15)

        # Next check should recover Redis!
        assert client.is_shared_backend is True
        assert client.raw_backend is not None
        assert not isinstance(client.raw_backend, _LocalCacheBackend)

        # Operations now route to Redis
        val = client.get("startup_key")
        assert val == "redis_val"
        mock_redis_client.get.assert_called_with("startup_key")

        client.close()


# ==============================================================================
# 2. Disconnection and Reconnection Lifecycle
# ==============================================================================


def test_redis_disconnection_and_reconnection():
    """Verify that if Redis disconnects mid-lifecycle, the client marks
    is_shared_backend=False, and once Redis recovers, re-establishes connection.
    """
    mock_redis_client = MagicMock()
    mock_redis_client.ping.return_value = True

    with patch("redis.Redis.from_url", return_value=mock_redis_client):
        client = CacheClient(redis_url="redis://localhost:6379/0", min_cooldown=0.1)
        assert client.is_shared_backend is True

        # Simulate Redis dropping connection during operation
        mock_redis_client.set.side_effect = ConnectionError("Connection reset by peer")

        with pytest.raises(ConnectionError):
            client.set("key", "val", 60)

        # Client detected failure and updated state
        mock_redis_client.ping.side_effect = ConnectionError("Host unreachable")
        assert client.is_shared_backend is False

        # Simulate Redis coming back up
        mock_redis_client.ping.side_effect = None
        mock_redis_client.ping.return_value = True
        mock_redis_client.set.side_effect = None

        time.sleep(0.15)

        # Reconnection succeeds
        assert client.is_shared_backend is True
        client.close()


# ==============================================================================
# 3. Retry Storm Prevention (Exponential Backoff Cooldowns)
# ==============================================================================


def test_retry_storm_prevention_during_outage():
    """Verify that when Redis is down, rapid repeated checks do NOT invoke
    ping repeatedly, protecting worker threads and backend services from retry storms.
    """
    mock_redis_client = MagicMock()
    mock_redis_client.ping.side_effect = ConnectionError("Service unavailable")

    with patch("redis.Redis.from_url", return_value=mock_redis_client):
        client = CacheClient(
            redis_url="redis://localhost:6379/0",
            min_cooldown=1.0,
            max_cooldown=10.0,
        )

        # Exactly 1 ping during __init__
        assert mock_redis_client.ping.call_count == 1
        assert client.is_shared_backend is False

        # Fire 10 rapid checks during cooldown window
        for _ in range(10):
            assert client.is_shared_backend is False

        # Ping count should NOT have increased (still 1) because cooldown is active
        assert mock_redis_client.ping.call_count == 1

        client.close()


def test_exponential_backoff_cooldown_progression():
    """Verify cooldown progressively doubles up to max_cooldown on consecutive failures."""
    mock_redis_client = MagicMock()
    mock_redis_client.ping.side_effect = ConnectionError("down")

    with patch("redis.Redis.from_url", return_value=mock_redis_client):
        client = CacheClient(
            redis_url="redis://localhost:6379/0",
            min_cooldown=0.05,
            max_cooldown=0.3,
        )

        # Initial failure: failure_count=1, cooldown=0.05
        assert client._failure_count == 1
        assert client._cooldown_seconds == 0.05

        # Wait past cooldown and probe again (failure 2 -> 0.10)
        time.sleep(0.06)
        client._check_redis(force=True)
        assert client._failure_count == 2
        assert client._cooldown_seconds == pytest.approx(0.10, rel=1e-2)

        # Wait past cooldown and probe again (failure 3 -> 0.20)
        time.sleep(0.11)
        client._check_redis(force=True)
        assert client._failure_count == 3
        assert client._cooldown_seconds == pytest.approx(0.20, rel=1e-2)

        # Wait past cooldown and probe again (failure 4 -> capped at max 0.30)
        time.sleep(0.21)
        client._check_redis(force=True)
        assert client._failure_count == 4
        assert client._cooldown_seconds == pytest.approx(0.30, rel=1e-2)

        client.close()


# ==============================================================================
# 4. Bounded Connection & Socket Timeouts
# ==============================================================================


def test_bounded_socket_timeouts_configured():
    """Verify that _RedisCacheBackend configures bounded socket timeouts (2.0s)
    and disables retry_on_timeout to avoid thread pool exhaustion.
    """
    mock_from_url = MagicMock()

    with patch("redis.Redis.from_url", mock_from_url):
        _RedisCacheBackend(
            "redis://localhost:6379/0",
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )

        mock_from_url.assert_called_once_with(
            "redis://localhost:6379/0",
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            retry_on_timeout=False,
        )


# ==============================================================================
# 5. Proper Shutdown and Connection Pool Disposal
# ==============================================================================


def test_clean_shutdown_and_pool_disposal():
    """Verify that client.close() and close_cache() cleanly dispose Redis connections."""
    mock_redis_client = MagicMock()
    mock_pool = MagicMock()
    mock_redis_client.connection_pool = mock_pool
    mock_redis_client.ping.return_value = True

    with patch("redis.Redis.from_url", return_value=mock_redis_client):
        client = CacheClient(redis_url="redis://localhost:6379/0")
        assert client.is_shared_backend is True

        client.close()

        mock_redis_client.close.assert_called_once()
        mock_pool.disconnect.assert_called_once()
        assert client.is_shared_backend is False
        assert client.get_status()["is_closed"] is True


def test_close_cache_singleton_lifecycle():
    """Verify module-level close_cache() cleanly disposes singleton instance."""
    mock_redis_client = MagicMock()
    mock_pool = MagicMock()
    mock_redis_client.connection_pool = mock_pool
    mock_redis_client.ping.return_value = True

    with patch("redis.Redis.from_url", return_value=mock_redis_client):
        client = CacheClient(redis_url="redis://localhost:6379/0")
        _reset_cache_for_testing(client)

        assert get_cache() is client

        close_cache()

        mock_redis_client.close.assert_called_once()
        mock_pool.disconnect.assert_called_once()

        # Next get_cache() builds a fresh client
        _reset_cache_for_testing(None)


# ==============================================================================
# 6. Local Mode Explicitly Configured for Development & Tests
# ==============================================================================


def test_local_mode_explicitly_configured():
    """Verify that when redis_url is None, the client operates purely in-memory
    without connection attempts or errors.
    """
    client = CacheClient(redis_url=None)

    assert client.backend_mode == "local"
    assert client.is_shared_backend is False
    assert client.is_available is True
    assert isinstance(client.raw_backend, _LocalCacheBackend)

    status = client.get_status()
    assert status["backend_mode"] == "local"
    assert status["redis_url_configured"] is False
    assert status["redis_url"] is None

    # Full CRUD in local mode
    client.set("test_key", "123", ttl_seconds=60)
    assert client.get("test_key") == "123"
    assert client.exists("test_key") is True
    assert client.incr("test_counter") == 1
    assert client.incr("test_counter") == 2
    client.delete("test_key")
    assert client.get("test_key") is None

    # Require shared raises expected error
    with pytest.raises(CacheUnavailableError):
        client.require_shared_backend()

    client.close()


# ==============================================================================
# 7. Credential Redaction & Observable Status
# ==============================================================================


def test_credential_redaction_in_urls_and_status():
    """Verify passwords in Redis URLs are redacted across logging and status inspection."""
    url_with_pass = "redis://:supersecretpassword@redis.internal:6379/0"
    url_with_user_pass = "rediss://nexus_user:extremelysecure@redis.internal:6380/0"
    plain_url = "redis://redis:6379/0"

    assert redact_redis_url(url_with_pass) == "redis://:<redacted>@redis.internal:6379/0"
    assert redact_redis_url(url_with_user_pass) == "rediss://nexus_user:<redacted>@redis.internal:6380/0"
    assert redact_redis_url(plain_url) == "redis://redis:6379/0"
    assert redact_redis_url(None) == ""

    mock_redis_client = MagicMock()
    mock_redis_client.ping.return_value = True

    with patch("redis.Redis.from_url", return_value=mock_redis_client):
        client = CacheClient(redis_url=url_with_user_pass)
        status = client.get_status()

        assert "extremelysecure" not in status["redis_url"]
        assert status["redis_url"] == "rediss://nexus_user:<redacted>@redis.internal:6380/0"
        client.close()


# ==============================================================================
# 8. Production Startup Configuration Validation
# ==============================================================================

# Valid cryptographically varied secrets meeting all production requirements
VALID_PROD_SECRET_KEY = "9f8b7c6d5e4a3b2c1d0e9f8a7b6c5d4e"
VALID_PROD_JWT_SECRET = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"


def test_production_rejects_missing_redis_when_fail_closed_mandatory():
    """Production startup must fail if shared security state is mandatory (REDIS_FAIL_CLOSED=True)
    but REDIS_URL is omitted or empty.
    """
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY=VALID_PROD_SECRET_KEY,
            AUTH_JWT_SECRET=VALID_PROD_JWT_SECRET,
            REDIS_FAIL_CLOSED=True,
            REDIS_URL=None,
        )

    assert "REDIS_URL is mandatory when shared security state is required" in str(exc_info.value)


def test_production_rejects_missing_redis_when_redis_required():
    """Production startup must fail if REDIS_REQUIRED=True but REDIS_URL is omitted."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY=VALID_PROD_SECRET_KEY,
            AUTH_JWT_SECRET=VALID_PROD_JWT_SECRET,
            REDIS_REQUIRED=True,
            REDIS_URL=None,
        )

    assert "REDIS_URL is mandatory when shared security state is required" in str(exc_info.value)


def test_production_rejects_unsupported_redis_scheme():
    """Production startup must reject invalid schemes (e.g. http:// or memcached://)."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY=VALID_PROD_SECRET_KEY,
            AUTH_JWT_SECRET=VALID_PROD_JWT_SECRET,
            REDIS_FAIL_CLOSED=True,
            REDIS_URL="http://redis:6379/0",
        )

    assert "Unsupported REDIS_URL scheme 'http'" in str(exc_info.value)


def test_production_rejects_placeholder_redis_url():
    """Production startup must reject insecure placeholder Redis URLs."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY=VALID_PROD_SECRET_KEY,
            AUTH_JWT_SECRET=VALID_PROD_JWT_SECRET,
            REDIS_FAIL_CLOSED=True,
            REDIS_URL="redis://:change-me@redis:6379/0",
        )

    assert "contains insecure placeholder token" in str(exc_info.value)


def test_production_accepts_valid_redis_configuration():
    """Production startup succeeds when valid secrets and REDIS_URL are provided."""
    s = Settings(
        APP_ENV="production",
        SECRET_KEY=VALID_PROD_SECRET_KEY,
        AUTH_JWT_SECRET=VALID_PROD_JWT_SECRET,
        REDIS_FAIL_CLOSED=True,
        REDIS_URL="redis://redis:6379/0",
    )
    assert s.REDIS_URL == "redis://redis:6379/0"
    assert s.REDIS_FAIL_CLOSED is True


def test_development_mode_allows_empty_redis():
    """In development, missing REDIS_URL is permitted even if REDIS_FAIL_CLOSED=True."""
    s = Settings(
        APP_ENV="development",
        REDIS_FAIL_CLOSED=True,
        REDIS_URL=None,
    )
    assert s.REDIS_URL is None
    assert s.REDIS_FAIL_CLOSED is True


# ==============================================================================
# 9. IPv6 & Unix Socket URL Redaction
# ==============================================================================


def test_credential_redaction_ipv6_and_unix_sockets():
    """Verify passwords in IPv6 and Unix domain socket URLs are cleanly redacted
    while preserving bracket notation and socket paths.
    """
    ipv6_url = "rediss://admin:supersecret@[2001:db8::1]:6380/0?ssl=true"
    unix_url = "unix://:socketpassword@/var/run/redis/redis.sock"

    redacted_ipv6 = redact_redis_url(ipv6_url)
    redacted_unix = redact_redis_url(unix_url)

    assert "supersecret" not in redacted_ipv6
    assert redacted_ipv6 == "rediss://admin:<redacted>@[2001:db8::1]:6380/0?ssl=true"

    assert "socketpassword" not in redacted_unix
    assert redacted_unix == "unix://:<redacted>@/var/run/redis/redis.sock"


# ==============================================================================
# 10. Concurrency & Multi-Threaded Stability
# ==============================================================================


def test_concurrent_thread_access_during_redis_failure_and_recovery():
    """Verify that multiple threads concurrently interacting with CacheClient
    during connection drop and recovery execute safely without deadlocks or races.
    """
    import concurrent.futures

    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.get.return_value = "val"
    mock_redis.set.return_value = True

    with patch("redis.Redis.from_url", return_value=mock_redis):
        client = CacheClient(redis_url="redis://localhost:6379/0", min_cooldown=0.01)

        def worker_task(thread_id: int):
            for i in range(20):
                if thread_id % 2 == 0 and i == 10:
                    # Thread simulates a transient failure
                    client._record_failure(ConnectionError("Simulated concurrent drop"))
                _ = client.is_shared_backend
                _ = client.get(f"key_{thread_id}_{i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_task, tid) for tid in range(8)]
            for f in concurrent.futures.as_completed(futures):
                f.result()  # no exceptions / deadlocks

        client.close()


# ==============================================================================
# 11. Redis Resource Exhaustion & OOM Simulation
# ==============================================================================


def test_redis_resource_exhaustion_oom_behavior():
    """Verify that Redis OOM errors (ResponseError: OOM command not allowed)
    are propagated to the caller rather than swallowed, so callers can fail-closed,
    while subsequent ordinary caching safely degrades to local fallback.
    """
    import redis

    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.set.side_effect = redis.ResponseError(
        "OOM command not allowed when used memory > 'maxmemory'"
    )
    mock_redis.incr.side_effect = redis.ResponseError(
        "OOM command not allowed when used memory > 'maxmemory'"
    )

    with patch("redis.Redis.from_url", return_value=mock_redis):
        client = CacheClient(redis_url="redis://localhost:6379/0")

        # 1. SET on active Redis must raise ResponseError on OOM (not swallowed)
        with pytest.raises(redis.ResponseError) as exc_set:
            client.set("some_key", "some_val", 60)
        assert "OOM command not allowed" in str(exc_set.value)

        # 2. Redis failure is recorded -> shared backend is marked unavailable
        assert client.is_shared_backend is False

        # 3. Security-sensitive callers calling require_shared_backend() fail-closed
        with pytest.raises(CacheUnavailableError):
            client.require_shared_backend()

        # 4. Ordinary caching can safely bypass Redis during outage into local store
        client.set("non_critical_key", "local_val", 60)
        assert client.get("non_critical_key") == "local_val"

        # 5. INCR on a fresh client with active Redis must also raise ResponseError on OOM
        client2 = CacheClient(redis_url="redis://localhost:6379/0")
        assert client2.is_shared_backend is True
        with pytest.raises(redis.ResponseError) as exc_incr:
            client2.incr("rate_limit_bucket")
        assert "OOM command not allowed" in str(exc_incr.value)

        client.close()
        client2.close()


# ==============================================================================
# 12. Repeated Lifespan Startup and Shutdown Cycles
# ==============================================================================


def test_repeated_lifespan_startup_and_shutdown():
    """Verify that CacheClient cleanly handles repeated startup and shutdown
    cycles across multiple application lifespans without resource leakage.
    """
    mock_redis = MagicMock()
    mock_pool = MagicMock()
    mock_redis.connection_pool = mock_pool
    mock_redis.ping.return_value = True

    with patch("redis.Redis.from_url", return_value=mock_redis):
        for cycle in range(3):
            client = CacheClient(redis_url="redis://localhost:6379/0")
            _reset_cache_for_testing(client)

            c = get_cache()
            assert c.is_shared_backend is True

            close_cache()
            assert c.get_status()["is_closed"] is True

        assert mock_redis.close.call_count == 3
        assert mock_pool.disconnect.call_count == 3
        _reset_cache_for_testing(None)

