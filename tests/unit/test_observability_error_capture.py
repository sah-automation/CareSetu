"""B8 #726: the bounded in-process error-capture buffer.

The buffer is the whole latency argument of #726, so the properties under test are
the ones an unbounded or path-recording implementation would break: the ceiling is
real, the drop policy keeps the NEWEST failures, the route recorded is the matched
TEMPLATE rather than the concrete path, and the fingerprint collapses repeats
without depending on anything that changes between occurrences.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import Settings
from app.main import create_app
from observability.error_capture import (
    ERROR_KIND_SERVER_ERROR_RESPONSE,
    ERROR_KIND_UNHANDLED_EXCEPTION,
    STATUS_CLASS_CLIENT_ERROR,
    STATUS_CLASS_REDIRECT,
    STATUS_CLASS_SERVER_ERROR,
    STATUS_CLASS_SUCCESS,
    UNMATCHED_ROUTE_TEMPLATE,
    capture_server_error,
    configure_error_capture,
    discard_error_captures,
    dropped_error_captures,
    error_capture_capacity,
    fingerprint_for,
    pending_error_captures,
    route_template_for,
    status_class_for,
)

#: Every test in this module reads or writes the buffer, so all of them request the
#: reset rather than each re-declaring the ceiling and the teardown.
pytestmark = pytest.mark.usefixtures("clean_error_buffer")


def _request(path: str = "/v1/cases/912/entries", method: str = "POST") -> Request:
    """A request whose scope carries a matched route with that route's TEMPLATE."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "route": type("_Route", (), {"path": "/v1/cases/{case_id}/entries"})(),
    }
    return Request(scope)


def _capture(request: Request, *, status_code: int = 500, code: str = "INTERNAL_SERVER_ERROR"):
    return capture_server_error(
        request=request,
        status_code=status_code,
        kind=ERROR_KIND_UNHANDLED_EXCEPTION,
        code=code,
        trace_id="trace-abc123",
    )


def test_capture_records_the_route_template_never_the_concrete_path() -> None:
    """#726: a record must not carry the id in the path - that is the whole rule."""
    record = _capture(_request("/v1/cases/912/entries"))

    assert record is not None
    assert record.route_template == "/v1/cases/{case_id}/entries"
    assert "912" not in record.route_template
    assert route_template_for(_request("/v1/patients/77/records")) == (
        "/v1/cases/{case_id}/entries"
    )


def test_capture_falls_back_to_a_fixed_token_when_no_route_matched() -> None:
    """An exception raised before routing leaves only the path - which must not be used."""
    scope = {"type": "http", "method": "GET", "path": "/v1/patients/77/records", "headers": []}
    request = Request(scope)

    assert route_template_for(request) == UNMATCHED_ROUTE_TEMPLATE


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, STATUS_CLASS_SUCCESS),
        (301, STATUS_CLASS_REDIRECT),
        (404, STATUS_CLASS_CLIENT_ERROR),
        (422, STATUS_CLASS_CLIENT_ERROR),
        (500, STATUS_CLASS_SERVER_ERROR),
        (503, STATUS_CLASS_SERVER_ERROR),
    ],
)
def test_status_class_collapses_before_it_is_stored(status_code: int, expected: str) -> None:
    """#726: a route answering 500 and 503 is one series, not two."""
    assert status_class_for(status_code) == expected


def test_repeats_of_one_failure_share_a_fingerprint() -> None:
    """#726: identical failures collapse onto one entry rather than burying others."""
    first = _capture(_request("/v1/cases/1/entries"), code="INTERNAL_SERVER_ERROR")
    second = _capture(_request("/v1/cases/999/entries"), code="INTERNAL_SERVER_ERROR")

    assert first is not None and second is not None
    assert first.fingerprint == second.fingerprint


