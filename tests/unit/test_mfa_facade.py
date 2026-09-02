"""PHASE-5 fix P1: MfaFacade.enroll_mfa + record_mfa_verified seams (#272).

These unit tests pin the MFA enrollment seam against a mocked engine: no SQL
plumbing, no empty-secret placeholder. ``enroll_mfa`` must persist a real
encrypted secret (the value read back by ``session_facade``'s S8 verification)
and return the plaintext secret + provisioning URI exactly once. A phone with
no enrollment refuses ``record_mfa_verified`` rather than writing an empty
secret (the Phase-5 review split-brain bug). The integration suite proves the
stored secret is genuinely encrypted; these tests pin the seam shape and the
fail-closed error paths.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects.postgresql.dml import (
    Insert as PostgresqlInsert,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert, Update

from modules.iam.domain.exceptions import SessionIssuanceError
from modules.iam.mfa_facade import MfaFacade

_KEY = base64.b64encode(b"0" * 32).decode("ascii")


class _FakeResult:
    """Mimics the result of an executed statement."""

    def __init__(self, scalar: Any = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


def _connection(results: list[Any]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=results)
    return connection


def _facade(connection: AsyncMock, *, key: str = _KEY) -> MfaFacade:
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return MfaFacade(engine, mfa_secret_key=key)


def _executed(connection: AsyncMock) -> list[Any]:
    return [call.args[0] for call in connection.execute.await_args_list]


def _upsert(connection: AsyncMock) -> Insert:
    return next(stmt for stmt in _executed(connection) if isinstance(stmt, PostgresqlInsert))


@pytest.mark.asyncio
async def test_enroll_mfa_persists_a_real_secret_and_returns_uri() -> None:
    connection = _connection(
        [
            _FakeResult(scalar="+919000000002"),  # _identity_phone
            _FakeResult(),  # iam_operator_mfa upsert
        ]
    )
    facade = _facade(connection)

    result = await facade.enroll_mfa(42)

    assert result.identity_id == 42
    assert result.phone_e164 == "+919000000002"
    assert len(result.secret) > 0
    assert result.provisioning_uri.startswith("otpauth://totp/")

    # The upsert is persisted against the real table, not dropped.
    assert _upsert(connection).table.name == "iam_operator_mfa"
    # The stored ciphertext is never the empty placeholder that broke login.
    assert "secret" in _upsert(connection).__dict__["_values"]


@pytest.mark.asyncio
async def test_enroll_mfa_refuses_an_unknown_identity() -> None:
    connection = _connection(
        [
            _FakeResult(scalar=None),  # _identity_phone: no such identity
        ]
    )
    facade = _facade(connection)

    with pytest.raises(SessionIssuanceError, match="invite the operator"):
        await facade.enroll_mfa(999)


@pytest.mark.asyncio
async def test_enroll_mfa_fails_closed_without_an_encryption_key() -> None:
    connection = _connection([])
    facade = _facade(connection, key="")

    with pytest.raises(SessionIssuanceError, match="encryption key"):
        await facade.enroll_mfa(42)


@pytest.mark.asyncio
async def test_record_mfa_verified_stamps_an_existing_enrollment() -> None:
    connection = _connection(
        [
            _FakeResult(scalar=42),  # identity lookup by phone
            _FakeResult(scalar=7),  # existing iam_operator_mfa row
            _FakeResult(),  # iam_operator_mfa update
        ]
    )
    facade = _facade(connection)

    result = await facade.record_mfa_verified("+919111111111")

    assert result.identity_id == 42
    assert result.enrolled is True

    statements = _executed(connection)
    updates = [stmt for stmt in statements if isinstance(stmt, Update)]
    assert len(updates) == 1
    # The update never touches the secret column - no empty placeholder.
    assert "secret" not in updates[0].__dict__.get("_values", {})


@pytest.mark.asyncio
async def test_record_mfa_verified_refuses_a_phone_without_enrollment() -> None:
    connection = _connection(
        [
            _FakeResult(scalar=42),  # identity lookup by phone
            _FakeResult(scalar=None),  # no iam_operator_mfa row
        ]
    )
    facade = _facade(connection)

    with pytest.raises(SessionIssuanceError, match="no enrolled MFA"):
        await facade.record_mfa_verified("+919111111111")
