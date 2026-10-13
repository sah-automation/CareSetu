"""MOD-013: HTTP adapter for the operator observability read surfaces (PHASE-14A C1a, #706).

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

Scope: C1a serves ``cost``, ``cost/trend``, ``usage``, and ``quality``
(plan-phase14 §9.1). The remaining read routes of that table land with C1b.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, status

from app.gateway.principal import Principal
from app.gateway.rbac import require_operator
from modules.observability.facade import (
    DEFAULT_WINDOW_DAYS,
    CostSummary,
    CostTrend,
    ObservabilityFacade,
    QualityReport,
    UsageReport,
)

router = APIRouter(tags=["observability"])

#: Ceiling of the windowed reads' ``days`` param: one year of daily points, which is
#: as much series as the chart behind these reads draws. It bounds the response, not
#: the system, so it is a module constant rather than an env-driven limit.
_MAX_WINDOW_DAYS = 365

_Window = Annotated[int, Query(ge=1, le=_MAX_WINDOW_DAYS)]


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
    facade = cast(ObservabilityFacade, request.app.state.observability_facade)
    return await facade.get_cost_summary()


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
    facade = cast(ObservabilityFacade, request.app.state.observability_facade)
    return await facade.get_cost_trend(days=days)


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
    facade = cast(ObservabilityFacade, request.app.state.observability_facade)
    return await facade.get_usage(days=days)


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
    facade = cast(ObservabilityFacade, request.app.state.observability_facade)
    return await facade.get_quality(days=days)
