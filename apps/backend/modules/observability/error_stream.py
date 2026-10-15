"""MOD-013: the error-buffer drain - read the buffer, upsert the error stream.

B8 (#726, plan-phase14 §8). The gateway error seam appends to a bounded in-process
buffer; this is the other half, and it is the ONLY writer of
``observability_error_events``. The seam cannot write on the failing request's hot
path, and the drain is never reached from a request, so the write happens exactly
where the latency argument allows it: on the worker's schedule, off every request.

The collapse rule is the whole point of the table's grain. One row per DISTINCT
``fingerprint``, upserted: a first sight inserts with ``occurrences = 1``, and a
repeat increments the count and moves ``last_seen_at`` forward carrying the newest
``trace_id`` - so an operator jumping from the feed reaches the occurrence they
are actually looking at (#717 decision 14). A storm of one repeated failure
therefore costs ONE row, which is the same reason the buffer upstream is bounded:
the two bounds together are what stop a failing system from being killed by its own
error reporting.

The drained batch is written in ONE transaction, and nothing is released from the
buffer until it has committed. A drain that dies mid-write therefore leaves the
records buffered and the next pass retries them, instead of losing the errors the
pass was in the middle of persisting. The re-drain that makes possible is not a
double row but a re-count of one occurrence - a bounded, self-correcting
inaccuracy, deliberately chosen over dropping an error outright.

**One process, and the buffer says so.** The drain empties the buffer of the process
it runs in. Production runs the dispatcher in-process in the web service
(``render.yaml`` sets ``DISPATCHER_IN_PROCESS_ENABLED=true`` at ``--workers 1``), so
the job that drains is registered in the same process that captures. A standalone
``python -m worker.main`` - the localhost and CI topology - has no captures to
drain by construction, which is the single-instance assumption stated rather than
hidden; carrying the buffer across processes is the multi-instance runbook's work.

Two alternatives a reader would expect, and why they are not here:

* **No consumed-event ledger row.** A captured failure is not an outbox delivery:
  there is no ``event_id`` to record and nothing to replay from. The fingerprint
  IS the deduplication key, and it is the better one - it collapses the repeats the
  feed exists to show, rather than storing each of them.
* **No direct table access from the seam.** The capture side appends to a buffer
  and knows nothing about this schema. Production reaches
  ``observability_error_events`` only through :func:`drain_error_buffer`, the one
  seam on this module's own facade, exactly like every other MOD-013 write
  (coding-standards §2, ADR-0003). :func:`drain_error_captures` is the connection-level
  half of that same seam: it is what the engine-level function calls INSIDE its one
  transaction, and it is public because that is the only way to test the upsert
  against a real transaction boundary. It takes a connection, not an engine, so no
  caller can open one without deciding its own transaction - which is the
  discipline, stated rather than assumed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sqlalchemy import Insert
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from modules.observability.schema.models import observability_error_events
from observability.error_capture import (
    CapturedError,
    discard_error_captures,
    dropped_error_captures,
    error_capture_capacity,
    pending_error_captures,
)

logger = logging.getLogger(__name__)

# Highest cumulative discard count already warned about in THIS process, under its
# own lock. Module state, deliberately: the alternative - warning whenever the
# count is non-zero - emits one line per drain interval for the whole duration of a
# storm. The lock is here rather than reusing the BUFFER's because the two guard
# different things, and because borrowing the buffer's would mean holding a lock
# this module does not own to protect a variable the buffer never reads. The
# scheduler fires this job with ``max_instances=1`` so concurrent passes are not
# expected; the lock costs nothing and makes that an optimization rather than a
# correctness assumption.
_drops_last_reported = 0
_drops_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class ErrorDrainReport:
    """What one drain pass wrote, and what it could not.

    ``written`` counts RECORDS drained, not rows created: a batch of three
    identical failures writes three occurrences onto one row. ``frequencies`` is
    therefore the honest headline and ``written`` only tells the operator how much
    of the buffer was cleared.

    ``dropped`` is CUMULATIVE since boot, not this pass's count - the buffer counts
    a discard once and cannot un-count it - so a caller reports it as "since boot"
    and never as a per-pass delta it did not measure.
    """

    written: int
    frequencies: int
    dropped: int


def _nothing_to_report() -> ErrorDrainReport:
    """The empty-pass report, so both entry points report it the same way."""
    return ErrorDrainReport(written=0, frequencies=0, dropped=dropped_error_captures())


def _upsert(record: CapturedError) -> Insert:
    """The one statement the drain runs per record: insert, or count the repeat.

    ``ON CONFLICT DO UPDATE`` keyed on ``fingerprint`` rather than an
    insert-then-catch: the conflict is the EXPECTED path for every repeat, so it
    belongs in the statement's own conflict target where it costs nothing, and the
    count increment is atomic against a concurrent drain rather than a
    read-modify-write race.

    Only ``occurrences``, ``last_seen_at`` and ``trace_id`` are refreshed. Route
    template, method, status code, kind and code are all INPUTS to the fingerprint,
    so a repeat is identical on every one of them and re-writing them would be
    churn; ``first_seen_at`` is deliberately not in the set, which is what makes it
    the row's true first sighting after the upsert.

    The ``where`` guard makes the update MONOTONIC in ``last_seen_at``. The buffer
    hands records over in occurrence order so this is belt-and-braces, but a
    retried batch after a partial drain must never roll a newer sighting - and the
    occurrence it names - backwards to an older one.
    """
    table = observability_error_events
    statement = insert(table).values(
        fingerprint=record.fingerprint,
        route_template=record.route_template,
        method=record.method,
        status_code=record.status_code,
        status_class=record.status_class,
        kind=record.kind,
        code=record.code,
        trace_id=record.trace_id,
        occurrences=1,
        first_seen_at=record.occurred_at,
        last_seen_at=record.occurred_at,
    )
    return statement.on_conflict_do_update(
        index_elements=["fingerprint"],
        set_={
            "occurrences": table.c.occurrences + 1,
            "last_seen_at": statement.excluded.last_seen_at,
            "trace_id": statement.excluded.trace_id,
        },
        where=statement.excluded.last_seen_at >= table.c.last_seen_at,
    )


async def drain_error_captures(connection: AsyncConnection) -> ErrorDrainReport:
    """Upsert every buffered capture onto the error stream, on ``connection``.

    Runs inside the caller's transaction, so the caller decides the commit: the
    engine-level :func:`drain_error_buffer` wraps it in exactly one, which is what
    makes the batch atomic and the buffer release safe.

    ``frequencies`` counts the distinct fingerprints in the batch rather than
    probing for rows after the fact: the batch is what was written, so counting it
    is both cheaper and immune to a row another writer created concurrently.
    """
    records = pending_error_captures()
    if not records:
        return _nothing_to_report()
    for record in records:
        await connection.execute(_upsert(record))
    return ErrorDrainReport(
        written=len(records),
        frequencies=len({record.fingerprint for record in records}),
        dropped=dropped_error_captures(),
    )


async def drain_error_buffer(engine: AsyncEngine) -> ErrorDrainReport:
    """Drain the process's error buffer into ``observability_error_events``.

    The engine-level seam every composition root calls: one transaction over the
    whole batch, then - and only then - release what it persisted from the buffer.
    Releasing after the commit is what turns a crash mid-drain into a retry rather
    than a silent loss; releasing before it would make the drain fire-and-forget on
    exactly the failures nobody is watching.

    An empty buffer is a no-op that opens no transaction, because a worker firing
    every drain interval must not hold a pooled connection while nothing has
    failed.
    """
    global _drops_last_reported

    pending = pending_error_captures()
    if not pending:
        return _nothing_to_report()

    async with engine.begin() as connection:
        report = await drain_error_captures(connection)
    unreleased = len(pending) - discard_error_captures(pending)
    with _drops_lock:
        changed = report.dropped != _drops_last_reported
        if changed:
            _drops_last_reported = report.dropped
    if changed:
        # Not "greater than": the buffer is resettable (``reset_error_capture``,
        # which the tests and a fresh process both use), so the count can come back
        # DOWN. Comparing for inequality rather than growth means a reset re-arms
        # the line instead of silencing it for the rest of the process. A sustained
        # storm discards on every pass, and warning each time would bury the failure
        # the operator is meant to read under one line per interval - so the latch is
        # on CHANGED, not on non-zero. The count reported stays cumulative, so the
        # line that does fire names the true total rather than the increment.
        logger.warning(
            "error capture buffer has discarded %d capture(s) since boot against a "
            "ceiling of %d; the error stream is incomplete for those failures",
            report.dropped,
            error_capture_capacity(),
        )
    if unreleased:
        # The batch was evicted mid-write by the buffer's own bound. Those records
        # are in ``report.dropped`` already, so this line attributes the loss rather
        # than inventing a second count for it.
        logger.warning(
            "%d of %d drained record(s) were evicted before the write committed; "
            "they are counted as dropped captures, not persisted",
            unreleased,
            len(pending),
        )
    return report
