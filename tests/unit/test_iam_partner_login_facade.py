"""F014-T02 #462: OtpFacade.partner_login decision surface (ADR-0016).

Pins the shared-OTP-machine reuse for the dedicated partner login route on a
mocked engine: the partner-profile gate (``resolve_partner_id_by_identity``)
alone separates ``sent`` from ``no_account``; a refusal never writes an
identity row, never issues a challenge, never lands an outbox event, and never
dispatches an SMS. The cooldown/locked/suspended decisions come from the shared
re-issue primitive (``_reissue_otp_challenge`` / ``evaluate_resend``), identical
to the patient surface - this file proves the partner flow feeds it the same
guard state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.iam.otp_facade import OtpFacade

_NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
_PHONE = "+919876543210"


class _MappedRow:
    """Row-shaped dict the lock query's ``.mappings().first()`` returns."""

    def __init__(self, **values: object) -> None:
        self._values = values

    def __getitem__(self, key: str) -> object:
        return self._values[key]


class _Mappings:
    """The result of ``.mappings()`` on the lock query.

    ``first()`` returns the locked identity row, or ``None`` to simulate a
    phone with no identity at all.
    """

    def __init__(self, row: _MappedRow | None) -> None:
        self._row = row

    def first(self) -> _MappedRow | None:
        return self._row


class _LockResult:
    """Result of the ``FOR UPDATE`` identity-row select."""

    def __init__(self, row: _MappedRow | None) -> None:
        self._row = row

    def mappings(self) -> _Mappings:
        return _Mappings(self._row)


class _CooldownResult:
    """Result of the latest-challenge ``cooldown_until`` read (``None`` when none)."""

    def __init__(self, value: datetime | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> datetime | None:
        return self._value


class _InsertIdResult:
    """Result of the challenge insert's ``returning(id)``."""

    def scalar_one(self) -> int:
        return 42


def _row(status: str = "Unverified") -> _MappedRow:
    return _MappedRow(
        id=7,
        status=status,
        lockout_failed_attempts=0,
        lockout_until=None,
    )


def _facade(
    execute_results: list[object],
) -> tuple[OtpFacade, AsyncMock, AsyncMock, AsyncMock]:
    """An ``OtpFacade`` over a mocked engine + a controller for gate and sender.

    ``execute_results`` are replayed per statement the facade issues. Returns
    ``(facade, gate, sender, connection)``; the test awaits
    ``facade.partner_login(...)``.
    """
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    sender = AsyncMock()
    facade = OtpFacade(engine, clock=lambda: _NOW, otp_sender=sender)
    gate = AsyncMock(return_value=3)
    return facade, gate, sender, connection


def _inserts(connection: AsyncMock) -> list[Insert]:
    """Every INSERT executed during the flow, in order (state changes + outbox)."""
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert)
    ]


@pytest.mark.asyncio
async def test_sent_issues_challenge_through_the_shared_otp_machine() -> None:
    facade, gate, sender, connection = _facade(
        [_LockResult(_row()), _CooldownResult(None), MagicMock(), _InsertIdResult(), MagicMock()]
    )

    result = await facade.partner_login("9876543210", gate)

    assert result.outcome == "sent"
    assert result.phone_e164 == _PHONE
    assert result.challenge_id == 42
    assert result.expires_in_seconds == 300
    assert result.cooldown_remaining_seconds == 60
    assert result.attempts_left == 5
    # the gate was consulted for the identity, then exactly one challenge row
    # and one outbox row (otp.sent) were inserted - the identity was read only.
    gate.assert_awaited_once_with(7)
    assert [stmt.table.name for stmt in _inserts(connection)] == [
        "iam_otp_challenges",
        "iam_outbox",
    ]
    sender.assert_awaited_once()
    sent_phone, sent_otp = sender.await_args.args
    assert sent_phone == _PHONE
    assert len(sent_otp) == 6 and sent_otp.isdigit()


@pytest.mark.asyncio
async def test_no_account_when_identity_is_absent() -> None:
    facade, gate, sender, connection = _facade([_LockResult(None)])

    result = await facade.partner_login("9876543210", gate)

    assert result.outcome == "no_account"
    assert result.phone_e164 == _PHONE
    # no identity to gate on, so the profile seam is never even consulted.
    gate.assert_not_awaited()
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_account_when_phone_has_no_partner_profile() -> None:
    facade, gate, sender, connection = _facade([_LockResult(_row())])
    gate.return_value = None

    result = await facade.partner_login("9876543210", gate)

    # a patient-only (or partner-less) phone is refused no_account: no identity
    # insert, no challenge, no outbox event, no SMS.
    assert result.outcome == "no_account"
    assert result.phone_e164 == _PHONE
    gate.assert_awaited_once_with(7)
    assert _inserts(connection) == []
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_cooldown_outcome_refuses_without_sending() -> None:
    facade, gate, sender, connection = _facade(
        [_LockResult(_row()), _CooldownResult(_NOW + timedelta(seconds=30)), MagicMock()]
    )

    result = await facade.partner_login("9876543210", gate)

    assert result.outcome == "cooldown"
    assert result.cooldown_remaining_seconds == 30
    sender.assert_not_awaited()
    # no challenge was inserted - the cooldown gate refused before issuance.
    assert _inserts(connection) == []


@pytest.mark.asyncio
async def test_locked_outcome_carries_lockout_countdown() -> None:
    row = _MappedRow(
        id=7,
        status="Unverified",
        lockout_failed_attempts=10,
        lockout_until=_NOW + timedelta(seconds=900),
    )
    facade, gate, sender, connection = _facade(
        [_LockResult(row), _CooldownResult(None), MagicMock()]
    )

    result = await facade.partner_login("9876543210", gate)

    assert result.outcome == "locked"
    assert result.lockout_remaining_seconds == 900
    sender.assert_not_awaited()
    assert _inserts(connection) == []


@pytest.mark.asyncio
async def test_suspended_outcome_refuses_without_sending() -> None:
    facade, gate, sender, connection = _facade(
        [_LockResult(_row(status="Suspended")), _CooldownResult(None), MagicMock()]
    )

    result = await facade.partner_login("9876543210", gate)

    assert result.outcome == "suspended"
    sender.assert_not_awaited()
    assert _inserts(connection) == []


@pytest.mark.asyncio
async def test_phone_is_normalized_server_side() -> None:
    facade, gate, _sender, _connection = _facade(
        [_LockResult(_row()), _CooldownResult(None), MagicMock(), _InsertIdResult(), MagicMock()]
    )

    result = await facade.partner_login("91-98765 43210", gate)

    # the +91 country prefix never comes from the client; the facade derives it.
    assert result.phone_e164 == _PHONE
    assert result.outcome == "sent"
