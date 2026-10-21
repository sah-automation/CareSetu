"""B8 #726: the error-buffer drain into the observability error stream (no DB).

The drain's contract is three things a unit test can prove and an integration test
should not have to: the upsert collapses on the fingerprint rather than appending,
the collapsed row's count and freshness move forward, and the buffer is released
only AFTER the write commits. The last one is the rule that keeps a crash mid-drain
a retry rather than a silent loss of the errors it was persisting.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import CompileError
from starlette.requests import Request

from modules.observability import error_stream
from modules.observability.error_stream import ErrorDrainReport, drain_error_captures
from modules.observability.facade import drain_error_buffer
from observability.error_capture import (
    ERROR_KIND_UNHANDLED_EXCEPTION,
    capture_server_error,
    configure_error_capture,
    pending_error_captures,
)

_TRACE_ID = "trace-abc123"


pytestmark = pytest.mark.usefixtures("clean_error_buffer")


def _capture(status_code: int = 500, *, case_id: str = "912") -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": f"/v1/cases/{case_id}/entries",
        "headers": [],
        "route": type("_Route", (), {"path": "/v1/cases/{case_id}/entries"})(),
    }
    capture_server_error(
        request=Request(scope),
        status_code=status_code,
        kind=ERROR_KIND_UNHANDLED_EXCEPTION,
        code="INTERNAL_SERVER_ERROR",
        trace_id=_TRACE_ID,
    )


def _sql(statement: Any) -> str:
    try:
        return str(
            statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
    except CompileError:
        return str(statement.compile(dialect=postgresql.dialect()))


class _RecordingConnection:
    """Records the SQL it is handed instead of executing it."""

    def __init__(self, *, fail: bool = False) -> None:
        self.statements: list[str] = []
        self._fail = fail

    async def execute(self, statement: Any) -> SimpleNamespace:
        self.statements.append(_sql(statement))
        if self._fail:
            raise RuntimeError("database unavailable")
        return SimpleNamespace(rowcount=1)


class _FakeBegin:
    """The context manager ``engine.begin()`` returns."""

    def __init__(self, connection: _RecordingConnection, engine: _FakeEngine) -> None:
        self._connection = connection
        self._engine = engine

    async def __aenter__(self) -> _RecordingConnection:
        return self._connection

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeEngine:
    """An engine whose ``begin()`` hands out one recording connection."""

    def __init__(self, connection: _RecordingConnection) -> None:
        self.connection = connection
        self.disposed = False

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self.connection, self)

    async def dispose(self) -> None:
        self.disposed = True


# ------------------------------------------------------------------ the upsert


def test_the_upsert_collapses_on_the_fingerprint_and_counts_the_repeat() -> None:
    """#726: one row per distinct failure, so a loop is a count and not a wall of rows."""
    connection = _RecordingConnection()
    _capture(500, case_id="1")

    asyncio.run(drain_error_captures(connection))  # type: ignore[arg-type]

    sql = connection.statements[0]
    assert "ON CONFLICT (fingerprint) DO UPDATE" in sql
    assert "observability.observability_error_events.occurrences +" in sql
    assert "last_seen_at" in sql
    # The first sighting's timestamp is NOT overwritten - it is the row's first
    # sighting precisely because it is absent from the update's SET list.
    assert "first_seen_at = " not in sql


def test_the_upsert_never_moves_a_sighting_backwards() -> None:
    """A retried batch must not roll a newer occurrence - and its trace id - backwards."""
    connection = _RecordingConnection()
    _capture(500)

    asyncio.run(drain_error_captures(connection))  # type: ignore[arg-type]

    sql = connection.statements[0]
    assert "WHERE" in sql and "excluded.last_seen_at >=" in sql


def test_a_repeat_batch_reports_records_written_and_distinct_failures() -> None:
    """Three identical failures are three OCCURRENCES on one frequency, not three rows."""
    connection = _RecordingConnection()
    for _ in range(3):
        _capture(500)
    _capture(503, case_id="77")

    report = asyncio.run(drain_error_captures(connection))  # type: ignore[arg-type]

    assert report == ErrorDrainReport(written=4, frequencies=2, dropped=0)
    assert len(connection.statements) == 4


