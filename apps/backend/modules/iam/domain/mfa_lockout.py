"""MOD-001: operator TOTP failure lockout policy (PHASE-14B T17, ticket #778).

An operator proves possession of a TOTP device after the SMS code. Each wrong
code is a guess against a long-lived authenticator, so failures are counted on
the operator profile and a configured streak locks the login for a configured
period. The counter is stored on the profile row, not the session, because a
failed login issues no session and its transaction rolls back - the counter
must commit on its own.

This module is pure: the facade supplies the persisted counter and timestamps,
so unit tests pin the threshold and expiry without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_OPERATOR_MFA_LOCKOUT_THRESHOLD = 5
DEFAULT_OPERATOR_MFA_LOCKOUT_SECONDS = 900


@dataclass(frozen=True)
class OperatorMfaLockoutDecision:
    """Outcome of recording one more failed operator TOTP verification.

    ``counter`` is the new consecutive-failure count to persist,
    ``lockout_until`` is the active window end (``None`` when unlocked), and
    ``locked`` says whether the operator must be refused.
    """

    counter: int
    locked: bool
    lockout_until: datetime | None


def evaluate_mfa_failure(
    consecutive_failures: int,
    now: datetime,
    lockout_until: datetime | None,
    threshold: int,
    lockout_seconds: int,
) -> OperatorMfaLockoutDecision:
    """Decide the profile state after one more wrong operator TOTP code.

    ``consecutive_failures`` is the count persisted before this attempt. A
    failure at or above ``threshold`` starts a ``lockout_seconds`` window from
    ``now``. Once a window has fully elapsed (``now >= lockout_until``) the
    streak restarts at one, matching the phone lockout boundary and keeping a
    single mistake after the lockout lifts from re-locking the operator.

    The caller refuses an actively locked operator before verifying a code, so
    the in-window branch below is defensive: it counts the failure but never
    extends the existing window.
    """
    if lockout_until is not None and now < lockout_until:
        return OperatorMfaLockoutDecision(
            counter=consecutive_failures + 1,
            locked=True,
            lockout_until=lockout_until,
        )

    counter = 1 if lockout_until is not None else consecutive_failures + 1
    if counter >= threshold:
        return OperatorMfaLockoutDecision(
            counter=counter,
            locked=True,
            lockout_until=now + timedelta(seconds=lockout_seconds),
        )
    return OperatorMfaLockoutDecision(counter=counter, locked=False, lockout_until=None)
