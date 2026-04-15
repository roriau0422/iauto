"""Redis connection pool + FastAPI dependency."""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.platform.config import Settings, get_settings

_client: Redis | None = None


async def init_redis(settings: Settings | None = None) -> None:
    global _client
    s = settings or get_settings()
    _client = from_url(  # type: ignore[no-untyped-call]
        s.redis_url_str,
        decode_responses=True,
        encoding="utf-8",
        max_connections=50,
    )
    await _client.ping()


async def dispose_redis() -> None:
    global _client
    if _client is not None:
        await _client.close()
    _client = None


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError(
            "Redis not initialised. Ensure init_redis() has been called "
            "(normally handled by the FastAPI lifespan)."
        )
    return _client
