# iauto-backend

FastAPI modular monolith. See `../docs/ARCHITECTURE.md` for the committed design.

## Quickstart

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

# 3. Start dev infra (Postgres 16 + pgvector, Redis 7, MinIO)
docker compose -f ../infra/docker-compose.dev.yml up -d

# 4. Copy env and edit secrets locally
cp .env.example .env
# edit .env to fill in real MessagePro credentials etc.

# 5. Apply migrations
alembic upgrade head

# 6. Run the API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 7. Run the outbox worker (separate terminal)
arq app.workers.outbox_consumer.WorkerSettings
```

OpenAPI docs at <http://localhost:8000/docs>. Health check at
<http://localhost:8000/v1/health>.

## Tests

```bash
ruff check
ruff format --check
mypy app
pytest
```

## OpenAPI snapshot

The live OpenAPI spec is at `/openapi.json` on the running server. A
committed snapshot at `../shared/openapi/v1.json` is the mobile-codegen
source and the CI drift-detection target — regenerate it whenever a route
or response model changes:

```bash
venv/Scripts/python.exe scripts/gen_openapi.py          # regenerate
venv/Scripts/python.exe scripts/gen_openapi.py --check  # fail if stale
```

## Layout

Contexts live under `app/`. Shared infra in `app/platform/`. HTTP routers
aggregate under `app/api/v1/`. See `docs/ARCHITECTURE.md` §3.1 for the
bounded-context list.
