"""F014-T03 #463: OtpFacade.partner_verify decision surface (ADR-0016).

Pins the silent partner challenge consumption on a mocked engine: a correct
code consumes the challenge and writes the ``phone_verified`` marker in the
same transaction - with no patient role grant, no ``patient.verified`` (or any)
outbox row, and no identity lifecycle transition; refusals render exactly as on
the patient surface and, for SMS-cost failures only, feed the lockout counter
(ADR-0004) while no ``patient.auth_failed`` row is written (partner phone
verification is silent, ADR-0016 §Events).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert, Update

from modules.iam.domain.otp import hash_otp
from modules.iam.otp_facade import OtpFacade

_NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
_PHONE = "+919876543210"


class _MappedRow:
    """Row-shaped dict the lock/challenge queries' ``.mappings().first()`` return."""

    def __init__(self, **values: object) -> None:
        self._values = values

    def __getitem__(self, key: str) -> object:
        return self._values[key]


class _Mappings:
    """The result of ``.mappings()``; ``first()`` returns the row, or ``None``."""

    def __init__(self, row: _MappedRow | None) -> None:
        self._row = row

    def first(self) -> _MappedRow | None:
        return self._row


class _RowResult:
    """Result of a ``.mappings().first()`` query (the identity row lock)."""

    def __init__(self, row: _MappedRow | None) -> None:
        self._row = row

    def mappings(self) -> _Mappings:
        return _Mappings(self._row)


def _identity_row(
    status: str = "Unverified",
    lockout_failed_attempts: int = 0,
    lockout_until: datetime | None = None,
) -> _MappedRow:
    return _MappedRow(
        id=7,
        status=status,
        lockout_failed_attempts=lockout_failed_attempts,
        lockout_until=lockout_until,
    )


def _challenge_row(
    *,
    status: str = "Pending",
    attempts: int = 0,
    expires_at: datetime | None = None,
    otp_hash: str = "",
) -> _MappedRow:
    return _MappedRow(
        id=42,
        otp_hash=otp_hash,
        status=status,
        attempts=attempts,
        expires_at=expires_at or (_NOW + timedelta(seconds=300)),
    )


def _facade(
    execute_results: list[object],
) -> tuple[OtpFacade, AsyncMock, AsyncMock]:
    """An ``OtpFacade`` over a mocked engine; ``execute_results`` replay per statement.

    Returns ``(facade, sender, connection)``; the test awaits
    ``facade.partner_verify(...)``. ``connection.execute`` is mocked, so the
    facade's SELECT/UPDATE/INSERT statements are captured on ``execute`` for
    inspection rather than executed.
    """
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    sender = AsyncMock()
    facade = OtpFacade(engine, clock=lambda: _NOW, otp_sender=sender)
    return facade, sender, connection


def _updates(connection: AsyncMock) -> list[Update]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Update)
    ]


def _inserts(connection: AsyncMock) -> list[Insert]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert)
    ]


def _values(stmt: Update | Insert) -> dict[str, object]:
    """Literal values of a DML statement's ``.values(...)`` (test_audit_consumer)."""
    return {key: parameter.value for key, parameter in stmt._values.items()}


def _challenge_updates(connection: AsyncMock) -> list[Update]:
    return [u for u in _updates(connection) if u.table.name == "iam_otp_challenges"]


def _identity_updates(connection: AsyncMock) -> list[Update]:
    return [u for u in _updates(connection) if u.table.name == "iam_identities"]


