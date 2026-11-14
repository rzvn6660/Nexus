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
        fail_closed: bool | None = None,
    ) -> Tuple[bool, int]:
        """Return ``(is_allowed, retry_after_seconds)``.

        Raises ``HTTP 503`` if ``REDIS_FAIL_CLOSED=True`` and the shared backend
        is unavailable or encounters an error.
        """
        if not self.enabled:
            return True, 0

        from app.core.cache import get_cache
        from app.core.config import settings

        if fail_closed is None:
            fail_closed = (
                getattr(settings, "REDIS_FAIL_CLOSED", False)
                or getattr(settings, "APP_ENV", "").lower() == "production"
            )

        cache = get_cache()

        if cache.is_shared_backend:
            return self._check_redis(
                cache, key, max_requests, window_seconds, fail_closed=fail_closed
            )

        # Shared backend is unavailable (startup outage, cooldown, offline)
        if fail_closed:
            logger.error(
                "Rate limiter: shared Redis backend unavailable and fail_closed=True — "
                "denying request for key prefix '%s'.",
                key[:32],  # truncate to avoid logging full identifiers
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiting service unavailable. Please retry shortly.",
            )

        # Graceful local fallback (development / testing only)
        logger.debug("Rate limiter: using local fallback for key prefix '%s'.", key[:32])
        return self._check_local(key, max_requests, window_seconds)

    def _check_redis(
        self,
        cache,
        key: str,
        max_requests: int,
        window_seconds: int,
        fail_closed: bool = False,
    ) -> Tuple[bool, int]:
        """Fixed-window counter via Redis Lua atomic INCR + EXPIRE."""
        now = int(time.time())
        bucket = now // window_seconds  # fixed window bucket
        redis_key = f"{_KEY_PREFIX}{key}:{bucket}"
        ttl = window_seconds + 1  # +1 for clock skew

        try:
            if hasattr(cache, "incr_with_ttl"):
                count = cache.incr_with_ttl(redis_key, ttl)
            else:
                count = cache.incr(redis_key)
                if count == 1:
                    # First hit in this window — set TTL fallback
                    cache.expire(redis_key, ttl)

            if count > max_requests:
                # Time until next bucket
                next_bucket_at = (bucket + 1) * window_seconds
                retry_after = max(1, next_bucket_at - now)
                return False, retry_after

            return True, 0

        except Exception as exc:
            logger.warning(
                "Rate limiter: Redis error (%s) for key prefix '%s'.",
                type(exc).__name__,
                key[:32],
            )
            from app.core.config import settings

            effective_fail_closed = (
                fail_closed
                or getattr(settings, "REDIS_FAIL_CLOSED", False)
                or getattr(settings, "APP_ENV", "").lower() == "production"
            )
            if effective_fail_closed:
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

    def record_attempt(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
        fail_closed: bool | None = None,
    ) -> None:
        """Enforce rate limit; raise HTTP 429 if threshold exceeded."""
        allowed, retry_after = self.check_rate_limit(
            key, max_requests, window_seconds, fail_closed=fail_closed
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Please try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    def reset(self, key: str | None = None, window_seconds: int | None = None) -> None:
        """Clear local records and active Redis rate-limit buckets for a key (or all).

        Affects the active backend (local memory and/or Redis).
        """
        with self._local_lock:
            if key is None:
                self._local_records.clear()
            else:
                self._local_records.pop(key, None)

        if key is not None:
            self.reset_redis_key(key, window_seconds=window_seconds)

    def reset_redis_key(self, key: str, window_seconds: int | None = None) -> None:
        """Delete active Redis rate-limit bucket(s) for a key.

        Useful after a successful login to clear brute-force counters.
        If ``window_seconds`` is omitted, cleans current buckets across common
        rate-limiting windows (60s, 300s, 900s, 3600s).
        """
        from app.core.cache import get_cache

        cache = get_cache()
        if not cache.is_shared_backend:
            return

        now = int(time.time())
        buckets_to_delete: list[str] = []
        if window_seconds is not None:
            bucket = now // window_seconds
            buckets_to_delete.append(f"{_KEY_PREFIX}{key}:{bucket}")
        else:
            for w in (60, 300, 900, 3600):
                bucket = now // w
                buckets_to_delete.append(f"{_KEY_PREFIX}{key}:{bucket}")

        for rk in buckets_to_delete:
            try:
                cache.delete(rk)
            except Exception as exc:
                logger.warning("Rate limiter: failed to delete Redis key (%s).", type(exc).__name__)

    def clear_all(self) -> None:
        """Clear all local records — for testing only."""
        with self._local_lock:
            self._local_records.clear()


# ---------------------------------------------------------------------------
# Application singleton
# ---------------------------------------------------------------------------

auth_rate_limiter = RateLimiter()


# In-memory DNS cache for hostname resolution in is_trusted_proxy.
# Uses a short 5-second TTL so that dynamic Docker IP changes are detected
# rapidly without incurring DNS lookup latency on every HTTP request.
_RESOLVED_HOST_CACHE: dict[str, tuple[float, set]] = {}
_DNS_CACHE_TTL_SECONDS: float = 5.0


def clear_proxy_dns_cache() -> None:
    """Clear cached proxy DNS resolutions — for testing and dynamic topology shifts."""
    _RESOLVED_HOST_CACHE.clear()


def is_trusted_proxy(ip_str: str, trusted_list: list[str]) -> bool:
    """Check if an IP string matches any trusted proxy IP, CIDR network, or resolvable proxy hostname.

    Security Invariant:
    - Only exact IPs, CIDR blocks, or explicitly resolved proxy hostnames (e.g. 'frontend') are trusted.
    - Subnets are never automatically trusted unless explicitly configured.
    - Hostnames are resolved dynamically with a 5-second TTL to handle Docker IP changes safely.
    """
    import ipaddress
    import socket
    import time

    try:
        ip = ipaddress.ip_address(ip_str)
        now = time.monotonic()
        for trusted in trusted_list:
            t = trusted.strip()
            if not t:
                continue
            try:
                if "/" in t:
                    if ip in ipaddress.ip_network(t, strict=False):
                        return True
                else:
                    if ip == ipaddress.ip_address(t):
                        return True
            except ValueError:
                # Not a literal IP/CIDR — try resolving hostname (e.g. 'frontend', 'localhost')
                cached_time, cached_ips = _RESOLVED_HOST_CACHE.get(t, (0.0, set()))
                if now - cached_time < _DNS_CACHE_TTL_SECONDS:
                    resolved_ips = cached_ips
                else:
                    resolved_ips = set()
                    try:
                        resolved_addrs = socket.getaddrinfo(t, None, proto=socket.IPPROTO_TCP)
                        for _, _, _, _, sockaddr in resolved_addrs:
                            try:
                                resolved_ips.add(ipaddress.ip_address(sockaddr[0]))
                            except ValueError:
                                continue
                    except (socket.gaierror, OSError):
                        pass
                    _RESOLVED_HOST_CACHE[t] = (now, resolved_ips)

                if ip in resolved_ips:
                    return True
    except ValueError:
        return False
    return False


def get_client_ip(request: Request) -> str:
    """
    Extract verified client IP from trusted reverse proxy headers or socket address.

    Security Contract:
    1. Obtains direct peer socket address from request.client.host.
    2. If request.client.host is NOT in TRUSTED_PROXIES, forwarded headers (X-Real-IP,
       X-Forwarded-For) are completely IGNORED to prevent client header spoofing.
    3. If request.client.host IS a trusted proxy:
       a. Evaluates X-Forwarded-For right-to-left, traversing the trusted proxy chain
          and returning the first untrusted upstream client IP.
       b. If X-Forwarded-For is absent, falls back to X-Real-IP if valid syntax.
    4. Validates IP syntax via ipaddress.ip_address on all candidates to prevent key injection.
    5. Safely defaults to socket host or '127.0.0.1'.
    """
    import ipaddress

    from app.core.config import settings

    # Resolve direct socket peer
    peer_ip = "127.0.0.1"
    if request.client and request.client.host:
        raw_peer = request.client.host.strip()
        try:
            ipaddress.ip_address(raw_peer)
            peer_ip = raw_peer
        except ValueError:
            logger.warning("SECURITY: Malformed peer socket address: %s", raw_peer)
            return "127.0.0.1"

    # Get configured trusted proxies
    trusted_proxies = getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1"])
    if isinstance(trusted_proxies, str):
        trusted_proxies = [p.strip() for p in trusted_proxies.split(",") if p.strip()]

    # If direct connection did not arrive from a trusted proxy, DO NOT trust forwarded headers!
    if not is_trusted_proxy(peer_ip, trusted_proxies):
        return peer_ip

    # Peer is a trusted proxy -> inspect forwarded headers
    # X-Forwarded-For takes precedence for multi-hop proxy chains
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        # Traverse right-to-left (from closest proxy to origin client)
        for candidate in reversed(parts):
            try:
                ipaddress.ip_address(candidate)
                # If this hop is also a trusted proxy, keep walking back
                if is_trusted_proxy(candidate, trusted_proxies):
                    continue
                # Found the first non-trusted IP in the chain — this is the client IP
                return candidate
            except ValueError:
                continue
        # If all hops were trusted proxies, return the leftmost valid one
        if parts:
            try:
                ipaddress.ip_address(parts[0])
                return parts[0]
            except ValueError:
                pass

    # X-Real-IP fallback (single reverse proxy hop)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        candidate = real_ip.strip()
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            logger.warning("SECURITY: Malformed X-Real-IP header rejected: %s", candidate)

    return peer_ip
