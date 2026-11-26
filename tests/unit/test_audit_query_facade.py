"""PHASE-4 T6: the audit facade's operator query SQL (ticket #240).

Pins the filtered, paginated ``query_audit_events`` SELECT against a mocked
connection - the WHERE-clause building for each filter, ``timestamp`` DESC
ordering, offseth/limit paging, and the separate full-match ``total_count`` -
without a live database (coding-standards A2: DB-free unit surface).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from modules.audit.facade import AuditFacade, query_audit_events


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self):
        return self._rows


_NOW = datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC)

_ROW = {
    "id": uuid4(),
    "event_type": "consent.granted",
    "actor_id": uuid4(),
    "target_id": uuid4(),
    "scope": "consultations",
    "metadata": {"producer": "consent"},
    "timestamp": _NOW,
    "prev_hash": "0" * 64,
    "hash": "1" * 64,
}


def _execute_statement(result: list[dict[str, object]] | None = None):
    connection = AsyncMock()
    connection.scalar = AsyncMock(return_value=1)
    connection.execute = AsyncMock(return_value=_FakeResult(result if result is not None else []))
    return connection


async def test_unfiltered_query_selects_all_and_returns_page() -> None:
    connection = _execute_statement([_ROW])

    page = await query_audit_events(
        connection,
        actor_id=None,
        event_type=None,
        target_id=None,
        scope=None,
        from_ts=None,
        to_ts=None,
        page=1,
        page_size=20,
    )

    assert page.total_count == 1
    assert len(page.events) == 1
    assert page.events[0].event_type == "consent.granted"
    assert page.events[0].hash == _ROW["hash"]

    (select_stmt,) = connection.execute.await_args.args
    assert str(select_stmt).startswith("SELECT")
    # Unfiltered: no WHERE in the page statement.
    assert "WHERE" not in str(select_stmt)


async def test_each_filter_composes_its_where_clause() -> None:
    actor = uuid4()
    target = uuid4()
    from_ts = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    to_ts = datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC)
    connection = _execute_statement([])

    await query_audit_events(
        connection,
        actor_id=actor,
        event_type="consent.granted",
        target_id=target,
        scope="consultations",
        from_ts=from_ts,
        to_ts=to_ts,
        page=1,
        page_size=20,
    )

    (select_stmt,) = connection.execute.await_args.args
    sql = str(select_stmt)
    assert "audit_events.actor_id" in sql
    assert "audit_events.event_type" in sql
    assert "audit_events.target_id" in sql
    assert "audit_events.scope" in sql
    assert "audit_events.timestamp" in sql


async def test_results_ordered_most_recent_first() -> None:
    connection = _execute_statement([])

    await query_audit_events(
        connection,
        actor_id=None,
        event_type=None,
        target_id=None,
        scope=None,
        from_ts=None,
        to_ts=None,
        page=1,
        page_size=20,
    )

    (select_stmt,) = connection.execute.await_args.args
    assert "ORDER BY audit_events.timestamp DESC" in str(select_stmt).replace("audit.", "")


async def test_pagination_offsets_and_limits() -> None:
    connection = _execute_statement([])

    await query_audit_events(
        connection,
        actor_id=None,
        event_type=None,
        target_id=None,
        scope=None,
        from_ts=None,
        to_ts=None,
        page=2,
        page_size=10,
    )

    (select_stmt,) = connection.execute.await_args.args
    sql = str(select_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 10" in sql
    assert "OFFSET 10" in sql


async def test_total_count_comes_from_a_separate_count_query() -> None:
    connection = _execute_statement([])
    connection.scalar = AsyncMock(return_value=7)

    page = await query_audit_events(
        connection,
        actor_id=None,
        event_type=None,
        target_id=None,
        scope=None,
        from_ts=None,
        to_ts=None,
        page=1,
        page_size=20,
    )

    # The full-match count reflects all matching rows, not just the page.
    assert page.total_count == 7
    assert page.events == []


async def test_facade_query_audit_delegates_through_its_engine() -> None:
    connection = AsyncMock()
    connection.scalar = AsyncMock(return_value=0)
    connection.execute = AsyncMock(return_value=_FakeResult([]))
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    facade = AuditFacade(engine)
    page = await facade.query_audit(page=1, page_size=20)

    assert page.total_count == 0
    assert page.events == []


async def test_facade_query_partner_audit_filters_by_deterministic_target_id() -> None:
    from modules.audit.domain.consumer import _partner_uuid

    partner_id = 42
    expected_target = _partner_uuid(partner_id)

    connection = AsyncMock()
    connection.scalar = AsyncMock(return_value=1)
    connection.execute = AsyncMock(return_value=_FakeResult([_ROW]))
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    facade = AuditFacade(engine)
    page = await facade.query_partner_audit(partner_id)

    assert page.total_count == 1
    assert len(page.events) == 1
    (select_stmt,) = connection.execute.await_args.args
    sql = str(select_stmt.compile(compile_kwargs={"literal_binds": True}))
    compact = expected_target.replace("-", "").lower()
    assert f"'{compact}'" in sql.lower()
    assert "audit_events.target_id" in sql
