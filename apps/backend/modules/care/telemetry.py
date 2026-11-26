"""MOD-006: process-local delivery telemetry helper (PHASE-8 T2, ticket #428).

Owns the care module's inbound-delivery running counters (KPI-001 "pipeline
counters per loop stage" family). Zero at process start and bumped once per
ledger-deduped delivery, so a replayed ``event_id`` is idempotently skipped and
each count tracks distinct deliveries. Telemetry only - no domain table and no
outbox row is written by the inbound seams (PHASE-8 T08 #424). Extracted into a
dedicated helper so the adapter handlers (case birth, forced-review flag) and
the pure telemetry seams share one counter store without coupling this module's
composition root to the counter bookkeeping.
"""

from __future__ import annotations

from bus.events import (
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
    EVENT_REPORT_FILED,
)

#: Process-local running totals of delivered inbound telemetry events.
_COUNTERS: dict[str, int] = {}


def bump_count(event_type: str) -> None:
    """Bump the running total for one ledger-deduped delivery."""
    _COUNTERS[event_type] = _COUNTERS.get(event_type, 0) + 1


def count_for(event_type: str) -> int:
    """Return the process-local count of distinct deliveries for ``event_type``."""
    return _COUNTERS.get(event_type, 0)


def pre_summary_ready_count() -> int:
    """Return the process-local count of distinct ``pre_summary.ready`` deliveries."""
    return count_for(EVENT_PRE_SUMMARY_READY)


def pre_summary_low_confidence_count() -> int:
    """Return the process-local count of distinct ``pre_summary.low_confidence`` deliveries."""
    return count_for(EVENT_PRE_SUMMARY_LOW_CONFIDENCE)


def report_filed_count() -> int:
    """Return the process-local count of distinct ``report.filed`` deliveries."""
    return count_for(EVENT_REPORT_FILED)
