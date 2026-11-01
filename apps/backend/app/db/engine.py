"""Database engine factory (ARCH-P1 #813).

Provides a narrow structural protocol exposing the async ``begin()`` and
``connect()`` context managers, and a factory that creates either a no-pool
engine (poolclass=NullPool) or a bounded pooled engine with pre-ping based on
settings.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings


class AsyncEngineLike(Protocol):
    """Narrow engine-like protocol for facade typing.

    Facades depend on this protocol instead of ``AsyncEngine`` directly so a
    router can satisfy the same seam later (ARCH-P1 #814).
    """

    def begin(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Begin a transaction and return a connection context manager."""
        ...

    def connect(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Return a connection context manager without starting a transaction."""
        ...


def create_engine(settings: Settings) -> AsyncEngine:
    """Primary engine factory alias expected by ARCH-P1 docs (#813)."""
    return create_primary_engine(settings)


def create_primary_engine(settings: Settings) -> AsyncEngine:
    """Create the primary database engine from settings.

    When ``DB_POOL_ENABLED`` is false (default), returns a no-pool engine using
     ``NullPool`` - preserving today's behaviour for local development and the
    free-tier deployment. When true, creates a bounded pooled engine with
    pre-ping using the configured pool settings.
    """
    if settings.db_pool_enabled:
        return create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=True,
        )
    return create_async_engine(settings.database_url, poolclass=NullPool)


async def dispose_engine(engine: AsyncEngine) -> None:
    """Dispose the engine and its pool.

    Called by the web app lifespan on shutdown. Worker, script, and test entry
    points keep constructing raw engines and manage their own disposal.
    """
    await engine.dispose()


# Backward-compatible aliases kept for plausible ARCH-P1 naming.
EngineLike = AsyncEngineLike
AsyncEngineProtocol = AsyncEngineLike
