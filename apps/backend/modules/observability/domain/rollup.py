"""MOD-013: the nightly rollup's pure core - percentiles, health, budget, alerts.

B5a (#704, plan-phase14 §8). Everything in this module is a database-free
function over already-loaded values: the adapter layer
(``modules/observability/rollup.py``) reads rows and persists what these
decide, so every threshold and every percentile is unit-tested without a
database (``error-handling-observability.md`` §5, coding-standards §2).

Three pieces:

* the estimator (:func:`percentile`, :func:`weighted_percentile`) plus the
  provider-health recompute it feeds;
* the paise budget snapshot, which mirrors the ``BudgetMeter``'s
  observe-and-warn semantics (``modules/intake/budget_meter.py``, PS-10 #408) -
  the rollup SNAPSHOTS spend, it never enforces it;
* the ``metric_key -> computation`` registry (:data:`ROLLUP_REGISTRY`) whose
  results land in the generic ``observability_business_daily`` store
  (plan-phase14 §7.2), so a later phase adds a metric with one registry line and
  no schema churn;
* the schedule (B5b #705): :func:`plan_rollup_dates`, which turns the rollup's
  own persisted state into the dates one invocation covers.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from modules.observability.domain.consumer import (
    ALERT_SEVERITY_CRITICAL,
    ALERT_SEVERITY_WARNING,
    AlertRow,
)

#: ``observability_ai_provider_health.breaker_state`` vocabulary. ``half_open``
#: is deliberately absent: the rollup only observes, it never trips a breaker.
BREAKER_STATE_CLOSED = "closed"
BREAKER_STATE_OPEN = "open"

#: ``observability_alert_events.status`` vocabulary. ``open`` is the server
#: default every producer's insert inherits; ``resolved`` is written ONLY by this
#: rollup's resolve step. One definition for the two producers and the operator
#: alert feed that reads both.
ALERT_STATUS_OPEN = "open"
ALERT_STATUS_RESOLVED = "resolved"

#: Alert kinds this rollup owns. ``audit_tamper`` / ``ai_egress`` stay with the
#: B4b consumer (``domain/consumer.py``) - one kind vocabulary, two producers.
ALERT_KIND_AI_BUDGET = "ai_budget"
ALERT_KIND_PROVIDER_HEALTH_DROP = "provider_health_drop"
ALERT_KIND_BREAKER_OPEN = "breaker_open"
ALERT_KIND_OUTBOX_BACKLOG = "outbox_backlog"
ALERT_KIND_OUTBOX_DEAD_LETTER = "outbox_dead_letter"

#: The share of a budget that raises ``ai_budget`` (plan-phase14 §11, the
#: "AI budget meter > 80%" member of the minimum alert set).
DEFAULT_BUDGET_ALERT_THRESHOLD_PCT = 80

#: A provider whose observed success rate falls below this is recorded with an
#: open breaker and raises the critical ``breaker_open`` alert
#: (``error-handling-observability.md`` §5, "repeated third-party failures").
DEFAULT_BREAKER_OPEN_SUCCESS_RATE = Decimal("0.5")

#: How far the success rate must fall below the previously recorded value before
#: ``provider_health_drop`` fires (plan-phase14 §11).
DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD = Decimal("0.2")

#: Rows parked in ``pending``/``inflight`` across an outbox table before
#: ``outbox_backlog`` fires (plan-phase14 §11). Sized well above a normal
#: dispatch delay so a burst of freshly published events is not an alert.
DEFAULT_OUTBOX_BACKLOG_ALERT_THRESHOLD = 500

#: Rollup metric-key prefixes registered at import. The suffix appended to each
#: key is the scope the entry computes over (the provider today).
METRIC_KEY_AI_PROVIDER_HEALTH = "ai.provider_health"
METRIC_KEY_AI_SPEND = "ai.spend"

#: The ``payload.source`` marker every rollup alert carries. It is how a rollup
#: alert is told apart from a consumer alert (``audit_tamper`` / ``ai_egress``),
#: which no rollup pass may resolve.
_ALERT_SOURCE = "rollup"

#: The payload keys that scope an alert to one subject. Two rollup alerts sharing
#: a ``(kind, scope)`` are the same finding however many nights in a row it holds.
_ALERT_SCOPE_KEYS = ("provider", "model", "table", "scope")

#: The ``ai_budget`` alert's scope: the ONE monthly cap compared against TOTAL
#: spend, the same figure ``BudgetMeter.meter()`` reports. Not per provider/model -
#: a per-scope cap would make the effective budget the cap times the scope count.
_BUDGET_ALERT_SCOPE = "monthly_total"

#: Alert kinds describing a STANDING condition, which a later pass resolves once
#: the condition clears. ``provider_health_drop`` is deliberately absent: a drop
#: is a transition with no steady state (the health row holds one rate per
#: provider), so a pass raises it and leaves it for the operator's history rather
#: than closing an alert it raised for the same reading.
RESOLVABLE_ALERT_KINDS: frozenset[str] = frozenset(
    {
        ALERT_KIND_AI_BUDGET,
        ALERT_KIND_BREAKER_OPEN,
        ALERT_KIND_OUTBOX_BACKLOG,
        ALERT_KIND_OUTBOX_DEAD_LETTER,
    }
)

_RATE_QUANTUM = Decimal("0.0001")

#: How one invocation covered its dates. Recorded on ``observability_rollup_runs``
#: so an operator can tell the first-run backfill from the steady-state pass, and
#: the planner can branch on it without re-reading the whole ledger.
ROLLUP_MODE_BACKFILL = "backfill"
ROLLUP_MODE_DAILY = "daily"


# ------------------------------------------------------------------ estimator


def _value_at_rank(ordered: Sequence[tuple[float, int]], rank: int) -> float:
    """The observation value at zero-based ``rank`` of a weighted sorted sample."""
    cumulative = 0
    for value, weight in ordered:
        cumulative += weight
        if rank < cumulative:
            return value
    return ordered[-1][0]


def weighted_percentile(points: Sequence[tuple[float, int]], fraction: float) -> float | None:
    """The ``fraction`` percentile of a sample where each point carries a weight.

    A ``(value, weight)`` pair is ``weight`` repeated observations at ``value``,
    so this is exactly :func:`percentile` over the expansion, computed without
    building it. That is the shape the rollup has: B4a folds each job's duration
    into a running mean per ``(date, provider, model, task_type)`` scope, so a
    provider's latency distribution is only recoverable as its per-scope means
    weighted by each scope's completion count. Rank interpolation is linear
    between the two closest ranks, matching the conventional definition.

    Returns ``None`` when the sample is empty or every weight is zero - there is
    no distribution to rank, so the percentile column stays NULL.
    """
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be within [0, 1], got {fraction}")
    total_weight = sum(weight for _, weight in points)
    if total_weight <= 0:
        return None
    ordered = sorted(points)
    position = fraction * (total_weight - 1)
    lower_rank = math.floor(position)
    upper_rank = math.ceil(position)
    lower_value = _value_at_rank(ordered, lower_rank)
    if upper_rank == lower_rank:
        return lower_value
    upper_value = _value_at_rank(ordered, upper_rank)
    return lower_value + (upper_value - lower_value) * (position - lower_rank)


def percentile(samples: Sequence[float], fraction: float) -> float | None:
    """The ``fraction`` percentile of an unweighted sample of observations.

    ``None`` for an empty sample. Used directly by the p50/p95/p99 reads; see
    :func:`weighted_percentile` for the rank definition.
    """
    return weighted_percentile([(value, 1) for value in samples], fraction)


def _as_ms(value: float) -> Decimal:
    """A percentile rendered at the 2dp scale of the ``*_duration_ms`` columns."""
    return Decimal(f"{value:.2f}")


# ----------------------------------------------------- usage shapes (pure data)


@dataclass(frozen=True)
class UsageScope:
    """One ``observability_ai_usage_daily`` row, loaded as plain values.

    ``avg_duration_ms`` is the running mean over COMPLETIONS the B4a consumer
    maintains (``None`` when a scope has no completion to average); the
    failure/timeout counters carry no duration because a failed job reports none.
    """

    model: str
    task_type: str
    calls: int
    success_count: int
    failure_count: int
    timeout_count: int
    cost_paise: int
    avg_duration_ms: Decimal | None


@dataclass(frozen=True)
class ProviderUsage:
    """Every ``observability_ai_usage_daily`` scope for one provider on one date."""

    provider: str
    scopes: tuple[UsageScope, ...]

    @property
    def calls(self) -> int:
        return sum(scope.calls for scope in self.scopes)

    @property
    def success_count(self) -> int:
        return sum(scope.success_count for scope in self.scopes)

    @property
    def failure_count(self) -> int:
        return sum(scope.failure_count for scope in self.scopes)

    @property
    def timeout_count(self) -> int:
        return sum(scope.timeout_count for scope in self.scopes)

    @property
    def cost_paise(self) -> int:
        return sum(scope.cost_paise for scope in self.scopes)

    @property
    def models(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(scope.model for scope in self.scopes))


# ----------------------------------------------------------- health computation


def ratio(numerator: int, denominator: int) -> Decimal | None:
    """``numerator`` over ``denominator`` at the 4dp scale of the rate columns.

    ``None`` only when ``denominator`` is zero: an absent sample is not a ``0.0000``
    and the two must stay distinguishable to a reader. Shared by every rate MOD-013
    reports, so the success rate, the provider-health rate, and the operator read
    API's low-confidence rate all render at one scale.
    """
    if denominator <= 0:
        return None
    rate = Decimal(numerator) / Decimal(denominator)
    return rate.quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)


def success_rate(success_count: int, calls: int) -> Decimal | None:
    """The share of ``calls`` that succeeded, at the 4dp scale of the column.

    ``None`` only when there were no calls at all - a scope with traffic and no
    success is a real ``0.0000`` and must stay distinguishable from no traffic.
    """
    return ratio(success_count, calls)


def breaker_state_for(rate: Decimal | None, *, open_below: Decimal) -> str:
    """The breaker state the rollup records for an observed success ``rate``.

    Open strictly below ``open_below``: no observed traffic (``None``) reads as
    closed, because an absent sample is not evidence of provider failure.
    """
    if rate is None or rate >= open_below:
        return BREAKER_STATE_CLOSED
    return BREAKER_STATE_OPEN


@dataclass(frozen=True)
class ProviderHealth:
    """The recomputed ``observability_ai_provider_health`` row for one provider.

    ``window_start``/``window_end`` are the half-open UTC bounds of the rolled
    date, so a reader can tell a single-day window from a longer one.
    """

    provider: str
    window_start: datetime
    window_end: datetime
    sample_count: int
    success_rate: Decimal | None
    p50_duration_ms: Decimal | None
    p95_duration_ms: Decimal | None
    p99_duration_ms: Decimal | None
    breaker_state: str


def duration_samples(usage: ProviderUsage) -> tuple[tuple[float, int], ...]:
    """The weighted duration sample for ``usage``: one point per completable scope.

    Each scope contributes ``(mean_duration_ms, success_count)`` - its own
    completions at its own mean. A scope with no completions, or no recorded mean,
    contributes nothing: it has no duration observation.
    """
    return tuple(
        (float(scope.avg_duration_ms), scope.success_count)
        for scope in usage.scopes
        if scope.avg_duration_ms is not None and scope.success_count > 0
    )


def compute_provider_health(
    provider: str,
    window_start: datetime,
    window_end: datetime,
    usage: ProviderUsage,
    *,
    breaker_open_below: Decimal = DEFAULT_BREAKER_OPEN_SUCCESS_RATE,
) -> ProviderHealth:
    """Recompute one provider's health for the half-open window ``[start, end)``.

    p50/p95/p99 rank the sample-weighted duration distribution and are ``None``
    when the provider recorded no completion to time. ``sample_count`` counts the
    observations behind the percentiles (completions), while ``success_rate`` is
    over ALL calls - a provider that mostly failed has a low rate over a thin
    latency sample, and the two numbers are read together.
    """
    points = duration_samples(usage)
    p50 = weighted_percentile(points, 0.50)
    p95 = weighted_percentile(points, 0.95)
    p99 = weighted_percentile(points, 0.99)
    rate = success_rate(usage.success_count, usage.calls)
    return ProviderHealth(
        provider=provider,
        window_start=window_start,
        window_end=window_end,
        sample_count=sum(weight for _, weight in points),
        success_rate=rate,
        p50_duration_ms=_as_ms(p50) if p50 is not None else None,
        p95_duration_ms=_as_ms(p95) if p95 is not None else None,
        p99_duration_ms=_as_ms(p99) if p99 is not None else None,
        breaker_state=breaker_state_for(rate, open_below=breaker_open_below),
    )


def provider_health_drop(previous: Decimal | None, current: Decimal | None) -> Decimal | None:
    """How far the success rate fell below ``previous``.

    Positive when the provider got worse, negative when it improved, and ``None``
    when either side is unknown - the first rollup of a provider has no baseline,
    which is not a drop.
    """
    if previous is None or current is None:
        return None
    return (previous - current).quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- budget snapshot


def budget_period_for(target_date: date) -> tuple[date, date]:
    """The inclusive calendar-month bounds ``[start, end]`` around ``target_date``."""
    start = target_date.replace(day=1)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    return start, end


@dataclass(frozen=True)
class BudgetSnapshot:
    """One ``observability_ai_cost_budget`` row: a scope's spend against the cap.

    Paise throughout, like ``BudgetMeter`` - the rollup SNAPSHOTS spend, it never
    enforces it (PS-10, #408). This row is the per-``(provider, model)`` share of
    the month's spend; the ``ai_budget`` alert is raised against the month's
    TOTAL (see :func:`evaluate_budget_alerts`), because ``AI_MONTHLY_BUDGET_PAISE``
    is one cap compared against the whole bill.
    """

    provider: str
    model: str
    monthly_limit_paise: int
    alert_threshold_pct: int
    current_spend_paise: int
    billing_period_start: date
    billing_period_end: date

    @property
    def remaining_paise(self) -> int:
        """What is left of the cap; floored at zero so it is never negative."""
        return max(0, self.monthly_limit_paise - self.current_spend_paise)

    @property
    def utilization_pct(self) -> Decimal:
        """Spend as a percentage of the cap, at 2dp. Unbounded above 100."""
        return (
            Decimal(self.current_spend_paise) / Decimal(self.monthly_limit_paise) * 100
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def exhausted(self) -> bool:
        """Whether this scope's spend has reached the cap - the observe-and-warn flag."""
        return self.current_spend_paise >= self.monthly_limit_paise


def build_budget_snapshot(
    provider: str,
    model: str,
    spend_paise: int,
    *,
    monthly_limit_paise: int,
    period_start: date,
    period_end: date,
    alert_threshold_pct: int = DEFAULT_BUDGET_ALERT_THRESHOLD_PCT,
) -> BudgetSnapshot:
    """Snapshot one ``(provider, model)`` budget for a billing period.

    ``spend_paise`` is the month-to-date aggregate the adapter already summed;
    keeping the function pure means the threshold arithmetic is testable with no
    database. A non-positive limit is refused rather than divided by.
    """
    if monthly_limit_paise <= 0:
        raise ValueError("monthly_limit_paise must be positive")
    return BudgetSnapshot(
        provider=provider,
        model=model,
        monthly_limit_paise=monthly_limit_paise,
        alert_threshold_pct=alert_threshold_pct,
        current_spend_paise=spend_paise,
        billing_period_start=period_start,
        billing_period_end=period_end,
    )


# ------------------------------------------------------------------ thresholds


@dataclass(frozen=True)
class RollupThresholds:
    """The tunable half of the rollup: one value per alert threshold.

    Defaults are the values plan-phase14 §11 names; a deployment can move them
    without touching the computations.
    """

    monthly_budget_paise: int
    budget_alert_threshold_pct: int = DEFAULT_BUDGET_ALERT_THRESHOLD_PCT
    breaker_open_success_rate: Decimal = DEFAULT_BREAKER_OPEN_SUCCESS_RATE
    provider_health_drop_threshold: Decimal = DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD
    outbox_backlog_threshold: int = DEFAULT_OUTBOX_BACKLOG_ALERT_THRESHOLD

    def __post_init__(self) -> None:
        if self.monthly_budget_paise <= 0:
            raise ValueError("monthly_budget_paise must be positive")


# --------------------------------------------------------------- alert builders


def _rate_text(value: Decimal) -> str:
    """A rate rendered for a JSON payload at the column's 4dp scale."""
    return f"{value:.4f}"


def _rate_text_or_zero(value: Decimal | None) -> str:
    """A rate rendered for a JSON payload; no traffic reads as ``0.0000``."""
    return _rate_text(Decimal("0.0000") if value is None else value)


def _ms_text(value: Decimal | None) -> str | None:
    """A duration rendered for a JSON payload; ``None`` stays JSON ``null``."""
    return None if value is None else f"{value:.2f}"


def build_budget_alert(
    total_spend_paise: int,
    *,
    monthly_limit_paise: int,
    threshold_pct: int,
    period_start: date,
    period_end: date,
) -> AlertRow:
    """The ``ai_budget`` alert for the month's TOTAL spend past the threshold.

    ``total_spend_paise`` is the whole month's metered cost across every provider
    and model, because ``AI_MONTHLY_BUDGET_PAISE`` is one cap compared against the
    whole bill - the same figure ``BudgetMeter.meter()`` reports. Critical once
    the cap itself is reached, warning while it is merely past the threshold;
    PHI-free paise figures and dates only (``error-handling-observability.md`` §5).
    """
    total = build_budget_snapshot(
        _BUDGET_ALERT_SCOPE,
        _BUDGET_ALERT_SCOPE,
        total_spend_paise,
        monthly_limit_paise=monthly_limit_paise,
        period_start=period_start,
        period_end=period_end,
        alert_threshold_pct=threshold_pct,
    )
    return AlertRow(
        severity=ALERT_SEVERITY_CRITICAL if total.exhausted else ALERT_SEVERITY_WARNING,
        kind=ALERT_KIND_AI_BUDGET,
        title=f"AI budget past {threshold_pct}% of the monthly cap",
        payload={
            "source": _ALERT_SOURCE,
            "scope": _BUDGET_ALERT_SCOPE,
            "current_spend_paise": total_spend_paise,
            "monthly_limit_paise": monthly_limit_paise,
            "alert_threshold_pct": threshold_pct,
            "utilization_pct": f"{total.utilization_pct:.2f}",
            "billing_period_start": period_start.isoformat(),
            "billing_period_end": period_end.isoformat(),
        },
    )


def build_provider_health_drop_alert(
    health: ProviderHealth,
    previous_success_rate: Decimal | None,
    *,
    drop_threshold: Decimal,
) -> AlertRow | None:
    """The ``provider_health_drop`` alert, or ``None`` when the drop is within range.

    ``None`` on the first rollup of a provider (no prior reading to drop from)
    and on an improvement - a rise in the success rate is never an alert.
    """
    if previous_success_rate is None or health.success_rate is None:
        return None
    drop = provider_health_drop(previous_success_rate, health.success_rate)
    if drop is None or drop < drop_threshold:
        return None
    return AlertRow(
        severity=ALERT_SEVERITY_WARNING,
        kind=ALERT_KIND_PROVIDER_HEALTH_DROP,
        title=f"AI provider health dropped for {health.provider}",
        payload={
            "source": _ALERT_SOURCE,
            "provider": health.provider,
            "previous_success_rate": _rate_text(previous_success_rate),
            "success_rate": _rate_text(health.success_rate),
            "success_rate_drop": _rate_text(drop),
            "window_start": health.window_start.isoformat(),
            "window_end": health.window_end.isoformat(),
        },
    )


def build_breaker_open_alert(health: ProviderHealth) -> AlertRow:
    """The critical ``breaker_open`` alert for a provider observed below the floor.

    The rollup never trips a breaker - it records the state it observed and
    reports it, matching the minimum alert set's "repeated third-party failures
    (breaker open)" member.
    """
    return AlertRow(
        severity=ALERT_SEVERITY_CRITICAL,
        kind=ALERT_KIND_BREAKER_OPEN,
        title=f"AI provider breaker open for {health.provider}",
        payload={
            "source": _ALERT_SOURCE,
            "provider": health.provider,
            "breaker_state": health.breaker_state,
            "success_rate": _rate_text_or_zero(health.success_rate),
            "window_start": health.window_start.isoformat(),
            "window_end": health.window_end.isoformat(),
        },
    )


def build_outbox_backlog_alert(table: str, *, backlog: int, threshold: int) -> AlertRow | None:
    """The ``outbox_backlog`` alert, or ``None`` at or below ``threshold``."""
    if backlog <= threshold:
        return None
    return AlertRow(
        severity=ALERT_SEVERITY_WARNING,
        kind=ALERT_KIND_OUTBOX_BACKLOG,
        title=f"Outbox backlog of {backlog} undelivered event(s) in {table}",
        payload={
            "source": _ALERT_SOURCE,
            "table": table,
            "backlog": backlog,
        },
    )


def build_dead_letter_alert(table: str, *, dead_letter_count: int) -> AlertRow:
    """The critical ``outbox_dead_letter`` alert: one row is a terminal failure."""
    return AlertRow(
        severity=ALERT_SEVERITY_CRITICAL,
        kind=ALERT_KIND_OUTBOX_DEAD_LETTER,
        title=f"Outbox dead-letter row in {table}",
        payload={
            "source": _ALERT_SOURCE,
            "table": table,
            "dead_letter_count": dead_letter_count,
        },
    )


@dataclass(frozen=True)
class OutboxTableHealth:
    """One outbox table's row counts, read through the dispatcher's table contract.

    Counted per status by the adapter; the rollup needs no cross-schema SQL of
    its own (ADR-0003 - the dispatcher owns the outbox shape).
    """

    schema: str
    table: str
    pending: int = 0
    inflight: int = 0
    dead_letter: int = 0

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.table}"

    @property
    def backlog(self) -> int:
        """Rows still owed a delivery attempt: ``pending`` plus ``inflight``."""
        return self.pending + self.inflight


