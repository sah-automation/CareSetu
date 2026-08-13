"""MOD-001: resend-OTP decision machine (PHASE-2 T5, ticket #56).

The pure gate for ``resend_otp`` per spec #51 §2.4: a resend is refused while
the phone is in the brute-force lockout, refused while the per-phone resend
cooldown (>= 60 s from the last issuance) is active, and refused outright for
a Suspended identity - ``Suspended`` is operator-only state, not something an
OTP flow can move past. A pass authorizes the facade to invalidate the pending
challenge (latest-wins) and issue a fresh one. No I/O here, so unit tests pin
the cooldown boundary and the lockout precedence without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Literal

from modules.iam.domain.lockout import lockout_remaining_seconds
from modules.iam.domain.verify import IDENTITY_SUSPENDED

ResendOutcome = Literal["sent", "cooldown", "locked", "suspended"]


@dataclass(frozen=True)
class ResendDecision:
    """Outcome of evaluating one resend request against the identity state.

    Only ``sent`` proceeds to issue a challenge; ``cooldown`` and ``locked``
    carry the seconds the PWA's disable states and countdowns need.
    """

    outcome: ResendOutcome
    cooldown_remaining_seconds: int | None = None
    lockout_remaining_seconds: int | None = None


def evaluate_resend(
    *,
    identity_status: str,
    lockout_until: datetime | None,
    cooldown_until: datetime | None,
    now: datetime,
) -> ResendDecision:
    """Gate a resend against Suspended, lockout, then cooldown.

    Precedence is deliberate: Suspended identity state wins over every
    counter, and the brute-force lockout wins over the resend cooldown (a
    locked phone must not burn its cooldown timer on a refused resend).
    Cooldown is measured from the last issuance - the latest challenge's
    ``cooldown_until`` - so a resend exactly at ``cooldown_until`` is allowed.
    """
    if identity_status == IDENTITY_SUSPENDED:
        return ResendDecision(outcome="suspended")
    lockout_left = lockout_remaining_seconds(lockout_until, now)
    if lockout_left is not None:
        return ResendDecision(outcome="locked", lockout_remaining_seconds=lockout_left)
    if cooldown_until is not None and now < cooldown_until:
        return ResendDecision(
            outcome="cooldown",
            cooldown_remaining_seconds=ceil((cooldown_until - now).total_seconds()),
        )
    return ResendDecision(outcome="sent")
