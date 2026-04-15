-- Runs once, the first time the postgres container initializes its data dir.
-- Subsequent container starts skip this file — changes to extensions after
-- first init must go through Alembic migrations.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS citext;

-- Dedicated test database. The test suite applies migrations here against a
-- clean schema so integration tests do not stomp on local development data.
CREATE DATABASE iauto_test OWNER iauto;
\connect iauto_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS citext;
