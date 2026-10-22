"""PHASE-14A A5: observability Settings gates (ticket #693).

Acceptance contract from the brief: every Phase-14A observability environment
gate exists on ``Settings`` with a safe default and is parsed by
``get_settings()`` via the existing ``_env_bool``/``_env_float``/``_env_csv``
helpers; ``__post_init__`` fails closed where a gate implies a companion
(OTel enabled requires an endpoint, a Sentry sample rate above 0 requires a
DSN); ``LOG_FORMAT`` is validated as the two-value console/json enum. All
gates must default to the inert posture so local dev, tests and CI are
unchanged.
"""

from decimal import Decimal

import pytest

from app.config import (
    DEFAULT_LOG_FORMAT,
    DEFAULT_OBSERVABILITY_BREAKER_OPEN_SUCCESS_RATE,
    DEFAULT_OBSERVABILITY_BUDGET_ALERT_THRESHOLD_PCT,
    DEFAULT_OBSERVABILITY_COST_OUTLIER_MIN_BASELINE_DAYS,
    DEFAULT_OBSERVABILITY_COST_OUTLIER_MULTIPLE,
    DEFAULT_OBSERVABILITY_OUTBOX_BACKLOG_THRESHOLD,
    DEFAULT_OBSERVABILITY_PROVIDER_HEALTH_DROP_THRESHOLD,
    DEFAULT_OBSERVABILITY_PROVIDER_RATE_LIMIT_ALERT_COUNT,
    DEFAULT_OBSERVABILITY_QUEUE_AGE_THRESHOLD_SECONDS,
    DEFAULT_OBSERVABILITY_ROLLUP_MAX_DATES,
    DEFAULT_OTEL_TRACES_SAMPLER_RATIO,
    DEFAULT_SENTRY_TRACES_SAMPLE_RATE,
    Settings,
    get_settings,
)


def test_settings_observability_gates_default_to_inert() -> None:
    settings = Settings()

    assert settings.log_format == "console"
    assert settings.sentry_dsn == ""
    assert settings.sentry_traces_sample_rate == 0.0
    assert settings.otel_enabled is False
    assert settings.otel_exporter_otlp_endpoint == ""
    assert settings.otel_exporter_otlp_headers == ()
    assert settings.otel_traces_sampler_ratio == 1.0
    assert settings.otel_service_version == ""
    assert settings.metrics_enabled is False
    assert settings.observability_enabled is False
    # The nightly rollup's per-pass date ceiling (B5b #705) is a limit, so it is
    # configuration (coding-standards 9.1), not a constant in the worker.
    assert settings.observability_rollup_max_dates == DEFAULT_OBSERVABILITY_ROLLUP_MAX_DATES
    # Batch-3 feature gates (#753): each new observability feature ships behind
    # its own gate, off until a deployment opts in.
    assert settings.error_capture_enabled is False
    assert settings.evaluation_enabled is False
    assert settings.annotation_queue_enabled is False


