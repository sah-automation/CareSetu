"""B9 #727: the in-process per-minute HTTP counter (no DB).

The counter is where the ticket's headline rule lives - one row per route per
MINUTE rather than one write per request - and a test that makes three requests
cannot tell the difference between a design that aggregates and one that buffers a
record each. So the tests below assert the shape directly: ``pending()`` reports
one delta per bucket no matter how many requests filled it, the status is collapsed
before the key is built, and a route that took a thousand requests has still cost a
single series.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import (
    DEFAULT_HTTP_COUNTER_DRAIN_INTERVAL_SECONDS,
    DEFAULT_HTTP_COUNTER_MAX_SERIES,
    Settings,
)
from app.main import create_app
from observability.error_capture import (
    STATUS_CLASS_CLIENT_ERROR,
    STATUS_CLASS_SERVER_ERROR,
    STATUS_CLASS_SUCCESS,
    UNMATCHED_ROUTE_TEMPLATE,
)
from observability.http_counter import (
    MinuteCount,
    configure_http_counter,
    dropped_http_requests,
    flush_http_counts,
    http_counter_capacity,
    minute_bucket,
    pending_http_counts,
    record_request,
    reset_http_counter,
)

_ENTRIES = "/v1/cases/{case_id}/entries"

#: One fixed instant so every bucket in a test lands in the same minute. Taken from
#: a date the suite does not otherwise use, so a stale pinned-clock bug shows up as
#: a bucket in the wrong minute rather than as today's bucket.
_NOW = datetime(2026, 10, 14, 12, 34, 56, tzinfo=UTC)

#: Every test in this module reads or writes the counter, so all of them request the
#: reset rather than each re-declaring the ceiling and the teardown.
pytestmark = pytest.mark.usefixtures("clean_http_counter")


@pytest.fixture
def clean_http_counter() -> Iterator[None]:
    """The process-global counter, empty and at its default ceiling.

    Requested rather than autouse for the reason ``clean_error_buffer`` is: it is
    module-level state shared by every test in the process, and an autouse fixture
    would reconfigure a module singleton for tests that never touch it.

    The ceiling is restored explicitly rather than left to
    :func:`reset_http_counter`, which deliberately KEEPS the current size - that is
    what makes it the production/test seam - so a test that shrinks the map would
    otherwise leave every test after it running against a one-series ceiling.
    """
    configure_http_counter(DEFAULT_HTTP_COUNTER_MAX_SERIES)
    reset_http_counter()
    yield
    configure_http_counter(DEFAULT_HTTP_COUNTER_MAX_SERIES)
    reset_http_counter()


def _request(path: str = "/v1/cases/912/entries", method: str = "POST") -> Request:
    """A request whose scope carries a matched route with that route's TEMPLATE."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "route": type("_Route", (), {"path": _ENTRIES})(),
    }
    return Request(scope)


def _count(
    status_code: int = 200,
    *,
    path: str = "/v1/cases/912/entries",
    method: str = "POST",
    now: datetime | None = None,
) -> None:
    record_request(
        request=_request(path, method), status_code=status_code, now=now if now else _NOW
    )


# ------------------------------------------------------- the grain, not the request


def test_a_thousand_requests_to_one_route_cost_one_series() -> None:
    """#727: this is the whole ticket - the write cost is per bucket, never per request.

    A per-request capture would report a thousand deltas here and the drain would
    run a thousand upserts. The assertion is on the SHAPE of what is pending, so it
    fails on the design rather than on a row count that only shows up under load.
    """
    for _ in range(1000):
        _count(200)

    (pending,) = pending_http_counts()

    assert pending.requests == 1000
    assert pending.route_template == _ENTRIES
    assert pending.method == "POST"
    assert pending.status_class == STATUS_CLASS_SUCCESS
    assert pending.minute_ts == _NOW.replace(second=0)


