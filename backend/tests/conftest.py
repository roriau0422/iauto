"""Shared pytest fixtures.

The integration suite talks to the dev-compose Postgres via the dedicated
`iauto_test` database (URL in `DATABASE_TEST_URL`). Each test runs inside a
SAVEPOINT that's rolled back on teardown, so tests are isolated without
re-running migrations between them.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.identity.providers.sms import InMemorySmsProvider
from app.platform.config import get_settings
from app.platform.outbox import clear_handlers

# asyncpg is incompatible with Windows' default ProactorEventLoop. Switch to
# Selector early, before pytest-asyncio spawns a loop for any fixture.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(settings) -> AsyncIterator[AsyncEngine]:
    url = settings.database_test_url_str
    if url is None:
        pytest.skip("DATABASE_TEST_URL not configured")
    eng = create_async_engine(url, pool_pre_ping=True, future=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test transactional session that always rolls back on exit.

    Any mutation the test performs — including the helper that writes an
    outbox row — is reverted before the next test runs. No need to truncate
    tables between tests.
    """
    connection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture(autouse=True)
def _clear_handlers():
    """Never leak outbox handler registrations across tests."""
    clear_handlers()
    yield
    clear_handlers()


def _test_redis_url(settings) -> str:
    """Rewrite the configured redis URL to target logical DB #15 for tests.

    Keeping tests on a dedicated DB means `flushdb` at the start of each test
    can't wipe a developer's running app state.
    """
    url = settings.redis_url_str
    if url.endswith("/0"):
        return url[:-2] + "/15"
    if "/" in url.split("://", 1)[1]:
        return url.rsplit("/", 1)[0] + "/15"
    return url.rstrip("/") + "/15"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def redis_client(settings) -> AsyncIterator[Redis]:
    client = from_url(  # type: ignore[no-untyped-call]
        _test_redis_url(settings),
        decode_responses=True,
        encoding="utf-8",
    )
    await client.ping()
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture(loop_scope="session")
async def redis(redis_client: Redis) -> AsyncIterator[Redis]:
    """Per-test Redis handle — flushes the test DB before yielding."""
    await redis_client.flushdb()
    yield redis_client
    await redis_client.flushdb()


@pytest.fixture
def sms() -> InMemorySmsProvider:
    return InMemorySmsProvider()
