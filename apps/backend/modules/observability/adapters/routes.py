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
"""

from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse

from app.config import Settings
from app.gateway.errors import error_response
from app.gateway.idempotency import run_idempotent
from app.gateway.principal import Principal
from app.gateway.rbac import require_operator
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
    AlertAcknowledgement,
    AlertPage,
    BusinessRead,
    CostSummary,
    CostTrend,
    Deeplinks,
    ErrorFeedPage,
    LatencyReport,
    ObservabilityFacade,
    Overview,
    ProviderBoardReport,
    QualityReport,
    ReliabilityReport,
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
    deliberately, not defects.
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
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "ALERT_ALREADY_RESOLVED",
            "That alert is already resolved, so it cannot be acknowledged",
            log_tag="observability_rejection",
            request=request,
        )

    app.add_exception_handler(AlertNotFoundError, _alert_not_found)
    app.add_exception_handler(AlertAlreadyResolvedError, _alert_already_resolved)
