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


def _production_pool_enabled(settings: Settings) -> bool:
    # Render production boots a pooled primary engine by default - opening a
    # fresh connection per query (NullPool) made /v1/me miss the live load
    # gate's p95 bound on the free-tier shared CPU instance (#846 CD).
    # Operators can still force NullPool with DB_POOL_ENABLED=false.
    if settings.db_pool_enabled:
        return True
    return str(getattr(settings, "app_environment", "")).strip().lower() == "production"


def create_primary_engine(settings: Settings) -> AsyncEngine:
    """Create the primary database engine from settings.

    When ``DB_POOL_ENABLED`` is false (default), returns a no-pool engine using
     ``NullPool`` - preserving today's behaviour for local development and the
    free-tier deployment. When true, creates a bounded pooled engine with
    pre-ping using the configured pool settings.
    """
    if _production_pool_enabled(settings):
        return create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=True,
        )
    return create_async_engine(settings.database_url, poolclass=NullPool)


def create_read_replica_engines(settings: Settings) -> list[AsyncEngine]:
    """Build one engine per configured read-replica URL (#814).

    Returns an empty list when read replicas are disabled or no URLs are
    configured, so the default posture keeps all traffic on the primary.
    """
    urls = getattr(settings, "database_read_urls", ()) or ()
    if not getattr(settings, "read_replica_enabled", False) or not urls:
        return []

    if isinstance(urls, str):
        urls = tuple(part.strip() for part in urls.split(",") if part.strip())

    engines: list[AsyncEngine] = []
    pool_enabled = _production_pool_enabled(settings)
    for url in urls:
        if pool_enabled:
            engines.append(
                create_async_engine(
                    url,
                    pool_size=settings.db_pool_size,
                    max_overflow=settings.db_max_overflow,
                    pool_timeout=settings.db_pool_timeout,
                    pool_recycle=settings.db_pool_recycle,
                    pool_pre_ping=True,
                )
            )
        else:
            engines.append(create_async_engine(url, poolclass=NullPool))
    return engines


async def dispose_engine(engine: AsyncEngine) -> None:
    """Dispose the engine and its pool.

    Called by the web app lifespan on shutdown. Worker, script, and test entry
    points keep constructing raw engines and manage their own disposal.
    """
    await engine.dispose()


async def dispose_engines(engines: list[AsyncEngine]) -> None:
    for engine in engines or []:
        await engine.dispose()


# Backward-compatible aliases kept for plausible ARCH-P1 naming.
EngineLike = AsyncEngineLike
AsyncEngineProtocol = AsyncEngineLike
