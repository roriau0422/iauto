"""Phase 5 session 22 — auth rate-limit middleware coverage."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.platform import cache as cache_module
from app.platform.rate_limit import AuthRateLimitMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthRateLimitMiddleware)

    async def hello() -> dict[str, bool]:
        return {"ok": True}

    # Two surfaces — auth is gated, the rest is not.
    app.add_api_route("/v1/auth/otp/request", hello, methods=["POST"])
    app.add_api_route("/v1/health", hello, methods=["GET"])
    return app


@pytest.fixture
def fake_redis_uninit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force `get_redis()` to raise so we can confirm the fail-open path."""

    def _raise() -> Redis:
        raise RuntimeError("redis not initialised")

    monkeypatch.setattr(cache_module, "get_redis", _raise)


@pytest.mark.asyncio
async def test_auth_rate_limit_skips_non_auth_paths(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-`/v1/auth/*` paths must never touch redis or rate-limit
    counters. Otherwise we'd serialise every read through the limiter."""

    monkeypatch.setattr(cache_module, "get_redis", lambda: redis)

    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 200 hits to /v1/health — no rate limit. /v1/auth/* would 429.
        for _ in range(200):
            r = await client.get("/v1/health")
            assert r.status_code == 200
    # No keys created.
    keys = await redis.keys("auth:rl:ip:*")
    assert keys == []


@pytest.mark.asyncio
async def test_auth_rate_limit_429s_after_threshold(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache_module, "get_redis", lambda: redis)

    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First 60 succeed, the 61st 429s with Retry-After.
        for _ in range(AuthRateLimitMiddleware.REQUESTS_PER_MINUTE):
            r = await client.post("/v1/auth/otp/request", json={})
            assert r.status_code == 200, r.text
        blocked = await client.post("/v1/auth/otp/request", json={})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    body = blocked.json()
    assert body["error_code"] == "rate_limited"
    assert body["retry_after_seconds"] >= 0


@pytest.mark.asyncio
async def test_auth_rate_limit_fails_open_when_redis_uninit(
    fake_redis_uninit: None,
) -> None:
    """If get_redis() raises (e.g. test stub doesn't init redis),
    requests must succeed — the per-phone OTP limit still applies in
    the service layer."""
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 100 requests — would be 429'd if redis were available.
        for _ in range(100):
            r = await client.post("/v1/auth/otp/request", json={})
            assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_rate_limit_uses_x_forwarded_for(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When fronted by nginx, X-Forwarded-For carries the real client IP.
    Two distinct forwarded IPs each get their own bucket."""
    monkeypatch.setattr(cache_module, "get_redis", lambda: redis)

    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(AuthRateLimitMiddleware.REQUESTS_PER_MINUTE):
            r = await client.post(
                "/v1/auth/otp/request",
                json={},
                headers={"X-Forwarded-For": "203.0.113.7"},
            )
            assert r.status_code == 200

        # IP A is exhausted.
        blocked = await client.post(
            "/v1/auth/otp/request",
            json={},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
        assert blocked.status_code == 429

        # IP B is fresh.
        ok = await client.post(
            "/v1/auth/otp/request",
            json={},
            headers={"X-Forwarded-For": "198.51.100.42"},
        )
        assert ok.status_code == 200
