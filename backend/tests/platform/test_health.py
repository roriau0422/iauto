"""/v1/health and /v1/ready coverage.

The readiness probe is the load balancer's traffic gate, so we lock
down: (a) the happy path returns 200 + `ready`, (b) a failed dep
flips the status to `degraded` and the response code to 503, (c) the
outbox-lag gauge mirrors into Prometheus.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import health as health_module
from app.platform.observability import OUTBOX_BACKLOG


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_module.router, prefix="/v1")
    return app


@pytest.mark.asyncio
async def test_health_endpoint_is_cheap_liveness() -> None:
    """`/v1/health` must always return 200 even when DB/Redis/MinIO
    are down — that's the point of separating live from ready."""
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "iauto-backend"


@pytest.mark.asyncio
async def test_ready_returns_503_when_db_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the DB probe fails, /ready must 503 so the LB stops
    routing traffic. Object-storage skip when not configured is fine."""

    async def _fail_db() -> tuple[bool, int]:
        return False, -1

    async def _ok_redis() -> bool:
        return True

    async def _ok_s3() -> bool:
        return True

    monkeypatch.setattr(health_module, "_probe_db", _fail_db)
    monkeypatch.setattr(health_module, "_probe_redis", _ok_redis)
    monkeypatch.setattr(health_module, "_probe_object_storage", _ok_s3)

    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"] is False
    assert body["redis"] is True
    assert body["object_storage"] is True


@pytest.mark.asyncio
async def test_ready_happy_path_publishes_backlog_gauge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All probes ok → 200 ready, and the outbox-lag mirrors to the
    Prometheus gauge so we don't need a separate scraper."""

    async def _ok_db() -> tuple[bool, int]:
        return True, 7

    async def _ok_redis() -> bool:
        return True

    async def _ok_s3() -> bool:
        return True

    monkeypatch.setattr(health_module, "_probe_db", _ok_db)
    monkeypatch.setattr(health_module, "_probe_redis", _ok_redis)
    monkeypatch.setattr(health_module, "_probe_object_storage", _ok_s3)

    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["outbox_backlog"] == 7

    # Gauge mirrors. Read the current value via the registry.
    assert OUTBOX_BACKLOG._value.get() == 7


@pytest.mark.asyncio
async def test_ready_negative_backlog_clamped_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the DB probe failed, backlog is -1 internally; the response
    body must clamp to 0 so dashboards don't see a negative count."""

    async def _ok_db() -> tuple[bool, int]:
        # Edge: probe succeeds but reports -1 (shouldn't happen, but
        # the response model must still produce a non-negative value).
        return True, -1

    async def _ok_redis() -> bool:
        return True

    async def _ok_s3() -> bool:
        return True

    monkeypatch.setattr(health_module, "_probe_db", _ok_db)
    monkeypatch.setattr(health_module, "_probe_redis", _ok_redis)
    monkeypatch.setattr(health_module, "_probe_object_storage", _ok_s3)

    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/ready")
    assert resp.status_code == 200
    assert resp.json()["outbox_backlog"] == 0


@pytest.mark.asyncio
async def test_probe_object_storage_skipped_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev environments without S3 configured must not block readiness."""
    from app.platform.config import Settings

    fake = Settings().model_copy(update={"s3_endpoint_url": None})
    monkeypatch.setattr(health_module, "get_settings", lambda: fake)
    ok = await health_module._probe_object_storage()
    assert ok is True


def test_probe_timeout_constant_bounded() -> None:
    """Timeout sane: short enough that a hung dep can't trip a long-LB
    health check, but long enough that healthy deps clear."""
    assert 0.5 <= health_module._PROBE_TIMEOUT_SECONDS <= 5.0


def _signature_typing_smoke() -> Any:
    """Compile-time smoke test that the response shape is what we expect.
    Pure import — no body. Caught by mypy in CI; pytest also runs it."""
    return health_module.ReadinessResponse(
        status="ready",
        database=True,
        redis=True,
        object_storage=True,
        outbox_backlog=0,
    )


def test_readiness_response_shape() -> None:
    r = _signature_typing_smoke()
    assert r.status == "ready"
    assert r.outbox_backlog == 0
