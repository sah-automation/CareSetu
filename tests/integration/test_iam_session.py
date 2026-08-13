"""PHASE-2 T6/T7: issue_session + validate_token + refresh rotation against a
real PostgreSQL (tickets #57, #58).

Exercises the facade through its typed seam (Spec #51, Seam 1): a verified
patient gets a session JWT carrying the patient scope from their role grant,
the ``iam_sessions`` row records the jti/scope/expiry anchor the refresh
rotation (T7) checks, and ``validate_token`` resolves the scope back with no
DB round-trip. Refusal states - unverified, Suspended, missing role grant,
unknown phone - all refuse issuance with ``SessionIssuanceError``. The refresh
half (T7) proves the opaque refresh token rotates in-place: the old row is
revoked and a fresh row records the new jti and hash, a replayed old token is
rejected and audited, and the whole path never touches the SMS adapter.
Requires the native PostgreSQL; the suite skips cleanly when it is unreachable,
and the ``iam`` schema is migrated up for the module and down again afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter, SmsAdapter, SmsSendRequest, SmsSendResult
from modules.iam.domain.exceptions import (
    AccessTokenExpiredError,
    RefreshTokenExpiredError,
    RefreshTokenRevokedError,
    RefreshTokenUnknownError,
    SessionIssuanceError,
)
from modules.iam.domain.jwt import verify_token
from modules.iam.domain.refresh import hash_refresh_token
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_T0 = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_KEY = "integration-test-signing-key"


class MutableClock:
    """Clock stand-in tests advance to walk the access-token expiry window."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def set(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def iam_schema(database_url: str) -> Iterator[None]:
    """Migrate the ``iam`` schema to head for the module, restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_iam(database_url: str, iam_schema: None) -> Iterator[None]:
    """Empty the iam tables before every test so they start from a clean slate."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE iam.iam_identities, iam.iam_otp_challenges, "
                    "iam.iam_role_grants, iam.iam_sessions, iam.iam_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


def _facade(
    database_url: str,
    sms: SmsAdapter,
    clock: MutableClock,
    *,
    refresh_token_ttl_seconds: int | None = None,
) -> IamFacade:
    engine = create_async_engine(database_url, poolclass=NullPool)
    if refresh_token_ttl_seconds is None:
        return IamFacade(engine=engine, sms_adapter=sms, clock=clock, access_token_signing_key=_KEY)
    return IamFacade(
        engine=engine,
        sms_adapter=sms,
        clock=clock,
        access_token_signing_key=_KEY,
        refresh_token_ttl_seconds=refresh_token_ttl_seconds,
    )


async def _register(
    database_url: str, sms: MockSmsAdapter, clock: MutableClock
) -> tuple[IamFacade, str]:
    facade = _facade(database_url, sms, clock)
    await facade.register_patient("9876543210")
    sent = sms.last_sent_code(_PHONE)
    assert sent is not None and len(sent) == 6
    return facade, sent


async def _verified_facade(database_url: str, clock: MutableClock) -> IamFacade:
    sms = MockSmsAdapter()
    facade, sent = await _register(database_url, sms, clock)
    result = await facade.verify_otp("9876543210", sent)
    assert result.outcome == "verified"
    return facade


async def test_verified_patient_gets_a_session_token_with_the_patient_scope(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)

    session = await facade.issue_session("9876543210")

    assert session.jwt.count(".") == 2
    assert session.scope == "patient"
    assert session.expires_in_seconds == 900
    assert isinstance(session.identity_id, int)
    claims = verify_token(session.jwt, _KEY, _T0)
    assert claims.jti == session.jti
    assert claims.subject_id == session.identity_id
    assert claims.scope == "patient"
    assert claims.issued_at == _T0
    assert claims.expires_at == _T0 + timedelta(seconds=900)


async def test_issue_session_records_the_session_anchor_row(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)

    session = await facade.issue_session("9876543210")

    rows = await _query(
        database_url,
        "SELECT jti, identity_id, scope, issued_at, expires_at, revoked_at FROM iam.iam_sessions",
    )
    assert rows == [
        {
            "jti": session.jti,
            "identity_id": session.identity_id,
            "scope": "patient",
            "issued_at": _T0,
            "expires_at": _T0 + timedelta(seconds=900),
            "revoked_at": None,
        }
    ]


