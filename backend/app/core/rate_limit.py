"""Production-grade rate limiter for NEXUS — Phase 23.6 hardening.

Uses a shared Redis backend (via ``app.core.cache``) when available, so that
rate limits are enforced consistently across all worker processes in production.

Falls back to an in-process sliding-window implementation for local development
or when Redis is unavailable and ``REDIS_FAIL_CLOSED`` is ``False``.

SECURITY CONTRACT:
- ``REDIS_FAIL_CLOSED=True`` → raises HTTP 503 if shared backend is missing,
  preventing bypassing rate limits in multi-worker deployments.
- ``REDIS_FAIL_CLOSED=False`` (default for dev) → gracefully uses local fallback;
  emits a warning log so operators are aware of the degraded mode.
- Keys are prefixed with ``rl:`` and include the caller-supplied key string.
  No tokens, passwords, or PII are embedded in keys passed by callers.
"""

from __future__ import annotations

import time
from typing import Tuple

from fastapi import HTTPException, Request, status

from app.core.logging import get_logger

logger = get_logger(__name__)

_KEY_PREFIX = "rl:"


class RateLimiter:
    """Sliding-window rate limiter backed by Redis or a local fallback.

    Uses the *fixed-window with INCR+EXPIRE* pattern on Redis, which is atomic
    and avoids WATCH/MULTI complexity while remaining accurate for typical abuse
    scenarios.

    Algorithm (Redis path):
      1. INCR ``rl:<key>:<window_start_bucket>``
      2. If the key was just created (value == 1), set its TTL to ``window_seconds``.
      3. If count > max_requests, deny and return ``retry_after``.

    Algorithm (local fallback):
      Sliding-window list of timestamps protected by a threading.Lock — identical
      to the original ``InMemoryRateLimiter`` implementation.
    """

    def __init__(self) -> None:
        self.enabled: bool = True
        # Local fallback store (used when Redis is unavailable and not fail-closed)
        self._local_records: dict[str, list[float]] = {}
        import threading
        self._local_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, int]:
        """Return ``(is_allowed, retry_after_seconds)``.

        Raises ``HTTP 503`` if ``REDIS_FAIL_CLOSED=True`` and the shared backend
        is unavailable.
        """
        if not self.enabled:
            return True, 0

        from app.core.cache import CacheUnavailableError, get_cache
        from app.core.config import settings

        cache = get_cache()
        fail_closed: bool = getattr(settings, "REDIS_FAIL_CLOSED", False)

        if cache.is_shared_backend:
            return self._check_redis(cache, key, max_requests, window_seconds)

        # Shared backend is unavailable
        if fail_closed:
            logger.error(
                "Rate limiter: shared Redis backend unavailable and REDIS_FAIL_CLOSED=True — "
                "denying request for key prefix '%s'.",
                key[:32],  # truncate to avoid logging full identifiers
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiting service unavailable. Please retry shortly.",
            )

        # Graceful local fallback
        logger.debug("Rate limiter: using local fallback for key prefix '%s'.", key[:32])
        return self._check_local(key, max_requests, window_seconds)

    def _check_redis(
        self,
        cache,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, int]:
        """Fixed-window counter via Redis INCR + EXPIRE."""
        import redis as redis_lib

        now = int(time.time())
        bucket = now // window_seconds  # fixed window bucket
        redis_key = f"{_KEY_PREFIX}{key}:{bucket}"

        try:
            count = cache.incr(redis_key)
            if count == 1:
                # First hit in this window — set TTL
                cache.expire(redis_key, window_seconds + 1)  # +1 for clock skew

            if count > max_requests:
                # Time until next bucket
                next_bucket_at = (bucket + 1) * window_seconds
                retry_after = max(1, next_bucket_at - now)
                return False, retry_after

            return True, 0

        except redis_lib.RedisError as exc:
            logger.warning("Rate limiter: Redis error (%s), falling back to local.", type(exc).__name__)
            # Runtime degradation — fall through to local
            from app.core.config import settings
            if getattr(settings, "REDIS_FAIL_CLOSED", False):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Rate limiting service unavailable. Please retry shortly.",
                ) from exc
            return self._check_local(key, max_requests, window_seconds)

    def _check_local(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, int]:
        """Sliding-window via in-process list (original implementation)."""
        from collections import defaultdict

        now = time.time()
        cutoff = now - window_seconds
        with self._local_lock:
            if key not in self._local_records:
                self._local_records[key] = []
            timestamps = self._local_records[key]
            valid = [t for t in timestamps if t > cutoff]
            self._local_records[key] = valid

            if len(valid) >= max_requests:
                oldest = valid[0]
                retry_after = max(1, int(oldest + window_seconds - now))
                return False, retry_after

            valid.append(now)
            return True, 0

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def record_attempt(self, key: str, max_requests: int, window_seconds: int) -> None:
        """Enforce rate limit; raise HTTP 429 if threshold exceeded."""
        allowed, retry_after = self.check_rate_limit(key, max_requests, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Please try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    def reset(self, key: str | None = None) -> None:
        """Clear local records for a key (or all) — e.g. on successful login.

        Note: This only affects the local fallback store.  Redis TTLs expire
        naturally; use ``reset_redis_key`` for explicit Redis eviction.
        """
        with self._local_lock:
            if key is None:
                self._local_records.clear()
            else:
                self._local_records.pop(key, None)

    def reset_redis_key(self, key: str, window_seconds: int | None = None) -> None:
        """Delete the active Redis rate-limit bucket for a key.

        Useful after a successful login to clear brute-force counters.
        ``window_seconds`` is used to compute the current bucket; if omitted,
        no deletion is attempted on Redis.
        """
        from app.core.cache import get_cache

        cache = get_cache()
        if cache.is_shared_backend and window_seconds is not None:
            bucket = int(time.time()) // window_seconds
            redis_key = f"{_KEY_PREFIX}{key}:{bucket}"
            try:
                cache.delete(redis_key)
            except Exception as exc:
                logger.warning("Rate limiter: failed to delete Redis key: %s", type(exc).__name__)

    def clear_all(self) -> None:
        """Clear all local records — for testing only."""
        with self._local_lock:
            self._local_records.clear()


# ---------------------------------------------------------------------------
# Application singleton
# ---------------------------------------------------------------------------

auth_rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from headers or client host."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"
