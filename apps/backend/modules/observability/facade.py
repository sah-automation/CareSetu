"""MOD-013 Observability: typed public sync API + the consumer's effect writes.

The only legal cross-module import target for the ``observability``
module (coding-standards §2, ADR-0003). It is telemetry, not a domain
bounded context: the C1 operator read methods arrive with the operator read
routes, split across two batches - C1a (``#706``) serves spend, usage and
quality; C1b (``#707``) serves the overview, latency, health, alert feed and
deep links. The B4 public surface carries the effects the event consumers
run - the AI-usage aggregation (B4a #702), the registry-driven business-daily
counts and the PHI-free alert rows (B4b #703) - plus the schema constant the
composition root resolves the ledger against.

B6 (#723) adds :func:`record_ai_job_spend`: the one-granular-row-per-AI-job
effect that makes per-patient and per-doctor attribution arithmetic rather than
guesswork, keyed on the one-way actor hashes rather than on raw identity
references.

B7 (#724) adds :func:`record_care_attribution_edge`: the one-row-per-intake
care-attribution edge that says which doctor an intake belongs to. It is written
because MOD-005 published ``intake.doctor_assigned``, never by reading the care
schema - the module isolation rule (ADR-0003) makes the event the only legal
source of that pairing.

The B5a nightly rollup (#704) joins it as :func:`run_rollup`: the off-request-path
pass that recomputes the percentile aggregates, snapshots budget spend and
evaluates the alert thresholds. B5b (#705) adds the two scheduler seams the
scheduled GitHub Action drives it through - :func:`load_rollup_state`, which
reports what the rollup has already covered, and :func:`plan_rollup_dates`, which
turns that state into the dates one invocation rolls (the first-run backfill, the
previous day afterwards). Both are re-exported here so the
``python -m worker.rollup`` entry point reaches them through the facade, like
every other composition-root seam.

B8 (#726) adds :func:`drain_error_buffer`, the same shape for a different job: the
gateway error seam buffers failures in process, and this drains them into
``observability_error_events`` in one transaction off the request path. It is the
ONLY writer of that table, and it is re-exported here so the worker's scheduled
drain reaches it through the facade rather than reaching into the module.

B9 (#727) adds :func:`drain_http_counter` and the ``/throughput`` read. The
gateway counts every answered request into a per-minute bucket in process; this
folds those buckets into ``observability_http_minute`` - the ONLY writer of that
table - and serves throughput, error rate and the capture-liveness answer over the
recent past. The count is one row per route per MINUTE (#717 decision 15), which
is what makes the figure queryable from Postgres beyond the vendor's fourteen-day
retention; ``/throughput`` is where that becomes operator-visible, and it reports
whether capture was working at all so an empty error feed never reads as a healthy
system.

B5a (#729) adds :func:`record_ai_queue_open` / :func:`close_ai_queue_item` - the
still-open AI jobs the ``ai_job.queued`` event opens and the completion/failure
events close - plus the ``/reliability`` read. Queue DEPTH and the age of the
oldest queued item are derived from those rows because a cross-schema read of
``intake_ai_jobs`` is forbidden (ADR-0003): depth is the lagging figure and age
is the leading one, and an alert that waits for a row count cannot see a queue
that has stopped draining. The same read serves the per-outbox backlog breakdown
and the recent-ACTIVITY figure, and LINKS to the tracing backend for true
concurrency rather than approximating it in Postgres (#717 decision 17).

B8 (#730) adds the ``/errors`` read: the live, collapsed error stream, served from
``observability_error_events`` because Postgres is the system of record and Sentry
is not a queryable store (#717 Out of Scope). Nothing about it is new aggregation -
the capture already collapsed repeats into one row per fingerprint with an
occurrence count - so the read's work is paging, the open/resolved split, and
carrying each entry's route TEMPLATE, method, status and trace identifier to the
wire without ever touching a concrete request path.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import (
    ColumnElement,
    Integer,
    cast,
    delete,
    func,
    literal,
    literal_column,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.bootstrap import MODULE_SCHEMAS
from bus.dispatcher import count_outbox_rows, discover_outbox_tables
from bus.envelope import Envelope
from bus.ledger import HANDLER_RESULT_ACTOR_KEY
from modules.observability.domain.consumer import (
    AI_JOB_SPEND_STATUS_COMPLETED,
    AI_JOB_SPEND_STATUS_FAILED,
    ALERT_SEVERITY_CRITICAL,
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
    AiJobQueuedTelemetryPayload,
    AlertRow,
    IntakeDoctorAssignedTelemetryPayload,
    sanitize_failure_reason,
)
from modules.observability.domain.deeplinks import (
    grafana_link,
    grafana_metric_link,
    langfuse_link,
    sentry_link,
)
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)
from modules.observability.domain.rollup import (
    ALERT_STATUS_OPEN,
    ALERT_STATUS_RESOLVED,
    BREAKER_STATE_OPEN,
    ROLLUP_MODE_BACKFILL,
    ROLLUP_MODE_DAILY,
    ProviderHealth,
    ProviderStatus,
    RollupPlan,
    RollupThresholds,
    plan_rollup_dates,
    provider_status,
    ratio,
)
from modules.observability.error_stream import ErrorDrainReport, drain_error_buffer
from modules.observability.http_counter_stream import (
    HttpCounterDrainReport,
    drain_http_counter,
)
from modules.observability.rollup import RollupReport, RollupRunState, load_rollup_state, run_rollup
from modules.observability.schema.models import (
    observability_ai_cost_budget,
    observability_ai_job_spend,
    observability_ai_provider_health,
    observability_ai_queue_open,
    observability_ai_usage_daily,
    observability_alert_events,
    observability_business_daily,
    observability_care_attribution_edges,
    observability_consumed_events,
    observability_error_events,
    observability_http_minute,
    observability_rollup_runs,
)

OBSERVABILITY_SCHEMA = "observability"

#: Default and ceiling of one page of the alert feed (api-standards §4: default
#: 25, max 100). The feed is paged rather than capped at one screen because the
#: operator page shows its most recent page and can page back through a long
#: incident.
DEFAULT_ALERT_PAGE_SIZE = 25
MAX_ALERT_PAGE_SIZE = 100

#: Window of the ``/throughput`` read, in MINUTES rather than days (B9 #727). The
#: counter's grain is a minute, so a day-granular window would answer a question
#: about an hour: the read exists to separate a spike from a trickle over "the
#: recent past", and a default wide enough to show a thirty-day trend is wide
#: enough to hide the spike in it. Sixty minutes is one working hour of a single
#: shift, and the ceiling is a full day - long enough to see this morning's outage
#: from this afternoon, short enough that a response stays a few thousand rows.
DEFAULT_THROUGHPUT_WINDOW_MINUTES = 60
MAX_THROUGHPUT_WINDOW_MINUTES = 1440

#: How many route rows ``/throughput`` returns. The per-route breakdown is a
#: "which endpoints are busy" list for a panel, not a dump: at launch scale a day
#: window touches a couple of hundred route/method pairs and no card renders that.
#: The total beside it is the honest signal that the list is truncated - the same
#: reason ``AlertPage`` carries ``total_count``.
MAX_THROUGHPUT_ROUTE_ROWS = 20

#: Window of the ``/reliability`` read's RECENT-ACTIVITY figure (B5 #729), in
#: minutes, for the same reason ``/throughput`` counts in minutes: the question is
#: "who was here just now", and a day-long window answers "who was here this
#: morning" instead. Sixty minutes is one working hour of a single shift; the
#: ceiling is a full day, so an operator can widen the lens without the read
#: becoming an unbounded scan of the consumed-event ledger.
DEFAULT_ACTIVITY_WINDOW_MINUTES = 60
MAX_ACTIVITY_WINDOW_MINUTES = 1440

#: Paging of the ``/errors`` read (#730), on the api-standards §4 default of 25 and
#: ceiling of 100. It carries its OWN pair rather than borrowing the alert feed's:
#: the two feeds are separate decisions that happen to agree on the convention, and a
#: shared constant would let a change to one silently reshape the other's response.
DEFAULT_ERROR_PAGE_SIZE = 25
MAX_ERROR_PAGE_SIZE = 100

#: How recently a failure has to have happened for its entry to read as ``open``
#: (#730). The window IS this read's whole notion of "live", because a captured
#: error carries no lifecycle of its own: nothing marks a failure handled, so
#: recency is the only signal available that separates a problem happening now from
#: one that has stopped happening. It matches ``/throughput``'s "recent past" so the
#: feed and the counter an operator reads beside it describe the same period, and the
#: ceiling is a full day - long enough for a nightly batch's failure to stay visible
#: through the morning it is investigated.
DEFAULT_ERROR_WINDOW_MINUTES = 60
MAX_ERROR_WINDOW_MINUTES = 1440

#: The statuses a captured error can read as (#730) - the statuses the CAPTURE can
#: produce, named from the alert vocabulary's own constants so the two feeds are
#: guaranteed to say ``open`` and ``resolved`` with the same words.
#:
#: It is deliberately narrower than the alert vocabulary, and that is a fact about
#: the data rather than a choice: acknowledgement is an action against
#: ``observability_alert_events`` and nothing writes one to a captured error, so an
#: ``acknowledged`` filter here would select rows no writer can ever create - an
#: option that only ever returns nothing.
#:
#: This is the ONE place the set is written down, but it cannot be the only place it
#: is ENFORCED: FastAPI needs a static ``Literal`` to render the accepted values into
#: OpenAPI, so the route spells the edge gate separately. That is exactly why
#: ``test_the_error_status_gate_matches_the_facade_vocabulary`` asserts the two agree -
#: widening this filter takes two edits and the test fails if only one is made.
#: #735 widens it when acknowledgement reaches captured errors.
ERROR_STATUS_VOCABULARY: tuple[str, ...] = (ALERT_STATUS_OPEN, ALERT_STATUS_RESOLVED)

__all__ = [
    "AI_JOB_SPEND_STATUS_COMPLETED",
    "AI_JOB_SPEND_STATUS_FAILED",
    "DEFAULT_ACTIVITY_WINDOW_MINUTES",
    "DEFAULT_ALERT_PAGE_SIZE",
    "DEFAULT_ERROR_PAGE_SIZE",
    "DEFAULT_ERROR_WINDOW_MINUTES",
    "DEFAULT_THROUGHPUT_WINDOW_MINUTES",
    "DEFAULT_WINDOW_DAYS",
    "ERROR_STATUS_VOCABULARY",
    "MAX_ACTIVITY_WINDOW_MINUTES",
    "MAX_ALERT_PAGE_SIZE",
    "MAX_ERROR_PAGE_SIZE",
    "MAX_ERROR_WINDOW_MINUTES",
    "MAX_THROUGHPUT_ROUTE_ROWS",
    "MAX_THROUGHPUT_WINDOW_MINUTES",
    "OBSERVABILITY_SCHEMA",
    "ROLLUP_MODE_BACKFILL",
    "ROLLUP_MODE_DAILY",
    "AlertEntry",
    "AlertPage",
    "BreakerHealthRow",
    "BusinessCountView",
    "CaptureLiveness",
    "CostBudgetView",
    "CostSummary",
    "CostTrend",
    "CostTrendPoint",
    "Deeplinks",
    "DependencyHealth",
    "ErrorDrainReport",
    "ErrorFeedEntry",
    "ErrorFeedPage",
    "HttpCounterDrainReport",
    "LatencyReport",
    "LatencyRow",
    "ObservabilityFacade",
    "OutboxHealthRow",
    "Overview",
    "ProviderQualityRow",
    "QualityReport",
    "QueueDepthRow",
    "ReliabilityReport",
    "RollupPlan",
    "RollupReport",
    "RollupRunState",
    "RollupThresholds",
    "RouteThroughputRow",
    "SystemHealth",
    "ThroughputPoint",
    "ThroughputReport",
    "UsageReport",
    "UsageRow",
    "accumulate_ai_usage",
    "accumulate_business_count",
    "close_ai_queue_item",
    "drain_error_buffer",
    "drain_http_counter",
    "error_status",
    "load_rollup_state",
    "plan_rollup_dates",
    "query_alerts",
    "query_cost_summary",
    "query_cost_trend",
    "query_error_feed",
    "query_health",
    "query_latency",
    "query_overview",
    "query_quality",
    "query_reliability",
    "query_throughput",
    "query_usage",
    "record_ai_job_spend",
    "record_ai_queue_open",
    "record_alert_event",
    "record_care_attribution_edge",
    "run_rollup",
    "window_for",
]


async def accumulate_ai_usage(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    payload: AiJobCompletedUsagePayload | AiJobFailedUsagePayload,
) -> None:
    """Accumulate one finished AI job into ``observability_ai_usage_daily``.

    Runs inside the handler's SAME transaction as the ``consumed_events``
    ledger write (the ledger row is recorded first by ``run_handler``), so a
    replayed ``event_id`` skips the effect and a crash rolls both back
    (ADR-0002 §3). The row is keyed by ``(usage_date, provider, model,
    task_type)`` with ``usage_date`` taken from the envelope's occurrence date
    (UTC) and all counters accumulated via ``ON CONFLICT DO UPDATE``.

    Completed jobs increment ``success_count``/``calls``, the token/cost
    totals, ``low_confidence_count`` when the derived flag is set, and fold the
    duration into the running ``avg_duration_ms`` mean over completions. Failed
    jobs increment ``failure_count`` (or ``timeout_count``, mutually exclusive
    buckets - ``calls == success + failure + timeout``). ``p95_duration_ms``
    stays NULL: the percentile columns are (re)computed by the nightly B5
    rollup (#704) from the raw event history, not here.
    """
    table = observability_ai_usage_daily
    usage_date = envelope.occurred_at.date()

    if isinstance(payload, AiJobCompletedUsagePayload):
        success_inc = 1
        timeout_inc = 0
        failure_inc = 0
        low_conf_inc = 1 if payload.low_confidence else 0
        input_inc = payload.input_tokens
        output_inc = payload.output_tokens
        cost_inc = payload.cost_paise
        duration = payload.duration_ms
    else:
        success_inc = 0
        timeout_inc = 1 if payload.timeout else 0
        failure_inc = 1 - timeout_inc
        low_conf_inc = 0
        input_inc = 0
        output_inc = 0
        cost_inc = 0
        duration = None

    if duration is not None:
        # Running mean over completions: the existing mean weighted by the
        # existing success count plus the new duration, over the new count.
        # ``coalesce`` covers rows born from failures (success_count 0 / NULL mean).
        new_avg = (func.coalesce(table.c.avg_duration_ms, 0) * table.c.success_count + duration) / (
            table.c.success_count + 1
        )
    else:
        new_avg = table.c.avg_duration_ms

    statement = (
        insert(table)
        .values(
            usage_date=usage_date,
            provider=payload.provider,
            model=payload.model,
            task_type=payload.task_type,
            calls=1,
            success_count=success_inc,
            failure_count=failure_inc,
            timeout_count=timeout_inc,
            low_confidence_count=low_conf_inc,
            input_tokens=input_inc,
            output_tokens=output_inc,
            cost_paise=cost_inc,
            avg_duration_ms=duration,
            p95_duration_ms=None,
        )
        .on_conflict_do_update(
            index_elements=["usage_date", "provider", "model", "task_type"],
            set_={
                "calls": table.c.calls + 1,
                "success_count": table.c.success_count + success_inc,
                "failure_count": table.c.failure_count + failure_inc,
                "timeout_count": table.c.timeout_count + timeout_inc,
                "low_confidence_count": table.c.low_confidence_count + low_conf_inc,
                "input_tokens": table.c.input_tokens + input_inc,
                "output_tokens": table.c.output_tokens + output_inc,
                "cost_paise": table.c.cost_paise + cost_inc,
                "avg_duration_ms": new_avg,
                "updated_at": func.now(),
            },
        )
    )
    await connection.execute(statement)


async def record_ai_job_spend(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    payload: AiJobCompletedUsagePayload | AiJobFailedUsagePayload,
) -> None:
    """Write ONE granular ``observability_ai_job_spend`` row for one finished AI job.

        B6 (#723). ``observability_ai_usage_daily`` answers "what did this scope
        spend" but has already discarded attribution by the time the day closes.
        This row is the granular source the per-patient and per-doctor numbers are
        computed FROM, so it is kept at one row per job rather than per scope.

        Runs in the same ``run_handler`` transaction as the ``consumed_events``
        ledger row and as :func:`accumulate_ai_usage`, so all three roll back
        together and a replayed ``event_id`` writes none of them.

        PHI-free by construction: the identity references on the payload are hashed
        through :func:`~modules.observability.domain.pseudonym.actor_key` before they
        are written, so the raw patient/doctor reference never lands in this schema
        (ADR-0025 D7). Nothing else on the payload is clinical - the transcript, the
        confidence score and the failure reason stay in ``intake``.

    A failed job records zero tokens and zero cost rather than a fabricated free
        call, mirroring what the daily aggregate does; the row's existence and its
        ``failed`` status are the record of the attempt.

        ``failure_reason`` (#728) is what the provider board names a degradation with,
        so it is kept rather than discarded with the rest of the payload. Two
        things keep it PHI-free, and they are not the same thing: the producer
        emits an operational token rather than a provider body, and
        :func:`sanitize_failure_reason` runs here, BEFORE the write, so what lands
        is one bounded line - a body that echoed request content is reduced to its
        status line. The docstring's "the failure reason stays in ``intake``" is
        about the unredacted reason: this column never holds the provider's words.

        ``ai_job_ref`` is UNIQUE on the table, so this insert is also the enforcement
        of "one row per AI job": the outbox ledger already makes a redelivery of
        the same ``event_id`` a no-op, and a SECOND event about the same job - which no
        current producer emits, since every leg books a fresh job row - would fail
        the constraint instead of quietly doubling one patient's spend.
    """
    if isinstance(payload, AiJobCompletedUsagePayload):
        input_tokens = payload.input_tokens
        output_tokens = payload.output_tokens
        cost_paise = payload.cost_paise
        status = AI_JOB_SPEND_STATUS_COMPLETED
        failure_reason = None
    else:
        input_tokens = 0
        output_tokens = 0
        cost_paise = 0
        status = AI_JOB_SPEND_STATUS_FAILED
        failure_reason = sanitize_failure_reason(payload.reason)

    statement = insert(observability_ai_job_spend).values(
        usage_date=envelope.occurred_at.date(),
        ai_job_ref=payload.ai_job_id,
        intake_ref=payload.intake_id,
        patient_key=actor_key(ACTOR_KIND_PATIENT, payload.patient_id),
        doctor_key=(
            actor_key(ACTOR_KIND_DOCTOR, payload.doctor_id)
            if payload.doctor_id is not None
            else None
        ),
        provider=payload.provider,
        model=payload.model,
        task_type=payload.task_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_paise=cost_paise,
        status=status,
        trace_id=payload.trace_id,
        failure_reason=failure_reason,
    )
    await connection.execute(statement)


async def record_ai_queue_open(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    payload: AiJobQueuedTelemetryPayload,
) -> None:
    """Add one still-open AI job to ``observability_ai_queue_open`` (B5 #729).

    The writer half of #717 decision 16. This table is the OPEN SET of AI work,
    and it exists because the depth and the age have to be DERIVED FROM AN EVENT:
    reading ``intake_ai_jobs`` from here would be a cross-schema read, which
    ADR-0003 forbids, and an enqueue event is what makes the queue measurable at
    all - ``ai_job.completed`` and ``ai_job.failed`` alone describe only what
    became of work that is already finished.

    Runs in the same ``run_handler`` transaction as the ``consumed_events`` ledger
    row, which is written first and gates this effect, so a replayed ``event_id``
    adds nothing and a crash rolls both back together.

    ``enqueued_at`` is the ENVELOPE's ``occurred_at``, not a payload field: the age
    of the oldest queued item is the leading indicator this whole table exists to
    serve, and it must be measured from the instant the delivery was stamped, not
    from a second value the producer supplied and could disagree with.

    ``ON CONFLICT DO NOTHING`` on ``ai_job_ref``, for the same reason the spend
    table's unique key exists: the ledger already makes a redelivery a no-op, and a
    SECOND enqueue event about one job must be a no-op too rather than a silently
    doubled depth.
    """
    statement = (
        insert(observability_ai_queue_open)
        .values(
            ai_job_ref=payload.ai_job_id,
            queue=payload.task_type,
            enqueued_at=envelope.occurred_at,
        )
        .on_conflict_do_nothing(index_elements=["ai_job_ref"])
    )
    await connection.execute(statement)


async def close_ai_queue_item(
    connection: AsyncConnection, payload: AiJobCompletedUsagePayload | AiJobFailedUsagePayload
) -> None:
    """Take one finished AI job back out of ``observability_ai_queue_open`` (B5 #729).

    The other half of :func:`record_ai_queue_open`: completed AND failed close an
    item, so depth is ``enqueued - completed - failed`` by construction rather than
    by a counter somebody has to remember to decrement.

    A close for a job this consumer never saw enqueue deletes nothing and is not an
    error. That is a real case - a completion can be delivered after the enqueue was
    dropped, and a deployment that starts mid-flight has no history at all - and
    treating it as a defect would put a harmless delivery in the dead letter and
    stall the very queue the alert is meant to protect. The depth of a queue is
    then an OVER-count, which the age alert will keep reporting until the item's
    queue drains for real.

    Takes the payload rather than the envelope because the key is the job, not the
    event: both close events name the same ``ai_job_id`` the enqueue wrote.
    """
    statement = delete(observability_ai_queue_open).where(
        observability_ai_queue_open.c.ai_job_ref == payload.ai_job_id
    )
    await connection.execute(statement)


async def record_care_attribution_edge(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    payload: IntakeDoctorAssignedTelemetryPayload,
) -> None:
    """Write ONE ``observability_care_attribution_edges`` row for one doctor pick.

    B7 (#724), the writer half of #717 decision 3. ``observability_ai_job_spend``
    (#723) carries a per-job doctor key, but the transcription and structuring
    legs run BEFORE a pick, so those rows have a NULL one - and a NULL is a gap
    an operator can see, not a placeholder that looks attributed. This row is what
    closes the gap after the fact: the rollup (#725) resolves an intake's spend to
    its doctor through this edge, so late-arriving attribution is reconciled on the
    next pass rather than lost for the day.

    The edge exists only because ``intake.doctor_assigned`` said so. There is no
    other legal source for the pairing: MOD-013 reading the intake or partner
    tables would be a cross-schema read, which ADR-0003 forbids.

    Runs in the same ``run_handler`` transaction as the ``consumed_events`` ledger
    row, which is written FIRST and gates this effect - so a replayed ``event_id``
    writes no edge, and a crash rolls the ledger row and the edge back together.

    PHI-free by construction: both identity references are hashed through
    :func:`~modules.observability.domain.pseudonym.actor_key` before they are
    written, so the raw patient/doctor reference never lands in this schema
    (ADR-0025 D7). Reusing #723's helper verbatim is the point: a key computed at
    consume time has to join one computed at rollup time, and two hashing
    conventions in one schema is how attribution quietly stops reconciling.

    **The conflict rule.** ``intake_ref`` is UNIQUE, so an intake has exactly one
    doctor and this upserts on that key rather than inserting and hoping. A
    genuinely new event about an already-picked intake - a re-pick - OVERWRITES
    the edge, because the newest pick is the intake's current truth and two rows
    would make attribution ambiguous. Overwriting rather than raising is also
    what keeps a data-quality question from becoming an ops incident: an insert
    would abort the transaction holding the ledger row, retry forever and land in
    the dead letter, and the wrong first edge would then be uncorrectable without
    a migration.

    The overwrite is MONOTONIC in ``assigned_at``, not merely last-delivered-wins:
    the guard below drops an arriving event older than the edge it would replace.
    Without it a late delivery of a stale pick - a redelivery the ledger lets
    through because it is a different ``event_id`` - would quietly roll the edge,
    and its ``assigned_at``, backwards to a doctor the patient has moved on from.
    Replay is not re-pick and never reaches here at all: the ledger row is written
    first, so a redelivered ``event_id`` cannot fail the constraint, cannot move
    the edge, and cannot overwrite the provenance columns either.
    """
    statement = insert(observability_care_attribution_edges).values(
        intake_ref=payload.intake_id,
        patient_key=actor_key(ACTOR_KIND_PATIENT, payload.patient_id),
        doctor_key=actor_key(ACTOR_KIND_DOCTOR, payload.doctor_id),
        event_id=envelope.event_id,
        assigned_at=envelope.occurred_at,
    )
    statement = statement.on_conflict_do_update(
        index_elements=["intake_ref"],
        set_={
            "patient_key": statement.excluded.patient_key,
            "doctor_key": statement.excluded.doctor_key,
            "event_id": statement.excluded.event_id,
            "assigned_at": statement.excluded.assigned_at,
        },
        where=statement.excluded.assigned_at >= observability_care_attribution_edges.c.assigned_at,
    )
    await connection.execute(statement)


async def accumulate_business_count(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    metric_key: str,
) -> None:
    """Increment one registry-driven business count in ``observability_business_daily``.

    B4b (#703): the consumer's business-event handlers call this for every
    event type in ``BUSINESS_EVENT_METRICS``. The row is keyed by
    ``(metric_key, metric_date)`` with ``metric_date`` taken from the
    envelope's occurrence date (UTC); ``value`` is JSON so later phases add
    fields without schema churn (plan-phase14 §7.2). The increment is atomic
    via ``ON CONFLICT DO UPDATE``: ``value.count`` is bumped in place, so
    concurrent deliveries of distinct events accumulate without a read-modify-
    write race.

    Runs inside the handler's SAME transaction as the ``consumed_events``
    ledger write (the ledger row is recorded first by ``run_handler``), so a
    replayed ``event_id`` never reaches this effect and a crash rolls both back
    together (ADR-0002 §3).
    """
    table = observability_business_daily
    metric_date = envelope.occurred_at.date()
    existing_count = func.coalesce(cast(table.c.value.op("->>")("count"), Integer), 0)
    statement = (
        insert(table)
        .values(metric_key=metric_key, metric_date=metric_date, value={"count": 1})
        .on_conflict_do_update(
            index_elements=["metric_key", "metric_date"],
            set_={
                "value": func.jsonb_set(
                    table.c.value,
                    literal_column("'{count}'::text[]"),
                    func.to_jsonb(existing_count + 1),
                ),
                "updated_at": func.now(),
            },
        )
    )
    await connection.execute(statement)


async def record_alert_event(connection: AsyncConnection, alert: AlertRow) -> None:
    """Insert one PHI-free alert row into ``observability_alert_events``.

    B4b (#703): the consumer's alert handlers (``audit.tamper_detected``, the
    ``ai_egress.recorded`` guardrail signal) call this. The ``id``, ``status``
    (``open``) and ``created_at`` columns take their server defaults. Like every
    other effect, it runs inside the handler's ledger-first transaction so a
    replayed ``event_id`` is a no-op (ADR-0002 §3).
    """
    await connection.execute(
        insert(observability_alert_events).values(
            severity=alert.severity,
            kind=alert.kind,
            title=alert.title,
            payload=alert.payload,
        )
    )


# ------------------------------------------------------- operator read API (C1)
#
# The nine aggregates the operator observability routes serve (plan-phase14 §9.1),
# projected out of this schema's own tables. No cross-schema SQL: the ledger MOD-013
# accumulated is the system of record (ADR-0003), and a read never joins another
# module's storage to build it. The one exception is the ``/health`` outbox counts,
# which are read through the dispatcher's own sanctioned contract rather than with
# SQL of its own.


class CostBudgetView(BaseModel):
    """One ``(provider, model)`` budget scope: spend against the cap.

    Paise throughout (api-standards §3). ``remaining_paise`` floors at zero and
    ``utilization_pct`` is unbounded above 100, so an overspent scope still reads
    as one overspent scope rather than as a negative remainder.
    """

    provider: str
    model: str
    monthly_limit_paise: int
    alert_threshold_pct: int
    current_spend_paise: int
    billing_period_start: date | None
    billing_period_end: date | None
    remaining_paise: int
    utilization_pct: Decimal
    exhausted: bool


class CostSummary(BaseModel):
    """Spend across the current billing period, plus the per-scope breakdown.

    ``total_spend_paise`` is the sum over ``budgets`` - the whole bill. The cap is
    NOT: ``observability_ai_cost_budget`` holds one snapshotted row per scope, and
    the single bill-wide ``AI_MONTHLY_BUDGET_PAISE`` is written onto every one of
    them, so ``total_limit_paise`` is the cap itself rather than its sum across
    rows. The ``ai_budget`` alert is evaluated against exactly this pair, so the
    headline and the alert cannot disagree.

    ``period_start``/``period_end`` are the bounds the rows carry: the rollup stamps
    them on every snapshot and re-stamps a stale row's period when it resets a
    closed month, so they read as the period the figures belong to. An empty table
    answers zeroes with a ``None`` period, which is "nothing budgeted yet", not
    "spent nothing".
    """

    period_start: date | None
    period_end: date | None
    total_spend_paise: int
    total_limit_paise: int
    remaining_paise: int
    utilization_pct: Decimal
    exhausted: bool
    budgets: list[CostBudgetView]


class CostTrendPoint(BaseModel):
    """One day of the cost trend: what that day cost, and how many calls produced it."""

    usage_date: date
    calls: int
    cost_paise: int


class CostTrend(BaseModel):
    """The daily cost series over the requested window, oldest day first.

    ``days``/``from_date``/``to_date`` echo the window the series was read for, so
    a chart can label its own axis and a caller can see which days are gaps (days
    with no AI job carry no point at all).
    """

    days: int
    from_date: date
    to_date: date
    points: list[CostTrendPoint]


class UsageRow(BaseModel):
    """One ``(provider, model, task_type)`` scope's usage over the window."""

    provider: str
    model: str
    task_type: str
    calls: int
    success_count: int
    failure_count: int
    timeout_count: int
    input_tokens: int
    output_tokens: int
    cost_paise: int


class UsageReport(BaseModel):
    """Calls and tokens by provider and task over the window, plus the totals."""

    days: int
    from_date: date
    to_date: date
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_paise: int
    rows: list[UsageRow]


class ProviderQualityRow(BaseModel):
    """One provider's rolled-up health: the success rate and the breaker state.

    ``success_rate`` is ``None`` for a provider the rollup has no traffic sample
    for, which is not the same as a provider failing every call.
    """

    provider: str
    sample_count: int
    success_rate: Decimal | None
    breaker_state: str


class QualityReport(BaseModel):
    """Output quality over the window, plus the per-provider health breakdown.

    ``success_rate`` is over all calls; ``low_confidence_rate`` is over the
    completions, since a failed job returns no result to have been unconfident
    about. Both are ``None`` rather than zero when their denominator is empty.
    """

    days: int
    from_date: date
    to_date: date
    total_calls: int
    success_count: int
    failure_count: int
    timeout_count: int
    low_confidence_count: int
    success_rate: Decimal | None
    low_confidence_rate: Decimal | None
    providers: list[ProviderQualityRow]


#: Default window of the windowed reads, in days (plan-phase14 §9.1: ``days=30``).
#: The single definition: the routes import it rather than repeating the number,
#: and the facade methods take the window the caller resolved.
DEFAULT_WINDOW_DAYS = 30

#: Two-decimal scale of the percentage figures (``60.00``, not ``60``).
_PCT_QUANTUM = Decimal("0.01")

#: Two-decimal scale of the requests-per-MINUTE average (``6.75``, not ``6.75xx``).
#: Its own constant rather than ``_PCT_QUANTUM`` because the figure is a count and
#: not a percentage, and a reader reaching for the percentage scale there would be
#: reading a name that does not describe what it quantizes.
_PER_MINUTE_QUANTUM = Decimal("0.01")


def window_for(days: int, *, today: date | None = None) -> tuple[date, date]:
    """The inclusive ``[from_date, to_date]`` window of ``days`` UTC days ending today.

    ``days`` counts the days themselves, so ``window_for(1)`` is today alone and the
    default 30-day window covers today plus the 29 days before it. A non-positive
    span is refused rather than silently inverted into a future-dated window.
    """
    if days < 1:
        raise ValueError("days must be positive")
    to_date = today if today is not None else datetime.now(UTC).date()
    return to_date - timedelta(days=days - 1), to_date


def _window_days(from_date: date, to_date: date) -> int:
    """The span of an inclusive window in days - the ``days`` a view echoes back."""
    return (to_date - from_date).days + 1


def _window_minutes(from_ts: datetime, to_ts: datetime) -> int:
    """The span of the half-open ``[from_ts, to_ts)`` minute window.

    Rounded down on purpose: ``to_ts`` is "now" and carries seconds and microseconds,
    so the exact span is a fraction of a minute and a reported ``minutes`` that
    changed every second would be a number no reader could use. The floor keeps the
    denominator a whole number of minute buckets, which is what it divides.
    """
    return max(0, int((to_ts - from_ts).total_seconds()) // 60)


def _per_minute(requests: int, minutes: int) -> Decimal | None:
    """``requests`` spread over ``minutes`` at 2dp; ``None`` when there is no answer.

    Two decimals rather than the four the ratio helpers carry: this figure is a
    count per minute ("6.75"), and a fourth place would be a resolution the grain
    cannot support - one request in a sixty-minute window is 0.0167, which rounds
    to 0.02 and then to nothing at all on a shorter window.

    ``None`` for a zero numerator OR a zero denominator. The numerator case is the
    one that matters and it is stated here because it is easy to get wrong:
    ``error_rate`` is ``None`` only for an EMPTY denominator, and reads
    ``0.0000`` for a window where requests were recorded and none failed. An
    average of zero over a window where nothing was recorded would be a claim
    about the platform that was never measured - the same reason
    :class:`CaptureLiveness` exists.
    """
    if requests <= 0 or minutes <= 0:
        return None
    return (Decimal(requests) / Decimal(minutes)).quantize(
        _PER_MINUTE_QUANTUM, rounding=ROUND_HALF_UP
    )


def _utilization_pct(spend_paise: int, limit_paise: int) -> Decimal:
    """``spend`` as a percentage of ``limit`` at 2dp; an uncapped total reads ``0.00``."""
    if limit_paise <= 0:
        return Decimal("0.00")
    return (Decimal(spend_paise) / Decimal(limit_paise) * 100).quantize(
        _PCT_QUANTUM, rounding=ROUND_HALF_UP
    )


def _budget_view(row: RowMapping) -> CostBudgetView:
    """One ``observability_ai_cost_budget`` row as the cost route answers it.

    The derived columns mirror :class:`~modules.observability.domain.rollup.BudgetSnapshot`
    but are computed here because a read has to survive two shapes the snapshot
    cannot: an uncapped scope (``monthly_limit_paise`` defaults to ``0``) and a row
    the rollup has not stamped a period onto yet (both period columns are nullable).
    An uncapped scope reports ``0.00`` rather than dividing by zero, and is never
    "exhausted" - there is no cap to exhaust.

    ``remaining_paise`` and ``utilization_pct`` are this scope's SHARE against the
    bill-wide cap every row carries (see :func:`query_cost_summary`) - the same
    reading ``BudgetSnapshot`` takes, not a second budget of its own.
    """
    limit = int(row["monthly_limit_paise"])
    spend = int(row["current_spend_paise"])
    capped = limit > 0
    return CostBudgetView(
        provider=row["provider"],
        model=row["model"],
        monthly_limit_paise=limit,
        alert_threshold_pct=int(row["alert_threshold_pct"]),
        current_spend_paise=spend,
        billing_period_start=row["billing_period_start"],
        billing_period_end=row["billing_period_end"],
        remaining_paise=max(0, limit - spend),
        utilization_pct=_utilization_pct(spend, limit),
        exhausted=capped and spend >= limit,
    )


async def query_cost_summary(connection: AsyncConnection) -> CostSummary:
    """Read spend against the budgeted period (``/cost``).

    Spend is the SUM over the rows - each row is one ``(provider, model)`` scope's
    snapshotted month-to-date share (B5a ``build_budget_snapshot``) - so the
    headline is the whole bill, the same total the ``ai_budget`` alert is evaluated
    against.

    The cap is NOT that sum. ``AI_MONTHLY_BUDGET_PAISE`` is ONE cap for the whole
    bill and the rollup writes that same figure onto every scope row, so summing
    ``monthly_limit_paise`` would multiply the budget by the number of scopes and
    understate utilisation. The total cap is the ``max`` over the rows - the one
    cap, and the conservative reading if two rows ever disagree. Every other column
    is derived from that pair, so the headline and the alert cannot disagree.
    """
    rows = await connection.execute(
        select(
            observability_ai_cost_budget.c.provider,
            observability_ai_cost_budget.c.model,
            observability_ai_cost_budget.c.monthly_limit_paise,
            observability_ai_cost_budget.c.alert_threshold_pct,
            observability_ai_cost_budget.c.current_spend_paise,
            observability_ai_cost_budget.c.billing_period_start,
            observability_ai_cost_budget.c.billing_period_end,
        ).order_by(
            observability_ai_cost_budget.c.provider,
            observability_ai_cost_budget.c.model,
        )
    )
    budgets = [_budget_view(row) for row in rows.mappings()]
    total_spend = sum(budget.current_spend_paise for budget in budgets)
    total_limit = max((budget.monthly_limit_paise for budget in budgets), default=0)
    return CostSummary(
        period_start=_earliest_period_start(budgets),
        period_end=_latest_period_end(budgets),
        total_spend_paise=total_spend,
        total_limit_paise=total_limit,
        remaining_paise=max(0, total_limit - total_spend),
        utilization_pct=_utilization_pct(total_spend, total_limit),
        exhausted=total_limit > 0 and total_spend >= total_limit,
        budgets=budgets,
    )


def _earliest_period_start(budgets: Sequence[CostBudgetView]) -> date | None:
    """The oldest period start the budget rows carry, or ``None`` before the rollup."""
    starts = [budget.billing_period_start for budget in budgets if budget.billing_period_start]
    return min(starts) if starts else None


def _latest_period_end(budgets: Sequence[CostBudgetView]) -> date | None:
    """The newest period end the budget rows carry, or ``None`` before the rollup."""
    ends = [budget.billing_period_end for budget in budgets if budget.billing_period_end]
    return max(ends) if ends else None


async def query_cost_trend(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> CostTrend:
    """Read the daily cost series across the window (``/cost/trend``).

    ``observability_ai_usage_daily`` holds one row per
    ``(usage_date, provider, model, task_type)``, so the trend is that table summed
    per day - the daily figure, not the running total. Days with no AI job are
    simply absent from the series; a caller charts them as the gaps they are rather
    than as a spend of zero the rollup never recorded.
    """
    usage = observability_ai_usage_daily
    rows = await connection.execute(
        select(
            usage.c.usage_date,
            func.coalesce(func.sum(usage.c.calls), 0).label("calls"),
            func.coalesce(func.sum(usage.c.cost_paise), 0).label("cost_paise"),
        )
        .where(usage.c.usage_date.between(from_date, to_date))
        .group_by(usage.c.usage_date)
        .order_by(usage.c.usage_date)
    )
    return CostTrend(
        days=_window_days(from_date, to_date),
        from_date=from_date,
        to_date=to_date,
        points=[
            CostTrendPoint(
                usage_date=row["usage_date"],
                calls=int(row["calls"]),
                cost_paise=int(row["cost_paise"]),
            )
            for row in rows.mappings()
        ],
    )


async def query_usage(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> UsageReport:
    """Read calls and tokens per provider/task scope across the window (``/usage``).

    Grouping by ``(provider, model, task_type)`` - the table's own scope key - turns
    the per-day rows into one lifetime-per-window row each, which is the "calls and
    tokens by provider/task" split the plan asks for.
    """
    usage = observability_ai_usage_daily
    rows = await connection.execute(
        select(
            usage.c.provider,
            usage.c.model,
            usage.c.task_type,
            func.coalesce(func.sum(usage.c.calls), 0).label("calls"),
            func.coalesce(func.sum(usage.c.success_count), 0).label("success_count"),
            func.coalesce(func.sum(usage.c.failure_count), 0).label("failure_count"),
            func.coalesce(func.sum(usage.c.timeout_count), 0).label("timeout_count"),
            func.coalesce(func.sum(usage.c.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(usage.c.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(usage.c.cost_paise), 0).label("cost_paise"),
        )
        .where(usage.c.usage_date.between(from_date, to_date))
        .group_by(usage.c.provider, usage.c.model, usage.c.task_type)
        .order_by(usage.c.provider, usage.c.model, usage.c.task_type)
    )
    scopes = [
        UsageRow(
            provider=row["provider"],
            model=row["model"],
            task_type=row["task_type"],
            calls=int(row["calls"]),
            success_count=int(row["success_count"]),
            failure_count=int(row["failure_count"]),
            timeout_count=int(row["timeout_count"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cost_paise=int(row["cost_paise"]),
        )
        for row in rows.mappings()
    ]
    return UsageReport(
        days=_window_days(from_date, to_date),
        from_date=from_date,
        to_date=to_date,
        total_calls=sum(scope.calls for scope in scopes),
        total_input_tokens=sum(scope.input_tokens for scope in scopes),
        total_output_tokens=sum(scope.output_tokens for scope in scopes),
        total_cost_paise=sum(scope.cost_paise for scope in scopes),
        rows=scopes,
    )


async def query_quality(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> QualityReport:
    """Read the quality rates across the window plus per-provider health (``/quality``).

    Two reads of this schema, never one joined query: the window totals come from
    ``observability_ai_usage_daily`` (``success_rate`` over ALL calls,
    ``low_confidence_rate`` over the completions that produced an answer - a failed
    job returns no result to have been unconfident about), while the per-provider
    breakdown is the B5a-computed ``observability_ai_provider_health`` row, whose
    percentiles and breaker state are already rolled up per provider.
    """
    usage = observability_ai_usage_daily
    totals = await connection.execute(
        select(
            func.coalesce(func.sum(usage.c.calls), 0).label("calls"),
            func.coalesce(func.sum(usage.c.success_count), 0).label("success_count"),
            func.coalesce(func.sum(usage.c.failure_count), 0).label("failure_count"),
            func.coalesce(func.sum(usage.c.timeout_count), 0).label("timeout_count"),
            func.coalesce(func.sum(usage.c.low_confidence_count), 0).label("low_confidence_count"),
        ).where(usage.c.usage_date.between(from_date, to_date))
    )
    row = totals.mappings().one()
    calls = int(row["calls"])
    success_count = int(row["success_count"])
    low_confidence_count = int(row["low_confidence_count"])

    health = observability_ai_provider_health
    providers = await connection.execute(
        select(
            health.c.provider,
            health.c.sample_count,
            health.c.success_rate,
            health.c.breaker_state,
        ).order_by(health.c.provider)
    )
    return QualityReport(
        days=_window_days(from_date, to_date),
        from_date=from_date,
        to_date=to_date,
        total_calls=calls,
        success_count=success_count,
        failure_count=int(row["failure_count"]),
        timeout_count=int(row["timeout_count"]),
        low_confidence_count=low_confidence_count,
        success_rate=ratio(success_count, calls),
        low_confidence_rate=ratio(low_confidence_count, success_count),
        providers=[
            ProviderQualityRow(
                provider=entry["provider"],
                sample_count=int(entry["sample_count"]),
                success_rate=entry["success_rate"],
                breaker_state=entry["breaker_state"],
            )
            for entry in providers.mappings()
        ],
    )


class Overview(BaseModel):
    """The operator landing page's headline KPIs (plan-phase14 §9.1).

    One number per question the dashboard opens with: is the bill on plan, is the
    AI working, is anything broken, and is the telemetry itself fresh. Each is
    read from the aggregate that already owns it, so the overview can never
    disagree with the route behind the tile - ``spend_paise`` and friends ARE
    ``/cost``'s headline, and the rates are ``/quality``'s.

    The windowed figures cover ``[from_date, to_date]``; spend and the alert
    counts do not, because the budget is a billing-period figure and an alert
    stays open until a later pass resolves it.
    """

    days: int
    from_date: date
    to_date: date
    total_calls: int
    success_count: int
    success_rate: Decimal | None
    low_confidence_count: int
    low_confidence_rate: Decimal | None
    #: The slowest provider's p95 across the last rolled day - the worst AI
    #: latency the ledger knows of, which is the figure an SLO is written
    #: against. ``None`` until a provider has a rolled latency sample.
    p95_duration_ms: Decimal | None
    spend_paise: int
    budget_paise: int
    budget_utilization_pct: Decimal
    budget_exhausted: bool
    open_alerts: int
    critical_open_alerts: int
    open_breakers: int
    #: The registry-driven business event counts the B4b consumer accumulated over
    #: the window (plan-phase14 §7.2), newest store first by key. The last thing
    #: an operator page shows above the fold: not just that the system is healthy,
    #: but what it actually did today.
    business_counts: list[BusinessCountView]
    #: The newest day the nightly rollup covered - how stale the percentiles,
    #: the budget snapshot and the health rows above can be.
    last_rolled_date: date | None


class LatencyRow(BaseModel):
    """One provider's rolled latency distribution.

    Percentiles come from ``observability_ai_provider_health``, which the nightly
    rollup recomputes over the whole recorded history it can see and stamps with
    the window it ranked. They are therefore "as of the last roll", not "over a
    requested window" - ``window_start``/``window_end`` say which.

    Each percentile is ``None`` for a provider with no timed completion, which is
    not the same as a provider that responded instantly.
    """

    provider: str
    sample_count: int
    p50_duration_ms: Decimal | None
    p95_duration_ms: Decimal | None
    p99_duration_ms: Decimal | None
    window_start: datetime | None
    window_end: datetime | None


class LatencyReport(BaseModel):
    """Per-provider p50/p95/p99, plus how fresh those percentiles are.

    No ``days`` param on purpose: the percentiles are a rolling snapshot the
    rollup writes, not a windowed aggregate the read can re-derive, so a window
    here would describe a period the numbers were never computed over. The HTTP
    server's own route latency rides the OTel ``caresetu.http.server.duration``
    histogram and is read from the OTLP backend, not from Postgres (see
    plan-phase14 §5).
    """

    last_rolled_date: date | None
    providers: list[LatencyRow]


class ProviderBoardRow(BaseModel):
    """One upstream model API on the degraded-provider board (#728).

    Everything a support engineer needs to tell a CareSetu bug from an upstream
    outage, on one row per provider, all read from
    ``observability_ai_provider_health`` - MOD-013's own table, so the board
    introduces no cross-module read (ADR-0003).

    ``status`` is DERIVED at read time from the other fields by
    :func:`~modules.observability.domain.rollup.provider_status`, not stored: a
    stored status is a second source of truth the nightly recompute could leave
    contradicting the row it came from (#717 decision 18).

    ``last_error`` is the newest failure's sanitised operational reason, written
    by the rollup from the day's per-job failure reasons. ``None`` means the
    window recorded no failure to name - which is why it is never the input to
    ``status``: a provider that was refused for quota once and served everything
    else is degraded, not down, and the count beside it is what says so.

    ``timeout_count``, ``rate_limit_count`` and ``sample_count`` are three
    different denominators and are read together: timeouts and quota refusals are
    failures, ``sample_count`` counts only the completions the percentiles were
    ranked over.
    """

    provider: str
    status: ProviderStatus
    breaker_state: str
    success_rate: Decimal | None
    sample_count: int
    timeout_count: int
    rate_limit_count: int
    p50_duration_ms: Decimal | None
    p95_duration_ms: Decimal | None
    p99_duration_ms: Decimal | None
    last_error: str | None
    window_start: datetime | None
    window_end: datetime | None

    @classmethod
    def from_health(cls, health: ProviderHealth) -> ProviderBoardRow:
        """The board row for one rolled provider, ``status`` derived from the rest.

        One place the stored counters become the served shape, so a counter added
        to :class:`ProviderHealth` and to this model is wired here once rather
        than left to two hand-written mappings drifting apart.
        """
        return cls(
            provider=health.provider,
            status=provider_status(health),
            breaker_state=health.breaker_state,
            success_rate=health.success_rate,
            sample_count=health.sample_count,
            timeout_count=health.timeout_count,
            rate_limit_count=health.rate_limit_count,
            p50_duration_ms=health.p50_duration_ms,
            p95_duration_ms=health.p95_duration_ms,
            p99_duration_ms=health.p99_duration_ms,
            last_error=health.last_error,
            window_start=health.window_start,
            window_end=health.window_end,
        )


class ProviderBoardReport(BaseModel):
    """The whole board, one row per provider the rollup has rolled, plus freshness.

    No ``days`` param, for the reason :class:`LatencyReport` gives: every field is
    the nightly rollup's rolling snapshot of one window, not a windowed aggregate
    the read could re-derive. ``last_rolled_date`` and each row's own window bounds
    are how a reader judges how fresh the board is.

    Providers the rollup has never seen are ABSENT rather than listed as healthy.
    An empty list is the honest answer before the first rollup, and a fabricated
    row would read as a provider answering normally.
    """

    last_rolled_date: date | None
    providers: list[ProviderBoardRow]


class CaptureLiveness(BaseModel):
    """Whether request capture ITSELF was working over the window (B9 #727).

        The answer that stops an empty feed reading as a healthy system. "No errors"
        and "nothing was watched" produce the same empty table, and only one of them is
        good news, so the read has to say which it saw - see #717 story 35.

    ``capturing`` is ``True`` iff at least one request was recorded in the window.
    It is deliberately NOT a claim that the counter is unbroken: a dead capture and
    a quiet system are indistinguishable from the rows alone, and inventing a liveness
    verdict that cannot be supported would replace one wrong answer with another.
    What it does support is the honest one - ``requests_recorded`` is a measurement,
    and every rate in the report is ``None`` when NOTHING was recorded (as distinct
    from ``0.0000``, which is a clean window), so a reader cannot mistake a missing
    measurement for a clean one. ``last_recorded_at`` is the next question an operator
    asks ("when did we last see ANY traffic?"), and it is ``None`` rather than an
    invented epoch when nothing was.
    """

    capturing: bool
    requests_recorded: int
    last_recorded_at: datetime | None


class ThroughputPoint(BaseModel):
    """One minute of platform-wide traffic, summed across every route.

    Minutes with no traffic at all are ABSENT rather than zero-filled: a flat line
    of zeros across a quiet night is indistinguishable from a counter that stopped
    recording, and only the gap says which. A chart that needs a continuous axis
    fills the gap client-side, where a fill is a rendering choice rather than a
    claim about the data.
    """

    minute_ts: datetime
    requests: int
    errors: int
    error_rate: Decimal | None


class RouteThroughputRow(BaseModel):
    """One route template's traffic over the whole window.

    Carries the METHOD as well as the template because the pair is the label the
    counter stores and the pair an operator reasons about: a ``POST`` to a template
    is a submission and a ``GET`` on the same path is a fetch, and a merged figure
    would hide one of them. The template is the PATTERN - never a concrete path -
    so no patient identifier can reach this response (ADR-0025 D7).
    """

    route_template: str
    method: str
    requests: int
    errors: int
    error_rate: Decimal | None


class ThroughputReport(BaseModel):
    """Request throughput and error rate over the recent past (B9 #727).

    What the operator needs to tell a real outage from a quiet period (#717 stories
    33 and 34): the totals answer "how much", ``points`` answers "a spike or a
    trickle", and ``routes`` answers "where". Every rate is ``None`` rather than
    ``0`` when nothing was recorded in the window - see :class:`CaptureLiveness`
    for why that distinction is the point of the read.

    ``error_rate`` is the STORED numerator over the STORED denominator: ``errors``
    is the 5xx subset of ``requests``, carried on the counter rows rather than
    re-derived here, so the rate cannot drift from the series it is read beside.
    Client errors are not in it - a 404 is a caller's mistake, not the platform
    failing, and folding 4xx into "error rate" would make a broken frontend link
    read as an outage.

    The window is half-open, ``[from_ts, to_ts)``, which is the only honest
    spelling for a minute-granular series read against "now": an inclusive end
    would put the in-progress minute in the window twice over two reads and make
    the total move as the clock ticks.
    """

    minutes: int
    from_ts: datetime
    to_ts: datetime
    requests: int
    errors: int
    error_rate: Decimal | None
    #: ``requests`` spread over the WHOLE window, so a burst over three minutes is
    #: visibly lower than a steady trickle across all of them. ``None`` when
    #: nothing was recorded, for the same reason ``error_rate`` is.
    requests_per_minute: Decimal | None
    points: list[ThroughputPoint]
    routes: list[RouteThroughputRow]
    #: How many route/method pairs the window holds in total, which is more than
    #: ``routes`` when the busiest exceeded :data:`MAX_THROUGHPUT_ROUTE_ROWS`.
    #:
    #: Capped rather than paginated on purpose. api-standards §4 governs list
    #: ENDPOINTS, and this is a KPI read with a breakdown nested inside it - the same
    #: shape as ``Overview.business_counts``, which is unbounded. A cursor over a
    #: sub-list of an aggregate would be a second navigation inside a panel, and the
    #: number an operator wants off it ("which endpoint is this?") is answered by the
    #: busiest rows. What must not happen is a silent truncation, which is what the
    #: total beside the cap is for.
    routes_total: int
    capture: CaptureLiveness


class DependencyHealth(BaseModel):
    """One dependency's state as this read observed it.

    Two statuses, both reachable, and neither overstated. ``up`` means the read
    itself reached the dependency (the database probe) or the deployment has it
    configured (the cache, which is deliberately never dialled per request - see
    :func:`query_health`). ``disabled`` means the deployment switched it off,
    which for the optional Redis cache is a configuration choice with a SQL
    fallback rather than an outage.

    ``latency_ms`` is the round trip this read measured and is present only when
    one was taken; ``detail`` carries the human-readable reason for a
    ``disabled`` dependency.
    """

    name: str
    status: str
    latency_ms: Decimal | None = None
    detail: str | None = None


class OutboxHealthRow(BaseModel):
    """One outbox table's undelivered and terminally-failed rows.

    Read through ``bus.dispatcher.count_outbox_rows``, never with SQL of this
    module's own: ADR-0003 names the dispatcher the only sanctioned cross-schema
    reader, and the outbox row contract is its to define. ``backlog`` is
    ``pending`` plus ``inflight`` - rows still owed a delivery attempt.

    ``table_schema`` is spelled out rather than named ``schema``, which would
    shadow the pydantic field BaseModel itself carries.
    """

    table_schema: str
    table: str
    pending: int
    inflight: int
    dead_letter: int
    backlog: int


class BreakerHealthRow(BaseModel):
    """One AI provider's recorded breaker state (the rollup observes, never trips)."""

    provider: str
    breaker_state: str


class BusinessCountView(BaseModel):
    """One registry-driven business event's count over the window.

    ``metric_key`` is the ``BUSINESS_EVENT_METRICS`` key the B4b consumer
    accumulates (plan-phase14 §7.2); ``count`` is the ``value.count`` the B4a-style
    increment maintains in ``observability_business_daily``.

    A key with no event in the window is ABSENT rather than zero: the store holds
    what was counted, and inventing a row per registered key would make a metric
    nobody fires look like one that fired and did nothing.
    """

    metric_key: str
    count: int


class SystemHealth(BaseModel):
    """Dependency reachability plus the outbox and circuit-breaker state.

    Everything an operator needs to answer "is something stuck?" without leaving
    the page: whether the stores answered, how much is queued for delivery, how
    many deliveries are terminally failed, and which providers the rollup last
    saw below its success-rate floor.

    A database this read cannot reach is not reported here - with no database
    there are no counts to report either, so the request fails through the app's
    own error path rather than answering 200 with an empty body that an external
    monitor would read as healthy.
    """

    dependencies: list[DependencyHealth]
    outbox: list[OutboxHealthRow]
    outbox_backlog: int
    dead_letter_rows: int
    breakers: list[BreakerHealthRow]
    open_breakers: int


class QueueDepthRow(BaseModel):
    """One AI pipeline queue: how much work is waiting, and how old the oldest is.

    B5 (#729). ``depth`` is ``enqueued - completed - failed``, derived from the
    ``observability_ai_queue_open`` rows rather than kept as a running counter, so
    the figure cannot drift from the events that caused it. One queue per pipeline
    leg (``transcribe``/``structure``/``draft``/``summarize``) - a queue is named by
    the work it holds, not by the module that happened to publish it.

    **The two figures are different signals and neither stands in for the other.**
    ``depth`` is LAGGING: a queue of one row looks identical whether that row was
    enqueued a second ago or an hour ago. ``oldest_age_s`` is LEADING: it is the
    only figure that moves when a queue has stalled rather than filled. An operator
    asking "is it draining" reads the age; one asking "is it backing up" reads the
    depth.

    ``oldest_age_s`` is ``None`` for a queue with nothing waiting, not ``0`` - an
    empty queue has no oldest item, and a zero would read as "the oldest item is
    brand new", which is a claim about work that does not exist.
    """

    queue: str
    depth: int
    oldest_enqueued_at: datetime | None
    oldest_age_s: int | None


class ReliabilityReport(BaseModel):
    """Queue depth and age, per-outbox backlog, and RECENT ACTIVITY (B5 #729).

    The operator's "is anything stuck, and is anyone even using this" read, and the
    surface #717 decision 16/17 asked for.

    Two kinds of queue live here and they are not interchangeable:

    * ``queues`` is the AI PIPELINE queue, derived from the enqueue/completion
      events into this module's own table. It knows how old the oldest waiting job
      is, which is the figure that pages before any depth does.
    * ``outbox`` is the per-MODULE event backlog, counted through the dispatcher's
      sanctioned cross-schema contract. It is broken out per table rather than
      totalled because a total AVERAGES a stuck module away against five healthy
      ones - the breakdown is the whole point of carrying it here. ``outbox_backlog``
      and ``dead_letter_rows`` are the totals an operator scans, and every one of
      them is the sum of the rows beside it.

    **``recent_active_actors`` is ACTIVITY, never concurrency.** It counts
    DISTINCT pseudonymous actors whose work this consumer processed over
    ``activity_window_minutes`` - how many people were here recently, not how many
    are here now. The field name says so, and the only simultaneous figure on this
    surface is the link: ``concurrency_grafana_link`` points at the tracing
    backend's live in-flight metric, which is where a number that changes every
    millisecond belongs. Nothing here approximates or stores it (#717 decision 17).

    ``recent_active_actors`` is counted from this module's own
    ``consumed_events`` ledger, so it needs no table of its own and cannot disagree
    with what was actually consumed: an actor appears here exactly when a delivery
    naming them was applied.
    """

    queues: list[QueueDepthRow]
    queue_depth: int
    oldest_queued_age_s: int | None
    outbox: list[OutboxHealthRow]
    outbox_backlog: int
    dead_letter_rows: int
    recent_active_actors: int
    activity_window_minutes: int
    concurrency_grafana_link: str | None


class AlertEntry(BaseModel):
    """One ``observability_alert_events`` row as the operator feed answers it.

    ``payload`` is the PHI-free map the producers wrote (ids and figures only -
    ``error-handling-observability.md`` §5); the read passes it through rather
    than reshaping it, so an alert reads the same in the feed as it does in the
    database.
    """

    id: UUID
    severity: str
    kind: str
    title: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    acked_by: int | None
    acked_at: datetime | None


class AlertPage(BaseModel):
    """One page of the alert feed, newest first, plus the full match count.

    Paged as api-standards §4 asks, with ``total_count`` counting every matching
    row rather than the page alone, so a client can tell a full page from the end
    of the feed. Ties on ``created_at`` are broken by ``id``, which keeps a page
    stable while a pass is still inserting.
    """

    alerts: list[AlertEntry]
    total_count: int


class ErrorFeedEntry(BaseModel):
    """One DISTINCT captured failure, as the live error feed answers it.

    ``fingerprint`` is the collapse key the drain already upserts on, and it is the
    row's identity here: one entry per failure, with ``occurrences`` saying how many
    times it happened and ``last_seen_at`` when it last did. An operator reading a
    feed wants to know when the failure LAST occurred, so the entry is ordered and
    timestamped on the most recent sighting and never on ``first_seen_at`` - which is
    carried too, because "started this morning" is a different question from
    "happening again right now".

    ``status`` is DERIVED at read time from ``last_seen_at`` against the read's
    window (:func:`error_status`), never stored: there is no writer that marks a
    captured error handled, so a stored status would be a column nothing could ever
    move off its default, which is the same second-source-of-truth problem
    ``provider_status`` refuses.

    ``route_template`` is the TEMPLATE. The capture seam is what keeps this column
    free of concrete request paths, and this model is the other half of that promise:
    it has no field a concrete path could be projected into, so no identifier can
    reach the wire even if a row ever held one (ADR-0025 D7).

    ``trace_id`` is the cross-tool join key (#717 decision 41) - the most recent
    occurrence's, which is the one an operator jumping from this entry wants to land
    on.
    """

    fingerprint: str
    route_template: str
    method: str
    status_code: int
    status_class: str
    kind: str
    code: str
    trace_id: str
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    status: str


class ErrorFeedPage(BaseModel):
    """One page of the live error feed, most recently seen first, plus both totals.

    Paged as api-standards §4 asks, and - because this feed collapses repeats - the
    page carries TWO counts, which are different questions and must not be conflated:
    ``total_count`` is the number of DISTINCT failures matching the filter, which is
    how many entries the feed has; ``total_occurrences`` is the sum of their counts,
    which is how many times the platform actually failed. A single bug that threw four
    hundred times is one entry over four hundred occurrences, and a client labelling
    the page has to know which of the two it is looking at (#717 story 32).

    ``window_minutes`` is echoed so the ``status`` on each entry is interpretable
    without the client having to know the read's default: an entry is ``open`` because
    it was seen inside THAT window, and a caller that widened the window changes which
    entries qualify.

    The page carries NO capture-liveness block. "No errors" and "nothing was watched"
    produce the same empty page, and only ``/throughput``'s ``capture`` distinguishes
    them (#717 story 35); duplicating the verdict here would make two places to keep
    honest for one answer.
    """

    errors: list[ErrorFeedEntry]
    total_count: int
    total_occurrences: int
    window_minutes: int


class Deeplinks(BaseModel):
    """The operator page's outbound vendor links (plan-phase14 §9.1).

    Every key is optional and independently ``None``: a deployment with Sentry but
    no Grafana answers with a Sentry link and an absent Grafana one. The route
    never fails over an unconfigured vendor - see
    :mod:`modules.observability.domain.deeplinks`.
    """

    grafana: str | None = None
    sentry: str | None = None
    langfuse: str | None = None


# ------------------------------------------------------- operator read API (C1b)
#
# The five reads C1b adds. Same rules as C1a above: this module's own tables,
# the dispatcher's sanctioned outbox contract where a cross-schema figure is
# wanted, and vendor URLs derived by pure functions over Settings.


def _elapsed_ms(started: float) -> Decimal:
    """Milliseconds since a :func:`time.perf_counter` reading, at 2dp."""
    return Decimal(f"{(perf_counter() - started) * 1000:.2f}")


async def _last_rolled_date(connection: AsyncConnection) -> date | None:
    """The newest day the nightly rollup covered, or ``None`` before its first pass.

    The freshness marker both ``/overview`` and ``/latency`` carry: every rolled
    figure the operator sees - percentiles, budget snapshots, provider health -
    is only as current as this date.
    """
    result = await connection.execute(
        select(func.max(observability_rollup_runs.c.rollup_date)).select_from(
            observability_rollup_runs
        )
    )
    value = result.scalar()
    return value if isinstance(value, date) else None


async def query_overview(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> Overview:
    """Read the headline KPIs (``/overview``).

    Deliberately composed from the aggregates that already own each figure rather
    than re-derived in one wide query: the spend is ``query_cost_summary``'s
    summary verbatim (so the overview's budget tile is the same arithmetic the
    ``ai_budget`` alert is raised against), the rates are the same windowed sums
    ``/quality`` reads, and the freshness marker is the rollup ledger's newest
    date. One extra read of the budget rows is cheaper than a second copy of the
    cap-versus-spend rule that could drift from the first.
    """
    usage = observability_ai_usage_daily
    totals = await connection.execute(
        select(
            func.coalesce(func.sum(usage.c.calls), 0).label("calls"),
            func.coalesce(func.sum(usage.c.success_count), 0).label("success_count"),
            func.coalesce(func.sum(usage.c.low_confidence_count), 0).label("low_confidence_count"),
        ).where(usage.c.usage_date.between(from_date, to_date))
    )
    row = totals.mappings().one()
    calls = int(row["calls"])
    success_count = int(row["success_count"])
    low_confidence_count = int(row["low_confidence_count"])

    alerts = observability_alert_events
    open_alerts = await connection.execute(
        select(
            func.count().label("open_alerts"),
            func.count()
            .filter(alerts.c.severity == ALERT_SEVERITY_CRITICAL)
            .label("critical_open_alerts"),
        ).where(alerts.c.status == ALERT_STATUS_OPEN)
    )
    alert_row = open_alerts.mappings().one()

    health = observability_ai_provider_health
    provider_health = await connection.execute(
        select(
            func.max(health.c.p95_duration_ms).label("p95_duration_ms"),
            func.count()
            .filter(health.c.breaker_state == BREAKER_STATE_OPEN)
            .label("open_breakers"),
        )
    )
    health_row = provider_health.mappings().one()

    business = observability_business_daily
    business_rows = await connection.execute(
        select(
            business.c.metric_key,
            cast(business.c.value.op("->>")("count"), Integer).label("count"),
        )
        .where(business.c.metric_date.between(from_date, to_date))
        .order_by(business.c.metric_key)
    )

    last_rolled = await _last_rolled_date(connection)
    cost = await query_cost_summary(connection)
    return Overview(
        days=_window_days(from_date, to_date),
        from_date=from_date,
        to_date=to_date,
        total_calls=calls,
        success_count=success_count,
        success_rate=ratio(success_count, calls),
        low_confidence_count=low_confidence_count,
        low_confidence_rate=ratio(low_confidence_count, success_count),
        p95_duration_ms=health_row["p95_duration_ms"],
        spend_paise=cost.total_spend_paise,
        budget_paise=cost.total_limit_paise,
        budget_utilization_pct=cost.utilization_pct,
        budget_exhausted=cost.exhausted,
        open_alerts=int(alert_row["open_alerts"]),
        critical_open_alerts=int(alert_row["critical_open_alerts"]),
        open_breakers=int(health_row["open_breakers"]),
        business_counts=[
            BusinessCountView(metric_key=entry["metric_key"], count=int(entry["count"]))
            for entry in business_rows.mappings()
        ],
        last_rolled_date=last_rolled,
    )


async def query_latency(connection: AsyncConnection) -> LatencyReport:
    """Read each provider's rolled p50/p95/p99 (``/latency``).

    The percentiles are the B5a rollup's own ``observability_ai_provider_health``
    rows, read verbatim with the window it ranked them over - recomputing them
    here would rank a different sample (this request's window) than the one the
    alert thresholds were evaluated against.

    Providers the rollup has no latency sample for are absent entirely: there is
    no row to project, and inventing a zero-percentile provider would read as a
    provider that answered instantly.
    """
    health = observability_ai_provider_health
    rows = await connection.execute(
        select(
            health.c.provider,
            health.c.sample_count,
            health.c.p50_duration_ms,
            health.c.p95_duration_ms,
            health.c.p99_duration_ms,
            health.c.window_start,
            health.c.window_end,
        ).order_by(health.c.provider)
    )
    return LatencyReport(
        last_rolled_date=await _last_rolled_date(connection),
        providers=[
            LatencyRow(
                provider=entry["provider"],
                sample_count=int(entry["sample_count"]),
                p50_duration_ms=entry["p50_duration_ms"],
                p95_duration_ms=entry["p95_duration_ms"],
                p99_duration_ms=entry["p99_duration_ms"],
                window_start=entry["window_start"],
                window_end=entry["window_end"],
            )
            for entry in rows.mappings()
        ],
    )


async def query_provider_board(connection: AsyncConnection) -> ProviderBoardReport:
    """Read every rolled provider's board row (``/providers``).

    ONE table read over ``observability_ai_provider_health`` plus the rollup
    ledger's newest date, both inside this schema. The percentiles, the success
    rate, the breaker state, the timeout and quota-refusal counts and the last
    error were all computed by the same nightly pass and stamped with the window
    it ranked, so re-deriving any of them here would rank a different sample than
    the alerts were evaluated against - and a provider whose traffic stopped
    would have its counters read against a date it was never rolled on.

    ``status`` is derived here rather than selected, which is what makes the
    healthy/degraded/down answer a read-time computation over stored counters
    instead of a stored column a recompute could contradict (#717 decision 18).
    """
    health = observability_ai_provider_health
    rows = await connection.execute(
        select(
            health.c.provider,
            health.c.sample_count,
            health.c.success_rate,
            health.c.timeout_count,
            health.c.rate_limit_count,
            health.c.p50_duration_ms,
            health.c.p95_duration_ms,
            health.c.p99_duration_ms,
            health.c.breaker_state,
            health.c.last_error,
            health.c.window_start,
            health.c.window_end,
        ).order_by(health.c.provider)
    )
    providers: list[ProviderBoardRow] = []
    for entry in rows.mappings():
        rolled = ProviderHealth(
            provider=str(entry["provider"]),
            window_start=entry["window_start"],
            window_end=entry["window_end"],
            sample_count=int(entry["sample_count"]),
            success_rate=entry["success_rate"],
            p50_duration_ms=entry["p50_duration_ms"],
            p95_duration_ms=entry["p95_duration_ms"],
            p99_duration_ms=entry["p99_duration_ms"],
            breaker_state=str(entry["breaker_state"]),
            timeout_count=int(entry["timeout_count"]),
            rate_limit_count=int(entry["rate_limit_count"]),
            last_error=entry["last_error"],
        )
        providers.append(ProviderBoardRow.from_health(rolled))
    return ProviderBoardReport(
        last_rolled_date=await _last_rolled_date(connection),
        providers=providers,
    )


async def query_throughput(
    connection: AsyncConnection, *, from_ts: datetime, to_ts: datetime
) -> ThroughputReport:
    """Read request throughput and error rate over ``[from_ts, to_ts)`` (``/throughput``).

    Three reads of ONE table, never a join: the per-minute series, the number of
    distinct route/method pairs in the window, and the busiest of those pairs. The
    window's TOTAL is summed from the per-minute rows rather than issued as a fourth
    aggregate, which is not an optimisation - the per-minute rows ARE the window's
    truth, so summing them in Python cannot disagree with the series the operator is
    looking at beside them, while a separately issued aggregate could.

    ``routes_total`` counts the pairs the window holds while ``routes`` carries the
    busiest :data:`MAX_THROUGHPUT_ROUTE_ROWS` of them, so a truncated list says so
    instead of quietly under-reporting.

    The half-open window is applied in SQL (``>= from_ts AND < to_ts``) rather than
    in Python, so the index on ``minute_ts`` does the narrowing and a wide window
    never drags the table in. ``to_ts`` is exclusive so the in-progress minute is
    never counted twice across two reads.
    """
    counter = observability_http_minute
    window = (counter.c.minute_ts >= from_ts) & (counter.c.minute_ts < to_ts)

    minute_rows = await connection.execute(
        select(
            counter.c.minute_ts,
            func.coalesce(func.sum(counter.c.requests), 0).label("requests"),
            func.coalesce(func.sum(counter.c.errors), 0).label("errors"),
        )
        .where(window)
        .group_by(counter.c.minute_ts)
        .order_by(counter.c.minute_ts)
    )
    points = [
        ThroughputPoint(
            minute_ts=entry["minute_ts"],
            requests=int(entry["requests"]),
            errors=int(entry["errors"]),
            # A minute with rows cannot have an empty denominator in practice, but
            # the type admits it and ``ratio`` already answers that honestly.
            error_rate=ratio(int(entry["errors"]), int(entry["requests"])),
        )
        for entry in minute_rows.mappings()
    ]

    route_count = await connection.execute(
        select(func.count()).select_from(
            select(
                counter.c.route_template,
                counter.c.method,
            )
            .where(window)
            .distinct()
            .subquery()
        )
    )
    route_rows = await connection.execute(
        select(
            counter.c.route_template,
            counter.c.method,
            func.coalesce(func.sum(counter.c.requests), 0).label("requests"),
            func.coalesce(func.sum(counter.c.errors), 0).label("errors"),
        )
        .where(window)
        .group_by(counter.c.route_template, counter.c.method)
        .order_by(func.sum(counter.c.requests).desc(), counter.c.route_template, counter.c.method)
        .limit(MAX_THROUGHPUT_ROUTE_ROWS)
    )
    routes = [
        RouteThroughputRow(
            route_template=str(entry["route_template"]),
            method=str(entry["method"]),
            requests=int(entry["requests"]),
            errors=int(entry["errors"]),
            error_rate=ratio(int(entry["errors"]), int(entry["requests"])),
        )
        for entry in route_rows.mappings()
    ]

    requests = sum(point.requests for point in points)
    errors = sum(point.errors for point in points)
    minutes = _window_minutes(from_ts, to_ts)
    last_recorded_at = points[-1].minute_ts if points else None
    return ThroughputReport(
        minutes=minutes,
        from_ts=from_ts,
        to_ts=to_ts,
        requests=requests,
        errors=errors,
        # ``ratio`` answers ``None`` for an empty denominator, which is exactly the
        # "nothing was recorded, so nothing failed" answer - never a 0.0000 that
        # reads as a clean window.
        error_rate=ratio(errors, requests),
        requests_per_minute=_per_minute(requests, minutes),
        points=points,
        routes=routes,
        routes_total=int(route_count.scalar_one()),
        capture=CaptureLiveness(
            capturing=requests > 0,
            requests_recorded=requests,
            last_recorded_at=last_recorded_at,
        ),
    )


async def _outbox_health_rows(connection: AsyncConnection) -> list[OutboxHealthRow]:
    """Every module outbox table's undelivered and dead-lettered row counts.

    The ONE place the outbox breakdown is built, so ``/health`` and
    ``/reliability`` cannot report different totals for the same tables. Counts
    come from ``bus.dispatcher``: ADR-0003 names the dispatcher the only sanctioned
    cross-schema reader, so the SELECT stays there and this layer only reshapes its
    rows.

    Every ``*_outbox`` table of every module schema is counted, because a stuck
    outbox is stuck regardless of which module published it - and the rows are kept
    PER TABLE rather than summed, so the caller can tell which module is stuck.
    """
    counts = await count_outbox_rows(
        connection, await discover_outbox_tables(connection, MODULE_SCHEMAS)
    )
    return [
        OutboxHealthRow(
            table_schema=row.table.schema,
            table=row.table.table_name,
            pending=row.pending,
            inflight=row.inflight,
            dead_letter=row.dead_letter,
            backlog=row.backlog,
        )
        for row in counts
    ]


async def query_health(connection: AsyncConnection, *, cache_configured: bool) -> SystemHealth:
    """Read dependency state plus outbox and breaker state (``/health``).

    The database entry is a timed round trip on this very connection, so the
    figure an operator reads is the one this request experienced. The cache entry
    is resolved from Settings and never dialled: the plan's Redis is optional
    with a SQL fallback, so the route must not spend a connection timeout
    discovering that on every dashboard load - an unconfigured cache is reported
    ``disabled``, the configuration choice it is.

    Outbox counts come from :func:`_outbox_health_rows`, the same breakdown
    ``/reliability`` serves, because both answer the same question about the same
    tables and two implementations would eventually disagree.
    """
    started = perf_counter()
    await connection.execute(select(literal(1)))
    dependencies = [
        DependencyHealth(name="database", status="up", latency_ms=_elapsed_ms(started)),
        DependencyHealth(
            name="cache",
            status="up" if cache_configured else "disabled",
            detail=None if cache_configured else "REDIS_URL is unset; reads fall back to SQL",
        ),
    ]

    outbox = await _outbox_health_rows(connection)

    health = observability_ai_provider_health
    breaker_rows = await connection.execute(
        select(health.c.provider, health.c.breaker_state).order_by(health.c.provider)
    )
    breakers = [
        BreakerHealthRow(provider=entry["provider"], breaker_state=entry["breaker_state"])
        for entry in breaker_rows.mappings()
    ]
    return SystemHealth(
        dependencies=dependencies,
        outbox=outbox,
        outbox_backlog=sum(row.backlog for row in outbox),
        dead_letter_rows=sum(row.dead_letter for row in outbox),
        breakers=breakers,
        open_breakers=sum(1 for row in breakers if row.breaker_state == BREAKER_STATE_OPEN),
    )


async def _query_queue_depth(connection: AsyncConnection, now: datetime) -> list[QueueDepthRow]:
    """Per-queue depth and oldest-age over the OPEN AI jobs this consumer holds.

    ``count(*)`` and ``min(enqueued_at)`` over the same rows, grouped by queue, so
    the two figures cannot describe different sets of work - the failing mode of a
    design that keeps depth in a counter and the oldest stamp in a column, where a
    missed close leaves the age pinned at a job that is no longer there.

    Age is computed HERE, in the read, from ``now`` rather than stored: it is the
    difference between two instants, and storing it would make it a number that
    was true when it was written.
    """
    table = observability_ai_queue_open
    rows = (
        (
            await connection.execute(
                select(
                    table.c.queue.label("queue"),
                    func.count().label("depth"),
                    func.min(table.c.enqueued_at).label("oldest_enqueued_at"),
                ).group_by(table.c.queue)
            )
        )
        .mappings()
        .all()
    )
    return [
        QueueDepthRow(
            queue=row["queue"],
            depth=int(row["depth"]),
            oldest_enqueued_at=row["oldest_enqueued_at"],
            oldest_age_s=(
                int((now - row["oldest_enqueued_at"]).total_seconds())
                if row["oldest_enqueued_at"] is not None
                else None
            ),
        )
        for row in rows
    ]


async def _count_recent_active_actors(connection: AsyncConnection, from_ts: datetime) -> int:
    """Distinct pseudonymous actors this consumer applied work for since ``from_ts``.

    Read off ``consumed_events`` - this module's OWN ledger - rather than a table
    of its own, which is what keeps the figure honest for free: an actor is counted
    exactly when a delivery naming them was applied, and a replay (the ledger's
    whole purpose) cannot count them twice.

    The actor is the one-way hash the ledger row's ``handler_result`` carries, not
    an identity reference: the ledger is not a PHI store, and a count of distinct
    hashes answers "how many people" without naming any of them.

    Rows whose ``handler_result`` has no actor key - every handler that is not
    about an actor - are excluded rather than counted as one shared anonymous actor,
    which is the answer a naive ``count(distinct ...)`` with no filter would give.
    The filter is the JSON ``->`` operator rather than a ``has_key`` predicate: the
    ledger column is declared generic ``JSON`` (the outbox DDL factory serves every
    module's ledger), and on PostgreSQL an absent key already extracts as SQL NULL.
    The key name is the writer's constant rather than a literal spelled here, so the
    write and this read cannot drift apart into a board that reads zero.
    """
    table = observability_consumed_events
    actor = table.c.handler_result[HANDLER_RESULT_ACTOR_KEY].as_string()
    statement = select(func.count(func.distinct(actor))).where(
        table.c.processed_at >= from_ts,
        actor.is_not(None),
    )
    counted = await connection.execute(statement)
    return int(counted.scalar_one())


async def query_reliability(
    connection: AsyncConnection, *, minutes: int, now: datetime, grafana_url: str | None
) -> ReliabilityReport:
    """Read queue depth and age, per-outbox backlog, and recent activity.

    B5 (#729). A now-reading with one windowed figure: the queue figures are the
    state as of ``now`` (a queue does not have a window), and only the recent-activity
    count is windowed, by ``minutes``.

    ``now`` is passed in rather than read from the clock so a test can pin the
    instant and get the identical ages production would report at that instant -
    the same reason ``/throughput`` resolves its window in the facade.

    ``minutes`` bounds the activity window and is validated HERE, the one place:
    both the route (whose ``Query`` bounds answer 422) and
    :meth:`~modules.observability.facade.ObservabilityFacade.get_reliability` funnel
    into this function, so a caller that arrives by neither still cannot ask for a
    window of zero or negative minutes and get an answer shaped like a real one.
    """
    if minutes < 1:
        raise ValueError("minutes must be positive")
    queues = await _query_queue_depth(connection, now)
    outbox = await _outbox_health_rows(connection)
    ages = [row.oldest_age_s for row in queues if row.oldest_age_s is not None]
    return ReliabilityReport(
        queues=queues,
        queue_depth=sum(row.depth for row in queues),
        oldest_queued_age_s=max(ages) if ages else None,
        outbox=outbox,
        outbox_backlog=sum(row.backlog for row in outbox),
        dead_letter_rows=sum(row.dead_letter for row in outbox),
        recent_active_actors=await _count_recent_active_actors(
            connection, now - timedelta(minutes=minutes)
        ),
        activity_window_minutes=minutes,
        concurrency_grafana_link=grafana_metric_link(grafana_url),
    )


async def query_alerts(
    connection: AsyncConnection, *, page: int, page_size: int, status: str | None = None
) -> AlertPage:
    """Read one page of the alert feed, newest first (``/alerts``).

    Unfiltered, this is the operator's standing-problems view; ``status`` narrows
    it to what is still open or to what a later pass has resolved. The feed is
    ordered newest first and carries only PHI-free columns, so it can be rendered
    inline on the operator page (plan-phase14 §9.2).

    ``total_count`` is a second aggregate over the same filter rather than
    ``len(alerts)``, so a caller can page back through a long feed without paging
    to find out there is more.
    """
    filter_clause = (
        (observability_alert_events.c.status == status) if status is not None else true()
    )
    counted = await connection.execute(
        select(func.count()).select_from(observability_alert_events).where(filter_clause)
    )
    total = int(counted.scalar_one())

    columns = (
        observability_alert_events.c.id,
        observability_alert_events.c.severity,
        observability_alert_events.c.kind,
        observability_alert_events.c.title,
        observability_alert_events.c.payload,
        observability_alert_events.c.status,
        observability_alert_events.c.created_at,
        observability_alert_events.c.acked_by,
        observability_alert_events.c.acked_at,
    )
    rows = await connection.execute(
        select(*columns)
        .where(filter_clause)
        .order_by(
            observability_alert_events.c.created_at.desc(),
            observability_alert_events.c.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    alerts = [
        AlertEntry(
            id=entry["id"],
            severity=entry["severity"],
            kind=entry["kind"],
            title=entry["title"],
            payload=entry["payload"],
            status=entry["status"],
            created_at=entry["created_at"],
            acked_by=entry["acked_by"],
            acked_at=entry["acked_at"],
        )
        for entry in rows.mappings()
    ]
    return AlertPage(alerts=alerts, total_count=total)


def error_status(last_seen_at: datetime, *, opened_after: datetime) -> str:
    """Whether a failure last seen at ``last_seen_at`` is still ``open``.

    Derived, not stored, and the derivation is the whole argument: a captured error
    has no lifecycle. Nothing resolves it - the drain only counts repeats - so a
    status column could only ever hold whatever default its insert carried, which
    makes it a second source of truth that no writer can contradict and every reader
    has to trust. Recency against the read's own window is derivable from data the row
    already has, which is the same rule ``provider_status`` follows (#717 decision
    18).

    It is a statement about WHEN, not about WHY: ``open`` means the failure was seen
    inside the window, ``resolved`` means it has not been seen since. The words are
    the alert vocabulary's because an operator switching between the two feeds should
    not have to learn that one says "resolved" and the other says "stopped".
    """
    return ALERT_STATUS_OPEN if last_seen_at >= opened_after else ALERT_STATUS_RESOLVED


def _error_status_clause(status: str | None, *, opened_after: datetime) -> ColumnElement[bool]:
    """The WHERE fragment ``status`` selects, or ``true()`` when unfiltered.

    Expressed against ``last_seen_at`` rather than a column so the filter and the
    per-entry ``status`` are the SAME judgement in the database and in
    :func:`error_status`: a filtered page can never return an entry labelled ``open``
    when it was ``resolved``, which is the drift a derived column silently invites.

    An unrecognised status is refused rather than folded into one arm, because the
    failure mode of getting it wrong is an empty feed that reads as "nothing is
    failing" - the same reason the route's ``Literal`` refuses it at the edge.
    """
    if status is None:
        return true()
    if status == ALERT_STATUS_OPEN:
        return observability_error_events.c.last_seen_at >= opened_after
    if status == ALERT_STATUS_RESOLVED:
        return observability_error_events.c.last_seen_at < opened_after
    raise ValueError(
        f"unknown error status {status!r}; expected one of {', '.join(ERROR_STATUS_VOCABULARY)}"
    )


async def query_error_feed(
    connection: AsyncConnection,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
    now: datetime,
    window_minutes: int,
) -> ErrorFeedPage:
    """Read one page of the live collapsed error feed, most recently seen first.

    Served from ``observability_error_events``, which is already one row per distinct
    fingerprint - the collapse happened at the drain, so this query does no grouping
    and cannot produce a different answer than the capture recorded.

    ``now`` is passed in rather than read from the clock, and ``window_minutes`` is
    validated HERE, the one place, for the same two reasons as
    :func:`query_reliability`: a test can pin the instant and get the statuses
    production would report at it, and a caller arriving by neither the route nor the
    facade still cannot ask for a window that decides liveness with a negative span.

    The totals come from ONE aggregate over the same filter the page carries, so
    ``total_count`` and ``total_occurrences`` cannot describe different sets of
    failures - and both are over the FILTER, so a paged client can tell a full page
    from the end of the feed.

    Ordering is ``last_seen_at`` descending, with ``fingerprint`` as the tiebreak
    rather than ``id``: a drain updates a repeat in place, so two failures can share a
    last sighting and the tiebreak is what keeps a page from shuffling while the feed
    is being written.
    """
    if window_minutes < 1:
        raise ValueError("window_minutes must be positive")
    opened_after = now - timedelta(minutes=window_minutes)
    table = observability_error_events
    filter_clause = _error_status_clause(status, opened_after=opened_after)

    counted = await connection.execute(
        select(
            func.count().label("entries"),
            func.coalesce(func.sum(table.c.occurrences), 0).label("occurrences"),
        )
        .select_from(table)
        .where(filter_clause)
    )
    totals = counted.mappings().one()

    rows = await connection.execute(
        select(
            table.c.fingerprint,
            table.c.route_template,
            table.c.method,
            table.c.status_code,
            table.c.status_class,
            table.c.kind,
            table.c.code,
            table.c.trace_id,
            table.c.occurrences,
            table.c.first_seen_at,
            table.c.last_seen_at,
        )
        .where(filter_clause)
        .order_by(table.c.last_seen_at.desc(), table.c.fingerprint.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return ErrorFeedPage(
        errors=[
            ErrorFeedEntry(
                fingerprint=entry["fingerprint"],
                route_template=entry["route_template"],
                method=entry["method"],
                status_code=entry["status_code"],
                status_class=entry["status_class"],
                kind=entry["kind"],
                code=entry["code"],
                trace_id=entry["trace_id"],
                occurrences=entry["occurrences"],
                first_seen_at=entry["first_seen_at"],
                last_seen_at=entry["last_seen_at"],
                status=error_status(entry["last_seen_at"], opened_after=opened_after),
            )
            for entry in rows.mappings()
        ],
        total_count=int(totals["entries"]),
        total_occurrences=int(totals["occurrences"]),
        window_minutes=window_minutes,
    )


def build_deeplinks(
    *,
    grafana_url: str | None = None,
    sentry_dsn: str | None = None,
    langfuse_host: str | None = None,
    langfuse_public_key: str | None = None,
) -> Deeplinks:
    """Derive the vendor deep links from Settings (``/deeplinks``).

    No database and no network: the read is a projection of configuration, so it
    cannot fail because a vendor is absent or unreachable. Each key is derived
    independently, which is what lets a Sentry-only deployment answer with a
    Sentry link and nothing else.
    """
    return Deeplinks(
        grafana=grafana_link(grafana_url),
        sentry=sentry_link(sentry_dsn),
        langfuse=langfuse_link(langfuse_host, langfuse_public_key),
    )


class ObservabilityFacade:
    """Typed public facade for observability.

    The B4 public surface carries the effects the event consumers run. The C1
        (``#706``/``#707``) read seam joins it: ``get_cost_summary``,
        ``get_cost_trend``, ``get_usage``, ``get_quality``, ``get_overview``,
        ``get_latency``, ``get_provider_board`` (#728), ``get_throughput``,
        ``get_health``, ``get_reliability`` (#729), ``get_alerts``,
        ``get_error_feed`` (#730) and ``get_deeplinks`` are what the operator
        observability routes call. Each opens the one settled engine connection and
        delegates its aggregate to the module helper, so routes hold no SQL and the
        reads stay in this module.

        The windowed reads take ``days`` (or, for the per-minute counter, ``minutes``)
        and an optional pinned instant so the caller - or a test - can pin the window;
        the routes own the default and production leaves the instant unset, so the
        facade reads the current UTC day or instant.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_cost_summary(self) -> CostSummary:
        """Read this billing period's spend against the budget (no window)."""
        async with self._engine.begin() as connection:
            return await query_cost_summary(connection)

    async def get_cost_trend(self, *, days: int, today: date | None = None) -> CostTrend:
        """Read the daily cost series over the last ``days`` days."""
        from_date, to_date = window_for(days, today=today)
        async with self._engine.begin() as connection:
            return await query_cost_trend(connection, from_date=from_date, to_date=to_date)

    async def get_usage(self, *, days: int, today: date | None = None) -> UsageReport:
        """Read calls and tokens per provider/task scope over the last ``days`` days."""
        from_date, to_date = window_for(days, today=today)
        async with self._engine.begin() as connection:
            return await query_usage(connection, from_date=from_date, to_date=to_date)

    async def get_quality(self, *, days: int, today: date | None = None) -> QualityReport:
        """Read the quality rates and per-provider health over the last ``days`` days."""
        from_date, to_date = window_for(days, today=today)
        async with self._engine.begin() as connection:
            return await query_quality(connection, from_date=from_date, to_date=to_date)

    async def get_overview(self, *, days: int, today: date | None = None) -> Overview:
        """Read the headline KPIs over the last ``days`` days."""
        from_date, to_date = window_for(days, today=today)
        async with self._engine.begin() as connection:
            return await query_overview(connection, from_date=from_date, to_date=to_date)

    async def get_latency(self) -> LatencyReport:
        """Read the rolled per-provider percentiles (no window - see ``LatencyReport``)."""
        async with self._engine.begin() as connection:
            return await query_latency(connection)

    async def get_provider_board(self) -> ProviderBoardReport:
        """Read the degraded-provider board (no window - see ``ProviderBoardReport``).

        The status on each row is derived by the read, never stored, so this is
        where the healthy/degraded/down answer is produced.
        """
        async with self._engine.begin() as connection:
            return await query_provider_board(connection)

    async def get_throughput(
        self, *, minutes: int, now: datetime | None = None
    ) -> ThroughputReport:
        """Read throughput and error rate over the last ``minutes`` minutes.

        The window is resolved HERE, against the current UTC instant, for the same
        reason the daily reads resolve ``today`` here: the route owns the default
        (:data:`DEFAULT_THROUGHPUT_WINDOW_MINUTES`) and the facade owns the clock,
        so a test can pin ``now`` and get the identical half-open window the
        production read would have taken at that instant.

        ``now`` is used verbatim, NOT truncated to the minute: the counter's rows
        are minute-truncated but the window's exclusive end is an instant on the
        clock, and rounding it down would drop the in-progress minute from every
        read instead of showing it counting up.
        """
        if minutes < 1:
            raise ValueError("minutes must be positive")
        to_ts = now if now is not None else datetime.now(UTC)
        from_ts = to_ts - timedelta(minutes=minutes)
        async with self._engine.begin() as connection:
            return await query_throughput(connection, from_ts=from_ts, to_ts=to_ts)

    async def get_health(self, *, cache_configured: bool) -> SystemHealth:
        """Read dependency reachability plus outbox and breaker state."""
        async with self._engine.begin() as connection:
            return await query_health(connection, cache_configured=cache_configured)

    async def get_reliability(
        self,
        *,
        minutes: int,
        grafana_url: str | None = None,
        now: datetime | None = None,
    ) -> ReliabilityReport:
        """Read queue depth and age, the per-outbox backlog, and recent activity.

        B5 (#729). The clock is resolved HERE, against the current UTC instant, for
        the same reason ``/throughput`` resolves its window here: the route owns the
        default and the facade owns the clock, so a test can pin ``now`` and get the
        identical ages the production read would have reported at that instant.

        ``grafana_url`` is configuration, not storage, so it is passed in by the
        route from Settings and only ever becomes a link - the concurrency figure
        itself stays in the tracing backend (#717 decision 17).

        The window is NOT validated here: :func:`query_reliability` owns that check
        and every path into this read goes through it, so a second copy would only
        be a second place for the two to disagree about what a valid window is.
        """
        to_ts = now if now is not None else datetime.now(UTC)
        async with self._engine.begin() as connection:
            return await query_reliability(
                connection, minutes=minutes, now=to_ts, grafana_url=grafana_url
            )

    async def get_alerts(
        self, *, page: int, page_size: int, status: str | None = None
    ) -> AlertPage:
        """Read one page of the alert feed, optionally narrowed by status."""
        async with self._engine.begin() as connection:
            return await query_alerts(connection, page=page, page_size=page_size, status=status)

    async def get_error_feed(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        minutes: int,
        now: datetime | None = None,
    ) -> ErrorFeedPage:
        """Read one page of the live collapsed error feed (``/errors``, #730).

        The clock is resolved HERE, against the current UTC instant, for the same
        reason ``/throughput`` and ``/reliability`` resolve theirs here: the route
        owns the default and the facade owns the clock, so a test can pin ``now`` and
        get the identical open/resolved split production would have reported at that
        instant.

        ``minutes`` is NOT validated here: :func:`query_error_feed` owns that check
        and every path into this read goes through it, so a second copy would only be
        a second place for the two to disagree about what a valid window is.
        """
        to_ts = now if now is not None else datetime.now(UTC)
        async with self._engine.begin() as connection:
            return await query_error_feed(
                connection,
                page=page,
                page_size=page_size,
                status=status,
                now=to_ts,
                window_minutes=minutes,
            )

    def get_deeplinks(
        self,
        *,
        grafana_url: str | None = None,
        sentry_dsn: str | None = None,
        langfuse_host: str | None = None,
        langfuse_public_key: str | None = None,
    ) -> Deeplinks:
        """Derive the vendor deep links from the configured Settings.

        Synchronous: it reads configuration, never storage. It stays on the facade
        so the routes keep the one seam every other read goes through and the
        derivation has one home to be tested in.
        """
        return build_deeplinks(
            grafana_url=grafana_url,
            sentry_dsn=sentry_dsn,
            langfuse_host=langfuse_host,
            langfuse_public_key=langfuse_public_key,
        )
