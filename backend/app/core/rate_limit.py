"""In-memory rate limiter for authentication abuse defense (brute-force, spraying, signup abuse).

Provides a lightweight, thread-safe sliding-window rate limiter for production authentication endpoints.
Can be configured or cleared easily in unit tests.
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Dict, List, Tuple
from fastapi import HTTPException, Request, status


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter for abuse defense."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: Dict[str, List[float]] = defaultdict(list)
        self.enabled: bool = True

    def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> Tuple[bool, int]:
        """Check if request is permitted under sliding window.

        Returns:
            (is_allowed, retry_after_seconds)
        """
        if not self.enabled:
            return True, 0

        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            timestamps = self._records[key]
            valid = [t for t in timestamps if t > cutoff]
            self._records[key] = valid

            if len(valid) >= max_requests:
                oldest = valid[0]
                retry_after = max(1, int(oldest + window_seconds - now))
                return False, retry_after

            valid.append(now)
            return True, 0

    def record_attempt(self, key: str, max_requests: int, window_seconds: int) -> None:
        """Enforce rate limit, raising HTTP 429 if threshold exceeded."""
        allowed, retry_after = self.check_rate_limit(key, max_requests, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Please try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    def reset(self, key: str | None = None) -> None:
        """Clear record for a key (e.g. on successful login), or clear all if key is None."""
        with self._lock:
            if key is None:
                self._records.clear()
            else:
                self._records.pop(key, None)

    def clear_all(self) -> None:
        """Clear all records (primarily for testing)."""
        with self._lock:
            self._records.clear()


auth_rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from headers or client host."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"
