"""Shared cache abstraction for NEXUS production hardening.

Provides a Redis-backed cache client with an automatic in-process fallback for
local development or when Redis is unavailable.

SECURITY CONTRACT:
- Security-sensitive paths (JWT revocation, rate limiting) use ``fail_closed=True``.
  When ``fail_closed=True`` and the shared backend is unreachable, the operation
  raises ``CacheUnavailableError`` so callers can deny the request rather than
  silently degrade.
- Non-sensitive paths may use ``fail_closed=False`` to gracefully degrade.
- Tokens, JWTs, and secrets MUST NOT be logged.  This module never logs values.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Utility: Credential Redaction
# ---------------------------------------------------------------------------


def redact_redis_url(url: Optional[str]) -> str:
    """Return Redis URL with passwords and sensitive credentials safely redacted.

    Safely preserves IPv6 bracket notation, Unix domain socket paths, TLS URLs,
    and query parameters while stripping all plaintext passwords.
    """
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
        if "@" in parsed.netloc:
            userinfo, hostport = parsed.netloc.rsplit("@", 1)
            if ":" in userinfo:
                user, _ = userinfo.split(":", 1)
                redacted_userinfo = f"{user}:<redacted>"
            else:
                redacted_userinfo = "<redacted>"
            redacted_netloc = f"{redacted_userinfo}@{hostport}"
            return urlunsplit((parsed.scheme, redacted_netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        pass
    return re.sub(r"://([^:]*):([^@]+)@", r"://\1:<redacted>@", url)

# ---------------------------------------------------------------------------
# Sentinel exception
# ---------------------------------------------------------------------------


class CacheUnavailableError(RuntimeError):
    """Raised when the shared cache backend is required but unavailable."""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class CacheBackend:
    """Minimal key/value + TTL interface used by rate-limiter and token-store."""

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise NotImplementedError

    def get(self, key: str) -> Optional[str]:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def incr(self, key: str) -> int:
        """Atomically increment and return the new value. Key is created at 0 if absent."""
        raise NotImplementedError

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        """Atomically increment and ensure TTL is set. Returns new value."""
        raise NotImplementedError

    def expire(self, key: str, ttl_seconds: int) -> None:
        """Set / refresh TTL on an existing key."""
        raise NotImplementedError

    @property
    def is_available(self) -> bool:  # noqa: D401
        """True if the backend is reachable."""
        raise NotImplementedError

    def close(self) -> None:
        """Close backend connections and release resources."""
        pass


# ---------------------------------------------------------------------------
# In-process fallback (single-worker, non-persistent)
# ---------------------------------------------------------------------------


class _LocalCacheBackend(CacheBackend):
    """Thread-safe in-memory cache backend — for development / testing only."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}  # key -> (value, expires_at)
        self._lock = threading.Lock()

    def _is_expired(self, expires_at: float) -> bool:
        return expires_at > 0 and time.monotonic() > expires_at

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds > 0 else 0.0
        with self._lock:
            self._store[key] = (value, expires_at)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._is_expired(expires_at):
                del self._store[key]
                return None
            return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def incr(self, key: str) -> int:
        with self._lock:
            entry = self._store.get(key)
            if entry is None or self._is_expired(entry[1]):
                # Create fresh; caller must call expire() if a TTL is needed
                new_val = 1
                self._store[key] = (str(new_val), 0.0)
            else:
                new_val = int(entry[0]) + 1
                self._store[key] = (str(new_val), entry[1])
            return new_val

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        with self._lock:
            entry = self._store.get(key)
            if entry is None or self._is_expired(entry[1]):
                new_val = 1
                self._store[key] = (
                    str(new_val),
                    time.monotonic() + ttl_seconds if ttl_seconds > 0 else 0.0,
                )
            else:
                new_val = int(entry[0]) + 1
                exp = entry[1]
                if exp <= 0.0 or self._is_expired(exp):
                    exp = time.monotonic() + ttl_seconds if ttl_seconds > 0 else 0.0
                self._store[key] = (str(new_val), exp)
            return new_val

    def expire(self, key: str, ttl_seconds: int) -> None:
        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                self._store[key] = (entry[0], time.monotonic() + ttl_seconds)

    def clear_all(self) -> None:
        """Test helper — wipe entire store."""
        with self._lock:
            self._store.clear()

    @property
    def is_available(self) -> bool:
        return True

    def close(self) -> None:
        self.clear_all()


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


