"""MOD-001: brute-force phone lockout counter (PHASE-2 T5, ticket #56).

The lockout contract from spec #51 §2.4: ten consecutive verification
failures across challenges trigger a 15-minute temporary phone lockout. The
lockout is a counter, never identity state - ``Suspended`` stays an identity
status reachable only via the operator status-change interface (Phase 5). The
counter lives on the identity row so it survives challenge replacement
(resend is latest-wins); only a successful verification resets it, so the
failures stay "consecutive". Everything here is pure logic with no I/O so unit
tests pin the threshold, the expiry, and the remaining-time boundary without a
database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil

LOCKOUT_THRESHOLD = 10
LOCKOUT_SECONDS = 900


@dataclass(frozen=True)
class LockoutDecision:
    """Outcome of recording one more verification failure.

    ``locked`` is True when this failure crossed the threshold and ``now`` is
    the start of the 15-minute window (``lockout_until``). ``counter`` is the
    new consecutive-failure count to persist on the identity.
    """

    locked: bool
    counter: int
    lockout_until: datetime | None


def evaluate_failure(consecutive_failures: int, now: datetime) -> LockoutDecision:
    """Decide whether the next failure triggers a lockout.

    ``consecutive_failures`` is the count persisted on the identity before this
    attempt. The counter keeps growing past the threshold so that, once a
    lockout expires, any further failure immediately re-locks (the prototype's
    ``submitOtp`` contract, otpState.ts).
    """
    counter = consecutive_failures + 1
    if counter >= LOCKOUT_THRESHOLD:
        return LockoutDecision(
            locked=True,
            counter=counter,
            lockout_until=now + timedelta(seconds=LOCKOUT_SECONDS),
        )
    return LockoutDecision(locked=False, counter=counter, lockout_until=None)


def lockout_remaining_seconds(lockout_until: datetime | None, now: datetime) -> int | None:
    """Seconds until the lockout lifts, or None when the phone is not locked.

    ``None`` covers both "never locked" and "lockout already expired" so a
    caller can treat any non-None value as an active lockout. The boundary is
    inclusive: at ``now == lockout_until`` the lockout has ended.
    """
    if lockout_until is None or now >= lockout_until:
        return None
    seconds = (lockout_until - now).total_seconds()
    return max(1, ceil(seconds))