def test_the_bucket_is_the_minute_the_request_arrived_in() -> None:
    """Two minutes are two buckets; the same minute twice is one."""
    _count(200, now=_NOW)
    _count(200, now=_NOW + timedelta(minutes=1))
    _count(200, now=_NOW + timedelta(minutes=1))

    buckets = {(count.minute_ts, count.requests) for count in pending_http_counts()}

    assert buckets == {
        (_NOW.replace(second=0, microsecond=0), 1),
        (_NOW.replace(second=0, microsecond=0) + timedelta(minutes=1), 2),
    }


def test_the_minute_is_truncated_so_a_bucket_cannot_span_two_minutes() -> None:
    """Seconds and microseconds dropped, so one bucket is exactly one minute wide."""
    assert minute_bucket(datetime(2026, 10, 14, 12, 34, 56, 789_123, tzinfo=UTC)) == datetime(
        2026, 10, 14, 12, 34, tzinfo=UTC
    )


def test_pending_reports_deltas_not_occurrences() -> None:
    """What a drain writes is the INCREMENT, never the bucket's lifetime total.

    The distinction is what makes a retried pass exact. A snapshot that reported
    the total would double-count the whole bucket every time the fold was retried,
    inflating throughput permanently and invisibly.
    """
    _count(200)
    _count(200)
    (first,) = pending_http_counts()
    flush_http_counts([first])

    assert pending_http_counts() == ()

    _count(200)
    (again,) = pending_http_counts()

    assert again.requests == 1


# ------------------------------------------------------------- the collapsed label


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(200, STATUS_CLASS_SUCCESS), (302, "3xx"), (404, STATUS_CLASS_CLIENT_ERROR), (503, "5xx")],
)
def test_the_status_class_is_collapsed_before_it_is_stored(status_code: int, expected: str) -> None:
    """#727: 500 and 503 on one route are one bucket, not two series.

    The cardinality firewall is decision 37's job and this is where the application
    half of it lives - one taxonomy, borrowed from the error capture rather than
    restated, so the counter and the feed can never disagree about what a 503 is.
    """
    _count(status_code)

    (pending,) = pending_http_counts()

    assert pending.status_class == expected


def test_two_codes_in_one_class_share_the_bucket() -> None:
    _count(500)
    _count(503)

    (pending,) = pending_http_counts()

    assert pending.requests == 2
    assert pending.status_class == STATUS_CLASS_SERVER_ERROR


def test_the_recorded_route_is_the_template_never_the_concrete_path() -> None:
    """#727: a patient's id in a telemetry label is both a leak and unbounded cardinality."""
    _count(200, path="/v1/cases/912/entries")

    (pending,) = pending_http_counts()

    assert pending.route_template == _ENTRIES
    assert "912" not in pending.route_template


def test_an_unmatched_route_falls_back_to_the_fixed_token() -> None:
    """The raw path is all that is available before routing, so it must not be used."""
    scope = {"type": "http", "method": "GET", "path": "/v1/patients/77/records", "headers": []}

    record_request(request=Request(scope), status_code=404, now=_NOW)

    (pending,) = pending_http_counts()

    assert pending.route_template == UNMATCHED_ROUTE_TEMPLATE
    assert "77" not in pending.route_template


def test_record_request_hands_back_the_class_it_stored() -> None:
    """The caller gets the collapsed class so no capture site recomputes it."""
    stored = record_request(request=_request(), status_code=503, now=_NOW)

    assert stored == STATUS_CLASS_SERVER_ERROR
    assert pending_http_counts()[0].status_class == stored


def test_the_method_is_bounded_so_a_hostile_request_cannot_grow_a_series() -> None:
    """A method is a fixed HTTP token in practice; the column is ten characters."""
    record_request(request=_request(method="M" * 200), status_code=200, now=_NOW)

    (pending,) = pending_http_counts()

    assert pending.method == "M" * 10


# ------------------------------------------------------------------ the bound


