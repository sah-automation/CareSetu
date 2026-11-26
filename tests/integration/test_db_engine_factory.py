"""Integration: database engine factory pooled and no-pool engines serve a query (ARCH-P1 #813).

Both factory paths must open a connection and answer ``SELECT 1`` against the
native PostgreSQL. ``reachable_db`` keeps the DB-unreachable case as a skip.
"""

from sqlalchemy import text

from app.config import Settings
from app.db import create_primary_engine


async def test_no_pool_engine_serves_query(database_url, reachable_db) -> None:
    settings = Settings(database_url=database_url, db_pool_enabled=False)
    engine = create_primary_engine(settings)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        await engine.dispose()


async def test_pooled_engine_serves_query(database_url, reachable_db) -> None:
    settings = Settings(
        database_url=database_url,
        db_pool_enabled=True,
        db_pool_size=2,
        db_max_overflow=1,
        db_pool_timeout=10.0,
        db_pool_recycle=60,
    )
    engine = create_primary_engine(settings)
    try:
        assert getattr(engine.pool, "_pre_ping", False) is True
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        await engine.dispose()
