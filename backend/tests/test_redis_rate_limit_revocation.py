"""Tests for Phase 23.6 production hardening: Redis-backed rate limiting and JWT revocation.

Coverage:
1.  Local cache backend — basic set/get/delete/exists/incr/expire/TTL
2.  CacheClient factory — no REDIS_URL → local backend
3.  CacheClient factory — bad REDIS_URL → local fallback (no crash)
4.  Rate limiter — local fallback allows requests within limit
5.  Rate limiter — local fallback blocks requests over limit
6.  Rate limiter — reset() clears local records (successful-login flow)
7.  Rate limiter — disabled flag bypasses all checks
8.  Rate limiter — REDIS_FAIL_CLOSED=True raises 503 when shared backend absent
9.  Rate limiter — REDIS_FAIL_CLOSED=False falls back gracefully (no exception)
10. JWT revocation — revoke_token stores JTI, is_token_revoked returns True
11. JWT revocation — non-revoked JTI returns False
12. JWT revocation — revoke by raw JWT string extracts JTI correctly
13. JWT revocation — local fallback stores revoked JTI when cache is local
14. JWT revocation — REDIS_FAIL_CLOSED=True raises 503 on revocation check error
15. JWT revocation — TTL expiry removes revoked entry (simulated)
16. Multi-worker simulation — shared local cache reflects revocations across instances
17. Rate limiter — window boundary resets counter
18. Rate limiter Redis path — INCR increments and EXPIRE is set
19. AuthService.decode_access_token — revoked token raises 401
20. AuthService.decode_access_token — non-revoked token decodes normally
21. _reset_cache_for_testing helper works correctly
22. CacheClient.require_shared_backend raises CacheUnavailableError on local
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Local helpers / fixtures
# ---------------------------------------------------------------------------


def _make_local_cache():
    """Return a fresh _LocalCacheBackend."""
    from app.core.cache import _LocalCacheBackend
    return _LocalCacheBackend()


def _make_local_client(redis_url: Optional[str] = None):
    """Return a CacheClient backed by the local fallback."""
    from app.core.cache import CacheClient
    return CacheClient(redis_url=redis_url)


# ---------------------------------------------------------------------------
# 1. Local backend — set / get / delete / exists
# ---------------------------------------------------------------------------


def test_local_cache_set_get():
    backend = _make_local_cache()
    backend.set("k1", "hello", ttl_seconds=60)
    assert backend.get("k1") == "hello"


def test_local_cache_ttl_expiry():
    """Expired entries must not be returned."""
    backend = _make_local_cache()
    backend.set("k2", "value", ttl_seconds=1)
    # Manually push the stored time into the past
    with backend._lock:
        key, (val, _) = list(backend._store.items())[0]
        backend._store[key] = (val, time.monotonic() - 1)
    assert backend.get("k2") is None


def test_local_cache_delete():
    backend = _make_local_cache()
    backend.set("k3", "x", ttl_seconds=60)
    backend.delete("k3")
    assert backend.get("k3") is None


def test_local_cache_exists():
    backend = _make_local_cache()
    assert not backend.exists("nope")
    backend.set("k4", "y", ttl_seconds=60)
    assert backend.exists("k4")


def test_local_cache_incr():
    backend = _make_local_cache()
    assert backend.incr("counter") == 1
    assert backend.incr("counter") == 2
    assert backend.incr("counter") == 3


def test_local_cache_expire():
    backend = _make_local_cache()
    backend.set("k5", "z", ttl_seconds=60)
    # Push expire time to the past
    backend.expire("k5", 0)
    # Mark as expired by setting monotonic time < now
    with backend._lock:
        val, _ = backend._store["k5"]
        backend._store["k5"] = (val, time.monotonic() - 1)
    assert backend.get("k5") is None


def test_local_cache_clear_all():
    backend = _make_local_cache()
    backend.set("a", "1", 60)
    backend.set("b", "2", 60)
    backend.clear_all()
    assert backend.get("a") is None
    assert backend.get("b") is None


# ---------------------------------------------------------------------------
# 2. CacheClient factory — no REDIS_URL → local backend
# ---------------------------------------------------------------------------


def test_cache_client_no_redis_url_uses_local():
    from app.core.cache import CacheClient, _LocalCacheBackend
    client = CacheClient(redis_url=None)
    assert not client.is_shared_backend
    assert isinstance(client.raw_backend, _LocalCacheBackend)
    assert client.is_available


# ---------------------------------------------------------------------------
# 3. CacheClient factory — bad REDIS_URL → graceful fallback
# ---------------------------------------------------------------------------


def test_cache_client_bad_redis_url_falls_back():
    """A bad Redis URL should NOT crash startup; should fall back to local."""
    from app.core.cache import CacheClient, _LocalCacheBackend
    client = CacheClient(redis_url="redis://localhost:1/0")  # unreachable
    # Either Redis connected (unlikely in CI) or fell back to local
    if not client.is_shared_backend:
        assert isinstance(client.raw_backend, _LocalCacheBackend)


# ---------------------------------------------------------------------------
# 4-9. Rate limiter tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def fresh_rate_limiter():
    """Return a fresh RateLimiter with local cache injected."""
    from app.core.cache import CacheClient, _reset_cache_for_testing
    from app.core.rate_limit import RateLimiter

    local_client = CacheClient(redis_url=None)
    _reset_cache_for_testing(local_client)
    rl = RateLimiter()
    rl.enabled = True
    yield rl
    _reset_cache_for_testing(None)  # reset singleton


def test_rate_limiter_allows_within_limit(fresh_rate_limiter):
    rl = fresh_rate_limiter
    for _ in range(3):
        allowed, retry_after = rl.check_rate_limit("user:1", max_requests=5, window_seconds=60)
        assert allowed
        assert retry_after == 0


def test_rate_limiter_blocks_over_limit(fresh_rate_limiter):
    rl = fresh_rate_limiter
    for _ in range(5):
        rl.check_rate_limit("user:2", max_requests=5, window_seconds=60)
    allowed, retry_after = rl.check_rate_limit("user:2", max_requests=5, window_seconds=60)
    assert not allowed
    assert retry_after >= 1


def test_rate_limiter_raises_429(fresh_rate_limiter):
    from fastapi import HTTPException

    rl = fresh_rate_limiter
    for _ in range(3):
        rl.record_attempt("ip:127.0.0.1", max_requests=3, window_seconds=60)
    with pytest.raises(HTTPException) as exc_info:
        rl.record_attempt("ip:127.0.0.1", max_requests=3, window_seconds=60)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_rate_limiter_reset_clears_local(fresh_rate_limiter):
    rl = fresh_rate_limiter
    for _ in range(3):
        rl.check_rate_limit("user:3", max_requests=5, window_seconds=60)
    rl.reset("user:3")
    # After reset, counter should be back to 0 in local store
    allowed, _ = rl.check_rate_limit("user:3", max_requests=5, window_seconds=60)
    assert allowed


def test_rate_limiter_disabled_bypasses_check(fresh_rate_limiter):
    rl = fresh_rate_limiter
    rl.enabled = False
    for _ in range(100):
        allowed, _ = rl.check_rate_limit("user:4", max_requests=1, window_seconds=60)
        assert allowed


def test_rate_limiter_fail_closed_raises_503_no_redis():
    """When REDIS_FAIL_CLOSED=True and only local backend, raise 503."""
    from fastapi import HTTPException
    from app.core.cache import CacheClient, _reset_cache_for_testing
    from app.core.rate_limit import RateLimiter

    local_client = CacheClient(redis_url=None)
    _reset_cache_for_testing(local_client)

    rl = RateLimiter()
    rl.enabled = True

    with patch("app.core.config.settings.REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            rl.check_rate_limit("user:5", max_requests=5, window_seconds=60)
        assert exc_info.value.status_code == 503

    _reset_cache_for_testing(None)


def test_rate_limiter_fail_open_no_exception_no_redis():
    """When REDIS_FAIL_CLOSED=False (default dev mode), gracefully fall back."""
    from app.core.cache import CacheClient, _reset_cache_for_testing
    from app.core.rate_limit import RateLimiter

    local_client = CacheClient(redis_url=None)
    _reset_cache_for_testing(local_client)

    rl = RateLimiter()
    rl.enabled = True

    with patch("app.core.config.settings.REDIS_FAIL_CLOSED", False):
        allowed, _ = rl.check_rate_limit("user:6", max_requests=5, window_seconds=60)
        assert allowed

    _reset_cache_for_testing(None)


# ---------------------------------------------------------------------------
# 10-15. JWT revocation tests
# ---------------------------------------------------------------------------


@pytest.fixture
def local_cache_setup():
    from app.core.cache import CacheClient, _reset_cache_for_testing
    client = CacheClient(redis_url=None)
    _reset_cache_for_testing(client)
    yield client
    _reset_cache_for_testing(None)
    # Also clear the local fallback store
    from app.services.auth_service import AuthService
    AuthService._local_revoked_tokens.clear()


def test_revoke_jti_and_check(local_cache_setup):
    from app.services.auth_service import AuthService
    AuthService.revoke_token("test-jti-001")
    assert AuthService.is_token_revoked("test-jti-001")


def test_non_revoked_jti_not_blocked(local_cache_setup):
    from app.services.auth_service import AuthService
    assert not AuthService.is_token_revoked("non-revoked-jti-xyz")


def test_revoke_by_raw_jwt_extracts_jti(local_cache_setup):
    """Revoking a raw JWT string should extract and store its JTI."""
    from app.services.auth_service import AuthService

    token = AuthService.create_access_token(
        user_id="u1",
        email="test@example.com",
        expires_delta=timedelta(minutes=30),
    )
    import jwt
    from app.core.config import settings
    payload = jwt.decode(token, settings.AUTH_JWT_SECRET, algorithms=[settings.AUTH_JWT_ALGORITHM])
    jti = payload["jti"]

    AuthService.revoke_token(token)
    assert AuthService.is_token_revoked(jti)


def test_revoke_none_jti_safe(local_cache_setup):
    """is_token_revoked(None) must return False without error."""
    from app.services.auth_service import AuthService
    assert not AuthService.is_token_revoked(None)


def test_revoked_token_rejected_by_decode_access_token(local_cache_setup):
    """decode_access_token must raise HTTP 401 for a revoked token."""
    from fastapi import HTTPException
    from app.services.auth_service import AuthService

    token = AuthService.create_access_token(
        user_id="u2",
        email="revoked@example.com",
        expires_delta=timedelta(minutes=30),
    )
    AuthService.revoke_token(token)

    with pytest.raises(HTTPException) as exc_info:
        AuthService.decode_access_token(token)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()


def test_valid_token_decodes_normally(local_cache_setup):
    """A non-revoked, non-expired token must decode without error."""
    from app.services.auth_service import AuthService

    token = AuthService.create_access_token(
        user_id="u3",
        email="valid@example.com",
        expires_delta=timedelta(minutes=30),
    )
    payload = AuthService.decode_access_token(token)
    assert payload["email"] == "valid@example.com"


def test_ttl_expiry_removes_revoked_jti():
    """Simulate TTL expiry — entry removed from local cache after TTL."""
    from app.core.cache import _LocalCacheBackend
    backend = _LocalCacheBackend()

    jti = "expiring-jti"
    backend.set(f"jwt:revoked:{jti}", "1", ttl_seconds=1)
    assert backend.exists(f"jwt:revoked:{jti}")

    # Manually expire the key
    with backend._lock:
        key = f"jwt:revoked:{jti}"
        val, _ = backend._store[key]
        backend._store[key] = (val, time.monotonic() - 1)

    assert not backend.exists(f"jwt:revoked:{jti}")


def test_fail_closed_revocation_check_raises_503():
    """When Redis check raises an error and REDIS_FAIL_CLOSED=True, must return 503."""
    from fastapi import HTTPException
    from app.core.cache import CacheClient, _reset_cache_for_testing
    from app.services.auth_service import AuthService

    # Simulate a shared-backend client that raises on exists()
    mock_backend = MagicMock()
    mock_backend.is_available = True
    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.exists.side_effect = Exception("Simulated Redis error")

    _reset_cache_for_testing(mock_cache)

    with patch("app.core.config.settings.REDIS_FAIL_CLOSED", True):
        with pytest.raises(HTTPException) as exc_info:
            AuthService.is_token_revoked("some-jti")
        assert exc_info.value.status_code == 503

    _reset_cache_for_testing(None)
    AuthService._local_revoked_tokens.clear()


# ---------------------------------------------------------------------------
# 16. Multi-worker simulation
# ---------------------------------------------------------------------------


def test_shared_local_cache_across_threads():
    """Revocations written by one thread are visible to another (shared local client)."""
    from app.core.cache import CacheClient, _reset_cache_for_testing
    from app.services.auth_service import AuthService

    shared_client = CacheClient(redis_url=None)
    _reset_cache_for_testing(shared_client)
    AuthService._local_revoked_tokens.clear()

    results: list[bool] = []

    def writer():
        AuthService.revoke_token("shared-jti-1")

    def reader():
        time.sleep(0.05)  # small delay to let writer run first
        results.append(AuthService.is_token_revoked("shared-jti-1"))

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=reader)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # In local mode, the local_revoked_tokens set is class-level → shared
    assert results[0] is True

    _reset_cache_for_testing(None)
    AuthService._local_revoked_tokens.clear()


# ---------------------------------------------------------------------------
# 17. Window boundary resets counter
# ---------------------------------------------------------------------------


def test_rate_limiter_new_window_resets_counter(fresh_rate_limiter):
    """Requests in a new time window should start with a fresh counter."""
    rl = fresh_rate_limiter
    # Fill window 1
    for _ in range(3):
        rl.check_rate_limit("user:7", max_requests=3, window_seconds=60)

    # Simulate all timestamps being old (outside the sliding window)
    with rl._local_lock:
        rl._local_records["user:7"] = [time.time() - 120]  # 2 minutes ago

    # Should be allowed again in the "new" window
    allowed, _ = rl.check_rate_limit("user:7", max_requests=3, window_seconds=60)
    assert allowed


# ---------------------------------------------------------------------------
# 18. Rate limiter Redis path — INCR and EXPIRE are called
# ---------------------------------------------------------------------------


def test_rate_limiter_redis_path_uses_incr_expire():
    """When shared backend is active, check_rate_limit must use INCR + EXPIRE."""
    from app.core.cache import CacheClient, _reset_cache_for_testing
    from app.core.rate_limit import RateLimiter

    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.is_available = True
    mock_cache.incr.return_value = 1  # first request in window

    _reset_cache_for_testing(mock_cache)

    rl = RateLimiter()
    rl.enabled = True
    allowed, _ = rl.check_rate_limit("user:8", max_requests=5, window_seconds=60)

    assert allowed
    mock_cache.incr.assert_called_once()
    mock_cache.expire.assert_called_once()

    _reset_cache_for_testing(None)


def test_rate_limiter_redis_path_blocks_over_limit():
    """Redis path blocks when INCR returns > max_requests."""
    from app.core.cache import CacheClient, _reset_cache_for_testing
    from app.core.rate_limit import RateLimiter

    mock_cache = MagicMock(spec=CacheClient)
    mock_cache.is_shared_backend = True
    mock_cache.is_available = True
    mock_cache.incr.return_value = 6  # over the limit of 5

    _reset_cache_for_testing(mock_cache)

    rl = RateLimiter()
    rl.enabled = True
    allowed, retry_after = rl.check_rate_limit("user:9", max_requests=5, window_seconds=60)

    assert not allowed
    assert retry_after >= 1

    _reset_cache_for_testing(None)


# ---------------------------------------------------------------------------
# 21. _reset_cache_for_testing helper
# ---------------------------------------------------------------------------


def test_reset_cache_for_testing_replaces_singleton():
    from app.core.cache import CacheClient, _reset_cache_for_testing, get_cache

    custom = CacheClient(redis_url=None)
    _reset_cache_for_testing(custom)
    assert get_cache() is custom
    _reset_cache_for_testing(None)
    # Next get_cache() call will rebuild from settings
    new_client = get_cache()
    assert new_client is not custom


# ---------------------------------------------------------------------------
# 22. require_shared_backend raises CacheUnavailableError on local
# ---------------------------------------------------------------------------


def test_require_shared_backend_raises_on_local():
    from app.core.cache import CacheClient, CacheUnavailableError

    client = CacheClient(redis_url=None)
    with pytest.raises(CacheUnavailableError):
        client.require_shared_backend()