def evaluate_budget_alerts(
    total_spend_paise: int,
    thresholds: RollupThresholds,
    *,
    period_start: date,
    period_end: date,
) -> tuple[AlertRow, ...]:
    """The month's ``ai_budget`` alerts for the TOTAL metered spend.

    One cap, one alert: ``AI_MONTHLY_BUDGET_PAISE`` bounds the whole bill, so the
    threshold is tested against the sum over every ``(provider, model)`` rather
    than against each scope's share. Strictly greater than the threshold - the
    plan's "AI budget meter > 80%".
    """
    threshold_paise = (
        Decimal(thresholds.monthly_budget_paise) * Decimal(thresholds.budget_alert_threshold_pct)
    ) / 100
    if Decimal(total_spend_paise) <= threshold_paise:
        return ()
    return (
        build_budget_alert(
            total_spend_paise,
            monthly_limit_paise=thresholds.monthly_budget_paise,
            threshold_pct=thresholds.budget_alert_threshold_pct,
            period_start=period_start,
            period_end=period_end,
        ),
    )


def evaluate_provider_health_alerts(
    health: ProviderHealth,
    previous_success_rate: Decimal | None,
    thresholds: RollupThresholds,
) -> tuple[AlertRow, ...]:
    """The alerts one provider's recomputed health raises, most severe first."""
    alerts: list[AlertRow] = []
    if health.breaker_state == BREAKER_STATE_OPEN:
        alerts.append(build_breaker_open_alert(health))
    drop_alert = build_provider_health_drop_alert(
        health,
        previous_success_rate,
        drop_threshold=thresholds.provider_health_drop_threshold,
    )
    if drop_alert is not None:
        alerts.append(drop_alert)
    return tuple(alerts)


