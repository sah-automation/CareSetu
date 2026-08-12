"""PHASE-2 T4: OTP verification challenge machine (ticket #55, spec #51 §2.4).

The decision core of ``verify_otp`` is pure logic with no I/O, so unit tests
pin every transition of the machine without a database: a live Pending
challenge accepts exactly one correct guess (single-use), a wrong guess only
decrements the 5-attempt budget, the budget exhausted spends the challenge,
and a used/expired/spent challenge is rejected with the "request a new code"
outcome. The outbox write on success (``patient.verified``) vs failure
(``patient_auth_failed``) is the integration suite's job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from modules.iam.domain.otp import MAX_ATTEMPTS, OTP_TTL_SECONDS, hash_otp
from modules.iam.domain.verify import (
    CHALLENGE_EXPIRED,
    CHALLENGE_FAILED,
    CHALLENGE_PENDING,
    AttemptDecision,
    evaluate_attempt,
    failure_write_back,
    no_challenge_decision,
    suspended_decision,
)

_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_CODE = "654321"


def _challenge(
    *,
    status: str = "Pending",
    attempts: int = 0,
    expires_at: datetime | None = None,
    guess: str = _CODE,
) -> AttemptDecision:
    return evaluate_attempt(
        status=status,
        attempts=attempts,
        expires_at=expires_at or (_NOW + timedelta(seconds=OTP_TTL_SECONDS)),
        now=_NOW,
        guess=guess,
        stored_hash=hash_otp(_CODE),
    )


def test_correct_code_verifies_a_live_challenge() -> None:
    decision = _challenge()

    assert decision.outcome == "verified"
    assert decision.reason is None
    assert decision.attempts_left is None


def test_correct_code_consumes_the_challenge_on_replay() -> None:
    # A second submission of the same code against a now-Verified challenge is
    # a rejection, never a second verification (single-use).
    decision = _challenge(status="Verified")

    assert decision.outcome == "expired"
    assert decision.reason == "replay"


def test_wrong_code_decrements_the_budget_but_keeps_the_code_alive() -> None:
    decision = _challenge(guess="000000")

    assert decision.outcome == "wrong_code"
    assert decision.reason == "wrong_code"
    assert decision.attempts_left == MAX_ATTEMPTS - 1


def test_wrong_code_tracks_prior_attempts() -> None:
    decision = _challenge(attempts=3, guess="000000")

    assert decision.outcome == "wrong_code"
    assert decision.attempts_left == MAX_ATTEMPTS - 4


def test_budget_exhausted_spends_the_challenge() -> None:
    decision = _challenge(attempts=MAX_ATTEMPTS - 1, guess="000000")

    assert decision.outcome == "spent"
    assert decision.reason == "spent"
    assert decision.attempts_left == 0


def test_spent_challenge_is_rejected_with_request_new_code() -> None:
    decision = _challenge(status="Failed", guess=_CODE)

    assert decision.outcome == "expired"
    assert decision.reason == "spent"


def test_expired_challenge_is_rejected() -> None:
    decision = _challenge(expires_at=_NOW)

    assert decision.outcome == "expired"
    assert decision.reason == "expired"


def test_expired_challenge_at_exact_ttl_is_rejected() -> None:
    decision = _challenge(expires_at=_NOW - timedelta(seconds=1))

    assert decision.outcome == "expired"


def test_already_expired_status_is_rejected() -> None:
    decision = _challenge(status="Expired", guess=_CODE)

    assert decision.outcome == "expired"
    assert decision.reason == "expired"


def test_expired_challenge_still_counts_no_budget() -> None:
    decision = _challenge(attempts=2, expires_at=_NOW - timedelta(minutes=1))

    assert decision.attempts_left is None


def test_no_challenge_decision_asks_for_a_new_code() -> None:
    decision = no_challenge_decision()

    assert decision.outcome == "expired"
    assert decision.reason == "no_challenge"
    assert decision.attempts_left is None


def test_suspended_decision_refuses_verification() -> None:
    decision = suspended_decision()

    assert decision.outcome == "expired"
    assert decision.reason == "suspended"
    assert decision.attempts_left is None


def test_unknown_challenge_status_is_rejected_not_raised() -> None:
    decision = _challenge(status="Bogus")

    assert decision.outcome == "expired"


def test_write_back_for_wrong_code_only_counts_the_budget() -> None:
    write_back = failure_write_back(
        AttemptDecision(outcome="wrong_code", reason="wrong_code", attempts_left=3),
        status=CHALLENGE_PENDING,
        attempts=1,
    )

    assert write_back.attempts == 2
    assert write_back.status is None


def test_write_back_for_spent_flips_the_challenge_to_failed() -> None:
    write_back = failure_write_back(
        AttemptDecision(outcome="spent", reason="spent", attempts_left=0),
        status=CHALLENGE_PENDING,
        attempts=4,
    )

    assert write_back.attempts == 5
    assert write_back.status == CHALLENGE_FAILED


def test_write_back_for_time_expired_marks_the_row_expired() -> None:
    write_back = failure_write_back(
        AttemptDecision(outcome="expired", reason="expired"),
        status=CHALLENGE_PENDING,
        attempts=0,
    )

    assert write_back.attempts is None
    assert write_back.status == CHALLENGE_EXPIRED


def test_write_back_for_replay_leaves_the_dead_row_alone() -> None:
    write_back = failure_write_back(
        AttemptDecision(outcome="expired", reason="replay"),
        status="Verified",
        attempts=0,
    )

    assert write_back.attempts is None
    assert write_back.status is None


def test_write_back_for_spent_challenge_does_not_increment_again() -> None:
    write_back = failure_write_back(
        AttemptDecision(outcome="expired", reason="spent"),
        status=CHALLENGE_FAILED,
        attempts=5,
    )

    assert write_back.attempts is None
    assert write_back.status is None
