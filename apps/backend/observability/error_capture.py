"""Bounded in-process capture buffer for server errors (PHASE-14A B8, #726).

The gateway error seam appends here instead of writing to the database, because a
request that is already failing must not also wait on a telemetry write to finish
failing: the capture is one append to a bounded deque, and a worker drains the
buffer into the ``observability`` schema off the request path
(:mod:`modules.observability.error_stream`).

Three rules this module exists to enforce, each of them a way the obvious
implementation leaks:

**Bounded, with an explicit drop policy.** ``deque(maxlen=...)`` keeps the NEWEST
``capacity`` records and discards the OLDEST, and every discard is counted. An
unbounded buffer turns an error storm into an out-of-memory kill, which is a worse
outcome than the outage it was recording. Dropping the oldest rather than the
newest is deliberate: a live feed is about what is failing NOW, and the records a
storm pushes out are the ones the operator has already been paged for.

**Route templates, never concrete paths.** :func:`route_template_for` reads the
MATCHED route's path pattern off the request scope, never ``request.url.path``. A
concrete path puts an identifier into telemetry and makes the label cardinality
unbounded - both are the same defect seen from two sides.

**PHI-free records by construction.** A :class:`CapturedError` carries a route
template, a method, a status code, a status class, a fixed envelope code, a kind
and a trace id. There is no field for a body, a query string, a header or an
exception's text, so there is no way for one to be added by accident; the code is
the envelope's stable human-safe string (error-handling-observability §1), never
internal detail.

The :func:`fingerprint_for` collapse key is derived from the STABLE attributes of
a failure alone. A fingerprint that included the trace id or a timestamp would be
unique per occurrence and would collapse nothing, which is the whole point of the
column (#717 decision 14).

In-process is correct for the current single-instance topology and is the stated
reason horizontal scaling stays deferred; a Redis hand-off is a different decision
with its own ticket. The one consequence worth writing down: the buffer lives in
WHATEVER PROCESS CAPTURED the failure, so only a worker sharing that process has
anything to drain. Production runs the dispatcher in-process in the web service
(``render.yaml`` sets ``DISPATCHER_IN_PROCESS_ENABLED=true`` at ``--workers 1``),
so the drain is registered in the same process that captures. A split topology -
a standalone ``python -m worker.main`` on localhost and CI - gives the standalone
worker an empty buffer by construction, and the capture is confined to the web
process there. Single-instance is the assumption; making it hold across processes
is the multi-instance ticket's work.
"""

from __future__ import annotations

import hashlib
import threading
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from starlette.requests import Request

from app.config import DEFAULT_ERROR_CAPTURE_MAX_RECORDS

#: An exception escaped every module-level handler. Captured as well as answered,
#: so a swallowed exception is not invisible (#717 story 27).
ERROR_KIND_UNHANDLED_EXCEPTION = "unhandled_exception"
#: A 5xx was answered by a handler rather than raised past one.
ERROR_KIND_SERVER_ERROR_RESPONSE = "server_error_response"

STATUS_CLASS_SUCCESS = "2xx"
STATUS_CLASS_REDIRECT = "3xx"
STATUS_CLASS_CLIENT_ERROR = "4xx"
STATUS_CLASS_SERVER_ERROR = "5xx"

#: Stands in when no route matched - an exception raised before routing finished
#: reaches the seam with an empty ``route["path"]``. It is a fixed token rather
#: than the raw path precisely because at this point the raw path is the only
#: thing available, and the raw path is exactly what must not be recorded.
UNMATCHED_ROUTE_TEMPLATE = "<unmatched>"

# NOTE on the ceiling's home: ``DEFAULT_ERROR_CAPTURE_MAX_RECORDS`` is declared in
# ``app.config`` - the one module every other default lives in - and imported below
# rather than restated, because the buffer needs a ceiling before any composition
# root has configured one. The dependency therefore runs ``app.config`` ->
# ``observability.error_capture`` and never the reverse: the ``observability``
# package's ``__init__`` reaches back into ``app.config`` for ``APP_VERSION``, so an
# import the other way round is a cycle (coding-standards §9.2). A thousand records
# rides out a drain interval through a spike, and is small enough that the buffer
# can never be the reason a process dies.

