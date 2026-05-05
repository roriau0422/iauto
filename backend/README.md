# iauto-backend

FastAPI modular monolith. See `../docs/ARCHITECTURE.md` for the committed design. Status and workflow rules: `../CLAUDE.md`.

## First-time setup

Prereqs: `uv`, Docker Desktop, `git`.

```bash
# From repo root
cd backend

# 1. Create venv (CLAUDE.md convention: venv/, not .venv/)
uv venv venv --python 3.13
source venv/Scripts/activate            # Windows git-bash
# source venv/bin/activate              # macOS / Linux

# 2. Install deps (runtime + dev)
uv pip install -e ".[dev]"

# 3. Start dev infra (Postgres 16 + pgvector + pg_trgm, Redis 7, MinIO)
docker compose -f ../infra/docker-compose.dev.yml up -d

# 4. Copy env template and fill secrets (all three keys are required)
cp .env.example .env
# Generate the three required secrets:
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print('APP_DATA_KEY=' + Fernet.generate_key().decode())"
python -c "import secrets; print('APP_SEARCH_KEY=' + secrets.token_hex(32))"
# Paste the output into .env. The app fails to start if any is missing.

# 5. Apply migrations (main DB + dedicated test DB)
alembic upgrade head
alembic -x db=test upgrade head
```

## Running

```bash
# API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Arq outbox consumer (separate terminal — required for events_archive to fill)
arq app.workers.outbox_consumer.WorkerSettings
```

OpenAPI docs: <http://localhost:8000/docs>. Health: <http://localhost:8000/v1/health>.

## Verification loop

Run all four before declaring work done. Matches `.github/workflows/backend.yml` exactly — any shortcut here ends in a red CI run.

```bash
ruff check app tests
ruff format --check app tests        # NOT just `ruff check` — format is separate
mypy app
pytest
```

To apply format fixes: `ruff format app tests` (no `--check`).

## OpenAPI snapshot

The live OpenAPI spec is at `/openapi.json` on the running server. A committed snapshot at `../shared/openapi/v1.json` is the mobile-codegen source and the CI drift-detection target — regenerate whenever a route or response model changes:

```bash
python scripts/gen_openapi.py          # regenerate (commit the diff)
python scripts/gen_openapi.py --check  # fail if stale — matches CI
```

## Migrations

Alembic with a **single migration history** for the whole backend (decision 9 in `../docs/ARCHITECTURE.md §13`). One directory, one upgrade head, one revision per PR.

```bash
alembic revision -m "add xyz"     # new empty revision (edit by hand; autogenerate is advisory only)
alembic upgrade head              # apply
alembic -x db=test upgrade head   # apply to the test DB
alembic downgrade -1              # reversibility check — run this before commit
```

Migration 0020 is the current head. `app/platform/models_registry.py` is the single import point Alembic's `env.py` uses; **add every new ORM model to that registry** or autogenerate will silently miss it.

## Layout

Contexts live under `app/<context>/`. Shared infra under `app/platform/`. HTTP routers aggregate under `app/api/v1/`. See `docs/ARCHITECTURE.md` §3.1 for the full bounded-context list.

Implemented contexts (alphabetical) — phases 1–5 complete:

- `app/admin/` — internal-only `/v1/admin/spend` AI spend report (admin role gate)
- `app/ads/` — self-served ad campaigns + click/impression tracking via QPay
- `app/ai_mechanic/` — Agents-SDK skeleton, LiteLLM Gemini routing, tools, KB w/ pgvector + HNSW, Whisper voice, warning-light classifier, Gemini multimodal (visual + engine sound), per-user daily Redis rate limit, embedding cache, spend log
- `app/businesses/` — profiles + members + vehicle-brand coverage; `businesses.id` is the `tenant_id`
- `app/catalog/` — vehicle country → brand → model taxonomy
- `app/chat/` — WebSocket chat over Redis pub/sub (driver ↔ business + ↔ user)
- `app/identity/` — OTP auth, JWT + rotating refresh w/ reuse-detection, device registry, role selection
- `app/marketplace/` — part-search RFQ + quotes + reservations + sales + reviews
- `app/media/` — MinIO presign+confirm flow for images, audio, PDFs
- `app/notifications/` — push notifications via outbox subscribers (FCM + APNs)
- `app/payments/` — QPay v2 invoices + double-entry ledger
- `app/platform/` — config, db, cache, crypto, outbox, events, logging, errors, middleware, observability (Sentry + Prometheus + OTel), auth rate-limit, models registry
- `app/story/` — UCar Story feed (posts, likes, comments)
- `app/valuation/` — CatBoost car valuation w/ heuristic fallback (`POST /v1/valuation/estimate`)
- `app/vehicles/` — client-side XYP lookup plan, ownership, operator SMS alerts, service history + PDF export
- `app/warehouse/` — business inventory (SKUs + stock movements)
- `app/workers/` — Arq cron jobs: outbox tick (5s), reservation expiry (1m), valuation retrain (02:00 UTC daily), AI cost alert (05:00 UTC daily)

Tests mirror the layout under `tests/<context>/`. The integration-test fixture in `tests/conftest.py` wraps every test in a SAVEPOINT against the `iauto_test` database on the dev-compose Postgres — no mocks, no sqlite fallback.

## Gotchas to know about before touching code

These live in `tasks/lessons.md` (local, git-ignored) but the common traps are worth naming here:

- Encryption keys (`APP_DATA_KEY`, `APP_SEARCH_KEY`) are required at startup — no dev fallbacks, because ephemeral dev keys silently corrupt DB state.
- Tests that need Redis keys owned by a service MUST import the service's own key helpers (`_cooldown_key`, `_phone_fingerprint`, ...) rather than hand-rolling string formats — the blind-index rewrite broke a hand-rolled key in session 3.
- Curl smoke tests with Cyrillic bodies must use `--data-binary @body.json` + `Content-Type: application/json; charset=utf-8`. Inline `-d '{"plate":"9987УБӨ"}'` gets mangled to `8877???` by Git Bash on Windows.
- Cross-context calls go through the target context's `Service`, never its `Repository`. This is enforced by convention, not by import guards — keep an eye out in review.
