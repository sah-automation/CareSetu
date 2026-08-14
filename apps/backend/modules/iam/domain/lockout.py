"""MOD-001: brute-force phone lockout counter (PHASE-2 T5, ticket #56).

The lockout contract from spec #51 §2.4: ten consecutive verification
failures across challenges trigger a 15-minute temporary phone lockout. The
lockout is a counter, never identity state - ``Suspended`` stays an identity
status reachable only via the operator status-change interface (Phase 5). The
counter lives on the identity row so it survives challenge replacement
(resend is latest-wins); a successful verification resets it and so does the
window lifting - once the 15 minutes have fully elapsed, the next failure
starts a fresh streak, so a single mistake after the lockout lifts never
re-locks the phone. Everything here is pure logic with no I/O so unit tests
pin the threshold, the expiry, and the remaining-time boundary without a
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


def evaluate_failure(
    consecutive_failures: int, now: datetime, lockout_until: datetime | None
) -> LockoutDecision:
    """Decide whether the next failure triggers a lockout.

    ``consecutive_failures`` is the count persisted on the identity before this
    attempt and ``lockout_until`` is when the active window ends (``None`` when
    the phone is not locked). The facade refuses a locked phone outright - under
    its ``FOR UPDATE`` identity lock it consults ``lockout_remaining_seconds``
    and rejects before ever calling this - so ``evaluate_failure`` is never
    reached with an open window: the in-window growth line below is defensive.
    It exists only so a caller
    that did pass an open window grows the counter rather than corrupting it,
    matching the ``submitOtp`` contract (otpState.ts); in-window attempts never
    extend ``lockout_until``, so the lockout is genuinely temporary (ADR-0004
    decision 4). Once the window has fully elapsed (``now >= lockout_until``)
    the streak resets to a fresh count, so a single mistake after a lockout
    lifts never re-locks the phone (spec #51 §2.4). The boundary is inclusive
    and matches ``lockout_remaining_seconds``: at ``now == lockout_until`` the
    lockout has ended and the failure starts a new streak.
    """
    counter = 1 if lockout_until is not None and now >= lockout_until else consecutive_failures + 1
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