def evaluate_outbox_health_alerts(
    health: OutboxTableHealth, thresholds: RollupThresholds
) -> tuple[AlertRow, ...]:
    """The alerts one outbox table's row counts raise, backlog first."""
    alerts: list[AlertRow] = []
    backlog_alert = build_outbox_backlog_alert(
        health.qualified_name,
        backlog=health.backlog,
        threshold=thresholds.outbox_backlog_threshold,
    )
    if backlog_alert is not None:
        alerts.append(backlog_alert)
    if health.dead_letter > 0:
        alerts.append(
            build_dead_letter_alert(health.qualified_name, dead_letter_count=health.dead_letter)
        )
    return tuple(alerts)


# -------------------------------------------------------- alert identity / scope


def alert_marker(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The ``(kind, scope)`` marker that identifies an alert's subject.

    Only the source and the scope keys count, so the measured figures inside a
    payload (``backlog``, ``current_spend_paise``, ...) never affect identity: a
    budget that climbs from 81% to 92% is the same open finding.
    """
    return {key: payload[key] for key in ("source", *_ALERT_SCOPE_KEYS) if key in payload}


def alert_key(kind: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    """The stable dedupe key for ``kind`` over ``payload``'s scope marker."""
    return kind, repr(sorted(alert_marker(payload).items()))


def evaluated_alert_keys(
    *, providers: Sequence[str], tables: Sequence[str]
) -> set[tuple[str, str]]:
    """Every ``(kind, scope)`` a pass with these inputs could raise.

    The resolve step may only close an open alert this pass actually re-evaluated,
    so absence of evidence never clears a standing condition: a pass that saw no
    traffic for a provider leaves that provider's ``breaker_open`` alert open.
    The monthly budget is always evaluated, so its key is unconditional.
    """
    keys = {
        alert_key(ALERT_KIND_AI_BUDGET, {"source": _ALERT_SOURCE, "scope": _BUDGET_ALERT_SCOPE})
    }
    for provider in providers:
        marker = {"source": _ALERT_SOURCE, "provider": provider}
        keys.update(
            alert_key(kind, marker)
            for kind in (ALERT_KIND_BREAKER_OPEN, ALERT_KIND_PROVIDER_HEALTH_DROP)
        )
    for table in tables:
        marker = {"source": _ALERT_SOURCE, "table": table}
        keys.update(
            alert_key(kind, marker)
            for kind in (ALERT_KIND_OUTBOX_BACKLOG, ALERT_KIND_OUTBOX_DEAD_LETTER)
        )
    return keys


# ------------------------------------------------------------------- registry


@dataclass(frozen=True)
class RollupProviderInput:
    """What one registered computation is given: the raw scopes and the health.

    Both are computed once per provider by the adapter, so a registered metric
    can read the percentiles without re-deriving them, and the recomputed health
    is not recomputed per metric.
    """

    usage: ProviderUsage
    health: ProviderHealth


@dataclass(frozen=True)
class RollupMetricValue:
    """One generic-store row: the fully-qualified ``metric_key`` and its JSON value.

    The key is the registered prefix plus the scope the entry computed over, so
    ``observability_business_daily`` keeps its ``(metric_key, metric_date)``
    uniqueness without any per-metric column (plan-phase14 §7.2).
    """

    metric_key: str
    value: dict[str, Any]


@dataclass(frozen=True)
class RollupMetric:
    """A registry entry: a stable ``metric_key`` prefix and its pure computation.

    Registering one is how a LATER phase adds a metric - a single
    :func:`register_rollup_metric` call, no schema churn, no adapter edit.
    """

    metric_key: str
    compute: Callable[[RollupProviderInput], Mapping[str, Any]]


#: The live registry, in the order rows are written. ``metric_key -> computation``.
ROLLUP_REGISTRY: dict[str, RollupMetric] = {}


def register_rollup_metric(metric: RollupMetric) -> RollupMetric:
    """Add ``metric`` to the registry and return it.

    A duplicate key is refused rather than silently overwritten: two computations
    claiming one ``metric_key`` would fight over the same generic-store row.
    """
    if metric.metric_key in ROLLUP_REGISTRY:
        raise ValueError(f"rollup metric {metric.metric_key!r} is already registered")
    ROLLUP_REGISTRY[metric.metric_key] = metric
    return metric


def rollup_metric_keys() -> tuple[str, ...]:
    """The registered metric-key prefixes, in registration order."""
    return tuple(ROLLUP_REGISTRY)


def rollup_metrics_for(
    usage: ProviderUsage, health: ProviderHealth
) -> tuple[RollupMetricValue, ...]:
    """Project one provider through every registered computation.

    The values are plain JSON scalars (rates and durations rendered as strings)
    so they serialise into the ``JSONB`` generic store without an encoder.
    """
    provider_input = RollupProviderInput(usage=usage, health=health)
    return tuple(
        RollupMetricValue(
            metric_key=f"{metric.metric_key}.{usage.provider}",
            value=dict(metric.compute(provider_input)),
        )
        for metric in ROLLUP_REGISTRY.values()
    )


def _provider_health_metric(provider_input: RollupProviderInput) -> Mapping[str, Any]:
    """The provider's latency + reliability snapshot for the rolled date."""
    health = provider_input.health
    return {
        "provider": health.provider,
        "sample_count": health.sample_count,
        "success_rate": _rate_text_or_zero(health.success_rate),
        "p50_duration_ms": _ms_text(health.p50_duration_ms),
        "p95_duration_ms": _ms_text(health.p95_duration_ms),
        "p99_duration_ms": _ms_text(health.p99_duration_ms),
        "breaker_state": health.breaker_state,
    }


def _spend_metric(provider_input: RollupProviderInput) -> Mapping[str, Any]:
    """The provider's call mix and metered spend for the rolled date."""
    usage = provider_input.usage
    return {
        "provider": usage.provider,
        "calls": usage.calls,
        "success_count": usage.success_count,
        "failure_count": usage.failure_count,
        "timeout_count": usage.timeout_count,
        "cost_paise": usage.cost_paise,
    }


register_rollup_metric(
    RollupMetric(metric_key=METRIC_KEY_AI_PROVIDER_HEALTH, compute=_provider_health_metric)
)
register_rollup_metric(RollupMetric(metric_key=METRIC_KEY_AI_SPEND, compute=_spend_metric))


# ------------------------------------------------------------------- the schedule


@dataclass(frozen=True)
class RollupPlan:
    """The dates one invocation rolls, oldest first, and which mode chose them.

    ``dates`` may be EMPTY - the pass is then a no-op, which is what a re-run of
    the same night is (plan-phase14 §8: "first run processes all existing
    ``intake_ai_jobs``; subsequent runs process the previous day"). ``mode`` is
    what the invocation records on the run ledger, so the backfill is auditable
    after the fact rather than inferred.
    """

    mode: str
    dates: tuple[date, ...]
    last_rolled: date | None
    history_start: date | None

    @property
    def is_backfill(self) -> bool:
        """Whether this invocation is the first-run history sweep."""
        return self.mode == ROLLUP_MODE_BACKFILL


def _inclusive_window(first: date, last: date, max_dates: int) -> tuple[date, ...]:
    """``first``..``last`` inclusive, oldest first, trimmed to ``max_dates`` from the front.

    Trimming takes the OLDEST days, not the newest: a pass that skipped the middle
    would lose it permanently, whereas one that stops early leaves the remainder
    for the next invocation to pick up from the ledger it is about to write.
    """
    return tuple(first + timedelta(days=offset) for offset in range((last - first).days + 1))[
        :max_dates
    ]


def plan_rollup_dates(
    *,
    today: date,
    last_rolled: date | None,
    history_start: date | None,
    max_dates: int,
) -> RollupPlan:
    """The UTC dates one scheduled invocation rolls, from the rollup's own state.

    B5b #705, plan-phase14 §8. Coverage is decided by what the rollup has ALREADY
    recorded, never by when the job happened to fire, so the rule is testable and a
    skipped night is not a lost day:

    * ``last_rolled is None`` - the first run. It sweeps the recorded AI-job history
      from ``history_start`` (the oldest ``observability_ai_usage_daily`` date, the
      module's own record of what the B4 consumer metered) up to yesterday.
    * otherwise - the daily pass. It rolls every day since ``last_rolled``, which in
      the steady state is yesterday alone, and an already-current ledger plans nothing.

    Yesterday is the hard ceiling in both cases: today is still accumulating when
    the nightly pass fires. ``max_dates`` bounds one invocation; the surplus stays
    covered by the next one.

    A ``last_rolled`` at or beyond today is treated as no information at all rather
    than as "already caught up": the caller reads the ledger bounded by today (see
    ``rollup.load_rollup_state``), so a run stamped into the future cannot silently
    switch the schedule off.
    """
    if max_dates < 1:
        raise ValueError("max_dates must be at least 1")
    yesterday = today - timedelta(days=1)

    if last_rolled is None:
        floor = min(filter(None, (history_start, yesterday)), default=yesterday)
        return RollupPlan(
            mode=ROLLUP_MODE_BACKFILL,
            dates=_inclusive_window(floor, yesterday, max_dates),
            last_rolled=None,
            history_start=history_start,
        )

    first = last_rolled + timedelta(days=1)
    if first > yesterday:
        return RollupPlan(
            mode=ROLLUP_MODE_DAILY, dates=(), last_rolled=last_rolled, history_start=history_start
        )
    return RollupPlan(
        mode=ROLLUP_MODE_DAILY,
        dates=_inclusive_window(first, yesterday, max_dates),
        last_rolled=last_rolled,
        history_start=history_start,
    )