class _RedisCacheBackend(CacheBackend):
    """Redis-backed cache backend using redis-py.

    Configures bounded socket timeouts (2.0s) and clean client/pool disposal.
    Any RedisError from core operations is propagated so callers decide how to
    handle failure (fail-closed vs. fallback).
    """

    def __init__(
        self,
        url: str,
        socket_connect_timeout: float = 2.0,
        socket_timeout: float = 2.0,
    ) -> None:
        import redis  # imported lazily so missing package doesn't break startup

        self._url = url
        self._socket_connect_timeout = socket_connect_timeout
        self._socket_timeout = socket_timeout
        self._client: redis.Redis = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=socket_connect_timeout,
            socket_timeout=socket_timeout,
            retry_on_timeout=False,
        )

    def ping(self) -> bool:
        """Probe Redis server reachability."""
        return bool(self._client.ping())

    @property
    def is_available(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    def close(self) -> None:
        """Close connection pool cleanly."""
        try:
            if hasattr(self, "_client") and self._client is not None:
                self._client.close()
                pool = getattr(self._client, "connection_pool", None)
                if pool is not None and hasattr(pool, "disconnect"):
                    pool.disconnect()
        except Exception as exc:
            logger.warning("Cache: Error closing Redis backend: %s", type(exc).__name__)

    # ------------------------------------------------------------------
    # Core operations — errors propagate to caller / CacheClient
    # ------------------------------------------------------------------

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._client.set(key, value, ex=ttl_seconds)

    def get(self, key: str) -> Optional[str]:
        return self._client.get(key)  # type: ignore[return-value]

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._client.exists(key))

    _INCR_WITH_TTL_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 or redis.call('TTL', KEYS[1]) < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

    def incr(self, key: str) -> int:
        return int(self._client.incr(key))

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        return int(self._client.eval(self._INCR_WITH_TTL_SCRIPT, 1, key, ttl_seconds))

    def expire(self, key: str, ttl_seconds: int) -> None:
        self._client.expire(key, ttl_seconds)


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------


