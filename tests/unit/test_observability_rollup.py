"""B5a #704: MOD-013 nightly rollup pure core (no DB).

Covers the database-free half of the rollup engine: the percentile estimator,
the success-rate / breaker derivation, the provider-health recompute, the paise
budget snapshot, the five threshold alerts from the minimum alert set
(``error-handling-observability.md`` §5, plan-phase14 §11) and the
``metric_key -> computation`` registry that lets a later phase add a metric
without schema churn. Nothing here opens a connection: the adapter layer
(``modules/observability/rollup.py``) only loads rows and persists what these
functions decide.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from modules.observability.domain import rollup as rollup_module
from modules.observability.domain.consumer import (
    ALERT_SEVERITY_CRITICAL,
    ALERT_SEVERITY_WARNING,
    AlertRow,
)
from modules.observability.domain.rollup import (
    ALERT_KIND_AI_BUDGET,
    ALERT_KIND_AUTH_FAILURE_HIGH,
    ALERT_KIND_BREAKER_OPEN,
    ALERT_KIND_CONSENT_REVOCATION,
    ALERT_KIND_COST_OUTLIER,
    ALERT_KIND_ERROR_RATE_HIGH,
    ALERT_KIND_LATENCY_OBJECTIVE_BREACH,
    ALERT_KIND_OPERATOR_MFA_FAILURE_HIGH,
    ALERT_KIND_OPERATOR_MFA_LOCKOUT,
    ALERT_KIND_OTP_LOCKOUT,
    ALERT_KIND_OUTBOX_BACKLOG,
    ALERT_KIND_OUTBOX_DEAD_LETTER,
    ALERT_KIND_PROMPT_INJECTION_HIGH,
    ALERT_KIND_PROVIDER_HEALTH_DROP,
    ALERT_KIND_PROVIDER_RATE_LIMITED,
    ALERT_KIND_QUEUE_AGE,
    ALERT_KIND_RATE_LIMIT_HIGH,
    ALERT_KIND_RECORD_DENIAL_HIGH,
    ALERT_KIND_WEBHOOK_SIGNATURE_FAILURE,
    BREAKER_STATE_CLOSED,
    BREAKER_STATE_OPEN,
    COST_OUTLIER_BASELINE_DAYS,
    DEFAULT_BREAKER_OPEN_SUCCESS_RATE,
    DEFAULT_COST_OUTLIER_MULTIPLE,
    DEFAULT_DEGRADED_SUCCESS_RATE,
    DEFAULT_ERROR_RATE_MIN_REQUESTS,
    DEFAULT_ERROR_RATE_OBJECTIVE,
    DEFAULT_LATENCY_OBJECTIVE_MS,
    DEFAULT_OUTBOX_BACKLOG_ALERT_THRESHOLD,
    DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD,
    DEFAULT_PROVIDER_RATE_LIMIT_ALERT_COUNT,
    DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS,
    FAILURE_REASON_RATE_LIMITED,
    METRIC_KEY_AI_PROVIDER_HEALTH,
    METRIC_KEY_AI_SPEND,
    NON_RESOLVABLE_ALERT_KINDS,
    PROVIDER_STATUS_DEGRADED,
    PROVIDER_STATUS_DOWN,
    PROVIDER_STATUS_HEALTHY,
    RESOLVABLE_ALERT_KINDS,
    ActorCostBaseline,
    ActorDailySpend,
    ActorSpend,
    AttributionDaily,
    BudgetSnapshot,
    HttpErrorRate,
    OutboxTableHealth,
    ProviderFailures,
    ProviderHealth,
    ProviderUsage,
    QueueHealth,
    RollupMetric,
    RollupThresholds,
    UsageScope,
    actor_alert_scope,
    actor_cost_baseline,
    alert_key,
    alert_kind_resolves,
    alert_marker,
    breaker_state_for,
    budget_period_for,
    build_attribution_daily,
    build_breaker_open_alert,
    build_budget_alert,
    build_budget_snapshot,
    build_cost_outlier_alert,
    build_dead_letter_alert,
    build_error_rate_alert,
    build_latency_objective_breach_alert,
    build_outbox_backlog_alert,
    build_provider_health_drop_alert,
    build_provider_rate_limited_alert,
    build_queue_age_alert,
    compute_provider_health,
    evaluate_budget_alerts,
    evaluate_cost_outlier_alerts,
    evaluate_http_error_rate_alerts,
    evaluate_outbox_health_alerts,
    evaluate_provider_health_alerts,
    evaluate_queue_health_alerts,
    evaluated_alert_keys,
    percentile,
    provider_health_drop,
    provider_status,
    register_rollup_metric,
    rollup_metric_keys,
    rollup_metrics_for,
    success_rate,
    summarize_failures,
    weighted_percentile,
)
from modules.observability.schema.models import observability_attribution_daily

_TARGET_DATE = date(2026, 10, 12)
_WINDOW_START = datetime(2026, 10, 12, tzinfo=UTC)
_WINDOW_END = _WINDOW_START + timedelta(days=1)

#: The instant the queue-age tests measure from. Pinned because an age is the
#: difference between two instants and a test that used the real clock could only
#: ever assert "roughly now".
_QUEUE_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

_PHI_KEYS = ("phone", "otp", "email", "name", "transcript", "patient", "text", "reason")


def _day(offset: int, cost_paise: int, *, actor_key: str = "actor-a") -> ActorDailySpend:
    """One actor-day of spend, ``offset`` days before :data:`_TARGET_DATE`."""
    return ActorDailySpend(
        actor_kind="patient",
        actor_key=actor_key,
        usage_date=_TARGET_DATE - timedelta(days=offset),
        cost_paise=cost_paise,
    )


def _trailing(
    *daily_costs: int, recent: int = 100, actor_key: str = "actor-a"
) -> list[ActorDailySpend]:
    """An actor's trailing days, then the day under test.

    ``daily_costs`` are the days BEHIND :data:`_TARGET_DATE`, oldest first, and
    ``recent`` is the target day itself. Only the days listed count as spend days -
    a day not listed is an actor who spent nothing, which is what makes the baseline
    a mean over observed days rather than a mean over the calendar.
    """
    days = len(daily_costs)
    return [
        *(
            _day(days - offset, cost, actor_key=actor_key)
            for offset, cost in enumerate(daily_costs)
        ),
        _day(0, recent, actor_key=actor_key),
    ]


def _scope(
    *,
    model: str = "mock-model",
    task_type: str = "summarize",
    calls: int = 4,
    success: int = 4,
    failure: int = 0,
    timeout: int = 0,
    cost: int = 1_000,
    avg: Decimal | None = Decimal("100.00"),
) -> UsageScope:
    return UsageScope(
        model=model,
        task_type=task_type,
        calls=calls,
        success_count=success,
        failure_count=failure,
        timeout_count=timeout,
        cost_paise=cost,
        avg_duration_ms=avg,
    )


def _usage(provider: str = "openai", *scopes: UsageScope) -> ProviderUsage:
    return ProviderUsage(provider=provider, scopes=scopes or (_scope(),))


def _health(usage: ProviderUsage | None = None) -> ProviderHealth:
    usage = usage or _usage()
    return compute_provider_health(usage.provider, _WINDOW_START, _WINDOW_END, usage)


def _budget(**kwargs: object) -> BudgetSnapshot:
    defaults: dict[str, object] = {
        "provider": "openai",
        "model": "mock-model",
        "spend_paise": 100_000,
        "monthly_limit_paise": 200_000,
        "period_start": date(2026, 10, 1),
        "period_end": date(2026, 10, 31),
    }
    return build_budget_snapshot(**{**defaults, **kwargs})


def _rate_limited_health(provider: str = "openai", *, rate_limit_count: int) -> ProviderHealth:
    """A provider's health for a day it was refused ``rate_limit_count`` times."""
    return compute_provider_health(
        provider,
        _WINDOW_START,
        _WINDOW_END,
        _usage(provider, _scope(calls=20, success=18, failure=2)),
        failures=ProviderFailures(rate_limit_count=rate_limit_count, last_error=None),
    )


def _slow_health(provider: str = "openai", *, p95_ms: Decimal) -> ProviderHealth:
    """A provider's health for a day whose calls came back slower than the objective."""
    return compute_provider_health(
        provider,
        _WINDOW_START,
        _WINDOW_END,
        _usage(provider, _scope(calls=20, success=20, avg=p95_ms)),
    )


def _volume(requests: int, errors: int) -> HttpErrorRate:
    """One rolled day of the platform's own request counter, over the test window."""
    return HttpErrorRate(
        requests=requests,
        errors=errors,
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
    )


def _thresholds(**kwargs: object) -> RollupThresholds:
    """Default thresholds, with the alert knobs a test wants to move overridden."""
    return RollupThresholds(monthly_budget_paise=200_000, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------- percentiles


def test_percentile_interpolates_between_closest_ranks() -> None:
    """The median of an even sample sits halfway between the two middle values."""
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == pytest.approx(25.0)
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.0) == pytest.approx(10.0)
    assert percentile([10.0, 20.0, 30.0, 40.0], 1.0) == pytest.approx(40.0)
    assert percentile([7.0], 0.95) == pytest.approx(7.0)


def test_percentile_returns_none_for_an_empty_sample() -> None:
    """No observations means no percentile - the column stays NULL."""
    assert percentile([], 0.5) is None
    assert percentile([], 0.95) is None


@pytest.mark.parametrize("fraction", [-0.1, 1.1, 1.5])
def test_percentile_rejects_a_fraction_outside_the_unit_interval(fraction: float) -> None:
    with pytest.raises(ValueError, match="fraction"):
        percentile([1.0, 2.0], fraction)


def test_weighted_percentile_matches_the_expansion_of_the_same_sample() -> None:
    """Weighting is the repeated-observation percentile, not an approximation."""
    points = [(100.0, 3), (500.0, 1)]
    assert weighted_percentile(points, 0.5) == pytest.approx(
        percentile([100.0, 100.0, 100.0, 500.0], 0.5)
    )
    assert weighted_percentile(points, 0.95) == pytest.approx(
        percentile([100.0, 100.0, 100.0, 500.0], 0.95)
    )


def test_weighted_percentile_is_none_when_every_weight_is_zero() -> None:
    assert weighted_percentile([(100.0, 0), (200.0, 0)], 0.5) is None
    assert weighted_percentile([], 0.5) is None


# ------------------------------------------------------- success rate / breaker


def test_success_rate_is_a_four_decimal_fraction() -> None:
    assert success_rate(3, 4) == Decimal("0.7500")
    assert success_rate(0, 4) == Decimal("0.0000")
    assert success_rate(4, 4) == Decimal("1.0000")


