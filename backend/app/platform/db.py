"""Async SQLAlchemy engine + session management.

One engine and one session factory per process, built in the FastAPI lifespan
and torn down on shutdown. Request handlers receive a session via the
`get_session` dependency, which commits on success and rolls back on exception.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.platform.config import Settings, get_settings


def build_engine(settings: Settings | None = None) -> AsyncEngine:
    s = settings or get_settings()
    return create_async_engine(
        s.database_url_str,
        echo=s.database_echo,
        pool_size=s.database_pool_size,
        max_overflow=s.database_max_overflow,
        pool_pre_ping=True,
        future=True,
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# Module-level handles populated by the app lifespan. Nothing outside of the
# lifespan + get_session should touch these.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(settings: Settings | None = None) -> None:
    global _engine, _session_factory
    _engine = build_engine(settings)
    _session_factory = build_sessionmaker(_engine)


async def dispose_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError(
            "Database not initialised. Ensure init_db() has been called "
            "(normally handled by the FastAPI lifespan)."
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an AsyncSession.

    Commits the transaction on clean exit and rolls back on any exception
    raised by the handler. The session is always closed.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