def test_a_different_route_or_status_or_kind_is_a_different_fingerprint() -> None:
    """A fingerprint that collapsed everything would hide the failure it merged."""
    base: dict[str, object] = {
        "route_template": "/v1/cases/{case_id}/entries",
        "method": "POST",
        "status_code": 500,
        "kind": ERROR_KIND_UNHANDLED_EXCEPTION,
        "code": "INTERNAL_SERVER_ERROR",
    }

    assert fingerprint_for(**base) != fingerprint_for(**{**base, "status_code": 503})
    assert fingerprint_for(**base) != fingerprint_for(**{**base, "method": "GET"})
    assert fingerprint_for(**base) != fingerprint_for(**{**base, "code": "SOMETHING_ELSE"})
    assert fingerprint_for(**base) != fingerprint_for(
        **{**base, "kind": ERROR_KIND_SERVER_ERROR_RESPONSE}
    )
    assert fingerprint_for(**base) != fingerprint_for(
        **{**base, "route_template": "/v1/cases/{case_id}"}
    )


def test_the_fingerprint_ignores_the_trace_id_and_the_clock() -> None:
    """#726: a fingerprint containing either collapses nothing and looks like it works."""
    before = datetime.now(UTC)
    first = _capture(_request("/v1/cases/1/entries"))
    second = _capture(_request("/v1/cases/2/entries"))
    after = datetime.now(UTC)

    assert first is not None and second is not None
    assert first.fingerprint == second.fingerprint
    # Both stamps are bounded by the window they were taken in, and the pair is
    # ordered - asserted separately rather than as the ``or`` of the two, which
    # would pass on either alone and prove nothing about the other.
    assert before <= first.occurred_at <= second.occurred_at <= after
    assert first.occurred_at != second.occurred_at


def test_a_client_supplied_trace_id_too_wide_for_the_column_is_clamped() -> None:
    """#726: an over-long trace id must not be able to wedge the drain.

    ``app.gateway.trace`` honours a client ``X-Request-Id`` only when it fits the
    shared rule in :mod:`observability.trace_ids` - printable, non-space and at
    most ``MAX_TRACE_ID_LENGTH`` (64) characters, which is the ``trace_id``
    column's width exactly. The capture clamps anyway, because the column is the
    last line of defence and a value that arrived by any other path (a log line,
    a background task) would still be too wide. Unclamped, one such header on one
    failing route writes a record whose upsert raises on length; the drain aborts
    the whole batch on that record, swallows the failure, and leaves it at the
    head of the buffer - so every subsequent pass fails too and error capture is
    silently dead until enough fresh errors evict it.
    """
    oversized = "t" * 128

    record = capture_server_error(
        request=_request("/v1/cases/912/entries"),
        status_code=500,
        kind=ERROR_KIND_UNHANDLED_EXCEPTION,
        code="INTERNAL_SERVER_ERROR",
        trace_id=oversized,
    )

    assert record is not None
    assert len(record.trace_id) == 64
    # Clamped, not rejected: correlation survives even when the tail does not.
    assert record.trace_id == oversized[:64]
    # And the clamp is invisible to the fingerprint, which never included it.
    assert record.fingerprint == fingerprint_for(
        route_template=record.route_template,
        method=record.method,
        status_code=500,
        kind=ERROR_KIND_UNHANDLED_EXCEPTION,
        code="INTERNAL_SERVER_ERROR",
    )


def test_a_record_carries_no_field_a_request_body_could_hide_in() -> None:
    """PHI-free by construction: there is nowhere to put a body, a query or a header."""
    record = _capture(_request("/v1/cases/912/entries?token=secret"))

    assert record is not None
    assert set(record.__slots__) == {
        "fingerprint",
        "route_template",
        "method",
        "status_code",
        "status_class",
        "kind",
        "code",
        "trace_id",
        "occurred_at",
    }


def test_the_buffer_is_bounded_and_drops_the_oldest_rather_than_growing() -> None:
    """#726: an unbounded buffer turns an error storm into an OOM kill."""
    configure_error_capture(3, enabled=True)
    request = _request()

    kept = [_capture(request) for _ in range(5)]

    # The first three fit; the last two displaced the two oldest.
    assert [record is not None for record in kept] == [True, True, True, False, False]
    assert len(pending_error_captures()) == 3
    assert dropped_error_captures() == 2
    assert error_capture_capacity() == 3