def test_success_rate_is_none_without_calls() -> None:
    assert success_rate(0, 0) is None


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (Decimal("0.4999"), BREAKER_STATE_OPEN),
        (Decimal("0.5000"), BREAKER_STATE_CLOSED),
        (None, BREAKER_STATE_CLOSED),
    ],
)
def test_breaker_state_follows_the_configured_success_rate_floor(
    rate: Decimal | None, expected: str
) -> None:
    """No traffic means a closed breaker; only observed failure opens it."""
    assert breaker_state_for(rate, open_below=DEFAULT_BREAKER_OPEN_SUCCESS_RATE) == expected


# ------------------------------------------------------------- provider health


def test_compute_provider_health_aggregates_scopes_into_percentiles() -> None:
    """The per-scope means are weighted by their completion counts, then ranked."""
    usage = _usage(
        "openai",
        _scope(calls=3, success=3, avg=Decimal("100.00")),
        _scope(
            model="gpt-4o-mini",
            task_type="suggest",
            calls=1,
            success=1,
            avg=Decimal("400.00"),
        ),
    )

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert health.provider == "openai"
    assert health.sample_count == 4
    assert health.success_rate == Decimal("1.0000")
    # 100 ms x3 and 400 ms x1: rank 1.5 -> 100.00, rank 2.85 -> 355.00, 2.97 -> 391.00.
    assert health.p50_duration_ms == Decimal("100.00")
    assert health.p95_duration_ms == Decimal("355.00")
    assert health.p99_duration_ms == Decimal("391.00")
    assert health.breaker_state == BREAKER_STATE_CLOSED


def test_compute_provider_health_counts_failures_in_the_rate_not_the_latency() -> None:
    """Durations are only recorded for completions, so failures move the rate alone."""
    usage = _usage(
        "openai",
        _scope(calls=10, success=5, failure=4, timeout=1, avg=Decimal("200.00")),
    )

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert health.success_rate == Decimal("0.5000")
    assert health.sample_count == 5
    assert health.breaker_state == BREAKER_STATE_CLOSED


def test_compute_provider_health_opens_the_breaker_on_observed_failures() -> None:
    usage = _usage("openai", _scope(calls=10, success=2, failure=8, avg=Decimal("200.00")))

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert health.success_rate == Decimal("0.2000")
    assert health.breaker_state == BREAKER_STATE_OPEN


def test_compute_provider_health_leaves_percentiles_null_without_completions() -> None:
    """A day of pure failures has no duration distribution to rank."""
    usage = _usage("openai", _scope(calls=3, success=0, failure=3, avg=None))

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert health.sample_count == 0
    assert health.success_rate == Decimal("0.0000")
    assert health.p50_duration_ms is None
    assert health.p95_duration_ms is None
    assert health.p99_duration_ms is None


def test_provider_health_drop_is_the_signed_delta_between_two_rates() -> None:
    assert provider_health_drop(Decimal("1.0000"), Decimal("0.6000")) == Decimal("0.4000")
    assert provider_health_drop(Decimal("0.6000"), Decimal("1.0000")) == Decimal("-0.4000")
    # No prior reading (or nothing to compare) is not a drop.
    assert provider_health_drop(None, Decimal("0.6000")) is None
    assert provider_health_drop(Decimal("1.0000"), None) is None


# ------------------------------------------- B9 #728: the named provider board


def test_summarize_failures_counts_quota_refusals_and_names_the_newest() -> None:
    """The order the loader hands over IS the recency order, newest first."""
    failures = summarize_failures(
        [
            FAILURE_REASON_RATE_LIMITED,
            "Ext002CallError",
            FAILURE_REASON_RATE_LIMITED,
        ]
    )

    assert failures.rate_limit_count == 2
    assert failures.last_error == FAILURE_REASON_RATE_LIMITED


def test_summarize_failures_names_a_non_quota_failure_without_counting_it() -> None:
    """A refusal is not the only failure; the newest reason is still worth naming."""
    failures = summarize_failures(["ConnectError", FAILURE_REASON_RATE_LIMITED, "ValueError"])

    assert failures.rate_limit_count == 1
    assert failures.last_error == "ConnectError"


def test_summarize_failures_skips_absent_reasons_and_reports_nothing_to_name() -> None:
    """A failed job whose producer gave no reason must not become the named error."""
    failures = summarize_failures([None, None, "TimeoutError"])

    assert failures.rate_limit_count == 0
    assert failures.last_error == "TimeoutError"
    assert summarize_failures([]) == ProviderFailures(0, None)
    assert summarize_failures([None, None]) == ProviderFailures(0, None)


def test_compute_provider_health_rolls_the_timeouts_and_named_failures_up() -> None:
    """The two previously-unwritten columns are filled from the day's own rows."""
    usage = _usage("openai", _scope(calls=10, success=8, failure=1, timeout=1))

    health = compute_provider_health(
        "openai",
        _WINDOW_START,
        _WINDOW_END,
        usage,
        failures=ProviderFailures(3, FAILURE_REASON_RATE_LIMITED),
    )

    assert health.timeout_count == 1
    assert health.rate_limit_count == 3
    assert health.last_error == FAILURE_REASON_RATE_LIMITED


def test_compute_provider_health_defaults_the_failure_columns_for_a_clean_day() -> None:
    """No ``failures`` means "none observed", not "the provider has never failed"."""
    usage = _usage("openai", _scope(calls=4, success=4))

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert (health.timeout_count, health.rate_limit_count, health.last_error) == (0, 0, None)


def test_provider_status_is_healthy_for_a_clean_window() -> None:
    usage = _usage("openai", _scope(calls=20, success=20))

    assert (
        provider_status(compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage))
        == PROVIDER_STATUS_HEALTHY
    )


def test_provider_status_is_healthy_for_a_provider_with_no_traffic_at_all() -> None:
    """Idle is not broken: an absent sample is never evidence of a failure."""
    health = compute_provider_health(
        "openai", _WINDOW_START, _WINDOW_END, _usage("openai", _scope(calls=0, success=0))
    )

    assert health.success_rate is None
    assert health.breaker_state == BREAKER_STATE_CLOSED
    assert provider_status(health) == PROVIDER_STATUS_HEALTHY


def test_provider_status_is_down_when_the_breaker_is_open() -> None:
    usage = _usage("openai", _scope(calls=10, success=2, failure=8))

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert health.breaker_state == BREAKER_STATE_OPEN
    assert provider_status(health) == PROVIDER_STATUS_DOWN


def test_provider_status_is_down_when_not_one_call_succeeded() -> None:
    """The case the brief calls out: traffic recorded, nothing succeeded.

    ``success_rate`` is a real ``0.0000`` and every percentile is NULL behind it,
    because there was no completion to time. Reading that as "no data" would
    report an outage as silence - which is precisely the bug the board exists to
    stop.

    The row is built through ``compute_provider_health`` and the breaker state is
    then patched to disagree with the stored rate, so the assertion is that the
    stored state wins: a provider whose stored breaker state and stored rate
    disagree must still resolve to down.
    """
    usage = _usage("openai", _scope(calls=3, success=0, failure=3, avg=None))

    rolled = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert rolled.success_rate == Decimal("0.0000")
    assert (rolled.p50_duration_ms, rolled.p95_duration_ms, rolled.p99_duration_ms) == (
        None,
        None,
        None,
    )
    assert provider_status(rolled) == PROVIDER_STATUS_DOWN

    # The same row with its breaker not tripped - the rate alone still says down.
    breaker_had_not_tripped = replace(rolled, breaker_state=BREAKER_STATE_CLOSED)
    assert provider_status(breaker_had_not_tripped) == PROVIDER_STATUS_DOWN


def test_provider_status_is_degraded_on_a_single_quota_refusal() -> None:
    """One refusal among many successes degrades the provider; it does not down it."""
    usage = _usage("openai", _scope(calls=100, success=99, failure=1))

    health = compute_provider_health(
        "openai",
        _WINDOW_START,
        _WINDOW_END,
        usage,
        failures=ProviderFailures(1, FAILURE_REASON_RATE_LIMITED),
    )

    assert health.success_rate == Decimal("0.9900")
    assert provider_status(health) == PROVIDER_STATUS_DEGRADED


def test_provider_status_is_degraded_on_a_timeout() -> None:
    usage = _usage("openai", _scope(calls=100, success=99, timeout=1))

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert health.timeout_count == 1
    assert provider_status(health) == PROVIDER_STATUS_DEGRADED


def test_provider_status_is_degraded_just_below_the_success_threshold() -> None:
    usage = _usage("openai", _scope(calls=10, success=9, failure=1))

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    # Exactly at the threshold, not merely under it: the boundary is inclusive, so a
    # provider sitting precisely on it reads degraded rather than healthy.
    assert health.success_rate == Decimal("0.9000")
    assert health.success_rate == DEFAULT_DEGRADED_SUCCESS_RATE
    assert provider_status(health) == PROVIDER_STATUS_DEGRADED


def test_provider_status_is_healthy_just_above_the_success_threshold() -> None:
    """The other side of the same boundary, so the line is pinned from both ends."""
    usage = _usage("openai", _scope(calls=1000, success=901, failure=99))

    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, usage)

    assert health.success_rate == Decimal("0.9010")
    assert provider_status(health) == PROVIDER_STATUS_HEALTHY


def test_provider_status_does_not_let_a_single_named_error_outrank_the_counters() -> None:
    """One call's word never outweighs every other call succeeding.

    The named error is what an operator READS once the status has told them to
    look. If it drove the status, a provider that was refused once and served
    everything else would read as an outage.
    """
    usage = _usage("openai", _scope(calls=1000, success=1000, failure=0, timeout=0))

    health = compute_provider_health(
        "openai",
        _WINDOW_START,
        _WINDOW_END,
        usage,
        failures=ProviderFailures(0, "ConnectError"),
    )

    assert health.last_error == "ConnectError"
    assert provider_status(health) == PROVIDER_STATUS_HEALTHY