def test_an_empty_buffer_writes_nothing_at_all() -> None:
    """A drain firing on a healthy system must not touch the database."""
    connection = _RecordingConnection()

    report = asyncio.run(drain_error_captures(connection))  # type: ignore[arg-type]

    assert report == ErrorDrainReport(written=0, frequencies=0, dropped=0)
    assert connection.statements == []


# ------------------------------------------------------------ the buffer handoff


def test_a_successful_drain_releases_exactly_what_it_persisted() -> None:
    """Post-commit release: the records the pass wrote are the records it gave back."""
    connection = _RecordingConnection()
    engine = _FakeEngine(connection)
    for _ in range(2):
        _capture(500)

    report = asyncio.run(drain_error_buffer(engine))  # type: ignore[arg-type]

    assert report.written == 2
    assert pending_error_captures() == ()


def test_a_failed_drain_leaves_the_records_buffered_for_the_next_pass() -> None:
    """The rule that turns a crash mid-drain into a retry rather than a silent loss."""
    engine = _FakeEngine(_RecordingConnection(fail=True))
    _capture(500)

    with pytest.raises(RuntimeError):
        asyncio.run(drain_error_buffer(engine))  # type: ignore[arg-type]

    assert len(pending_error_captures()) == 1


def test_an_empty_buffer_opens_no_transaction() -> None:
    """A healthy system must not hold a pooled connection to find nothing to report."""

    class _ExplodingEngine:
        def begin(self) -> Any:
            raise AssertionError("a drain with nothing buffered must not open a transaction")

    report = asyncio.run(drain_error_buffer(_ExplodingEngine()))  # type: ignore[arg-type]

    assert report == ErrorDrainReport(written=0, frequencies=0, dropped=0)


def test_discards_are_warned_about_once_per_growth_not_once_per_pass(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A storm discards on every pass; one line per interval would bury the failure.

    The count reported stays cumulative, so the line that does fire names the true
    total - the operator is told how bad it got, not how bad it got since lunch.
    """
    monkeypatch.setattr(error_stream, "_drops_last_reported", 0)
    engine = _FakeEngine(_RecordingConnection())

    # A ceiling of one record: a second capture in the same pass discards the first,
    # which is the storm this line exists to report. The middle pass fits in the
    # buffer and so discards nothing - the pass that must NOT re-warn.
    configure_error_capture(1, enabled=True)
    _capture(500)
    _capture(500)
    asyncio.run(drain_error_buffer(engine))  # type: ignore[arg-type]
    _capture(500)
    asyncio.run(drain_error_buffer(engine))  # type: ignore[arg-type]
    _capture(500)
    _capture(500)
    asyncio.run(drain_error_buffer(engine))  # type: ignore[arg-type]

    warnings = [record for record in caplog.records if "discarded" in record.message]
    # Two growths (1 then 2) across THREE passes - and each line names the cumulative
    # count, so the operator is told how bad it got, not how bad it got since lunch.
    assert len(warnings) == 2
    assert "discarded 1 capture(s)" in warnings[0].message
    assert "discarded 2 capture(s)" in warnings[1].message
    assert all("ceiling of 1" in record.message for record in warnings)


def test_a_reset_re_arms_the_discard_warning(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A buffer reset lowers the count; the line must not be silenced for good.

    The latch compares for CHANGE rather than for growth, so a fresh process (or the
    test fixture's reset) that discards once after an earlier count of five still
    reports it - a growth-only comparison would leave the operator permanently deaf.
    """
    monkeypatch.setattr(error_stream, "_drops_last_reported", 5)
    engine = _FakeEngine(_RecordingConnection())

    configure_error_capture(1, enabled=True)
    _capture(500)
    _capture(500)
    asyncio.run(drain_error_buffer(engine))  # type: ignore[arg-type]

    warnings = [record for record in caplog.records if "discarded" in record.message]
    assert len(warnings) == 1
    assert "discarded 1 capture(s)" in warnings[0].message


def test_the_captured_record_still_carries_the_trace_identifier() -> None:
    """#726: the trace id is what takes an operator from the feed to the trace."""
    _capture(500)

    (record,) = pending_error_captures()

    assert record.trace_id == _TRACE_ID
    assert record.status_class == "5xx"
    assert record.route_template == "/v1/cases/{case_id}/entries"
    assert isinstance(record.occurred_at, datetime)
    assert record.occurred_at.tzinfo is UTC
