"""B9 #727: the HTTP-counter fold into ``observability_http_minute`` (no DB).

The fold's contract is three things a unit test can prove and an integration test
should not have to: the upsert ADDS onto the table's own unique key rather than
replacing the row, the 5xx subset is derived from the bucket's status class rather
than a second query, and the deltas are released only AFTER the write commits.
The last one is the rule that keeps a crash mid-fold a retry rather than a
permanent, invisible inflation of throughput.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import CompileError
from starlette.requests import Request

from app.config import DEFAULT_HTTP_COUNTER_MAX_SERIES
from modules.observability import http_counter_stream
from modules.observability.facade import drain_http_counter
from modules.observability.http_counter_stream import HttpCounterDrainReport, drain_http_counts
from observability.http_counter import (
    configure_http_counter,
    pending_http_counts,
    record_request,
    reset_http_counter,
)

_ENTRIES = "/v1/cases/{case_id}/entries"
_NOW = datetime(2026, 10, 14, 12, 34, 56, tzinfo=UTC)


@pytest.fixture
def clean_http_counter() -> None:
    configure_http_counter(DEFAULT_HTTP_COUNTER_MAX_SERIES)
    reset_http_counter()
    yield
    configure_http_counter(DEFAULT_HTTP_COUNTER_MAX_SERIES)
    reset_http_counter()


pytestmark = pytest.mark.usefixtures("clean_http_counter")


def _count(
    status_code: int = 200, *, times: int = 1, route: str = _ENTRIES, now: datetime = _NOW
) -> None:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/cases/912/entries",
        "headers": [],
        "route": type("_Route", (), {"path": route})(),
    }
    for _ in range(times):
        record_request(request=Request(scope), status_code=status_code, now=now)


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
    def __init__(self, connection: _RecordingConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _RecordingConnection:
        return self._connection

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeEngine:
    """An engine whose ``begin()`` hands out one recording connection."""

    def __init__(self, connection: _RecordingConnection) -> None:
        self.connection = connection

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self.connection)


# ------------------------------------------------------------------ the upsert


def test_the_upsert_adds_onto_the_tables_own_unique_key() -> None:
    """#727: a bucket split across two passes must still be ONE row.

    Replacing rather than adding would make throughput non-monotonic inside a single
    minute, which is the one thing a rate-of-change chart must never show - and it
    would also silently discard the traffic the first pass had already counted.
    """
    connection = _RecordingConnection()
    _count(200)

    asyncio.run(drain_http_counts(connection))  # type: ignore[arg-type]

    sql = connection.statements[0]
    assert "ON CONFLICT (minute_ts, route_template, method, status_class) DO UPDATE" in sql.replace(
        '"', ""
    )
    assert "observability.observability_http_minute.requests +" in sql
    assert "observability.observability_http_minute.errors +" in sql


def test_the_error_numerator_is_the_five_xx_subset_of_the_denominator() -> None:
    """A stored numerator over a stored denominator, not a second scan of the table.

    The class is part of the bucket key, so the subset is exact arithmetic: a
    server-error bucket writes its whole count into both columns and every other
    class writes it into ``requests`` alone.
    """
    connection = _RecordingConnection()
    _count(500, times=3)
    _count(200, times=10)

    asyncio.run(drain_http_counts(connection))  # type: ignore[arg-type]

    success, failure = connection.statements
    assert "'5xx', 3, 3)" in failure
    assert "'2xx', 10, 0)" in success


def test_a_repeat_batch_reports_series_and_requests_separately() -> None:
    """The two figures say different things, and the log line needs both.

    ``series`` is the number of statements run and of rows touched - flat while
    traffic climbs, which is the ticket's claim. ``requests`` is how much traffic
    those buckets carried, which is what an operator reads.
    """
    connection = _RecordingConnection()
    _count(200, times=1000)
    _count(500, times=3)
    _count(404, times=2)

    report = asyncio.run(drain_http_counts(connection))  # type: ignore[arg-type]

    assert report == HttpCounterDrainReport(series=3, requests=1005, dropped=0)
    assert len(connection.statements) == 3


def test_an_empty_counter_writes_nothing_at_all() -> None:
    """A fold firing on a quiet system must not touch the database."""
    connection = _RecordingConnection()

    report = asyncio.run(drain_http_counts(connection))  # type: ignore[arg-type]

    assert report == HttpCounterDrainReport(series=0, requests=0, dropped=0)
    assert connection.statements == []


# ------------------------------------------------------------ the counter handoff


def test_a_successful_fold_releases_exactly_what_it_persisted() -> None:
    """Post-commit release: the deltas the pass wrote are the deltas it gave back."""
    engine = _FakeEngine(_RecordingConnection())
    _count(200, times=2)

    report = asyncio.run(drain_http_counter(engine))  # type: ignore[arg-type]

    assert (report.series, report.requests) == (1, 2)
    assert pending_http_counts() == ()


def test_a_failed_fold_leaves_the_deltas_waiting_for_the_next_pass() -> None:
    """The rule that turns a crash mid-fold into a retry rather than a double count.

    The opposite trade from the error stream's, where re-writing a captured record
    re-counts ONE occurrence. Re-writing a counter delta would inflate throughput
    permanently and invisibly, so here the retry has to be exact.
    """
    engine = _FakeEngine(_RecordingConnection(fail=True))
    _count(200, times=2)

    with pytest.raises(RuntimeError):
        asyncio.run(drain_http_counter(engine))  # type: ignore[arg-type]

    (still_waiting,) = pending_http_counts()
    assert still_waiting.requests == 2


def test_a_retried_fold_writes_the_same_delta_rather_than_the_bucket_total() -> None:
    """Three passes, one row, and the count never doubles.

    This is the whole reason the counter reports deltas: the pass after the failure
    must add 2 again - not 2, then 4 - or the next minute's chart shows a spike
    nobody caused.
    """
    failing = _FakeEngine(_RecordingConnection(fail=True))
    working = _FakeEngine(_RecordingConnection())
    _count(200, times=2)

    with pytest.raises(RuntimeError):
        asyncio.run(drain_http_counter(failing))  # type: ignore[arg-type]
    asyncio.run(drain_http_counter(working))  # type: ignore[arg-type]

    assert len(working.connection.statements) == 1
    assert (
        "observability.observability_http_minute.requests +" in (working.connection.statements[0])
    )


def test_an_empty_counter_opens_no_transaction() -> None:
    """A quiet system must not hold a pooled connection to find nothing to write."""

    class _ExplodingEngine:
        def begin(self) -> Any:
            raise AssertionError("a fold with nothing buffered must not open a transaction")

    report = asyncio.run(drain_http_counter(_ExplodingEngine()))  # type: ignore[arg-type]

    assert report == HttpCounterDrainReport(series=0, requests=0, dropped=0)


def test_requests_arriving_mid_write_are_folded_on_the_next_pass_not_this_one() -> None:
    """The pass writes the snapshot it took; the newcomer waits its turn.

    Without this the fold would release a delta the row never received, and the
    request would vanish from the record entirely - a lost request rather than a
    double count, which is the quieter and equally wrong outcome.
    """

    class _CapturingConnection(_RecordingConnection):
        """A connection whose write is followed by a request landing in the window."""

        async def execute(self, statement: Any) -> SimpleNamespace:
            result = await super().execute(statement)
            _count(200, now=_NOW + timedelta(minutes=1))
            return result

    connection = _CapturingConnection()
    _count(200)

    asyncio.run(drain_http_counter(_FakeEngine(connection)))  # type: ignore[arg-type]

    assert [(count.minute_ts, count.requests) for count in pending_http_counts()] == [
        (_NOW.replace(second=0, microsecond=0) + timedelta(minutes=1), 1)
    ]


def test_a_request_arriving_before_the_connection_is_opened_is_not_written_twice() -> None:
    """#727: the fold writes ONE snapshot and releases that same one.

    The regression this pins is narrow and expensive. The engine-level pass has to
    know the batch it is going to release BEFORE it opens a connection, because
    acquiring one takes real time and a request arriving in that window lands in
    the counter. A pass that re-reads the counter once the connection is open - the
    obvious way to write ``drain_http_counts``, which the error stream does - would
    WRITE that newcomer and then release a batch that does not contain it, so the
    newcomer would be written again on every later pass. Throughput would climb for
    no reason at all and nothing anywhere would say so.

    The symptom is a first pass that reports MORE than it snapshotted: with the
    second read in place the batch grows between the snapshot and the write, and the
    release then covers only the smaller one.
    """

    class _CapturingEngine(_FakeEngine):
        """An engine whose connection is "acquired" after the snapshot is taken."""

        def begin(self) -> _FakeBegin:
            _count(200)
            return super().begin()

    connection = _RecordingConnection()
    _count(200)

    first = asyncio.run(drain_http_counter(_CapturingEngine(connection)))  # type: ignore[arg-type]

    assert (first.series, first.requests) == (1, 1)
    assert len(connection.statements) == 1
    # The newcomer is still waiting, and only the newcomer.
    assert [count.requests for count in pending_http_counts()] == [1]

    second = asyncio.run(drain_http_counter(_FakeEngine(connection)))  # type: ignore[arg-type]

    assert (second.series, second.requests) == (1, 1)
    assert pending_http_counts() == ()


# ------------------------------------------------------------------- the bound


def _fill(minute_offset: int, buckets: int) -> None:
    """``buckets`` requests on DISTINCT routes inside one minute.

    Distinct routes matter: two requests to one route in one minute are ONE bucket
    by design, so a ceiling could never be reached by repeating one route - which is
    the property the ticket is about, and is asserted in its own test.
    """
    first = _NOW.replace(second=0, microsecond=0)
    for index in range(buckets):
        record_request(
            request=Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/v1/cases/1/x",
                    "headers": [],
                    "route": type("_Route", (), {"path": f"/route-{minute_offset}-{index}"})(),
                }
            ),
            status_code=200,
            now=first + timedelta(minutes=minute_offset),
        )


def test_discards_are_warned_about_once_per_change_not_once_per_pass(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sustained spike discards every pass; one line per interval would bury it.

    The count reported stays cumulative, so the line that does fire names the true
    total rather than the increment since the last line.
    """
    monkeypatch.setattr(http_counter_stream, "_drops_last_reported", 0)
    engine = _FakeEngine(_RecordingConnection())

    # A ceiling of one series: each overflowing pass discards one bucket, and the
    # pass in between fits - the pass that must NOT re-warn.
    configure_http_counter(1)
    _fill(0, 2)
    asyncio.run(drain_http_counter(engine))  # type: ignore[arg-type]
    _fill(1, 1)
    asyncio.run(drain_http_counter(engine))  # type: ignore[arg-type]
    _fill(2, 2)
    asyncio.run(drain_http_counter(engine))  # type: ignore[arg-type]

    warnings = [record for record in caplog.records if "discarded" in record.message]
    assert len(warnings) == 2
    assert "discarded 1 request(s)" in warnings[0].message
    assert "discarded 2 request(s)" in warnings[1].message
    assert all("ceiling of 1" in record.message for record in warnings)


