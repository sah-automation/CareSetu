"""PHASE-5 T02: create_credential_account against a real PostgreSQL (ticket #245).

Exercises the ADR-0010 sync seam the ``partner`` module will call during
registration: the identity is created in one transaction with the
``partner.registered`` outbox event, holds no ``partner``/``patient`` role
grant yet, and the resulting identity can begin a phone-OTP login via
``resend_otp`` (the begin-or-resume path resolves the existing identity and
issues a fresh challenge). The role grant is deliberately out of scope - that
is the activation-gated step T03 (#246).

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, and the ``iam`` schema is migrated up for the module and down
again afterwards, leaving the database as it was found.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
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
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_T0 = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)


class MutableClock:
    """Clock stand-in that tests advance to walk cooldown windows."""

    def __init__(self, now: datetime) -> None:
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
async def clean_iam(database_url: str, iam_schema: None) -> AsyncIterator[None]:
    """Empty the iam tables before every test so they start from a clean slate."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE iam.iam_identities, iam.iam_otp_challenges, "
                    "iam.iam_outbox CASCADE"
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


def _facade(database_url: str, sms: SmsAdapter) -> IamFacade:
    engine = create_async_engine(database_url, poolclass=NullPool)
    return IamFacade(engine=engine, sms_adapter=sms, clock=MutableClock(_T0))


async def _flush(facade: IamFacade) -> None:
    await facade.delivery_queue.flush()


async def test_partner_credential_created_in_one_tx_with_no_role_grant(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms)

    result = await facade.create_credential_account("9876543210")

    assert result.phone_e164 == _PHONE
    assert isinstance(result.identity_id, int)

    identities = await _query(
        database_url,
        "SELECT id, phone_e164, status FROM iam.iam_identities ORDER BY id",
    )
    assert len(identities) == 1
    assert identities[0]["phone_e164"] == _PHONE
    assert identities[0]["status"] == "Unverified"
    assert identities[0]["id"] == result.identity_id

    grants = await _query(database_url, "SELECT identity_id, role FROM iam.iam_role_grants")
    assert grants == []

    outbox = await _query(database_url, "SELECT event_type, payload FROM iam.iam_outbox")
    assert [row["event_type"] for row in outbox] == ["partner.registered"]
    assert outbox[0]["payload"] == {"identity_id": result.identity_id, "phone_e164": _PHONE}


async def test_partner_credential_account_can_begin_otp_login(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms)

    created = await facade.create_credential_account("9876543210")

    login = await facade.resend_otp("9876543210")
    await _flush(facade)

    assert login.outcome == "sent"
    assert login.phone_e164 == _PHONE
    assert sms.sent_count(_PHONE) == 1
    assert sms.last_sent_code(_PHONE) is not None

    challenges = await _query(
        database_url, "SELECT identity_id, status FROM iam.iam_otp_challenges"
    )
    assert len(challenges) == 1
    assert challenges[0]["identity_id"] == created.identity_id
    assert challenges[0]["status"] == "Pending"
