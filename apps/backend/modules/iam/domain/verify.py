"""MOD-001: OTP verification challenge machine (PHASE-2 T4, ticket #55).

The decision core of ``verify_otp`` per the challenge contract in spec #51
§2.4: a challenge is single-use with a 5-attempt budget and a 5-minute TTL.
Only a ``Pending`` challenge within its TTL is live. A correct guess consumes
it (``[Pending] -> [Verified]``); a wrong guess only decrements the budget -
the code stays alive - and the challenge is ``[Failed]`` (spent) at budget 0.
A used (replayed), expired, or spent challenge is rejected with the
"request a new code" outcome. Everything here is pure logic with no I/O so
unit tests pin every transition without a database. The challenge-state
vocabulary and the row write-back that persists a rejected attempt live here
too, so the machine stays the single source of truth for its transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from modules.iam.domain.otp import MAX_ATTEMPTS, verify_otp

Outcome = Literal["verified", "wrong_code", "expired", "spent", "locked"]

FailureReason = Literal[
    "wrong_code", "expired", "spent", "replay", "no_challenge", "suspended", "locked"
]

CHALLENGE_PENDING = "Pending"
CHALLENGE_VERIFIED = "Verified"
CHALLENGE_EXPIRED = "Expired"
CHALLENGE_FAILED = "Failed"

IDENTITY_ACTIVE = "Active"
IDENTITY_SUSPENDED = "Suspended"


@dataclass(frozen=True)
class AttemptDecision:
    """Outcome of evaluating one submitted code against a stored challenge.

    ``reason`` and ``attempts_left`` are only meaningful for failures:
    ``reason`` names the failure for the ``patient.auth_failed`` event and
    ``attempts_left`` is the remaining budget after a wrong guess (0 when the
    budget is exhausted and the challenge is spent).
    """

    outcome: Outcome
    reason: FailureReason | None = None
    attempts_left: int | None = None


@dataclass(frozen=True)
class ChallengeWriteBack:
    """The challenge-row changes that persist a rejected attempt.

    ``None`` fields mean "leave the column unchanged"; only genuine wrong
    guesses consume budget, and expired/replayed rows are already dead.
    """

    attempts: int | None = None
    status: str | None = None


def evaluate_attempt(
    *,
    status: str,
    attempts: int,
    expires_at: datetime,
    now: datetime,
    guess: str,
    stored_hash: str,
) -> AttemptDecision:
    """Decide the outcome of a submitted code against a stored challenge.

    ``status`` must be one of the challenge machine's states (Pending,
    Verified, Expired, Failed). A correct guess on a live challenge returns
    ``verified``; every other input - a wrong guess, an out-of-TTL challenge,
    or a challenge that is already verified/expired/failed - is a rejection.
    """
    if status != CHALLENGE_PENDING:
        if status == CHALLENGE_VERIFIED:
            return AttemptDecision(outcome="expired", reason="replay")
        reason: FailureReason = "spent" if status == CHALLENGE_FAILED else "expired"
        return AttemptDecision(outcome="expired", reason=reason)
    if now >= expires_at:
        return AttemptDecision(outcome="expired", reason="expired")
    if verify_otp(guess, stored_hash):
        return AttemptDecision(outcome="verified")
    next_attempts = attempts + 1
    if next_attempts >= MAX_ATTEMPTS:
        return AttemptDecision(outcome="spent", reason="spent", attempts_left=0)
    return AttemptDecision(
        outcome="wrong_code",
        reason="wrong_code",
        attempts_left=MAX_ATTEMPTS - next_attempts,
    )


def failure_write_back(
    decision: AttemptDecision, *, status: str, attempts: int
) -> ChallengeWriteBack:
    """Map a rejected attempt to the challenge-row changes that persist it.

    Only wrong guesses (``wrong_code``/``spent``) count against the budget; an
    expired or replayed challenge is already dead, so its ``attempts`` is
    untouched. A spent budget flips the row to ``Failed``; a time-expired
    ``Pending`` row is lazily marked ``Expired``. Replays leave the row alone.
    """
    next_attempts = attempts + 1 if decision.outcome in ("wrong_code", "spent") else None
    next_status: str | None = None
    if decision.outcome == "spent":
        next_status = CHALLENGE_FAILED
    elif decision.outcome == "expired" and status == CHALLENGE_PENDING:
        next_status = CHALLENGE_EXPIRED
    return ChallengeWriteBack(attempts=next_attempts, status=next_status)


def no_challenge_decision() -> AttemptDecision:
    """Outcome when no challenge exists for the phone (nothing to verify)."""
    return AttemptDecision(outcome="expired", reason="no_challenge")


def suspended_decision() -> AttemptDecision:
    """Outcome when the identity is Suspended: verification is refused.

    The identity machine is ``[Unverified] -> [Active] -> [Suspended]``
    (internal-modules.md §3.1); ``Suspended`` is reachable only via the
    operator status-change interface (spec #51 §2.4, Phase 5), so no OTP
    verification can move an identity out of it. The attempt is rejected
    without touching the challenge.
    """
    return AttemptDecision(outcome="expired", reason="suspended")


def locked_decision() -> AttemptDecision:
    """Outcome when the phone is in the brute-force lockout: verification refused.

    Distinct from ``Suspended`` (spec #51 §2.4): the lockout is a temporary
    15-minute counter, never identity state, so the identity row's ``status``
    is untouched and the lockout lifts on its own. The attempt is rejected
    without touching the challenge or the counter.
    """
    return AttemptDecision(outcome="locked", reason="locked")
