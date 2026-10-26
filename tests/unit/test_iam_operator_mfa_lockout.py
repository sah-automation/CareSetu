"""Operator TOTP lockout policy (PHASE-14B T17, ticket #778)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings, get_settings
from modules.iam.domain.mfa_lockout import evaluate_mfa_failure

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
THRESHOLD = 5
SECONDS = 900


def test_failure_below_threshold_counts_without_locking() -> None:
    decision = evaluate_mfa_failure(
        consecutive_failures=2,
        now=NOW,
        lockout_until=None,
        threshold=THRESHOLD,
        lockout_seconds=SECONDS,
    )

    assert decision.counter == 3
    assert decision.locked is False
    assert decision.lockout_until is None


def test_failure_at_threshold_locks_for_configured_seconds() -> None:
    decision = evaluate_mfa_failure(
        consecutive_failures=THRESHOLD - 1,
        now=NOW,
        lockout_until=None,
        threshold=THRESHOLD,
        lockout_seconds=SECONDS,
    )

    assert decision.counter == THRESHOLD
    assert decision.locked is True
    assert decision.lockout_until == NOW + timedelta(seconds=SECONDS)


def test_first_failure_after_expiry_starts_a_fresh_streak() -> None:
    decision = evaluate_mfa_failure(
        consecutive_failures=THRESHOLD,
        now=NOW,
        lockout_until=NOW - timedelta(seconds=1),
        threshold=THRESHOLD,
        lockout_seconds=SECONDS,
    )

    assert decision.counter == 1
    assert decision.locked is False
    assert decision.lockout_until is None


def test_active_window_is_not_extended_by_another_failure() -> None:
    active_until = NOW + timedelta(minutes=5)

    decision = evaluate_mfa_failure(
        consecutive_failures=THRESHOLD,
        now=NOW,
        lockout_until=active_until,
        threshold=THRESHOLD,
        lockout_seconds=SECONDS,
    )

    assert decision.counter == THRESHOLD + 1
    assert decision.locked is True
    assert decision.lockout_until == active_until


@pytest.mark.parametrize("threshold", [0, -1])
def test_settings_reject_non_positive_mfa_lockout_threshold(threshold: int) -> None:
    with pytest.raises(ValueError, match="iam_operator_mfa_lockout_threshold must be at least 1"):
        Settings(iam_operator_mfa_lockout_threshold=threshold)


@pytest.mark.parametrize("seconds", [0, -1])
def test_settings_reject_non_positive_mfa_lockout_seconds(seconds: int) -> None:
    with pytest.raises(ValueError, match="iam_operator_mfa_lockout_seconds must be positive"):
        Settings(iam_operator_mfa_lockout_seconds=seconds)


def test_settings_read_operator_mfa_lockout_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IAM_OPERATOR_MFA_LOCKOUT_THRESHOLD", "7")
    monkeypatch.setenv("IAM_OPERATOR_MFA_LOCKOUT_SECONDS", "120")

    settings = get_settings()

    assert settings.iam_operator_mfa_lockout_threshold == 7
    assert settings.iam_operator_mfa_lockout_seconds == 120
