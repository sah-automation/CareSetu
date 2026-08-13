"""PHASE-2 T6: issue_session + validate_token against a real PostgreSQL (ticket #57).

Exercises the facade through its typed seam (Spec #51, Seam 1): a verified
patient gets a session JWT carrying the patient scope from their role grant,
the ``iam_sessions`` row records the jti/scope/expiry anchor the refresh
rotation (T7) checks, and ``validate_token`` resolves the scope back with no
DB round-trip. Refusal states - unverified, Suspended, missing role grant,
unknown phone - all refuse issuance with ``SessionIssuanceError``. Requires the
native PostgreSQL; the suite skips cleanly when it is unreachable, and the
``iam`` schema is migrated up for the module and down again afterwards.
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

from modules.iam.adapters.sms import MockSmsAdapter, SmsAdapter
from modules.iam.domain.exceptions import AccessTokenExpiredError, SessionIssuanceError
from modules.iam.domain.jwt import verify_token
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


def _facade(database_url: str, sms: SmsAdapter, clock: MutableClock) -> IamFacade:
    engine = create_async_engine(database_url, poolclass=NullPool)
    return IamFacade(
        engine=engine,
        sms_adapter=sms,
        clock=clock,
        access_token_signing_key=_KEY,
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
        "SELECT jti, identity_id, scope, issued_at, expires_at, revoked_at "
        "FROM iam.iam_sessions",
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
            await connection.execute(
                text("UPDATE iam.iam_identities SET status = 'Suspended'")
            )
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


async def test_issue_session_refuses_an_unknown_phone(
    database_url: str, clean_iam: Any
) -> None:
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


async def test_validate_token_resolves_an_issued_token(
    database_url: str, clean_iam: Any
) -> None:
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
