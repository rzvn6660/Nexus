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
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

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

    def expire(self, key: str, ttl_seconds: int) -> None:
        """Set / refresh TTL on an existing key."""
        raise NotImplementedError

    @property
    def is_available(self) -> bool:  # noqa: D401
        """True if the backend is reachable."""
        raise NotImplementedError


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


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


class _RedisCacheBackend(CacheBackend):
    """Redis-backed cache backend using redis-py.

    Lazy-initialises the connection pool on first use and probes availability
    with a ``PING``.  Any ``RedisError`` is re-raised as-is so callers decide
    how to handle failure (fail-closed vs. fallback).
    """

    def __init__(self, url: str) -> None:
        import redis  # imported lazily so missing package doesn't break startup

        self._client: redis.Redis = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self._url = url
        self._available: Optional[bool] = None  # cache probe result briefly

    # ------------------------------------------------------------------
    # Availability probe
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        try:
            self._client.ping()
            self._available = True
            return True
        except Exception:
            self._available = False
            return False

    # ------------------------------------------------------------------
    # Core operations — all errors propagate to the caller
    # ------------------------------------------------------------------

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._client.set(key, value, ex=ttl_seconds)

    def get(self, key: str) -> Optional[str]:
        return self._client.get(key)  # type: ignore[return-value]

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._client.exists(key))

    def incr(self, key: str) -> int:
        return int(self._client.incr(key))

    def expire(self, key: str, ttl_seconds: int) -> None:
        self._client.expire(key, ttl_seconds)


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------


class CacheClient:
    """Primary cache client used application-wide.

    * Tries to connect to Redis if ``REDIS_URL`` is configured.
    * Falls back to an in-process ``_LocalCacheBackend`` when Redis is absent
      or unreachable — emitting a startup warning.
    * Callers that need fail-closed semantics should check
      ``client.is_shared_backend`` before performing security-critical reads.
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._redis_url = redis_url
        self._backend: CacheBackend
        self._is_shared = False

        if redis_url:
            try:
                redis_backend = _RedisCacheBackend(redis_url)
                if redis_backend.is_available:
                    self._backend = redis_backend
                    self._is_shared = True
                    logger.info("Cache: Redis backend connected (%s)", self._redact(redis_url))
                else:
                    logger.warning(
                        "Cache: Redis configured but unreachable — using LOCAL fallback. "
                        "Multi-worker rate limiting and token revocation will NOT be shared."
                    )
                    self._backend = _LocalCacheBackend()
            except Exception as exc:
                logger.warning(
                    "Cache: Redis init failed (%s) — using LOCAL fallback.",
                    type(exc).__name__,
                )
                self._backend = _LocalCacheBackend()
        else:
            logger.info(
                "Cache: No REDIS_URL configured — using LOCAL in-process fallback. "
                "Set REDIS_URL for production multi-worker deployments."
            )
            self._backend = _LocalCacheBackend()

    @staticmethod
    def _redact(url: str) -> str:
        """Return URL with password redacted for logging."""
        import re
        return re.sub(r"://[^:]+:[^@]+@", "://<redacted>@", url)

    @property
    def is_shared_backend(self) -> bool:
        """True if a real shared backend (Redis) is active."""
        return self._is_shared

    def require_shared_backend(self) -> None:
        """Raise ``CacheUnavailableError`` if only a local backend is available.

        Use this before security-critical operations when ``fail_closed=True``.
        """
        if not self._is_shared:
            raise CacheUnavailableError(
                "Security-critical operation requires a shared cache backend (Redis). "
                "Configure REDIS_URL or deploy a Redis instance."
            )

    # ------------------------------------------------------------------
    # Delegate all cache operations to the active backend
    # ------------------------------------------------------------------

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._backend.set(key, value, ttl_seconds)

    def get(self, key: str) -> Optional[str]:
        return self._backend.get(key)

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    def exists(self, key: str) -> bool:
        return self._backend.exists(key)

    def incr(self, key: str) -> int:
        return self._backend.incr(key)

    def expire(self, key: str, ttl_seconds: int) -> None:
        self._backend.expire(key, ttl_seconds)

    @property
    def raw_backend(self) -> CacheBackend:
        """Access the underlying backend (e.g. for test helpers)."""
        return self._backend

    @property
    def is_available(self) -> bool:
        return self._backend.is_available


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
