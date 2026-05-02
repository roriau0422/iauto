"""Production observability — Sentry, Prometheus, OpenTelemetry.

All three integrations are env-gated: nothing initialises unless the
corresponding setting is non-empty. Tests never see Sentry traffic and
the `/metrics` endpoint always works (the registry exists in-process)
but it returns zero counters when no requests have been served.

Wiring:

  * `init_sentry(settings)` is called from the FastAPI lifespan AFTER
    `configure_logging` so structured logs propagate as breadcrumbs.
  * `init_tracing(settings)` is a no-op when
    `OTEL_EXPORTER_OTLP_ENDPOINT` is unset; otherwise it wires the
    OTLP exporter via `opentelemetry-sdk` + the FastAPI / SQLAlchemy
    auto-instrumentations. We don't ship the OTel deps yet (they're
    heavy and unused outside prod) — this stub holds the shape so
    the prod build can pull them in without code churn.
  * `MetricsMiddleware` records request count + latency histograms by
    method + path template + status. Use `path_template_for(request)`
    so /v1/users/{id} doesn't blow up cardinality.
  * `metrics_endpoint(request)` exposes `/metrics` for Prometheus.

The Prometheus registry is module-level so any context can register
a custom counter/gauge once at import time without re-pulling the
registry handle.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.platform.logging import get_logger

if TYPE_CHECKING:
    from app.platform.config import Settings

logger = get_logger("app.platform.observability")

# Module-level registry — all metrics live here so `/metrics` exposes
# the full picture from a single scrape. Tests can read this directly.
REGISTRY = CollectorRegistry()

REQUESTS_TOTAL = Counter(
    "iauto_http_requests_total",
    "Total HTTP requests handled by the API.",
    ("method", "path", "status"),
    registry=REGISTRY,
)
REQUEST_LATENCY_SECONDS = Histogram(
    "iauto_http_request_duration_seconds",
    "Request latency, in seconds, by method/path/status.",
    ("method", "path", "status"),
    # Tighter buckets at the bottom — most requests should be sub-100ms.
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
    registry=REGISTRY,
)
AI_SPEND_MICRO_MNT_TOTAL = Counter(
    "iauto_ai_spend_micro_mnt_total",
    "Cumulative AI spend in micro-MNT (1 MNT = 1_000_000 micro).",
    ("model",),
    registry=REGISTRY,
)
OUTBOX_BACKLOG = Gauge(
    "iauto_outbox_backlog",
    "Number of undispatched outbox events at the last scrape.",
    registry=REGISTRY,
)


def init_sentry(settings: Settings) -> bool:
    """Initialise Sentry if a DSN is configured.

    Returns True iff Sentry was initialised — useful for tests that
    want to assert the no-op path.
    """
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        logger.info("sentry_skipped", reason="no_dsn")
        return False

    # Lazy import — sentry-sdk pulls a non-trivial chain of optional
    # extras (urllib3 hooks, gevent shims) we don't want loaded in
    # tests or in workers that don't need it.
    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.app_env.value,
        release=settings.app_name,
        # Send 10% of transactions in prod; staging+dev get full sampling
        # so noisy paths show up immediately during dogfooding.
        traces_sample_rate=0.1 if settings.is_prod else 1.0,
        # Link breadcrumbs to structlog by default — we already log
        # request_id/path/method via contextvars.
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            AsyncioIntegration(),
        ],
        # Don't ship request bodies — they may contain JWTs, OTPs, or
        # encrypted PII. Sentry's default scrubber misses Mongolian
        # field names and we'd rather err on the safe side.
        send_default_pii=False,
        max_breadcrumbs=50,
    )
    logger.info("sentry_initialised", env=settings.app_env.value)
    return True


def init_tracing(settings: Settings) -> bool:
    """Wire OpenTelemetry against the configured OTLP endpoint.

    The OTel deps are intentionally NOT in pyproject.toml — they're
    heavy and only useful in prod. The prod Docker image installs
    `opentelemetry-distro[otlp] opentelemetry-instrumentation-fastapi
    opentelemetry-instrumentation-sqlalchemy` on top of the wheel.

    This function silently skips if the deps aren't present, so dev
    + tests + the dev image all keep booting cleanly.
    """
    endpoint = (settings.otel_exporter_otlp_endpoint or "").strip()
    if not endpoint:
        logger.info("otel_skipped", reason="no_endpoint")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("otel_skipped", reason="deps_missing", endpoint=endpoint)
        return False

    resource = Resource.create(
        {
            "service.name": settings.app_name,
            "service.namespace": "iauto",
            "deployment.environment": settings.app_env.value,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("otel_initialised", endpoint=endpoint)
    return True


def path_template_for(request: Request) -> str:
    """Return the FastAPI route template (e.g. `/v1/users/{id}`).

    Falls back to the literal path when no route matches — this happens
    on 404s. We bucket all unmatched paths under `__not_found__` to
    avoid cardinality blowup from random URL probes.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return "__not_found__"


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request counters + latency for every served HTTP request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            # If the handler raised, record a 500 then re-raise so the
            # exception handler chain still runs.
            elapsed = time.perf_counter() - start
            template = path_template_for(request)
            REQUESTS_TOTAL.labels(request.method, template, "500").inc()
            REQUEST_LATENCY_SECONDS.labels(request.method, template, "500").observe(elapsed)
            raise

        elapsed = time.perf_counter() - start
        template = path_template_for(request)
        REQUESTS_TOTAL.labels(request.method, template, str(status)).inc()
        REQUEST_LATENCY_SECONDS.labels(request.method, template, str(status)).observe(elapsed)
        return response


async def metrics_endpoint(_request: Request) -> Response:
    """Prometheus scrape endpoint.

    Mounted at `/metrics` on the root app (not `/v1/metrics`) because
    Prometheus scrapers default to that path and renaming costs us a
    config knob in every deploy.
    """
    body = generate_latest(REGISTRY)
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)


def record_ai_spend(model: str, micro_mnt: int) -> None:
    """Cheap counter increment — call from spend logging code paths."""
    if micro_mnt <= 0:
        return
    AI_SPEND_MICRO_MNT_TOTAL.labels(model).inc(micro_mnt)