def test_the_two_alert_vocabularies_are_disjoint_and_cover_every_rollup_kind() -> None:
    """The never-auto-resolve rule is DATA, so "tidying it up" fails a test.

    Read as an omission next to :data:`RESOLVABLE_ALERT_KINDS`, adding
    ``provider_health_drop`` to that set looks like completing the vocabulary - and
    silently makes a degraded provider disappear the moment it recovers.
    """
    every_kind = {
        ALERT_KIND_AI_BUDGET,
        ALERT_KIND_PROVIDER_HEALTH_DROP,
        ALERT_KIND_BREAKER_OPEN,
        ALERT_KIND_OUTBOX_BACKLOG,
        ALERT_KIND_OUTBOX_DEAD_LETTER,
        ALERT_KIND_QUEUE_AGE,
        ALERT_KIND_COST_OUTLIER,
        ALERT_KIND_ERROR_RATE_HIGH,
        ALERT_KIND_PROVIDER_RATE_LIMITED,
        ALERT_KIND_LATENCY_OBJECTIVE_BREACH,
        ALERT_KIND_AUTH_FAILURE_HIGH,
        ALERT_KIND_OPERATOR_MFA_FAILURE_HIGH,
        ALERT_KIND_RECORD_DENIAL_HIGH,
        ALERT_KIND_RATE_LIMIT_HIGH,
        ALERT_KIND_PROMPT_INJECTION_HIGH,
        ALERT_KIND_OTP_LOCKOUT,
        ALERT_KIND_OPERATOR_MFA_LOCKOUT,
        ALERT_KIND_CONSENT_REVOCATION,
        ALERT_KIND_WEBHOOK_SIGNATURE_FAILURE,
    }

    assert not RESOLVABLE_ALERT_KINDS & NON_RESOLVABLE_ALERT_KINDS
    assert every_kind == RESOLVABLE_ALERT_KINDS | NON_RESOLVABLE_ALERT_KINDS
    assert ALERT_KIND_PROVIDER_HEALTH_DROP in NON_RESOLVABLE_ALERT_KINDS
    # A stalled queue drains and then stops being an alert (B5 #729), so unlike a
    # provider health DROP it belongs to the resolvable half. Stated here because the
    # kind would otherwise sit in that set for the same reason it was left out of the
    # other one - by not being thought about.
    assert alert_kind_resolves(ALERT_KIND_QUEUE_AGE)
    # A one-day spend spike is the same shape of thing (B7 #733): it either repeats or
    # it does not, and an alert nobody can see close is one nobody clears by hand.
    assert alert_kind_resolves(ALERT_KIND_COST_OUTLIER)
    # The three kinds #734 adds. Each is a figure that comes back DOWN when the
    # condition clears, which is the whole test of whether it belongs in the
    # resolvable half: quota refusals stop, the 5xx share falls, a provider speeds up.
    for kind in (
        ALERT_KIND_ERROR_RATE_HIGH,
        ALERT_KIND_PROVIDER_RATE_LIMITED,
        ALERT_KIND_LATENCY_OBJECTIVE_BREACH,
        ALERT_KIND_AUTH_FAILURE_HIGH,
        ALERT_KIND_OPERATOR_MFA_FAILURE_HIGH,
        ALERT_KIND_RECORD_DENIAL_HIGH,
        ALERT_KIND_RATE_LIMIT_HIGH,
        ALERT_KIND_PROMPT_INJECTION_HIGH,
    ):
        assert alert_kind_resolves(kind), kind


def test_the_auto_resolve_policy_is_explicit_about_every_kind() -> None:
    """Which kinds close themselves and which must be closed by hand, named.

    The policy is two sentences an operator depends on: "the open list clears itself
    when the condition clears" and "a provider that went bad stays on the board".
    Which kind sits in which half is the whole content of those sentences, so it is
    asserted kind by kind here rather than left to be read out of two frozensets.
    """
    # Standing conditions: a level that returns to normal.
    for kind in (
        ALERT_KIND_AI_BUDGET,
        ALERT_KIND_OUTBOX_BACKLOG,
        ALERT_KIND_OUTBOX_DEAD_LETTER,
        ALERT_KIND_QUEUE_AGE,
        ALERT_KIND_BREAKER_OPEN,
        ALERT_KIND_COST_OUTLIER,
        ALERT_KIND_ERROR_RATE_HIGH,
        ALERT_KIND_PROVIDER_RATE_LIMITED,
        ALERT_KIND_LATENCY_OBJECTIVE_BREACH,
        ALERT_KIND_AUTH_FAILURE_HIGH,
        ALERT_KIND_OPERATOR_MFA_FAILURE_HIGH,
        ALERT_KIND_RECORD_DENIAL_HIGH,
        ALERT_KIND_RATE_LIMIT_HIGH,
        ALERT_KIND_PROMPT_INJECTION_HIGH,
    ):
        assert kind in RESOLVABLE_ALERT_KINDS, kind
        assert kind not in NON_RESOLVABLE_ALERT_KINDS, kind

    # The exceptions, and the reason the deny-set exists at all.
    assert {
        ALERT_KIND_PROVIDER_HEALTH_DROP,
        ALERT_KIND_OTP_LOCKOUT,
        ALERT_KIND_OPERATOR_MFA_LOCKOUT,
        ALERT_KIND_CONSENT_REVOCATION,
        ALERT_KIND_WEBHOOK_SIGNATURE_FAILURE,
    } == NON_RESOLVABLE_ALERT_KINDS
    for kind in NON_RESOLVABLE_ALERT_KINDS:
        assert not alert_kind_resolves(kind), kind


def test_the_resolve_step_reads_both_vocabularies_and_unknown_kinds_resolve_to_nothing() -> None:
    """The resolve step answers one question, from both sets rather than one.

    :data:`RESOLVABLE_ALERT_KINDS` alone would leave the never-auto-resolve rule
    living only in an absence, so the deny-list is read as well; and an unclassified
    kind resolves to nothing rather than defaulting to yes, which is what makes
    adding a new kind a deliberate act.
    """
    assert not alert_kind_resolves(ALERT_KIND_PROVIDER_HEALTH_DROP)
    for kind in (ALERT_KIND_AI_BUDGET, ALERT_KIND_BREAKER_OPEN):
        assert alert_kind_resolves(kind)
    assert not alert_kind_resolves("a_kind_from_a_future_batch")


# --------------------------------------------------------------------- budget


def test_budget_period_for_is_the_calendar_month_containing_the_target_date() -> None:
    assert budget_period_for(date(2026, 10, 12)) == (date(2026, 10, 1), date(2026, 10, 31))
    assert budget_period_for(date(2026, 2, 3)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert budget_period_for(date(2024, 2, 3)) == (date(2024, 2, 1), date(2024, 2, 29))


def test_budget_snapshot_reports_paise_remaining_and_utilisation() -> None:
    snapshot = _budget(spend_paise=160_000)

    assert snapshot.current_spend_paise == 160_000
    assert snapshot.monthly_limit_paise == 200_000
    assert snapshot.remaining_paise == 40_000
    assert snapshot.utilization_pct == Decimal("80.00")
    # 80% of the cap is not past it - the alert fires STRICTLY above.
    assert snapshot.exhausted is False


def test_budget_snapshot_never_reports_negative_remaining() -> None:
    snapshot = _budget(spend_paise=250_000)

    assert snapshot.remaining_paise == 0
    assert snapshot.utilization_pct == Decimal("125.00")
    assert snapshot.exhausted is True


def test_budget_snapshot_rejects_a_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="monthly_limit_paise"):
        _budget(monthly_limit_paise=0)


# --------------------------------------------------------------------- alerts


def _budget_alert(total_spend_paise: int, *, monthly_limit_paise: int = 200_000) -> AlertRow:
    """The month's total-budget alert, exactly as the pass raises it."""
    return build_budget_alert(
        total_spend_paise,
        monthly_limit_paise=monthly_limit_paise,
        threshold_pct=80,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
    )


def test_budget_alert_reports_the_months_totals_with_a_phi_free_payload() -> None:
    alert = _budget_alert(170_000)

    assert alert.severity == ALERT_SEVERITY_WARNING
    assert alert.kind == ALERT_KIND_AI_BUDGET
    assert "80%" in alert.title
    assert alert.payload == {
        "source": "rollup",
        "scope": "monthly_total",
        "current_spend_paise": 170_000,
        "monthly_limit_paise": 200_000,
        "alert_threshold_pct": 80,
        "utilization_pct": "85.00",
        "billing_period_start": "2026-10-01",
        "billing_period_end": "2026-10-31",
    }


def test_budget_alert_is_a_critical_once_the_cap_is_reached() -> None:
    assert _budget_alert(220_000).severity == ALERT_SEVERITY_CRITICAL


def test_budget_alert_is_evaluated_on_the_month_total_not_per_scope() -> None:
    """One cap, one alert: three scopes each under 80% still breach the month's cap."""
    thresholds = RollupThresholds(monthly_budget_paise=100_000)
    per_scope = [_budget(spend_paise=30_000, monthly_limit_paise=100_000) for _ in range(3)]
    assert not any(snapshot.exhausted for snapshot in per_scope)

    alerts = evaluate_budget_alerts(
        sum(snapshot.current_spend_paise for snapshot in per_scope),
        thresholds,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
    )

    assert [alert.kind for alert in alerts] == [ALERT_KIND_AI_BUDGET]
    assert alerts[0].payload["current_spend_paise"] == 90_000


def test_budget_alert_stays_silent_exactly_at_the_threshold() -> None:
    """ "AI budget meter > 80%" - at 80% of the cap there is nothing to say."""
    thresholds = RollupThresholds(monthly_budget_paise=100_000)

    at_threshold = evaluate_budget_alerts(
        80_000, thresholds, period_start=date(2026, 10, 1), period_end=date(2026, 10, 31)
    )
    past_threshold = evaluate_budget_alerts(
        80_001, thresholds, period_start=date(2026, 10, 1), period_end=date(2026, 10, 31)
    )

    assert at_threshold == ()
    assert len(past_threshold) == 1


def test_health_drop_alert_fires_only_past_the_configured_drop() -> None:
    health = compute_provider_health(
        "openai",
        _WINDOW_START,
        _WINDOW_END,
        _usage("openai", _scope(calls=10, success=8, failure=2)),
    )

    small = build_provider_health_drop_alert(
        health, Decimal("0.8500"), drop_threshold=Decimal("0.2")
    )
    large = build_provider_health_drop_alert(
        health, Decimal("1.0000"), drop_threshold=DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD
    )

    assert small is None
    assert large is not None
    assert large.kind == ALERT_KIND_PROVIDER_HEALTH_DROP
    assert large.severity == ALERT_SEVERITY_WARNING
    assert large.payload["provider"] == "openai"
    assert large.payload["previous_success_rate"] == "1.0000"
    assert large.payload["success_rate"] == "0.8000"
    assert large.payload["success_rate_drop"] == "0.2000"