def test_settings_reads_every_observability_gate_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("SENTRY_DSN", "https://sentry.invalid/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.25")
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otlp.invalid/v1/traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Basic dGVzdA==")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_RATIO", "0.5")
    monkeypatch.setenv("OTEL_SERVICE_VERSION", "abc1234")
    monkeypatch.setenv("METRICS_ENABLED", "1")
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "on")
    monkeypatch.setenv("OBSERVABILITY_ROLLUP_MAX_DATES", "14")
    monkeypatch.setenv("ERROR_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("EVALUATION_ENABLED", "1")
    monkeypatch.setenv("ANNOTATION_QUEUE_ENABLED", "on")

    settings = get_settings()

    assert settings.log_format == "json"
    assert settings.sentry_dsn == "https://sentry.invalid/1"
    assert settings.sentry_traces_sample_rate == 0.25
    assert settings.otel_enabled is True
    assert settings.otel_exporter_otlp_endpoint == "https://otlp.invalid/v1/traces"
    assert settings.otel_exporter_otlp_headers == ("Authorization=Basic dGVzdA==",)
    assert settings.otel_traces_sampler_ratio == 0.5
    assert settings.otel_service_version == "abc1234"
    assert settings.metrics_enabled is True
    assert settings.observability_enabled is True
    assert settings.observability_rollup_max_dates == 14
    assert settings.error_capture_enabled is True
    assert settings.evaluation_enabled is True
    assert settings.annotation_queue_enabled is True


def test_settings_refuses_a_non_positive_rollup_date_ceiling() -> None:
    """Fail closed at boot rather than planning an empty window every night."""
    with pytest.raises(ValueError, match="observability_rollup_max_dates"):
        Settings(observability_rollup_max_dates=0)


def test_settings_parses_otlp_headers_as_trimmed_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Basic aGk= , x-api-key=k")

    settings = get_settings()

    assert settings.otel_exporter_otlp_headers == ("Authorization=Basic aGk=", "x-api-key=k")


def test_settings_rejects_unknown_log_format() -> None:
    with pytest.raises(ValueError, match="unsupported log_format"):
        Settings(log_format="xml")


def test_settings_accepts_both_log_format_values_case_insensitively() -> None:
    assert Settings(log_format="console").log_format == DEFAULT_LOG_FORMAT
    assert Settings(log_format="json").log_format == "json"
    assert Settings(log_format="JSON").log_format == "JSON"


def test_settings_sentry_sample_rate_without_dsn_fails_closed() -> None:
    with pytest.raises(ValueError, match="requires SENTRY_DSN"):
        Settings(sentry_traces_sample_rate=0.1)


def test_settings_sentry_sample_rate_with_dsn_is_allowed() -> None:
    settings = Settings(sentry_dsn="https://sentry.invalid/1", sentry_traces_sample_rate=0.1)

    assert settings.sentry_traces_sample_rate == 0.1


def test_settings_sentry_sample_rate_refuses_out_of_range() -> None:
    with pytest.raises(ValueError, match="sentry_traces_sample_rate must be finite"):
        Settings(sentry_dsn="https://sentry.invalid/1", sentry_traces_sample_rate=1.5)

    with pytest.raises(ValueError, match="sentry_traces_sample_rate must be finite"):
        Settings(sentry_dsn="https://sentry.invalid/1", sentry_traces_sample_rate=-0.5)


def test_settings_otel_enabled_without_endpoint_fails_closed() -> None:
    with pytest.raises(ValueError, match="requires OTEL_EXPORTER_OTLP_ENDPOINT"):
        Settings(otel_enabled=True)


def test_settings_otel_enabled_with_endpoint_is_allowed() -> None:
    settings = Settings(
        otel_enabled=True,
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/traces",
    )

    assert settings.otel_enabled is True


def test_settings_otel_disabled_needs_no_endpoint() -> None:
    settings = Settings(otel_enabled=False)

    assert settings.otel_enabled is False


def test_settings_otel_sampler_ratio_refuses_out_of_range() -> None:
    with pytest.raises(ValueError, match="otel_traces_sampler_ratio must be finite"):
        Settings(otel_traces_sampler_ratio=1.1)

    with pytest.raises(ValueError, match="otel_traces_sampler_ratio must be finite"):
        Settings(otel_traces_sampler_ratio=-0.1)


def test_settings_otel_sampler_ratio_defaults_and_accepts_boundaries() -> None:
    assert Settings().otel_traces_sampler_ratio == DEFAULT_OTEL_TRACES_SAMPLER_RATIO
    assert Settings(otel_traces_sampler_ratio=0.0).otel_traces_sampler_ratio == 0.0
    assert Settings(otel_traces_sampler_ratio=1.0).otel_traces_sampler_ratio == 1.0


def test_settings_sentry_sample_rate_defaults_to_zero() -> None:
    assert Settings().sentry_traces_sample_rate == DEFAULT_SENTRY_TRACES_SAMPLE_RATE


# ------------------------------------------------------- the alert thresholds


def test_the_alert_thresholds_default_to_the_values_the_plan_names() -> None:
    """Each threshold is a limit a deployment may move, so it is configuration."""
    settings = Settings()

    assert settings.observability_budget_alert_threshold_pct == (
        DEFAULT_OBSERVABILITY_BUDGET_ALERT_THRESHOLD_PCT
    )
    assert settings.observability_breaker_open_success_rate == (
        DEFAULT_OBSERVABILITY_BREAKER_OPEN_SUCCESS_RATE
    )
    assert settings.observability_provider_health_drop_threshold == (
        DEFAULT_OBSERVABILITY_PROVIDER_HEALTH_DROP_THRESHOLD
    )
    assert settings.observability_outbox_backlog_threshold == (
        DEFAULT_OBSERVABILITY_OUTBOX_BACKLOG_THRESHOLD
    )
    assert settings.observability_queue_age_threshold_seconds == (
        DEFAULT_OBSERVABILITY_QUEUE_AGE_THRESHOLD_SECONDS
    )
    assert settings.observability_cost_outlier_multiple == (
        DEFAULT_OBSERVABILITY_COST_OUTLIER_MULTIPLE
    )
    assert settings.observability_cost_outlier_min_baseline_days == (
        DEFAULT_OBSERVABILITY_COST_OUTLIER_MIN_BASELINE_DAYS
    )
    assert settings.observability_provider_rate_limit_alert_count == (
        DEFAULT_OBSERVABILITY_PROVIDER_RATE_LIMIT_ALERT_COUNT
    )


def test_the_alert_thresholds_are_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """coding-standards §9.1: a limit a deployment must touch is an environment edit."""
    monkeypatch.setenv("OBSERVABILITY_BUDGET_ALERT_THRESHOLD_PCT", "60")
    monkeypatch.setenv("OBSERVABILITY_BREAKER_OPEN_SUCCESS_RATE", "0.7")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER_HEALTH_DROP_THRESHOLD", "0.1")
    monkeypatch.setenv("OBSERVABILITY_OUTBOX_BACKLOG_THRESHOLD", "100")
    monkeypatch.setenv("OBSERVABILITY_QUEUE_AGE_THRESHOLD_SECONDS", "300")
    monkeypatch.setenv("OBSERVABILITY_COST_OUTLIER_MULTIPLE", "4.5")
    monkeypatch.setenv("OBSERVABILITY_COST_OUTLIER_MIN_BASELINE_DAYS", "5")
    monkeypatch.setenv("OBSERVABILITY_PROVIDER_RATE_LIMIT_ALERT_COUNT", "3")

    settings = get_settings()

    assert settings.observability_budget_alert_threshold_pct == 60
    # A ratio stays a Decimal, so a threshold compared for equality against a
    # rolled figure carries no binary approximation.
    assert settings.observability_breaker_open_success_rate == Decimal("0.7")
    assert settings.observability_provider_health_drop_threshold == Decimal("0.1")
    assert settings.observability_outbox_backlog_threshold == 100
    assert settings.observability_queue_age_threshold_seconds == 300
    assert settings.observability_cost_outlier_multiple == Decimal("4.5")
    assert settings.observability_cost_outlier_min_baseline_days == 5
    assert settings.observability_provider_rate_limit_alert_count == 3


def test_a_threshold_outside_its_range_fails_closed_at_boot() -> None:
    """A percentage outside 0-100 is not a percentage, and a zero floor is silence."""
    with pytest.raises(ValueError, match="observability_budget_alert_threshold_pct"):
        Settings(observability_budget_alert_threshold_pct=0)
    with pytest.raises(ValueError, match="observability_breaker_open_success_rate"):
        Settings(observability_breaker_open_success_rate=Decimal("0"))
    with pytest.raises(ValueError, match="observability_provider_health_drop_threshold"):
        Settings(observability_provider_health_drop_threshold=Decimal("1"))
    with pytest.raises(ValueError, match="observability_outbox_backlog_threshold"):
        Settings(observability_outbox_backlog_threshold=0)
    with pytest.raises(ValueError, match="observability_queue_age_threshold_seconds"):
        Settings(observability_queue_age_threshold_seconds=0)
    with pytest.raises(ValueError, match="observability_cost_outlier_multiple"):
        Settings(observability_cost_outlier_multiple=Decimal("1"))
    with pytest.raises(ValueError, match="observability_cost_outlier_min_baseline_days"):
        Settings(observability_cost_outlier_min_baseline_days=0)
    with pytest.raises(ValueError, match="observability_provider_rate_limit_alert_count"):
        Settings(observability_provider_rate_limit_alert_count=0)


def test_a_malformed_ratio_threshold_fails_closed_at_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OBSERVABILITY_COST_OUTLIER_MULTIPLE", "three")

    with pytest.raises(ValueError, match="OBSERVABILITY_COST_OUTLIER_MULTIPLE"):
        get_settings()
