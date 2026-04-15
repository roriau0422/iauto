# iAuto

Super-app for Mongolian drivers and auto businesses: marketplace for parts and
services, social stories, warehouse management, QPay-integrated payments, an
AI Mechanic (multi-modal diagnostic), and a CatBoost-based car valuation engine.

## Repository map

```
iauto/
  backend/   FastAPI modular monolith (Python 3.13, uv, SQLAlchemy 2 async)
  mobile/    Expo (dev client) React Native app
  ml/        Training pipelines, notebooks, CatBoost experiments
  shared/    OpenAPI snapshot + generated clients
  infra/     docker-compose, deploy scripts
  docs/      Product spec (Mongolian PDF + UTF-8) and ARCHITECTURE.md
  tasks/     Session plans and lessons learned
```

## Start here

1. Read `docs/ARCHITECTURE.md` end-to-end — committed decisions live there.
2. Read `CLAUDE.md` for workflow rules and tooling conventions.
3. For day-to-day backend work see `backend/README.md` once it ships.

## Status

Pre-implementation. Phase 0 scaffold in progress — see `tasks/todo.md`.