def test_health_drop_alert_stays_silent_without_a_prior_reading() -> None:
    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, _usage())

    assert (
        build_provider_health_drop_alert(
            health, None, drop_threshold=DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD
        )
        is None
    )


def test_breaker_alert_is_critical_and_carries_the_observed_rate() -> None:
    health = compute_provider_health(
        "openai",
        _WINDOW_START,
        _WINDOW_END,
        _usage("openai", _scope(calls=4, success=1, failure=3)),
    )

    alerts = evaluate_provider_health_alerts(
        health, previous_success_rate=None, thresholds=RollupThresholds(monthly_budget_paise=1)
    )

    assert [alert.kind for alert in alerts] == [ALERT_KIND_BREAKER_OPEN]
    breaker = alerts[0]
    assert breaker.severity == ALERT_SEVERITY_CRITICAL
    assert breaker.payload["breaker_state"] == BREAKER_STATE_OPEN
    assert breaker.payload["success_rate"] == "0.2500"


def test_provider_health_alerts_are_silent_while_the_breaker_is_closed() -> None:
    health = compute_provider_health("openai", _WINDOW_START, _WINDOW_END, _usage())

    assert (
        evaluate_provider_health_alerts(
            health,
            previous_success_rate=Decimal("1.0000"),
            thresholds=RollupThresholds(monthly_budget_paise=1),
        )
        == ()
    )


def test_outbox_backlog_alert_fires_only_past_the_threshold() -> None:
    healthy = OutboxTableHealth(schema="intake", table="intake_outbox", pending=5)
    backed_up = OutboxTableHealth(
        schema="intake", table="intake_outbox", pending=DEFAULT_OUTBOX_BACKLOG_ALERT_THRESHOLD + 1
    )

    quiet = evaluate_outbox_health_alerts(
        healthy, thresholds=RollupThresholds(monthly_budget_paise=1)
    )
    loud = evaluate_outbox_health_alerts(
        backed_up, thresholds=RollupThresholds(monthly_budget_paise=1)
    )

    assert quiet == ()
    assert [alert.kind for alert in loud] == [ALERT_KIND_OUTBOX_BACKLOG]
    assert loud[0].severity == ALERT_SEVERITY_WARNING
    assert loud[0].payload["table"] == "intake.intake_outbox"
    assert loud[0].payload["backlog"] == DEFAULT_OUTBOX_BACKLOG_ALERT_THRESHOLD + 1


def test_dead_letter_alert_is_critical_and_names_only_the_table() -> None:
    health = OutboxTableHealth(schema="care", table="care_outbox", dead_letter=3, pending=0)

    alerts = evaluate_outbox_health_alerts(
        health, thresholds=RollupThresholds(monthly_budget_paise=1)
    )

    assert [alert.kind for alert in alerts] == [ALERT_KIND_OUTBOX_DEAD_LETTER]
    assert alerts[0].severity == ALERT_SEVERITY_CRITICAL
    assert alerts[0].payload == {
        "source": "rollup",
        "table": "care.care_outbox",
        "dead_letter_count": 3,
    }


def test_build_outbox_backlog_alert_is_a_direct_builder_for_one_table() -> None:
    alert = build_outbox_backlog_alert("intake.intake_outbox", backlog=12, threshold=10)

    assert alert is not None
    assert alert.kind == ALERT_KIND_OUTBOX_BACKLOG
    assert alert.payload["backlog"] == 12
    assert build_outbox_backlog_alert("intake.intake_outbox", backlog=10, threshold=10) is None


def test_build_dead_letter_alert_is_critical() -> None:
    alert = build_dead_letter_alert("care.care_outbox", dead_letter_count=1)

    assert alert.severity == ALERT_SEVERITY_CRITICAL
    assert alert.kind == ALERT_KIND_OUTBOX_DEAD_LETTER


# ------------------------------------------------------------------- queue age


def _queue(queue: str, *, depth: int, oldest_age_s: int | None) -> QueueHealth:
    """A queue whose oldest open job entered ``oldest_age_s`` seconds before now."""
    enqueued_at = None if oldest_age_s is None else _QUEUE_NOW - timedelta(seconds=oldest_age_s)
    return QueueHealth(queue=queue, depth=depth, oldest_enqueued_at=enqueued_at)


def test_queue_age_alert_fires_on_a_single_wedged_job_the_depth_alert_cannot_see() -> None:
    """The whole point of the kind: age leads, depth lags (#729).

    A depth of ONE - far below the five-hundred-row backlog threshold - is all a
    queue holding a single stalled job ever reaches. If the stall had to be
    measured in depth it would never alert at all.
    """
    thresholds = RollupThresholds(monthly_budget_paise=1)

    assert (
        evaluate_outbox_health_alerts(
            OutboxTableHealth(schema="intake", table="intake_outbox", pending=1),
            thresholds,
        )
        == ()
    )

    alerts = evaluate_queue_health_alerts(
        _queue("structure", depth=1, oldest_age_s=3_600), thresholds, now=_QUEUE_NOW
    )

    assert [alert.kind for alert in alerts] == [ALERT_KIND_QUEUE_AGE]
    assert alerts[0].severity == ALERT_SEVERITY_CRITICAL
    assert alerts[0].payload == {
        "source": "rollup",
        "queue": "structure",
        "oldest_age_seconds": 3_600,
        "threshold_seconds": DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS,
    }
    # The alert NAMES its queue, so a stalled structuring leg is identifiable
    # rather than averaged into a single pipeline-wide figure.
    assert "structure" in alerts[0].title


def test_queue_age_alert_stays_quiet_at_or_below_the_threshold_and_on_an_empty_queue() -> None:
    thresholds = RollupThresholds(monthly_budget_paise=1)
    at_threshold = DEFAULT_QUEUE_AGE_ALERT_THRESHOLD_SECONDS

    assert (
        evaluate_queue_health_alerts(
            _queue("draft", depth=4, oldest_age_s=at_threshold), thresholds, now=_QUEUE_NOW
        )
        == ()
    )
    assert (
        evaluate_queue_health_alerts(
            _queue("draft", depth=1, oldest_age_s=at_threshold + 1), thresholds, now=_QUEUE_NOW
        )
        != ()
    )
    # An idle pipeline is healthy: with nothing open there is no oldest item, and
    # inventing one would alert on every quiet night.
    assert (
        evaluate_queue_health_alerts(
            _queue("draft", depth=0, oldest_age_s=None), thresholds, now=_QUEUE_NOW
        )
        == ()
    )


def test_queue_age_threshold_is_configurable_and_must_be_positive() -> None:
    tight = RollupThresholds(monthly_budget_paise=1, queue_age_threshold_seconds=60)

    assert (
        evaluate_queue_health_alerts(
            _queue("transcribe", depth=1, oldest_age_s=120), tight, now=_QUEUE_NOW
        )
        != ()
    )
    with pytest.raises(ValueError, match="queue_age_threshold_seconds"):
        RollupThresholds(monthly_budget_paise=1, queue_age_threshold_seconds=0)


def test_a_drained_queue_is_still_evaluated_because_an_empty_open_set_clears_it() -> None:
    """``alerted_queues`` re-admits a queue this pass no longer sees.

    A queue's rows ARE the queue, so "no open rows" is a positive statement that
    nothing is waiting - the one condition where absence resolves rather than holds.
    Without the union, a single wedged job's alert would stay open for ever after the
    job finished, and the standing-problems list would only ever grow.
    """
    observed = evaluated_alert_keys(providers=[], tables=[], queues=["draft"])
    drained = evaluated_alert_keys(
        providers=[], tables=[], queues=["draft"], alerted_queues=["structure"]
    )

    # The union adds exactly one key: the drained queue's, and nothing else moves.
    assert drained - observed == {
        alert_key(ALERT_KIND_QUEUE_AGE, {"source": "rollup", "queue": "structure"})
    }
    assert observed - drained == set()


@pytest.mark.parametrize(
    "alert",
    [
        _budget_alert(170_000),
        build_breaker_open_alert(
            compute_provider_health(
                "openai",
                _WINDOW_START,
                _WINDOW_END,
                _usage("openai", _scope(calls=4, success=1, failure=3)),
            )
        ),
        build_dead_letter_alert("care.care_outbox", dead_letter_count=2),
        build_outbox_backlog_alert("intake.intake_outbox", backlog=99, threshold=10),
        build_provider_health_drop_alert(
            compute_provider_health(
                "openai",
                _WINDOW_START,
                _WINDOW_END,
                _usage("openai", _scope(calls=10, success=8, failure=2)),
            ),
            Decimal("1.0000"),
            drop_threshold=DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD,
        ),
        build_queue_age_alert("structure", oldest_age_seconds=3_600, threshold_seconds=900),
        build_provider_rate_limited_alert(
            _rate_limited_health(rate_limit_count=3),
            threshold=DEFAULT_PROVIDER_RATE_LIMIT_ALERT_COUNT,
        ),
        build_latency_objective_breach_alert(
            _slow_health(p95_ms=Decimal("45000.00")), objective_ms=DEFAULT_LATENCY_OBJECTIVE_MS
        ),
        build_error_rate_alert(
            _volume(1_000, 40),
            objective=DEFAULT_ERROR_RATE_OBJECTIVE,
            min_requests=DEFAULT_ERROR_RATE_MIN_REQUESTS,
        ),
        build_cost_outlier_alert(
            "patient",
            "actor-a",
            recent_spend_paise=90_000,
            baseline=actor_cost_baseline(
                _trailing(1_000, 1_000, 1_000),
                RollupThresholds(monthly_budget_paise=200_000),
                target_date=_TARGET_DATE,
            ),
            multiple=DEFAULT_COST_OUTLIER_MULTIPLE,
            usage_date=_TARGET_DATE,
        ),
    ],
)
def test_every_rollup_alert_payload_is_phi_free(alert: AlertRow) -> None:
    """error-handling-observability §5: no PHI in an alert payload."""
    payload = alert.payload
    assert set(payload) <= {
        "source",
        "scope",
        "provider",
        "model",
        "current_spend_paise",
        "monthly_limit_paise",
        "alert_threshold_pct",
        "utilization_pct",
        "billing_period_start",
        "billing_period_end",
        "success_rate",
        "previous_success_rate",
        "success_rate_drop",
        "breaker_state",
        "window_start",
        "window_end",
        "table",
        "backlog",
        "dead_letter_count",
        "queue",
        "oldest_age_seconds",
        "threshold_seconds",
        "actor",
        "actor_kind",
        "actor_key",
        "usage_date",
        "recent_day_spend_paise",
        "baseline_daily_paise",
        "baseline_total_paise",
        "baseline_days",
        "deviation_multiple",
        "threshold_multiple",
        "rate_limit_count",
        "threshold_count",
        "p95_duration_ms",
        "objective_ms",
        "sample_count",
        "requests",
        "errors",
        "error_rate",
        "objective",
        "min_requests",
    }
    for key in _PHI_KEYS:
        assert key not in payload


