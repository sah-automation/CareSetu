"""METRICS #916: Prometheus remote-write exporter selection logic.

Verifies the priority order for metrics exporter selection:
1. PROMETHEUS_REMOTE_WRITE_ENDPOINT set -> Prometheus remote-write exporter
2. OTEL_EXPORTER_OTLP_ENDPOINT set -> OTLP metric exporter (existing behavior)
3. Neither set -> metrics disabled (inert)
"""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, MetricReader

from app.config import Settings
from observability import otel
from observability.otel import init_metrics

# --- fakes -------------------------------------------------------------------


class _NoOpMetricReader(MetricReader):
    """A thread-free real ``MetricReader`` seam for the reader slot."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        super().__init__()

    def _receive_metrics(  # type: ignore[no-untyped-def]
        self, metrics, timeout_millis: int = 10000
    ) -> bool:
        del metrics, timeout_millis
        return True

    def shutdown(self) -> None:
        return


# --- test fixture ------------------------------------------------------------


@pytest.fixture
def otel_metrics_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reset the once-per-process metrics init guard around each test."""
    monkeypatch.setattr(otel, "_metrics_configured", False)
    monkeypatch.setattr(otel, "_metrics_enabled", False)
    monkeypatch.setattr(otel, "_meter_provider", None)
    monkeypatch.setattr(otel, "_instruments", {})
    yield


# --- vendor gate: METRICS_ENABLED off = inert --------------------------------


