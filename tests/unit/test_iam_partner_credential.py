"""PHASE-5 T02: partner credential account facade seam (ticket #245, ADR-0010).

The ``create_credential_account`` seam is the iam change that lets a newly
registered partner get a login account immediately - synchronously, in one
transaction boundary - so phone-OTP login works from registration. Unlike a
patient registration it does NOT grant a role: the identity is created
``[Unverified]`` with no ``partner``/``patient`` role grant, so activation
(T03, #246) is the gated step that unlocks patient-facing scope.

The ``partner.registered`` event is MOD-002's (internal-modules §4.2): the
partner module emits it from its own outbox inside the same registration
transaction, so this seam deliberately writes no outbox event itself. The
integration suite proves the DB rows land in one transaction. This unit test
pins the seam shape: the facade creates the identity only - one insert, no
outbox write, never a role grant.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Insert

from modules.iam.identity_facade import IdentityFacade
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import iam_role_grants


class _FakeResult:
    """Mimics the result of an executed statement."""

    def __init__(self) -> None:
        self.rowcount = 1


class _FakeScalar:
    """Replays the id the identity re-read resolves to."""

    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


def _facade() -> tuple[IdentityFacade, AsyncMock]:
    """An ``IdentityFacade`` whose engine records every executed statement.

    The identity ``INSERT ... ON CONFLICT`` completes and the identity-id
    re-read answers ``7``. No outbox insert is expected on the happy path.
    """
    from sqlalchemy.ext.asyncio import AsyncEngine

    connection = AsyncMock()
    connection.execute = AsyncMock(
        side_effect=[
            _FakeResult(),  # identity INSERT ... ON CONFLICT DO NOTHING
            _FakeScalar(7),  # identity-id re-read
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
async def test_creates_identity_only_in_one_transaction() -> None:
    facade, connection = _facade()

    result = await facade.create_credential_account("9876543210")

    assert result.identity_id == 7
    assert result.phone_e164 == "+919876543210"

    tables = [stmt.table.name for stmt in _inserts(connection)]
    assert tables == ["iam_identities"]


@pytest.mark.asyncio
async def test_writes_no_outbox_event() -> None:
    facade, connection = _facade()

    await facade.create_credential_account("9876543210")

    tables = [stmt.table.name for stmt in _inserts(connection)]
    assert IAM_OUTBOX_TABLE not in tables


@pytest.mark.asyncio
async def test_never_grants_a_role() -> None:
    facade, connection = _facade()

    await facade.create_credential_account("9876543210")

    tables = [stmt.table.name for stmt in _inserts(connection)]
    assert iam_role_grants.name not in tables