# ------------------------------------------------------------------- registry


def test_rollup_registry_covers_the_registered_metrics() -> None:
    keys = rollup_metric_keys()

    assert METRIC_KEY_AI_PROVIDER_HEALTH in keys
    assert METRIC_KEY_AI_SPEND in keys


def test_rollup_metrics_project_one_generic_store_row_per_registered_metric() -> None:
    """Every registry entry lands in observability_business_daily keyed by metric_key."""
    usage = _usage(
        "openai", _scope(calls=10, success=9, failure=1, cost=2_500, avg=Decimal("150.00"))
    )
    health = compute_provider_health(usage.provider, _WINDOW_START, _WINDOW_END, usage)

    rows = rollup_metrics_for(usage, health)

    assert [row.metric_key for row in rows] == [
        f"{METRIC_KEY_AI_PROVIDER_HEALTH}.openai",
        f"{METRIC_KEY_AI_SPEND}.openai",
    ]
    health_value = rows[0].value
    assert health_value["provider"] == "openai"
    assert health_value["success_rate"] == "0.9000"
    assert health_value["p50_duration_ms"] == "150.00"
    assert health_value["breaker_state"] == BREAKER_STATE_CLOSED
    assert rows[1].value == {
        "provider": "openai",
        "calls": 10,
        "success_count": 9,
        "failure_count": 1,
        "timeout_count": 0,
        "cost_paise": 2_500,
    }


def test_registering_a_metric_extends_the_registry_without_touching_the_store() -> None:
    """AC1: a later phase adds a metric by one registry line, not by schema churn."""
    sentinel = RollupMetric(metric_key="ai.custom", compute=lambda provider_input: {"calls": 1})

    try:
        register_rollup_metric(sentinel)

        assert "ai.custom" in rollup_metric_keys()
        rows = rollup_metrics_for(_usage(), _health())
        assert rows[-1].metric_key == "ai.custom.openai"
        assert rows[-1].value == {"calls": 1}
    finally:
        rollup_module.ROLLUP_REGISTRY.pop("ai.custom", None)

    assert "ai.custom" not in rollup_metric_keys()


def test_registering_a_duplicate_metric_key_is_refused() -> None:
    with pytest.raises(ValueError, match=r"ai\.spend"):
        register_rollup_metric(RollupMetric(metric_key=METRIC_KEY_AI_SPEND, compute=lambda _: {}))


def test_rollup_thresholds_carry_the_documented_defaults() -> None:
    thresholds = RollupThresholds(monthly_budget_paise=200_000)

    assert thresholds.budget_alert_threshold_pct == 80
    assert thresholds.breaker_open_success_rate == DEFAULT_BREAKER_OPEN_SUCCESS_RATE
    assert thresholds.provider_health_drop_threshold == DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD
    assert thresholds.outbox_backlog_threshold == DEFAULT_OUTBOX_BACKLOG_ALERT_THRESHOLD
    # The two documented objectives #734 finally alerts on, and the floor that keeps
    # the error-rate rule from firing on a three-request sample.
    assert thresholds.error_rate_objective == DEFAULT_ERROR_RATE_OBJECTIVE
    assert thresholds.error_rate_min_requests == DEFAULT_ERROR_RATE_MIN_REQUESTS
    assert thresholds.latency_objective_ms == DEFAULT_LATENCY_OBJECTIVE_MS
    assert thresholds.provider_rate_limit_count == DEFAULT_PROVIDER_RATE_LIMIT_ALERT_COUNT


def test_rollup_thresholds_reject_an_objective_nobody_can_meet_or_a_lie_about() -> None:
    """The new thresholds refuse values that would silence or perma-fire their rule."""
    with pytest.raises(ValueError, match="error_rate_objective"):
        RollupThresholds(monthly_budget_paise=200_000, error_rate_objective=Decimal("0"))
    with pytest.raises(ValueError, match="error_rate_min_requests"):
        RollupThresholds(monthly_budget_paise=200_000, error_rate_min_requests=0)
    with pytest.raises(ValueError, match="latency_objective_ms"):
        RollupThresholds(monthly_budget_paise=200_000, latency_objective_ms=0)
    with pytest.raises(ValueError, match="provider_rate_limit_count"):
        RollupThresholds(monthly_budget_paise=200_000, provider_rate_limit_count=0)


def test_rollup_thresholds_reject_a_non_positive_budget() -> None:
    with pytest.raises(ValueError, match="monthly_budget_paise"):
        RollupThresholds(monthly_budget_paise=0)


# ------------------------------------- B6 #725: the per-actor attribution rollup

#: ``observability_attribution_daily`` stores the raw counters and NOTHING derived
#: from them. Cost per thousand input or output tokens, per request, per completed
#: task, per patient, per doctor and cost-of-pass are all read-time divisions over
#: these same columns: a stored copy would be a second source of truth that goes
#: stale the moment a day's spend is recomputed (#717 decision 8).
_PER_UNIT_FIGURES = (
    "cost_per_thousand_input_tokens",
    "cost_per_thousand_output_tokens",
    "cost_per_request",
    "cost_per_completed_task",
    "cost_per_patient",
    "cost_per_doctor",
    "cost_of_pass",
    "gross_margin",
)


def _spend(
    *,
    intake_ref: int = 10,
    patient_key: str = "patient-a",
    doctor_key: str | None = None,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    task_type: str = "structure",
    input_tokens: int = 100,
    output_tokens: int = 20,
    cost_paise: int = 500,
    status: str = "completed",
) -> ActorSpend:
    """One ``observability_ai_job_spend`` row as #723's consumer leaves it."""
    return ActorSpend(
        intake_ref=intake_ref,
        patient_key=patient_key,
        doctor_key=doctor_key,
        provider=provider,
        model=model,
        task_type=task_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_paise=cost_paise,
        status=status,
    )


def test_the_attribution_rollup_splits_one_jobs_spend_across_patient_and_doctor() -> None:
    """A patient's cost and the doctor who served it are the SAME spend, counted twice.

    One job is one rupee of cost and two facts about it: whose it was, and whose
    case it served. The two actor rows therefore carry identical figures, which is
    what lets per-patient and per-doctor cost reconcile against each other.
    """
    rows = build_attribution_daily(spend=[_spend()], doctor_by_intake={10: "doctor-a"})

    assert [(row.actor_kind, row.actor_key) for row in rows] == [
        ("doctor", "doctor-a"),
        ("patient", "patient-a"),
    ]
    for row in rows:
        assert (row.jobs, row.completed_jobs, row.failed_jobs) == (1, 1, 0)
        assert (row.input_tokens, row.output_tokens, row.cost_paise) == (100, 20, 500)


def test_a_doctor_edge_that_lands_after_its_ai_job_fills_the_doctor_in_on_the_next_pass() -> None:
    """The late-arriving attribution case, and the reason nothing here increments.

    Transcription and structuring run BEFORE the patient picks a doctor, so the job
    row reaches the source table with no doctor at all. The first pass can only
    produce the patient row; once the edge lands, the next pass adds the doctor -
    and because every figure is recomputed from the same source rows rather than
    added to the previous pass's total, the patient row comes back unchanged
    instead of the day's spend being counted a second time.
    """
    without_edge = build_attribution_daily(spend=[_spend()], doctor_by_intake={})
    assert [row.actor_kind for row in without_edge] == ["patient"]

    with_edge = build_attribution_daily(spend=[_spend()], doctor_by_intake={10: "doctor-a"})
    assert [row.actor_kind for row in with_edge] == ["doctor", "patient"]

    patient_now = next(row for row in with_edge if row.actor_kind == "patient")
    assert patient_now == without_edge[0]


def test_an_unattributed_job_leaves_no_doctor_row_to_invent() -> None:
    """A missing doctor is a gap the operator can see, not a row that looks attributed.

    Writing a row under a placeholder key would make unattributed spend
    indistinguishable from attributed spend in every per-doctor figure downstream.
    """
    rows = build_attribution_daily(spend=[_spend()], doctor_by_intake={})

    assert len(rows) == 1


def test_the_intakes_current_edge_outranks_a_jobs_own_doctor_key() -> None:
    """One intake has one doctor, so the edge decides and the row's key is the fallback.

    A re-pick moves the edge, and a drafting job that ran before it carries the
    doctor the patient has moved on from. Letting each row's own key win would
    split one intake's spend across two doctors on the same day and stop the
    per-patient and per-doctor figures reconciling.
    """
    rows = build_attribution_daily(
        spend=[_spend(doctor_key="doctor-old")], doctor_by_intake={10: "doctor-new"}
    )

    assert [(row.actor_kind, row.actor_key) for row in rows] == [
        ("doctor", "doctor-new"),
        ("patient", "patient-a"),
    ]


def test_a_drafting_job_is_attributed_to_its_own_doctor_without_an_edge() -> None:
    """The fallback is what covers a pick the edge table has not recorded yet."""
    rows = build_attribution_daily(
        spend=[_spend(task_type="draft", doctor_key="doctor-a")], doctor_by_intake={}
    )

    assert [(row.actor_kind, row.actor_key) for row in rows] == [
        ("doctor", "doctor-a"),
        ("patient", "patient-a"),
    ]


def test_a_failed_job_counts_as_attempted_and_never_as_spend() -> None:
    """The attempt is recorded; the tokens and paise are not fabricated as free."""
    rows = build_attribution_daily(
        spend=[_spend(status="failed", input_tokens=0, output_tokens=0, cost_paise=0)],
        doctor_by_intake={10: "doctor-a"},
    )

    for row in rows:
        assert (row.jobs, row.completed_jobs, row.failed_jobs) == (1, 0, 1)
        assert (row.input_tokens, row.output_tokens, row.cost_paise) == (0, 0, 0)


def test_the_attribution_rollup_sums_a_scope_and_keeps_the_actor_kinds_apart() -> None:
    """One row per (actor, provider, model, task type): summed, never merged away."""
    rows = build_attribution_daily(
        spend=[
            _spend(cost_paise=500),
            _spend(cost_paise=300, output_tokens=10),
            _spend(cost_paise=7, task_type="draft"),
        ],
        doctor_by_intake={10: "doctor-a"},
    )

    indexed = {(row.actor_kind, row.actor_key, row.task_type): row for row in rows}
    structure = indexed[("patient", "patient-a", "structure")]
    assert (structure.jobs, structure.cost_paise, structure.output_tokens) == (2, 800, 30)
    # The draft is its own scope, so a task-type breakdown is a plain group-by.
    assert indexed[("doctor", "doctor-a", "draft")].cost_paise == 7
    assert len(rows) == 4


