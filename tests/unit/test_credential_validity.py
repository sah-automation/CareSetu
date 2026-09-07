"""Credential-validity pure eligibility decision (ticket #331).

Mirrors the partner state-machine pure-domain suite pattern: the eligibility
decision is a pure function evaluated over credential records, so it can be
exhaustively tested without a database.

The SQL predicates (``has_any_credential``, ``has_invalid_credential``,
``provider_visible``) are integration-tested through the existing partner/iam
suites. This suite pins the pure domain logic that those predicates mirror.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from modules.partner.credential_validity import (
    CredentialRecord,
    EligibilityDecision,
    evaluate_eligibility,
)

_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)


def _valid_credential(
    *,
    credential_id: int = 1,
    expires_at: datetime | None = None,
) -> CredentialRecord:
    return CredentialRecord(
        id=credential_id,
        verified=True,
        expires_at=expires_at,
        revoked_at=None,
        invalidation_reason=None,
    )


def _unverified_credential(credential_id: int = 1) -> CredentialRecord:
    return CredentialRecord(
        id=credential_id,
        verified=False,
        expires_at=None,
        revoked_at=None,
        invalidation_reason=None,
    )


def _expired_credential(
    credential_id: int = 1,
    *,
    expired_ago: timedelta = timedelta(days=1),
) -> CredentialRecord:
    return CredentialRecord(
        id=credential_id,
        verified=True,
        expires_at=_NOW - expired_ago,
        revoked_at=None,
        invalidation_reason=None,
    )


def _revoked_credential(credential_id: int = 1) -> CredentialRecord:
    return CredentialRecord(
        id=credential_id,
        verified=True,
        expires_at=None,
        revoked_at=_NOW,
        invalidation_reason="revoked",
    )


# --- Empty / no-credential cases ---


def test_no_credentials_yields_no_any_and_no_invalid() -> None:
    result = evaluate_eligibility([], now=_NOW)

    assert result == EligibilityDecision(has_any=False, has_invalid=False)


# --- Single valid credential ---


def test_single_valid_credential_is_eligible() -> None:
    result = evaluate_eligibility(
        [_valid_credential(expires_at=_NOW + timedelta(days=365))],
        now=_NOW,
    )

    assert result == EligibilityDecision(has_any=True, has_invalid=False)


def test_single_valid_credential_no_expiry_is_eligible() -> None:
    result = evaluate_eligibility([_valid_credential()], now=_NOW)

    assert result == EligibilityDecision(has_any=True, has_invalid=False)


# --- Single invalid credential cases ---


def test_unverified_credential_is_invalid() -> None:
    result = evaluate_eligibility([_unverified_credential()], now=_NOW)

    assert result == EligibilityDecision(has_any=True, has_invalid=True)


def test_expired_credential_is_invalid() -> None:
    result = evaluate_eligibility([_expired_credential()], now=_NOW)

    assert result == EligibilityDecision(has_any=True, has_invalid=True)


def test_revoked_credential_is_invalid() -> None:
    result = evaluate_eligibility([_revoked_credential()], now=_NOW)

    assert result == EligibilityDecision(has_any=True, has_invalid=True)


def test_credential_expiring_in_future_is_valid() -> None:
    result = evaluate_eligibility(
        [_valid_credential(expires_at=_NOW + timedelta(seconds=1))],
        now=_NOW,
    )

    assert result == EligibilityDecision(has_any=True, has_invalid=False)


def test_credential_expiring_exactly_now_is_invalid() -> None:
    """Boundary: expires_at == now counts as expired (<= comparison)."""
    result = evaluate_eligibility(
        [
            CredentialRecord(
                id=1, verified=True, expires_at=_NOW, revoked_at=None, invalidation_reason=None
            )
        ],
        now=_NOW,
    )

    assert result == EligibilityDecision(has_any=True, has_invalid=True)


# --- Multiple credential mixes ---


def test_one_valid_one_unverified_yields_invalid() -> None:
    result = evaluate_eligibility(
        [_valid_credential(credential_id=1), _unverified_credential(credential_id=2)],
        now=_NOW,
    )

    assert result == EligibilityDecision(has_any=True, has_invalid=True)


def test_one_valid_one_expired_yields_invalid() -> None:
    result = evaluate_eligibility(
        [_valid_credential(credential_id=1), _expired_credential(credential_id=2)],
        now=_NOW,
    )

    assert result == EligibilityDecision(has_any=True, has_invalid=True)


def test_one_valid_one_revoked_yields_invalid() -> None:
    result = evaluate_eligibility(
        [_valid_credential(credential_id=1), _revoked_credential(credential_id=2)],
        now=_NOW,
    )

    assert result == EligibilityDecision(has_any=True, has_invalid=True)


def test_two_valid_credentials_are_eligible() -> None:
    result = evaluate_eligibility(
        [
            _valid_credential(credential_id=1, expires_at=_NOW + timedelta(days=365)),
            _valid_credential(credential_id=2, expires_at=_NOW + timedelta(days=365)),
        ],
        now=_NOW,
    )

    assert result == EligibilityDecision(has_any=True, has_invalid=False)


def test_all_invalid_yields_invalid() -> None:
    result = evaluate_eligibility(
        [_unverified_credential(1), _expired_credential(2), _revoked_credential(3)],
        now=_NOW,
    )

    assert result == EligibilityDecision(has_any=True, has_invalid=True)


# --- ADR-0011 lazy read-hide: expired before sweep is already invalid ---


def test_expired_not_yet_swept_is_still_invalid() -> None:
    """Lazy read-hide: an expired credential suppresses visibility even before
    the daily sweep stamps ``revoked_at`` / ``invalidation_reason``."""
    pre_sweep = CredentialRecord(
        id=1,
        verified=True,
        expires_at=_NOW - timedelta(hours=1),
        revoked_at=None,  # sweep has not yet run
        invalidation_reason=None,
    )
    result = evaluate_eligibility([pre_sweep], now=_NOW)

    assert result.has_invalid is True


# --- Idempotency: reason vocabulary not consumed by pure decision ---


def test_pure_decision_ignores_invalidation_reason_value() -> None:
    """The eligibility decision does not inspect ``invalidation_reason``; it
    only checks ``revoked_at`` is set. The reason vocabulary lives in
    ``domain/credentials.py`` and is consumed by the outbox envelope."""
    cred = CredentialRecord(
        id=1,
        verified=True,
        expires_at=None,
        revoked_at=_NOW,
        invalidation_reason="any_reason",
    )
    result = evaluate_eligibility([cred], now=_NOW)

    assert result.has_invalid is True
