"""MOD-013: HTTP adapter for the operator observability surfaces (PHASE-14A C1, #706/#707).

Twelve ``GET`` reads plus, since B5 (#735), the module's one ``POST`` write. The
reads are the plan-phase14 §9.1 read table; the write is the alert acknowledgement,
against a row this module already owns.

The endpoints are thin adapters (api-standards §1): resolve the gateway
``Principal``, validate the query params, call the observability facade, answer its
typed view. They sit behind the gateway middleware stack in ``app.main``; every
route declares ``require_operator`` (NFR-SEC-003, api-standards §6), so an
anonymous caller is refused 401 and any non-operator scope 403 - both through the
shared gateway error envelope, and both before the facade is reached.

The READS raise no module-level domain exceptions (an un-budgeted month, a window
with no traffic, and an uncapped scope are all answers, not failures), so they
need no error handler of their own - RBAC rejections answer through the gateway
handlers and anything unexpected falls to the app catch-all. B5 (#735) adds the
module's first WRITE, and a write has outcomes a read never does: an alert that
does not exist and an alert that is already resolved are both expected failures an
operator can cause deliberately, so :func:`register_error_handlers` answers those
two through the shared envelope rather than letting them fall to the catch-all as
a 5xx.

Scope: the whole plan-phase14 §9.1 read table. C1a (#706) serves ``cost``,
``cost/trend``, ``usage`` and ``quality``; C1b (#707) adds ``overview``,
``latency``, ``health``, ``alerts`` and ``deeplinks``; B9 (#727) adds
``throughput``, the per-minute request counter and the capture-liveness answer;
B9 (#728) adds ``providers``, the degraded-provider board; B5 (#729) adds
``reliability``, the queue depth/age read with the per-outbox breakdown, the
recent-activity figure and the link out to true concurrency; B8 (#730) adds
``errors``, the live collapsed error stream with its open/resolved split; B2
(#731) adds ``business``, the period-parameterised spend read - today, week-to-date
and month-to-date are three windows of ONE endpoint.
B2 (#732) widens that one response with the per-unit figures, the per-patient and
per-doctor attribution and the not-captured margin reason - the same read, answered
more fully, because a second endpoint would re-read the same aggregate and the two
answers would have to be kept in agreement by hand.
B5 (#735) adds the one WRITE, ``/alerts/{alert_id}/acknowledge``, and widens the
alert feed's status filter to the three statuses that write can now produce.
B4f (#741) adds ``/product/active-users``, the adoption read - DAU, WAU, MAU, the
stickiness between them and the load per head - which is the one read whose figures
cannot come from a vendor at all, because the free metrics tier's fourteen-day
retention makes a monthly active user structurally impossible there.
B4g (#742) adds ``/product/retention-cohorts``, the stickiness read - what share of
each arrival day came back at seven and at thirty days. It is the question DAU/WAU/MAU
cannot answer, because a product that acquires and churns in equal measure leaves those
three windows looking healthy. It is also the first of these reads to be served from a
DAILY aggregate rather than the ledger: a cohort is a question about identities spanning
two days, and only a per-actor day row still has them - so the thirty-day answer never
scans the raw ledger and outlives the vendor's fourteen-day retention on its own.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.config import Settings
from app.gateway.errors import error_response
from app.gateway.idempotency import run_idempotent
from app.gateway.principal import Principal
from app.gateway.rbac import require_admin, require_operator
from modules.observability.domain.deeplinks import (
    DEFAULT_GRAFANA_WINDOW,
    MAX_KEY_LENGTH,
    MAX_TRACE_ID_LENGTH,
)
from modules.observability.domain.exceptions import (
    AlertAlreadyResolvedError,
    AlertNotFoundError,
)
from modules.observability.facade import (
    BUSINESS_PERIOD_MONTH,
    DEFAULT_ACTIVITY_WINDOW_MINUTES,
    DEFAULT_ALERT_PAGE_SIZE,
    DEFAULT_ERROR_PAGE_SIZE,
    DEFAULT_ERROR_WINDOW_MINUTES,
    DEFAULT_THROUGHPUT_WINDOW_MINUTES,
    DEFAULT_WINDOW_DAYS,
    MAX_ACTIVITY_WINDOW_MINUTES,
    MAX_ALERT_PAGE_SIZE,
    MAX_ERROR_PAGE_SIZE,
    MAX_ERROR_WINDOW_MINUTES,
    MAX_THROUGHPUT_WINDOW_MINUTES,
    RETENTION_DEFAULT_COHORT_DAYS,
    ActiveUsersRead,
    AlertAcknowledgement,
    AlertPage,
    BusinessRead,
    CostSummary,
    CostTrend,
    Deeplinks,
    ErrorFeedPage,
    EvaluationDatasetActivateResponse,
    EvaluationDatasetCloneRequest,
    EvaluationDatasetCreateRequest,
    EvaluationDatasetEditRequest,
    EvaluationDatasetListResponse,
    EvaluationDatasetSeedRequest,
    EvaluationDatasetVersion,
    EvaluationDatasetVersionDetail,
    FunnelRead,
    LatencyReport,
    ObservabilityFacade,
    Overview,
    ProviderBoardReport,
    QualityReport,
    ReliabilityReport,
    RetentionCohortsRead,
    SecuritySummary,
    SystemHealth,
    ThroughputReport,
    UsageReport,
)

router = APIRouter(tags=["observability"])

#: Ceiling of the windowed reads' ``days`` param: one year of daily points, which is
#: as much series as the chart behind these reads draws. It bounds the response, not
#: the system, so it is a module constant rather than an env-driven limit.
_MAX_WINDOW_DAYS = 365

_Window = Annotated[int, Query(ge=1, le=_MAX_WINDOW_DAYS)]

#: The ``/throughput`` window, in minutes against the counter's own grain. It
#: carries its own ceiling rather than borrowing ``_MAX_WINDOW_DAYS`` because the
#: two are not the same shape: a day of MINUTE rows is a thousand series to
#: aggregate, where a day of daily rows is thirty. Like ``_MAX_WINDOW_DAYS`` it is a
#: constant rather than an env-driven limit, because it bounds the RESPONSE rather
#: than the system.
_MinuteWindow = Annotated[int, Query(ge=1, le=MAX_THROUGHPUT_WINDOW_MINUTES)]

#: The ``/reliability`` recent-ACTIVITY window, in minutes against the consumed-event
#: ledger's own ``processed_at`` grain. It carries its own ceiling for the same reason
#: ``_MinuteWindow`` does: it bounds the RESPONSE, so it is a module constant rather
#: than an env-driven limit - and the queue figures on that read are a now-reading
#: that this window deliberately does not apply to.
_ActivityWindow = Annotated[int, Query(ge=1, le=MAX_ACTIVITY_WINDOW_MINUTES)]

#: The ``/errors`` recency window, in minutes against ``last_seen_at``. It decides
#: what reads as ``open``, so it carries its own ceiling for the reason
#: :data:`_MinuteWindow` does: it bounds the RESPONSE, which makes it a module
#: constant rather than an env-driven limit.
_ErrorWindow = Annotated[int, Query(ge=1, le=MAX_ERROR_WINDOW_MINUTES)]

#: The alert statuses ``observability_alert_events.status`` can hold. Spelled as a
#: ``Literal`` rather than imported from the domain so FastAPI can render the
#: accepted values into the OpenAPI schema and refuse a typo at the edge: a
#: misspelled status that 200'd with an empty feed would read as "nothing is wrong".
#:
#: The whole vocabulary now (#735), because an operator acknowledgement can move an
#: alert into the third of the three statuses and the open list an operator works is
#: exactly the one that shrinks when they do.
_AlertStatus = Annotated[Literal["open", "acknowledged", "resolved"] | None, Query(alias="status")]

#: The statuses ``/errors`` accepts, same reasoning as :data:`_AlertStatus` and the
#: same words - an operator moving between the alert feed and the error feed should
#: not have to learn two vocabularies.
#:
#: Spelled as a static ``Literal`` because that is what puts the accepted values into
#: the OpenAPI schema and makes FastAPI refuse a typo at the edge, which is why this
#: cannot simply be derived from
#: :data:`~modules.observability.facade.ERROR_STATUS_VOCABULARY`. A test asserts the
#: two agree so the duplication cannot drift.
#:
#: Deliberately NOT the whole alert set even after #735: acknowledgement is an action
#: against ``observability_alert_events`` and no writer can acknowledge a CAPTURED
#: error, so accepting ``acknowledged`` here would offer a filter that can only ever
#: return nothing.
_ErrorStatus = Annotated[Literal["open", "resolved"] | None, Query(alias="status")]

#: The AI task types ``/deeplinks`` accepts for its Langfuse view. Spelled as a
#: static ``Literal`` for the reason :data:`_ErrorStatus` is - FastAPI renders the
#: accepted values into OpenAPI and refuses a typo at the edge. A misspelled task
#: would otherwise 200 with a Langfuse link filtered by a span nobody records, which
#: is a link that opens an empty list and looks like "no AI activity".
#:
#: The same ``Literal`` the intake module declares as ``AiTaskType``
#: (``modules.intake.domain.events``); a test asserts the two agree so the
#: duplication cannot drift.
_DeeplinkTaskType = Annotated[
    Literal["transcribe", "structure", "draft", "summarize"] | None, Query()
]

#: The identifiers ``/deeplinks`` will put in a link. Each is capped at the width of
#: the column the platform stores it in - ``trace_id VARCHAR(64)`` on every
#: observability table, and ``actor_key`` / ``session_key VARCHAR(64)`` on the
#: product-event ledger - so an over-long value is a 422 at the edge rather than a
#: link built from something the platform could never have written. The narrower rule
#: (no spaces, no separators) is :func:`clean_trace_id`, which drops the value rather
#: than escaping it into a vendor's query grammar.
_LinkTraceId = Annotated[str | None, Query(max_length=MAX_TRACE_ID_LENGTH)]
_LinkActorKey = Annotated[str | None, Query(max_length=MAX_KEY_LENGTH)]
_LinkSessionKey = Annotated[str | None, Query(max_length=MAX_KEY_LENGTH)]
_LinkFilter = Annotated[str | None, Query(max_length=MAX_KEY_LENGTH)]

#: The periods ``/business`` accepts. Spelled as a static ``Literal`` for the reason
#: :data:`_ErrorStatus` is: FastAPI renders the accepted values into OpenAPI and
#: refuses a typo at the edge, where a hand-rolled check would 422 with no schema and
#: a permissive one would answer 200 with a DIFFERENT period's numbers - which is the
#: worse failure here, because an operator reads a whole month's spend as a day's.
#: The values are the facade's own
#: :data:`~modules.observability.facade.BUSINESS_PERIODS` constants, and
#: ``test_the_business_period_gate_matches_the_facade_vocabulary`` asserts the two agree.
_BusinessPeriod = Annotated[Literal["today", "week_to_date", "month_to_date"], Query()]

#: The outcomes ``/product/funnel`` accepts, spelled as a static ``Literal`` for the
#: reason :data:`_ErrorStatus` is - FastAPI renders the accepted values into the
#: OpenAPI schema and refuses a typo at the edge. A misspelled outcome would otherwise
#: 200 with an empty funnel, which reads as "nobody is being abandoned" rather than as
#: a bad query. The values are the registry's own ``PRODUCT_OUTCOMES`` in closed
#: order, and ``test_the_funnel_outcome_gate_matches_the_registry_vocabulary``
#: asserts the two agree so the duplication cannot drift.
_FunnelOutcome = Annotated[
    Literal["completed", "abandoned", "errored", "re_recorded"] | None, Query()
]

_Page = Annotated[int, Query(ge=1)]
_PageSize = Annotated[int, Query(ge=1, le=MAX_ALERT_PAGE_SIZE)]
_ErrorPageSize = Annotated[int, Query(ge=1, le=MAX_ERROR_PAGE_SIZE)]


def _facade(request: Request) -> ObservabilityFacade:
    """The one resolved read facade ``app.main`` bound to state (composition root)."""
    return cast(ObservabilityFacade, request.app.state.observability_facade)


def _settings(request: Request) -> Settings:
    """The resolved Settings ``app.main`` bound to state, for the env-gated reads."""
    return cast(Settings, request.app.state.settings)


@router.get(
    "/v1/operator/observability/cost",
    response_model=CostSummary,
    status_code=status.HTTP_200_OK,
    summary="Read AI spend against the current period's budget (operator only)",
)
async def read_cost(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
) -> CostSummary:
    """Spend vs budget for the billing period the rollup last snapshotted.

    No window param: the current billing period is the only period an operator
    budgets against, and the rows already carry their own period bounds.
    """
    del principal
    return await _facade(request).get_cost_summary()


@router.get(
    "/v1/operator/observability/business",
    response_model=BusinessRead,
    status_code=status.HTTP_200_OK,
    summary="Read period AI spend, unit metrics, attribution and margin (operator only)",
)
async def read_business(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    period: _BusinessPeriod = BUSINESS_PERIOD_MONTH,
) -> BusinessRead:
    """Spend for a period, against the monthly cap, with a projected month-end burn.

    One endpoint for all three periods. ``period`` selects the window -
    ``today``, ``week_to_date`` or ``month_to_date`` - rather than three handlers over
    three copies of the same aggregation existing to choose between them (#717
    decision 11). All three windows end today and differ only in where they start, so
    the parameter is a start date, not a different question.

    The default is ``month_to_date`` because the cap it is reported against is a
    MONTHLY cap: a panel opened without a period is asking "how is this month
    going", and answering with today's rupee figure would compare one day against a
    month-long budget.

    The cap figures ride every period, not just the monthly one. That is what makes
    "is this spend healthy" answerable at a glance - ``projected_month_end_paise`` and
    ``projected_over_cap`` say where the month lands if the days so far are
    representative - and it is why an operator hears about the cap on the twentieth
    rather than on the last.

    What one unit of value costs rides the same response: ``cost_per_request_paise``,
    ``cost_per_completed_task_paise``, ``cost_per_patient_paise``,
    ``cost_per_doctor_paise`` and ``cost_of_pass_paise`` are read-time divisions over
    the same counters (#732, decision 8), and every one of them is ``null`` rather than
    zero when its denominator is empty. The heavy actors come with them -
    ``top_patients`` and ``top_doctors``, each beside the median, ninety-fifth
    percentile and maximum over the WHOLE population, so one outlier cannot be read as
    the average - and ``margin`` reports ``null`` with a machine-readable reason until
    revenue is captured, never a zero a finance lead could quote.
    """
    del principal
    return await _facade(request).get_business(period=period)


@router.get(
    "/v1/operator/observability/cost/trend",
    response_model=CostTrend,
    status_code=status.HTTP_200_OK,
    summary="Read the daily AI cost trend (operator only)",
)
async def read_cost_trend(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    days: _Window = DEFAULT_WINDOW_DAYS,
) -> CostTrend:
    """Daily cost across the window, oldest day first, defaulting to 30 days.

    ``days`` counts the days themselves, so the default covers today and the 29
    days before it. An out-of-range value is refused at the edge (422) before any
    query runs.
    """
    del principal
    return await _facade(request).get_cost_trend(days=days)


@router.get(
    "/v1/operator/observability/usage",
    response_model=UsageReport,
    status_code=status.HTTP_200_OK,
    summary="Read AI calls and tokens by provider and task (operator only)",
)
async def read_usage(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    days: _Window = DEFAULT_WINDOW_DAYS,
) -> UsageReport:
    """Calls, tokens, and paise per ``(provider, model, task_type)`` scope.

    The same 30-day default window as the cost trend: usage and spend are read
    together on the dashboard, so they are windowed identically.
    """
    del principal
    return await _facade(request).get_usage(days=days)


@router.get(
    "/v1/operator/observability/quality",
    response_model=QualityReport,
    status_code=status.HTTP_200_OK,
    summary="Read AI output quality and provider health (operator only)",
)
async def read_quality(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    days: _Window = DEFAULT_WINDOW_DAYS,
) -> QualityReport:
    """Success and low-confidence rates over the window, plus per-provider health.

    Windowed like its sibling reads so an operator can line the quality rates up
    against the spend they explain.
    """
    del principal
    return await _facade(request).get_quality(days=days)


# --------------------------------------------------------- C1b (#707) reads


@router.get(
    "/v1/operator/observability/overview",
    response_model=Overview,
    status_code=status.HTTP_200_OK,
    summary="Read the operator observability headline KPIs (operator only)",
)
async def read_overview(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    days: _Window = DEFAULT_WINDOW_DAYS,
) -> Overview:
    """The one-number-per-question tile row the operator page opens with.

    Windowed like the reads whose figures it republishes, so a KPI on the overview
    and the same figure on ``/usage`` or ``/quality`` always cover the same days.
    Spend and the alert counts are not windowed - a budget is a billing-period
    figure and an alert stays open until a pass resolves it - and the response
    says so by carrying ``period``-independent ``last_rolled_date`` for freshness.
    """
    del principal
    return await _facade(request).get_overview(days=days)


@router.get(
    "/v1/operator/observability/latency",
    response_model=LatencyReport,
    status_code=status.HTTP_200_OK,
    summary="Read AI provider latency percentiles (operator only)",
)
async def read_latency(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
) -> LatencyReport:
    """Per-provider p50/p95/p99 as the nightly rollup last ranked them.

    No ``days`` param: the percentiles are the rollup's rolling snapshot, so a
    window here would describe a period they were never computed over. The
    response carries ``last_rolled_date`` and each provider's ranked window
    instead, which is the honest answer to "how fresh is this?".
    """
    del principal
    return await _facade(request).get_latency()


@router.get(
    "/v1/operator/observability/providers",
    response_model=ProviderBoardReport,
    status_code=status.HTTP_200_OK,
    summary="Read the per-provider degraded status board (operator only)",
)
async def read_providers(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
) -> ProviderBoardReport:
    """Every rolled upstream model API, with whether it is healthy, degraded or down.

    The board's whole purpose is telling a CareSetu bug from an upstream outage, so
    each row carries the numbers that separate them: the quota refusals, the
    timeouts, the success rate, the three percentiles, the breaker state and the
    newest failure's reason. ``status`` is derived from those at read time, which
    is why there is no stored column to drift.

    No ``days`` param, for the same reason as ``/latency``: every field is the
    nightly rollup's snapshot of one window, so a window here would describe a
    period the numbers were never computed over. ``last_rolled_date`` and each
    row's own bounds are how fresh the board is.

    A separate route rather than a wider ``/quality``: that read's per-provider
    list exists to give the quality panel its context, and folding an operational
    verdict into it would either make every existing consumer carry a status it
    has no use for or split the shape across two reads of the same table.
    """
    del principal
    return await _facade(request).get_provider_board()


@router.get(
    "/v1/operator/observability/throughput",
    response_model=ThroughputReport,
    status_code=status.HTTP_200_OK,
    summary="Read request throughput, error rate and capture liveness (operator only)",
)
async def read_throughput(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    minutes: _MinuteWindow = DEFAULT_THROUGHPUT_WINDOW_MINUTES,
) -> ThroughputReport:
    """Requests served and the server-error rate over the recent past.

    ``minutes`` rather than ``days``: the counter's grain is a minute, so the read
    asks for the same span the data is stored at and a day would answer a question
    about an hour. The window is bounded in the query parameter itself
    (:data:`MAX_THROUGHPUT_WINDOW_MINUTES`), so an over-wide request is refused at
    the edge rather than turning the panel into a table scan.

    The response carries ``capture`` because the alternative is the failure this
    read exists to prevent: an empty feed of errors, indistinguishable from a
    healthy system unless the read says whether any request was recorded at all.
    """
    del principal
    return await _facade(request).get_throughput(minutes=minutes)


@router.get(
    "/v1/operator/observability/health",
    response_model=SystemHealth,
    status_code=status.HTTP_200_OK,
    summary="Read dependency, outbox and circuit-breaker health (operator only)",
)
async def read_health(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
) -> SystemHealth:
    """Whether the stores answered, what is queued, and what has terminally failed.

    No ``days`` param and no window: health is a now-reading. An unconfigured cache
    reports ``disabled`` rather than ``down`` - the plan's Redis is optional with a
    SQL fallback, so its absence is a configuration choice, not an outage.
    """
    del principal
    settings = _settings(request)
    return await _facade(request).get_health(cache_configured=bool(settings.redis_url.strip()))


@router.get(
    "/v1/operator/observability/security",
    response_model=SecuritySummary,
    status_code=status.HTTP_200_OK,
    summary="Read the operator security posture summary (operator only)",
)
async def read_security(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
) -> SecuritySummary:
    """Security posture summary: auth/lockout trends, consent/rate-limit anomalies,
    CSP violations, prompt-injection counts, and webhook monitoring status.

    PHASE-14B Batch 2 (#781): webhook-signature monitoring is deferred and shows
    a deferred status rather than live data.
    """
    del principal
    settings = _settings(request)
    return await _facade(request).get_security_summary(
        window_minutes=settings.security_summary_window_minutes, settings=settings
    )


@router.get(
    "/v1/operator/observability/reliability",
    response_model=ReliabilityReport,
    status_code=status.HTTP_200_OK,
    summary="Read queue depth and age, per-outbox backlog and recent activity (operator only)",
)
async def read_reliability(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    minutes: _ActivityWindow = DEFAULT_ACTIVITY_WINDOW_MINUTES,
) -> ReliabilityReport:
    """How much work is waiting, how old the oldest is, and who was here recently.

    B5 (#729). Three answers on one surface because they are read together: the AI
    queues with their depth and oldest-item age, the per-module outbox breakdown
    with the dead-letter total, and the RECENT-ACTIVITY figure.

    The field is ``recent_active_actors``, and the distinction is the point: it is
    how many distinct people were here in the last ``minutes``, never how many are
    here now. Simultaneous concurrency is a live signal in the tracing backend, so
    this read hands back ``concurrency_grafana_link`` instead of a number that
    would be stale the moment it was computed (#717 decision 17).

    ``minutes`` applies to the activity figure only, and is bounded in the query
    parameter itself (:data:`MAX_ACTIVITY_WINDOW_MINUTES`): the queue figures are a
    now-reading, because a queue has no window.
    """
    del principal
    settings = _settings(request)
    return await _facade(request).get_reliability(minutes=minutes, grafana_url=settings.grafana_url)


@router.get(
    "/v1/operator/observability/alerts",
    response_model=AlertPage,
    status_code=status.HTTP_200_OK,
    summary="Read the observability alert feed (operator only)",
)
async def read_alerts(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    page: _Page = 1,
    page_size: _PageSize = DEFAULT_ALERT_PAGE_SIZE,
    alert_status: _AlertStatus = None,
) -> AlertPage:
    """One page of ``observability_alert_events``, newest first, PHI-free fields only.

    Paged as api-standards §4 asks - ``page``/``page_size`` (default 25, max 100)
    with ``total_count`` over the whole filter, so a client can page back through
    a long feed. Unfiltered it is the standing-problems view; ``status`` narrows
    it to what is still open, to what an operator has acknowledged, or to what a
    later pass resolved - which is what lets an operator work the open list while
    the answered ones stay one filter away. An unrecognised status is a 422 at the
    edge, never a silently empty feed.
    """
    del principal
    return await _facade(request).get_alerts(page=page, page_size=page_size, status=alert_status)


@router.post(
    "/v1/operator/observability/alerts/{alert_id}/acknowledge",
    response_model=AlertAcknowledgement,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge an alert (operator only)",
)
async def acknowledge_alert(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    alert_id: UUID,
) -> AlertAcknowledgement:
    """Take ownership of one alert: name the operator, stamp the time, close the status.

    The write that fills the ``acked_by`` / ``acked_at`` columns which have been on
    the row since the first observability migration and which nothing ever wrote. A
    verb under the domain rather than a PATCH on the collection (api-standards §1),
    because acknowledging is an action, not a field edit - and because the route is
    then impossible to call with a body that sets ``status`` to anything else.

    **Idempotent, and the FIRST acknowledgement stands.** A repeat is a 200 carrying
    the standing row with ``already_acknowledged: true`` - not a 409, because refusing
    a double-click would teach an operator that acknowledging is a once-only privilege
    and would make them hesitate to press it. The flag is what keeps the 200 honest:
    it says the claim on the row is not this call's.

    Accepts ``Idempotency-Key`` (api-standards §5), so a retry on a network failure
    replays the stored response instead of re-attributing anything.

    A resolved alert is refused rather than acknowledged: it is closed, and moving it
    to ``acknowledged`` would re-open a problem a later pass had already established
    as cleared. An unknown alert is a 404, because an operator who pressed the button
    on a row that is gone needs to be told that.
    """
    return await run_idempotent(
        request,
        lambda: _facade(request).acknowledge_alert(
            alert_id=alert_id,
            # An identity reference, not a display name - the same shape every other
            # ``*_by`` column in the platform records "who did this" with.
            acked_by=int(principal.subject_id),
        ),
        namespace=f"identity:{principal.subject_id}",
    )


@router.get(
    "/v1/operator/observability/errors",
    response_model=ErrorFeedPage,
    status_code=status.HTTP_200_OK,
    summary="Read the live collapsed error feed (operator only)",
)
async def read_errors(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    page: _Page = 1,
    page_size: _ErrorPageSize = DEFAULT_ERROR_PAGE_SIZE,
    error_status: _ErrorStatus = None,
    minutes: _ErrorWindow = DEFAULT_ERROR_WINDOW_MINUTES,
) -> ErrorFeedPage:
    """One page of captured server errors, most recently seen first, PHI-free.

    Paged as api-standards §4 asks - ``page``/``page_size`` (default 25, max 100)
    - over a feed that is already collapsed: one entry per DISTINCT failure, with
    ``occurrences`` saying how many times it happened. The response carries both
    counts (``total_count`` over ``total_occurrences``) because "four hundred
    failures" and "one failure, four hundred times" are different pages and a client
    labelling it has to know which it is looking at.

    Every entry names the ROUTE TEMPLATE, the method, the status code and the trace
    identifier - never a concrete request path - so the feed can be rendered with no
    identifier in it, and one click reaches the trace.

    ``status`` narrows to ``open`` or ``resolved``. Neither is stored: a captured
    error has no lifecycle and nothing marks one handled, so a status column could
    only ever hold its insert default. The read derives both from ``last_seen_at``
    against ``minutes``, which is therefore the read's whole notion of "live" and is
    why it is a parameter and not a constant.

    The response carries no capture-liveness block. An empty page is ambiguous - "no
    errors" and "nothing was watched" look identical - and ``/throughput``'s
    ``capture`` is what says which; answering it here too would make two places to
    keep honest for one verdict.
    """
    del principal
    return await _facade(request).get_error_feed(
        page=page, page_size=page_size, status=error_status, minutes=minutes
    )


@router.get(
    "/v1/operator/observability/product/funnel",
    response_model=FunnelRead,
    status_code=status.HTTP_200_OK,
    summary="Read the intake funnel, step by step, with its outcomes and gaps (operator only)",
)
async def read_product_funnel(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    days: _Window = DEFAULT_WINDOW_DAYS,
    outcome: _FunnelOutcome = None,
) -> FunnelRead:
    """Is the product working? - the funnel from the moment a patient opened the composer.

    One response carries the four things that only mean anything together: how many
    arrived at each step, how they left it (``completed``, ``abandoned``, ``errored``,
    and ``re_recorded`` for a corrected attempt), how long they thought between this
    step and the last, and whether the workflow ended in an issued e-prescription or a
    closed case. A workflow that dies silently at transcription and one that runs to a
    completed prescription stop looking identical without this.

    **Success rate and abandonment rate ride one block.** They are two halves of the
    same verdict over the same ``started``, and a client that can be handed either one
    without the other will eventually quote it alone.

    ``outcome`` narrows the STEPS to those whose declared vocabulary holds that
    outcome - so ``outcome=abandoned`` is the abandoned path on its own - and narrows
    each reported step's counts to that outcome too, so nothing else is on the row to
    quote instead. It deliberately does not narrow the headline rates: those are the
    window's verdict, and narrowing one of them to a single outcome would leave two
    rates measured over two different populations.

    A step's conversion is over the nearest preceding NON-TERMINAL step, which is why
    both ``prescription_approved`` and ``case_closed`` count as successes from
    ``prescription_drafted``: a case closed without a prescription is a completed
    consultation, not a drop-off. The conventions behind the conversion, the rates and
    the gap are carried in the response (``denominator_convention``,
    ``rate_convention``, ``gap_convention``) rather than promised here, because a client
    rendering the numbers has to be able to say what they mean.

    The median gap is ``null`` - with ``gap_basis`` saying ``unavailable`` - for the
    handoff from the patient's intake into the doctor's consult, because those two
    steps share no key the ledger stores today, and ``no_predecessor`` on the entry
    step, which has nothing before it to measure from. Both are reported as unmeasured
    rather than as zero seconds.
    """
    del principal
    return await _facade(request).get_funnel(days=days, outcome=outcome)


@router.get(
    "/v1/operator/observability/product/active-users",
    response_model=ActiveUsersRead,
    status_code=status.HTTP_200_OK,
    summary="Read daily, weekly and monthly active users with stickiness and load per head",
)
async def read_active_users(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    days: _Window = DEFAULT_WINDOW_DAYS,
) -> ActiveUsersRead:
    """Is adoption growing? - DAU, WAU, MAU, the stickiness between them and the load.

    One response carries the five figures that only mean anything read together: how
    many people were here today, how many came back inside the week and the month,
    how the daily habit holds against the monthly base, and how much of the platform's
    throughput each of those people accounts for.

    **The three counts are three different actor SETS, never multiples of one
    another.** A person active on three days of the week is one weekly user, and a
    read that multiplied today's figure by thirty would report a product that grew
    because its arithmetic did.

    **They are counted in Postgres, in the system of record, over a rolling window
    ending today.** The free metrics tier keeps fourteen days, so a monthly figure is
    not a question the vendor can answer - the data is gone before it is asked - and
    the number this route returns is deliberately NOT truncated to whatever the
    vendor still holds.

    ``days`` governs the throughput figures and the trend, not the three headline
    counts: those keep their own one-, seven- and thirty-day windows, because a
    ``days=7`` request answered with a "monthly" figure of seven days would be the
    exact truncation this read exists to prevent. ``window_active_users`` is the one
    count that follows ``days`` - it is the denominator of ``requests_per_active_user``,
    so both sides of that division span the same days.

    The four conventions the figures rest on - which window, which events, how
    stickiness is defined and what the per-user figure divides - ride the response
    rather than living only in this docstring, because a client rendering the numbers
    has to be able to say what they mean.
    """
    del principal
    return await _facade(request).get_active_users(days=days)


@router.get(
    "/v1/operator/observability/product/retention-cohorts",
    response_model=RetentionCohortsRead,
    status_code=status.HTTP_200_OK,
    summary="Read seven- and thirty-day retention for each arrival day",
)
async def read_retention_cohorts(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    days: _Window = RETENTION_DEFAULT_COHORT_DAYS,
) -> RetentionCohortsRead:
    """Does adoption stick? - the share of each arrival day that came back later.

    ``/product/active-users`` answers "is adoption growing". This answers the question
    that one cannot: a product can add a thousand people a week and lose every one of
    them inside a fortnight, and the rolling windows are computed from the same
    arrivals, so that churn and that acquisition cancel out of a DAU/MAU pair.

    **A cohort is a GROUP, not a window.** Everyone who arrived on one date is held
    together and asked what became of them, so a falling figure here means the product
    lost people rather than that it stopped acquiring them at a convenient moment.

    **Served from the daily aggregate, and the raw ledger is never scanned for it.**
    The response is derived at read time from the nightly per-actor day aggregate
    MOD-013 writes from the product event ledger, so a thirty-day question costs thirty
    days of aggregate rows and the numbers outlive the free metrics tier's fourteen-day
    retention - the system of record holds them, the vendor no longer does.

    ``days`` counts ARRIVAL DATES, ending today, and deliberately does NOT shorten
    either horizon: a ``days=7`` request still measures day-30 retention for each of
    its seven dates. Truncating the horizon to the requested window is the exact
    truncation this read exists to prevent. Its default is 60 dates rather than the
    other reads' 30, because the newest cohort that can be measured at thirty days is
    itself thirty days old - a 30-date default would return a thirty-day column that is
    null on every row.

    A cohort too young to have reached a horizon reports ``null`` there, never zero -
    a horizon nobody has lived through yet is not the same as one that arrived and
    nobody came back to, and only the first of those is a fact about the product.
    """
    del principal
    return await _facade(request).get_retention_cohorts(days=days)


@router.get(
    "/v1/operator/observability/deeplinks",
    response_model=Deeplinks,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    summary="Read the configured vendor deep links (operator only)",
)
async def read_deeplinks(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    trace_id: _LinkTraceId = None,
    actor_key: _LinkActorKey = None,
    session_key: _LinkSessionKey = None,
    model: _LinkFilter = None,
    task_type: _DeeplinkTaskType = None,
    error_type: _LinkFilter = None,
    window: Annotated[str, Query(max_length=MAX_KEY_LENGTH)] = DEFAULT_GRAFANA_WINDOW,
) -> Deeplinks:
    """Grafana / Sentry / Langfuse link SETS derived from the deployment's Settings.

    Vendor-gated and no-op when unconfigured (plan-phase14 A§4): each vendor is
    derived independently and an unconfigured one is **absent from the JSON
    entirely** - ``response_model_exclude_none`` drops the key rather than answering
    ``null`` - so a deployment with none of the three still answers 200 and a client
    never has to tell "switched off" from "broken".

    #736 widened the three bare URLs into parameterised link sets (decision 44: a wire
    change, and the frontend client contract moves with it). Every query param is
    CONTEXT for the links and every one is optional: the read is still a projection of
    configuration, so a panel that knows nothing extra still gets the dashboard and
    the service-filtered issue list, while a panel holding a trace, a model, an actor
    or a session gets those views too - each carrying the platform's own stored
    identifier, never one reconstructed here.
    """
    del principal
    settings = _settings(request)
    return _facade(request).get_deeplinks(
        grafana_url=settings.grafana_url,
        sentry_dsn=settings.sentry_dsn,
        langfuse_host=settings.langfuse_host,
        langfuse_public_key=settings.langfuse_public_key,
        environment=settings.app_environment,
        window=window,
        trace_id=trace_id,
        actor_key=actor_key,
        session_key=session_key,
        model=model,
        task_type=task_type,
        error_type=error_type,
    )


# --------------------------------------------------------- evaluation dataset API (#787)
#
# Admin-only routes for managing versioned evaluation datasets. The golden dataset
# is seeded as the initial active version; admins can create draft versions, clone
# existing ones, edit drafts, and activate a version (which retires the previous
# active version). Active versions are immutable - edits are refused.


@router.post(
    "/v1/operator/observability/evaluation/datasets/seed",
    response_model=EvaluationDatasetVersion,
    status_code=status.HTTP_200_OK,
    summary="Seed the active evaluation dataset from the golden dataset (admin only)",
)
async def seed_evaluation_dataset(
    request: Request,
    body: EvaluationDatasetSeedRequest,
    principal: Annotated[Principal, Depends(require_admin)],
) -> EvaluationDatasetVersion:
    """Seed the active evaluation dataset version from the synthetic golden dataset (#751).

    Idempotent: if the named version already exists, returns it without changes.
    The golden dataset contains transcription and structuring examples that mirror
    the two AI legs the product PRD scores. Only admin-tier operators may call this.
    """
    del principal
    return await _facade(request).seed_evaluation_dataset(name=body.name, version=body.version)


@router.get(
    "/v1/operator/observability/evaluation/datasets",
    response_model=EvaluationDatasetListResponse,
    status_code=status.HTTP_200_OK,
    summary="List evaluation dataset versions (admin only)",
)
async def list_evaluation_dataset_versions(
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    name: str | None = None,
) -> EvaluationDatasetListResponse:
    """List all evaluation dataset versions, optionally filtered by dataset name.

    Only admin-tier operators may call this.
    """
    del principal
    return await _facade(request).list_evaluation_dataset_versions(name=name)


@router.get(
    "/v1/operator/observability/evaluation/datasets/{name}/{version}",
    response_model=EvaluationDatasetVersionDetail,
    status_code=status.HTTP_200_OK,
    summary="Get a specific evaluation dataset version with examples (admin only)",
)
async def get_evaluation_dataset_version(
    request: Request,
    name: str,
    version: int,
    principal: Annotated[Principal, Depends(require_admin)],
) -> EvaluationDatasetVersionDetail:
    """Get a specific dataset version with its examples.

    Only admin-tier operators may call this. Returns 404 if the version does not exist.
    """
    del principal
    facade = _facade(request)
    result = await facade.get_evaluation_dataset_version(name=name, version=version)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "EVALUATION_DATASET_NOT_FOUND",
                "message": f"Dataset version {name} v{version} not found",
                "trace_id": request.state.trace_id if hasattr(request.state, "trace_id") else None,
            },
        )
    return result


@router.post(
    "/v1/operator/observability/evaluation/datasets",
    response_model=EvaluationDatasetVersion,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new draft evaluation dataset version (admin only)",
)
async def create_evaluation_dataset_draft(
    request: Request,
    body: EvaluationDatasetCreateRequest,
    principal: Annotated[Principal, Depends(require_admin)],
) -> EvaluationDatasetVersion:
    """Create a new draft evaluation dataset version.

    Only admin-tier operators may call this. The version must not already exist.
    """
    del principal
    facade = _facade(request)
    try:
        return await facade.create_evaluation_dataset_draft(
            name=body.name, version=body.version, examples=body.examples
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EVALUATION_DATASET_CREATE_FAILED",
                "message": str(e),
                "trace_id": request.state.trace_id if hasattr(request.state, "trace_id") else None,
            },
        ) from e


@router.post(
    "/v1/operator/observability/evaluation/datasets/{name}/{version}/clone",
    response_model=EvaluationDatasetVersion,
    status_code=status.HTTP_201_CREATED,
    summary="Clone an existing dataset version as a new draft (admin only)",
)
async def clone_evaluation_dataset(
    request: Request,
    name: str,
    version: int,
    body: EvaluationDatasetCloneRequest,
    principal: Annotated[Principal, Depends(require_admin)],
) -> EvaluationDatasetVersion:
    """Clone an existing dataset version as a new draft.

    Only admin-tier operators may call this. The source dataset is copied entirely
    to the new version with 'draft' status. The new version must not already exist.
    """
    del principal
    facade = _facade(request)
    try:
        return await facade.clone_evaluation_dataset(
            name=name, version=version, source_dataset_id=body.source_dataset_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EVALUATION_DATASET_CLONE_FAILED",
                "message": str(e),
                "trace_id": request.state.trace_id if hasattr(request.state, "trace_id") else None,
            },
        ) from e


@router.patch(
    "/v1/operator/observability/evaluation/datasets/{name}/{version}",
    response_model=EvaluationDatasetVersion,
    status_code=status.HTTP_200_OK,
    summary="Edit a draft evaluation dataset version's examples (admin only)",
)
async def edit_evaluation_dataset_draft(
    request: Request,
    name: str,
    version: int,
    body: EvaluationDatasetEditRequest,
    principal: Annotated[Principal, Depends(require_admin)],
) -> EvaluationDatasetVersion:
    """Edit a draft evaluation dataset version's examples.

    Only admin-tier operators may call this. Refuses if the version is not in 'draft'
    status (active/retired versions are immutable).
    """
    del principal
    facade = _facade(request)
    try:
        return await facade.edit_evaluation_dataset_draft(
            name=name, version=version, examples=body.examples
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EVALUATION_DATASET_EDIT_FAILED",
                "message": str(e),
                "trace_id": request.state.trace_id if hasattr(request.state, "trace_id") else None,
            },
        ) from e


@router.post(
    "/v1/operator/observability/evaluation/datasets/{name}/{version}/activate",
    response_model=EvaluationDatasetActivateResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate a dataset version, retiring the previous active version (admin only)",
)
async def activate_evaluation_dataset_version(
    request: Request,
    name: str,
    version: int,
    principal: Annotated[Principal, Depends(require_admin)],
) -> EvaluationDatasetActivateResponse:
    """Activate a dataset version, retiring the previous active version.

    Only admin-tier operators may call this. Only draft versions can be activated.
    The previous active version (if any) is retired atomically.
    """
    del principal
    facade = _facade(request)
    try:
        return await facade.activate_evaluation_dataset_version(name=name, version=version)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EVALUATION_DATASET_ACTIVATE_FAILED",
                "message": str(e),
                "trace_id": request.state.trace_id if hasattr(request.state, "trace_id") else None,
            },
        ) from e


@router.post(
    "/v1/operator/observability/evaluation/datasets/{name}/{version}/retire",
    response_model=EvaluationDatasetVersion,
    status_code=status.HTTP_200_OK,
    summary="Retire a dataset version (admin only)",
)
async def retire_evaluation_dataset_version(
    request: Request,
    name: str,
    version: int,
    principal: Annotated[Principal, Depends(require_admin)],
) -> EvaluationDatasetVersion:
    """Retire a dataset version (draft or active).

    Only admin-tier operators may call this. Retiring an active version leaves no
    active version for that name. Already retired versions cannot be retired again.
    """
    del principal
    facade = _facade(request)
    try:
        return await facade.retire_evaluation_dataset_version(name=name, version=version)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EVALUATION_DATASET_RETIRE_FAILED",
                "message": str(e),
                "trace_id": request.state.trace_id if hasattr(request.state, "trace_id") else None,
            },
        ) from e


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-013 error envelope to every expected observability failure.

    Registered from ``app.main`` alongside the other modules'. Both handlers are
    about the ONE write (#735) - the reads have no expected failures of their own.

    ``ALERT_NOT_FOUND`` says the named alert row is gone; ``ALERT_ALREADY_RESOLVED``
    says the operator asked to acknowledge something a later pass had already
    closed. Both are prefixed by the alert RESOURCE rather than by ``MOD-013``,
    matching the sibling resources rather than the module codes (``CARE_NOT_FOUND``,
    ``CONSENT_NOT_FOUND``) - the alert feed is the only observability surface an
    operator names a resource on, so the resource is what disambiguates the code.
    Both are 4xx because both are outcomes of a call an operator made
    deliberately, not defects - and the second is a 409 rather than a 422, because
    the row's state is what refuses it, not the request's shape.
    """

    async def _alert_not_found(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_404_NOT_FOUND,
            "ALERT_NOT_FOUND",
            "No alert exists with that identifier",
            log_tag="observability_rejection",
            request=request,
        )

    async def _alert_already_resolved(request: Request, exc: Exception) -> JSONResponse:
        del exc
        # 409, not 422: the request was well formed, and what refuses it is the
        # ROW's state, not the payload's shape - a state conflict is what the rest
        # of the platform answers with 409 for. 422 is reserved for a request the
        # server could not understand (api-standards §3).
        return error_response(
            status.HTTP_409_CONFLICT,
            "ALERT_ALREADY_RESOLVED",
            "That alert is already resolved, so it cannot be acknowledged",
            log_tag="observability_rejection",
            request=request,
        )

    app.add_exception_handler(AlertNotFoundError, _alert_not_found)
    app.add_exception_handler(AlertAlreadyResolvedError, _alert_already_resolved)
