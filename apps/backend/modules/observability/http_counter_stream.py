"""MOD-013: the HTTP-counter fold - read the per-minute buckets, upsert the counter.

B9 (#727, plan-phase14 §8). The gateway counts every answered request into an
in-process per-minute bucket; this is the other half, and it is the ONLY writer of
``observability_http_minute``. The seam cannot write on the request's hot path,
and the fold is never reached from a request, so the write happens exactly where
the latency argument allows it: on the worker's schedule, off every request.

The batch is written as a SET OF DELTAS, not as one statement per request, and
that is the whole ticket (#717 decision 15). Ten thousand requests to one route in
one minute arrive as one bucket, so the fold runs one upsert and leaves one row -
where a per-request capture would have run ten thousand. The upsert target is the
table's own ``(minute_ts, route_template, method, status_class)`` unique key and
both counters are ADDED, so a bucket split across two drain passes still lands on
one row: the row count is a function of how many route/minute buckets exist, never
of how much traffic arrived.

``errors`` is the 5xx SUBSET of ``requests``, carried on the same row rather than
derived by a second scan - so the operator's error rate is a stored numerator over
a stored denominator. Because the status class is part of the bucket key, the
subset is exact arithmetic rather than a re-read: a ``5xx`` bucket writes its whole
count into both columns and every other class writes it into ``requests`` alone.

Nothing is released from the counter until the write has committed, and only the
delta that was written is released. A drain that dies mid-write therefore leaves
the deltas in place and the next pass retries them, which is a different trade
from the error stream's: re-writing a captured error re-counts ONE occurrence, a
bounded and self-correcting inaccuracy, whereas re-writing a counter delta would
inflate throughput permanently and invisibly. Here the retry has to be exact.

**One process, and the map says so.** The fold empties the counter of the process
it runs in. Production runs the dispatcher in-process in the web service
(``render.yaml`` sets ``DISPATCHER_IN_PROCESS_ENABLED=true`` at ``--workers 1``),
so the job that folds is registered in the same process that counts. A standalone
``python -m worker.main`` - the localhost and CI topology - has nothing to fold by
construction, which is the single-instance assumption stated rather than hidden;
carrying the map across processes is the multi-instance runbook's work.

Two alternatives a reader would expect, and why they are not here:

* **No consumed-event ledger row.** A served request is not an outbox delivery:
  there is no ``event_id`` to record and nothing to replay from. The bucket key IS
  the aggregation key, and it is the better one - it collapses a minute of traffic
  instead of storing each of it.
* **No direct table access from the seam.** The counting side appends to a map and
  knows nothing about this schema. Production reaches ``observability_http_minute``
  only through :func:`drain_http_counter`, the one seam on this module's own facade,
  exactly like every other MOD-013 write (coding-standards §2, ADR-0003).
  :func:`drain_http_counts` is the connection-level half of that same seam: it is
  what the engine-level function calls INSIDE its one transaction, and it is public
  because that is the only way to test the upsert against a real transaction
  boundary. It takes a connection, not an engine, so no caller can open one without
  deciding its own transaction - which is the discipline, stated rather than
  assumed.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Insert
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from modules.observability.schema.models import observability_http_minute
from observability.error_capture import STATUS_CLASS_SERVER_ERROR
from observability.http_counter import (
    MinuteCount,
    dropped_http_requests,
    flush_http_counts,
    http_counter_capacity,
    pending_http_counts,
)

logger = logging.getLogger(__name__)

# Highest cumulative discard count already warned about in THIS process, under its
# own lock. Module state for the same reason as the error drain's: the alternative -
# warning whenever the count is non-zero - emits one line per fold interval for the
# whole duration of a spike. The lock is not the counter's because the two guard
# different things; the scheduler fires this job with ``max_instances=1``, so
# concurrent passes are not expected and the lock costs nothing.
_drops_last_reported = 0
_drops_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class HttpCounterDrainReport:
    """What one fold pass wrote, and what it could not.

    ``series`` counts the BUCKETS written, which is also the number of rows the
    upsert created or added to - the honest headline, and the figure that stays
    flat while traffic climbs. ``requests`` counts the requests those buckets
    carried, so a log line can say both: "folded 12 buckets covering 9,400
    requests" is a complete statement, and "wrote 9400 captures" would describe a
    design this ticket exists not to build.

    ``dropped`` is CUMULATIVE since the last reset, not this pass's count - the
    counter counts a discard once and cannot un-count it - so a caller reports it as
    "since boot" and never as a per-pass delta it did not measure.
    """

    series: int
    requests: int
    dropped: int


def _nothing_to_report() -> HttpCounterDrainReport:
    """The empty-pass report, so both entry points report it the same way."""
    return HttpCounterDrainReport(series=0, requests=0, dropped=dropped_http_requests())


def _upsert(count: MinuteCount) -> Insert:
    """The one statement the fold runs per bucket: insert, or add this minute's traffic.

    ``ON CONFLICT DO UPDATE`` on the table's own unique key rather than an
    insert-then-catch: the conflict is the EXPECTED path for every bucket that
    survives two drain passes, and the addition is atomic against a concurrent fold
    rather than a read-modify-write race.

    Both counters are ADDED and neither is overwritten. A bucket whose minute is
    still open has more requests arriving between two passes, and the row already
    holds the earlier ones; replacing them would make throughput non-monotonic
    inside a single minute, which is the one thing a rate-of-change chart must never
    show.
    """
    table = observability_http_minute
    # The 5xx subset, by construction rather than by a second query: the status
    # class is part of the bucket key, so a server-error bucket's whole count IS
    # its error count and every other class's is zero. The single taxonomy comes
    # from the capture seam - a second spelling of "5xx" here is how the numerator
    # and the series start disagreeing.
    #
    # All four classes are stored, not three, because the table's own CHECK admits
    # exactly ``2xx``/``3xx``/``4xx``/``5xx`` and that is the one vocabulary in the
    # system (shared with the error stream). The three-way collapse of decision 37 is
    # what makes the ERROR RATE a single stored numerator, and it is the server-error
    # class alone that feeds it - a 404 stays visible as its own series so an
    # operator can split a broken link from a failing platform without a second
    # scan, while never letting a caller's mistake read as an outage.
    errors = count.requests if count.status_class == STATUS_CLASS_SERVER_ERROR else 0
    statement = insert(table).values(
        minute_ts=count.minute_ts,
        route_template=count.route_template,
        method=count.method,
        status_class=count.status_class,
        requests=count.requests,
        errors=errors,
    )
    return statement.on_conflict_do_update(
        index_elements=["minute_ts", "route_template", "method", "status_class"],
        set_={
            "requests": table.c.requests + statement.excluded.requests,
            "errors": table.c.errors + statement.excluded.errors,
        },
    )


async def drain_http_counts(
    connection: AsyncConnection, batch: Sequence[MinuteCount] | None = None
) -> HttpCounterDrainReport:
    """Add every waiting bucket's delta onto the per-minute counter, on ``connection``.

    Runs inside the caller's transaction, so the caller decides the commit: the
    engine-level :func:`drain_http_counter` wraps it in exactly one, which is what
    makes the batch atomic and the release safe.

    ``batch`` defaults to a fresh snapshot, and that default is only correct for a
    caller that releases NOTHING afterwards. :func:`drain_http_counter` passes the
    very batch it releases after the commit, and it has to: taking a second snapshot
    after the connection is acquired would WRITE increments the release does not
    cover, so they would be written again next pass and throughput would inflate
    permanently and invisibly. One snapshot, written and released, is the invariant -
    the exactness this counter trades for, in contrast with the error stream's
    re-count.
    """
    counts = pending_http_counts() if batch is None else tuple(batch)
    if not counts:
        return _nothing_to_report()
    for count in counts:
        await connection.execute(_upsert(count))
    return HttpCounterDrainReport(
        series=len(counts),
        requests=sum(count.requests for count in counts),
        dropped=dropped_http_requests(),
    )


async def drain_http_counter(engine: AsyncEngine) -> HttpCounterDrainReport:
    """Fold the process's per-minute buckets into ``observability_http_minute``.

    The engine-level seam every composition root calls: one transaction over the
    whole batch, then - and only then - release exactly the deltas it persisted.
    Releasing after the commit is what turns a crash mid-fold into a retry rather
    than silent loss; releasing before it would make the fold fire-and-forget.

    An empty counter is a no-op that opens no transaction, because a quiet system
    must not hold a pooled connection every interval to discover there is nothing
    to write.
    """
    global _drops_last_reported

    pending = pending_http_counts()
    if not pending:
        return _nothing_to_report()

    async with engine.begin() as connection:
        report = await drain_http_counts(connection, batch=pending)
    unreleased = sum(count.requests for count in pending) - flush_http_counts(pending)
    with _drops_lock:
        changed = report.dropped != _drops_last_reported
        if changed:
            _drops_last_reported = report.dropped
    if changed:
        # Not "greater than": the counter is resettable (``reset_http_counter``,
        # which the tests and a fresh process both use), so the count can come back
        # DOWN. Comparing for inequality rather than growth means a reset re-arms the
        # line instead of silencing it for the rest of the process. A sustained
        # spike discards on every pass, and warning each time would bury the signal
        # the operator is meant to read under one line per interval - so the latch
        # is on CHANGED, not on non-zero. The count reported stays cumulative, so the
        # line that does fire names the true total rather than the increment.
        logger.warning(
            "http counter has discarded %d request(s) since boot against a ceiling of "
            "%d series; throughput is incomplete for the minutes dropped",
            report.dropped,
            http_counter_capacity(),
        )
    if unreleased:
        # The batch was evicted mid-write by the counter's own bound. Those requests
        # are in ``report.dropped`` already, so this line attributes the loss rather
        # than inventing a second count for it.
        logger.warning(
            "%d of %d folded request(s) were evicted before the write committed; "
            "they are counted as dropped, not persisted",
            unreleased,
            report.requests,
        )
    return report
