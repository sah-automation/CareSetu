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
    DEFAULT_OUTBOX_BACKLOG_ALERT_THRESHOLD,
    DEFAULT_PROVIDER_HEALTH_DROP_THRESHOLD,
    METRIC_KEY_AI_PROVIDER_HEALTH,
    METRIC_KEY_AI_SPEND,
    BudgetSnapshot,
    OutboxTableHealth,
    ProviderHealth,
    ProviderUsage,
    RollupMetric,
    RollupThresholds,
    UsageScope,
    breaker_state_for,
    budget_period_for,
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
    register_rollup_metric,
    rollup_metric_keys,
    rollup_metrics_for,
    success_rate,
    weighted_percentile,
)

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
