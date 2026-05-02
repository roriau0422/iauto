"""Per-user daily request limit for AI Mechanic agent runs.

Redis key shape: `ai:rl:{user_id}:{yyyy-mm-dd}`. INCR with a 25h TTL
the first time we see a user on a given day. The TTL covers the
midnight-UTC roll-over plus a comfortable margin so a slow clock doesn't
let a user double-claim quota across the boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.platform.errors import RateLimitedError


class AiRateLimiter:
    def __init__(self, *, redis: Redis, daily_limit: int) -> None:
        self.redis = redis
        self.daily_limit = daily_limit

    @staticmethod
    def _key(user_id: uuid.UUID, day: str) -> str:
        return f"ai:rl:{user_id}:{day}"

    async def check_and_consume(self, *, user_id: uuid.UUID) -> int:
        """Atomically increment the daily counter and reject when over quota.

        Returns the new count (1-based) on success; raises 429 otherwise.
        """
        if self.daily_limit <= 0:
            return 0
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        key = self._key(user_id, day)
        # INCR returns the new value after increment.
        count = await self.redis.incr(key)
        if count == 1:
            # First hit today — set TTL so the key disappears tomorrow.
            await self.redis.expire(key, 25 * 60 * 60)
        if int(count) > self.daily_limit:
            raise RateLimitedError(f"Daily AI request limit exceeded ({self.daily_limit} per user)")
        return int(count)