def test_a_repeat_pass_over_the_same_rows_produces_identical_rows_in_identical_order() -> None:
    """Recompute-in-full is only idempotent if the order does not depend on arrival."""
    spend = [
        _spend(patient_key="patient-b", intake_ref=11, cost_paise=9),
        _spend(patient_key="patient-a", intake_ref=10, cost_paise=5),
    ]

    first = build_attribution_daily(spend=spend, doctor_by_intake={10: "doctor-a", 11: "doctor-a"})
    second = build_attribution_daily(spend=spend, doctor_by_intake={10: "doctor-a", 11: "doctor-a"})

    assert first == second
    assert [(row.actor_kind, row.actor_key) for row in first] == [
        ("doctor", "doctor-a"),
        ("patient", "patient-a"),
        ("patient", "patient-b"),
    ]


def test_the_attribution_rollup_of_an_empty_day_writes_nothing() -> None:
    """An idle day invents no actor rows; ``run_rollup`` has nothing to upsert."""
    assert build_attribution_daily(spend=[], doctor_by_intake={10: "doctor-a"}) == ()


def test_the_daily_actor_aggregate_stores_counters_and_no_per_unit_figure() -> None:
    """Decision 8, as a negative: the per-unit figures must not become columns."""
    assert tuple(field for field in AttributionDaily.__dataclass_fields__) == (
        "actor_kind",
        "actor_key",
        "provider",
        "model",
        "task_type",
        "jobs",
        "completed_jobs",
        "failed_jobs",
        "input_tokens",
        "output_tokens",
        "cost_paise",
    )

    stored = {column.name for column in observability_attribution_daily.c}
    assert not set(_PER_UNIT_FIGURES) & stored
    # The counters the derived figures are read from are here, so the read-time
    # division has something to divide.
    assert {"jobs", "completed_jobs", "input_tokens", "output_tokens", "cost_paise"} <= stored


def test_the_daily_actor_aggregate_keeps_revenue_and_tier_nullable_and_empty() -> None:
    """Decision 9: the monetization dimensions ship present and NULL.

    NULL is "not captured", deliberately not 0, which would mean "captured, and it
    was nothing" - so a reader can tell an unrevenueed day from a free one without
    a second column, and switching monetization on is a data write.
    """
    revenue = observability_attribution_daily.c.revenue_paise
    tier = observability_attribution_daily.c.tier_key

    assert (revenue.nullable, tier.nullable) == (True, True)
    assert (revenue.server_default, tier.server_default) == (None, None)


def test_the_actor_aggregate_carries_no_identifying_column() -> None:
    """Decision 7 and ADR-0025 D7: a one-way actor key, never an identity reference."""
    assert "actor_key" in observability_attribution_daily.c
    assert not {
        "patient_id",
        "patient_ref",
        "doctor_id",
        "doctor_ref",
        "intake_ref",
        "name",
        "phone",
    } & set(observability_attribution_daily.c.keys())


# ---------------------------------------- B7 #733: the cost-outlier alert


def test_a_day_that_multiplies_the_actors_own_week_raises_a_cost_outlier() -> None:
    """The headline case: one actor, one day, ninety times what that actor normally spends."""
    alerts = evaluate_cost_outlier_alerts(
        _trailing(1_000, 1_000, 1_000, recent=90_000),
        RollupThresholds(monthly_budget_paise=200_000),
        target_date=_TARGET_DATE,
    )

    assert len(alerts) == 1
    assert alerts[0].kind == ALERT_KIND_COST_OUTLIER
    # A warning, not a page: the operator has to JUDGE this one, and a page for a
    # figure that may be a legitimately heavy patient trains people to ignore pages.
    assert alerts[0].severity == ALERT_SEVERITY_WARNING


def test_the_cost_outlier_alert_names_the_actor_and_carries_both_figures() -> None:
    """AC2: without both figures the alert is a claim nobody can check."""
    alerts = evaluate_cost_outlier_alerts(
        _trailing(1_000, 1_000, 1_000, recent=90_000),
        RollupThresholds(monthly_budget_paise=200_000),
        target_date=_TARGET_DATE,
    )

    payload = alerts[0].payload
    assert payload["actor_kind"] == "patient"
    assert payload["actor_key"] == "actor-a"
    assert payload["usage_date"] == _TARGET_DATE.isoformat()
    assert payload["baseline_daily_paise"] == "1000.00"
    assert payload["baseline_total_paise"] == 3_000
    assert payload["baseline_days"] == 3
    assert payload["recent_day_spend_paise"] == 90_000
    assert payload["threshold_multiple"] == "3.00"
    assert payload["deviation_multiple"] == "90.00"
    # The actor is named in the one-line title too: the feed's card view has to be
    # judgeable without opening the payload.
    assert "actor-a" in alerts[0].title
    assert "90.00" in alerts[0].title


def test_a_cost_outlier_is_a_spike_in_the_day_under_test_not_a_heavy_week() -> None:
    """The other end of the same rule: a heavy trailing week with a normal day is quiet."""
    alerts = evaluate_cost_outlier_alerts(
        _trailing(*([10_000] * (COST_OUTLIER_BASELINE_DAYS - 1)), recent=10_000),
        RollupThresholds(monthly_budget_paise=200_000),
        target_date=_TARGET_DATE,
    )

    assert alerts == ()


def test_the_outlier_rule_is_relative_so_a_heavy_actor_is_only_judged_against_itself() -> None:
    """AC3: the same rupee figure alerts one actor and not another.

    Both spend 90_000 paise on the day under test. The one with a small history is
    the spike; the one that spends that every day is not, and an absolute cap could
    only have called both of them - or neither.
    """
    spikes = evaluate_cost_outlier_alerts(
        [
            *_trailing(1_000, 1_000, 1_000, recent=90_000, actor_key="spiker"),
            *_trailing(*([90_000] * 6), recent=90_000, actor_key="heavy"),
        ],
        RollupThresholds(monthly_budget_paise=200_000),
        target_date=_TARGET_DATE,
    )

    assert [alert.payload["actor_key"] for alert in spikes] == ["spiker"]
    assert spikes[0].payload["deviation_multiple"] == "90.00"


def test_an_actor_with_no_trailing_history_is_never_a_cost_outlier() -> None:
    """AC: the fresh-database case, written down because it fires first on an empty one.

    Without a baseline every actor's first ever day would be an infinite multiple of
    nothing, so the entire population would alert on day one.
    """
    assert (
        evaluate_cost_outlier_alerts(
            [_day(0, 90_000)],
            RollupThresholds(monthly_budget_paise=200_000),
            target_date=_TARGET_DATE,
        )
        == ()
    )
    assert (
        actor_cost_baseline(
            [_day(0, 90_000)],
            RollupThresholds(monthly_budget_paise=200_000),
            target_date=_TARGET_DATE,
        )
        is None
    )


def test_an_actor_with_too_little_history_has_no_baseline_to_be_an_outlier_against() -> None:
    """A patient is episodic: one consultation last week is normal, not a 90x spike.

    Averaged over seven calendar days including the six they spent nothing, their
    baseline would be a seventh of one consultation and an ordinary return visit
    would alert every single time.
    """
    history = _trailing(1_000, recent=90_000)

    assert (
        actor_cost_baseline(
            history, RollupThresholds(monthly_budget_paise=200_000), target_date=_TARGET_DATE
        )
        is None
    )
    assert (
        evaluate_cost_outlier_alerts(
            history,
            RollupThresholds(monthly_budget_paise=200_000),
            target_date=_TARGET_DATE,
        )
        == ()
    )


def test_the_baseline_ignores_days_outside_the_trailing_week_and_the_day_under_test() -> None:
    """The window is the seven days behind, so neither an older spike nor today's own
    figure can move the bar it is judged against.

    Including the day under test would let a large day raise its own average and halve
    the deviation it is being measured by - an abuse worth 3x would read as 1.4x.
    """
    rows = [
        *(_day(offset, 1_000) for offset in range(1, COST_OUTLIER_BASELINE_DAYS)),
        _day(0, 1_000_000),
        _day(COST_OUTLIER_BASELINE_DAYS, 999_999),
    ]

    baseline = actor_cost_baseline(
        rows, RollupThresholds(monthly_budget_paise=200_000), target_date=_TARGET_DATE
    )

    assert baseline is not None
    assert baseline.days == COST_OUTLIER_BASELINE_DAYS - 1
    assert baseline.total_paise == 6_000
    assert baseline.daily_paise == Decimal("1000")


def test_the_baseline_window_is_configurable_and_the_adapter_reads_the_same_window() -> None:
    """A deployment that widens the window gets a wider baseline, not a stale one.

    The query is bounded by the SAME configured figure the rule judges against. If the
    two were separate constants, a fourteen-day configuration would silently judge a
    fourteen-day average against seven days of history.
    """
    wide = RollupThresholds(
        monthly_budget_paise=200_000,
        cost_outlier_baseline_days=14,
        cost_outlier_min_baseline_days=10,
    )
    rows = [
        *(_day(offset, 1_000) for offset in range(1, 11)),
        _day(0, 90_000),
    ]

    assert (
        actor_cost_baseline(
            rows, RollupThresholds(monthly_budget_paise=200_000), target_date=_TARGET_DATE
        ).days
        == 6
    )
    baseline = actor_cost_baseline(rows, wide, target_date=_TARGET_DATE)
    assert baseline is not None
    assert baseline.days == 10
    assert baseline.daily_paise == Decimal("1000")
    # A minimum wider than the window could never be met, which would silence the rule
    # for everyone rather than for anyone.
    with pytest.raises(ValueError, match="cost_outlier_min_baseline_days"):
        RollupThresholds(
            monthly_budget_paise=200_000,
            cost_outlier_baseline_days=2,
            cost_outlier_min_baseline_days=3,
        )