async def test_issue_session_refuses_an_unverified_identity(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, _sent = await _register(database_url, sms, clock)

    with pytest.raises(SessionIssuanceError, match="not Active"):
        await facade.issue_session("9876543210")

    assert await _query(database_url, "SELECT id FROM iam.iam_sessions") == []


async def test_issue_session_refuses_a_suspended_identity(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE iam.iam_identities SET status = 'Suspended'"))
    finally:
        await engine.dispose()

    with pytest.raises(SessionIssuanceError, match="not Active"):
        await facade.issue_session("9876543210")


async def test_issue_session_refuses_without_an_active_role_grant(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM iam.iam_role_grants"))
    finally:
        await engine.dispose()

    with pytest.raises(SessionIssuanceError, match="role grant"):
        await facade.issue_session("9876543210")

    assert await _query(database_url, "SELECT id FROM iam.iam_sessions") == []


async def test_issue_session_refuses_an_unknown_phone(database_url: str, clean_iam: Any) -> None:
    facade = _facade(database_url, MockSmsAdapter(), MutableClock(_T0))

    with pytest.raises(SessionIssuanceError, match="no identity"):
        await facade.issue_session("9876543210")


async def test_issue_session_mints_a_unique_jti_per_issue(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)

    first = await facade.issue_session("9876543210")
    second = await facade.issue_session("9876543210")

    assert first.jti != second.jti
    assert first.jwt != second.jwt
    rows = await _query(database_url, "SELECT jti FROM iam.iam_sessions")
    assert {row["jti"] for row in rows} == {first.jti, second.jti}


async def test_validate_token_resolves_an_issued_token(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")

    validated = await facade.validate_token(session.jwt)

    assert validated.subject_id == session.identity_id
    assert validated.scope == "patient"
    assert validated.jti == session.jti


async def test_validate_token_rejects_an_expired_issued_token(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")
    clock.set(_T0 + timedelta(minutes=20))

    with pytest.raises(AccessTokenExpiredError):
        await facade.validate_token(session.jwt)


class ExplodingSmsAdapter:
    """Proof the refresh path never touches EXT-001: any send fails the test."""

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        raise AssertionError("refresh_session must be independent of SMS (NFR-004)")


async def test_issue_session_returns_an_opaque_refresh_token_and_hashes_it_at_rest(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)

    session = await facade.issue_session("9876543210")

    assert session.refresh_token
    assert "." not in session.refresh_token  # opaque, never a JWT
    rows = await _query(
        database_url,
        "SELECT refresh_token_hash, refresh_expires_at FROM iam.iam_sessions",
    )
    assert rows == [
        {
            "refresh_token_hash": hash_refresh_token(session.refresh_token),
            "refresh_expires_at": _T0 + timedelta(days=30),
        }
    ]
    assert rows[0]["refresh_token_hash"] != session.refresh_token


async def test_refresh_returns_a_fresh_access_token_and_rotates_the_refresh_token(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")
    clock.set(_T0 + timedelta(minutes=10))

    refreshed = await facade.refresh_session(session.refresh_token)

    assert refreshed.jti != session.jti
    assert refreshed.jwt != session.jwt
    assert refreshed.scope == "patient"
    assert refreshed.identity_id == session.identity_id
    assert refreshed.refresh_token != session.refresh_token
    claims = verify_token(refreshed.jwt, _KEY, _T0 + timedelta(minutes=10))
    assert claims.jti == refreshed.jti
    rows = await _query(
        database_url,
        "SELECT jti, revoked_at, refresh_token_hash, refresh_expires_at "
        "FROM iam.iam_sessions ORDER BY id",
    )
    assert len(rows) == 2
    old, new = rows
    assert old["jti"] == session.jti
    assert old["revoked_at"] == _T0 + timedelta(minutes=10)
    assert old["refresh_token_hash"] == hash_refresh_token(session.refresh_token)
    assert new["jti"] == refreshed.jti
    assert new["revoked_at"] is None
    assert new["refresh_token_hash"] == hash_refresh_token(refreshed.refresh_token)


async def test_old_refresh_token_is_unusable_after_rotation(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")
    await facade.refresh_session(session.refresh_token)

    with pytest.raises(RefreshTokenRevokedError, match="already used or revoked"):
        await facade.refresh_session(session.refresh_token)


async def test_reusing_a_rotated_refresh_token_writes_patient_auth_failed(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")
    await facade.refresh_session(session.refresh_token)

    with pytest.raises(RefreshTokenRevokedError):
        await facade.refresh_session(session.refresh_token)

    rows = await _query(
        database_url,
        "SELECT event_type, payload FROM iam.iam_outbox WHERE event_type = 'patient.auth_failed'",
    )
    assert rows == [
        {
            "event_type": "patient.auth_failed",
            "payload": {
                "identity_id": session.identity_id,
                "phone_e164": "+919876543210",
                "reason": "replay",
                "attempts_left": None,
            },
        }
    ]


async def test_an_expired_refresh_token_is_rejected(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")
    clock.set(_T0 + timedelta(days=30))

    with pytest.raises(RefreshTokenExpiredError):
        await facade.refresh_session(session.refresh_token)


async def test_an_unknown_refresh_token_is_rejected(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    await facade.issue_session("9876543210")

    with pytest.raises(RefreshTokenUnknownError, match="no session matches"):
        await facade.refresh_session("opaque-token-that-was-never-issued")


async def test_refresh_path_never_touches_the_sms_adapter(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")

    no_sms = _facade(database_url, ExplodingSmsAdapter(), clock)
    refreshed = await no_sms.refresh_session(session.refresh_token)

    assert refreshed.jwt.count(".") == 2


async def test_refresh_slides_the_refresh_lifetime_forward(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")

    clock.set(_T0 + timedelta(days=10))
    first_rotation = await facade.refresh_session(session.refresh_token)

    clock.set(_T0 + timedelta(days=35))
    second_rotation = await facade.refresh_session(first_rotation.refresh_token)

    assert second_rotation.jti != first_rotation.jti
    rows = await _query(
        database_url,
        "SELECT refresh_expires_at FROM iam.iam_sessions ORDER BY id",
    )
    assert rows[-1]["refresh_expires_at"] == _T0 + timedelta(days=65)


async def test_refresh_derives_scope_from_the_current_role_grant(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _verified_facade(database_url, clock)
    session = await facade.issue_session("9876543210")

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM iam.iam_role_grants"))
    finally:
        await engine.dispose()

    with pytest.raises(RefreshTokenRevokedError, match="role grant"):
        await facade.refresh_session(session.refresh_token)