def test_shrinking_the_buffer_keeps_what_is_currently_failing() -> None:
    """A resize down applies the same policy an append to a full buffer does."""
    configure_error_capture(5, enabled=True)
    for offset in range(5):
        capture_server_error(
            request=_request(f"/v1/cases/{offset}/entries"),
            status_code=500 + offset,
            kind=ERROR_KIND_UNHANDLED_EXCEPTION,
            code="INTERNAL_SERVER_ERROR",
            trace_id="trace-abc123",
        )

    configure_error_capture(2, enabled=True)

    pending = pending_error_captures()
    assert [record.status_code for record in pending] == [503, 504]


def test_a_snapshot_does_not_consume_and_a_discard_releases_only_what_it_claims() -> None:
    """The drain writes a snapshot and releases it AFTER the commit; both halves matter."""
    configure_error_capture(10, enabled=True)
    for _ in range(3):
        _capture(_request())

    snapshot = pending_error_captures()
    assert len(snapshot) == 3
    assert len(pending_error_captures()) == 3

    assert discard_error_captures(snapshot[:2]) == 2
    assert len(pending_error_captures()) == 1

    assert discard_error_captures(()) == 0
    assert len(pending_error_captures()) == 1

    remaining = pending_error_captures()
    assert discard_error_captures(remaining) == 1
    assert pending_error_captures() == ()


def test_a_discard_releases_the_survivors_of_a_partial_turnover() -> None:
    """B8 #726: eviction can drop PART of the batch, leaving survivors to release.

    The snapshot is non-destructive, so newcomers arriving during the write append
    behind the drained batch and then evict from the FRONT. The buffer ends as
    ``[old2, old3, old4, new1, new2, new3]``: three of the four drained records
    survive with the newcomers behind them.

    A left-to-right identity scan starts by asking whether ``old1`` is still first -
    it is not - and so releases NOTHING, re-writing the three survivors forever and
    inflating ``occurrences`` permanently. Only the survivors may be released; the
    newcomers were never in the batch.
    """
    configure_error_capture(4, enabled=True)
    captured = [_capture(_request(f"/v1/cases/{offset}/entries")) for offset in range(4)]
    persisted = tuple(record for record in captured if record is not None)
    assert len(persisted) == 4

    # One newcomer against a ceiling of four evicts exactly the OLDEST of the batch,
    # leaving [p1, p2, p3, new]. The captures are read back off the buffer rather
    # than off ``_capture``'s return, which is ``None`` for a displaced record.
    _capture(_request("/v1/cases/90/entries"))
    (newcomer,) = pending_error_captures()[-1:]
    assert pending_error_captures() == (*persisted[1:], newcomer)

    assert discard_error_captures(persisted) == 3
    # The newcomer was never in the batch, so it must survive untouched.
    assert pending_error_captures() == (newcomer,)


def test_a_discard_of_a_fully_evicted_batch_releases_nothing() -> None:
    """B8 #726: a stale batch must not free records the write never persisted.

    The hardest case for identity matching: every record of the batch is gone, and
    the buffer now holds three captures the write never saw. A counted pop would
    free those three - silent loss during exactly the storm the bound exists for -
    while identity matching finds nothing of the batch and releases nothing.
    """
    configure_error_capture(10, enabled=True)
    captured = [_capture(_request(f"/v1/cases/{offset}/entries")) for offset in range(3)]
    persisted = tuple(record for record in captured if record is not None)

    # A ceiling small enough that the next three captures evict all three of the
    # batch, so the buffer holds only records the write never persisted.
    configure_error_capture(3, enabled=True)
    for _ in range(3):
        _capture(_request("/v1/cases/90/entries"))
    newcomers = pending_error_captures()
    assert len(newcomers) == 3
    assert not set(newcomers) & set(persisted)

    assert discard_error_captures(persisted) == 0
    assert pending_error_captures() == newcomers