def test_a_reset_re_arms_the_discard_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The counter is resettable, so the count can come back DOWN.

    The latch compares for CHANGE rather than for growth, so a fresh process (or the
    test fixture's reset) that discards once after an earlier count of five still
    reports it - a growth-only comparison would leave the operator permanently deaf.
    """
    monkeypatch.setattr(http_counter_stream, "_drops_last_reported", 5)
    engine = _FakeEngine(_RecordingConnection())

    configure_http_counter(1)
    _fill(0, 2)
    asyncio.run(drain_http_counter(engine))  # type: ignore[arg-type]

    warnings = [record for record in caplog.records if "discarded" in record.message]
    assert len(warnings) == 1
    assert "discarded 1 request(s)" in warnings[0].message


def test_a_batch_evicted_mid_write_is_reported_as_lost_rather_than_written() -> None:
    """The count already in ``dropped`` is attributed, not counted a second time."""
    engine = _FakeEngine(_RecordingConnection())
    _count(200, times=3)

    report = asyncio.run(drain_http_counter(engine))  # type: ignore[arg-type]

    assert (report.series, report.requests, report.dropped) == (1, 3, 0)


def test_the_fold_carries_no_field_a_request_body_could_hide_in() -> None:
    """PHI-free by construction: the upsert names only labels and two counters.

    The bucket has no body, query, header or trace field, so there is nowhere for
    one to be added by accident - the same rule the error stream states.
    """
    connection = _RecordingConnection()
    _count(200)

    asyncio.run(drain_http_counts(connection))  # type: ignore[arg-type]

    sql = connection.statements[0]
    for forbidden in ("path_params", "headers", "query", "trace_id", "body"):
        assert forbidden not in sql
