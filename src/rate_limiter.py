"""
Production-capable rate limiter with Redis backend and in-memory fallback.

Usage:
    store = RateLimitStore()  # auto-detects Redis from REDIS_URL env var
    retry = store.status(key, limit, window)
    if retry:
        return 429, retry
    store.remember(key)
"""
import os
import time
import logging
import json
from datetime import datetime, timedelta, timezone
from threading import Lock

logger = logging.getLogger(__name__)


class _InMemoryBackend:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self):
        self._store: dict[str, list[float]] = {}
        self._lock = Lock()

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> int | None:
        """Return seconds until retry, or None if allowed."""
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            events = self._store.get(key, [])
            events = [t for t in events if t > cutoff]
            self._store[key] = events
            if len(events) < limit:
                return None
            retry_at = min(events) + window_seconds
            return max(1, int(retry_at - now))

    def record(self, key: str):
        with self._lock:
            self._store.setdefault(key, []).append(time.time())

    def prune(self, window_seconds: int):
        cutoff = time.time() - window_seconds
        with self._lock:
            for k in list(self._store):
                self._store[k] = [t for t in self._store[k] if t > cutoff]
                if not self._store[k]:
                    del self._store[k]


class _RedisBackend:
    """Redis-backed sliding window rate limiter using sorted sets."""

    def __init__(self, redis_client):
        self._r = redis_client

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = time.time()
        cutoff = now - window_seconds
        pipe = self._r.pipeline()
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        _, count, _ = pipe.execute()
        if count < limit:
            return None
        oldest = self._r.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_at = oldest[0][1] + window_seconds
            return max(1, int(retry_at - now))
        return window_seconds

    def record(self, key: str):
        now = time.time()
        self._r.zadd(key, {f"{now}": now})
        self._r.expire(key, 7200)

    def prune(self, window_seconds: int):
        cutoff = time.time() - window_seconds
        for k in self._r.scan_iter(match="ratelimit:*"):
            self._r.zremrangebyscore(k, 0, cutoff)


class RateLimitStore:
    """Unified rate limiter that uses Redis when available, else in-memory."""

    def __init__(self):
        redis_url = os.getenv("REDIS_URL", "").strip()
        self._backend = None
        self._backend_name = "memory"
        if redis_url:
            try:
                import redis
                client = redis.from_url(redis_url, decode_responses=True, socket_timeout=3)
                client.ping()
                self._backend = _RedisBackend(client)
                self._backend_name = "redis"
                logger.info("Rate limiter: using Redis backend (%s)", redis_url.split("@")[-1])
            except Exception as exc:
                logger.warning(
                    "Redis rate limiter unavailable (%s). Falling back to in-memory. "
                    "Rate limits will NOT persist across restarts or multiple processes.",
                    exc,
                )
                self._backend = _InMemoryBackend()
                self._backend_name = "memory-fallback"
        else:
            self._backend = _InMemoryBackend()
            self._backend_name = "memory"
            if os.getenv("APP_ENV", "").strip().lower() == "production":
                logger.warning(
                    "REDIS_URL is not set. Using in-memory rate limiting which does NOT "
                    "work across multiple processes. Set REDIS_URL for production."
                )
            else:
                logger.info("Rate limiter: using in-memory backend (development)")

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def status(self, key: str, limit: int, window: timedelta) -> int | None:
        """Return seconds until retry, or None if request is allowed."""
        window_seconds = int(window.total_seconds())
        return self._backend.is_allowed(f"ratelimit:{key}", limit, window_seconds)

    def remember(self, key: str):
        """Record a timestamped event for the given key."""
        self._backend.record(f"ratelimit:{key}")

    def prune_all(self, window: timedelta):
        """Remove expired events across all keys."""
        self._backend.prune(int(window.total_seconds()))
