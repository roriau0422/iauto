# syntax=docker/dockerfile:1.7

# -----------------------------------------------------------------------------
# Stage 1 — builder. Produces a wheel with all runtime deps installed into a
# discardable virtualenv we copy out in the next stage.
# -----------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Build deps for asyncpg, catboost, cryptography, reportlab.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only metadata first so dep resolution caches across code edits.
COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install '.[]' \
 && /opt/venv/bin/pip install opentelemetry-distro[otlp] \
        opentelemetry-instrumentation-fastapi \
        opentelemetry-instrumentation-sqlalchemy \
        opentelemetry-instrumentation-redis

# -----------------------------------------------------------------------------
# Stage 2 — runtime. Slim image, non-root user, tini as PID 1 for signal
# handling and zombie reaping.
# -----------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=prod \
    APP_LOG_FORMAT=json

# tini — small init handling SIGTERM cleanly so uvicorn graceful-shutdown runs.
# libpq for asyncpg dynamic linking. ca-certificates for outbound TLS.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        libpq5 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root account — never run app code as root in prod.
RUN groupadd --system --gid 1000 iauto \
 && useradd --system --uid 1000 --gid iauto --create-home --shell /usr/sbin/nologin iauto

# venv + source from builder.
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=iauto:iauto app /app/app
COPY --chown=iauto:iauto alembic.ini /app/alembic.ini
COPY --chown=iauto:iauto alembic /app/alembic
COPY --chown=iauto:iauto scripts /app/scripts

USER iauto

EXPOSE 8000

# k8s/ALB target health → /v1/health (cheap liveness). /v1/ready hits DB +
# Redis + MinIO and is the gate for traffic shifting.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail http://localhost:8000/v1/health || exit 1

# tini handles signal forwarding so SIGTERM lands cleanly on uvicorn.
ENTRYPOINT ["/usr/bin/tini", "--"]

# uvicorn defaults — overridden in compose for the worker process.
# `--proxy-headers` lets X-Forwarded-* reach FastAPI when fronted by
# nginx/ALB. `--forwarded-allow-ips=*` is fine because the LB strips
# untrusted forwarded headers before forwarding.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips=*", \
     "--workers", "2", \
     "--log-config", "/dev/null"]