#: Caps the free-text fields a hostile or buggy client can push into a column. The
#: method is a fixed HTTP token in practice and the code a fixed envelope string;
#: ``trace_id`` is the exception that matters - ``app.gateway.trace`` HONOURS a
#: client-supplied ``X-Request-Id`` up to its own 128-char safety limit, which is
#: wider than the ``trace_id`` column. Unbounded, one such header on one failing
#: route writes a record whose upsert raises on length, and because the drain
#: aborts the WHOLE batch on the first bad row, that record poisons every
#: subsequent pass - error capture is silently dead until enough fresh errors evict
#: it. So the width is clamped HERE, at the only point the value enters the system,
#: rather than trusted at the column.
_MAX_METHOD_LENGTH = 10
_MAX_CODE_LENGTH = 64
_MAX_TRACE_ID_LENGTH = 64

#: A hex sha256 is 64 characters, which is the column's width exactly - no
#: truncation, so a fingerprint collision is a sha256 collision.
_FINGERPRINT_LENGTH = 64


@dataclass(frozen=True, slots=True)
class CapturedError:
    """One captured server error: structured, PHI-free and already collapsed."""

    fingerprint: str
    route_template: str
    method: str
    status_code: int
    status_class: str
    kind: str
    code: str
    trace_id: str
    occurred_at: datetime


def route_template_for(request: Request) -> str:
    """The matched route's path PATTERN for ``request``, never the concrete path.

    Starlette stores the matched ``Route`` in the scope once routing has run, and
    that object's ``path`` is the pattern the app declared (``/v1/cases/{case_id}``).
    Reading the concrete ``request.url.path`` instead would record a patient's
    intake id as a telemetry label, which is both an identifier leak and unbounded
    cardinality (#717 decision 13).
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not isinstance(template, str) or not template:
        return UNMATCHED_ROUTE_TEMPLATE
    return template


def method_for(request: Request) -> str:
    """The uppercased request method, bounded to the column's width."""
    method = request.scope.get("method") or "UNKNOWN"
    return str(method).upper()[:_MAX_METHOD_LENGTH]


def status_class_for(status_code: int) -> str:
    """The COLLAPSED status class - ``5xx``, never the raw ``503``.

    Collapsed here rather than at read time because a class is what a filter or a
    series can be built on without cardinality growing with the codes a platform
    happens to emit. It is deliberately NOT the fingerprint's input: the error
    stream keeps the exact ``status_code`` beside this class, because an operator
    reading the feed needs to see a failure move from 500 to 502, and the two
    columns can be read either way (#717 decisions 13 and 15).
    """
    if status_code >= 500:
        return STATUS_CLASS_SERVER_ERROR
    if status_code >= 400:
        return STATUS_CLASS_CLIENT_ERROR
    if status_code >= 300:
        return STATUS_CLASS_REDIRECT
    return STATUS_CLASS_SUCCESS


def fingerprint_for(
    *,
    route_template: str,
    method: str,
    status_code: int,
    kind: str,
    code: str,
) -> str:
    """The collapse key for a failure, from its STABLE attributes alone.

    Route template, method, status code, kind and envelope code - the things that
    are the same on the hundredth occurrence as on the first. Deliberately absent:
    the trace id and the timestamp. Including either would make every occurrence
    its own fingerprint, and a collapse column that collapses nothing is worse than
    no collapse column because it looks like it is working (#717 decision 14).
    """
    material = f"{kind}|{route_template}|{method}|{status_code}|{code}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:_FINGERPRINT_LENGTH]


