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
3. For day-to-day backend work see `backend/README.md`.

## Status

**Phase 0 complete. Phase 1 session 4 shipped.** Backend-only so far.

Implemented contexts: `identity`, `vehicles`, `catalog`, `businesses`, `marketplace` (driver-side RFQ slice), `platform`, `workers` (Arq outbox consumer). See `CLAUDE.md` for the full status table and the list of contexts still ahead in phase 1.

Mobile app (Expo), `chat`, `stories`, `ads`, `warehouse`, `payments`, `ai_mechanic`, `valuation`, `notifications`, `moderation`, and `analytics` contexts are deliberately deferred to later sessions.