def test_init_metrics_is_inert_when_disabled(
    otel_metrics_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When METRICS_ENABLED=false, no exporter is wired regardless of endpoints."""
    set_calls: list[Any] = []
    monkeypatch.setattr(
        "opentelemetry.metrics.set_meter_provider",
        lambda provider: set_calls.append(provider),
    )

    settings = Settings(
        metrics_enabled=False,
        prometheus_remote_write_endpoint="https://prom.invalid/api/prom/push",
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/metrics",
    )
    assert init_metrics(settings) is False

    assert otel._metrics_enabled is False
    assert otel._meter_provider is None
    assert set_calls == []


# --- priority 1: Prometheus remote-write -------------------------------------


def test_prometheus_remote_write_chosen_when_endpoint_set(
    otel_metrics_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When PROMETHEUS_REMOTE_WRITE_ENDPOINT is set, Prometheus exporter is used."""
    captured: dict[str, Any] = {}

    class _FakePromExporter:
        def __init__(self, endpoint: str, headers: dict[str, str]) -> None:
            captured["exporter"] = "prometheus_remote_write"
            captured["endpoint"] = endpoint
            captured["headers"] = headers

        def force_flush(self, timeout_millis: int | None = None) -> bool:
            del timeout_millis
            return True

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(
        "opentelemetry.exporter.prometheus_remote_write.PrometheusRemoteWriteMetricsExporter",
        _FakePromExporter,
    )
    monkeypatch.setattr(
        "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader", _NoOpMetricReader
    )
    monkeypatch.setattr("opentelemetry.metrics.set_meter_provider", lambda provider: None)

    settings = Settings(
        metrics_enabled=True,
        prometheus_remote_write_endpoint="https://prom.invalid/api/prom/push",
        prometheus_remote_write_headers=("Authorization=Basic dGVzdA==",),
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/metrics",
    )
    assert init_metrics(settings) is True

    assert captured["exporter"] == "prometheus_remote_write"
    assert captured["endpoint"] == "https://prom.invalid/api/prom/push"
    assert captured["headers"] == {"Authorization": "Basic dGVzdA=="}
    assert otel._metrics_enabled is True


def test_prometheus_remote_write_with_headers_parsed_correctly(
    otel_metrics_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prometheus remote-write headers are parsed using the same CSV logic as OTLP."""
    captured: dict[str, Any] = {}

    class _FakePromExporter:
        def __init__(self, endpoint: str, headers: dict[str, str]) -> None:
            captured["endpoint"] = endpoint
            captured["headers"] = headers

        def force_flush(self, timeout_millis: int | None = None) -> bool:
            del timeout_millis
            return True

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(
        "opentelemetry.exporter.prometheus_remote_write.PrometheusRemoteWriteMetricsExporter",
        _FakePromExporter,
    )
    monkeypatch.setattr(
        "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader", _NoOpMetricReader
    )
    monkeypatch.setattr("opentelemetry.metrics.set_meter_provider", lambda provider: None)

    settings = Settings(
        metrics_enabled=True,
        prometheus_remote_write_endpoint="https://prom.invalid/api/prom/push",
        prometheus_remote_write_headers=(
            "Authorization=Basic dGVzdA==",
            "x-api-key=test-key",
        ),
    )
    assert init_metrics(settings) is True

    assert captured["headers"] == {
        "Authorization": "Basic dGVzdA==",
        "x-api-key": "test-key",
    }


# --- priority 2: OTLP fallback -----------------------------------------------


def test_otlp_chosen_when_only_otlp_endpoint_set(
    otel_metrics_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When only OTEL_EXPORTER_OTLP_ENDPOINT is set, OTLP exporter is used."""
    captured: dict[str, Any] = {}

    class _FakeOtlpExporter:
        def __init__(self, endpoint: str, headers: dict[str, str]) -> None:
            captured["exporter"] = "otlp"
            captured["endpoint"] = endpoint
            captured["headers"] = headers

        def force_flush(self, timeout_millis: int | None = None) -> bool:
            del timeout_millis
            return True

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter",
        _FakeOtlpExporter,
    )
    monkeypatch.setattr(
        "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader", _NoOpMetricReader
    )
    monkeypatch.setattr("opentelemetry.metrics.set_meter_provider", lambda provider: None)

    settings = Settings(
        metrics_enabled=True,
        prometheus_remote_write_endpoint="",
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/metrics",
        otel_exporter_otlp_headers=("Authorization=Basic dGVzdA==",),
    )
    assert init_metrics(settings) is True

    assert captured["exporter"] == "otlp"
    assert captured["endpoint"] == "https://otlp.invalid/v1/metrics"
    assert captured["headers"] == {"Authorization": "Basic dGVzdA=="}
    assert otel._metrics_enabled is True


# --- priority 3: neither set = disabled --------------------------------------


def test_metrics_disabled_when_no_endpoint_configured(
    otel_metrics_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When neither endpoint is set, metrics export is disabled."""
    set_calls: list[Any] = []
    monkeypatch.setattr(
        "opentelemetry.metrics.set_meter_provider",
        lambda provider: set_calls.append(provider),
    )

    settings = Settings(
        metrics_enabled=True,
        prometheus_remote_write_endpoint="",
        otel_exporter_otlp_endpoint="",
    )
    assert init_metrics(settings) is False

    assert otel._metrics_enabled is False
    assert otel._meter_provider is None
    assert set_calls == []


def test_metrics_disabled_when_endpoints_blank_whitespace(
    otel_metrics_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank/whitespace endpoints are treated as unset."""
    set_calls: list[Any] = []
    monkeypatch.setattr(
        "opentelemetry.metrics.set_meter_provider",
        lambda provider: set_calls.append(provider),
    )

    settings = Settings(
        metrics_enabled=True,
        prometheus_remote_write_endpoint="   ",
        otel_exporter_otlp_endpoint="  ",
    )
    assert init_metrics(settings) is False

    assert otel._metrics_enabled is False
    assert set_calls == []


# --- test seam: metric_reader override ---------------------------------------


def test_metric_reader_override_bypasses_exporter_selection(
    otel_metrics_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When metric_reader is supplied, it is used directly (test seam)."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "opentelemetry.metrics.set_meter_provider",
        lambda provider: captured.setdefault("provider", provider),
    )

    settings = Settings(
        metrics_enabled=True,
        prometheus_remote_write_endpoint="https://prom.invalid/api/prom/push",
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/metrics",
    )
    reader = InMemoryMetricReader()
    assert init_metrics(settings, metric_reader=reader) is True

    # The supplied reader should be used (no exporter instantiated)
    provider = captured["provider"]
    assert provider._metric_readers == [reader]
    assert otel._metrics_enabled is True


# --- backward compatibility --------------------------------------------------


def test_existing_otlp_only_deployment_still_works(
    otel_metrics_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing OTLP-only deployments (no PROMETHEUS_REMOTE_WRITE_ENDPOINT) work unchanged."""
    captured: dict[str, Any] = {}

    class _FakeOtlpExporter:
        def __init__(self, endpoint: str, headers: dict[str, str]) -> None:
            captured["exporter"] = "otlp"
            captured["endpoint"] = endpoint

        def force_flush(self, timeout_millis: int | None = None) -> bool:
            del timeout_millis
            return True

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter",
        _FakeOtlpExporter,
    )
    monkeypatch.setattr(
        "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader", _NoOpMetricReader
    )
    monkeypatch.setattr("opentelemetry.metrics.set_meter_provider", lambda provider: None)

    # Simulate existing deployment: only OTLP vars set
    settings = Settings(
        metrics_enabled=True,
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/metrics",
        otel_exporter_otlp_headers=("Authorization=Basic dGVzdA==",),
        # prometheus_remote_write_endpoint defaults to ""
    )
    assert init_metrics(settings) is True

    assert captured["exporter"] == "otlp"
    assert otel._metrics_enabled is True