def test_the_cost_outlier_multiple_travels_with_the_rollup_thresholds() -> None:
    """AC5: the multiple is a threshold, so a deployment moves it without a code change."""
    strict = RollupThresholds(monthly_budget_paise=200_000, cost_outlier_multiple=Decimal("20"))
    lenient = RollupThresholds(monthly_budget_paise=200_000, cost_outlier_multiple=Decimal("2"))
    # 1_000 paise on a 100 paise day is 10x the actor's own average.
    history = _trailing(*([100] * 7), recent=1_000)

    assert evaluate_cost_outlier_alerts(history, lenient, target_date=_TARGET_DATE) != ()
    assert evaluate_cost_outlier_alerts(history, strict, target_date=_TARGET_DATE) == ()
    assert RollupThresholds(monthly_budget_paise=200_000).cost_outlier_multiple == (
        DEFAULT_COST_OUTLIER_MULTIPLE
    )
    # A multiple that fires on any day merely above the actor's own average is refused
    # rather than shipped: half of any week is above its mean.
    with pytest.raises(ValueError, match="cost_outlier_multiple"):
        RollupThresholds(monthly_budget_paise=200_000, cost_outlier_multiple=Decimal("1"))


def test_one_cost_outlier_alert_per_actor_no_matter_how_many_scopes_the_day_had() -> None:
    """An abuse in one task type must not be averaged away by the actor's ordinary ones."""
    alerts = evaluate_cost_outlier_alerts(
        [*_trailing(1_000, 1_000, 1_000, recent=40_000), _day(0, 20_000)],
        RollupThresholds(monthly_budget_paise=200_000),
        target_date=_TARGET_DATE,
    )

    assert len(alerts) == 1
    assert alerts[0].payload["recent_day_spend_paise"] == 60_000


def test_the_reported_deviation_can_never_read_as_under_the_threshold_it_fired_against() -> None:
    """The rule compares at the precision the payload reports.

    At full precision 4_090paise on a 1_000paise baseline is 4.09x, but a fraction
    just over a multiple - 3.004x - would otherwise be reported as ``3.00x`` beside a
    ``3.00`` threshold, leaving the reader unable to see why the alert fired at all.
    """
    just_over = evaluate_cost_outlier_alerts(
        _trailing(1_000, 1_000, 1_000, recent=3_004),
        RollupThresholds(monthly_budget_paise=200_000),
        target_date=_TARGET_DATE,
    )
    just_under = evaluate_cost_outlier_alerts(
        _trailing(1_000, 1_000, 1_000, recent=2_999),
        RollupThresholds(monthly_budget_paise=200_000),
        target_date=_TARGET_DATE,
    )

    # Rounding down to the reported precision makes both sides agree, so a figure that
    # would read as AT the threshold does not fire at all.
    assert just_over == ()
    assert just_under == ()
    assert (
        evaluate_cost_outlier_alerts(
            _trailing(1_000, 1_000, 1_000, recent=3_010),
            RollupThresholds(monthly_budget_paise=200_000),
            target_date=_TARGET_DATE,
        )[0].payload["deviation_multiple"]
        == "3.01"
    )


def test_a_zero_baseline_is_silence_rather_than_a_pass_crash() -> None:
    """The builder is public, so it must not divide by a baseline it did not build.

    A zero baseline is not a deviation; it is an absence of one, and raising a
    ``DivisionByZero`` out of the nightly pass over it would take the whole rollup
    down for a figure that means nothing.
    """
    assert (
        build_cost_outlier_alert(
            "patient",
            "actor-a",
            recent_spend_paise=90_000,
            baseline=ActorCostBaseline(
                actor_kind="patient",
                actor_key="actor-a",
                days=3,
                total_paise=0,
                daily_paise=Decimal("0"),
            ),
            multiple=DEFAULT_COST_OUTLIER_MULTIPLE,
            usage_date=_TARGET_DATE,
        )
        is None
    )


def test_a_cost_outlier_alert_dedupes_on_the_actor_and_not_on_the_figures() -> None:
    """The marker is the actor alone, so the measured figures cannot change identity."""
    payload = {
        "source": "rollup",
        "actor": actor_alert_scope("patient", "actor-a"),
        "recent_day_spend_paise": 90_000,
        "baseline_daily_paise": "1000.00",
    }

    assert alert_marker(payload) == {
        "source": "rollup",
        "actor": actor_alert_scope("patient", "actor-a"),
    }
    assert alert_key(ALERT_KIND_COST_OUTLIER, payload) == alert_key(
        ALERT_KIND_COST_OUTLIER,
        {"source": "rollup", "actor": actor_alert_scope("patient", "actor-a")},
    )


def test_the_resolve_step_may_close_a_cost_outlier_because_a_spike_has_a_steady_state() -> None:
    """AC4: the kind is resolvable, and the vocabulary test states which half it is in."""
    assert alert_kind_resolves(ALERT_KIND_COST_OUTLIER)
    assert ALERT_KIND_COST_OUTLIER in RESOLVABLE_ALERT_KINDS
    assert ALERT_KIND_COST_OUTLIER not in NON_RESOLVABLE_ALERT_KINDS


def test_the_evaluated_keys_cover_every_actor_the_pass_measured() -> None:
    """An actor measured and found normal is the one whose alert has to CLOSE.

    A set built only from the alerts this pass raised could never contain an actor
    that has stopped spiking, so its alert would sit open for ever.
    """
    keys = evaluated_alert_keys(
        providers=[], tables=[], actors=[actor_alert_scope("patient", "actor-a")]
    )

    assert (
        alert_key(
            ALERT_KIND_COST_OUTLIER,
            {"source": "rollup", "actor": actor_alert_scope("patient", "actor-a")},
        )
        in keys
    )
    # An actor this pass never read is not evaluated, so its alert is not closed on
    # absence of evidence - unless it is handed over as ALREADY alerting, which is
    # what the adapter does. Otherwise it could never be closed at all.
    assert (
        alert_key(
            ALERT_KIND_COST_OUTLIER,
            {"source": "rollup", "actor": actor_alert_scope("patient", "actor-b")},
        )
        not in keys
    )


def test_an_actor_who_has_gone_quiet_still_gets_their_cost_outlier_reconciled() -> None:
    """An actor past the trailing window leaves it for good, so absence must resolve.

    Their alert is about ONE DAY's figure, and later quiet cannot un-spike it - only
    end it. Without the union no later pass would ever re-read them, so the row would
    stay open for ever: not held on missing evidence, but unreachable.
    """
    observed_only = evaluated_alert_keys(
        providers=[], tables=[], actors=[actor_alert_scope("patient", "actor-a")]
    )
    reconciled = evaluated_alert_keys(
        providers=[],
        tables=[],
        actors=[actor_alert_scope("patient", "actor-a")],
        alerted_actors=[actor_alert_scope("patient", "actor-b")],
    )

    # The union adds exactly the gone-quiet actor's key, and nothing else moves.
    assert reconciled - observed_only == {
        alert_key(ALERT_KIND_COST_OUTLIER, {"source": "rollup", "actor": "patient:actor-b"})
    }
    assert observed_only - reconciled == set()


def test_the_two_actor_kinds_keep_separate_cost_outlier_alerts() -> None:
    """A patient's spike and their doctor's are different findings, not one merged row."""
    doctor = [
        ActorDailySpend("doctor", "actor-b", _TARGET_DATE - timedelta(days=offset), 1_000)
        for offset in range(1, 4)
    ]
    alerts = evaluate_cost_outlier_alerts(
        [
            *_trailing(1_000, 1_000, 1_000, recent=90_000, actor_key="actor-a"),
            *_trailing(1_000, 1_000, 1_000, actor_key="actor-b"),
            *doctor,
            ActorDailySpend("doctor", "actor-b", _TARGET_DATE, 90_000),
        ],
        RollupThresholds(monthly_budget_paise=200_000),
        target_date=_TARGET_DATE,
    )

    assert [alert.payload["actor"] for alert in alerts] == [
        "doctor:actor-b",
        "patient:actor-a",
    ]


# ------------------------------------------------------- rate-limited provider


def test_a_rate_limited_provider_raises_its_own_kind() -> None:
    """A quota refusal is named, and named separately from a generic health drop.

    The board already shows ``rate_limit_count`` on a degraded row, but "degraded" is
    a verdict and not an action: the fix for being throttled is to slow down, and
    that is not what an operator does with a success-rate figure.
    """
    alert = build_provider_rate_limited_alert(
        _rate_limited_health(rate_limit_count=3),
        threshold=DEFAULT_PROVIDER_RATE_LIMIT_ALERT_COUNT,
    )

    assert alert is not None
    assert alert.kind == ALERT_KIND_PROVIDER_RATE_LIMITED
    assert alert.severity == ALERT_SEVERITY_WARNING
    assert alert.payload["provider"] == "openai"
    assert alert.payload["rate_limit_count"] == 3
    assert alert.payload["threshold_count"] == DEFAULT_PROVIDER_RATE_LIMIT_ALERT_COUNT


def test_a_provider_the_platform_never_throttled_raises_nothing() -> None:
    """Zero refusals is the absence of a condition, not a mild form of it."""
    assert (
        build_provider_rate_limited_alert(
            _rate_limited_health(rate_limit_count=0),
            threshold=DEFAULT_PROVIDER_RATE_LIMIT_ALERT_COUNT,
        )
        is None
    )


def test_the_rate_limit_count_is_tunable_above_the_one_refusal_that_is_enough() -> None:
    """The default fires on ONE refusal; a deployment that treats that as noise raises it."""
    health = _rate_limited_health(rate_limit_count=2)

    assert build_provider_rate_limited_alert(health, threshold=1) is not None
    assert build_provider_rate_limited_alert(health, threshold=5) is None


def test_a_throttled_provider_keeps_its_degradation_verdict_aside_from_the_alert() -> None:
    """The alert and the board agree: the same refusal count that alerts is what degrades."""
    health = _rate_limited_health(rate_limit_count=3)

    assert provider_status(health) == PROVIDER_STATUS_DEGRADED
    assert evaluate_provider_health_alerts(health, None, _thresholds()) == (
        build_provider_rate_limited_alert(health, threshold=1),
    )


# ------------------------------------------------------------- latency objective


def test_an_ai_call_slower_than_the_documented_objective_raises_its_own_kind() -> None:
    """The objective is the standard's, not a round number the alert invented.

    ``error-handling-observability.md`` §5.1 states "AI call (end to end, provider
    included) p95 <= 30 s", so 30_000 ms is the comparison and the payload carries it
    next to the measured p95 - a reader can falsify the judgement from the card.
    """
    health = _slow_health(p95_ms=Decimal("45000.00"))

    alert = build_latency_objective_breach_alert(health, objective_ms=DEFAULT_LATENCY_OBJECTIVE_MS)

    assert alert is not None
    assert alert.kind == ALERT_KIND_LATENCY_OBJECTIVE_BREACH
    assert alert.severity == ALERT_SEVERITY_WARNING
    assert alert.payload["provider"] == "openai"
    assert alert.payload["p95_duration_ms"] == "45000.00"
    assert alert.payload["objective_ms"] == DEFAULT_LATENCY_OBJECTIVE_MS