def test_the_method_is_bounded_so_a_hostile_request_cannot_grow_a_record() -> None:
    """A record's cost must not depend on the request that produced it."""
    record = _capture(_request(method="X" * 64))

    assert record is not None
    assert len(record.method) == 10


def test_the_buffer_ceiling_floors_at_one_rather_than_disabling_capture() -> None:
    """A misconfigured ceiling of zero must not turn error capture off silently."""
    configure_error_capture(0, enabled=True)

    assert error_capture_capacity() == 1
    assert _capture(_request()) is not None


def test_configured_off_is_a_no_op_that_buffers_nothing() -> None:
    """#753: the gate off means the seam captures nothing, at any capacity."""
    configure_error_capture(10, enabled=False)

    assert _capture(_request()) is None
    assert pending_error_captures() == ()
    assert dropped_error_captures() == 0


# ------------------------------------------------- the gateway seams, at the app


def _failing_client(**settings: object) -> TestClient:
    """The real app with two routes that fail in the two different ways.

    ``raise_server_exceptions=False`` because Starlette's ``ServerErrorMiddleware``
    sends the envelope AND re-raises, so the test client would otherwise see the
    exception rather than the 500 a real client sees.
    """
    app = create_app(settings=Settings(**settings))  # type: ignore[arg-type]

    @app.get("/v1/cases/{case_id}/boom")
    def boom(case_id: str) -> None:
        raise RuntimeError(f"database unavailable for {case_id}")

    @app.get("/v1/cases/{case_id}/degraded")
    def degraded() -> JSONResponse:
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})

    @app.get("/v1/cases/{case_id}/fine")
    def fine() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app, raise_server_exceptions=False)


def test_an_escaped_exception_buffers_exactly_one_record_on_the_route_template() -> None:
    """#726: the catch-all seam captures what a handler never caught."""
    client = _failing_client()

    response = client.get("/v1/cases/912/boom", headers={"X-Request-Id": "trace-abc123"})

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
    (record,) = pending_error_captures()
    assert record.kind == ERROR_KIND_UNHANDLED_EXCEPTION
    assert record.route_template == "/v1/cases/{case_id}/boom"
    assert "912" not in record.route_template
    assert record.code == "INTERNAL_SERVER_ERROR"
    assert record.status_class == "5xx"
    assert record.trace_id == "trace-abc123"


def test_a_handled_5xx_is_also_captured_and_never_twice() -> None:
    """#726: a 5xx a handler produced itself is the half the exception seam cannot see."""
    client = _failing_client()

    response = client.get("/v1/cases/912/degraded")

    assert response.status_code == 503
    (record,) = pending_error_captures()
    assert record.kind == ERROR_KIND_SERVER_ERROR_RESPONSE
    assert record.status_code == 503
    assert record.route_template == "/v1/cases/{case_id}/degraded"


def test_a_healthy_request_buffers_nothing() -> None:
    """Capture that fires on success would turn the buffer into a request log."""
    client = _failing_client()

    assert client.get("/v1/cases/912/fine").status_code == 200

    assert pending_error_captures() == ()


def test_the_lifespan_arms_the_capture_when_the_gate_is_on() -> None:
    """#753: the composition root applies the gate, not just the buffer ceiling."""
    with _failing_client(error_capture_enabled=True) as client:
        response = client.get("/v1/cases/912/boom")

    assert response.status_code == 500
    (record,) = pending_error_captures()
    assert record.route_template == "/v1/cases/{case_id}/boom"


def test_a_disabled_gate_serves_the_error_without_capturing_it() -> None:
    """#753: gate off changes nothing the client sees; only the buffer stays empty.

    The whole point of the gate: a deployment that has not opted in behaves as
    if the capture seam did not exist - the 500 still answers the same way, and
    not one byte of record is built or buffered.
    """
    with _failing_client() as client:
        response = client.get("/v1/cases/912/boom")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
    assert pending_error_captures() == ()
