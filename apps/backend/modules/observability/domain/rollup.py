"""MOD-013: the nightly rollup's pure core - percentiles, health, budget, alerts.

B5a (#704, plan-phase14 §8). Everything in this module is a database-free
function over already-loaded values: the adapter layer
(``modules/observability/rollup.py``) reads rows and persists what these
decide, so every threshold and every percentile is unit-tested without a
database (``error-handling-observability.md`` §5, coding-standards §2).

Three pieces:

* the estimator (:func:`percentile`, :func:`weighted_percentile`) plus the
  provider-health recompute it feeds, and the healthy/degraded/down status the
  provider board derives from that recompute (#728);
* the paise budget snapshot, which mirrors the ``BudgetMeter``'s
  observe-and-warn semantics (``modules/intake/budget_meter.py``, PS-10 #408) -
  the rollup SNAPSHOTS spend, it never enforces it;
* the ``metric_key -> computation`` registry (:data:`ROLLUP_REGISTRY`) whose
  results land in the generic ``observability_business_daily`` store
  (plan-phase14 §7.2), so a later phase adds a metric with one registry line and
  no schema churn;
* the daily per-actor attribution aggregate (:func:`build_attribution_daily`,
  B6 #725), recomputed in full from the per-job spend rows so that a doctor
  attribution arriving after its AI job fills itself in without double counting;
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
from typing import Any, Literal

from modules.observability.domain.consumer import (
    AI_JOB_SPEND_STATUS_COMPLETED,
    AI_JOB_SPEND_STATUS_FAILED,
    ALERT_SEVERITY_CRITICAL,
    ALERT_SEVERITY_WARNING,
    AiJobSpendStatus,
    AlertRow,
)
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    ActorKind,
)

#: ``observability_ai_provider_health.breaker_state`` vocabulary. ``half_open``
#: is deliberately absent: the rollup only observes, it never trips a breaker.
BREAKER_STATE_CLOSED = "closed"
BREAKER_STATE_OPEN = "open"

#: The provider board's status vocabulary (#728, spec #717 decision 18). Derived at
#: READ time from the counters the rollup stored and never stored as a column: a
#: stored status is a second source of truth that the nightly recompute could leave
#: contradicting the row it was derived from.
PROVIDER_STATUS_HEALTHY: ProviderStatus = "healthy"
PROVIDER_STATUS_DEGRADED: ProviderStatus = "degraded"
PROVIDER_STATUS_DOWN: ProviderStatus = "down"
ProviderStatus = Literal["healthy", "degraded", "down"]

#: The token the intake producer emits on ``ai_job.failed`` for a provider that
#: refused for quota. It lives here as well as in
#: ``modules.intake.adapters.ai_jobs`` because ADR-0003 forbids importing the
#: producing module, so the count cannot read the constant at runtime. What stops
#: the two copies from drifting is the test named on the producer's constant:
#: ``test_the_reason_the_producer_emits_is_the_one_the_rollup_counts``. Without a
#: rename on both sides, the drift would be silent - the board would count zero
#: quotas and show a throttled provider as healthy.
FAILURE_REASON_RATE_LIMITED = "rate_limited"

#: A provider whose observed success rate falls to or below this is ``degraded`` on
#: the board even with nothing else wrong. Above it, a provider is healthy unless a
#: quota refusal or a timeout says otherwise. Set at the same kind of boundary the
#: breaker uses (:data:`DEFAULT_BREAKER_OPEN_SUCCESS_RATE` at 0.5), one tier lower,
#: because this is the "something is wrong but the provider is still serving" line
#: rather than the "stop calling it" one.
DEFAULT_DEGRADED_SUCCESS_RATE = Decimal("0.9")

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
ALERT_KIND_QUEUE_AGE = "queue_age"
ALERT_KIND_COST_OUTLIER = "cost_outlier"

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

#: How old the OLDEST still-open job in one AI queue may get before ``queue_age``
#: fires (B5, #729). Fifteen minutes is well past any healthy pipeline leg: a
#: transcription or structuring call that has been waiting a quarter of an hour is
#: not slow, it is stuck.
#:
#: Deliberately far BELOW what the backlog threshold would allow, because age and
#: depth are not two views of one condition. A queue holding a single wedged job
#: has a depth of one - invisible to an alert sized for five hundred rows - and an
#: age that grows without limit. Age is the LEADING indicator; a stall has to page
#: on it, not on the row count that follows an hour later.
DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS = 900

#: How many times one actor's own trailing average a single day of its spend has to
#: reach before ``cost_outlier`` fires (B7, #733). A multiple of their OWN history,
#: deliberately and never a rupee amount: a patient whose case genuinely needs four
#: imaging passes and a caller looping the same request four hundred times are the
#: same figure on the meter, and only the actor's own baseline tells them apart. The
#: absolute cap belongs to ``ai_budget``, which bounds the bill; this bounds the
#: SHAPE of one actor's spend.
DEFAULT_COST_OUTLIER_MULTIPLE = Decimal("3")

#: How far back an actor's baseline reaches, in days: the seven days trailing the
#: day under test, not the day under test itself. Including the day being judged
#: would let a large spike raise its own baseline and hide itself.
COST_OUTLIER_BASELINE_DAYS = 7

#: How many of those seven days the actor must actually have spent on before it has
#: a baseline at all. A patient is episodic - a returning one who last spent a week
#: ago would otherwise be measured against an average diluted by six silent days
#: and alert on a perfectly ordinary consultation, which is the false positive that
#: trains an operator to dismiss the feed.
MIN_COST_OUTLIER_BASELINE_DAYS = 3

#: The precision every ratio in a ``cost_outlier`` payload is reported at. The rule
#: compares at this precision too, so a payload can never state a deviation that
#: reads as at-or-below the threshold it fired against.
_COST_OUTLIER_QUANTUM = Decimal("0.01")

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
_ALERT_SCOPE_KEYS = ("provider", "model", "table", "queue", "scope", "actor")

#: The ``ai_budget`` alert's scope: the ONE monthly cap compared against TOTAL
#: spend, the same figure ``BudgetMeter.meter()`` reports. Not per provider/model -
#: a per-scope cap would make the effective budget the cap times the scope count.
_BUDGET_ALERT_SCOPE = "monthly_total"

#: Alert kinds describing a STANDING condition, which a later pass resolves once
#: the condition clears. ``provider_health_drop`` is deliberately absent: a drop
#: is a transition with no steady state (the health row holds one rate per
#: provider), so a pass raises it and leaves it for the operator's history rather
#: than closing an alert it raised for the same reading. ``queue_age`` belongs here
#: (B5, #729): a queue that drains stops being an alert, and an alert that has to be
#: cleared by hand trains the operator to ignore the feed. ``cost_outlier`` belongs
#: here for the same reason (B7, #733): a spike that does not repeat is a one-off
#: worth reading once and then closing, not an incident to keep open.
RESOLVABLE_ALERT_KINDS: frozenset[str] = frozenset(
    {
        ALERT_KIND_AI_BUDGET,
        ALERT_KIND_BREAKER_OPEN,
        ALERT_KIND_OUTBOX_BACKLOG,
        ALERT_KIND_OUTBOX_DEAD_LETTER,
        ALERT_KIND_QUEUE_AGE,
        ALERT_KIND_COST_OUTLIER,
    }
)

#: Alert kinds that must NEVER auto-resolve (#728, #717 decision 20). Held as its
#: own set, complementary to :data:`RESOLVABLE_ALERT_KINDS`, because a rule that
#: exists only as an ABSENCE is one somebody tidies up: adding this kind to the set
#: above looks like completing the vocabulary and silently makes a degraded
#: provider disappear from the board the moment it recovers (#717 story 55).
#: Stated here as data, the resolve step reads both sets, and a test asserts the
#: two are disjoint and together cover every rollup kind - so "tidy it up" fails a
#: test rather than shipping.
NON_RESOLVABLE_ALERT_KINDS: frozenset[str] = frozenset(
    {
        ALERT_KIND_PROVIDER_HEALTH_DROP,
    }
)


def alert_kind_resolves(kind: str) -> bool:
    """Whether a later pass is allowed to close an open alert of ``kind``.

    The single question the resolve step asks, and the single place both vocabularies
    are read. Membership of :data:`RESOLVABLE_ALERT_KINDS` alone would leave the
    never-auto-resolve rule living only in a comment: the two sets are therefore
    checked together here, so a kind that lands in both is refused rather than
    silently resolving.
    """
    return kind in RESOLVABLE_ALERT_KINDS and kind not in NON_RESOLVABLE_ALERT_KINDS


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

    ``timeout_count``, ``rate_limit_count`` and ``last_error`` are #728's
    additions: the window's timeouts and quota refusals, and the most recent
    failure's reason. The first two come from the day's usage scopes, the third
    from the day's per-job spend rows, so all three are stored as measured rather
    than reconstructed at read time.
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
    timeout_count: int = 0
    rate_limit_count: int = 0
    last_error: str | None = None


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


@dataclass(frozen=True)
class ProviderFailures:
    """One provider's failed attempts for a single rolled day.

    Built from ``observability_ai_job_spend``, the per-job source the attribution
    aggregate already reads, so the board's failure figures come from rows the
    provider itself produced rather than from a second tally kept alongside them.
    ``last_error`` is already ordered (most recent first) by whoever assembled it.
    """

    rate_limit_count: int
    last_error: str | None


def summarize_failures(reasons: Sequence[str | None]) -> ProviderFailures:
    """Count the day's quota refusals and take its most recent reason to name.

    ``reasons`` is the day's failed jobs in MOST-RECENT-FIRST order, so the first
    non-empty entry is the newest failure there is to name. A day with no failure at
    all gives ``rate_limit_count == 0`` and ``last_error is None``, which reads as
    "nothing to report" rather than as a healthy provider - the board derives the
    status separately and deliberately does not treat a missing reason as evidence
    of health.
    """
    rate_limited = 0
    last_error: str | None = None
    for reason in reasons:
        if not reason:
            continue
        if reason == FAILURE_REASON_RATE_LIMITED:
            rate_limited += 1
        if last_error is None:
            last_error = reason
    return ProviderFailures(rate_limit_count=rate_limited, last_error=last_error)


def compute_provider_health(
    provider: str,
    window_start: datetime,
    window_end: datetime,
    usage: ProviderUsage,
    *,
    breaker_open_below: Decimal = DEFAULT_BREAKER_OPEN_SUCCESS_RATE,
    failures: ProviderFailures | None = None,
) -> ProviderHealth:
    """Recompute one provider's health for the half-open window ``[start, end)``.

    p50/p95/p99 rank the sample-weighted duration distribution and are ``None``
    when the provider recorded no completion to time. ``sample_count`` counts the
    observations behind the percentiles (completions), while ``success_rate`` is
    over ALL calls - a provider that mostly failed has a low rate over a thin
    latency sample, and the two numbers are read together.

    ``failures`` carries the day's quota refusals and newest failure reason
    (#728). It is optional and defaults to "none observed", so the count and the
    reason a provider accumulated before this ticket existed still roll up - the
    counters are unchanged, only previously-unwritten columns are filled.
    """
    points = duration_samples(usage)
    p50 = weighted_percentile(points, 0.50)
    p95 = weighted_percentile(points, 0.95)
    p99 = weighted_percentile(points, 0.99)
    rate = success_rate(usage.success_count, usage.calls)
    observed = failures if failures is not None else ProviderFailures(0, None)
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
        timeout_count=usage.timeout_count,
        rate_limit_count=observed.rate_limit_count,
        last_error=observed.last_error,
    )


def provider_status(health: ProviderHealth) -> ProviderStatus:
    """Resolve one rolled provider's board status: healthy, degraded or down.

    Derived from the counters the health row carries, never stored (#717
    decision 18): a stored status would be a second source of truth the nightly
    recompute could leave contradicting the row it was derived from. The order is
    what makes each verdict safe to act on, so it is the order written:

    1. **Down** when the breaker is open, or when the window recorded calls and
       NOT ONE of them succeeded. The second arm is the one an operator most
       needs right, and it is written out rather than left to the breaker: a
       ``success_rate`` of ``0.0000`` is a provider that was asked and refused
       every time, with every percentile ``None`` behind it because there was no
       completion to time. Reading that as "no data" would report an outage as
       silence.
    2. **Degraded** when the provider was refused for quota, when it timed out, or
       when its success rate fell to or below :data:`DEFAULT_DEGRADED_SUCCESS_RATE`.
       Any one of these is "still answering, but not normally", which calls for a
       different action from down and a different one from healthy.
    3. **Healthy** otherwise - including a provider with NO traffic at all
       (``success_rate is None``), which is idle rather than working. Absence of a
       sample is never evidence of a failure, exactly as it is not for
       :func:`breaker_state_for`.

    ``last_error`` is deliberately NOT an input. A named failure is what an
    operator reads once the status has already told them to look, and letting it
    drive the status would make the word a provider happened to emit on one call
    outrank twenty that succeeded.
    """
    if health.breaker_state == BREAKER_STATE_OPEN:
        return PROVIDER_STATUS_DOWN
    if health.success_rate is not None and health.success_rate <= 0:
        return PROVIDER_STATUS_DOWN
    if health.rate_limit_count > 0 or health.timeout_count > 0:
        return PROVIDER_STATUS_DEGRADED
    if health.success_rate is not None and health.success_rate <= DEFAULT_DEGRADED_SUCCESS_RATE:
        return PROVIDER_STATUS_DEGRADED
    return PROVIDER_STATUS_HEALTHY


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
class ActorSpend:
    """One ``observability_ai_job_spend`` row, as the attribution rollup reads it.

    ``doctor_key`` is what the JOB knew, which for the transcription and
    structuring legs is nothing: those run before the patient picks a doctor. The
    edge in :func:`build_attribution_daily` is what fills that gap.
    """

    intake_ref: int
    patient_key: str
    doctor_key: str | None
    provider: str
    model: str
    task_type: str
    input_tokens: int
    output_tokens: int
    cost_paise: int
    status: AiJobSpendStatus


@dataclass(frozen=True)
class _ActorScope:
    """The grouping key of one actor row: the table's UNIQUE key minus the date.

    Named rather than a bare five-tuple so the summed figure is written back out
    field by field against something that says what each element is.
    """

    actor_kind: ActorKind
    actor_key: str
    provider: str
    model: str
    task_type: str


@dataclass(frozen=True)
class AttributionDaily:
    """One recomputed actor-day row of ``observability_attribution_daily``.

    The UNIQUE key of the table is ``(usage_date, actor_kind, actor_key, provider,
    model, task_type)``; ``usage_date`` is supplied by the adapter, so this value
    carries the other five plus the six counters.

    **Counters only.** Cost per thousand input or output tokens, per request, per
    completed task, per patient, per doctor and cost-of-pass are read-time
    divisions over exactly these columns (#717 decision 8), so none of them is a
    column here: a stored copy would be a second source of truth that goes stale
    the moment the day is recomputed.

    ``revenue_paise`` and ``tier_key`` are absent for the mirror-image reason
    (decision 9): the PRD defers the revenue model, so the rollup has no source
    for them and must not claim the dimensions - see
    :func:`~modules.observability.rollup._upsert_attribution_daily`.
    """

    actor_kind: ActorKind
    actor_key: str
    provider: str
    model: str
    task_type: str
    jobs: int
    completed_jobs: int
    failed_jobs: int
    input_tokens: int
    output_tokens: int
    cost_paise: int


@dataclass
class _ActorTotals:
    """The running counters for one actor scope, summed over that day's jobs."""

    jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_paise: int = 0

    def add(self, spend: ActorSpend) -> None:
        """Add one job's contribution. The status vocabulary is closed by a CHECK."""
        self.jobs += 1
        if spend.status == AI_JOB_SPEND_STATUS_COMPLETED:
            self.completed_jobs += 1
        elif spend.status == AI_JOB_SPEND_STATUS_FAILED:
            self.failed_jobs += 1
        self.input_tokens += spend.input_tokens
        self.output_tokens += spend.output_tokens
        self.cost_paise += spend.cost_paise


def _doctor_for(spend: ActorSpend, doctor_by_intake: Mapping[int, str]) -> str | None:
    """The doctor this job's spend belongs to, or ``None`` when nothing says yet.

    The intake's CURRENT edge wins over the key the job itself carried. A re-pick
    moves the edge, and a drafting job that ran before it carries the doctor the
    patient has moved on from; letting the row's own key win would split one
    intake's spend across two doctors on the same day and stop the per-patient and
    per-doctor figures reconciling. The row's key is the fallback, which is what
    covers a pick the edge table has not recorded yet.

    ``None`` is returned rather than a placeholder: an unattributed job produces no
    doctor row at all, so an operator can see the gap instead of reading
    unattributed spend as attributed.
    """
    edge = doctor_by_intake.get(spend.intake_ref)
    return edge if edge is not None else spend.doctor_key


def build_attribution_daily(
    *,
    spend: Sequence[ActorSpend],
    doctor_by_intake: Mapping[int, str],
) -> tuple[AttributionDaily, ...]:
    """Recompute one day's per-actor aggregate from the per-job spend rows.

    B6 (#725), #717 decisions 5-9. Every returned row is the WHOLE figure for its
    scope, derived from this day's source rows and nothing else: the adapter
    upserts it on the table's UNIQUE key, so a second pass over the same data
    lands on the identical row rather than adding to it. That is the property the
    late-arriving care-attribution edge depends on - an incrementing rollup could
    never add a doctor to an intake whose jobs were already counted.

    Each job contributes to TWO rows - its patient and, when a doctor is known, the
    doctor whose case it served - with identical figures. That is not double
    counting: it is one rupee of cost recorded against the two actors the business
    reads need it against, which is what lets per-patient and per-doctor cost
    reconcile.

    The output is sorted by ``(actor_kind, actor_key, provider, model, task_type)``
    so two passes over the same rows produce the same rows in the same order -
    order must not depend on arrival for a recompute to be verifiable.
    """
    totals: dict[_ActorScope, _ActorTotals] = {}
    for row in spend:
        actors = [(ACTOR_KIND_PATIENT, row.patient_key)]
        doctor = _doctor_for(row, doctor_by_intake)
        if doctor is not None:
            actors.append((ACTOR_KIND_DOCTOR, doctor))
        for actor_kind, actor_key in actors:
            scope = _ActorScope(
                actor_kind=actor_kind,
                actor_key=actor_key,
                provider=row.provider,
                model=row.model,
                task_type=row.task_type,
            )
            totals.setdefault(scope, _ActorTotals()).add(row)

    return tuple(
        AttributionDaily(
            actor_kind=scope.actor_kind,
            actor_key=scope.actor_key,
            provider=scope.provider,
            model=scope.model,
            task_type=scope.task_type,
            jobs=total.jobs,
            completed_jobs=total.completed_jobs,
            failed_jobs=total.failed_jobs,
            input_tokens=total.input_tokens,
            output_tokens=total.output_tokens,
            cost_paise=total.cost_paise,
        )
        for scope, total in sorted(totals.items(), key=lambda item: _scope_sort_key(item[0]))
    )


def _scope_sort_key(scope: _ActorScope) -> tuple[str, str, str, str, str]:
    """``_ActorScope`` in the order the aggregate is written and read back.

    Stated rather than inherited from ``order=True`` so the sort order is the
    table's UNIQUE key, in the table's column order, by inspection.
    """
    return (scope.actor_kind, scope.actor_key, scope.provider, scope.model, scope.task_type)


# ------------------------------------------------- the actor's own trailing week


@dataclass(frozen=True)
class ActorDailySpend:
    """One actor's metered spend on one day, as the cost-outlier rule reads it.

    The ``observability_attribution_daily`` aggregate already collapsed one actor's
    day across providers, models and task types, so this is the whole actor-day
    figure rather than a per-scope row - which is the grain a deviation has to be
    measured at, since a caller abusing one task type must not be averaged away by
    the patient's other, ordinary ones.
    """

    actor_kind: ActorKind
    actor_key: str
    usage_date: date
    cost_paise: int


@dataclass(frozen=True)
class ActorCostBaseline:
    """What one actor normally spends in a day, and how much of it was observed.

    ``daily_paise`` is the MEAN over the days the actor actually spent on, not over
    all seven calendar days. Those differ for an episodic actor, and the difference
    is the whole judgement: an average diluted by six silent days is near zero, so
    a returning patient's ordinary consultation would read as an infinite multiple
    and alert every single time they came back.
    """

    actor_kind: ActorKind
    actor_key: str
    days: int
    total_paise: int
    daily_paise: Decimal


def actor_cost_baseline(
    rows: Sequence[ActorDailySpend], thresholds: RollupThresholds, *, target_date: date
) -> ActorCostBaseline | None:
    """One actor's own trailing-week average, or ``None`` when it has no history.

    ``rows`` are ONE actor's days, which is the function's precondition and why the
    actor is read off them rather than passed in beside them: a caller that stated
    the pair separately could state one that disagrees with the rows it handed over.

    ``None`` is the answer for an actor with too few spend days behind them, and the
    caller must read it as silence rather than as zero. On a fresh database EVERY
    actor is in this case, so treating it as a baseline of zero would raise the
    whole population's first day as a spike - the loudest possible way to be wrong
    about an abuse rule.

    The day under test is excluded: a spike that counted itself would raise its own
    average and halve the deviation it is being judged on. Rows outside the trailing
    week are excluded too, so a caller may hand over a whole table.
    """
    window_start = target_date - timedelta(days=thresholds.cost_outlier_baseline_days)
    spend_days = {
        row.usage_date
        for row in rows
        if window_start < row.usage_date < target_date and row.cost_paise > 0
    }
    if len(spend_days) < thresholds.cost_outlier_min_baseline_days:
        return None
    total = sum(row.cost_paise for row in rows if row.usage_date in spend_days)
    return ActorCostBaseline(
        actor_kind=rows[0].actor_kind,
        actor_key=rows[0].actor_key,
        days=len(spend_days),
        total_paise=total,
        daily_paise=Decimal(total) / Decimal(len(spend_days)),
    )


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
    queue_age_threshold_seconds: int = DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS
    cost_outlier_multiple: Decimal = DEFAULT_COST_OUTLIER_MULTIPLE
    cost_outlier_baseline_days: int = COST_OUTLIER_BASELINE_DAYS
    cost_outlier_min_baseline_days: int = MIN_COST_OUTLIER_BASELINE_DAYS

    def __post_init__(self) -> None:
        if self.monthly_budget_paise <= 0:
            raise ValueError("monthly_budget_paise must be positive")
        if self.queue_age_threshold_seconds <= 0:
            raise ValueError("queue_age_threshold_seconds must be positive")
        if self.cost_outlier_multiple <= 1:
            # A multiple of one or less fires on every day merely ABOVE the actor's
            # own average, which is what half of any week looks like - the alert
            # would be noise rather than a deviation.
            raise ValueError("cost_outlier_multiple must be greater than 1")
        if self.cost_outlier_baseline_days <= 0:
            raise ValueError("cost_outlier_baseline_days must be positive")
        if not 0 < self.cost_outlier_min_baseline_days <= self.cost_outlier_baseline_days:
            # A minimum wider than the window can never be met, which would silence
            # the rule for every actor in the system rather than for anyone.
            raise ValueError(
                "cost_outlier_min_baseline_days must be positive and no wider "
                "than cost_outlier_baseline_days"
            )


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


def build_queue_age_alert(
    queue: str, *, oldest_age_seconds: int, threshold_seconds: int
) -> AlertRow | None:
    """The ``queue_age`` alert, or ``None`` at or below ``threshold_seconds``.

    B5 (#729). Raised on the AGE of the oldest job still waiting in one AI queue,
    never on its depth - a queue holding a single wedged job would sit at a depth
    of one for the whole incident, which is exactly the case a depth threshold
    sized for five hundred rows can never see. One alert per queue, so a stalled
    ``structure`` leg names itself rather than being averaged into the pipeline.

    Critical rather than warning: a job this old is not going to finish, and the
    patient's workflow behind it is waiting on it. PHI-free by construction - a
    closed queue name (the pipeline leg) and two durations.
    """
    if oldest_age_seconds <= threshold_seconds:
        return None
    return AlertRow(
        severity=ALERT_SEVERITY_CRITICAL,
        kind=ALERT_KIND_QUEUE_AGE,
        title=(
            f"Oldest job in the {queue} AI queue has waited "
            f"{oldest_age_seconds}s (threshold {threshold_seconds}s)"
        ),
        payload={
            "source": _ALERT_SOURCE,
            "queue": queue,
            "oldest_age_seconds": oldest_age_seconds,
            "threshold_seconds": threshold_seconds,
        },
    )


def _ratio_text(value: Decimal) -> str:
    """A paise-per-day, threshold or deviation rendered at :data:`_COST_OUTLIER_QUANTUM`.

    Rendered as text like every other figure in a payload, so the JSONB column needs
    no encoder and a reader sees exactly the precision the rule compared at.
    """
    return f"{value:.2f}"


def actor_alert_scope(actor_kind: ActorKind, actor_key: str) -> str:
    """The ``(kind, key)`` pair a per-actor alert dedupes on.

    One function for the builder and for the pass's evaluated set, because the two
    must agree on a single string: a marker spelled one way when raised and another
    when reconciled is an alert that can never be resolved.

    The value is the PSEUDONYMOUS key, never an intake ref or a name - an alert
    that identifies a patient breaks the no-PHI rule even when it identifies them
    correctly. ``actor_key`` is a one-way hash, which is exactly what lets an
    operator see the SAME actor spike again tomorrow without the payload ever
    holding who they are.
    """
    return f"{actor_kind}:{actor_key}"


def build_cost_outlier_alert(
    actor_kind: ActorKind,
    actor_key: str,
    *,
    recent_spend_paise: int,
    baseline: ActorCostBaseline,
    multiple: Decimal,
    usage_date: date,
) -> AlertRow | None:
    """The ``cost_outlier`` alert for one actor's day, or ``None`` within range.

    **Relative, never absolute.** The comparison is ``recent_spend_paise`` against
    ``baseline.daily_paise * multiple`` - that actor's own trailing average times
    the configured multiple. There is deliberately no rupee figure anywhere in the
    rule: a legitimately heavy patient and a caller looping one request are the same
    amount of money, and only the actor's own history separates them, so a cap here
    would either shame the first and miss the second.

    The alert therefore CARRIES both figures. A multiple without them is an
    unfalsifiable claim; ``recent_day_spend_paise`` beside ``baseline_daily_paise``
    is the whole judgement, and an operator reading only the feed can make it.

    The comparison is done at the precision the payload reports
    (:data:`_COST_OUTLIER_QUANTUM`), so a card cannot read ``3.00x`` against a
    ``3.00`` threshold and leave the reader unable to see why it fired. A baseline of
    zero is silence rather than a crash: an alert that takes the nightly pass down
    with it helps nobody.
    """
    if recent_spend_paise <= 0 or baseline.daily_paise <= 0:
        return None
    deviation = (Decimal(recent_spend_paise) / baseline.daily_paise).quantize(_COST_OUTLIER_QUANTUM)
    if deviation <= multiple.quantize(_COST_OUTLIER_QUANTUM):
        return None
    return AlertRow(
        severity=ALERT_SEVERITY_WARNING,
        kind=ALERT_KIND_COST_OUTLIER,
        title=(
            f"AI spend for {actor_kind} {actor_key} on {usage_date} is "
            f"{_ratio_text(deviation)}x its own {baseline.days}-day average"
        ),
        payload={
            "source": _ALERT_SOURCE,
            "actor": actor_alert_scope(actor_kind, actor_key),
            "actor_kind": actor_kind,
            "actor_key": actor_key,
            "usage_date": usage_date.isoformat(),
            "recent_day_spend_paise": recent_spend_paise,
            "baseline_daily_paise": _ratio_text(baseline.daily_paise),
            "baseline_total_paise": baseline.total_paise,
            "baseline_days": baseline.days,
            "deviation_multiple": _ratio_text(deviation),
            "threshold_multiple": _ratio_text(multiple),
        },
    )


@dataclass(frozen=True)
class QueueHealth:
    """One AI queue's still-open work, as the rollup's pure input type (B5 #729).

    ``depth`` is ``enqueued - completed - failed``, counted by the adapter from the
    open-job rows the ``ai_job.queued`` / ``ai_job.completed`` / ``ai_job.failed``
    events produce. ``oldest_enqueued_at`` is the enqueue instant of the oldest job
    still open, and is ``None`` for an empty queue - an empty queue has no oldest
    item, and inventing one would let a healthy idle pipeline raise a stall alert.
    """

    queue: str
    depth: int
    oldest_enqueued_at: datetime | None


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


def evaluate_queue_health_alerts(
    health: QueueHealth, thresholds: RollupThresholds, *, now: datetime
) -> tuple[AlertRow, ...]:
    """The alerts one AI queue's depth and age raise.

    ``now`` is passed in rather than read from the clock so a test can pin the
    instant, which is the only way to assert an AGE without waiting for one.
    """
    if health.oldest_enqueued_at is None:
        return ()
    age = int((now - health.oldest_enqueued_at).total_seconds())
    alert = build_queue_age_alert(
        health.queue,
        oldest_age_seconds=age,
        threshold_seconds=thresholds.queue_age_threshold_seconds,
    )
    return () if alert is None else (alert,)


def evaluate_cost_outlier_alerts(
    history: Sequence[ActorDailySpend],
    thresholds: RollupThresholds,
    *,
    target_date: date,
) -> tuple[AlertRow, ...]:
    """The ``cost_outlier`` alerts one pass raises, one per actor at most.

    ``history`` is the trailing window the adapter read - the day under test plus
    the seven days behind it - and every actor in it is judged against ITSELF. One
    alert per actor rather than per ``(actor, provider, model, task_type)``: the
    question is whether this actor's day is out of character, and splitting the
    figure by scope would hide an abuse that only looks normal once averaged across
    task types.

    No window filter here on purpose: :func:`actor_cost_baseline` bounds its own
    days and the recent figure is ``usage_date == target_date``, so the window is
    stated in exactly one place and the two cannot drift apart. A row outside it
    therefore only costs an actor group that neither test can pass.

    Output is ordered by ``(actor_kind, actor_key)`` so two passes over the same
    rows raise the same alerts in the same order.
    """
    grouped: dict[tuple[ActorKind, str], list[ActorDailySpend]] = {}
    for row in history:
        grouped.setdefault((row.actor_kind, row.actor_key), []).append(row)

    alerts: list[AlertRow] = []
    for (actor_kind, actor_key), rows in sorted(grouped.items()):
        baseline = actor_cost_baseline(rows, thresholds, target_date=target_date)
        if baseline is None:
            continue
        alert = build_cost_outlier_alert(
            actor_kind,
            actor_key,
            recent_spend_paise=sum(row.cost_paise for row in rows if row.usage_date == target_date),
            baseline=baseline,
            multiple=thresholds.cost_outlier_multiple,
            usage_date=target_date,
        )
        if alert is not None:
            alerts.append(alert)
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
    *,
    providers: Sequence[str],
    tables: Sequence[str],
    queues: Sequence[str] = (),
    alerted_queues: Sequence[str] = (),
    actors: Sequence[str] = (),
    alerted_actors: Sequence[str] = (),
) -> set[tuple[str, str]]:
    """Every ``(kind, scope)`` a pass with these inputs could raise.

    The resolve step may only close an open alert this pass actually re-evaluated,
    so absence of evidence never clears a standing condition: a pass that saw no
    traffic for a provider leaves that provider's ``breaker_open`` alert open.

    ``queues`` (what the pass observed) and ``alerted_queues`` (what already carries
    an open ``queue_age`` alert) are UNIONED, and that is the one place this rule is
    deliberately broken. A provider with no rows means "we observed no traffic", which
    is ambiguous; a queue with no open rows means "there is nothing queued", because
    the table's entire content IS the queue. A drained queue has therefore CLEARED its
    age condition, and without the union its alert would stay open forever - the
    standing-problems list polluted by an incident that is over. ``queues`` defaults
    to empty for callers that do not read queue state, and then no queue alert is
    resolved at all.

    ``actors`` are the ``actor_alert_scope`` values of the actors whose trailing
    week this pass read, and ``alerted_actors`` the ones already carrying an open
    ``cost_outlier``. They are UNIONED for the same reason ``queues`` is, and the
    reason is stronger here: an alert is about ONE DAY's figure, and an actor who
    spends nothing for a week leaves the trailing window for good. No later pass can
    ever re-read them, so without the union their alert is not merely un-cleared by
    absence of evidence - it is unreachable, a permanently open row no scheduler can
    ever close. Contrast a provider, which may take traffic again and be re-judged
    from scratch: an actor's spike cannot be un-spiked by later quiet, only ended.
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
    for queue in {*queues, *alerted_queues}:
        keys.add(alert_key(ALERT_KIND_QUEUE_AGE, {"source": _ALERT_SOURCE, "queue": queue}))
    for actor in {*actors, *alerted_actors}:
        keys.add(alert_key(ALERT_KIND_COST_OUTLIER, {"source": _ALERT_SOURCE, "actor": actor}))
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
