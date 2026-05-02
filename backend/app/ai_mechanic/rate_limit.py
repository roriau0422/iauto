"""Per-user daily request limit for AI Mechanic agent runs.

Redis key shape: `ai:rl:{user_id}:{yyyy-mm-dd}`. INCR with a 25h TTL
the first time we see a user on a given day. The TTL covers the
midnight-UTC roll-over plus a comfortable margin so a slow clock doesn't
let a user double-claim quota across the boundary.

`RateLimitDecision` carries the metadata needed to set IETF
draft-ietf-httpapi-ratelimit-headers on the response (and on the 429
problem+json body via `RateLimitedError.extra`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from app.platform.errors import RateLimitedError


@dataclass(slots=True)
class RateLimitDecision:
    """Metadata describing the bucket state after a check_and_consume call."""

    limit: int
    remaining: int
    reset_seconds: int


def _seconds_until_utc_midnight(now: datetime) -> int:
    """Seconds until the next 00:00 UTC. Used as the rate-limit reset window."""
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0, int((tomorrow - now).total_seconds()))


class AiRateLimiter:
    def __init__(self, *, redis: Redis, daily_limit: int) -> None:
        self.redis = redis
        self.daily_limit = daily_limit

    @staticmethod
    def _key(user_id: uuid.UUID, day: str) -> str:
        return f"ai:rl:{user_id}:{day}"

    async def check_and_consume(self, *, user_id: uuid.UUID) -> RateLimitDecision:
        """Atomically increment the daily counter and reject when over quota.

        Returns a `RateLimitDecision` on success so the router can mirror
        the bucket state into response headers; raises `RateLimitedError`
        with the same metadata on overage.
        """
        now = datetime.now(UTC)
        reset_seconds = _seconds_until_utc_midnight(now)

        if self.daily_limit <= 0:
            # Limit disabled — return a sentinel decision so callers can
            # still set RateLimit-* headers without special-casing.
            return RateLimitDecision(limit=0, remaining=0, reset_seconds=reset_seconds)

        day = now.strftime("%Y-%m-%d")
        key = self._key(user_id, day)
        count = int(await self.redis.incr(key))
        if count == 1:
            # First hit today — set TTL so the key disappears tomorrow.
            await self.redis.expire(key, 25 * 60 * 60)

        remaining = max(0, self.daily_limit - count)

        if count > self.daily_limit:
            raise RateLimitedError(
                f"Daily AI request limit exceeded ({self.daily_limit} per user)",
                extra={
                    "limit": self.daily_limit,
                    "remaining": 0,
                    "reset_seconds": reset_seconds,
                },
            )

        return RateLimitDecision(
            limit=self.daily_limit,
            remaining=remaining,
            reset_seconds=reset_seconds,
        )
