"""PHASE-2 T7: refresh-token decision machine + token primitives (ticket #58).

``evaluate_refresh`` is pure logic with no I/O: it gates a known session row,
so a revoked one (the replay of an already-rotated or operator-revoked
session) and an expired one are each rejected and a live one rotates. An
unknown token is refused before the gate - the facade lookup on the hash
misses and raises - and is pinned at the integration seam. Unit tests pin the
token shape (opaque, never a JWT), the hash round-trip (server-side, one-way),
the precedence (revoked beats a still-open window), and the expiry boundary.
The DB-backed rotation - old row revoked, fresh row inserted, outbox write on
a replay - is the integration suite's job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from modules.iam.domain.refresh import (
    REFRESH_TOKEN_TTL_SECONDS,
    evaluate_refresh,
    generate_refresh_token,
    hash_refresh_token,
)

_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_FUTURE = _NOW + timedelta(days=30)


def test_known_live_token_rotates() -> None:
    decision = evaluate_refresh(
        revoked_at=None,
        refresh_expires_at=_FUTURE,
        now=_NOW,
    )

    assert decision.outcome == "rotated"
    assert decision.reason is None


def test_revoked_token_is_rejected_even_inside_the_window() -> None:
    decision = evaluate_refresh(
        revoked_at=_NOW,
        refresh_expires_at=_FUTURE,
        now=_NOW,
    )

    assert decision.outcome == "rejected"
    assert decision.reason == "revoked"


def test_expired_token_is_rejected() -> None:
    decision = evaluate_refresh(
        revoked_at=None,
        refresh_expires_at=_NOW - timedelta(seconds=1),
        now=_NOW,
    )

    assert decision.outcome == "rejected"
    assert decision.reason == "expired"


def test_expiry_at_exact_boundary_is_rejected() -> None:
    decision = evaluate_refresh(
        revoked_at=None,
        refresh_expires_at=_NOW,
        now=_NOW,
    )

    assert decision.outcome == "rejected"
    assert decision.reason == "expired"


def test_missing_refresh_expiry_is_rejected() -> None:
    decision = evaluate_refresh(
        revoked_at=None,
        refresh_expires_at=None,
        now=_NOW,
    )

    assert decision.outcome == "rejected"
    assert decision.reason == "expired"


def test_generated_token_is_opaque_and_url_safe() -> None:
    token = generate_refresh_token()

    assert isinstance(token, str)
    assert "." not in token  # opaque - never a JWS/JWT
    assert all(char.isalnum() or char in "-_" for char in token)


def test_generated_tokens_are_unique() -> None:
    tokens = {generate_refresh_token() for _ in range(50)}

    assert len(tokens) == 50


def test_hash_round_trip_is_deterministic_and_never_the_token() -> None:
    token = generate_refresh_token()

    first = hash_refresh_token(token)
    second = hash_refresh_token(token)

    assert first == second
    assert first != token
    assert token not in first


def test_different_tokens_hash_differently() -> None:
    assert hash_refresh_token(generate_refresh_token()) != hash_refresh_token(
        generate_refresh_token()
    )


def test_refresh_window_is_thirty_days() -> None:
    assert REFRESH_TOKEN_TTL_SECONDS == 30 * 24 * 60 * 60
