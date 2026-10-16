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
    ALERT_KIND_BREAKER_OPEN,
    ALERT_KIND_OUTBOX_BACKLOG,
    ALERT_KIND_OUTBOX_DEAD_LETTER,
    ALERT_KIND_PROVIDER_HEALTH_DROP,
    BREAKER_STATE_CLOSED,
    BREAKER_STATE_OPEN,
    DEFAULT_BREAKER_OPEN_SUCCESS_RATE,
    DEFAULT_DEGRADED_SUCCESS_RATE,
    DEFAULT_OUTBOX_BACKLOG_ALERT_THRESHOLD,
    DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD,
    FAILURE_REASON_RATE_LIMITED,
    METRIC_KEY_AI_PROVIDER_HEALTH,
    METRIC_KEY_AI_SPEND,
    NON_RESOLVABLE_ALERT_KINDS,
    PROVIDER_STATUS_DEGRADED,
    PROVIDER_STATUS_DOWN,
    PROVIDER_STATUS_HEALTHY,
    RESOLVABLE_ALERT_KINDS,
    ActorSpend,
    AttributionDaily,
    BudgetSnapshot,
    OutboxTableHealth,
    ProviderFailures,
    ProviderHealth,
    ProviderUsage,
    RollupMetric,
    RollupThresholds,
    UsageScope,
    alert_kind_resolves,
    breaker_state_for,
    budget_period_for,
    build_attribution_daily,
    build_breaker_open_alert,
    build_budget_alert,
    build_budget_snapshot,
    build_dead_letter_alert,
    build_outbox_backlog_alert,
    build_provider_health_drop_alert,
    compute_provider_health,
    evaluate_budget_alerts,
    evaluate_outbox_health_alerts,
    evaluate_provider_health_alerts,
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

_PHI_KEYS = ("phone", "otp", "email", "name", "transcript", "patient", "text", "reason")


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
    }

    assert not RESOLVABLE_ALERT_KINDS & NON_RESOLVABLE_ALERT_KINDS
    assert every_kind == RESOLVABLE_ALERT_KINDS | NON_RESOLVABLE_ALERT_KINDS
    assert ALERT_KIND_PROVIDER_HEALTH_DROP in NON_RESOLVABLE_ALERT_KINDS


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
