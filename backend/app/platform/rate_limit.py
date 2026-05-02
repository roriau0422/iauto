"""Per-IP rate limit middleware for authentication endpoints.

Phase 5 session 22. Caps OTP request/verify floods at the network
edge so a single bad actor can't burn through MessagePro credits or
brute-force a 6-digit OTP.

The bucket is `auth:rl:ip:{ip}:{epoch_minute}` with a 70-second TTL
(longer than the bucket window to avoid race deletions). When a
caller crosses the threshold, the middleware returns a problem+json
429 with `Retry-After` set to the seconds until the bucket rolls.

Path scope is hard-coded to `/v1/auth/` because that's the only
Phase 5 surface that needs unauthenticated rate limiting. The
identity service still enforces per-phone OTP attempt limits
inside the service layer.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Imported as a module so tests can monkeypatch `cache.get_redis`
# without having to reach into this module's local namespace.
from app.platform import cache as _cache
from app.platform.logging import get_logger

logger = get_logger(__name__)

AUTH_PATH_PREFIX = "/v1/auth/"


def _client_ip(request: Request) -> str:
    """Return the best-guess client IP.

    Trusts X-Forwarded-For (rightmost is the closest proxy; leftmost
    is the original client). nginx + uvicorn `--proxy-headers` set
    these. Falls back to the socket peer if no proxy header is set.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """60-requests-per-minute per IP on /v1/auth/* (~1 req/sec sustained)."""

    REQUESTS_PER_MINUTE = 60
    BUCKET_TTL_SECONDS = 70

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith(AUTH_PATH_PREFIX):
            return await call_next(request)

        try:
            redis: Redis = _cache.get_redis()
        except RuntimeError:
            # Cache not initialised (e.g. unit-test stub). Fail open —
            # the per-phone OTP limiter still gates attempts at the
            # service layer.
            return await call_next(request)

        ip = _client_ip(request)
        epoch_minute = int(time.time() // 60)
        key = f"auth:rl:ip:{ip}:{epoch_minute}"
        try:
            count = int(await redis.incr(key))
            if count == 1:
                await redis.expire(key, self.BUCKET_TTL_SECONDS)
        except Exception as exc:
            # Redis hiccup — fail open. Logging here so a flapping
            # cache doesn't silently disable the limiter.
            logger.warning("auth_ratelimit_redis_error", error=str(exc), ip=ip)
            return await call_next(request)

        if count > self.REQUESTS_PER_MINUTE:
            retry_after = 60 - int(time.time() % 60)
            logger.info(
                "auth_ratelimit_blocked",
                ip=ip,
                count=count,
                limit=self.REQUESTS_PER_MINUTE,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "type": "about:blank#rate_limited",
                    "title": "Too many requests",
                    "status": 429,
                    "detail": "Slow down — too many auth requests from this IP.",
                    "error_code": "rate_limited",
                    "retry_after_seconds": retry_after,
                },
                media_type="application/problem+json",
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
