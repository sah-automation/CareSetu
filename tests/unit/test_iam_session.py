"""PHASE-2 T6: facade session seam without a database (ticket #57).

``validate_token`` is the stateless hot path (MOD-001 §3.1: p95 < 100 ms) -
signature + expiry only, no DB round-trip. These tests drive it through the
facade against tokens minted by the domain ``issue_token``, using an engine
pointing at an unreachable host: if ``validate_token`` ever touched the
database the connect would fail and the test would error instead of pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.domain.exceptions import (
    AccessTokenExpiredError,
    AccessTokenMalformedError,
    AccessTokenSignatureError,
)
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import IamFacade, ValidatedAccessToken

_KEY = "unit-test-signing-key"
_OTHER_KEY = "unit-test-other-key"
_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)


class MutableClock:
    """Clock stand-in tests advance to walk the access-token expiry window."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def set(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


def _facade(clock: MutableClock | None = None) -> IamFacade:
    engine = create_async_engine(
        "postgresql+asyncpg://no-such-host.invalid/no-db", poolclass=NullPool
    )
    return IamFacade(
        engine=engine,
        sms_adapter=MockSmsAdapter(),
        clock=clock if clock is not None else MutableClock(_NOW),
        access_token_signing_key=_KEY,
    )


def _token(
    *,
    jti: str = "jti-unit-1",
    subject_id: int = 7,
    scope: str = "patient",
    key: str = _KEY,
) -> str:
    return issue_token(
        jti=jti,
        subject_id=subject_id,
        scope=scope,
        signing_key=key,
        now=_NOW,
    )


async def test_validate_token_resolves_scope_through_the_facade() -> None:
    token = _token()

    validated = await _facade().validate_token(token)

    assert validated == ValidatedAccessToken(
        subject_id=7, scope="patient", jti="jti-unit-1"
    )


async def test_validate_token_rejects_an_expired_token() -> None:
    clock = MutableClock(_NOW)
    token = _token()
    clock.set(_NOW + timedelta(minutes=20))

    with pytest.raises(AccessTokenExpiredError):
        await _facade(clock).validate_token(token)


async def test_validate_token_rejects_a_tampered_token() -> None:
    token = _token()
    header, payload, _signature = token.split(".")

    with pytest.raises(AccessTokenSignatureError):
        await _facade().validate_token(f"{header}.{payload}.AAAA")


async def test_validate_token_rejects_a_malformed_token() -> None:
    with pytest.raises(AccessTokenMalformedError):
        await _facade().validate_token("not-a-jwt")


async def test_validate_token_rejects_a_wrong_signature_token() -> None:
    token = _token(key=_OTHER_KEY)

    with pytest.raises(AccessTokenSignatureError):
        await _facade().validate_token(token)


async def test_validate_token_fails_closed_without_a_configured_key() -> None:
    engine = create_async_engine(
        "postgresql+asyncpg://no-such-host.invalid/no-db", poolclass=NullPool
    )
    facade = IamFacade(
        engine=engine,
        sms_adapter=MockSmsAdapter(),
        access_token_signing_key="",
    )
    token = _token()

    with pytest.raises(
        AccessTokenSignatureError, match="signing key is not configured"
    ):
        await facade.validate_token(token)