class _BoundedErrorBuffer:
    """A bounded FIFO of captured errors with a counted, newest-first drop policy."""

    def __init__(self, capacity: int) -> None:
        self._lock = threading.Lock()
        self._capacity = max(1, capacity)
        self._records: deque[CapturedError] = deque(maxlen=self._capacity)
        self._dropped = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    def capture(self, record: CapturedError) -> bool:
        """Append ``record``; ``False`` when it displaced an older one.

        On a full buffer ``deque(maxlen=...)`` evicts the OLDEST record to make
        room, so what survives a storm is the current failure and the count of what
        was lost is available to the drain's log line. Discarding rather than
        blocking is the whole design: this runs on the failing request's path and
        must never make that request wait.
        """
        with self._lock:
            evicted = len(self._records) == self._capacity
            self._records.append(record)
            if evicted:
                self._dropped += 1
            return not evicted

    def pending(self) -> tuple[CapturedError, ...]:
        """A NON-DESTRUCTIVE snapshot of everything held, oldest first.

        Non-destructive on purpose: the drain writes the snapshot and only then
        calls :meth:`discard`. A drain that dies mid-write therefore leaves the
        records in place and the next pass retries them, instead of losing the
        errors the pass was in the middle of persisting.
        """
        with self._lock:
            return tuple(self._records)

    def discard(self, persisted: Sequence[CapturedError]) -> int:
        """Release exactly ``persisted`` - the records a completed write persisted.

        Identity-matched across the WHOLE buffer, not a counted pop from the front,
        and the two failure modes that difference prevents are the reason this
        method exists in its current shape.

        A counted pop releases the N OLDEST records, which is only the right N
        while the buffer has not turned over underneath the drain. Captures arriving
        during the write transaction append to the far end, so a busy interval can
        evict part of the drained batch from the near end - and then a counted pop
        releases records the write NEVER touched, which is silent, uncounted loss
        during exactly the storm the bound exists for.

        A left-to-right identity scan is not enough either, and the subtle case is
        a PARTIAL turnover. The snapshot is non-destructive, so the buffer holds
        ``[old1..oldN, new1..newK]``; eviction removes from the near end, so a
        long-enough burst of newcomers can shift the OLD records right rather than
        deleting all of them, leaving ``[new1..newK, oldJ+1..oldN]``. A scan that
        stops at the first mismatch - ``records[0] is old1`` is false the moment
        ``old1`` is gone - then releases NOTHING at all, and the surviving old
        records are written a second time next pass, inflating ``occurrences``
        permanently rather than by one recoverable count. Scanning the whole buffer
        by identity releases the 200 survivors and correctly reports the 300 that
        were genuinely lost.

        A record missing at the end was evicted by the buffer's own bound, and
        :attr:`dropped` already counted it.
        """
        surviving = {id(record) for record in persisted}
        if not surviving:
            return 0
        with self._lock:
            kept = deque(record for record in self._records if id(record) not in surviving)
            # Counted from what was actually removed rather than from the size of
            # the identity set: a caller may hand the same object twice, and the
            # buffer could hold it twice, in which case the set's size is not the
            # number of slots cleared.
            released = len(self._records) - len(kept)
            self._records = kept
            return released

    @property
    def dropped(self) -> int:
        """How many captures were discarded for want of room, since boot."""
        with self._lock:
            return self._dropped

    def clear(self) -> None:
        """Empty the buffer and clear the drop count, keeping the current size."""
        with self._lock:
            self._records.clear()
            self._dropped = 0

    def reset(self, capacity: int) -> None:
        """Resize to ``capacity``, keeping the NEWEST records that still fit.

        Shrinking rebuilds the deque rather than assigning a new ``maxlen``,
        because a ``deque`` constructed from an over-long iterable keeps the
        RIGHTMOST items - so a resize down keeps what is currently happening and
        drops what has already been superseded, the same policy an append to a
        full buffer applies.
        """
        with self._lock:
            self._capacity = max(1, capacity)
            self._records = deque(self._records, maxlen=self._capacity)


_buffer = _BoundedErrorBuffer(DEFAULT_ERROR_CAPTURE_MAX_RECORDS)
#: The #753 gate (ERROR_CAPTURE_ENABLED). Armed at import - the pre-gate
#: behaviour - and re-armed by every composition root from its resolved
#: ``Settings`` at boot, so the capture sites stay Settings-free too.
_error_capture_enabled = True


