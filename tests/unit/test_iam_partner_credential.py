"""PHASE-5 T02: partner credential account facade seam (ticket #245, ADR-0010).

The ``create_credential_account`` seam is the iam change that lets a newly
registered partner get a login account immediately - synchronously, in one
transaction boundary - so phone-OTP login works from registration. Unlike a
patient registration it does NOT grant a role: the identity is created
``[Unverified]`` with no ``partner``/``patient`` role grant, so activation
(T03, #246) is the gated step that unlocks patient-facing scope.

The integration suite proves the DB rows land in one transaction with the
``partner.registered`` outbox event. This unit test pins the seam shape: the
facade creates the identity and writes the outbox event into one transaction,
and never inserts a role grant.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Insert

from modules.iam.identity_facade import IdentityFacade
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import iam_role_grants


class _FakeResult:
    """Mimics the ``rowcount`` of ``INSERT ... ON CONFLICT DO NOTHING``."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeScalar:
    """Replays the id the identity re-read resolves to."""

    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


def _facade() -> tuple[IdentityFacade, AsyncMock]:
    """An ``IdentityFacade`` whose engine records every executed statement.

    The identity ``INSERT ... ON CONFLICT`` answers ``rowcount==1`` (a fresh
    identity), the identity-id re-read answers ``7``, and the outbox insert
    completes. No role grant insert is expected on the happy path.
    """
    from sqlalchemy.ext.asyncio import AsyncEngine

    connection = AsyncMock()
    connection.execute = AsyncMock(
        side_effect=[
            _FakeResult(rowcount=1),
            _FakeScalar(7),
            _FakeResult(rowcount=1),
        ]
    )
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    facade = IdentityFacade(engine, otp_sender=lambda phone, otp: None)
    return facade, connection


def _inserts(connection: AsyncMock) -> list[Insert]:
    """Every executed INSERT statement, in order."""
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert)
    ]


@pytest.mark.asyncio
async def test_creates_identity_and_outbox_in_one_transaction() -> None:
    facade, connection = _facade()

    result = await facade.create_credential_account("9876543210")

    assert result.identity_id == 7
    assert result.phone_e164 == "+919876543210"

    tables = [stmt.table.name for stmt in _inserts(connection)]
    assert tables == ["iam_identities", IAM_OUTBOX_TABLE]


@pytest.mark.asyncio
async def test_writes_partner_registered_event() -> None:
    facade, connection = _facade()

    await facade.create_credential_account("9876543210")

    inserts = _inserts(connection)
    outbox_stmt = next(stmt for stmt in inserts if stmt.table.name == IAM_OUTBOX_TABLE)
    assert outbox_stmt._values["event_type"].value == "partner.registered"


@pytest.mark.asyncio
async def test_never_grants_a_role() -> None:
    facade, connection = _facade()

    await facade.create_credential_account("9876543210")

    tables = [stmt.table.name for stmt in _inserts(connection)]
    assert iam_role_grants.name not in tables
