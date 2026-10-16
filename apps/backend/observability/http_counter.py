"""In-process per-minute HTTP counter (PHASE-14A B9, #727).

Every answered request increments ONE ``(minute, route template, method, status
class)`` bucket here, and a worker folds the waiting buckets into
``observability_http_minute`` off every request path
(:mod:`modules.observability.http_counter_stream`). That is the whole design, and
it is what makes request throughput and error rate queryable from Postgres past
the free Grafana tier's fourteen-day retention at a bounded write cost: one row
per route per MINUTE, never one write per request (#717 decision 15). A thousand
requests to one route inside one minute are one bucket, one upsert and one row -
so the write amplification that would make a per-request counter unusable in
production never gets the chance to appear.

Three rules this module exists to enforce, each a way the obvious implementation
leaks:

**Aggregate in process, buffer records.** The obvious shape copies the error
capture one-for-one: append a record per request, drain a record per request.
That is one upsert per request and it is exactly the cost decision 15 rules out -
and it is invisible in a test that makes three requests and visible only under
load. The difference here is :meth:`_MinuteCounter.pending`, which reports
unwritten DELTAS per bucket rather than a list of occurrences, so a drain's
statement count is a function of how many route/minute buckets exist, never of
how much traffic arrived.

**Route templates, never concrete paths, and a collapsed status class.** Both are
reused verbatim from the error capture - :func:`route_template_for`,
:func:`method_for` and :func:`status_class_for` - rather than re-derived here.
There is exactly one status taxonomy in the system, and a second extractor is how
two of them start disagreeing. The collapse is what stops the series count from
growing with the codes a platform happens to emit, and the template is what keeps
a patient's id out of a label (#717 decisions 13, 15 and 37).

**Bounded by MINUTE, not by count, and every discard is counted.** A bucket is
keyed on its minute, so the map's natural growth is one entry per route per
minute and the ceiling is spent on minutes that have already gone quiet. At
:attr:`~_MinuteCounter.capacity` the whole OLDEST minute is dropped rather than
one arbitrary bucket, because a partial minute is a row whose count silently
disagrees with reality - worse than an absent row, which at least reads as
missing. A bucket already folded into Postgres is not dropped and does not count
against the ceiling: the row is durable, so keeping the key would only spend
memory on a number the database already owns. :meth:`flush` therefore retires
fully written buckets and leaves the rest.

The drain reports DELTAS, so a crash mid-write is a retry rather than a double
count - the opposite trade from the error stream, where re-writing a record
re-counts one occurrence. There the repeat is a bounded, self-correcting
inaccuracy chosen over dropping an error outright; here the repeat would inflate
throughput permanently and invisibly, which is a different thing entirely. The
one accuracy this design gives up is narrower than either and is stated at
:meth:`_MinuteCounter.flush`, where it belongs.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple

from starlette.requests import Request

from app.config import DEFAULT_HTTP_COUNTER_MAX_SERIES
from observability.error_capture import (
    method_for,
    route_template_for,
    status_class_for,
)


class CounterKey(NamedTuple):
    """One bucket's identity: the minute it belongs to, the route, the method and
    the COLLAPSED status class.

    Raw status codes are deliberately absent - ``status_class_for`` runs before the
    key is built, so ``/v1/cases`` answering 500 then 503 is one bucket rather than
    two (#717 decision 37).

    A NamedTuple rather than a bare ``tuple[...]`` because the eviction and release
    paths read individual fields: ``key[0] == oldest_minute`` names nothing, and a
    positional read of a four-field label is how the wrong minute gets dropped.
    """

    minute_ts: datetime
    route_template: str
    method: str
    status_class: str


@dataclass(frozen=True, slots=True)
class MinuteCount:
    """One bucket's UNWRITTEN delta: requests counted, not yet folded into Postgres.

    ``requests`` is the increment to add to the row, never the row's total. The
    drain sums it into ``observability_http_minute.requests`` and releases exactly
    this amount, so a capture arriving while the write is in flight is counted
    once and released once.
    """

    minute_ts: datetime
    route_template: str
    method: str
    status_class: str
    requests: int


def minute_bucket(now: datetime | None = None) -> datetime:
    """The UTC minute ``now`` belongs to, with seconds and microseconds dropped.

    UTC because that is the axis the table is read on: the operator reads "the
    last hour" against a clock that never changes offset, so a local-time bucket
    would split one hour into two as deployments move.
    """
    moment = now if now is not None else datetime.now(UTC)
    return moment.replace(second=0, microsecond=0)


def record_request(*, request: Request, status_code: int, now: datetime | None = None) -> str:
    """Count one answered request into its minute bucket; returns the status class.

    The whole hot-path cost of the counter is this call: read the matched route
    template off the scope, collapse the status, increment an int in a dict under
    a lock. No I/O, no await, no database connection - every request pays
    microseconds and the drain pays the write.

    The return is the collapsed class because that is what the caller usually
    needs next, and because a caller that had to recompute it would risk drifting
    from the vocabulary this module stores.
    """
    status_class = status_class_for(status_code)
    _counter.record(
        minute_ts=minute_bucket(now),
        route_template=route_template_for(request),
        method=method_for(request),
        status_class=status_class,
    )
    return status_class


class _MinuteCounter:
    """Per-bucket request totals with a flushed baseline and minute-based eviction."""

    def __init__(self, capacity: int) -> None:
        self._lock = threading.Lock()
        self._capacity = max(1, capacity)
        # Accumulated totals, and how much of each has already been folded into
        # Postgres. A pending report is the difference, which is what makes a
        # retried pass idempotent instead of double-counting the traffic.
        self._totals: dict[CounterKey, int] = {}
        self._flushed: dict[CounterKey, int] = {}
        self._dropped = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def dropped(self) -> int:
        """Requests discarded for want of room, since the last :meth:`reset`."""
        with self._lock:
            return self._dropped

    def record(
        self,
        *,
        minute_ts: datetime,
        route_template: str,
        method: str,
        status_class: str,
    ) -> None:
        """Add one request to ``minute_ts``'s bucket for this route/method/class.

        Evicts before incrementing, so the new bucket is never the one dropped: a
        request that arrives when the map is full must land somewhere, and the
        minute that has already drained away is the one an operator no longer
        needs the in-memory copy of.
        """
        key = CounterKey(
            minute_ts=minute_ts,
            route_template=route_template,
            method=method,
            status_class=status_class,
        )
        with self._lock:
            if key not in self._totals:
                self._evict_oldest_minute()
            self._totals[key] = self._totals.get(key, 0) + 1

    def _evict_oldest_minute(self) -> None:
        """Drop every bucket of the oldest minute present, counting its pending requests.

        Assumes the lock is held. The oldest minute is chosen over the oldest
        single bucket so the loss is a whole minute - a bucket kept because
        another of its minute survived would report a count that disagrees with
        the request that made it, which is the failure mode the bound exists to
        avoid.
        """
        if len(self._totals) < self._capacity:
            return
        oldest = min(key.minute_ts for key in self._totals)
        for key in [key for key in self._totals if key.minute_ts == oldest]:
            self._dropped += self._pending(key)
            del self._totals[key]
            self._flushed.pop(key, None)

    def _pending(self, key: CounterKey) -> int:
        """How much of ``key`` has not been folded into Postgres. Assumes the lock."""
        return self._totals.get(key, 0) - self._flushed.get(key, 0)

    def pending(self) -> tuple[MinuteCount, ...]:
        """A NON-DESTRUCTIVE snapshot of every bucket's unwritten delta.

        Non-destructive for the same reason the error buffer's snapshot is: the
        drain writes the snapshot and only then calls :meth:`flush`, so a pass
        that dies mid-write leaves the deltas in place and the next one retries
        them rather than losing the traffic.

        Ordered by minute then route then method then class, so a report is
        reproducible: two runs over the same state produce the same sequence.
        """
        with self._lock:
            keys = sorted(key for key in self._totals if self._pending(key) > 0)
            return tuple(
                MinuteCount(
                    minute_ts=key.minute_ts,
                    route_template=key.route_template,
                    method=key.method,
                    status_class=key.status_class,
                    requests=self._pending(key),
                )
                for key in keys
            )

    def flush(self, persisted: Sequence[MinuteCount]) -> int:
        """Release exactly ``persisted``; returns how many requests that retired.

        Takes the deltas rather than a count, because the deltas are the only
        thing the database's row can be matched against - a key that gained new
        requests during the write must surrender only the amount that was
        written, or the write's requests are counted a second time next pass.

        A bucket whose total has now been written is retired outright: its number
        is durable in Postgres and keeping the key would spend the ceiling on a
        minute the drain has finished with.

        One bounded loss is accepted rather than engineered away, and it is worth
        naming. A bucket evicted mid-write takes its flushed baseline with it, so a
        NEW request for that same minute/route/method/class arriving before this
        release cannot be told apart from the delta already written; its increment
        is retired along with the baseline and never reaches Postgres. It needs the
        ceiling reached AND the eviction to land on the very minute in flight -
        unreachable at the shipped ceiling, reachable at a tiny one - and it happens
        only while the eviction is already being counted and warned about. The
        alternative, a per-bucket generation counter, would buy exactness against a
        condition that only occurs when the telemetry has already said it is
        incomplete.
        """
        if not persisted:
            return 0
        with self._lock:
            released = 0
            for count in persisted:
                key = CounterKey(
                    minute_ts=count.minute_ts,
                    route_template=count.route_template,
                    method=count.method,
                    status_class=count.status_class,
                )
                if key not in self._totals:
                    # Evicted mid-write by the ceiling. Already counted in
                    # ``dropped``; a shortfall here is not the caller's problem.
                    continue
                self._flushed[key] = min(
                    self._totals[key], self._flushed.get(key, 0) + count.requests
                )
                released += count.requests
                if self._flushed[key] >= self._totals[key]:
                    del self._totals[key]
                    del self._flushed[key]
            return released

    def reset(self, capacity: int) -> None:
        """Resize to ``capacity``, evicting the oldest minutes if that means less.

        A resize, not a reset: the counts and the drop total survive, exactly as
        ``_BoundedErrorBuffer.reset`` keeps its records and its drop count. A
        composition root that reconfigures a running process must not erase what the
        process has already observed, and a smaller ceiling evicts immediately rather
        than waiting for the next capture so the bound is real from the moment it is
        set.
        """
        with self._lock:
            self._capacity = max(1, capacity)
            while len(self._totals) >= self._capacity:
                self._evict_oldest_minute()

    def clear(self) -> None:
        """Forget every count and the drop count, keeping the current ceiling.

        The seam between production and the test suites, as
        :func:`reset_http_counter` is; the two are kept apart so a resize and an
        emptying cannot be confused for one another.
        """
        with self._lock:
            self._totals.clear()
            self._flushed.clear()
            self._dropped = 0


_counter = _MinuteCounter(DEFAULT_HTTP_COUNTER_MAX_SERIES)


def configure_http_counter(max_series: int) -> None:
    """Resize the process-global counter; called once at a composition root.

    Resizing rather than reading a constant at increment time is what lets a
    deployment bound the counter by configuration (coding-standards §9.1) without
    the capture site knowing anything about ``Settings``. Counts survive the
    resize - this is a ceiling, not a reset.
    """
    _counter.reset(max_series)


def reset_http_counter() -> None:
    """Empty the counter and clear the drop count without resizing it.

    The seam between production and the test suites, exactly as
    :func:`observability.error_capture.reset_error_capture` is: a process-global
    map is right in production (the capture and the drain are the same process)
    and wrong in a test (two tests share one process), so the suites clear it
    explicitly rather than the production code learning about tests.
    """
    _counter.clear()


def pending_http_counts() -> tuple[MinuteCount, ...]:
    """Every bucket's unwritten delta right now. Does not consume it."""
    return _counter.pending()


def flush_http_counts(persisted: Sequence[MinuteCount]) -> int:
    """Release the deltas a completed drain persisted; returns how many it released.

    Takes the deltas rather than a count for the reason
    :meth:`_MinuteCounter.flush` states: a bucket that took new requests while the
    write was open must surrender only what was written. A shortfall is the caller
    logging that some of the batch was evicted mid-write - already counted by the
    counter - not an error to raise on the worker's timer.
    """
    return _counter.flush(persisted)


def dropped_http_requests() -> int:
    """Requests discarded for want of room since the last :func:`reset_http_counter`.

    Reported by the drain's log line rather than stored: a discarded request is by
    definition not in the map, and a drop count persisted per pass would be a
    second telemetry stream to keep honest for a number that resets on every
    restart anyway. An operator reading a non-zero count knows throughput for
    those minutes is short, which is the fact that matters.
    """
    return _counter.dropped


def http_counter_capacity() -> int:
    """The map's current ceiling - the number the drop policy is stated against."""
    return _counter.capacity


__all__ = [
    "CounterKey",
    "MinuteCount",
    "configure_http_counter",
    "dropped_http_requests",
    "flush_http_counts",
    "http_counter_capacity",
    "minute_bucket",
    "pending_http_counts",
    "record_request",
    "reset_http_counter",
]
