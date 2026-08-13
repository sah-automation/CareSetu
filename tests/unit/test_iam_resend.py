"""PHASE-2 T5: resend-OTP decision machine (ticket #56, spec #51 §2.4).

``evaluate_resend`` is pure logic with no I/O: it gates a resend against
operator state (Suspended), the brute-force lockout, then the >= 60 s resend
cooldown measured from the last issuance. Unit tests pin the cooldown boundary
and the precedence order; the DB-backed issuance (latest-wins, outbox rows) is
the integration suite's job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from modules.iam.domain.resend import evaluate_resend

_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_LOCKED_UNTIL = _NOW + timedelta(minutes=15)
_COOLDOWN_UNTIL = _NOW + timedelta(seconds=60)


def test_sent_when_nothing_blocks() -> None:
    decision = evaluate_resend(
        identity_status="Unverified",
        lockout_until=None,
        cooldown_until=None,
        now=_NOW,
    )

    assert decision.outcome == "sent"
    assert decision.cooldown_remaining_seconds is None
    assert decision.lockout_remaining_seconds is None


def test_suspended_beats_every_counter() -> None:
    decision = evaluate_resend(
        identity_status="Suspended",
        lockout_until=_LOCKED_UNTIL,
        cooldown_until=_COOLDOWN_UNTIL,
        now=_NOW,
    )

    assert decision.outcome == "suspended"
    assert decision.cooldown_remaining_seconds is None
    assert decision.lockout_remaining_seconds is None


def test_locked_beats_cooldown() -> None:
    decision = evaluate_resend(
        identity_status="Active",
        lockout_until=_LOCKED_UNTIL,
        cooldown_until=_COOLDOWN_UNTIL,
        now=_NOW,
    )

    assert decision.outcome == "locked"
    assert decision.lockout_remaining_seconds is not None
    assert decision.cooldown_remaining_seconds is None


def test_cooldown_active_blocks_and_reports_seconds() -> None:
    decision = evaluate_resend(
        identity_status="Active",
        lockout_until=None,
        cooldown_until=_NOW + timedelta(seconds=45),
        now=_NOW,
    )

    assert decision.outcome == "cooldown"
    assert decision.cooldown_remaining_seconds == 45


def test_cooldown_at_exact_boundary_is_allowed() -> None:
    decision = evaluate_resend(
        identity_status="Active",
        lockout_until=None,
        cooldown_until=_NOW,
        now=_NOW,
    )

    assert decision.outcome == "sent"


def test_cooldown_in_the_past_is_allowed() -> None:
    decision = evaluate_resend(
        identity_status="Active",
        lockout_until=None,
        cooldown_until=_NOW - timedelta(seconds=1),
        now=_NOW,
    )

    assert decision.outcome == "sent"