class CacheClient:
    """Primary cache client used application-wide.

    Features:
    - Automatically attempts to connect to Redis when ``REDIS_URL`` is configured.
    - Avoids permanent local-backend latch: periodically probes Redis with exponential
      backoff and auto-recovers when Redis becomes available.
    - Bounded timeouts and cooldowns prevent retry storms and worker thread exhaustion.
    - Clean shutdown via ``close()`` disposing connection pools.
    - Explicit local fallback mode for development and testing.
    - Observable status without leaking sensitive credentials.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        *,
        min_cooldown: float = 1.0,
        max_cooldown: float = 10.0,
    ) -> None:
        self._redis_url = redis_url
        self._local_backend = _LocalCacheBackend()
        self._redis_backend: Optional[_RedisCacheBackend] = None

        self._min_cooldown = min_cooldown
        self._max_cooldown = max_cooldown
        self._cooldown_seconds = min_cooldown
        self._last_probe_time: float = 0.0
        self._failure_count: int = 0
        self._is_closed: bool = False
        self._lock = threading.RLock()

        if redis_url:
            try:
                self._redis_backend = _RedisCacheBackend(redis_url)
                if self._check_redis(force=True):
                    logger.info("Cache: Redis backend connected (%s)", redact_redis_url(redis_url))
                else:
                    logger.warning(
                        "Cache: Redis configured (%s) but unreachable at startup — using local fallback. "
                        "Reconnection will be attempted automatically in the background.",
                        redact_redis_url(redis_url),
                    )
            except Exception as exc:
                self._record_failure(exc)
                logger.warning(
                    "Cache: Redis init failed (%s) — using local fallback (will retry).",
                    type(exc).__name__,
                )
        else:
            logger.info(
                "Cache: No REDIS_URL configured — using LOCAL in-process fallback. "
                "Set REDIS_URL for production multi-worker deployments."
            )

    @staticmethod
    def _redact(url: str) -> str:
        """Return URL with password redacted for logging."""
        return redact_redis_url(url)

    def _record_failure(self, exc: Optional[Exception] = None) -> None:
        """Record connection failure and advance backoff cooldown to prevent retry storms."""
        with self._lock:
            self._failure_count += 1
            self._cooldown_seconds = min(
                self._min_cooldown * (2 ** (self._failure_count - 1)),
                self._max_cooldown,
            )
            self._last_probe_time = time.monotonic()
            if self._failure_count == 1:
                logger.warning(
                    "Cache: Redis backend unreachable (%s) — activating local fallback (retry cooldown: %.1fs).",
                    type(exc).__name__ if exc else "ping failed",
                    self._cooldown_seconds,
                )
            else:
                logger.debug(
                    "Cache: Redis still unreachable (failure count: %d, retry cooldown: %.1fs).",
                    self._failure_count,
                    self._cooldown_seconds,
                )

    def _check_redis(self, force: bool = False) -> bool:
        """Check if Redis is reachable, respecting exponential backoff to avoid retry storms."""
        if not self._redis_backend or self._is_closed:
            return False

        now = time.monotonic()
        with self._lock:
            # If healthy and not forced, return immediately
            if self._failure_count == 0 and not force:
                return True

            # If under cooldown, return False immediately without blocking
            if not force and (now - self._last_probe_time) < self._cooldown_seconds:
                return False

            self._last_probe_time = now
            try:
                if self._redis_backend.ping():
                    if self._failure_count > 0:
                        logger.info(
                            "Cache: Redis backend connection restored (%s).",
                            redact_redis_url(self._redis_url),
                        )
                    self._failure_count = 0
                    self._cooldown_seconds = self._min_cooldown
                    return True
                else:
                    self._record_failure()
                    return False
            except Exception as exc:
                self._record_failure(exc)
                return False

    @property
    def is_shared_backend(self) -> bool:
        """True if a real shared backend (Redis) is active and reachable."""
        if not self._redis_backend or self._is_closed:
            return False
        return self._check_redis()

    def probe_shared_backend(self) -> bool:
        """Actively probe Redis reachability if configured and not in cooldown.

        Returns True if shared Redis backend is healthy and reachable.
        If under cooldown, returns False immediately without blocking or generating log noise.
        """
        if not self._redis_backend or self._is_closed:
            return False
        now = time.monotonic()
        with self._lock:
            if self._failure_count > 0 and (now - self._last_probe_time) < self._cooldown_seconds:
                return False
            if self._failure_count == 0 and (now - self._last_probe_time) < 1.0:
                return True
        return self._check_redis(force=True)

    @property
    def backend_mode(self) -> str:
        """Return 'redis' if Redis is configured, otherwise 'local'."""
        return "redis" if self._redis_url else "local"

    @property
    def is_available(self) -> bool:
        """True if the active backend is reachable."""
        if self._redis_url and not self._is_closed:
            return self.is_shared_backend
        return self._local_backend.is_available

    def get_status(self) -> dict[str, Any]:
        """Return observable backend status with all credentials safely redacted."""
        return {
            "backend_mode": self.backend_mode,
            "is_shared_backend": self.is_shared_backend,
            "is_available": self.is_available,
            "redis_url_configured": bool(self._redis_url),
            "redis_url": redact_redis_url(self._redis_url) if self._redis_url else None,
            "consecutive_failures": self._failure_count,
            "cooldown_seconds": self._cooldown_seconds if self._failure_count > 0 else 0.0,
            "is_closed": self._is_closed,
        }

    def require_shared_backend(self) -> None:
        """Raise ``CacheUnavailableError`` if only a local backend is available.

        Use this before security-critical operations when ``fail_closed=True``.
        """
        if not self.is_shared_backend:
            raise CacheUnavailableError(
                "Security-critical operation requires a shared cache backend (Redis). "
                "Configure REDIS_URL or deploy a Redis instance."
            )

    @property
    def raw_backend(self) -> CacheBackend:
        """Access the underlying active backend (e.g. for test helpers)."""
        if self.is_shared_backend and self._redis_backend is not None:
            return self._redis_backend
        return self._local_backend

    # ------------------------------------------------------------------
    # Delegate all cache operations to the active backend
    # ------------------------------------------------------------------

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        if self.is_shared_backend and self._redis_backend is not None:
            try:
                return self._redis_backend.set(key, value, ttl_seconds)
            except Exception as exc:
                self._record_failure(exc)
                raise
        return self._local_backend.set(key, value, ttl_seconds)

    def get(self, key: str) -> Optional[str]:
        if self.is_shared_backend and self._redis_backend is not None:
            try:
                return self._redis_backend.get(key)
            except Exception as exc:
                self._record_failure(exc)
                raise
        return self._local_backend.get(key)

    def delete(self, key: str) -> None:
        if self.is_shared_backend and self._redis_backend is not None:
            try:
                return self._redis_backend.delete(key)
            except Exception as exc:
                self._record_failure(exc)
                raise
        return self._local_backend.delete(key)

    def exists(self, key: str) -> bool:
        if self.is_shared_backend and self._redis_backend is not None:
            try:
                return self._redis_backend.exists(key)
            except Exception as exc:
                self._record_failure(exc)
                raise
        return self._local_backend.exists(key)

    def incr(self, key: str) -> int:
        if self.is_shared_backend and self._redis_backend is not None:
            try:
                return self._redis_backend.incr(key)
            except Exception as exc:
                self._record_failure(exc)
                raise
        return self._local_backend.incr(key)

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        if self.is_shared_backend and self._redis_backend is not None:
            try:
                return self._redis_backend.incr_with_ttl(key, ttl_seconds)
            except Exception as exc:
                self._record_failure(exc)
                raise
        return self._local_backend.incr_with_ttl(key, ttl_seconds)

    def expire(self, key: str, ttl_seconds: int) -> None:
        if self.is_shared_backend and self._redis_backend is not None:
            try:
                return self._redis_backend.expire(key, ttl_seconds)
            except Exception as exc:
                self._record_failure(exc)
                raise
        return self._local_backend.expire(key, ttl_seconds)

    def close(self) -> None:
        """Cleanly close connection pools and release resources."""
        with self._lock:
            self._is_closed = True
            if self._redis_backend is not None:
                self._redis_backend.close()
                self._redis_backend = None
            self._local_backend.close()


# ---------------------------------------------------------------------------
# Application singleton — initialised lazily from settings
# ---------------------------------------------------------------------------

_cache_client: Optional[CacheClient] = None
_cache_lock = threading.Lock()


def get_cache() -> CacheClient:
    """Return the application-wide ``CacheClient`` singleton.

    On first call, reads ``settings.REDIS_URL`` and constructs the client.
    Safe to call from multiple threads.
    """
    global _cache_client
    if _cache_client is None:
        with _cache_lock:
            if _cache_client is None:
                from app.core.config import settings  # avoid circular import at module level

                _cache_client = CacheClient(redis_url=getattr(settings, "REDIS_URL", None))
    return _cache_client


def _reset_cache_for_testing(client: Optional[CacheClient] = None) -> None:
    """Replace the singleton for unit tests.  NOT for production use."""
    global _cache_client
    _cache_client = client


def close_cache() -> None:
    """Cleanly close and reset the application-wide CacheClient singleton."""
    global _cache_client
    with _cache_lock:
        if _cache_client is not None:
            _cache_client.close()
            _cache_client = None


def check_redis_health() -> dict[str, Any]:
    """Check Redis health for health checks and readiness probes.

    Distinguishes:
    - 'connected': Redis is reachable and shared state is operational.
    - 'reconnecting': Redis was configured but is currently failing and in backoff cooldown.
    - 'unavailable': Redis is required but unreachable / failed.
    - 'optional': Redis is unconfigured in development/testing (using local fallback).

    SECURITY: Never returns Redis URLs, credentials, hostnames, or raw exception strings.
    """
    from app.core.config import settings

    client = get_cache()
    is_prod = (
        getattr(settings, "is_production", False)
        or getattr(settings, "APP_ENV", "").lower() == "production"
    )
    is_required = bool(
        getattr(settings, "REDIS_REQUIRED", False)
        or (is_prod and getattr(settings, "REDIS_FAIL_CLOSED", False))
    )

    is_shared = False
    try:
        if hasattr(client, "probe_shared_backend"):
            is_shared = bool(client.probe_shared_backend())
        else:
            is_shared = bool(client.is_shared_backend)
    except Exception:
        is_shared = False

    if is_shared:
        return {
            "status": "connected",
            "shared_state_available": True,
            "mode": "redis",
            "required": is_required,
        }

    redis_url = getattr(client, "_redis_url", None)
    if not redis_url:
        return {
            "status": "unavailable" if is_required else "optional",
            "shared_state_available": False,
            "mode": "local",
            "required": is_required,
        }

    failure_count = getattr(client, "_failure_count", 0)
    if failure_count > 0:
        return {
            "status": "reconnecting",
            "shared_state_available": False,
            "mode": "local",
            "required": is_required,
        }

    return {
        "status": "unavailable",
        "shared_state_available": False,
        "mode": "local",
        "required": is_required,
    }
