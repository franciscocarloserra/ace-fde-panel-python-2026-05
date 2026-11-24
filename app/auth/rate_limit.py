"""Fixed-window, per-API-key rate limiting backed by Redis.

One counter per key per minute: `rl:{key_id}:{epoch_minute}`. INCR + EXPIRE
in a pipeline, so every process/replica shares the same count.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import redis

from app.config import REDIS_URL

DEFAULT_LIMIT = 100
WINDOW_SECONDS = 60

log = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL)
    return _client


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset: int  # unix timestamp when the current window ends

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset),
        }


def hit(
    r: redis.Redis, key_id: int, limit: int, now: float | None = None
) -> RateLimitResult:
    now = time.time() if now is None else now
    window = int(now) // WINDOW_SECONDS
    reset = (window + 1) * WINDOW_SECONDS
    try:
        pipe = r.pipeline()
        pipe.incr(f"rl:{key_id}:{window}")
        pipe.expire(f"rl:{key_id}:{window}", WINDOW_SECONDS)
        count = int(pipe.execute()[0])
    except redis.RedisError:
        # Fail open: an outage of the limiter must not take the API down.
        log.warning("rate limiter unavailable, allowing request", exc_info=True)
        return RateLimitResult(True, limit, limit, reset)
    return RateLimitResult(count <= limit, limit, max(limit - count, 0), reset)
