"""MOD-013: HTTP adapter for the operator observability read surfaces (PHASE-14A C1, #706/#707).

The endpoints are thin adapters (api-standards §1): resolve the gateway
``Principal``, validate the query params, call the observability read facade,
answer its typed view. They sit behind the gateway middleware stack in
``app.main``; every route declares ``require_operator`` (NFR-SEC-003,
api-standards §6), so an anonymous caller is refused 401 and any non-operator
scope 403 - both through the shared gateway error envelope, and both before the
facade is reached.

The reads raise no module-level domain exceptions (an un-budgeted month, a window
with no traffic, and an uncapped scope are all answers, not failures), so this
router needs no error handler of its own - RBAC rejections answer through the
gateway handlers and anything unexpected falls to the app catch-all.

Scope: the whole plan-phase14 §9.1 read table. C1a (#706) serves ``cost``,
``cost/trend``, ``usage`` and ``quality``; C1b (#707) adds ``overview``,
``latency``, ``health``, ``alerts`` and ``deeplinks``.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, status

from app.config import Settings
from app.gateway.principal import Principal
from app.gateway.rbac import require_operator
from modules.observability.facade import (
    DEFAULT_ALERT_FEED_LIMIT,
    DEFAULT_WINDOW_DAYS,
    MAX_ALERT_FEED_LIMIT,
    AlertFeed,
    CostSummary,
    CostTrend,
    Deeplinks,
    LatencyReport,
    ObservabilityFacade,
    Overview,
    QualityReport,
    SystemHealth,
    UsageReport,
)

router = APIRouter(tags=["observability"])

#: Ceiling of the windowed reads' ``days`` param: one year of daily points, which is
#: as much series as the chart behind these reads draws. It bounds the response, not
#: the system, so it is a module constant rather than an env-driven limit.
_MAX_WINDOW_DAYS = 365

_Window = Annotated[int, Query(ge=1, le=_MAX_WINDOW_DAYS)]

#: The alert statuses ``observability_alert_events.status`` can hold
#: (``domain/rollup.py``). Declared as a ``Literal`` so a typo is a 422 at the
#: edge rather than an empty feed that reads as "nothing is wrong".
_AlertStatus = Annotated[Literal["open", "resolved"] | None, Query(alias="status")]

_AlertLimit = Annotated[int, Query(ge=1, le=MAX_ALERT_FEED_LIMIT)]


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
    "/v1/operator/observability/alerts",
    response_model=AlertFeed,
    status_code=status.HTTP_200_OK,
    summary="Read the observability alert feed (operator only)",
)
async def read_alerts(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    limit: _AlertLimit = DEFAULT_ALERT_FEED_LIMIT,
    alert_status: _AlertStatus = None,
) -> AlertFeed:
    """The newest page of ``observability_alert_events``, PHI-free fields only.

    Unfiltered it is the standing-problems view; ``status`` narrows it to what is
    still open or to what a later pass resolved. An unrecognised status is a 422
    at the edge, never a silently empty feed.
    """
    del principal
    return await _facade(request).get_alerts(limit=limit, status=alert_status)


@router.get(
    "/v1/operator/observability/deeplinks",
    response_model=Deeplinks,
    status_code=status.HTTP_200_OK,
    summary="Read the configured vendor deep links (operator only)",
)
async def read_deeplinks(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
) -> Deeplinks:
    """Grafana / Sentry / Langfuse URLs derived from the deployment's Settings.

    Vendor-gated and no-op when unconfigured (plan-phase14 §4): each link is
    derived independently and an absent vendor leaves its key ``null`` rather than
    failing the read, so a deployment with none of the three still answers 200.
    """
    del principal
    settings = _settings(request)
    return _facade(request).get_deeplinks(
        grafana_url=settings.grafana_url,
        sentry_dsn=settings.sentry_dsn,
        langfuse_host=settings.langfuse_host,
        langfuse_public_key=settings.langfuse_public_key,
    )
