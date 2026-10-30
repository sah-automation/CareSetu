"""Security detector settings (PHASE-14B Batch 2, #779).

The scan is opt-in; its window, cooldown and every per-kind threshold are
environment limits. These tests pin the inert defaults, the env parsing, and the
positive-value validation that keeps a zero threshold from making an alert
permanent.
"""

from __future__ import annotations

import pytest

from app.config import (
    DEFAULT_SECURITY_DETECTION_ENABLED,
    DEFAULT_SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_COOLDOWN_SECONDS,
    DEFAULT_SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_WINDOW_MINUTES,
    Settings,
    get_settings,
)


def test_security_detector_defaults_are_inert() -> None:
    settings = Settings()

    assert settings.security_detection_enabled is DEFAULT_SECURITY_DETECTION_ENABLED
    assert settings.security_detection_enabled is False
    assert settings.security_detector_window_minutes == DEFAULT_SECURITY_DETECTOR_WINDOW_MINUTES
    assert settings.security_detector_cooldown_seconds == DEFAULT_SECURITY_DETECTOR_COOLDOWN_SECONDS
    assert (
        settings.security_detector_auth_failure_threshold
        == DEFAULT_SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD
    )
    assert (
        settings.security_detector_operator_mfa_failure_threshold
        == DEFAULT_SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD
    )
    assert (
        settings.security_detector_record_denial_threshold
        == DEFAULT_SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD
    )
    assert (
        settings.security_detector_rate_limit_threshold
        == DEFAULT_SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD
    )
    assert (
        settings.security_detector_prompt_injection_threshold
        == DEFAULT_SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD
    )


def test_security_detector_reads_every_value_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECURITY_DETECTION_ENABLED", "true")
    monkeypatch.setenv("SECURITY_DETECTOR_WINDOW_MINUTES", "30")
    monkeypatch.setenv("SECURITY_DETECTOR_COOLDOWN_SECONDS", "600")
    monkeypatch.setenv("SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD", "11")
    monkeypatch.setenv("SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD", "13")
    monkeypatch.setenv("SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD", "14")
    monkeypatch.setenv("SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD", "15")
    monkeypatch.setenv("SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD", "16")

    settings = get_settings()

    assert settings.security_detection_enabled is True
    assert settings.security_detector_window_minutes == 30
    assert settings.security_detector_cooldown_seconds == 600
    assert settings.security_detector_auth_failure_threshold == 11
    assert settings.security_detector_operator_mfa_failure_threshold == 13
    assert settings.security_detector_record_denial_threshold == 14
    assert settings.security_detector_rate_limit_threshold == 15
    assert settings.security_detector_prompt_injection_threshold == 16


@pytest.mark.parametrize(
    "field",
    [
        "security_detector_window_minutes",
        "security_detector_cooldown_seconds",
        "security_detector_auth_failure_threshold",
        "security_detector_operator_mfa_failure_threshold",
        "security_detector_record_denial_threshold",
        "security_detector_rate_limit_threshold",
        "security_detector_prompt_injection_threshold",
    ],
)
def test_security_detector_rejects_non_positive_limits(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        Settings(**{field: 0})
