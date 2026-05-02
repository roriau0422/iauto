"""Phase 5 session 18 — observability wiring.

These tests don't assert that Sentry/OTel actually ship data — that
needs a live network and is out of scope. They lock down the no-op
paths (so test runs never accidentally page a Sentry org) and the
shape of the Prometheus metrics surface.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.platform.config import Settings
from app.platform.observability import (
    AI_SPEND_MICRO_MNT_TOTAL,
    REGISTRY,
    REQUESTS_TOTAL,
    MetricsMiddleware,
    init_sentry,
    init_tracing,
    metrics_endpoint,
    record_ai_spend,
)


def _settings_with(**overrides: Any) -> Settings:
    """Build a Settings instance starting from `.env`-loaded defaults
    and applying the test overrides via Pydantic's `model_copy`."""
    return Settings().model_copy(update=overrides)


def test_init_sentry_no_dsn_skips() -> None:
    """No DSN → no Sentry init. Otherwise CI runs would page on errors."""
    s = _settings_with(sentry_dsn=None)
    assert init_sentry(s) is False
    s2 = _settings_with(sentry_dsn="")
    assert init_sentry(s2) is False


def test_init_tracing_no_endpoint_skips() -> None:
    s = _settings_with(otel_exporter_otlp_endpoint=None)
    assert init_tracing(s) is False
    s2 = _settings_with(otel_exporter_otlp_endpoint="")
    assert init_tracing(s2) is False


def test_record_ai_spend_increments_counter() -> None:
    """Calling record_ai_spend should bump the labelled counter and
    /metrics should expose the running total."""
    before = AI_SPEND_MICRO_MNT_TOTAL.labels("test-model")._value.get()
    record_ai_spend("test-model", 100_000)
    after = AI_SPEND_MICRO_MNT_TOTAL.labels("test-model")._value.get()
    assert after - before == 100_000

    # Negative or zero values are no-ops — the spend log already flooring
    # at 0 means we'd otherwise tick on every unknown-model call.
    before = AI_SPEND_MICRO_MNT_TOTAL.labels("test-model")._value.get()
    record_ai_spend("test-model", 0)
    record_ai_spend("test-model", -42)
    after = AI_SPEND_MICRO_MNT_TOTAL.labels("test-model")._value.get()
    assert after == before


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_format() -> None:
    """`/metrics` must respond with Prometheus's text exposition format
    so a stock prometheus scraper picks us up without any config."""

    async def hello() -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.add_middleware(MetricsMiddleware)
    app.add_api_route("/v1/hello", hello, methods=["GET"])
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Drive a request so the histogram + counter have data.
        ok = await client.get("/v1/hello")
        assert ok.status_code == 200

        # Non-existent route → middleware buckets it under __not_found__
        # so cardinality stays bounded.
        nf = await client.get("/totally/missing")
        assert nf.status_code == 404

        scrape = await client.get("/metrics")
    assert scrape.status_code == 200
    assert scrape.headers["content-type"].startswith("text/plain")
    body = scrape.text
    # Histogram + counter both present.
    assert "iauto_http_requests_total" in body
    assert "iauto_http_request_duration_seconds" in body
    # The /v1/hello label landed.
    assert "/v1/hello" in body
    assert "__not_found__" in body


def test_registry_collects_known_metrics() -> None:
    """Sanity check: the well-known metric names show up in the registry
    so other contexts can register more without accidentally shadowing
    one of ours.

    `Metric.name` strips counter suffixes like `_total`, so we check the
    base names. The exposition format restores them.
    """
    names = {m.name for m in REGISTRY.collect()}
    assert "iauto_http_requests" in names  # _total stripped from counter
    assert "iauto_http_request_duration_seconds" in names
    assert "iauto_ai_spend_micro_mnt" in names  # _total stripped
    assert "iauto_outbox_backlog" in names


@pytest.mark.asyncio
async def test_metrics_middleware_records_500_on_handler_exception() -> None:
    """If a handler raises, the middleware must still tick the counter
    with a 500 label so dashboards see the error rate."""

    async def boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    app = FastAPI()
    app.add_middleware(MetricsMiddleware)
    app.add_api_route("/v1/boom", boom, methods=["GET"])

    before = REQUESTS_TOTAL.labels("GET", "/v1/boom", "500")._value.get()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # raise_app_exceptions=False so httpx returns the 500 instead of
        # re-raising the inner RuntimeError.
        resp = await client.get("/v1/boom")
        assert resp.status_code == 500
    after = REQUESTS_TOTAL.labels("GET", "/v1/boom", "500")._value.get()
    assert after - before == 1