def test_the_latency_alert_measures_the_call_and_nothing_inside_it() -> None:
    """A user-facing symptom, never an internal cause (#734, decision 20).

    The p95 compared here is the AI call END TO END with the provider included: the
    duration somebody waited for. It is deliberately NOT the duration of any function
    inside the platform - ``validate_token`` p95 or ``check_consent`` p95 would be
    faster, would breach far more often, and would page on something no user ever
    experiences. Stated here because the temptation is to alert on the tightest
    number in the standards rather than the one anybody feels.
    """
    assert DEFAULT_LATENCY_OBJECTIVE_MS == 30_000
    internal = _slow_health(p95_ms=Decimal("120.00"))

    # An internal function's p95 an order of magnitude inside the objective breaches
    # none of them, because the rule only ever looks at the end-to-end call.
    assert build_latency_objective_breach_alert(internal, objective_ms=100) is not None
    assert (
        build_latency_objective_breach_alert(internal, objective_ms=DEFAULT_LATENCY_OBJECTIVE_MS)
        is None
    )


def test_a_provider_with_no_completion_to_time_is_not_a_slow_provider() -> None:
    """No p95 means no sample, and an absent sample is never evidence of a failure."""
    idle = compute_provider_health(
        "openai",
        _WINDOW_START,
        _WINDOW_END,
        _usage("openai", _scope(calls=4, success=0, failure=4, avg=None)),
    )

    assert idle.p95_duration_ms is None
    assert build_latency_objective_breach_alert(idle, objective_ms=1) is None


def test_a_call_exactly_at_the_objective_is_within_it() -> None:
    """The objective states "p95 <= 30 s", so the rule fires strictly above."""
    at_objective = _slow_health(p95_ms=Decimal("30000.00"))

    assert build_latency_objective_breach_alert(at_objective, objective_ms=30_000) is None
    assert (
        build_latency_objective_breach_alert(
            _slow_health(p95_ms=Decimal("30000.01")), objective_ms=30_000
        )
        is not None
    )


# -------------------------------------------------------------- high error rate


def test_an_error_rate_past_the_documented_objective_raises_its_own_kind() -> None:
    """The objective is standards §5.1's "error rate (5xx share of requests) < 1%".

    The payload carries the numerator, the denominator and both rates, because a rate
    with no denominator behind it is an unfalsifiable claim on an operator's board.
    """
    alerts = evaluate_http_error_rate_alerts(
        _volume(1_000, 40),
        _thresholds(),
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.kind == ALERT_KIND_ERROR_RATE_HIGH
    # Critical: the objective is the platform-wide "the platform is failing" line, and
    # every caller is on the other side of it at once.
    assert alert.severity == ALERT_SEVERITY_CRITICAL
    assert alert.payload["requests"] == 1_000
    assert alert.payload["errors"] == 40
    assert alert.payload["error_rate"] == "0.0400"
    assert alert.payload["objective"] == "0.0100"
    assert alert.payload["min_requests"] == DEFAULT_ERROR_RATE_MIN_REQUESTS


def test_an_error_rate_exactly_at_the_objective_is_within_it() -> None:
    """The objective reads "< 1%", so one percent is not past it."""
    assert (
        evaluate_http_error_rate_alerts(
            _volume(1_000, 10),
            _thresholds(),
        )
        == ()
    )


def test_a_tiny_sample_is_silence_rather_than_a_hundred_percent_error_rate() -> None:
    """One failure in three requests is 33% and is not an outage.

    Without a floor this rule is the first thing an operator learns to dismiss: on a
    quiet night a handful of requests carry the whole denominator, so every one of
    them is a large share of it. The floor is why the alert can be trusted at all.
    """
    below_floor = evaluate_http_error_rate_alerts(
        _volume(DEFAULT_ERROR_RATE_MIN_REQUESTS - 1, DEFAULT_ERROR_RATE_MIN_REQUESTS - 1),
        _thresholds(),
    )
    at_floor = evaluate_http_error_rate_alerts(
        _volume(DEFAULT_ERROR_RATE_MIN_REQUESTS, 90),
        _thresholds(),
    )

    assert below_floor == ()
    assert [alert.kind for alert in at_floor] == [ALERT_KIND_ERROR_RATE_HIGH]


def test_a_day_the_counter_never_saw_is_not_a_perfect_error_rate() -> None:
    """No recorded requests is an absent denominator, which reads as no alert."""
    assert (
        evaluate_http_error_rate_alerts(
            _volume(0, 0),
            _thresholds(),
        )
        == ()
    )
    assert _volume(0, 0).error_rate is None
    # And it is also NOT a judgement the resolve step may act on, which is a separate
    # question from whether the rule fires - see ``error_rate_evaluated``.
    assert _volume(0, 0).traffic_recorded is False
    assert _volume(1_000, 40).traffic_recorded is True


def test_the_error_rate_floor_is_tunable() -> None:
    """A deployment that wants the rule on thinner traffic can lower the floor."""
    thin = _thresholds(error_rate_min_requests=10)

    assert (
        evaluate_http_error_rate_alerts(
            _volume(10, 5),
            thin,
        )
        != ()
    )
    assert (
        evaluate_http_error_rate_alerts(
            _volume(10, 5),
            _thresholds(),
        )
        == ()
    )


# -------------------------------------------------------- dedupe across nights


def test_every_new_kind_dedupes_on_one_marker_and_nights_do_not_stack_it() -> None:
    """The dedupe marker is the existing mechanism, not a per-kind reinvention.

    A nightly rollup that re-raised the same breach every night would bury the one
    operator change that clears it. Two passes over the same condition must produce
    the SAME key even though every measured figure between them moved, because the
    marker holds the subject and nothing else.
    """
    rate_limited_keys = {
        _key_of(
            build_provider_rate_limited_alert(
                _rate_limited_health(rate_limit_count=count), threshold=1
            )
        )
        for count in (1, 3, 97)
    }
    latency_keys = {
        _key_of(
            build_latency_objective_breach_alert(
                _slow_health(p95_ms=p95), objective_ms=DEFAULT_LATENCY_OBJECTIVE_MS
            )
        )
        for p95 in (Decimal("31000.00"), Decimal("45000.00"), Decimal("90000.00"))
    }
    error_rate_keys = {
        _key_of(
            build_error_rate_alert(
                volume,
                objective=DEFAULT_ERROR_RATE_OBJECTIVE,
                min_requests=DEFAULT_ERROR_RATE_MIN_REQUESTS,
            )
        )
        for volume in (_volume(1_000, 40), _volume(9_000, 900))
    }

    assert len(rate_limited_keys) == 1
    assert len(latency_keys) == 1
    assert len(error_rate_keys) == 1


def _key_of(alert: AlertRow | None) -> tuple[str, str]:
    """The dedupe key of an alert the test expects to exist."""
    assert alert is not None
    return alert_key(alert.kind, alert.payload)


def test_two_providers_in_trouble_do_not_share_one_alert() -> None:
    """Distinct subjects must produce distinct markers or one breach hides the other.

    The measured figures are deliberately outside the marker, so the SUBJECT has to
    be inside it: two providers at the same refusal count are two findings, and
    resolving one must leave the other open.
    """

    def key(provider: str, *, rate_limit_count: int) -> tuple[str, str]:
        alert = build_provider_rate_limited_alert(
            _rate_limited_health(provider, rate_limit_count=rate_limit_count),
            threshold=1,
        )
        assert alert is not None
        return alert_key(alert.kind, alert.payload)

    openai = key("openai", rate_limit_count=1)
    google = key("google", rate_limit_count=1)

    assert openai != google
    assert (
        alert_key(ALERT_KIND_PROVIDER_RATE_LIMITED, {"source": "rollup", "provider": "google"})
        == google
    )


# ------------------------------------------- the evaluated set and auto-resolve


def test_the_platform_error_rate_is_reconciled_only_on_a_day_that_had_traffic() -> None:
    """A day with no traffic is NOT the observation that the error rate is fine.

    The rollup runs over arbitrary dates, so a backfill of a quiet day - one from
    before the counter was deployed, or one simply nobody used the platform on -
    would otherwise read zero requests, raise nothing, and silently close a LIVE
    breach an operator was in the middle of. Gating on traffic keeps "absence of
    evidence never clears a standing condition" true for the one subject that has no
    rows of its own, and it defaults to closed for any caller that does not read the
    counter at all, exactly like ``queues`` and ``actors`` do.
    """
    with_traffic = evaluated_alert_keys(providers=[], tables=[], error_rate_evaluated=True)
    without_traffic = evaluated_alert_keys(providers=[], tables=[])
    key = alert_key(ALERT_KIND_ERROR_RATE_HIGH, {"source": "rollup", "scope": "platform_total"})

    assert key in with_traffic
    assert key not in without_traffic


def test_a_provider_marks_all_four_of_its_kinds_as_evaluated() -> None:
    """Every kind scoped to a provider joins that provider's reconciliation.

    The resolve step closes only what this pass could have re-raised, so a kind
    missing from this set can never be closed by ANY pass - an alert with no exit.
    """
    keys = evaluated_alert_keys(providers=["openai"], tables=[])

    for kind in (
        ALERT_KIND_BREAKER_OPEN,
        ALERT_KIND_PROVIDER_HEALTH_DROP,
        ALERT_KIND_PROVIDER_RATE_LIMITED,
        ALERT_KIND_LATENCY_OBJECTIVE_BREACH,
    ):
        assert alert_key(kind, {"source": "rollup", "provider": "openai"}) in keys, kind

    # And nothing about a provider nobody observed: absence of evidence, not clearing.
    assert not any("google" in repr(key) for key in keys)


def test_the_three_new_kinds_resolve_and_the_health_drop_does_not() -> None:
    """The policy read end to end: the resolve step asks one question, about data.

    Each new kind clears itself when its figure comes back inside the objective; the
    health drop stays open because it is the kind that must not quietly vanish.
    """
    assert alert_kind_resolves(ALERT_KIND_PROVIDER_RATE_LIMITED)
    assert alert_kind_resolves(ALERT_KIND_ERROR_RATE_HIGH)
    assert alert_kind_resolves(ALERT_KIND_LATENCY_OBJECTIVE_BREACH)
    assert not alert_kind_resolves(ALERT_KIND_PROVIDER_HEALTH_DROP)