def test_the_map_drops_the_OLDEST_MINUTE_rather_than_one_of_its_buckets() -> None:
    """A traffic spike must not be an out-of-memory kill, and a partial minute is worse.

    A whole minute goes, not one arbitrary bucket: a minute that kept three of its
    four routes would report a count that silently disagrees with the requests that
    made it - a row that looks like data and is not. An absent minute at least reads
    as missing.
    """
    configure_http_counter(3)
    first = _NOW.replace(second=0, microsecond=0)
    # Minute one takes TWO buckets (two routes), then two more minutes take one each.
    _count(200, path="/v1/cases/1/entries", now=first)
    _count(200, path="/v1/cases/2/entries", now=first)
    _count(200, path="/v1/cases/3/entries", now=first + timedelta(minutes=1))
    _count(200, path="/v1/cases/4/entries", now=first + timedelta(minutes=2))
    # At the ceiling, so the new bucket evicts - and the eviction is minute-shaped.
    _count(200, path="/v1/cases/5/entries", now=first + timedelta(minutes=3))

    minutes = sorted({count.minute_ts for count in pending_http_counts()})

    assert minutes == [
        first + timedelta(minutes=1),
        first + timedelta(minutes=2),
        first + timedelta(minutes=3),
    ]
    # Both buckets of minute one went with it, and both requests are counted lost.
    assert dropped_http_requests() == 2


def test_the_ceiling_spends_itself_on_minutes_that_already_look_quiet() -> None:
    """A steady route keeps one series while the clock moves, not one per minute."""
    configure_http_counter(3)
    first = _NOW.replace(second=0, microsecond=0)
    for index in range(10):
        _count(200, now=first + timedelta(minutes=index))

    assert dropped_http_requests() > 0
    assert len(pending_http_counts()) <= 3


def test_the_ceiling_is_on_series_not_on_requests() -> None:
    """A thousand requests are one series, so a thousand requests never hit the bound."""
    configure_http_counter(1)
    for _ in range(1000):
        _count(200)

    assert len(pending_http_counts()) == 1
    assert dropped_http_requests() == 0


def test_a_bucket_that_has_been_folded_is_not_dropped_and_costs_no_ceiling() -> None:
    """The row is durable in Postgres, so the key has done its job."""
    configure_http_counter(1)
    _count(200, now=_NOW)
    (first,) = pending_http_counts()
    flush_http_counts([first])

    _count(200, now=_NOW + timedelta(minutes=5))

    assert dropped_http_requests() == 0
    assert len(pending_http_counts()) == 1


def test_a_bucket_that_gained_requests_mid_write_releases_only_what_was_written() -> None:
    """#727: the retry has to be exact or throughput inflates without anyone noticing.

    The release is matched on the DELTA, so a request that arrived while the write
    was open keeps its own increment waiting for the next pass instead of being
    surrendered against a row that never received it.
    """
    _count(200)
    (snapshot,) = pending_http_counts()
    _count(200)
    flush_http_counts([snapshot])

    (still_waiting,) = pending_http_counts()

    assert still_waiting.requests == 1


def test_a_snapshot_does_not_consume_and_the_release_is_idempotent() -> None:
    _count(200)
    (snapshot,) = pending_http_counts()

    assert pending_http_counts() == (snapshot,)
    flush_http_counts([snapshot])
    flush_http_counts([snapshot])

    assert pending_http_counts() == ()


def test_an_empty_release_is_a_no_op() -> None:
    assert flush_http_counts([]) == 0


def test_the_ceiling_floors_at_one_rather_than_disabling_capture() -> None:
    """A misconfigured ceiling of zero must not turn the counter off silently."""
    configure_http_counter(0)

    assert http_counter_capacity() == 1
    _count(200)

    assert len(pending_http_counts()) == 1


def test_the_reset_clears_the_counts_and_the_drop_count_but_keeps_the_ceiling() -> None:
    """The seam between production and the suites, exactly as the error buffer's."""
    configure_http_counter(1)
    _count(200, now=_NOW)
    _count(200, now=_NOW + timedelta(minutes=1))

    reset_http_counter()

    assert pending_http_counts() == ()
    assert dropped_http_requests() == 0
    assert http_counter_capacity() == 1


