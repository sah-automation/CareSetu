"""MOD-001: pure-logic TOTP verification (S8, #261).

Pins the TOTP verify/generate logic against pyotp without a database
(coding-standards S2: DB-free unit surface).  Tests exercise the injectable
clock and drift window to prove RFC-6238 acceptance/rejection without
sleeping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from modules.iam.domain.totp import (
    DEFAULT_DRIFT_WINDOW,
    TOTP_INTERVAL,
    TotpSecretEmptyError,
    TotpVerificationError,
    generate_secret,
    verify_totp,
)

_T0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
_SECRET = "JBSWY3DPEHPK3PXP"


class _FixedClock:
    """Injectable clock for deterministic TOTP window tests."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


def test_generate_secret_returns_base32_string() -> None:
    secret = generate_secret()
    assert len(secret) == 32
    assert pyotp.TOTP(secret).now().isdigit()


def test_valid_code_at_current_time_accepted() -> None:
    totp = pyotp.TOTP(_SECRET)
    code = totp.at(_T0)
    clock = _FixedClock(_T0)

    verify_totp(_SECRET, code, clock=clock)


def test_valid_code_one_step_ahead_accepted() -> None:
    totp = pyotp.TOTP(_SECRET)
    future = _T0 + timedelta(seconds=TOTP_INTERVAL)
    code = totp.at(future)
    clock = _FixedClock(_T0)

    # Default drift window = 1: t+1 is accepted.
    verify_totp(_SECRET, code, clock=clock)


def test_valid_code_one_step_behind_accepted() -> None:
    totp = pyotp.TOTP(_SECRET)
    past = _T0 - timedelta(seconds=TOTP_INTERVAL)
    code = totp.at(past)
    clock = _FixedClock(_T0)

    verify_totp(_SECRET, code, clock=clock)


def test_code_two_steps_ahead_rejected() -> None:
    totp = pyotp.TOTP(_SECRET)
    future = _T0 + timedelta(seconds=TOTP_INTERVAL * 2)
    code = totp.at(future)
    clock = _FixedClock(_T0)

    with pytest.raises(TotpVerificationError):
        verify_totp(_SECRET, code, clock=clock)


def test_code_two_steps_behind_rejected() -> None:
    totp = pyotp.TOTP(_SECRET)
    past = _T0 - timedelta(seconds=TOTP_INTERVAL * 2)
    code = totp.at(past)
    clock = _FixedClock(_T0)

    with pytest.raises(TotpVerificationError):
        verify_totp(_SECRET, code, clock=clock)


def test_wrong_code_rejected() -> None:
    clock = _FixedClock(_T0)

    with pytest.raises(TotpVerificationError):
        verify_totp(_SECRET, "000000", clock=clock)


def test_empty_secret_raises_totp_secret_empty_error() -> None:
    clock = _FixedClock(_T0)

    with pytest.raises(TotpSecretEmptyError):
        verify_totp("", "000000", clock=clock)


def test_whitespace_only_secret_raises_totp_secret_empty_error() -> None:
    clock = _FixedClock(_T0)

    with pytest.raises(TotpSecretEmptyError):
        verify_totp("   ", "000000", clock=clock)


def test_custom_drift_window_zero_accepts_only_exact_step() -> None:
    totp = pyotp.TOTP(_SECRET)
    code = totp.at(_T0)
    clock = _FixedClock(_T0)

    # drift_window=0: only the exact current step is accepted.
    verify_totp(_SECRET, code, clock=clock, drift_window=0)

    past = _T0 - timedelta(seconds=TOTP_INTERVAL)
    stale_code = totp.at(past)
    with pytest.raises(TotpVerificationError):
        verify_totp(_SECRET, stale_code, clock=clock, drift_window=0)


def test_default_drift_window_constant_is_one() -> None:
    assert DEFAULT_DRIFT_WINDOW == 1