@pytest.mark.asyncio
async def test_verified_consumes_challenge_and_marks_phone_in_the_same_transaction() -> None:
    otp = "123456"
    facade, sender, connection = _facade(
        [
            _RowResult(_identity_row()),
            _RowResult(_challenge_row(otp_hash=hash_otp(otp))),
            MagicMock(),
            MagicMock(),
        ]
    )

    result = await facade.partner_verify("9876543210", otp)

    assert result.outcome == "verified"
    assert result.phone_e164 == _PHONE
    assert result.identity_id == 7
    # the challenge was consumed exactly once (single-use)
    challenge = _challenge_updates(connection)
    assert len(challenge) == 1
    assert _values(challenge[0])["status"] == "Verified"
    # the phone-verified marker was written in the same transaction and the
    # brute-force counter reset - and crucially NO lifecycle transition: the
    # status column is never written by the partner verify.
    identity = _identity_updates(connection)
    assert len(identity) == 1
    identity_values = _values(identity[0])
    assert identity_values["phone_verified"] is True
    assert identity_values["lockout_failed_attempts"] == 0
    assert identity_values["lockout_until"] is None
    assert "status" not in identity_values
    # silent: no role-grant row, no outbox row of any kind, no SMS
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_code_decrements_budget_and_feeds_only_the_lockout_counter() -> None:
    facade, sender, connection = _facade(
        [
            _RowResult(_identity_row(lockout_failed_attempts=0)),
            _RowResult(_challenge_row(otp_hash=hash_otp("123456"))),
            MagicMock(),
            MagicMock(),
        ]
    )

    result = await facade.partner_verify("9876543210", "654321")

    assert result.outcome == "wrong_code"
    assert result.attempts_left == 4
    assert result.identity_id == 7
    # the challenge budget was decremented (the code stays alive) and the
    # identity's lockout counter incremented - the SMS-cost rule of ADR-0004.
    assert _values(_challenge_updates(connection)[0])["attempts"] == 1
    identity_values = _values(_identity_updates(connection)[0])
    assert identity_values["lockout_failed_attempts"] == 1
    assert identity_values["lockout_until"] is None
    assert "status" not in identity_values
    # silent rejection: no patient.auth_failed / otp.failed outbox row
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_spent_wrong_guess_exhausts_budget_and_flips_the_challenge_failed() -> None:
    ch = _challenge_row(attempts=4, otp_hash=hash_otp("123456"))
    facade, sender, connection = _facade(
        [_RowResult(_identity_row()), _RowResult(ch), MagicMock(), MagicMock()]
    )

    result = await facade.partner_verify("9876543210", "112233")

    assert result.outcome == "spent"
    assert result.attempts_left == 0
    challenge = _values(_challenge_updates(connection)[0])
    assert challenge["attempts"] == 5
    assert challenge["status"] == "Failed"
    assert _values(_identity_updates(connection)[0])["lockout_failed_attempts"] == 1
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_pending_challenge_rejects_and_counts_toward_lockout() -> None:
    ch = _challenge_row(expires_at=_NOW - timedelta(seconds=1))
    facade, sender, connection = _facade(
        [_RowResult(_identity_row()), _RowResult(ch), MagicMock(), MagicMock()]
    )

    result = await facade.partner_verify("9876543210", "654321")

    assert result.outcome == "expired"
    # a time-expired Pending row is lazily marked Expired; the failure still
    # incurred an SMS cost, so it feeds the lockout counter (ADR-0004).
    assert _values(_challenge_updates(connection)[0])["status"] == "Expired"
    assert _values(_identity_updates(connection)[0])["lockout_failed_attempts"] == 1
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_replayed_verified_challenge_rejects_without_touching_the_row() -> None:
    ch = _challenge_row(status="Verified", attempts=1)
    facade, sender, connection = _facade(
        [_RowResult(_identity_row()), _RowResult(ch), MagicMock(), MagicMock()]
    )

    result = await facade.partner_verify("9876543210", "654321")

    assert result.outcome == "expired"
    # an already-verified row is already dead: no challenge write-back, but the
    # SMS was sent for it, so the lockout counter still grows.
    assert _challenge_updates(connection) == []
    assert _values(_identity_updates(connection)[0])["lockout_failed_attempts"] == 1
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_suspended_identity_refused_without_touching_counter_or_events() -> None:
    facade, sender, connection = _facade([_RowResult(_identity_row(status="Suspended"))])

    result = await facade.partner_verify("9876543210", "654321")

    assert result.outcome == "expired"
    assert result.identity_id == 7
    # a Suspended guard is not an attempt: no challenge write, no counter.
    assert _updates(connection) == []
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_lockout_refused_with_countdown_and_no_counter_touch() -> None:
    row = _identity_row(lockout_failed_attempts=10, lockout_until=_NOW + timedelta(seconds=900))
    facade, sender, connection = _facade([_RowResult(row)])

    result = await facade.partner_verify("9876543210", "654321")

    assert result.outcome == "locked"
    assert result.lockout_remaining_seconds == 900
    assert _updates(connection) == []
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_identity_refused_like_the_patient_no_challenge_surface() -> None:
    facade, sender, connection = _facade([_RowResult(None)])

    result = await facade.partner_verify("9876543210", "654321")

    assert result.outcome == "expired"
    assert _updates(connection) == []
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_live_challenge_refused_without_touching_anything() -> None:
    facade, sender, connection = _facade([_RowResult(_identity_row()), _RowResult(None)])

    result = await facade.partner_verify("9876543210", "654321")

    assert result.outcome == "expired"
    assert _updates(connection) == []
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_tenth_consecutive_failure_triggers_lockout_without_an_event() -> None:
    facade, sender, connection = _facade(
        [
            _RowResult(_identity_row(lockout_failed_attempts=9)),
            _RowResult(_challenge_row(otp_hash=hash_otp("123456"))),
            MagicMock(),
            MagicMock(),
        ]
    )

    result = await facade.partner_verify("9876543210", "654321")

    assert result.outcome == "locked"
    assert result.lockout_remaining_seconds == 900
    identity_values = _values(_identity_updates(connection)[0])
    assert identity_values["lockout_failed_attempts"] == 10
    assert identity_values["lockout_until"] == _NOW + timedelta(seconds=900)
    # even the lockout flip is silent: no otp.failed outbox row
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_reboots_the_lockout_streak_after_a_lockout_window_lifts() -> None:
    otp = "123456"
    row = _identity_row(lockout_failed_attempts=5, lockout_until=_NOW - timedelta(seconds=1))
    facade, _sender, connection = _facade(
        [
            _RowResult(row),
            _RowResult(_challenge_row(otp_hash=hash_otp(otp))),
            MagicMock(),
            MagicMock(),
        ]
    )

    result = await facade.partner_verify("9876543210", otp)

    assert result.outcome == "verified"
    # a correct code clears the expired lockout window and resets the streak.
    identity_values = _values(_identity_updates(connection)[0])
    assert identity_values["phone_verified"] is True
    assert identity_values["lockout_failed_attempts"] == 0
    assert identity_values["lockout_until"] is None
    assert _inserts(connection) == []


@pytest.mark.asyncio
async def test_phone_is_normalized_server_side() -> None:
    otp = "123456"
    facade, _sender, _connection = _facade(
        [
            _RowResult(_identity_row()),
            _RowResult(_challenge_row(otp_hash=hash_otp(otp))),
            MagicMock(),
            MagicMock(),
        ]
    )

    result = await facade.partner_verify("91-98765 43210", otp)

    assert result.phone_e164 == _PHONE
    assert result.outcome == "verified"