def test_pending_is_ordered_so_two_reads_of_the_same_state_agree() -> None:
    """A reproducible report is what makes a drain's log line comparable between passes."""
    _count(200, now=_NOW + timedelta(minutes=1))
    _count(503, now=_NOW)
    _count(404, now=_NOW)

    first = [
        (count.minute_ts, count.route_template, count.status_class)
        for count in pending_http_counts()
    ]
    second = [
        (count.minute_ts, count.route_template, count.status_class)
        for count in pending_http_counts()
    ]

    assert first == second == sorted(first)


# --------------------------------------------------- the seam inside the real app
#
# These three drive the real ASGI application rather than a synthetic scope. Only
# the real router proves the counter reads the MATCHED route template, and only the
# real stack proves where the counting middleware sits relative to the gateway.
# ``raise_server_exceptions=False`` because Starlette's ``ServerErrorMiddleware``
# sends the envelope AND re-raises, so the client would otherwise see the exception
# rather than the 500 a real client sees.


def _app_client(**settings: object) -> TestClient:
    """The real app with three extra routes, and no lifespan (nothing here needs one)."""
    app = create_app(settings=Settings(**settings))  # type: ignore[arg-type]

    @app.get("/v1/cases/{case_id}/entries/fine")
    def fine() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/cases/{case_id}/entries/boom")
    def boom(case_id: str) -> None:
        raise RuntimeError(f"database unavailable for {case_id}")

    @app.get("/v1/cases/{case_id}/entries/unavailable")
    def unavailable() -> JSONResponse:
        """A handler that gives up by itself - the half the catch-all cannot see."""
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})

    @app.get("/v1/cases/{case_id}/entries/both-ways")
    def both_ways() -> JSONResponse:
        """Raises on the first call, gives up by itself on the second.

        One route reached by BOTH capture seams, so a test can prove they do not
        double count and that the collapsed class puts both in one bucket.
        """
        both_ways.calls += 1  # type: ignore[attr-defined]
        if both_ways.calls == 1:
            raise RuntimeError("the dependency went away mid-request")
        return JSONResponse(status_code=503, content={"code": "SERVICE_UNAVAILABLE"})

    both_ways.calls = 0  # type: ignore[attr-defined]

    return TestClient(app, raise_server_exceptions=False)


def _buckets_for(suffix: str) -> list[MinuteCount]:
    return [count for count in pending_http_counts() if count.route_template.endswith(suffix)]


def test_an_answered_request_is_counted_once_on_its_route_template() -> None:
    """The middleware has to see the MATCHED route, which only exists after routing.

    A concrete path here would put a patient id into a telemetry label and make the
    label set unbounded, which is the same defect decision 13 rules out for the
    error stream and the reason the extractor is borrowed rather than written again.
    """
    client = _app_client()

    assert client.get("/v1/cases/912/entries/fine").status_code == 200

    (pending,) = _buckets_for("/fine")
    assert pending.route_template == "/v1/cases/{case_id}/entries/fine"
    assert "912" not in pending.route_template
    assert pending.method == "GET"
    assert pending.status_class == STATUS_CLASS_SUCCESS
    assert pending.requests == 1


def test_an_escaped_exception_is_counted_by_the_catch_all_seam() -> None:
    """#727: the requests that failed worst must not be the ones missing from throughput.

    Starlette answers an escaped exception from ``ServerErrorMiddleware``, outside
    all user middleware, so the counting middleware never sees it. Counting only
    there would report a healthy system during a crash loop - the exact answer this
    ticket exists to make impossible.
    """
    client = _app_client()

    assert client.get("/v1/cases/912/entries/boom").status_code == 500

    (pending,) = _buckets_for("/boom")
    assert pending.route_template == "/v1/cases/{case_id}/entries/boom"
    assert "912" not in pending.route_template
    assert pending.status_class == STATUS_CLASS_SERVER_ERROR
    assert pending.requests == 1


def test_a_handler_produced_failure_is_counted_by_the_middleware_seam() -> None:
    """The half the catch-all cannot see: a 5xx the handler produced on purpose."""
    client = _app_client()

    assert client.get("/v1/cases/912/entries/unavailable").status_code == 503

    (pending,) = _buckets_for("/unavailable")
    assert pending.status_class == STATUS_CLASS_SERVER_ERROR
    assert pending.requests == 1


