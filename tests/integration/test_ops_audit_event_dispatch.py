"""Integration: an ops settings write drains through the dispatcher (issue #945).

The bug: ops wrote ``audit.event`` rows into ``ops.ops_outbox`` as raw dicts,
and the audit carrier only accepted the consent lifecycle shape - so the
dispatcher failed reconstruction on every ops row and (before #944's reclaim
loop) left them inflight forever. This test writes a REAL setting through
``OpsFacade`` (the shared transactional outbox writer, typed envelope), runs
one dispatcher pass over the ops outbox with the real audit + observability
consumers registered, and asserts the row is reconstructed and drained with no
validation error. It also pins the two semantic rules of the widened carrier:
the ops act is NOT appended to the audit hash chain (operational by default),
and the observability telemetry mirror still counts it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from bus.dispatcher import (
    DEFAULT_DISPATCHER_CONFIG,
    discover_outbox_tables,
    process_outbox_table,
)
from bus.events import EVENT_AUDIT_EVENT
from bus.registry import HandlerRegistry
from modules.audit.schema.models import audit_events
from modules.observability.schema.models import observability_business_daily
from modules.ops.facade import OpsFacade
from modules.ops.schema.models import ops_outbox


@pytest.fixture(autouse=True)
async def _reset_ops_settings(engine: AsyncEngine) -> AsyncIterator[None]:
    """Truncate the ops setting tables; ``clean_tables`` only clears outboxes."""
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE ops.ops_setting_history, ops.ops_settings RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def facade(engine: AsyncEngine) -> OpsFacade:
    return OpsFacade(engine=engine, settings=Settings())


@pytest.fixture
def registry() -> HandlerRegistry:
    from modules.audit.adapters import register_handlers as audit_register_handlers
    from modules.observability.adapters import register_handlers as obs_register_handlers
    from modules.ops.adapters import register_handlers as ops_register_handlers

    registry = HandlerRegistry()
    ops_register_handlers(registry)
    audit_register_handlers(registry)
    obs_register_handlers(registry)
    return registry


class TestOpsAuditEventDrains:
    async def test_ops_setting_write_is_reconstructed_and_drained(
        self, facade: OpsFacade, engine: AsyncEngine, registry: HandlerRegistry
    ) -> None:
        async with engine.connect() as connection:
            audit_rows_before = (
                await connection.execute(select(func.count()).select_from(audit_events))
            ).scalar_one()
            audit_metric_before = (
                (
                    await connection.execute(
                        select(observability_business_daily.c.value).where(
                            observability_business_daily.c.metric_key == EVENT_AUDIT_EVENT
                        )
                    )
                )
                .scalars()
                .all()
            )

        result = await facade.write_setting(
            setting_key="ai.timeout_seconds",
            value=15,
            updated_by=7,
        )
        assert result == {"setting_key": "ai.timeout_seconds", "value": 15, "version": 1}

        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        select(ops_outbox).where(ops_outbox.c.event_type == EVENT_AUDIT_EVENT)
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        assert rows[0]["payload"]["action"] == "setting.write"
        assert rows[0]["payload"]["setting_key"] == "ai.timeout_seconds"
        assert rows[0]["payload"]["version"] == 1
        assert rows[0]["occurred_at"] is not None
        assert rows[0]["status"] == "pending"

        # One dispatcher pass over the ops outbox: the row reconstructs through
        # the widened carrier, fans out to both subscribers, and is deleted.
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("ops",))
        assert len(tables) == 1
        poll = await process_outbox_table(engine, tables[0], registry, DEFAULT_DISPATCHER_CONFIG)
        assert poll.claimed == 1
        assert poll.fanned_out == 1
        assert poll.deleted == 1

        async with engine.connect() as connection:
            remaining = (
                await connection.execute(select(func.count()).select_from(ops_outbox))
            ).scalar_one()
            audit_rows_after = (
                await connection.execute(select(func.count()).select_from(audit_events))
            ).scalar_one()
            metric_values = (
                (
                    await connection.execute(
                        select(observability_business_daily.c.value).where(
                            observability_business_daily.c.metric_key == EVENT_AUDIT_EVENT
                        )
                    )
                )
                .scalars()
                .all()
            )
            dead_letters = (
                await connection.execute(
                    select(func.count())
                    .select_from(ops_outbox)
                    .where(ops_outbox.c.status == "dead_letter")
                )
            ).scalar_one()

        # Drained, no dead letter, no validation error left behind.
        assert remaining == 0
        assert dead_letters == 0

        # The ops act is operational by default: consumed, never hash-chained.
        assert audit_rows_after == audit_rows_before

        # The telemetry mirror accepted the ops carrier and counted it.
        total = sum(int(value["count"]) for value in metric_values) - sum(
            int(value["count"]) for value in audit_metric_before
        )
        assert total == 1