def configure_error_capture(max_records: int, *, enabled: bool = False) -> None:
    """Size the process-global buffer and set the #753 capture gate.

    Resizing rather than reading a constant at append time is what lets a
    deployment bound the buffer by configuration (coding-standards §9.1) without
    every capture site having to know about ``Settings``. ``enabled`` is the same
    idea one level up: the composition root applies ``ERROR_CAPTURE_ENABLED``
    here, so the gate check inside :func:`capture_server_error` needs no
    ``Settings`` either. The default is OFF so a caller that forgets the kwarg
    fails safe; every caller in this repo passes it explicitly (the composition
    roots from resolved ``Settings``, the suites' fixture arming ``True``). The
    module flag's own import-time default stays ``True`` - the pre-gate
    behaviour - so a process that never configures at all (a one-off script) is
    unchanged.
    """
    global _error_capture_enabled
    _error_capture_enabled = enabled
    _buffer.reset(max_records)


def reset_error_capture() -> None:
    """Empty the buffer and clear the drop count without resizing it.

    The seam between production and the test suites: a process-global buffer is
    right in production (the capture and the drain are the same process) and wrong
    in a test (two tests share one process), so the suites clear it explicitly
    rather than the production code learning about tests.
    """
    _buffer.clear()


def capture_server_error(
    *,
    request: Request,
    status_code: int,
    kind: str,
    code: str,
    trace_id: str,
) -> CapturedError | None:
    """Build and buffer one server-error record; ``None`` when it captured nothing.

    The gate first (#753): with ``ERROR_CAPTURE_ENABLED`` off this returns before
    a record is even built, which is what makes the feature a true no-op for a
    deployment that has not opted in - the 500 answers exactly as it would
    without the seam. Like the ceiling, the gate lives here so neither capture
    site (the catch-all handler, the gateway middleware) knows about ``Settings``.

    The whole hot-path cost of the capture is this call: read the matched route
    template off the scope, hash five short strings, append to a deque. No I/O, no
    await, no database connection - the failing request pays microseconds and the
    drain pays the write.

    The remaining ``None`` is the DISPLACEMENT signal, not a rejection: ``None`` means the
    buffer was full and an older capture lost its place, which :func:`capture` has
    already counted. Nothing on the request path branches on it - a failing request
    must not start failing differently because telemetry was busy - and the drain
    reads the cumulative count instead, one place, where an operator will see it.
    """
    if not _error_capture_enabled:
        return None
    route_template = route_template_for(request)
    method = method_for(request)
    safe_code = (code or "")[:_MAX_CODE_LENGTH]
    record = CapturedError(
        fingerprint=fingerprint_for(
            route_template=route_template,
            method=method,
            status_code=status_code,
            kind=kind,
            code=safe_code,
        ),
        route_template=route_template,
        method=method,
        status_code=status_code,
        status_class=status_class_for(status_code),
        kind=kind,
        code=safe_code,
        # Clamped, not validated: a trace id's job is correlation, and a truncated
        # one still correlates within the window an operator is reading, while a
        # rejected one would drop the link to the log lines that explain the
        # failure. See ``_MAX_TRACE_ID_LENGTH`` for why the column cannot be the
        # thing that says no.
        trace_id=trace_id[:_MAX_TRACE_ID_LENGTH],
        occurred_at=datetime.now(UTC),
    )
    return record if _buffer.capture(record) else None


def pending_error_captures() -> tuple[CapturedError, ...]:
    """Everything the buffer holds right now, oldest first. Does not consume it."""
    return _buffer.pending()


def discard_error_captures(persisted: Sequence[CapturedError]) -> int:
    """Release the records a completed drain persisted; returns how many it released.

    Takes the records themselves rather than a count, for the reason
    :meth:`_BoundedErrorBuffer.discard` states. A shortfall is the caller logging
    that some of the batch was evicted mid-write - already counted as a drop by the
    buffer - not an error to raise on the worker's timer.
    """
    return _buffer.discard(persisted)


def dropped_error_captures() -> int:
    """Captures discarded for want of buffer room since boot.

    Reported by the drain's log line rather than stored: a dropped capture is by
    definition not in the buffer, and a drop count persisted per pass would be a
    second telemetry stream to keep honest for a number that resets on every
    restart anyway. An operator reading a non-zero count knows the feed is
    incomplete, which is the fact that matters.
    """
    return _buffer.dropped


def error_capture_capacity() -> int:
    """The buffer's current ceiling - the number the drop policy is stated against."""
    return _buffer.capacity