def test_the_two_seams_count_each_failure_once_into_one_bucket() -> None:
    """Same route, same collapsed class, one bucket, count of two.

    An escaped exception and a handler-produced 5xx are different operational
    problems but the same served request, and both are ``5xx`` once collapsed - so
    one bucket carrying two is the correct answer. Two buckets would split one
    route's failure rate across keys a reader has to add up; a count of four would
    mean the two seams double count every failure.
    """
    client = _app_client()

    assert client.get("/v1/cases/912/entries/both-ways").status_code == 500
    assert client.get("/v1/cases/912/entries/both-ways").status_code == 503

    (pending,) = _buckets_for("/both-ways")
    assert pending.status_class == STATUS_CLASS_SERVER_ERROR
    assert pending.requests == 2


def test_a_gateway_rejection_is_counted_like_any_other_served_request() -> None:
    """A rejected token never reaches a route, and must still be counted.

    The counting middleware is registered OUTSIDE ``jwt_verify`` for exactly this
    reason: a 401 that never matched a route is a served request, and an inner
    registration would omit every request the gateway turned away - which are the
    ones a security or availability signal is made of.
    """
    client = _app_client(
        gateway_jwt_verify_enabled=True,
        gateway_jwt_signing_key="unit-http-counter-gateway-signing-key",
    )

    rejected = client.get("/v1/cases/912/entries/fine", headers={"Authorization": "Bearer junk"})

    assert rejected.status_code == 401
    (pending,) = _buckets_for(UNMATCHED_ROUTE_TEMPLATE)
    assert pending.status_class == STATUS_CLASS_CLIENT_ERROR
    assert pending.method == "GET"
    assert pending.requests == 1


def test_a_healthy_request_still_costs_exactly_one_series() -> None:
    """Capture fires on every request, so the map grows by BUCKETS and not by traffic.

    The counterpart to the error capture's "a healthy request buffers nothing": here
    a healthy request does count, and the thing that has to stay bounded is the
    series count rather than the request count.
    """
    for _ in range(50):
        _count(200)

    assert len(pending_http_counts()) == 1


# ------------------------------------------------------------------- the settings


def test_the_counter_defaults_to_a_ceiling_and_a_minute_cadence() -> None:
    """Both numbers are declared in ``app.config`` so nothing hardcodes them twice."""
    settings = Settings()

    assert settings.http_counter_max_series == DEFAULT_HTTP_COUNTER_MAX_SERIES == 5000
    assert (
        settings.http_counter_drain_interval_seconds
        == (DEFAULT_HTTP_COUNTER_DRAIN_INTERVAL_SECONDS)
        == 60
    )


def test_the_drain_cadence_matches_the_counter_grain_by_default() -> None:
    """The write cost is bounded at one row per route per MINUTE, and this is why.

    A faster fold cannot add information - a bucket split across two passes still
    lands on one row - and a slower one only makes the operator's "recent past"
    stale.
    """
    assert Settings().http_counter_drain_interval_seconds % 60 == 0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("http_counter_max_series", 0, "http_counter_max_series must be positive"),
        ("http_counter_max_series", -1, "http_counter_max_series must be positive"),
        (
            "http_counter_drain_interval_seconds",
            0,
            "http_counter_drain_interval_seconds must be positive",
        ),
    ],
)
def test_a_non_positive_counter_setting_is_refused_at_boot(
    field: str, value: int, message: str
) -> None:
    """A zero ceiling would silently disable capture; a zero interval is a busy loop."""
    with pytest.raises(ValueError, match=message):
        Settings(**{field: value})  # type: ignore[arg-type]


def test_the_app_sizes_the_counter_from_settings_on_boot() -> None:
    """The gateway must never read Settings itself, so a composition root does it.

    Sized at the lifespan rather than at the capture site: a setting applied only by
    the worker would leave the ceiling at its import-time default on the one path the
    ceiling exists to protect - the process that serves the requests being counted.
    """
    app = create_app(
        settings=Settings(http_counter_max_series=17, dispatcher_in_process_enabled=False)
    )

    with TestClient(app):
        assert http_counter_capacity() == 17
