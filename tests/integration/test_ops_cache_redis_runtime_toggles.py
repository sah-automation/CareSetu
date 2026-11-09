"""Integration tests for the ops to cache/redis runtime-toggle full cycle (#897).

Writes a runtime switch through OpsFacade, drives the outbox row through the
real dispatcher with the cache module's consumer registered, and asserts that
the in-process toggle flag and the effective settings view both follow.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.runtime_toggles import (
    cache_enabled,
    redis_enabled,
    set_cache_enabled,
    set_redis_enabled,
)
from bus.dispatcher import (
    DEFAULT_DISPATCHER_CONFIG,
    discover_outbox_tables,
    process_outbox_table,
)
from bus.events import EVENT_OPS_RUNTIME_SETTING_CHANGED
from bus.registry import HandlerRegistry
from modules.ops.facade import OpsFacade
from modules.ops.schema.models import ops_outbox


@pytest.fixture(autouse=True)
async def _reset_ops_settings(engine: AsyncEngine) -> AsyncIterator[None]:
    from sqlalchemy import text

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE ops.ops_setting_history, ops.ops_settings RESTART IDENTITY CASCADE"
            )
        )
    set_cache_enabled(True)
    set_redis_enabled(True)
    yield
    set_cache_enabled(True)
    set_redis_enabled(True)


@pytest.fixture
def facade(engine: AsyncEngine) -> OpsFacade:
    return OpsFacade(engine=engine, settings=Settings())


@pytest.fixture
def registry() -> HandlerRegistry:
    from app.cache import register_handlers as cache_register_handlers
    from modules.ops.adapters import register_handlers as ops_register_handlers

    reg = HandlerRegistry()
    ops_register_handlers(reg)
    cache_register_handlers(reg)
    return reg


async def _process_ops_outbox(engine: AsyncEngine, registry: HandlerRegistry) -> None:
    async with engine.connect() as connection:
        tables = await discover_outbox_tables(connection, ("ops",))
    for table in tables:
        await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)


class TestOpsCacheRedisRuntimeToggles:
    async def test_redis_disabled_full_cycle(
        self, facade: OpsFacade, engine: AsyncEngine, registry: HandlerRegistry
    ) -> None:
        assert redis_enabled() is True

        result = await facade.write_setting(setting_key="redis.enabled", value=False, updated_by=7)
        assert result == {"setting_key": "redis.enabled", "value": False, "version": 1}

        history = await facade.get_setting_history("redis.enabled")
        assert len(history) == 1
        assert history[0].value is False
        assert history[0].version == 1
        assert history[0].changed_by == 7

        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(ops_outbox).where(
                            ops_outbox.c.event_type == EVENT_OPS_RUNTIME_SETTING_CHANGED
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        assert rows[0]["payload"]["key"] == "redis.enabled"
        assert rows[0]["payload"]["value"] is False

        await _process_ops_outbox(engine, registry)

        assert redis_enabled() is False

        effective = await facade.get_effective_settings()
        row = next(s for s in effective if s.key == "redis.enabled")
        assert row.value is False
        assert row.source == "database"

    async def test_cache_disabled_full_cycle(
        self, facade: OpsFacade, engine: AsyncEngine, registry: HandlerRegistry
    ) -> None:
        assert cache_enabled() is True

        result = await facade.write_setting(setting_key="cache.enabled", value=False, updated_by=7)
        assert result == {"setting_key": "cache.enabled", "value": False, "version": 1}

        history = await facade.get_setting_history("cache.enabled")
        assert len(history) == 1
        assert history[0].value is False

        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(ops_outbox).where(
                            ops_outbox.c.event_type == EVENT_OPS_RUNTIME_SETTING_CHANGED
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        assert rows[0]["payload"]["key"] == "cache.enabled"
        assert rows[0]["payload"]["value"] is False

        await _process_ops_outbox(engine, registry)

        assert cache_enabled() is False

        effective = await facade.get_effective_settings()
        row = next(s for s in effective if s.key == "cache.enabled")
        assert row.value is False
        assert row.source == "database"

    async def test_toggle_back_to_true_restores_behavior(
        self, facade: OpsFacade, engine: AsyncEngine, registry: HandlerRegistry
    ) -> None:
        await facade.write_setting(setting_key="redis.enabled", value=False, updated_by=9)
        await _process_ops_outbox(engine, registry)
        assert redis_enabled() is False

        await facade.write_setting(setting_key="redis.enabled", value=True, updated_by=9)
        history = await facade.get_setting_history("redis.enabled")
        assert [entry.value for entry in history] == [True, False]

        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(ops_outbox).where(
                            ops_outbox.c.event_type == EVENT_OPS_RUNTIME_SETTING_CHANGED
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        assert rows[0]["payload"]["value"] is True

        await _process_ops_outbox(engine, registry)

        assert redis_enabled() is True
        effective = await facade.get_effective_settings()
        row = next(s for s in effective if s.key == "redis.enabled")
        assert row.value is True
        assert row.source == "database"

        await facade.write_setting(setting_key="cache.enabled", value=False, updated_by=9)
        await _process_ops_outbox(engine, registry)
        assert cache_enabled() is False

        await facade.write_setting(setting_key="cache.enabled", value=True, updated_by=9)
        await _process_ops_outbox(engine, registry)
        assert cache_enabled() is True
        effective = await facade.get_effective_settings()
        row = next(s for s in effective if s.key == "cache.enabled")
        assert row.value is True
        assert row.source == "database"
