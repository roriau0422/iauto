# iAuto

Super-app for Mongolian drivers and auto businesses: marketplace for parts and
services, social stories, warehouse management, QPay-integrated payments, an
AI Mechanic (multi-modal diagnostic), and a CatBoost-based car valuation engine.

## Status

**Phases 1–5 complete (backend).** 22 sessions shipped, 336 tests passing,
single-deployable FastAPI modular monolith with production Docker stack and
observability instrumentation. Mobile (Expo) deferred until staging cutover.

Per-phase summary (full breakdown in `docs/ARCHITECTURE.md §11`):

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundations: monorepo, CI, identity, vehicles, catalog, outbox spine | done |
| 1 | Marketplace: RFQ + quotes + reservations + sales + reviews, chat (WebSocket + Redis pub/sub), QPay v2 + double-entry ledger, service history + PDF export, push notifications | done |
| 2 | Business tools: warehouse (SKUs + stock movements), iAuto Story feed, paid ads | done |
| 3 | AI Mechanic: Agents-SDK + LiteLLM Gemini, RAG knowledge base (pgvector + HNSW), Whisper voice, warning-light classifier, Gemini multimodal (visual + engine sound), per-user cost controls | done |
| 4 | Car Valuation: CatBoost + heuristic fallback, daily 02:00 UTC retrain cron | done |
| 5 | Production hardening: Sentry + Prometheus + OTel, prod Dockerfile + compose, MinIO/outbox readiness probes, AI cost-alert cron, admin spend report, index + autovacuum hardening, per-IP auth rate limiter | done |

## Implemented contexts

`admin`, `ads`, `ai_mechanic`, `businesses`, `catalog`, `chat`, `identity`,
`marketplace`, `media`, `notifications`, `payments`, `platform`, `story`,
`valuation`, `vehicles`, `warehouse`, `workers`. All under `backend/app/`.

## Stack

- **Backend** — FastAPI (Python 3.13 via `uv`), SQLAlchemy 2 async + asyncpg,
  Alembic single-history migrations (head: 0020), Arq for cron + outbox.
- **Data plane** — Postgres 16 + pgvector + pg_trgm, Redis 7, MinIO (S3-
  compatible, talked to via `boto3` + `endpoint_url`).
- **AI** — OpenAI Agents SDK + LiteLLM routing to Gemini
  (`gemini-3-flash-preview`), Whisper for speech, Gemini multimodal for
  visual + engine-sound, CatBoost for valuation.
- **Observability** — Sentry, Prometheus (`/metrics`), OpenTelemetry hooks
  (all env-gated, no-op when DSN/endpoint absent).
- **Production** — multi-stage Dockerfile, `infra/docker-compose.prod.yml`
  with nginx TLS terminator on a split internal/edge network.

## Repository map

```
iauto/
  backend/   FastAPI modular monolith
  shared/    Committed OpenAPI snapshot for mobile codegen
  infra/     dev + prod docker-compose stacks, nginx config, prod env template
  docs/      Product spec (Mongolian PDF + UTF-8) and ARCHITECTURE.md
  ml/        Reserved for offline training notebooks (empty)
  mobile/    Reserved for the Expo app (deferred, empty)
```

## Start here

1. Read `docs/ARCHITECTURE.md` — committed decisions and phase log live there.
2. For day-to-day backend work see `backend/README.md` (setup + verification gate).
3. Bring up the dev stack: `docker compose -f infra/docker-compose.dev.yml up -d`.

## Deferred to post-launch

JWT key rotation with `kid` + grace window, OBD-II BLE integration, dealer/
bank bulk valuation API, business web app (Vite + React + TanStack Query),
ONNX MobileNet swap-in for the warning-light classifier, scraping pipelines,
real tax/insurance/fines data sources, Expo mobile build.
