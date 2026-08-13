"""PHASE-2 T5: brute-force lockout machine (ticket #56, spec #51 §2.4).

The lockout is a pure counter decision - ten consecutive verification failures
across challenges trigger a 15-minute temporary phone lockout - so unit tests
pin the threshold, the expiry, and the remaining-time boundary without a
database. The counter persists across challenges and is reset only by a
successful verification (the facade's job), which is what makes the failures
"consecutive".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from modules.iam.domain.lockout import (
    LOCKOUT_SECONDS,
    LOCKOUT_THRESHOLD,
    evaluate_failure,
    lockout_remaining_seconds,
)

_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)


def test_failures_below_threshold_do_not_lock() -> None:
    decision = evaluate_failure(LOCKOUT_THRESHOLD - 2, _NOW)

    assert decision.locked is False
    assert decision.counter == LOCKOUT_THRESHOLD - 1
    assert decision.lockout_until is None


def test_exactly_threshold_triggers_lockout() -> None:
    decision = evaluate_failure(LOCKOUT_THRESHOLD - 1, _NOW)

    assert decision.locked is True
    assert decision.counter == LOCKOUT_THRESHOLD
    assert decision.lockout_until == _NOW + timedelta(seconds=LOCKOUT_SECONDS)


def test_first_failure_counts_one() -> None:
    decision = evaluate_failure(0, _NOW)

    assert decision.locked is False
    assert decision.counter == 1
    assert decision.lockout_until is None


def test_failure_after_lockout_expired_relocks_immediately() -> None:
    # The counter keeps growing past the threshold, so once a lockout expires
    # any further failure re-locks (otpState.ts submitOtp contract).
    decision = evaluate_failure(LOCKOUT_THRESHOLD, _NOW)

    assert decision.locked is True
    assert decision.counter == LOCKOUT_THRESHOLD + 1
    assert decision.lockout_until == _NOW + timedelta(seconds=LOCKOUT_SECONDS)


def test_remaining_is_none_when_never_locked() -> None:
    assert lockout_remaining_seconds(None, _NOW) is None


def test_remaining_counts_down_while_locked() -> None:
    lockout_until = _NOW + timedelta(seconds=900)

    remaining = lockout_remaining_seconds(lockout_until, _NOW)

    assert remaining is not None
    assert remaining > 0
    assert remaining <= 900


def test_remaining_is_none_at_exact_expiry_boundary() -> None:
    lockout_until = _NOW

    assert lockout_remaining_seconds(lockout_until, _NOW) is None


def test_remaining_is_none_after_expiry() -> None:
    lockout_until = _NOW - timedelta(seconds=1)

    assert lockout_remaining_seconds(lockout_until, _NOW) is None
