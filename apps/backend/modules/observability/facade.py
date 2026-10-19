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

B2 (#731) adds the ``/business`` read: spend for a period, the monthly cap it is
measured against, and a projected month-end burn, broken out by provider, by model
within a provider and by task type, with input and output token volumes reported
SEPARATELY and a rate per thousand on each side. Today, week-to-date and month-to-date
are three windows of ONE period-parameterised read (#717 decision 11), because three
route handlers over three copies of the same aggregation is the failure mode that
decision exists to prevent. Everything spend-shaped is computed at read time out of
``observability_attribution_daily`` - the daily per-actor aggregate #725 writes - so no
figure here has a stored second copy to drift from (#717 decision 8).

B2 (#732) widens that same read rather than adding another one: the per-unit figures
- cost per AI request, per completed task, per patient, per doctor, and cost-of-pass -
plus who the heavy actors are. Top patients and top doctors come off the two actor
kinds of the SAME aggregate, joined by the care-attribution edges #724 records, so the
per-patient and per-doctor totals reconcile through an edge rather than through a
cross-schema join that the module isolation rule forbids. The median, ninety-fifth
percentile and maximum are reported BESIDE the top list rather than as its average,
because a mean over a distribution with one heavy outlier describes nobody. The
revenue and tier dimensions are read and returned as they are - empty - so margin
answers ``null`` carrying a machine-readable not-captured reason rather than a zero a
finance lead could quote (#717 decision 9).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from time import perf_counter
from typing import Any, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, model_validator
from sqlalchemy import (
    CTE,
    ColumnElement,
    Date,
    Integer,
    Table,
    and_,
    cast,
    delete,
    distinct,
    extract,
    func,
    literal,
    literal_column,
    select,
    text,
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
    DEFAULT_GRAFANA_WINDOW,
    GRAFANA_DASHBOARD_UID,
    clean_trace_id,
    grafana_dashboard_link,
    grafana_explore_link,
    grafana_metric_link,
    langfuse_actor_link,
    langfuse_session_link,
    langfuse_trace_link,
    langfuse_traces_link,
    sentry_issues_link,
    sentry_project,
    sentry_trace_link,
)
from modules.observability.domain.exceptions import (
    AlertAlreadyResolvedError,
    AlertNotFoundError,
    ProductOutcomeNotAllowed,
)
from modules.observability.domain.product import (
    FUNNEL_INTAKE,
    FUNNEL_TERMINAL_CASE_CLOSED,
    FUNNEL_TERMINAL_PRESCRIPTION,
    PRODUCT_OUTCOME_ABANDONED,
    PRODUCT_OUTCOME_COMPLETED,
    PRODUCT_OUTCOME_ERRORED,
    PRODUCT_OUTCOME_RE_RECORDED,
    PRODUCT_OUTCOMES,
    ProductOutcome,
    ProductStep,
    ProductStepPayload,
    active_actor_step_names,
    duration_ms_of,
    funnel_stages,
    product_event_keys,
    registered_steps,
    stage_predecessor,
)
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)
from modules.observability.domain.rollup import (
    ALERT_STATUS_ACKNOWLEDGED,
    ALERT_STATUS_OPEN,
    ALERT_STATUS_RESOLVED,
    ALERT_STATUS_VOCABULARY,
    BREAKER_STATE_OPEN,
    ROLLUP_MODE_BACKFILL,
    ROLLUP_MODE_DAILY,
    ProviderHealth,
    ProviderStatus,
    RollupPlan,
    RollupThresholds,
    percentile,
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
    observability_attribution_daily,
    observability_business_daily,
    observability_care_attribution_edges,
    observability_consumed_events,
    observability_error_events,
    observability_http_minute,
    observability_product_actor_daily,
    observability_product_events,
    observability_rollup_runs,
)
from observability.logging import SERVICE_API

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
ERROR_STATUS_VOCABULARY: tuple[str, ...] = (ALERT_STATUS_OPEN, ALERT_STATUS_RESOLVED)

#: The three periods ``/business`` serves, as wire spellings. Named constants rather
#: than bare strings so the route's ``Literal``, this module's validation and the tests
#: all say the same word for the same window - the drift a raw literal invites.
#:
#: Typed as the ``Literal`` each one is, rather than as ``str``, so the route can use
#: them as the DEFAULT of its own ``Literal`` parameter and keep ``mypy --strict``:
#: a default of type ``str`` against a ``Literal`` parameter is a widened value the
#: type system rightly refuses, and widening it back with a cast would throw away the
#: only thing that ties the route's gate to these words.
BUSINESS_PERIOD_TODAY: Literal["today"] = "today"
BUSINESS_PERIOD_WEEK: Literal["week_to_date"] = "week_to_date"
BUSINESS_PERIOD_MONTH: Literal["month_to_date"] = "month_to_date"

#: The periods ``/business`` serves (#731, #717 decision 11). Today, week-to-date and
#: month-to-date are three WINDOWS OF ONE READ, not three reads: each is a different
#: start date against the same end date, so a fourth window is a value here rather
#: than a route, a facade method and a query.
#:
#: The names are the wire spelling and are closed on purpose. An open "period" that
#: fell back to something sensible when it was misspelled would answer 200 with
#: another period's numbers, and an operator would read a whole month's spend as a
#: day's. FastAPI needs a static ``Literal`` to render the accepted values into
#: OpenAPI, so the route spells its gate separately for the same reason
#: :data:`ERROR_STATUS_VOCABULARY` does, and
#: ``test_the_business_period_gate_matches_the_facade_vocabulary`` asserts the two agree.
BUSINESS_PERIODS: tuple[str, ...] = (
    BUSINESS_PERIOD_TODAY,
    BUSINESS_PERIOD_WEEK,
    BUSINESS_PERIOD_MONTH,
)

#: The same three periods as one type, for every hop that takes an already-resolved
#: period. :data:`BUSINESS_PERIODS` is deliberately a ``tuple[str, ...]`` - it is the
#: runtime vocabulary a caller is checked against - so it widens the words back to
#: ``str``; this alias keeps the narrowing for the signatures that never validate
#: anything. Only :func:`period_window` and :func:`query_business`'s callers take a
#: plain ``str``, because those are where an unvalidated value can still arrive.
BusinessPeriod = Literal["today", "week_to_date", "month_to_date"]

#: How many rows ``/business`` returns in each of its top-actor lists (#732). Ten is
#: a panel, not a report: the operator question behind the list is "who is the heavy
#: consumer THIS MONTH", and the answer is the top of the distribution rather than all
#: of it.
#:
#: Not paginated, and deliberately so, for the reason
#: :data:`MAX_THROUGHPUT_ROUTE_ROWS` already is: this bounds the RESPONSE for a panel
#: that renders the whole list, where a cursor would offer a "next page" no panel has
#: room to show. Every actor in the period is aggregated regardless - the distribution
#: beside the list is computed over the whole population - so the cap costs a reader the
#: visibility of the top ten and nothing else, where dropping actors from the
#: aggregation would quietly bend every figure the read exists to report.
MAX_BUSINESS_TOP_ACTORS = 10

#: Why a derived figure is absent, as a closed machine-readable vocabulary (#732).
#:
#: These are statements about the DATA, never about the code, and that is the whole
#: point: a caller switches on the reason, and a reason nobody has a case for cannot be
#: added without a decision at this seam rather than by a developer typing a string.
#: Each one is also rendered into prose by :data:`_UNAVAILABLE_DETAIL` so a panel can
#: say something to a human, but the prose is a translation of the reason and never the
#: reason itself - a string field alone would leave a client parsing English to find
#: out whether a null is "we don't collect that yet" or "the arithmetic broke".
UNAVAILABLE_REVENUE_NOT_CAPTURED: Literal["revenue_not_captured"] = "revenue_not_captured"
UNAVAILABLE_REVENUE_ZERO: Literal["revenue_zero"] = "revenue_zero"

UNAVAILABLE_REASONS: tuple[str, ...] = (
    UNAVAILABLE_REVENUE_NOT_CAPTURED,
    UNAVAILABLE_REVENUE_ZERO,
)

#: The same two reasons as one type, for every signature that takes an already-resolved
#: reason. :data:`UNAVAILABLE_REASONS` is the runtime vocabulary a value is checked
#: against and so widens to ``str``; this alias keeps the narrowing where the model
#: itself does the validating, so a typo is a type error at the call site rather than a
#: validator firing in production.
UnavailableReason = Literal["revenue_not_captured", "revenue_zero"]

#: The human sentence behind each reason. Deliberately separate from the reason
#: itself so the vocabulary above stays a vocabulary: a panel renders this, a client
#: branches on :data:`UNAVAILABLE_REASONS`, and neither has to parse the other.
_UNAVAILABLE_DETAIL: dict[str, str] = {
    UNAVAILABLE_REVENUE_NOT_CAPTURED: (
        "Revenue is not captured yet. The revenue column exists on the daily "
        "aggregate and is empty, so no margin percentage can be computed."
    ),
    UNAVAILABLE_REVENUE_ZERO: (
        "Revenue is captured and is zero for this period, so there is no "
        "denominator for a margin percentage."
    ),
}

__all__ = [
    "ACTIVE_USER_DAY_WINDOW",
    "ACTIVE_USER_MONTH_WINDOW",
    "ACTIVE_USER_SOURCE_CONVENTION",
    "ACTIVE_USER_WEEK_WINDOW",
    "ACTIVE_USER_WINDOW_CONVENTION",
    "AI_JOB_SPEND_STATUS_COMPLETED",
    "AI_JOB_SPEND_STATUS_FAILED",
    "ALERT_STATUS_VOCABULARY",
    "BUSINESS_PERIODS",
    "BUSINESS_PERIOD_MONTH",
    "BUSINESS_PERIOD_TODAY",
    "BUSINESS_PERIOD_WEEK",
    "DEFAULT_ACTIVITY_WINDOW_MINUTES",
    "DEFAULT_ALERT_PAGE_SIZE",
    "DEFAULT_ERROR_PAGE_SIZE",
    "DEFAULT_ERROR_WINDOW_MINUTES",
    "DEFAULT_THROUGHPUT_WINDOW_MINUTES",
    "DEFAULT_WINDOW_DAYS",
    "ERROR_STATUS_VOCABULARY",
    "FUNNEL_DENOMINATOR_CONVENTION",
    "FUNNEL_GAP_CONVENTION",
    "FUNNEL_RATE_CONVENTION",
    "GAP_BASIS_ACTOR",
    "GAP_BASIS_NO_PREDECESSOR",
    "GAP_BASIS_UNAVAILABLE",
    "MAX_ACTIVITY_WINDOW_MINUTES",
    "MAX_ALERT_PAGE_SIZE",
    "MAX_BUSINESS_TOP_ACTORS",
    "MAX_ERROR_PAGE_SIZE",
    "MAX_ERROR_WINDOW_MINUTES",
    "MAX_THROUGHPUT_ROUTE_ROWS",
    "MAX_THROUGHPUT_WINDOW_MINUTES",
    "OBSERVABILITY_SCHEMA",
    "REQUESTS_PER_ACTIVE_USER_CONVENTION",
    "ROLLUP_MODE_BACKFILL",
    "ROLLUP_MODE_DAILY",
    "STICKINESS_CONVENTION",
    "UNAVAILABLE_REASONS",
    "UNAVAILABLE_REVENUE_NOT_CAPTURED",
    "UNAVAILABLE_REVENUE_ZERO",
    "ActiveUserWindow",
    "ActiveUsersDayPoint",
    "ActiveUsersRead",
    "ActorSpendDistribution",
    "AlertAcknowledgement",
    "AlertEntry",
    "AlertPage",
    "BreakerHealthRow",
    "BusinessCountView",
    "BusinessPeriod",
    "BusinessRead",
    "CaptureLiveness",
    "CostBudgetView",
    "CostSummary",
    "CostTrend",
    "CostTrendPoint",
    "Deeplinks",
    "DependencyHealth",
    "DoctorSpend",
    "ErrorDrainReport",
    "ErrorFeedEntry",
    "ErrorFeedPage",
    "FunnelOutcomeTotals",
    "FunnelRead",
    "FunnelStepRow",
    "HttpCounterDrainReport",
    "LatencyReport",
    "LatencyRow",
    "MarginPercent",
    "MarginRead",
    "ModelSpend",
    "ObservabilityFacade",
    "OutboxHealthRow",
    "Overview",
    "PatientSpend",
    "ProjectionBasis",
    "ProviderQualityRow",
    "ProviderSpend",
    "QualityReport",
    "QueueDepthRow",
    "ReliabilityReport",
    "RollupPlan",
    "RollupReport",
    "RollupRunState",
    "RollupThresholds",
    "RouteThroughputRow",
    "SystemHealth",
    "TaskTypeSpend",
    "ThroughputPoint",
    "ThroughputReport",
    "UsageReport",
    "UsageRow",
    "accumulate_ai_usage",
    "accumulate_business_count",
    "acknowledge_alert",
    "close_ai_queue_item",
    "drain_error_buffer",
    "drain_http_counter",
    "error_status",
    "load_rollup_state",
    "period_window",
    "plan_rollup_dates",
    "query_active_users",
    "query_alerts",
    "query_business",
    "query_cost_summary",
    "query_cost_trend",
    "query_error_feed",
    "query_funnel",
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


def _product_actor(step: ProductStep, payload: ProductStepPayload) -> tuple[str | None, str | None]:
    """The ``(actor_kind, actor_key)`` pair one funnel step's row carries.

    Both columns or neither, which is what the table's CHECK enforces and what keeps
    "distinct active actors" from counting a half-filled row. The kind comes from the
    registry entry and the key from the mirror field that kind names, so a step that
    declares an actor kind and a mirror that carries no matching reference produce an
    honest NULL pair rather than a key with no actor behind it.

    The key is hashed through :func:`~modules.observability.domain.pseudonym.actor_key`
    before it is written - the same helper #723's attribution rows use, verbatim, so
    an actor key means one thing across this whole schema (ADR-0025 D7).
    """
    if step.actor_kind is None:
        return None, None
    reference = payload.patient_id if step.actor_kind == ACTOR_KIND_PATIENT else payload.doctor_id
    if reference is None:
        return None, None
    return step.actor_kind, actor_key(step.actor_kind, reference)


async def record_product_event(
    connection: AsyncConnection,
    envelope: Envelope[BaseModel],
    step: ProductStep,
    payload: ProductStepPayload,
) -> None:
    """Write ONE ``observability_product_events`` row for one funnel step.

    B4e (#739), the writer half of #717 decisions 22, 23 and 41. Everything about
    the row - which funnel, which step, which outcome, which actor - comes from the
    ``step`` REGISTRY ENTRY, never from the payload. That is the whole point of the
    registry: a funnel's vocabulary is declared once, in one place, and neither this
    writer nor the daily rollup enumerates steps anywhere else, so adding one is a
    registry line and not a migration.

    Runs inside the handler's SAME transaction as the ``consumed_events`` ledger row,
    which ``run_handler`` writes FIRST and uses to gate this effect. Replay safety is
    therefore enforced twice over, and the second one is the one that matters if the
    first is ever bypassed: ``event_id`` is UNIQUE on this table and the insert is
    ``ON CONFLICT DO NOTHING``, so replaying the same identifiers changes nothing
    whether or not a redelivery is treated as one.

    ``ON CONFLICT DO NOTHING`` rather than an upsert, deliberately. A funnel row is an
    append-only record of one journey moment: overwriting it would let a late
    delivery rewrite a step that already happened, which is the one thing a funnel
    must not do. The daily rollup is where late arrivals are reconciled, because it
    recomputes each day in full rather than accumulating.

    **PHI-free by construction.** No field here is clinical content and no identity
    reference is stored raw: the actor columns hold a one-way hash of the reference
    the producer published, the step/outcome names come from a closed registry
    vocabulary, and ``duration_ms`` is a number the producer measured about its own
    action (security-phii-standards).

    Raises ``ProductOutcomeNotAllowed`` when the registry entry's own outcome is not
    one it declared. That check is not redundant with the registration guard: the
    guard proves the REGISTRY is coherent, and this proves the WRITER is reading that
    same entry - a writer that invented or defaulted an outcome would slip past a
    coherent registry entirely. Decision 24 ("a degraded fallback is ``errored``, not
    a quiet abandonment") and decision 25 ("a re-record is its own outcome") live in
    ``allowed_outcomes``, so this is where they are enforced rather than merely
    documented.
    """
    if step.outcome not in step.allowed_outcomes:
        raise ProductOutcomeNotAllowed(step.step, step.outcome, step.allowed_outcomes)
    actor_kind, actor_key_value = _product_actor(step, payload)
    trace_id, session_key = product_event_keys(payload, event_id=envelope.event_id)
    statement = insert(observability_product_events).values(
        event_id=envelope.event_id,
        # The ENVELOPE's occurrence, never a payload field: a step-to-step gap has to
        # be measured from when the delivery was stamped, so it cannot depend on a
        # second value a producer might disagree with.
        occurred_at=envelope.occurred_at,
        actor_kind=actor_kind,
        actor_key=actor_key_value,
        session_key=session_key,
        trace_id=trace_id,
        funnel=step.funnel,
        step=step.step,
        outcome=step.outcome,
        duration_ms=duration_ms_of(payload),
    )
    statement = statement.on_conflict_do_nothing(index_elements=["event_id"])
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

#: Two-decimal scale of the requests-per-ACTIVE-USER average, for the same reason as
#: :data:`_PER_MINUTE_QUANTUM`: it is a count per person, not a percentage, and the
#: name says which.
_PER_USER_QUANTUM = Decimal("0.01")


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


def _per_active_user(requests: int, active_users: int) -> Decimal | None:
    """``requests`` per active user at 2dp; ``None`` when either side is zero.

    The same two ``None`` cases as :func:`_per_minute` and for the same reasons: an
    empty denominator has no rate, and a window where nobody was active has no
    per-person figure to report. A measured ``0.00`` is a real answer here - requests
    were served by the actors who were there - while ``None`` says the figure was
    never measured.
    """
    if requests <= 0 or active_users <= 0:
        return None
    return (Decimal(requests) / Decimal(active_users)).quantize(
        _PER_USER_QUANTUM, rounding=ROUND_HALF_UP
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
    total_limit, total_spend = _budget_totals(budgets)
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


def _budget_totals(budgets: Sequence[CostBudgetView]) -> tuple[int, int]:
    """The bill-wide ``(cap, consumed)`` pair the snapshot rows add up to.

    The cap is the ``max``, NOT the sum: the rollup writes the single bill-wide
    ``AI_MONTHLY_BUDGET_PAISE`` onto EVERY scope row, so summing it would multiply the
    budget by the number of scopes and understate utilisation. The consumed figure IS
    the sum, because each row carries that scope's own share of the one bill.

    One helper for both reads that need the pair - ``/cost``'s headline and
    ``/business``'s cap - because the ``ai_budget`` alert is evaluated against exactly
    this pair and two copies of the rule is two places for them to disagree.
    """
    cap = max((budget.monthly_limit_paise for budget in budgets), default=0)
    return cap, sum(budget.current_spend_paise for budget in budgets)


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


class AlertAcknowledgement(BaseModel):
    """The outcome of one acknowledgement: the row as it now stands, and whose claim won.

    ``already_acknowledged`` is the conflict rule made observable. A repeat is not a
    409 - the write is idempotent and the first acknowledgement stands - so without
    this flag a 200 on the second call would be read as "I am the one who took this"
    when the columns say it was somebody else.
    """

    alert: AlertEntry
    already_acknowledged: bool


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


#: How a step's ``entered`` and its conversion relate, in the words a client can put
#: on screen. Sent rather than documented, because the convention is the one thing a
#: reader cannot derive from the numbers: two funnels can agree on every count and
#: still disagree about what a conversion is a fraction OF, and a client that picked
#: its own convention would silently publish a different product.
FUNNEL_DENOMINATOR_CONVENTION = (
    "entered is every ledger row the step wrote in the window that is in scope - every "
    "outcome when no outcome filter is given, and only that outcome when one is - and "
    "conversion_from_previous is this step's entered over the entered of the nearest "
    "preceding non-terminal step, which may exceed 1 where a step was reached without "
    "passing its predecessor"
)

#: What the two headline rates divide, which is a different convention from the steps'
#: and just as un-guessable: the numerator of a rate is the one figure a reader has to
#: be told, because "abandonment rate" means anything from "of the journeys that
#: started" to "of the arrivals at each step" and the two disagree whenever anyone
#: abandons more than once.
FUNNEL_RATE_CONVENTION = (
    "both rates divide started, the entry step's entered count: task_success_rate's "
    "numerator is every COMPLETED row at a terminal step, and abandonment_rate's is "
    "every abandoned row across the funnel's steps. They are not complementary - a "
    "journey that abandoned, re-recorded and carried on is counted in both"
)

#: How the median gap was measured, in the same spirit. A gap with no stated basis
#: is a gap nobody can defend, and the one the ledger cannot measure today is named
#: here rather than reported as a zero.
FUNNEL_GAP_CONVENTION = (
    "median_gap_from_previous_s pairs each row of a step with the most recent COMPLETED "
    "row of its predecessor step for the same pseudonymous actor at or before it, "
    "inside the same window - which on the doctor half of the funnel pairs a doctor's "
    "own consecutive clinical actions rather than one case's journey, because the "
    "ledger stores no case identifier to pair on. gap_basis says which key paired them: "
    "'actor_key' where they share one, 'no_predecessor' where there is no step before "
    "it, and 'unavailable' where they share none - which today is the "
    "patient-to-doctor handoff into consult_complete"
)

#: The ``gap_basis`` values. One says the pair was measured on the actor key, one says
#: there was nothing before it to measure from, and the last says the ledger holds no
#: key the two steps share - which is a different fact from a step nobody passed, and
#: a null median with either of the last two is unmeasured rather than zero.
GAP_BASIS_ACTOR = "actor_key"
GAP_BASIS_NO_PREDECESSOR = "no_predecessor"
GAP_BASIS_UNAVAILABLE = "unavailable"


class FunnelStepRow(BaseModel):
    """One step of the walk: how many arrived, how they ended, how long they took.

    ``entered`` counts EVERY row the step wrote in the window and ``completed``,
    ``abandoned`` and ``errored`` split it by outcome, so the step's own figures can
    never describe different populations. A step whose journey was corrected is
    counted ``re_recorded`` on its own row rather than against either failure
    outcome, which is decision 25's rule arriving as a shape rather than as prose.

    With an ``outcome`` filter on the read, every one of those counters is narrowed to
    THAT outcome and the row is the abandoned (or errored, or corrected) arrivals at
    this step on their own - which is what isolating that path means.
    :data:`FUNNEL_DENOMINATOR_CONVENTION`, which the response carries verbatim, says
    so in the same words.

    **``conversion_from_previous`` is not a percentage of successes.** Its denominator
    is the nearest preceding NON-TERMINAL step's ``entered`` - see
    :data:`FUNNEL_DENOMINATOR_CONVENTION` - so a step reached without passing its
    predecessor reports a figure above ``1`` instead of being clamped.
    ``previous_step`` is in the row so the denominator is readable without walking the
    list, and is ``null`` on the first stage, whose conversion is ``null`` rather than
    a division by zero.

    ``median_gap_from_previous_s`` is the THINKING time between the two steps, not
    the step's own machine time (``duration_ms`` on the ledger row is that, and this
    read deliberately does not repeat it): the gap pairs this step's row with its
    predecessor's row for the same actor, so it includes the time a patient spent
    deciding. ``gap_samples`` says how many pairs the median was taken over, and
    ``gap_basis`` says what paired them; a ``null`` median with a basis other than
    ``actor_key`` is unmeasured rather than instant.

    ``latest_trace_id`` is the most recent row's, from the same window as the counts.
    It is what makes the number defensible: every count here is backed by a journey an
    operator can open (#717 story 81).
    """

    step: str
    event_type: str
    terminal: bool
    previous_step: str | None
    entered: int
    completed: int
    abandoned: int
    errored: int
    re_recorded: int
    conversion_from_previous: Decimal | None
    median_gap_from_previous_s: Decimal | None
    gap_samples: int
    gap_basis: str
    latest_trace_id: str | None


class FunnelOutcomeTotals(BaseModel):
    """Did the workflows finish? Success and abandonment, over ONE denominator.

    **The two rates are one block because they must never be quoted apart.** A reader
    shown "92% task success" and no abandonment rate concludes the product works;
    shown "8% abandonment" and no success rate concludes it does not. Both live here,
    over the same ``started``, so the pair is the answer rather than two numbers a
    client picks one of.

    Both divide ``started`` - the funnel's entry step's ``entered`` - so they are
    directly comparable. They are deliberately NOT complementary and their sum need
    not be ``1``: a workflow that abandons, re-records and carries on to an issued
    prescription is counted in both figures, which is the honest reading of a funnel
    measured in arrivals rather than in people. Forcing them to partition would mean
    choosing which one the re-record belongs to, and decision 25 already refused that
    choice.

    ``issued_e_prescriptions`` and ``cases_closed`` are reported apart and BOTH count
    towards ``task_success_rate``: an issued e-prescription and a closed case are two
    legitimate ends of the same journey, and a shape that folded them together could
    not tell a practice whether its consultations ended in a prescription or not
    (#717 decision 23). Both count their COMPLETED rows only - a case closed under an
    error or abandoned on the way out is not a finished consultation, and scoring it as
    one would make a broken end look like the good one.

    ``errored`` and ``re_recorded`` ride the same block for the same reason. An
    ``errored`` count is a degraded fallback the registry scored as an error rather
    than as a quiet abandonment (decision 24), and a ``re_recorded`` count is a
    correction rather than a failure of the attempt it replaces (decision 25).
    """

    started: int
    task_success_rate: Decimal | None
    abandonment_rate: Decimal | None
    issued_e_prescriptions: int
    cases_closed: int
    abandoned: int
    errored: int
    re_recorded: int


class FunnelRead(BaseModel):
    """The funnel from the moment a patient opened the composer, with its conventions.

    ``steps`` is the walk in order - the entry step through the terminal branch -
    and each row carries its own completion, abandonment, conversion and gap. The
    walk is driven from the funnel-step registry rather than restated here, so a step
    registered tomorrow appears here without a second list to forget.

    ``outcome`` narrows the STEPS to those that can end in that outcome and narrows
    each reported row to that outcome's own counts, which is how an operator isolates
    the abandoned path: ``outcome=abandoned`` answers "where do people walk away, and
    how many of them", with nothing else on the row to quote instead.

    It deliberately does NOT narrow ``outcomes``: success and abandonment are the
    headline verdict on the whole window, and quoting either of them measured over a
    different population than the other would be the exact failure
    :class:`FunnelOutcomeTotals` exists to prevent. The response carries
    ``denominator_convention``, ``rate_convention`` and ``gap_convention`` because all
    three are conventions a reader cannot derive from the numbers.

    ``window_start``/``window_end`` echo the instants the figures were read for, and
    ``window_days`` the span between them, so a client drawing the funnel does not
    have to keep its own clock to label what it is showing.
    """

    funnel: str
    window_start: datetime
    window_end: datetime
    window_days: int
    outcome: str | None
    denominator_convention: str
    rate_convention: str
    gap_convention: str
    steps: list[FunnelStepRow]
    outcomes: FunnelOutcomeTotals


# ------------------------------------------------------- the active users read (#741)


#: The three rolling windows, in DAYS, that "daily, weekly and monthly active users"
#: name. Spelled as constants rather than as literal 1/7/30 at the call sites because
#: they are a stated convention (see :data:`ACTIVE_USER_WINDOW_CONVENTION`) and a
#: reader comparing two responses has to be able to check them.
ACTIVE_USER_DAY_WINDOW = 1
ACTIVE_USER_WEEK_WINDOW = 7
ACTIVE_USER_MONTH_WINDOW = 30

#: What each of the three figures counts and over which window. A daily, weekly and
#: monthly figure quoted without its window is three numbers nobody can compare, and
#: the mistake this read exists to prevent is reading a rolling MONTHLY base off a
#: fourteen-day vendor window and reporting the gap as a collapse in adoption.
ACTIVE_USER_WINDOW_CONVENTION = (
    "each figure counts DISTINCT pseudonymous actors who performed a qualifying clinical "
    "action, over a rolling window ENDING ON to_date: daily is to_date alone, weekly is "
    "the seven days to_date - 6 .. to_date, monthly is the thirty days to_date - 29 .. "
    "to_date. They are three different actor SETS, never multiples of one another - a "
    "person active on three days of the week counts once"
)

#: Where the actor set comes from, and what it is not. There is no authentication,
#: session or logout event anywhere in the product-step registry and
#: ``register_product_step`` refuses one, so a login could not be counted here even by
#: accident (spec decision 26).
ACTIVE_USER_SOURCE_CONVENTION = (
    "active users are counted from the product event ledger's qualifying clinical steps - "
    "the registered steps that name an actor kind - and never from a login: there is no "
    "authentication, session or logout event in the registry, and registering one is "
    "refused. A step a machine finished records no actor and counts nobody. Actors are "
    "pseudonymous keys domain-separated per kind, so patients and doctors are disjoint "
    "sets and total is their sum"
)

#: How stickiness is defined. The usual one is daily over monthly; the response says
#: so rather than leaving a bare ratio to be quoted out of context, which is how a
#: stickiness figure ends up meaning daily-over-weekly in one deck and daily-over-monthly
#: in another.
STICKINESS_CONVENTION = (
    "stickiness is daily_active_users.total over monthly_active_users.total - the usual "
    "DAU/MAU definition - rendered as a fraction at 4dp, not a percentage. It is null "
    "when nobody was active in the rolling month, which is 'no base to divide by' rather "
    "than zero"
)

#: What requests-per-active-user divides. The denominator is the WINDOW's active users,
#: not the day's, so the numerator and the denominator span the same days; a per-user
#: figure whose two halves cover different windows is not a per-user figure.
REQUESTS_PER_ACTIVE_USER_CONVENTION = (
    "requests_per_active_user is the window's total requests over the window's own "
    "distinct active users - both sides covering the same days - rendered at 2dp. It is "
    "null when either side is zero: no traffic and no actors are unmeasured, not a "
    "measured zero. The total is the sum of the days the counter actually recorded; a "
    "day with no row contributes nothing and is ABSENT from the trend rather than "
    "zero-filled, so the figure and the series cannot disagree. Requests are counted "
    "over every route, the same sum the throughput read reports, and include the "
    "operator console's own traffic"
)


class ActiveUserWindow(BaseModel):
    """One window's distinct active actors, split by the kind of person.

    ``window_days``/``from_date``/``to_date`` travel with the counts rather than being
    assumed by the reader, because the three headline figures are three DIFFERENT
    windows and the one that makes a daily number look like a monthly one is quoting
    it without saying which.

    ``total`` is ``patients + doctors``, which is exact rather than approximate: an
    actor key is a hash whose preimage includes its actor kind
    (:func:`~modules.observability.domain.pseudonym.actor_key`), so a patient and a
    doctor sharing a database serial cannot share a key, and no actor is counted twice
    by summing the two columns.
    """

    window_days: int
    from_date: date
    to_date: date
    patients: int
    doctors: int
    total: int


class ActiveUsersDayPoint(BaseModel):
    """One day of the window: the load served and the people who caused it.

    A day with NOTHING recorded is ABSENT rather than zero-filled, following
    :class:`ThroughputPoint`: a run of zeros across a quiet stretch and a counter that
    stopped recording produce the same flat line, and only the gap tells them apart.
    The window's ``requests`` total beside the series says how much the series is
    missing.

    A day that recorded traffic but no actor is present with ``active_users`` 0, which
    is the honest reading of an operator console poll, and its
    ``requests_per_active_user`` is ``null`` rather than a division by zero.
    """

    day: date
    requests: int
    active_users: int
    requests_per_active_user: Decimal | None


class ActiveUsersRead(BaseModel):
    """Is adoption growing? - DAU, WAU, MAU, stickiness and load per head (#741).

    Five questions on one surface because they are one question: are more people here
    than last week, do they come back, does the daily habit hold against the monthly
    base, and how much of the platform's load is each of them responsible for.

    **Every figure here is computed in Postgres, and that is the point.** The free
    metrics tier keeps fourteen days, so a monthly active-user number is not a query
    the vendor can answer - the data is gone before the question is asked - and a
    report that silently returned a fourteen-day base labelled "monthly" would be
    worse than no report. The product event ledger is the system of record, so a
    thirty-day window returns a real number rather than a truncated one.

    ``window_active_users`` is the requested window's own distinct actors and is the
    denominator of ``requests_per_active_user``; it is NOT a fourth DAU/WAU/MAU
    figure, and it is the one that follows the ``days`` parameter - see
    :data:`REQUESTS_PER_ACTIVE_USER_CONVENTION`.

    ``trend`` is at DAY grain rather than the counter's minute grain, because a
    thirty-day window at minute grain is forty-three thousand points and no chart draws
    them. The per-minute series is ``/throughput``'s job and stays there.
    """

    days: int
    from_date: date
    to_date: date
    daily_active_users: ActiveUserWindow
    weekly_active_users: ActiveUserWindow
    monthly_active_users: ActiveUserWindow
    window_active_users: ActiveUserWindow
    stickiness: Decimal | None
    requests: int
    requests_per_active_user: Decimal | None
    trend: list[ActiveUsersDayPoint]
    window_convention: str
    source_convention: str
    stickiness_convention: str
    requests_per_active_user_convention: str


# ----------------------------------------------------- the retention cohorts read (#742)

#: The two horizons "seven- and thirty-day retention" names, in DAYS. Seven is the
#: habit question - did the person come back next week - and thirty is the adoption
#: question - did they become a monthly user. Spelled as constants because they are a
#: stated convention (:data:`RETENTION_WINDOW_CONVENTION`) rather than a literal at the
#: call site, and because both horizons are applied by the SAME query with only this
#: number changing.
RETENTION_WEEK_WINDOW = 7
RETENTION_MONTH_WINDOW = 30

#: The horizons, in the order they are queried and reported. One constant rather than
#: the pair written at both use sites, so a third horizon could not be queried and left
#: out of the response - or reported without ever being measured.
_RETENTION_HORIZONS: tuple[int, ...] = (RETENTION_WEEK_WINDOW, RETENTION_MONTH_WINDOW)

#: The ``/product/retention-cohorts`` default, in COHORT DATES. It carries its own
#: default rather than borrowing :data:`DEFAULT_WINDOW_DAYS` for the same reason
#: ``_MinuteWindow`` carries its own ceiling: the two windows are not the same shape.
#: ``DEFAULT_WINDOW_DAYS`` counts days of SERIES ending today, and on this read the
#: right-hand end of the series is where nothing can be measured yet - the newest
#: cohort whose thirty-day horizon has arrived sits thirty days back. A thirty-date
#: window therefore returns thirty rows whose thirty-day figures are ALL null, which
#: is the honest answer and a useless default: the half of the table a product manager
#: opens the page for would be empty. Sixty dates buys thirty fully-mature cohorts and
#: thirty that are still filling in, which is the shape a cohort table is read in.
RETENTION_DEFAULT_COHORT_DAYS = RETENTION_MONTH_WINDOW * 2

#: What a cohort IS, and what the window it travels over covers. A retention figure is
#: meaningless without its denominator - "40% retained" is a triumph or a disaster
#: depending on whether the cohort was nine people or nine thousand - so every row
#: carries the cohort size beside the rate and every rate is a fraction, not a
#: percentage.
RETENTION_WINDOW_CONVENTION = (
    "a cohort is the set of actors whose FIRST EVER recorded qualifying clinical action "
    "falls on cohort_date - not their first action inside this window, so a patient who "
    "arrived last year and came back on Tuesday joins no cohort today. The two horizons "
    "are cohort_date + 7 days and cohort_date + 30 days, measured on that EXACT day (the "
    "classic day-N retention), and reported at 4dp as retained / cohort_size: a cohort that "
    "came back on day nine and never again is not a day-30 cohort. cohort_size travels with "
    "every rate because '40% retained' means nothing without its denominator. days governs "
    "how many consecutive cohort DATES are reported, ending on to_date, and is not a "
    "truncation of either horizon: a seven-date read still reports the full thirty-day figure "
    "for each of its seven dates. The default is 60 dates rather than 30 precisely so the "
    "thirty-day column has values in it - the newest cohort that can be measured at thirty "
    "days is thirty days old"
)

#: Why a young cohort reports ``null`` rather than zero. This is the distinction the
#: whole read turns on: a cohort three days old has not been GIVEN the chance to come
#: back on day thirty, and writing zero for it would put a fabricated collapse at the
#: right-hand end of every chart, where a real decline would be invisible next to it.
RETENTION_MATURITY_CONVENTION = (
    "a cohort whose cohort_date + 7 (or + 30) is later than to_date has not reached that "
    "horizon yet, and reports retained and retention as null - 'not yet observed', which is "
    "NOT zero. Zero means observed and nobody came back; null means the horizon is still in "
    "the future. A date on which nobody arrived has cohort_size 0 and reports null for both "
    "horizons as well: 'none of them came back' is not a measurement of an empty set, and a "
    "chart reading it as a total retention collapse would be reading the absence of a cohort "
    "as the loss of one. Where a rate exists it is retained over that cohort's own size, "
    "which is never zero - there is no such thing as a rate on an empty base"
)

#: Where the cohorts come from, and the one thing they are not computed from. The daily
#: actor aggregate is the system of record's own materialisation of the product ledger,
#: so these figures outlive the free vendor tier's fourteen-day retention, and the raw
#: ledger is not scanned even once to produce a thirty-day answer.
RETENTION_SOURCE_CONVENTION = (
    "cohorts are derived at READ time from observability_product_actor_daily, the nightly "
    "per-actor day aggregate MOD-013 recomputes from the product event ledger - one row per "
    "pseudonymous actor per day they did a qualifying clinical action. The raw ledger is "
    "never scanned: it is read once a night by the rollup and never by this query, so a "
    "thirty-day question costs thirty days of AGGREGATE rows rather than thirty days of "
    "events. Nothing here is stored: a stored retention rate would be a second source of "
    "truth that disagrees with the daily aggregate after any recompute. Actors are "
    "pseudonymous keys domain-separated per kind, so no name, phone number or clinical "
    "content reaches this response"
)

#: Which actors count. Identical to the active-users set (#741), deliberately: two
#: adoption numbers built on two definitions would be the more confusing thing to have,
#: and a cohort whose members are not the people the DAU counts is not a cohort of users.
RETENTION_ACTOR_CONVENTION = (
    "cohort membership requires a qualifying clinical action - the registry's active-actor "
    "steps, the same set /product/active-users counts - so a machine step records no actor "
    "and joins no cohort, and there is no login to count: the registry refuses registering "
    "one. cohort_size counts DISTINCT actors across BOTH kinds, and patients and doctors are "
    "disjoint sets because an actor key's preimage includes its kind"
)


class RetentionCohortDay(BaseModel):
    """One arrival date's cohort and how much of it was still here later.

    ``cohort_size`` is how many actors were first seen on ``cohort_date``. The two
    ``retained`` counts are how many of exactly those people were active again at the
    horizon, and each ``retention`` is that count over the cohort size - never over the
    base of some other date's cohort, and never over the window's total.

    ``retained_7d``/``retained_30d`` are ``None`` when the horizon is still in the
    future, and so are the rates: see :data:`RETENTION_MATURITY_CONVENTION`. They are
    NOT zero, and the difference is the whole reason a cohort table is worth reading.
    """

    cohort_date: date
    cohort_size: int
    retained_7d: int | None
    retention_7d: Decimal | None
    retained_30d: int | None
    retention_30d: Decimal | None


class RetentionCohortsRead(BaseModel):
    """Does adoption stick? - seven- and thirty-day retention, one row per arrival day.

    **Active users answer "is adoption growing" and this answers "does it stay."** A
    product can add a thousand people a week and lose every one of them inside a
    fortnight, and DAU/WAU/MAU alone will not show it: the rolling windows are
    computed from the same arrivals, so churn and acquisition cancel.

    A cohort is a GROUP rather than a window for that reason. Everyone who arrived on
    one date is held together and asked what happened to them later, so a falling
    retention figure means the product lost people, not that it stopped acquiring them
    at exactly the right moment.

    **Derived at read time from the daily aggregate, never stored.** The figures are
    divisions over rows the nightly rollup already wrote, so there is exactly one
    source of truth: a recompute of any day moves this response with it and nothing
    else has to be kept in step. See :data:`RETENTION_SOURCE_CONVENTION`.

    **A thirty-day question never scans the raw ledger.** The query below touches one
    table - ``observability_product_actor_daily`` - and joins it to itself. The ledger
    is read once a night by the rollup and by nothing else, which is what lets these
    numbers outlive the free vendor tier's fourteen-day retention.

    Every cohort date in ``[from_date, to_date]`` is listed, including one with nobody
    in it, so a gap in the series is a real absence of arrivals rather than a row the
    chart quietly dropped.
    """

    days: int
    from_date: date
    to_date: date
    horizons: tuple[int, int]
    cohorts: list[RetentionCohortDay]
    window_convention: str
    maturity_convention: str
    source_convention: str
    actor_convention: str


class GrafanaDeeplinks(BaseModel):
    """The Grafana views, each already narrowed (#736).

    ``dashboard_url`` is always present when the vendor is configured - the
    dashboard link can always carry its range and variables. ``explore_url`` needs a
    trace, so it is absent until the caller supplies one.
    """

    dashboard_uid: str
    dashboard_url: str
    explore_url: str | None = None


class SentryDeeplinks(BaseModel):
    """The Sentry views, each already filtered to this service (#736).

    ``project_id`` is carried beside the URLs so a client can label the link with the
    project it points into without re-deriving it from a DSN it has never seen.
    """

    project_id: str
    issues_url: str
    trace_url: str | None = None


class LangfuseDeeplinks(BaseModel):
    """The Langfuse views, each already filtered (#736).

    Every key here needs context - a model, a task, a trace, an actor or a session -
    so this group is present only when the caller supplied at least one. There is no
    bare project view: that was the link #736 removed.
    """

    traces_url: str | None = None
    trace_url: str | None = None
    actor_url: str | None = None
    session_url: str | None = None


class Deeplinks(BaseModel):
    """The operator page's outbound vendor links (plan-phase14 A§9.1), widened (#736).

    A WIRE CHANGE (decision 44): three bare URL strings became three link SETS, each
    carrying its own filters. The frontend client contract moves with it in the same
    change - there is no compatibility window.

    Every key is optional and independently ``None``, and the route answers with
    ``exclude_none`` so an unconfigured vendor is **absent from the JSON entirely**
    rather than a ``null`` the client has to interpret: a deployment with Sentry but
    no Grafana has no ``grafana`` key at all, and there is no such thing as a link
    here that points nowhere. See :mod:`modules.observability.domain.deeplinks`.

    ``trace_id`` echoes the platform's own stored identifier so a client can label
    every link it renders with the join key they all share - and so a link set is
    self-describing once it has been passed around or logged.
    """

    trace_id: str | None = None
    grafana: GrafanaDeeplinks | None = None
    sentry: SentryDeeplinks | None = None
    langfuse: LangfuseDeeplinks | None = None


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


#: Every column ``observability_alert_events`` contributes to an :class:`AlertEntry`,
#: in one place. The feed and the acknowledgement read both select exactly this, so
#: the row an operator is handed after acknowledging is byte-for-byte the row the
#: feed would have handed them - including the two acknowledgement columns.
_ALERT_COLUMNS = (
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


def _alert_entry(row: RowMapping) -> AlertEntry:
    """One selected alert row as the feed and the acknowledgement both answer it."""
    return AlertEntry(
        id=row["id"],
        severity=row["severity"],
        kind=row["kind"],
        title=row["title"],
        payload=row["payload"],
        status=row["status"],
        created_at=row["created_at"],
        acked_by=row["acked_by"],
        acked_at=row["acked_at"],
    )


async def query_alerts(
    connection: AsyncConnection, *, page: int, page_size: int, status: str | None = None
) -> AlertPage:
    """Read one page of the alert feed, newest first (``/alerts``).

    Unfiltered, this is the operator's standing-problems view; ``status`` narrows
    it to what is still open, to what an operator has taken ownership of, or to what
    a later pass has resolved. The feed is ordered newest first and carries only
    PHI-free columns, so it can be rendered inline on the operator page
    (plan-phase14 §9.2).

    ``total_count`` is a second aggregate over the same filter rather than
    ``len(alerts)``, so a caller can page back through a long feed without paging
    to find out there is more.

    An unrecognised status is refused rather than passed through, because the failure
    mode of getting it wrong is an empty feed that reads as "nothing is wrong" - the
    same reason the route's ``Literal`` refuses it at the edge, and the same rule
    :func:`_error_status_clause` follows for the error feed.
    """
    if status is not None and status not in ALERT_STATUS_VOCABULARY:
        raise ValueError(
            f"unknown alert status {status!r}; expected one of {', '.join(ALERT_STATUS_VOCABULARY)}"
        )
    filter_clause = (
        (observability_alert_events.c.status == status) if status is not None else true()
    )
    counted = await connection.execute(
        select(func.count()).select_from(observability_alert_events).where(filter_clause)
    )
    total = int(counted.scalar_one())

    rows = await connection.execute(
        select(*_ALERT_COLUMNS)
        .where(filter_clause)
        .order_by(
            observability_alert_events.c.created_at.desc(),
            observability_alert_events.c.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return AlertPage(alerts=[_alert_entry(row) for row in rows.mappings()], total_count=total)


async def acknowledge_alert(
    connection: AsyncConnection,
    *,
    alert_id: UUID,
    acked_by: int,
    acked_at: datetime,
) -> AlertAcknowledgement:
    """Move one alert to ``acknowledged`` and attribute it to the operator (#735).

    Writes the ``acked_by`` / ``acked_at`` columns that have been on the row since
    the first observability migration and that nothing ever wrote, so a response
    becomes attributable rather than anonymous.

    **The first acknowledgement stands, and the DATABASE is what decides that.** The
    write is guarded on the alert still being ``open``, so a second caller does not
    overwrite the first operator: it blocks on the first UPDATE's row lock,
    re-evaluates the guard against the committed row and matches nothing. Reading
    the status first and then writing would leave a window in which two operators
    both read ``open`` and both write themselves in; guarding the write itself
    closes that window in the engine rather than in this code.

    So the three outcomes are decided by one statement plus one read-back:

    - the UPDATE matched a row - this call wrote the acknowledgement;
    - it matched nothing and the row reads ``acknowledged`` - somebody got here
      first, and their operator and timestamp stand;
    - it matched nothing and the row reads ``resolved`` - the alert is closed, and
      acknowledging it would re-open a problem a later pass already cleared.
    """
    result = await connection.execute(
        observability_alert_events.update()
        .where(
            observability_alert_events.c.id == alert_id,
            observability_alert_events.c.status == ALERT_STATUS_OPEN,
        )
        .values(
            status=ALERT_STATUS_ACKNOWLEDGED,
            acked_by=acked_by,
            acked_at=acked_at,
        )
    )
    acknowledged_now = bool(result.rowcount)

    rows = (
        await connection.execute(
            select(*_ALERT_COLUMNS).where(observability_alert_events.c.id == alert_id)
        )
    ).mappings()
    row = rows.one_or_none()
    if row is None:
        raise AlertNotFoundError(alert_id)
    if row["status"] == ALERT_STATUS_RESOLVED:
        raise AlertAlreadyResolvedError(alert_id)
    return AlertAcknowledgement(alert=_alert_entry(row), already_acknowledged=not acknowledged_now)


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


#: One-decimal scale of the median step gap (``94.5``, not ``94.5123``). A gap is a
#: human pause measured in seconds, so a tenth of a second is the resolution worth
#: spending; the ledger keeps milliseconds and the pairs behind this figure are one
#: per row, so the extra places would be noise a reader cannot act on.
_GAP_QUANTUM = Decimal("0.1")


def _seconds(value: float) -> Decimal:
    """An epoch-second gap at the gap scale.

    Quantized rather than formatted, the way :func:`~modules.observability.domain.rollup.ratio`
    and the spend ranks are: formatting a float through ``.1f`` rounds half to EVEN,
    which is not the rule any other figure on these surfaces uses.
    """
    return Decimal(repr(value)).quantize(_GAP_QUANTUM, rounding=ROUND_HALF_UP)


def _gap_basis(step: ProductStep, predecessor: ProductStep | None) -> str:
    """Which key paired this step with the one before it - or why nothing did.

    Three answers, because "no number" has three different reasons and a reader does
    something different with each: nothing came before this step at all, something came
    before it and the ledger cannot join the two, or the pair was measured. Folding the
    first two into one ``unavailable`` would tell an operator the funnel has no entry
    step, which is not what happened.
    """
    if predecessor is None:
        return GAP_BASIS_NO_PREDECESSOR
    return GAP_BASIS_ACTOR if _gap_is_joinable(step, predecessor) else GAP_BASIS_UNAVAILABLE


def _gap_is_joinable(step: ProductStep, predecessor: ProductStep) -> bool:
    """Whether the ledger holds a key these two steps can be paired on.

    The pairing key today is ``actor_key`` (see
    :func:`_median_step_gap_seconds`), so two steps are joinable exactly when they are
    attributed to the SAME kind of actor. The intake funnel's three patient steps and
    its four doctor steps pair within themselves; the handoff from
    ``pre_summary_ready`` to ``consult_complete`` crosses from the patient to the
    doctor and shares no key the ledger stores, so its gap is reported as unmeasured.

    This is the seam a future stable session key drops into: when producers publish
    one, the pairing key becomes ``session_key`` on both sides of this comparison and
    the handoff measures like every other step, with no change to the shape.
    """
    return (
        step.actor_kind is not None
        and predecessor.actor_kind is not None
        and step.actor_kind == predecessor.actor_kind
    )


async def _median_step_gap_seconds(
    connection: AsyncConnection,
    *,
    funnel: str,
    step: ProductStep,
    predecessor: ProductStep,
    window_start: datetime,
    window_end: datetime,
) -> tuple[Decimal | None, int]:
    """The median gap between ``predecessor`` and ``step`` in seconds, and its size.

    Each row of ``step`` is paired with the MOST RECENT completed row of
    ``predecessor`` for the same pseudonymous actor at or before it - a lateral join
    rather than a plain one, because "the step before this one" is the NEAREST
    matching row, not the first row of the day. That matters because the browser
    fires ``intake.composer_opened`` on every composer mount, so one patient can hold
    several entry rows and only the nearest of them is the step this row followed.

    The predecessor is bounded by the same window as the rows it pairs with, on
    purpose. Widening the search backwards would report a gap measured over a longer
    horizon than the window the operator asked for - a thirty-day funnel answering
    with a gap measured from nine months back is a number nobody can place - so a
    workflow straddling the window edge reports no gap, and ``gap_samples`` of zero
    says so.

    Only a COMPLETED predecessor row is paired from: the gap answers "how long after
    finishing the step before did the next one happen", so an abandoned or errored
    predecessor is not a finish and pairing from it would measure the wrong interval.

    **The median is taken in the database, not in Python.** The rollup's own
    :func:`~modules.observability.domain.rollup.percentile` exists because what it
    serves is a bounded number of daily rows; the pairs here are one per ledger row in
    the window, and pulling them into the process to rank would make the query cost
    depend on how busy the product is. ``percentile_cont`` returns one number for the
    whole population, which is what a read wants.

    ``(None, 0)`` when nothing paired: no completed predecessor row precedes any row of
    this step inside the window. That is a fact about the window, not a failure, and
    the caller turns it into a ``null`` median beside a ``gap_samples`` of zero.
    """
    table = observability_product_events
    arrived = table.alias("arrived")
    before = table.alias("before")
    # An INNER lateral: a row of this step with no predecessor row to pair against is
    # not a gap of zero, it is an unmeasured gap, and counting it as one would drag
    # every median toward zero.
    nearest_before = (
        select(before.c.occurred_at.label("occurred_at"))
        .where(
            (before.c.funnel == predecessor.funnel)
            & (before.c.step == predecessor.step)
            & (before.c.outcome == PRODUCT_OUTCOME_COMPLETED)
            & (before.c.actor_key == arrived.c.actor_key)
            & (before.c.occurred_at <= arrived.c.occurred_at)
            & (before.c.occurred_at >= window_start)
        )
        .order_by(before.c.occurred_at.desc())
        .limit(1)
        .lateral()
    )
    gap_seconds = extract("epoch", arrived.c.occurred_at) - extract(
        "epoch", nearest_before.c.occurred_at
    )
    statement = (
        select(
            func.count().label("samples"),
            func.percentile_cont(0.5).within_group(gap_seconds).label("median_gap_s"),
        )
        .select_from(arrived.join(nearest_before, true()))
        .where(
            (arrived.c.funnel == funnel)
            & (arrived.c.step == step.step)
            & (arrived.c.actor_key.is_not(None))
            & (arrived.c.occurred_at >= window_start)
            & (arrived.c.occurred_at <= window_end)
        )
    )
    result = await connection.execute(statement)
    row = result.mappings().one()
    samples = int(row["samples"])
    if samples == 0 or row["median_gap_s"] is None:
        return None, 0
    return _seconds(float(row["median_gap_s"])), samples


def _in_scope(
    counts: Mapping[ProductOutcome, int], candidate: ProductOutcome, outcome: ProductOutcome | None
) -> int:
    """One step's count for ``candidate``, or zero when a filter excludes it.

    The narrowing half of :data:`FUNNEL_DENOMINATOR_CONVENTION`: with the read filtered
    to one outcome, every counter on a row counts that outcome alone, so a row filtered
    to ``abandoned`` cannot be quoted as a completed step that happened to also lose
    people.
    """
    if outcome is not None and outcome != candidate:
        return 0
    return counts.get(candidate, 0)


def _step_conversion(
    entered: int, counts: Mapping[str, int], predecessor: ProductStep | None
) -> Decimal | None:
    """``entered`` over the predecessor's, or ``None`` when there is no denominator.

    Reads the predecessor's figure off the same counts the steps were built from
    rather than re-querying or re-deriving it, so a step's conversion and its
    neighbour's ``entered`` can never describe different populations - the drift a
    funnel cannot afford, since the two numbers are read as a fraction of each other.
    """
    if predecessor is None:
        return None
    return ratio(entered, counts.get(predecessor.step, 0))


def _step_entered(
    by_step: Mapping[str, Mapping[ProductOutcome, int]],
    steps: Sequence[ProductStep],
    outcome: ProductOutcome | None,
) -> Mapping[str, int]:
    """One ``entered`` per step: every row it wrote, or only the outcome asked for.

    Which of the two is :data:`FUNNEL_DENOMINATOR_CONVENTION` made mechanical. With no
    filter it is EVERY row the step wrote - an arrival that was abandoned still ARRIVED,
    and removing it would let a broken step look like a step nobody reached. With a
    filter it is that outcome's rows alone, which is what isolating one path means, and
    it stays coherent because every counter on the row narrows with it.

    Read per STEP rather than per walk, so a step the walk does not include - the
    re-record - reports its own rows instead of an ``entered`` of zero beside a
    ``re_recorded`` of three.
    """
    if outcome is None:
        return {step.step: sum(by_step.get(step.step, {}).values()) for step in steps}
    return {step.step: by_step.get(step.step, {}).get(outcome, 0) for step in steps}


def _outcome_total(
    by_step: Mapping[str, Mapping[ProductOutcome, int]],
    steps: Sequence[ProductStep],
    outcome: ProductOutcome,
) -> int:
    """How many rows across ``steps`` ended with ``outcome``."""
    return sum(by_step.get(step.step, {}).get(outcome, 0) for step in steps)


def _completed_at(by_step: Mapping[str, Mapping[ProductOutcome, int]], step_name: str) -> int:
    """How many COMPLETED rows one step recorded: a finished end, not an arrival."""
    return by_step.get(step_name, {}).get(PRODUCT_OUTCOME_COMPLETED, 0)


def _terminal_entered(
    by_step: Mapping[str, Mapping[ProductOutcome, int]], stages: Sequence[ProductStep]
) -> int:
    """How many workflows REACHED an end: a COMPLETED row at a terminal step.

    Every terminal, not the two named ones, so a terminal registered tomorrow is in the
    rate without this function being taught its name. Completed rows only: a case closed
    under an error or abandoned on the way out is not a finished consultation, and
    counting it as one is exactly the conflation decision 23 refuses.
    """
    return sum(_completed_at(by_step, stage.step) for stage in stages if stage.terminal)


def _funnel_totals(
    by_step: Mapping[str, Mapping[ProductOutcome, int]],
    funnel: str,
    stages: Sequence[ProductStep],
) -> FunnelOutcomeTotals:
    """The headline verdict: did the workflows finish, and how many did not.

    Computed from the UNFILTERED counts, always, and over the WHOLE walk rather than
    the filtered step list. An ``outcome`` filter narrows the steps that are reported
    and what each of them counts; narrowing the success rate to the abandoned rows as
    well would leave a client comparing two rates measured over two different
    populations, which is the failure :class:`FunnelOutcomeTotals` exists to prevent.

    The three outcome counters run over EVERY registered step rather than over the
    walk, because the re-record step is not a stage of the walk and its rows are still
    the funnel's rows. An abandoned attempt that was then corrected is counted in
    ``abandoned`` and in ``re_recorded`` alike, which is decision 25's rule made
    arithmetic: the correction does not erase the abandonment, and neither figure is
    scored as a failure of the other.

    ``started`` is the walk's own first step, which is why the walk and not the
    registry: a funnel that grew a step before its entry step would still be counted
    from where journeys actually begin.
    """
    every = registered_steps(funnel)
    entered = _step_entered(by_step, every, None)
    started = entered.get(stages[0].step, 0) if stages else 0
    abandoned = _outcome_total(by_step, every, PRODUCT_OUTCOME_ABANDONED)
    return FunnelOutcomeTotals(
        started=started,
        task_success_rate=ratio(_terminal_entered(by_step, stages), started),
        abandonment_rate=ratio(abandoned, started),
        issued_e_prescriptions=_completed_at(by_step, FUNNEL_TERMINAL_PRESCRIPTION),
        cases_closed=_completed_at(by_step, FUNNEL_TERMINAL_CASE_CLOSED),
        abandoned=abandoned,
        errored=_outcome_total(by_step, every, PRODUCT_OUTCOME_ERRORED),
        re_recorded=_outcome_total(by_step, every, PRODUCT_OUTCOME_RE_RECORDED),
    )


def _funnel_steps(funnel: str, outcome: ProductOutcome | None) -> tuple[ProductStep, ...]:
    """The steps this read reports: the walk, narrowed to an outcome's own vocabulary.

    **The filter narrows the step LIST and the counts together.** A step's declared
    ``allowed_outcomes`` says which outcomes can end it, so filtering by ``abandoned``
    returns the steps that can be abandoned - which is what "isolate the abandoned
    path" means - and each of those rows then counts abandoned arrivals and nothing
    else, so there is no second figure on the row to quote instead.

    The re-record step is not in the walk, so an ``outcome=re_recorded`` filter would
    otherwise select nothing and return an empty funnel. Falling back to the whole
    registry keeps every accepted outcome an answer rather than a dead filter: the
    re-record is reported on its own row, which is exactly what decision 25 asks for.
    """
    if outcome is None:
        return funnel_stages(funnel)
    selected = tuple(stage for stage in funnel_stages(funnel) if outcome in stage.allowed_outcomes)
    if selected:
        return selected
    return tuple(step for step in registered_steps(funnel) if outcome in step.allowed_outcomes)


async def query_funnel(
    connection: AsyncConnection,
    *,
    funnel: str = FUNNEL_INTAKE,
    outcome: ProductOutcome | None = None,
    now: datetime,
    window_days: int,
) -> FunnelRead:
    """The funnel from the moment a patient opened the composer, over its window.

    Served from ``observability_product_events``, the ledger, rather than from the
    daily rollup - and the reason is that this read asks three things a daily row
    cannot answer: the median gap between two steps needs those two rows' own
    ``occurred_at``, the trace behind a count needs the row carrying it, and neither
    survives being summed. The rollup is the right table for a thirty-day COUNT and
    this is not a thirty-day count.

    ``now`` is passed in rather than read from the clock and ``window_days`` is
    validated HERE, the one place, for the same two reasons as
    :func:`query_error_feed`: a test can pin the instant, and no caller can ask for a
    window that ends before it starts.

    **Three conventions travel with the numbers and all of them are on the wire.**
    Which rows a step's ``entered`` covers and what its conversion divides by
    (:data:`FUNNEL_DENOMINATOR_CONVENTION`), what each rate's numerator is
    (:data:`FUNNEL_RATE_CONVENTION`), and what the gap between two steps was measured
    against (:data:`FUNNEL_GAP_CONVENTION`). They are fields rather than docstrings
    because a client rendering this response has to be able to say what it means - and
    because the gap the ledger CANNOT measure today, the patient-to-doctor handoff into
    ``consult_complete``, has to be reported as unmeasured rather than as a fast, happy
    step.
    """
    if window_days < 1:
        raise ValueError("window_days must be positive")
    if outcome is not None and outcome not in PRODUCT_OUTCOMES:
        raise ValueError(
            f"unknown funnel outcome {outcome!r}; expected one of {', '.join(PRODUCT_OUTCOMES)}"
        )
    window_start = now - timedelta(days=window_days)
    table = observability_product_events
    stages = funnel_stages(funnel)
    reported = _funnel_steps(funnel, outcome)

    counted = await connection.execute(
        select(
            table.c.step,
            table.c.outcome,
            func.count().label("events"),
        )
        .select_from(table)
        .where(
            (table.c.funnel == funnel)
            & (table.c.occurred_at >= window_start)
            & (table.c.occurred_at <= now)
        )
        .group_by(table.c.step, table.c.outcome)
    )
    by_step: dict[str, dict[ProductOutcome, int]] = {}
    for row in counted.mappings():
        by_step.setdefault(str(row["step"]), {})[row["outcome"]] = int(row["events"])
    entered_by_step = _step_entered(by_step, registered_steps(funnel), outcome)

    traced = await connection.execute(
        select(table.c.step, table.c.trace_id)
        .select_from(table)
        .where(
            (table.c.funnel == funnel)
            & (table.c.occurred_at >= window_start)
            & (table.c.occurred_at <= now)
        )
        .distinct(table.c.step)
        .order_by(table.c.step, table.c.occurred_at.desc(), table.c.id.desc())
    )
    latest_trace = {str(row["step"]): str(row["trace_id"]) for row in traced.mappings()}

    rows: list[FunnelStepRow] = []
    for stage in reported:
        counts = by_step.get(stage.step, {})
        predecessor = stage_predecessor(stage, stages)
        basis = _gap_basis(stage, predecessor)
        median_gap: Decimal | None = None
        gap_samples = 0
        if predecessor is not None and basis == GAP_BASIS_ACTOR:
            median_gap, gap_samples = await _median_step_gap_seconds(
                connection,
                funnel=funnel,
                step=stage,
                predecessor=predecessor,
                window_start=window_start,
                window_end=now,
            )
        entered = entered_by_step.get(stage.step, 0)
        rows.append(
            FunnelStepRow(
                step=stage.step,
                event_type=stage.event_type,
                terminal=stage.terminal,
                previous_step=predecessor.step if predecessor is not None else None,
                entered=entered,
                completed=_in_scope(counts, PRODUCT_OUTCOME_COMPLETED, outcome),
                abandoned=_in_scope(counts, PRODUCT_OUTCOME_ABANDONED, outcome),
                errored=_in_scope(counts, PRODUCT_OUTCOME_ERRORED, outcome),
                re_recorded=_in_scope(counts, PRODUCT_OUTCOME_RE_RECORDED, outcome),
                conversion_from_previous=_step_conversion(entered, entered_by_step, predecessor),
                median_gap_from_previous_s=median_gap,
                gap_samples=gap_samples,
                gap_basis=basis,
                latest_trace_id=latest_trace.get(stage.step),
            )
        )

    return FunnelRead(
        funnel=funnel,
        window_start=window_start,
        window_end=now,
        window_days=window_days,
        outcome=outcome,
        denominator_convention=FUNNEL_DENOMINATOR_CONVENTION,
        rate_convention=FUNNEL_RATE_CONVENTION,
        gap_convention=FUNNEL_GAP_CONVENTION,
        steps=rows,
        outcomes=_funnel_totals(by_step, funnel, stages),
    )


def _day_start(day: date) -> datetime:
    """Midnight UTC on ``day`` - the instant every window here opens on."""
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def _utc_day(column: ColumnElement[Any]) -> ColumnElement[date]:
    """``column`` (a ``timestamptz``) reduced to its UTC calendar day.

    Explicitly UTC rather than the session's time zone, because every window this
    module reads is a UTC day (``window_for``, ``usage_date``, ``event_date``) and a
    deployment whose database runs on local time would otherwise bucket a
    midnight-UTC event into yesterday - quietly moving a day of traffic and a day of
    active users across the boundary, which is exactly the class of bug the last-day
    figure cannot recover from.
    """
    return cast(func.timezone(text("'UTC'"), column), Date)


def _row_day(value: object) -> date:
    """One ``day`` cell of an active-users result as a calendar date.

    The query casts to ``Date`` so the DATABASE does the UTC truncation rather than
    Python doing it from a zone-naive timestamp, but a driver is free to hand a bare
    ``timestamp`` back, and keying the daily maps by an instant would silently split
    one day into two - a trend that is wrong in a way no assertion about its totals
    would catch. Anything that is neither is a driver contract break, raised on
    rather than coerced into a plausible date.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"expected a date from the day column, got {type(value).__name__}")


def _actor_window(
    *, window_days: int, from_date: date, to_date: date, counts: Mapping[str, int]
) -> ActiveUserWindow:
    """One window's per-kind actor counts as the response carries them.

    ``total`` is the SUM of the two kinds rather than a distinct count of the
    combined set, and that is exact: an actor key is hashed with its actor kind in
    the preimage (:func:`~modules.observability.domain.pseudonym.actor_key`), so the
    two kinds hold disjoint keys and no person is counted twice.
    """
    patients = counts.get(ACTOR_KIND_PATIENT, 0)
    doctors = counts.get(ACTOR_KIND_DOCTOR, 0)
    return ActiveUserWindow(
        window_days=window_days,
        from_date=from_date,
        to_date=to_date,
        patients=patients,
        doctors=doctors,
        total=patients + doctors,
    )


async def query_active_users(
    connection: AsyncConnection, *, days: int, now: datetime
) -> ActiveUsersRead:
    """Read DAU, WAU, MAU, stickiness and load per head (``/product/active-users``).

    **Every figure is counted in Postgres, and that is the reason the read exists.**
    The free metrics tier keeps fourteen days, so a monthly active-user number is not
    a question the vendor can answer - the data is gone before it is asked - and the
    honest alternative to computing it here would be reporting a fourteen-day base
    under a "monthly" label, which is a decline in adoption nobody reported.

    **Why the ledger and not the daily rollup.** ``observability_product_daily``'
    ``actor_count`` is a distinct count per ``(funnel, step, outcome, day)``, and
    summing it cannot produce a distinct count over a window: one patient who opened
    the composer and then submitted is two rows and one active actor, so a summed
    daily figure doubles the people who got further than the first step and is
    largest exactly where the product works best. Distinctness only exists before the
    aggregation, so the three headline figures count DISTINCT ``actor_key`` against
    ``observability_product_events`` directly, on the index its ``occurred_at``
    column carries. The daily rollup stays the answer for per-step funnel questions,
    which is what its grain is for.

    **The actor set is the registry's, not this query's.** ``step IN (...)`` is built
    from :func:`~modules.observability.domain.product.active_actor_step_names`, so a
    newly registered step counts toward adoption by declaring an actor kind, with no
    edit here - and ``actor_key IS NOT NULL`` keeps a row that carries no actor from
    inflating anything even if one arrived.

    **Three windows, one scan.** The daily, weekly and monthly figures are nested
    (today is inside the week is inside the month), so one grouped ``count(DISTINCT)``
    with three ``FILTER`` clauses answers all three plus the requested window's own
    count, over a scan that starts at the OLDEST of the windows rather than being
    issued three times.

    The throughput trend is a SECOND table read at DAY grain, merged with the daily
    actor counts in Python. Summing the merged series in Python rather than issuing a
    separate total aggregate follows ``query_throughput``: the rows in the series are
    the window's truth, so a total computed from them cannot disagree with the chart
    beside them, while a separately issued aggregate could.

    ``days`` is validated here rather than at the route, because every path into this
    read goes through here and two copies of the check are two places for them to
    disagree about what a valid window is.
    """
    if days < 1:
        raise ValueError("days must be positive")

    events = observability_product_events
    counter = observability_http_minute
    qualifying = active_actor_step_names()

    to_date = now.date()
    from_date = to_date - timedelta(days=days - 1)
    week_from = to_date - timedelta(days=ACTIVE_USER_WEEK_WINDOW - 1)
    month_from = to_date - timedelta(days=ACTIVE_USER_MONTH_WINDOW - 1)
    # One exclusive end for all four windows: the ledger and the counter both store
    # instants, so "today" has to mean the whole of today rather than up to the
    # instant the read happened to run at.
    to_ts = _day_start(to_date + timedelta(days=1))
    # The scan starts at the EARLIEST of the three windows, which is the requested one
    # whenever ``days`` exceeds thirty. Every count then carries its own lower bound as
    # a FILTER rather than trusting the scan, so a sixty-day request cannot leak its
    # extra days into the rolling monthly figure.
    scan_from_ts = _day_start(min(from_date, month_from))
    ledger_scan = (
        (events.c.occurred_at >= scan_from_ts),
        (events.c.occurred_at < to_ts),
        events.c.actor_key.is_not(None),
        events.c.step.in_(qualifying),
    )

    windows: dict[str, dict[str, int]] = {"window": {}, "week": {}, "month": {}}
    daily_actors: dict[date, dict[str, int]] = {}
    daily_requests: dict[date, int] = {}
    # Nothing in the registry qualifies, so the queries are not issued at all. An
    # empty ``IN`` list would match nothing and read as "nobody was active", which is
    # the right answer - but letting Postgres decide it would put a registry fact
    # behind a query planner detail, and every answer below would then be built from
    # three results nobody asked for.
    if qualifying:
        window_rows = await connection.execute(
            select(
                events.c.actor_kind,
                func.count(distinct(events.c.actor_key))
                .filter(events.c.occurred_at >= _day_start(from_date))
                .label("window_total"),
                func.count(distinct(events.c.actor_key))
                .filter(events.c.occurred_at >= _day_start(week_from))
                .label("week_total"),
                func.count(distinct(events.c.actor_key))
                .filter(events.c.occurred_at >= _day_start(month_from))
                .label("month_total"),
            )
            .where(*ledger_scan)
            .group_by(events.c.actor_kind)
        )
        for entry in window_rows.mappings():
            kind = str(entry["actor_kind"])
            windows["window"][kind] = int(entry["window_total"])
            windows["week"][kind] = int(entry["week_total"])
            windows["month"][kind] = int(entry["month_total"])

        event_day = _utc_day(events.c.occurred_at)
        daily_actor_rows = await connection.execute(
            select(
                event_day.label("day"),
                events.c.actor_kind,
                func.count(distinct(events.c.actor_key)).label("actors"),
            )
            .where(*ledger_scan)
            .group_by(event_day, events.c.actor_kind)
            .order_by(event_day)
        )
        for entry in daily_actor_rows.mappings():
            kind = str(entry["actor_kind"])
            daily_actors.setdefault(_row_day(entry["day"]), {})[kind] = int(entry["actors"])

        counter_day = _utc_day(counter.c.minute_ts)
        request_rows = await connection.execute(
            select(counter_day.label("day"), func.sum(counter.c.requests).label("requests"))
            .where(
                (counter.c.minute_ts >= _day_start(from_date)),
                (counter.c.minute_ts < to_ts),
            )
            .group_by(counter_day)
            .order_by(counter_day)
        )
        for entry in request_rows.mappings():
            daily_requests[_row_day(entry["day"])] = int(entry["requests"])

    trend: list[ActiveUsersDayPoint] = []
    for day in sorted(set(daily_actors) | set(daily_requests)):
        if day < from_date:
            # The daily series is read over the widest scan the nested windows need;
            # only the requested window's own days belong on the trend.
            continue
        actors = daily_actors.get(day, {})
        patients = actors.get(ACTOR_KIND_PATIENT, 0)
        doctors = actors.get(ACTOR_KIND_DOCTOR, 0)
        requests = daily_requests.get(day, 0)
        active_users = patients + doctors
        trend.append(
            ActiveUsersDayPoint(
                day=day,
                requests=requests,
                active_users=active_users,
                requests_per_active_user=_per_active_user(requests, active_users),
            )
        )

    daily = _actor_window(
        window_days=ACTIVE_USER_DAY_WINDOW,
        from_date=to_date,
        to_date=to_date,
        counts=daily_actors.get(to_date, {}),
    )
    monthly = _actor_window(
        window_days=ACTIVE_USER_MONTH_WINDOW,
        from_date=month_from,
        to_date=to_date,
        counts=windows["month"],
    )
    requested = _actor_window(
        window_days=days, from_date=from_date, to_date=to_date, counts=windows["window"]
    )
    requests = sum(point.requests for point in trend)
    return ActiveUsersRead(
        days=days,
        from_date=from_date,
        to_date=to_date,
        daily_active_users=daily,
        weekly_active_users=_actor_window(
            window_days=ACTIVE_USER_WEEK_WINDOW,
            from_date=week_from,
            to_date=to_date,
            counts=windows["week"],
        ),
        monthly_active_users=monthly,
        window_active_users=requested,
        # The usual definition - daily over monthly - and ``None`` rather than zero
        # when the monthly base is empty, which is "nothing to divide by" rather than
        # a measured absence of stickiness.
        stickiness=ratio(daily.total, monthly.total),
        requests=requests,
        requests_per_active_user=_per_active_user(requests, requested.total),
        trend=trend,
        window_convention=ACTIVE_USER_WINDOW_CONVENTION,
        source_convention=ACTIVE_USER_SOURCE_CONVENTION,
        stickiness_convention=STICKINESS_CONVENTION,
        requests_per_active_user_convention=REQUESTS_PER_ACTIVE_USER_CONVENTION,
    )


# --------------------------------------- the retention cohorts read's SQL pieces (#742)


def _cohort_arrivals(actors: Table, *, from_date: date, to_date: date) -> CTE:
    """The CTE naming each actor's FIRST EVER active day, narrowed to the window.

    Two stages, and the inner one has no date filter at all - which is the whole
    correctness of the read. A person who arrived ninety days ago and came back on
    Tuesday has NOT arrived on Tuesday, and a ``min`` bounded to the window would say
    they had: the oldest cohorts in the response, which are the only ones carrying a
    matured thirty-day figure, would have returning veterans inflating their own
    denominators and every rate dragged down with them. It would also make the same
    actor a different person depending on ``days`` - a cohort of Monday's under
    ``days=7`` and absent from it under ``days=60``.

    So the inner aggregate takes ``min(event_date)`` per ``(actor_kind, actor_key)``
    across the WHOLE aggregate and the outer one filters that arrival date into the
    window. The inner scan is unbounded and that is the price of the truth in it; it is
    still the daily aggregate rather than the per-event ledger, which is the bound this
    read exists to keep. ``ix_observability_product_actor_daily_actor`` leads with the
    actor pair, so it is a per-actor minimum along an index rather than a table walk.

    It is a CTE rather than a subquery so the cohort-size query and BOTH horizon
    queries below share one definition of "when this person arrived" - two copies of a
    first-seen rule are two places for a cohort to be measured from a different arrival
    date depending on which horizon you asked about.
    """
    first_ever = (
        select(
            actors.c.actor_kind,
            actors.c.actor_key,
            func.min(actors.c.event_date).label("first_date"),
        )
        .group_by(actors.c.actor_kind, actors.c.actor_key)
        .cte("first_ever")
    )
    return (
        select(
            first_ever.c.actor_kind,
            first_ever.c.actor_key,
            first_ever.c.first_date,
        )
        .where(first_ever.c.first_date >= from_date, first_ever.c.first_date <= to_date)
        .cte("first_seen")
    )


def _retained_by_cohort(
    actors: Table,
    first_seen: CTE,
    *,
    horizon: int,
    to_date: date,
) -> Any:
    """One horizon's retention statement: how many of each cohort came back at it.

    A self-join of the daily aggregate, never a second table. The join predicate is
    ``event_date = first_date + horizon`` rather than a range, so the answer is "was
    this exact person here on exactly that day" - the classic day-N retention a product
    manager means by "seven-day retention". A cohort that returned on day nine and
    never again is not a retained cohort, and a range would quietly report it as one.

    Cohorts whose horizon falls after ``to_date`` are excluded by the ``where`` rather
    than counted as zero retained: the question has not been answerable yet.
    """
    return (
        select(
            first_seen.c.first_date.label("cohort_date"),
            func.count().label("retained"),
        )
        .select_from(
            first_seen.join(
                actors,
                and_(
                    actors.c.actor_kind == first_seen.c.actor_kind,
                    actors.c.actor_key == first_seen.c.actor_key,
                    actors.c.event_date == first_seen.c.first_date + horizon,
                ),
            )
        )
        .where(first_seen.c.first_date <= to_date - timedelta(days=horizon))
        .group_by(first_seen.c.first_date)
    )


def _retained_or_none(
    cohort_date: date,
    horizon: int,
    to_date: date,
    retained: dict[int, dict[date, int]],
    *,
    cohort_size: int,
) -> int | None:
    """A cohort's retained count at ``horizon``, or ``None`` when there is nothing to say.

    ``None`` and ``0`` are different answers and the whole maturity convention rests on
    keeping them apart: ``None`` is a horizon nobody has lived through yet, ``0`` is a
    horizon that arrived and nobody came back to it.

    An EMPTY cohort is the third case and gets ``None`` too, not ``0``. Nobody arrived
    on this date, so "zero of them came back on day thirty" is not a measurement of
    anybody - it is a claim about an empty set, and a chart reading it as a full
    retention collapse would be reading the absence of a cohort as the loss of one.
    """
    if cohort_size == 0 or cohort_date + timedelta(days=horizon) > to_date:
        return None
    return retained.get(horizon, {}).get(cohort_date, 0)


async def query_retention_cohorts(
    connection: AsyncConnection, *, days: int, now: datetime
) -> RetentionCohortsRead:
    """Read seven- and thirty-day retention per arrival day (``/product/retention-cohorts``).

    **Served from the daily actor aggregate, and the ledger is never touched.** The one
    table this query names is ``observability_product_actor_daily``, which the nightly
    rollup writes from the product event ledger - one row per pseudonymous actor per day
    they did a qualifying clinical action. The raw ledger is read once a night by that
    rollup and by nothing else, so a thirty-day question costs thirty days of aggregate
    rows rather than thirty days of events, and the answer outlives the free vendor
    tier's fourteen-day retention because the system of record holds it.

    **Why not the step-grain rollup, and why not the ledger.** ``observability_product_daily``
    stores ``actor_count``, a distinct count, and distinctness does not survive being
    stored: the only way to get a distinct actor back out of it is to SUM, and summing
    double-counts precisely the people who got furthest - one patient who opened the
    composer and then submitted is two step rows and one person. #741 hit the same wall
    and read the ledger instead, which is right for a one- or thirty-day ACTIVE-USER
    count and wrong for a cohort, because a cohort is a question about identities
    spanning two days and the ledger is the only table that still has them. This is the
    table that keeps them without the ledger.

    **Three statements, one first-seen rule.** The cohort sizes and each horizon's
    retained counts both build on :func:`_cohort_arrivals`, so both horizons measure
    arrival on the same day. The two horizon statements differ only in the constant
    added to it, which is why the horizon is a named constant rather than a literal in
    a WHERE clause.

    ``days`` counts COHORT DATES and is not a truncation of either horizon: a
    ``days=7`` request still measures day-30 retention for each of its seven dates,
    which is the point of computing in Postgres rather than asking a vendor.

    **What "first" costs.** :func:`_cohort_arrivals` reaches the WHOLE aggregate to
    find each actor's earliest day, because a window-bounded minimum would report a
    returning patient as a new arrival and inflate exactly the oldest cohorts - the ones
    carrying the matured thirty-day figures. The scan stays inside this module's own
    daily aggregate and never touches the per-event ledger, which is the bound that
    matters here; what it does give up is an unbounded lower date.

    ``days`` is validated here rather than at the route, for the same reason every
    other windowed read validates here: every path into this read goes through here.
    """
    if days < 1:
        raise ValueError("days must be positive")

    actors = observability_product_actor_daily
    to_date = now.date()
    from_date = to_date - timedelta(days=days - 1)
    first_seen = _cohort_arrivals(actors, from_date=from_date, to_date=to_date)

    size_rows = await connection.execute(
        select(
            first_seen.c.first_date.label("cohort_date"),
            func.count().label("cohort_size"),
        )
        .select_from(first_seen)
        .group_by(first_seen.c.first_date)
        .order_by(first_seen.c.first_date)
    )
    cohort_sizes: dict[date, int] = {}
    for entry in size_rows.mappings():
        cohort_sizes[_row_day(entry["cohort_date"])] = int(entry["cohort_size"])

    retained: dict[int, dict[date, int]] = {}
    for horizon in _RETENTION_HORIZONS:
        rows = await connection.execute(
            _retained_by_cohort(actors, first_seen, horizon=horizon, to_date=to_date)
        )
        retained[horizon] = {
            _row_day(entry["cohort_date"]): int(entry["retained"]) for entry in rows.mappings()
        }

    cohorts: list[RetentionCohortDay] = []
    for offset in range(days):
        cohort_date = from_date + timedelta(days=offset)
        size = cohort_sizes.get(cohort_date, 0)
        retained_7d = _retained_or_none(
            cohort_date, RETENTION_WEEK_WINDOW, to_date, retained, cohort_size=size
        )
        retained_30d = _retained_or_none(
            cohort_date, RETENTION_MONTH_WINDOW, to_date, retained, cohort_size=size
        )
        cohorts.append(
            RetentionCohortDay(
                cohort_date=cohort_date,
                cohort_size=size,
                retained_7d=retained_7d,
                # ``ratio`` returns None for an empty cohort, which is 'no base to
                # divide by' rather than a measured absence of retention - and it is
                # the same helper every other rate in this facade uses, so a retention
                # figure renders at the same 4dp as a stickiness figure or an
                # abandonment rate. A horizon still in the future short-circuits to
                # None without a division at all.
                retention_7d=None if retained_7d is None else ratio(retained_7d, size),
                retained_30d=retained_30d,
                retention_30d=None if retained_30d is None else ratio(retained_30d, size),
            )
        )

    return RetentionCohortsRead(
        days=days,
        from_date=from_date,
        to_date=to_date,
        horizons=_RETENTION_HORIZONS,
        cohorts=cohorts,
        window_convention=RETENTION_WINDOW_CONVENTION,
        maturity_convention=RETENTION_MATURITY_CONVENTION,
        source_convention=RETENTION_SOURCE_CONVENTION,
        actor_convention=RETENTION_ACTOR_CONVENTION,
    )


class ProjectionBasis(BaseModel):
    """The assumption a projected month-end burn was computed from.

    Carried on the wire beside the projection rather than described in prose,
    because a projection with no stated basis is a guess with a decimal in it: an
    operator cannot tell "we project 400,000" from "we project 400,000 because
    200,000 went out over 16 of 31 days" without knowing which it is. The model
    is a straight line - spend to date spread evenly across the elapsed days and
    scaled to the period's length - so both day counts are what makes it checkable.
    """

    period_start: date
    period_end: date
    elapsed_days: int
    period_days: int


class ProviderSpend(BaseModel):
    """One model provider's spend over the period.

    Input and output are separate columns with separate figures, never a blended
    one. See :func:`_per_1k_paise` for what each side's figure is and is not.
    """

    provider: str
    jobs: int
    spend_paise: int
    input_tokens: int
    output_tokens: int
    paise_per_1k_input_tokens: Decimal | None
    paise_per_1k_output_tokens: Decimal | None


class ModelSpend(ProviderSpend):
    """One model's spend, WITHIN its provider.

    Repeats ``provider`` rather than nesting under
    :class:`ProviderSpend`: a flat row list keyed by ``(provider, model)`` is the
    same shape ``/usage`` already serves, it costs one table scan rather than a
    join, and a routing change shows up as a model moving between providers
    instead of a subtree quietly rebalancing.
    """

    model: str


class TaskTypeSpend(BaseModel):
    """One task type's spend over the period.

    Whatever the pipeline actually produced - ``transcribe``, ``structure`` and
    ``draft`` alike, since #722 made the drafting leg metered. The read filters on
    nothing but the period and the actor kind, so a task type nobody has declared
    anywhere still shows up rather than being dropped by a vocabulary this module
    would have to be taught about.
    """

    task_type: str
    jobs: int
    spend_paise: int
    input_tokens: int
    output_tokens: int
    paise_per_1k_input_tokens: Decimal | None
    paise_per_1k_output_tokens: Decimal | None


class MarginPercent(BaseModel):
    """One derived margin percentage, paired with the reason it is absent.

    **The pairing is the deliverable; the null is only the mechanism.** A margin
    percentage of ``0.00`` is indistinguishable from a real zero-revenue month, and a
    finance lead will put it in a deck: the number is not wrong, it is a claim about a
    thing nobody measured. So an absent figure must carry WHY it is absent, in a
    vocabulary a client can switch on (:data:`UNAVAILABLE_REASONS`) rather than a
    sentence it has to parse, and the two halves are validated as a pair - a figure can
    never be ``None`` without a reason or carry a reason while holding a value.

    ``value`` is a percentage at the 2dp scale the other ratios use, never a fraction.
    """

    value: Decimal | None
    reason: UnavailableReason | None
    detail: str | None

    @model_validator(mode="after")
    def _value_and_reason_agree(self) -> MarginPercent:
        # Deliberately NOT re-checking that ``reason`` is one of
        # :data:`UNAVAILABLE_REASONS`: the field is typed :data:`UnavailableReason`, so
        # pydantic has already refused anything else with the two accepted values in the
        # message. Re-checking a closed vocabulary here would be a second definition of
        # it, and the second one is the one that goes stale.
        if (self.value is None) != (self.reason is not None):
            raise ValueError(
                "a margin percentage carries a reason if and only if it is absent; got "
                f"value={self.value!r}, reason={self.reason!r}"
            )
        if self.reason is None and self.detail is not None:
            raise ValueError("a computed margin percentage carries no not-captured detail")
        return self


class MarginRead(BaseModel):
    """Revenue against AI cost of goods, plus the reason any percentage is absent.

    ``revenue_paise`` and ``cost_of_goods_paise`` are both read over the READ'S OWN
    PERIOD, so the two halves of every percentage here are like for like. A margin
    built from this month's cost and last week's revenue is a number nobody can act on,
    and the default period is ``month_to_date`` - so asking for the board figure is the
    zero-argument call.

    ``headline_month_cost_of_goods_paise`` is the separate, single number the finance
    story asks for: AI spend for the BILLING MONTH, which is not the selected period
    when an operator asks for ``today``. It is the same figure the read reports as
    ``cap_consumed_paise`` and the same one the ``ai_budget`` alert is evaluated
    against, carried under this name because it answers a different QUESTION ("what
    did AI cost us this month") from "how much of the cap is gone"; a test asserts the
    two figures are equal so the second name cannot become a second number.

    It is ``None`` - never ``0`` - when no budget snapshot row has been written. The
    snapshot is what says what the month has cost, and with no row there is no bill to
    quote: reporting zero beside a month that plainly has spend would be exactly the
    misleading zero the rest of this read is built to avoid, in the one figure a board
    is most likely to quote.

    ``revenue_captured`` and ``tiers_captured`` say whether the dimensions hold
    anything at all, and ``tier_keys`` carries what they hold. Both are ``False`` and
    ``[]`` today: the columns exist and stay empty, so switching monetization on is a
    data write and not a migration (#717 decision 9). Reporting them as present-and-
    empty rather than omitting them is what makes that promise checkable.
    """

    revenue_paise: int
    cost_of_goods_paise: int
    headline_month_cost_of_goods_paise: int | None
    revenue_captured: bool
    tiers_captured: bool
    tier_keys: list[str]
    gross_margin: MarginPercent
    ai_cost_pct_of_revenue: MarginPercent


class ActorSpendDistribution(BaseModel):
    """Where per-actor spend sits across the WHOLE population, not just the top of it.

    The three figures are the answer to "is this spend healthy", and they are reported
    instead of a mean for the reason they are reported: one heavy patient drags a mean
    far enough that the operator reads a typical patient as an expensive one. The
    median is the typical one, the ninety-fifth percentile is "who needs looking at",
    and the maximum is the ceiling nobody should be quietly surprised by.

    All three are ``None`` on an empty population rather than zero - no actors means
    there is no distribution to rank, not that every actor spent nothing. ``max`` is an
    integer because it is an observed figure rather than a rank: no interpolation, and
    a maximum that is off by a fraction of a paise is not a different maximum.
    """

    actors: int
    total_spend_paise: int
    median_spend_paise: Decimal | None
    p95_spend_paise: Decimal | None
    max_spend_paise: int | None


class PatientSpend(BaseModel):
    """One patient's spend over the period, and the doctor it was attributed to.

    ``patient_key`` is the one-way hash the aggregate stores, never an identity
    reference: a top-patient list is people-shaped data in a PHI-free schema, so what
    it can carry is a key an operator can correlate between panels and nothing they
    can identify a human from.

    ``attributed_doctor_key`` comes from the care-attribution edges (#724), which is
    the only legal record of that pairing - computing it by joining across to the care
    schema is forbidden (ADR-0003). It is ``None`` when no doctor is known yet, which
    is most patients before a doctor is picked, and equally ``None`` when the period
    contains a re-pick and two doctors both served this patient's spend: the aggregate
    records the doctor's own total and not which of the patient's jobs went to which
    doctor, so naming either would be a claim the data does not make. An answer is
    therefore only given where the recorded edge settles it.
    """

    patient_key: str
    attributed_doctor_key: str | None
    jobs: int
    completed_jobs: int
    failed_jobs: int
    spend_paise: int


class DoctorSpend(BaseModel):
    """One doctor's caseload cost over the period.

    ``doctor_key`` is pseudonymous for the same reason the patient key is, and
    ``patients`` counts the DISTINCT patients the recorded edges attribute to this
    doctor - the divisor that turns "this caseload is expensive" into "this caseload is
    expensive PER PERSON", which is the difference between a heavy doctor and an
    ordinary one seeing many patients. ``None`` when no edge names this doctor at all,
    which is a missing count rather than a count of zero.
    """

    doctor_key: str
    patients: int | None
    jobs: int
    completed_jobs: int
    failed_jobs: int
    spend_paise: int


class BusinessRead(BaseModel):
    """Spend for one period, against the monthly cap, with the breakdown.

    ``period``/``period_start``/``period_end`` echo the window the figures were read
    for, so a client rendering three of these knows which is which without keeping
    its own clock. Every window ends today and differs only in where it starts.

    ``spend_paise`` and the token volumes describe THE SELECTED PERIOD. The cap
    figures beside them describe the BILLING PERIOD, which is the month and not the
    selection: asking for ``today`` and learning nothing about how much of the month
    is already gone is how an operator finds out on the last day of the month.
    ``monthly_cap_paise`` and ``cap_consumed_paise`` are the pair the ``ai_budget``
    alert is evaluated against, taken from the same snapshot rows, so the headline
    and the alert cannot disagree.

    The projection is the "before the cap, not after" half of the question:
    ``projected_month_end_paise`` says where the month lands if the elapsed days
    are representative, ``projected_over_cap`` says whether that is past the cap,
    and ``projection_basis`` says what was assumed. Both are ``None`` when there is
    nothing to project from - an unstamped budget row has no period to spread spend
    across - which is an answer rather than a failure.

    **The unit figures answer "what does one unit of value cost?"** Cost per AI
    request, per completed task, per patient and per doctor, plus cost-of-pass - the
    named metric where the denominator is SUCCESSFUL OUTCOMES rather than tokens or
    raw requests, so an operator optimises for value delivered rather than for a cheap
    rate. Every one is a division computed here, over counters the nightly rollup
    already wrote; none is a column, because a stored copy would be a second source of
    truth that goes stale the moment a day is recomputed (#717 decision 8). Each is
    ``None`` on an empty denominator for the reason :func:`_per_1k_paise` gives: a
    scope that sent nothing has no per-unit price, and quoting ``0.0000`` would be a
    claim about its pricing that nothing measured.

    **Cost per doctor divides the ATTRIBUTED spend by the doctor count**, which is the
    one per-unit figure whose numerator is not the whole bill. Every rupee has exactly
    one patient, so cost per patient IS the bill over the patient count; spend only
    reaches a doctor once an attribution edge exists, so dividing the whole bill by the
    doctor count would report a number larger than any doctor's row and would not
    reconcile with ``doctor_spend`` beside it. What the reader gets is what a doctor's
    attributable caseload costs, with the unattributed remainder visible as the gap
    between the two totals.

    Cost-of-pass and cost-per-completed-task are the SAME division today and are kept
    as two fields anyway, because the aggregate carries exactly one successful-outcome
    counter (``completed_jobs``) and the spec names both metrics: the value delivered
    per finished leg, and the bill per pass. They come apart the moment a second
    outcome dimension lands - a pass that delivered a prescription is worth more than
    one that delivered a transcript - and a test asserts they coincide so nobody later
    reads the coincidence as a bug in one of them.

    The actor figures say WHO the money went to. ``patient_spend`` and ``doctor_spend``
    describe the whole population - median, ninety-fifth percentile and maximum, not a
    mean - while ``top_patients`` and ``top_doctors`` are the capped lists a panel
    renders. They are not halves of one bill: the rollup writes one row per ACTOR, so
    a doctor row MIRRORS the patient row of the same job, and the two totals reconcile
    through the recorded attribution edge rather than by being two shares of one
    number. ``doctor_spend.total_spend_paise`` is therefore at most the patient total,
    and the gap is exactly the spend whose doctor is not yet known.
    """

    period: BusinessPeriod
    period_start: date
    period_end: date
    spend_paise: int
    jobs: int
    completed_jobs: int
    failed_jobs: int
    input_tokens: int
    output_tokens: int
    paise_per_1k_input_tokens: Decimal | None
    paise_per_1k_output_tokens: Decimal | None
    monthly_cap_paise: int
    cap_consumed_paise: int
    cap_consumed_pct: Decimal
    projected_month_end_paise: int | None
    projected_over_cap: bool
    projection_basis: ProjectionBasis | None
    by_provider: list[ProviderSpend]
    by_model: list[ModelSpend]
    by_task_type: list[TaskTypeSpend]
    cost_per_request_paise: Decimal | None
    cost_per_completed_task_paise: Decimal | None
    cost_per_patient_paise: Decimal | None
    cost_per_doctor_paise: Decimal | None
    cost_of_pass_paise: Decimal | None
    patient_spend: ActorSpendDistribution
    doctor_spend: ActorSpendDistribution
    top_patients: list[PatientSpend]
    top_doctors: list[DoctorSpend]
    margin: MarginRead


#: Four-decimal scale of the cost-per-thousand-token figures (``0.1234``). The rate
#: scale rather than the percentage scale because the figure is not a percentage and
#: at 2dp most distinct rates collapse onto the same value: a cheap model's input
#: rate is a fraction of a paise per thousand tokens, and rounding it to hundredths
#: of a paise is a rounding that erases the difference it exists to show.
_COST_PER_1K_QUANTUM = Decimal("0.0001")

#: Four-decimal scale of every OTHER per-unit money figure (cost per request, per
#: completed task, per patient, per doctor, cost-of-pass). The same scale as
#: :data:`_COST_PER_1K_QUANTUM` and not reused from it: a constant named for one token
#: rate would be read at the next call site as a claim about per-token pricing, which
#: is exactly the misreading :func:`_per_1k_paise`'s docstring goes to some lengths to
#: warn against.
_UNIT_PAISES_QUANTUM = Decimal("0.0001")

#: Paise is the unit money is rounded back into; see ``modules.intake.pricing``.
_PAISE_QUANTUM = Decimal("1")

_BreakdownKey = TypeVar("_BreakdownKey")


def period_window(period: str, *, today: date | None = None) -> tuple[date, date]:
    """The inclusive ``[start, end]`` window one ``period`` names, ending today.

    The three periods differ ONLY in where they start - ``today`` is the day
    itself, ``week_to_date`` starts at the ISO week's Monday, ``month_to_date`` at
    the first of the calendar month - which is the whole reason one read serves all
    three (#717 decision 11).

    A week is the calendar week CONTAINING today, not a rolling seven days. "Week to
    date" is a period an operator reasons about against a calendar, and a rolling
    window reports a two-day-old Tuesday as a whole week of spend.
    """
    end = today if today is not None else datetime.now(UTC).date()
    if period == BUSINESS_PERIOD_TODAY:
        return end, end
    if period == BUSINESS_PERIOD_WEEK:
        return end - timedelta(days=end.weekday()), end
    if period == BUSINESS_PERIOD_MONTH:
        return end.replace(day=1), end
    raise ValueError(
        f"unknown business period {period!r}; expected one of {', '.join(BUSINESS_PERIODS)}"
    )


def _per_1k_paise(cost_paise: int, tokens: int) -> Decimal | None:
    """``cost`` paise spread over ``tokens``, per thousand tokens, at 4dp.

    ``None`` for an empty denominator, for the reason ``ratio`` and ``_per_minute``
    give: a scope that sent no tokens has no per-token price to quote, and quoting
    ``0.0000`` would be a claim about its pricing that nothing measured.

    The numerator is the scope's WHOLE metered cost on BOTH sides, because that is
    all the metered tables store - one ``cost_paise`` per job, not one per token side.
    So these are two rates, not two prices: ``cost * 1000 / input_tokens`` and
    ``cost * 1000 / output_tokens``, which between them carry the input:output MIX and
    the cost level. That is the information the ticket needs - a single
    ``cost / (input + output)`` figure averages the two denominators together and a
    routing change from cheap-output to expensive-output models moves it far less than
    it moves these - but it is NOT a per-side price, and the field names say so.

    Splitting the bill into two per-side prices needs per-side metering: an
    ``input_cost_paise``/``output_cost_paise`` pair carried from
    ``modules.intake.pricing`` through the per-job row and the daily aggregate. Until
    that exists, no honest read can quote two prices, and quoting two prices anyway
    would be the worse defect.
    """
    if tokens <= 0:
        return None
    return (Decimal(cost_paise) * 1000 / Decimal(tokens)).quantize(
        _COST_PER_1K_QUANTUM, rounding=ROUND_HALF_UP
    )


def _per_unit_paise(cost_paise: int, units: int) -> Decimal | None:
    """``cost`` paise spread over ``units`` of value, at the 4dp rate scale (#732).

    The "what does one unit cost" division behind cost per request, per completed task,
    per patient, per doctor and cost-of-pass. Same scale as :func:`_per_1k_paise` and
    for the same reason: these are rates on small denominators, and at 2dp a cost of
    0.4 paise per patient and one of 0.44 paise per patient render as the same figure,
    which erases the difference the number exists to show.

    ``None`` for an empty denominator, for the reason ``ratio``, ``_per_minute`` and
    :func:`_per_1k_paise` all give it: nothing was served, so there is no price to
    quote, and ``0.0000`` would be a claim about a scope that measured nothing.
    """
    if units <= 0:
        return None
    return (Decimal(cost_paise) / Decimal(units)).quantize(
        _UNIT_PAISES_QUANTUM, rounding=ROUND_HALF_UP
    )


def _spend_rank(samples: Sequence[int], fraction: float) -> Decimal | None:
    """The ``fraction`` percentile of integer-paise spend figures, in whole paise.

    Reuses the rollup's own :func:`~modules.observability.domain.rollup.percentile`
    rather than a second rank definition: the median here and the p50 on the latency
    panel must be the same statistic, or the operator comparing two panels is
    comparing two definitions. It returns ``None`` for an empty sample, which this
    passes straight through - an empty period has no median rather than a zero one.

    The result is rounded to whole paise because money is integer paise. That is the
    one place the interpolation the estimator does is undone, and it is correct: a
    median of 20,000.5 paise is not a spend anyone made.
    """
    ranked = percentile([float(value) for value in samples], fraction)
    if ranked is None:
        return None
    return Decimal(repr(ranked)).quantize(_PAISE_QUANTUM, rounding=ROUND_HALF_UP)


def _spend_distribution(spend_by_actor: Mapping[str, int]) -> ActorSpendDistribution:
    """Where one actor kind's spend sits across its whole population (#732).

    Computed over EVERY actor in the period, not over the capped list beside it. That
    is the difference between a distribution and a highlight reel: if the top ten were
    the sample, the median would describe the top ten and the ninety-fifth percentile
    would be the tenth, and both would be wrong by construction.

    ``total_spend_paise`` is the population total, which is what lets a caller check
    the capped list against the whole without re-reading the aggregate - and, for the
    doctor kind, is what makes the reconciliation with the patient total checkable:
    every doctor rupee is also a patient rupee, so the doctor total can only be at
    most the patient total and the gap is the spend whose doctor is not yet known.
    """
    values = list(spend_by_actor.values())
    if not values:
        return ActorSpendDistribution(
            actors=0,
            total_spend_paise=0,
            median_spend_paise=None,
            p95_spend_paise=None,
            max_spend_paise=None,
        )
    return ActorSpendDistribution(
        actors=len(values),
        total_spend_paise=sum(values),
        median_spend_paise=_spend_rank(values, 0.50),
        p95_spend_paise=_spend_rank(values, 0.95),
        max_spend_paise=max(values),
    )


def _margin_percent(value: Decimal | None, reason: UnavailableReason | None) -> MarginPercent:
    """A :class:`MarginPercent` with the detail that goes with ``reason``.

    The detail is looked up rather than written at the call site so the prose and the
    vocabulary cannot drift: there is no second place to say something different about
    the same reason.
    """
    return MarginPercent(
        value=value,
        reason=reason,
        detail=None if reason is None else _UNAVAILABLE_DETAIL[reason],
    )


def _margin_percentages(
    *, revenue_paise: int, revenue_captured: bool, cost_of_goods_paise: int
) -> tuple[MarginPercent, MarginPercent]:
    """Both margin percentages, derived from one answer about revenue.

    They are computed together because they are absent or present TOGETHER and for the
    same reason: with no revenue neither has a denominator, and there is no version of
    this data where one exists and the other does not. Two separate derivations would be
    two places for them to disagree, and a panel showing "gross margin: 62%, AI cost: n/a"
    would be reporting on half a fact.

    The two reasons are distinguished because they call for different action: revenue
    never captured means there is no revenue model to read, and revenue captured and zero
    means the denominator is zero for this period alone.
    """
    if not revenue_captured:
        absent = _margin_percent(None, UNAVAILABLE_REVENUE_NOT_CAPTURED)
        return absent, absent
    if revenue_paise <= 0:
        absent = _margin_percent(None, UNAVAILABLE_REVENUE_ZERO)
        return absent, absent
    scale = Decimal(revenue_paise)
    return (
        _margin_percent(
            (Decimal(revenue_paise - cost_of_goods_paise) / scale * 100).quantize(
                _PCT_QUANTUM, rounding=ROUND_HALF_UP
            ),
            None,
        ),
        _margin_percent(
            (Decimal(cost_of_goods_paise) / scale * 100).quantize(
                _PCT_QUANTUM, rounding=ROUND_HALF_UP
            ),
            None,
        ),
    )


@dataclass
class _BreakdownTotals:
    """Additive totals for one breakdown row, folded up from the grain's rows.

    Mutable and internal on purpose: the three breakdowns are roll-ups of ONE
    aggregation at ``(provider, model, task_type)`` grain, so the fold has to
    accumulate across rows rather than assign - which is what makes a provider row
    the sum of its own model rows by construction rather than by agreement.
    """

    jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_paise: int = 0

    def add(self, row: RowMapping) -> None:
        self.jobs += int(row["jobs"])
        self.completed_jobs += int(row["completed_jobs"])
        self.failed_jobs += int(row["failed_jobs"])
        self.input_tokens += int(row["input_tokens"])
        self.output_tokens += int(row["output_tokens"])
        self.cost_paise += int(row["cost_paise"])


def _spend_figures(totals: _BreakdownTotals) -> dict[str, Any]:
    """The six figures every breakdown row carries, whatever its key column.

    :class:`ProviderSpend`, :class:`ModelSpend` and :class:`TaskTypeSpend` differ only
    in which column names them - provider, provider plus model, or task type - so the
    measures are built ONCE here rather than restated per row type. That is also what
    makes the three breakdowns comparable: they are the same six numbers, projected
    three ways, so a caller summing one can compare it with a caller summing another.
    """
    return {
        "spend_paise": totals.cost_paise,
        "jobs": totals.jobs,
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "paise_per_1k_input_tokens": _per_1k_paise(totals.cost_paise, totals.input_tokens),
        "paise_per_1k_output_tokens": _per_1k_paise(totals.cost_paise, totals.output_tokens),
    }


@dataclass(frozen=True)
class _ActorTotals:
    """One actor's summed spend over the period, across every scope they touched.

    Frozen because the read builds it from an already-grouped row rather than folding
    into it: an actor is one ``(actor_kind, actor_key)`` group, so there is nothing to
    accumulate and a mutable counter here would invite exactly the kind of second
    folding that would put the actor figures at odds with the breakdown above them.
    """

    jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    cost_paise: int = 0

    @classmethod
    def from_row(cls, row: RowMapping) -> _ActorTotals:
        return cls(
            jobs=int(row["jobs"]),
            completed_jobs=int(row["completed_jobs"]),
            failed_jobs=int(row["failed_jobs"]),
            cost_paise=int(row["cost_paise"]),
        )


def _order_by_spend(totals: Mapping[str, _ActorTotals]) -> list[tuple[str, _ActorTotals]]:
    """Actors heaviest-first, with the pseudonymous key as a stable tiebreak.

    The tiebreak is not cosmetic: two actors with identical spend would otherwise swap
    places between two reads of an unchanged period, and a list whose order moves on
    its own is a list an operator stops trusting.
    """
    return sorted(totals.items(), key=lambda item: (-item[1].cost_paise, item[0]))


def _distinct_patients(patients: set[str] | None) -> int | None:
    """How many distinct patients ``patients`` holds, or ``None`` when nothing does.

    ``None`` rather than zero, for the same reason every other absent figure on this
    read is null. A doctor row can exist with no recorded edge behind it - the rollup
    falls back to the doctor key a job row carries - and for that doctor the pairing is
    simply not recorded. ``0`` beside a non-zero ``spend_paise`` would be read as "this
    doctor served nobody", which is a claim about a caseload rather than a statement
    about the data; ``None`` says the count is unavailable.
    """
    return None if patients is None else len(patients)


def _doctor_for_patient(edges: Mapping[str, set[str]], patient_key: str) -> str | None:
    """The doctor ``patient_key``'s recorded edges name, or ``None`` when they do not
    settle it.

    An edge is one ``intake.doctor_assigned`` delivery, and a patient who re-picks can
    accumulate several - the table is UNIQUE on ``intake_ref``, not on the patient. A
    name is therefore only unambiguous for a patient with exactly one, and this says so
    rather than guessing: it returns the single doctor when there is one, and ``None``
    when the patient's spend sits against two or more, because a top-patient row that
    named an arbitrary one of them would be a claim the data does not make.

    The absence costs the reconciliation nothing. That patient's rupee is still in
    ``doctor_spend`` and still appears on the doctor rows the edges DO name, so the
    conservation law holds over the whole population; what a top-patient row gives up
    is naming the doctor, not accounting for the money.
    """
    doctors: frozenset[str] = frozenset(edges.get(patient_key, ()))
    return next(iter(doctors)) if len(doctors) == 1 else None


def _accumulate(
    bucket: dict[_BreakdownKey, _BreakdownTotals], key: _BreakdownKey, row: RowMapping
) -> None:
    """Fold one grain row into ``bucket``, creating its entry on first sight."""
    bucket.setdefault(key, _BreakdownTotals()).add(row)


def _projected_month_end(
    *, consumed_paise: int, period_start: date | None, period_end: date | None, today: date
) -> tuple[int | None, ProjectionBasis | None]:
    """Where the month lands at a straight line, with the basis it was computed from.

    Spend consumed so far, spread evenly over the ``elapsed_days`` of the billing
    period that have actually happened and scaled up to the period's ``period_days``.
    A straight line is a crude model - real spend is not uniform across a month -
    and the only honest answer to that is to say so, which is what returning the
    basis alongside the figure is for.

    ``(None, None)`` when there is nothing to project from: an unstamped budget row
    has no period to spread the spend across, and a period that has not started has
    no elapsed days to divide by. ``today`` is clamped to ``period_end`` so a stale
    snapshot stamped on a closed month projects its final figure rather than
    extrapolating past a month that is over.
    """
    if period_start is None or period_end is None or period_end < period_start:
        return None, None
    period_days = (period_end - period_start).days + 1
    elapsed_days = (min(today, period_end) - period_start).days + 1
    if elapsed_days < 1:
        return None, None
    projected = Decimal(consumed_paise) * Decimal(period_days) / Decimal(elapsed_days)
    return (
        int(projected.quantize(_PAISE_QUANTUM, rounding=ROUND_HALF_UP)),
        ProjectionBasis(
            period_start=period_start,
            period_end=period_end,
            elapsed_days=elapsed_days,
            period_days=period_days,
        ),
    )


async def query_business(
    connection: AsyncConnection,
    *,
    period: BusinessPeriod,
    from_date: date,
    to_date: date,
    today: date,
) -> BusinessRead:
    """Read period spend, the cap it is measured against, and the breakdown.

    ONE aggregation over ``observability_attribution_daily`` at
    ``(provider, model, task_type)`` grain serves the headline, the provider rows,
    the model rows and the task-type rows; the three breakdowns are folded up from
    it in Python rather than issued as three queries that would have to be kept in
    agreement by hand. Today, week-to-date and month-to-date are three windows over
    this one read, not three reads (#717 decision 11).

    Everything spend-shaped is computed here, at read time, out of the daily
    per-actor aggregate - the same number is never stored twice (#717 decision 8),
    so this read and the ``ai_budget`` alert cannot report different bills.

    **Only ``patient`` rows are aggregated.** Every job contributes one patient row
    and, when a doctor is known, one doctor row with identical figures - that is how
    per-patient and per-doctor figures reconcile, not two halves of the bill. Summing
    both kinds would count every rupee twice, so the kind is a filter on the money
    and the doctor rows are a projection #732 reads rather than a second total.

    The cap and the consumed figure come from ``observability_ai_cost_budget``,
    through the SAME ``_budget_view`` projection and the same ``_budget_totals``
    max-not-sum rule ``query_cost_summary`` uses, because that pair is the one the
    ``ai_budget`` alert is evaluated against and a business panel reporting a different
    cap - or a different bill - would contradict it. It is therefore read, not
    recomputed: the aggregate and the snapshot carry the same month-to-date figure
    because the rollup writes both from the same per-job rows, and reading one of them
    keeps the two panels and the alert on one number.

    The projection's period bounds are the snapshot's own stamps, taken as the widest
    span the rows carry - the same rule ``/cost`` reads them by. That holds because the
    rollup's period reset re-stamps every stale or unstamped row inside the same
    transaction it snapshots in, so a mixed set of periods cannot survive a pass.

    **The actor figures come off the SAME table, one query, both kinds** (#732). An
    actor's spend over a period is a fold over the same grain rows the breakdowns are
    folded from, so ``patient_spend``/``doctor_spend`` and the two top lists cannot
    disagree with the headline: they are the same numbers grouped by a different column.
    Reading ``patient`` and ``doctor`` separately would be two more queries whose
    agreement nothing would enforce.

    The care-attribution edges are read for the patients in the window, not for the
    whole table: they are how a patient's spend is tied to a doctor, and an edge for a
    patient who sent nothing in this period cannot appear in this period's answer.
    """
    spend = observability_attribution_daily
    rows = await connection.execute(
        select(
            spend.c.provider,
            spend.c.model,
            spend.c.task_type,
            func.coalesce(func.sum(spend.c.jobs), 0).label("jobs"),
            func.coalesce(func.sum(spend.c.completed_jobs), 0).label("completed_jobs"),
            func.coalesce(func.sum(spend.c.failed_jobs), 0).label("failed_jobs"),
            func.coalesce(func.sum(spend.c.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(spend.c.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(spend.c.cost_paise), 0).label("cost_paise"),
        )
        .where(
            spend.c.actor_kind == ACTOR_KIND_PATIENT,
            spend.c.usage_date.between(from_date, to_date),
        )
        .group_by(spend.c.provider, spend.c.model, spend.c.task_type)
        .order_by(spend.c.provider, spend.c.model, spend.c.task_type)
    )

    totals = _BreakdownTotals()
    by_provider: dict[str, _BreakdownTotals] = {}
    by_model: dict[tuple[str, str], _BreakdownTotals] = {}
    by_task_type: dict[str, _BreakdownTotals] = {}
    for row in rows.mappings():
        totals.add(row)
        _accumulate(by_provider, str(row["provider"]), row)
        _accumulate(by_model, (str(row["provider"]), str(row["model"])), row)
        _accumulate(by_task_type, str(row["task_type"]), row)

    budget_rows = await connection.execute(
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
    budgets = [_budget_view(row) for row in budget_rows.mappings()]
    monthly_cap, cap_consumed = _budget_totals(budgets)
    projected, basis = _projected_month_end(
        consumed_paise=cap_consumed,
        period_start=_earliest_period_start(budgets),
        period_end=_latest_period_end(budgets),
        today=today,
    )

    patient_totals, doctor_totals = await _query_actor_spend(
        connection, from_date=from_date, to_date=to_date
    )
    edges = await _query_care_edges(connection, from_date=from_date, to_date=to_date)
    margin = await _query_margin_dimensions(
        connection,
        from_date=from_date,
        to_date=to_date,
        period_spend_paise=totals.cost_paise,
        # Absent rather than zero when the snapshot has no row: see MarginRead. The
        # read cannot invent the month's bill from nothing, and an operator is better
        # served by "no bill recorded yet" than by a zero they will quote.
        headline_month_cost_of_goods_paise=cap_consumed if budgets else None,
    )

    ordered_patients = _order_by_spend(patient_totals)
    ordered_doctors = _order_by_spend(doctor_totals)
    patient_spend = _spend_distribution(
        {key: scope.cost_paise for key, scope in patient_totals.items()}
    )
    doctor_spend = _spend_distribution(
        {key: scope.cost_paise for key, scope in doctor_totals.items()}
    )
    # One pass over the edges builds BOTH directions of the same pairing: the doctor a
    # patient's spend sits against, and the patients each doctor carries. Rescanning the
    # edge list once per row of either top list would make the read quadratic in the
    # number of edges, for a table that grows with the platform.
    doctors_of: dict[str, set[str]] = {}
    patients_of: dict[str, set[str]] = {}
    for patient_key, doctor_key in edges:
        doctors_of.setdefault(patient_key, set()).add(doctor_key)
        patients_of.setdefault(doctor_key, set()).add(patient_key)

    return BusinessRead(
        period=period,
        period_start=from_date,
        period_end=to_date,
        completed_jobs=totals.completed_jobs,
        failed_jobs=totals.failed_jobs,
        **_spend_figures(totals),
        monthly_cap_paise=monthly_cap,
        cap_consumed_paise=cap_consumed,
        cap_consumed_pct=_utilization_pct(cap_consumed, monthly_cap),
        projected_month_end_paise=projected,
        projected_over_cap=monthly_cap > 0 and projected is not None and projected > monthly_cap,
        projection_basis=basis,
        by_provider=[
            ProviderSpend(provider=provider, **_spend_figures(scope))
            for provider, scope in sorted(by_provider.items())
        ],
        by_model=[
            ModelSpend(provider=provider, model=model, **_spend_figures(scope))
            for (provider, model), scope in sorted(by_model.items())
        ],
        by_task_type=[
            TaskTypeSpend(task_type=task_type, **_spend_figures(scope))
            for task_type, scope in sorted(by_task_type.items())
        ],
        cost_per_request_paise=_per_unit_paise(totals.cost_paise, totals.jobs),
        cost_per_completed_task_paise=_per_unit_paise(totals.cost_paise, totals.completed_jobs),
        cost_per_patient_paise=_per_unit_paise(totals.cost_paise, patient_spend.actors),
        cost_per_doctor_paise=_per_unit_paise(doctor_spend.total_spend_paise, doctor_spend.actors),
        cost_of_pass_paise=_per_unit_paise(totals.cost_paise, totals.completed_jobs),
        patient_spend=patient_spend,
        doctor_spend=doctor_spend,
        top_patients=[
            PatientSpend(
                patient_key=key,
                attributed_doctor_key=_doctor_for_patient(doctors_of, key),
                jobs=scope.jobs,
                completed_jobs=scope.completed_jobs,
                failed_jobs=scope.failed_jobs,
                spend_paise=scope.cost_paise,
            )
            for key, scope in ordered_patients[:MAX_BUSINESS_TOP_ACTORS]
        ],
        top_doctors=[
            DoctorSpend(
                doctor_key=key,
                patients=_distinct_patients(patients_of.get(key)),
                jobs=scope.jobs,
                completed_jobs=scope.completed_jobs,
                failed_jobs=scope.failed_jobs,
                spend_paise=scope.cost_paise,
            )
            for key, scope in ordered_doctors[:MAX_BUSINESS_TOP_ACTORS]
        ],
        margin=margin,
    )


async def _query_actor_spend(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> tuple[dict[str, _ActorTotals], dict[str, _ActorTotals]]:
    """Per-actor spend over the window, split by the two actor kinds (#732).

    ONE grouped read over ``observability_attribution_daily`` at ``(actor_kind,
    actor_key)``, returned as the patient map and the doctor map. Both actor kinds
    come from it because they are the same rows read under two values of one column,
    and issuing two queries would put the reconciliation between the per-patient and
    per-doctor totals at the mercy of two filters drifting apart.

    Every actor in the window is returned, not a top slice: the distribution beside
    the capped list is computed over this whole map, and SQL ``LIMIT`` would take the
    sample out from under it.
    """
    spend = observability_attribution_daily
    rows = await connection.execute(
        select(
            spend.c.actor_kind,
            spend.c.actor_key,
            func.coalesce(func.sum(spend.c.jobs), 0).label("jobs"),
            func.coalesce(func.sum(spend.c.completed_jobs), 0).label("completed_jobs"),
            func.coalesce(func.sum(spend.c.failed_jobs), 0).label("failed_jobs"),
            func.coalesce(func.sum(spend.c.cost_paise), 0).label("cost_paise"),
        )
        .where(
            spend.c.actor_kind.in_((ACTOR_KIND_PATIENT, ACTOR_KIND_DOCTOR)),
            spend.c.usage_date.between(from_date, to_date),
        )
        .group_by(spend.c.actor_kind, spend.c.actor_key)
    )

    patients: dict[str, _ActorTotals] = {}
    doctors: dict[str, _ActorTotals] = {}
    for row in rows.mappings():
        totals = _ActorTotals.from_row(row)
        if str(row["actor_kind"]) == ACTOR_KIND_PATIENT:
            patients.setdefault(str(row["actor_key"]), totals)
        else:
            doctors.setdefault(str(row["actor_key"]), totals)
    return patients, doctors


async def _query_care_edges(
    connection: AsyncConnection, *, from_date: date, to_date: date
) -> list[tuple[str, str]]:
    """``(patient_key, doctor_key)`` edges for the patients this window touched.

    Restricted to the patients in the window by a subquery over the same aggregate,
    because the edge table has no date of its own to filter on - it is keyed by intake
    - and an answer naming a doctor for a patient who spent nothing this period is a
    row this read has no business returning. The table is one row per intake, so it is
    small enough that reading it whole would work; the restriction is here so that
    stays true as the platform does.

    Returned as a list of pairs rather than a dict because a patient may hold several
    edges (a re-pick overwrites by ``intake_ref``, not by patient), and collapsing them
    into one key each would silently drop the very ambiguity a reader has to be able to
    see. :func:`_doctor_for_patient` decides what a single row may claim.
    """
    spend = observability_attribution_daily
    edges = observability_care_attribution_edges
    rows = await connection.execute(
        select(edges.c.patient_key, edges.c.doctor_key).where(
            edges.c.patient_key.in_(
                select(spend.c.actor_key).where(
                    spend.c.actor_kind == ACTOR_KIND_PATIENT,
                    spend.c.usage_date.between(from_date, to_date),
                )
            )
        )
    )
    return [(str(row["patient_key"]), str(row["doctor_key"])) for row in rows.mappings()]


async def _query_margin_dimensions(
    connection: AsyncConnection,
    *,
    from_date: date,
    to_date: date,
    period_spend_paise: int,
    headline_month_cost_of_goods_paise: int | None,
) -> MarginRead:
    """Read the revenue and tier dimensions, and say why margin is absent (#732).

    Both columns live on the daily per-actor aggregate and both are NULL on every row
    today: the PRD defers the revenue model, so the rollup has no source for them and
    deliberately does not write them (#717 decision 9). They are READ here rather than
    omitted, which is what makes "turning monetization on is a data write, not a
    migration" a claim this read can be checked against - a dimension the read did not
    look at cannot be shown to be empty.

    Revenue is read over the READ'S OWN PERIOD so the two halves of every percentage
    are like for like, and the headline month's cost of goods rides beside it for the
    board figure.

    ``COUNT(revenue_paise)`` rather than ``SUM`` decides whether revenue is captured:
    ``SUM`` of no rows and ``SUM`` of rows that are all NULL are both zero, and the
    difference between "we collected nothing" and "we collected no revenue" is exactly
    the difference between a reason and a margin.
    """
    spend = observability_attribution_daily
    revenue_rows = await connection.execute(
        select(
            func.coalesce(func.sum(spend.c.revenue_paise), 0).label("revenue_paise"),
            func.count(spend.c.revenue_paise).label("captured_rows"),
        ).where(
            spend.c.actor_kind == ACTOR_KIND_PATIENT,
            spend.c.usage_date.between(from_date, to_date),
        )
    )
    revenue = revenue_rows.mappings().one()
    tier_rows = await connection.execute(
        select(spend.c.tier_key)
        .where(
            spend.c.actor_kind == ACTOR_KIND_PATIENT,
            spend.c.usage_date.between(from_date, to_date),
            spend.c.tier_key.is_not(None),
        )
        .distinct()
        .order_by(spend.c.tier_key)
    )
    tier_keys = [str(row["tier_key"]) for row in tier_rows.mappings()]

    revenue_paise = int(revenue["revenue_paise"])
    captured_rows = int(revenue["captured_rows"])
    revenue_captured = captured_rows > 0
    tiers_captured = bool(tier_keys)
    gross_margin, ai_cost_pct = _margin_percentages(
        revenue_paise=revenue_paise,
        revenue_captured=revenue_captured,
        cost_of_goods_paise=period_spend_paise,
    )

    return MarginRead(
        revenue_paise=revenue_paise,
        cost_of_goods_paise=period_spend_paise,
        headline_month_cost_of_goods_paise=headline_month_cost_of_goods_paise,
        revenue_captured=revenue_captured,
        tiers_captured=tiers_captured,
        tier_keys=tier_keys,
        gross_margin=gross_margin,
        ai_cost_pct_of_revenue=ai_cost_pct,
    )


def build_deeplinks(
    *,
    grafana_url: str | None = None,
    sentry_dsn: str | None = None,
    langfuse_host: str | None = None,
    langfuse_public_key: str | None = None,
    # The Sentry ``service`` filter and the dashboard's ``var-service`` both name the
    # platform's own service identity. It is a constant rather than configuration
    # because there is exactly one: ``observability.otel`` says so at
    # ``SERVICE_NAME`` - the composition roots pass the SAME ``SERVICE_API`` /
    # ``SERVICE_WORKER`` identities precisely "so a process has one name across
    # logs and traces". A configurable service name here would let the links filter
    # on something telemetry never reported.
    service: str = SERVICE_API,
    environment: str | None = None,
    window: str = DEFAULT_GRAFANA_WINDOW,
    trace_id: str | None = None,
    actor_key: str | None = None,
    session_key: str | None = None,
    model: str | None = None,
    task_type: str | None = None,
    error_type: str | None = None,
) -> Deeplinks:
    """Derive the parameterised vendor link sets from Settings (``/deeplinks``).

    No database and no network: the read is a projection of configuration plus the
    caller's context, so it cannot fail because a vendor is absent or unreachable.
    Each vendor is derived independently, which is what lets a Sentry-only
    deployment answer with a Sentry link and nothing else.

    The context arguments are all OPTIONAL and all come from the caller, never from
    here: ``trace_id`` is the platform's own stored identifier handed over by whichever
    read the operator was looking at, ``actor_key``/``session_key`` are the
    pseudonymous keys the product ledger stores, and ``model``/``task_type``/
    ``error_type`` name what the panel in front of the operator was showing. This
    function never looks one of them up and never invents one - a link built from a
    guessed identifier opens a trace that does not exist, which is worse than no
    link.

    A vendor whose links are ALL empty is left ``None`` rather than answered with an
    object of nulls, so "this deployment ships no Grafana" and "this deployment ships
    Grafana but nothing to link to" are one absence the client renders the same way:
    as nothing.
    """
    trace = clean_trace_id(trace_id)

    grafana_links: GrafanaDeeplinks | None = None
    dashboard_url = grafana_dashboard_link(
        grafana_url,
        dashboard_uid=GRAFANA_DASHBOARD_UID,
        window=window,
        service=service,
        environment=environment,
    )
    if dashboard_url is not None:
        # ``GRAFANA_DASHBOARD_UID`` is the default the dashboard derivation used, so
        # the uid the model carries cannot name a different dashboard than the URL
        # does. It is carried anyway so a client can label the link without parsing
        # a path segment back out of it.
        grafana_links = GrafanaDeeplinks(
            dashboard_uid=GRAFANA_DASHBOARD_UID,
            dashboard_url=dashboard_url,
            explore_url=grafana_explore_link(grafana_url, trace_id=trace, window=window),
        )

    sentry_links: SentryDeeplinks | None = None
    project = sentry_project(sentry_dsn)
    issues_url = sentry_issues_link(sentry_dsn, service=service, error_type=error_type)
    if project is not None and issues_url is not None:
        sentry_links = SentryDeeplinks(
            project_id=project[1],
            issues_url=issues_url,
            trace_url=sentry_trace_link(sentry_dsn, trace_id=trace),
        )

    traces_url = langfuse_traces_link(
        langfuse_host, langfuse_public_key, model=model, task_type=task_type
    )
    lf_trace_url = langfuse_trace_link(langfuse_host, langfuse_public_key, trace_id=trace)
    lf_actor_url = langfuse_actor_link(langfuse_host, langfuse_public_key, actor_key=actor_key)
    lf_session_url = langfuse_session_link(
        langfuse_host, langfuse_public_key, session_key=session_key
    )

    # Langfuse has no bare project view to fall back on, so a caller that supplied no
    # model, task, trace, actor or session gets no group at all - the same absence an
    # unconfigured workspace produces, and the same thing for the client to render.
    langfuse_links: LangfuseDeeplinks | None = None
    if any(url is not None for url in (traces_url, lf_trace_url, lf_actor_url, lf_session_url)):
        langfuse_links = LangfuseDeeplinks(
            traces_url=traces_url,
            trace_url=lf_trace_url,
            actor_url=lf_actor_url,
            session_url=lf_session_url,
        )

    return Deeplinks(
        trace_id=trace,
        grafana=grafana_links,
        sentry=sentry_links,
        langfuse=langfuse_links,
    )


class ObservabilityFacade:
    """Typed public facade for observability.

    The B4 public surface carries the effects the event consumers run. The C1
        (``#706``/``#707``) read seam joins it: ``get_cost_summary``,
        ``get_cost_trend``, ``get_usage``, ``get_quality``, ``get_overview``,
        ``get_latency``, ``get_provider_board`` (#728), ``get_throughput``,
        ``get_health``, ``get_reliability`` (#729), ``get_alerts``,
        ``get_error_feed`` (#730), ``get_business`` (#731), ``get_funnel`` (#740),
        ``get_active_users`` (#741) and
        ``get_deeplinks`` are what the operator observability routes call. Each opens
        the one settled engine connection and delegates its aggregate to the module
        helper, so routes hold no SQL and the reads stay in this module.

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

    async def acknowledge_alert(
        self, *, alert_id: UUID, acked_by: int, now: datetime | None = None
    ) -> AlertAcknowledgement:
        """Acknowledge one alert as ``acked_by`` (#735), the module's only write.

        The clock is resolved HERE, against the current UTC instant, for the same
        reason the windowed reads resolve theirs here rather than in the route: a
        test can pin ``now`` and get the identical ``acked_at`` production would
        have stamped at that instant, and the route carries no time of its own.

        ``acked_by`` is an identity reference, not a display name - the same shape
        every other ``*_by`` column in the platform records "who did this" with.
        """
        acked_at = now if now is not None else datetime.now(UTC)
        async with self._engine.begin() as connection:
            return await acknowledge_alert(
                connection, alert_id=alert_id, acked_by=acked_by, acked_at=acked_at
            )

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

    async def get_funnel(
        self,
        *,
        days: int,
        outcome: ProductOutcome | None = None,
        funnel: str = FUNNEL_INTAKE,
        now: datetime | None = None,
    ) -> FunnelRead:
        """Read the intake funnel over its window (``/product/funnel``, #740).

        "Is the product working?" answered from the product event ledger (#739): the
        per-step counts, the completion and abandonment that end each one, the median
        gap between one step and the next, and the terminal it reached - in one
        response, because the figures only mean something read together.

        The clock is resolved HERE, for the same reason every other windowed read
        resolves its own: the route owns the default and the facade owns the clock, so
        a test can pin ``now`` and get the identical window production would have
        taken at that instant.

        Neither ``days`` nor ``outcome`` is validated here:
        :func:`query_funnel` owns both checks and every path into this read goes
        through it, so a second copy would only be a second place for the two to
        disagree about what a valid window or a known outcome is.
        """
        to_ts = now if now is not None else datetime.now(UTC)
        async with self._engine.begin() as connection:
            return await query_funnel(
                connection,
                funnel=funnel,
                outcome=outcome,
                now=to_ts,
                window_days=days,
            )

    async def get_active_users(self, *, days: int, now: datetime | None = None) -> ActiveUsersRead:
        """Read DAU, WAU, MAU, stickiness and load per head (``/product/active-users``).

        B4f (#741). "Is adoption growing?" answered from the product event ledger
        (#739) and the per-minute request counter (#727), both of them Postgres: the
        free metrics tier's fourteen-day retention makes a monthly figure structurally
        impossible in the vendor, so this read exists precisely to compute it in the
        system of record instead of quietly reporting a fortnight as a month.

        The clock is resolved HERE, for the same reason every other windowed read
        resolves its own: the route owns the default and the facade owns the clock, so
        a test can pin ``now`` and get the identical windows production would have
        taken at that instant. It is resolved once and read four times - the day, the
        week and the month all end on the SAME ``now``, so two reads seconds apart
        cannot report two different stickiness figures for one screen.

        ``days`` is NOT validated here: :func:`query_active_users` owns that check and
        every path into this read goes through it, so a second copy would only be a
        second place for the two to disagree about what a valid window is.
        """
        to_ts = now if now is not None else datetime.now(UTC)
        async with self._engine.begin() as connection:
            return await query_active_users(connection, days=days, now=to_ts)

    async def get_retention_cohorts(
        self, *, days: int, now: datetime | None = None
    ) -> RetentionCohortsRead:
        """Read seven- and thirty-day retention per arrival day (``/product/retention-cohorts``).

        B4g (#742). "Does adoption stick?", answered from the daily per-actor product
        aggregate the nightly rollup writes from the product event ledger - so the
        answer outlives the free vendor tier's fourteen-day retention, and a thirty-day
        question never scans the raw ledger.

        The clock is resolved HERE for the same reason every other windowed read
        resolves its own: the route owns the default and the facade owns the clock, so
        a test can pin ``now`` and get the identical cohort dates production would
        have taken at that instant. Both horizons are measured against that ONE
        ``now``, so a cohort cannot be mature against the week and immature against
        the month.

        ``days`` is NOT validated here: :func:`query_retention_cohorts` owns that
        check and every path into this read goes through it, so a second copy would
        only be a second place for the two to disagree about what a valid window is.
        """
        to_ts = now if now is not None else datetime.now(UTC)
        async with self._engine.begin() as connection:
            return await query_retention_cohorts(connection, days=days, now=to_ts)

    async def get_business(
        self, *, period: BusinessPeriod, today: date | None = None
    ) -> BusinessRead:
        """Read spend for ``period`` against the monthly cap, with the breakdown.

        B2 (#731, widened by #732). One method for all three periods: ``today``,
        ``week_to_date`` and ``month_to_date`` are three windows of this read, and the
        alternative - a method each - would be three copies of the aggregation to keep
        in agreement (#717 decision 11). The per-unit figures, the per-actor
        attribution and the not-captured margin answer ride this same method rather
        than three more that would each have to re-read the same aggregate.

        The clock is resolved HERE and the window resolved off it, for the same
        reason every other windowed read does: the route owns the default and the
        facade owns the clock, so a test can pin ``today`` and get the identical
        window production would have taken at that date. ``today`` is resolved ONCE
        and used both for the window and for the projection's elapsed-day count -
        two reads of the clock could straddle midnight and put this month's spend
        into tomorrow's window.

        ``period`` is NOT validated here: :func:`period_window` owns that check and
        every path into this read goes through it, so a second copy would only be a
        second place for the two to disagree about what a valid period is.
        """
        resolved_today = today if today is not None else datetime.now(UTC).date()
        from_date, to_date = period_window(period, today=resolved_today)
        async with self._engine.begin() as connection:
            return await query_business(
                connection,
                period=period,
                from_date=from_date,
                to_date=to_date,
                today=resolved_today,
            )

    def get_deeplinks(
        self,
        *,
        grafana_url: str | None = None,
        sentry_dsn: str | None = None,
        langfuse_host: str | None = None,
        langfuse_public_key: str | None = None,
        service: str = SERVICE_API,
        environment: str | None = None,
        window: str = DEFAULT_GRAFANA_WINDOW,
        trace_id: str | None = None,
        actor_key: str | None = None,
        session_key: str | None = None,
        model: str | None = None,
        task_type: str | None = None,
        error_type: str | None = None,
    ) -> Deeplinks:
        """Derive the parameterised vendor link sets from the configured Settings.

        Synchronous: it reads configuration and the caller's context, never storage.
        It stays on the facade so the routes keep the one seam every other read goes
        through and the derivation has one home to be tested in.

        ``trace_id`` and the rest of the context are the CALLER's, taken from whatever
        platform read put the operator on the panel they are looking at - the error
        feed's stored ``trace_id``, a product-event row's pseudonymous ``actor_key``,
        a usage row's ``model``/``task_type``. This method looks none of them up, and
        that is deliberate: a link built from an identifier the platform never stored
        opens an empty view and is worse than no link.
        """
        return build_deeplinks(
            grafana_url=grafana_url,
            sentry_dsn=sentry_dsn,
            langfuse_host=langfuse_host,
            langfuse_public_key=langfuse_public_key,
            service=service,
            environment=environment,
            window=window,
            trace_id=trace_id,
            actor_key=actor_key,
            session_key=session_key,
            model=model,
            task_type=task_type,
            error_type=error_type,
        )
