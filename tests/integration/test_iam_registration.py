"""PHASE-2 T3: register_patient against a real PostgreSQL (ticket #54).

Exercises the facade through its typed seam with the EXT-001 adapter stubbed
(Spec #51, Seam 1): first-time creation, existing-phone resolution, E.164
normalization convergence, concurrent duplicate resolution, the same-
transaction outbox rows, and the atomic-commit guarantee when the SMS send
fails after the transaction. Requires the native PostgreSQL; the suite skips
cleanly when it is unreachable, and the ``iam`` schema is migrated up for the
module and down again afterwards, leaving the database as it was found.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
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
from modules.iam.domain.exceptions import InvalidPhoneError, SmsDeliveryError
from modules.iam.domain.otp import verify_otp
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"


class FailingSmsAdapter:
    """EXT-001 stand-in that always fails, to prove the DB commits independently."""

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        raise SmsDeliveryError("EXT-001 unavailable")


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
    return IamFacade(engine=engine, sms_adapter=sms)


async def test_first_time_phone_creates_identity_issues_otp_and_writes_events(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms)

    result = await facade.register_patient("9876543210")

    assert result.phone_e164 == _PHONE
    assert result.flow == "register"
    assert result.is_existing is False
    assert result.expires_in_seconds == 300
    assert result.cooldown_remaining_seconds == 60
    assert result.attempts_left == 5
    assert sms.sent_count(_PHONE) == 1
    sent = sms.last_sent_code(_PHONE)
    assert sent is not None and len(sent) == 6

    identities = await _query(database_url, "SELECT id, phone_e164, status FROM iam.iam_identities")
    assert len(identities) == 1
    identity = identities[0]
    assert identity["phone_e164"] == _PHONE
    assert identity["status"] == "Unverified"

    challenges = await _query(
        database_url,
        "SELECT identity_id, otp_hash, status, attempts FROM iam.iam_otp_challenges",
    )
    assert len(challenges) == 1
    challenge = challenges[0]
    assert challenge["identity_id"] == identity["id"]
    assert challenge["status"] == "Pending"
    assert challenge["attempts"] == 0
    assert sent not in challenge["otp_hash"]
    assert verify_otp(sent, challenge["otp_hash"]) is True

    outbox = await _query(database_url, "SELECT event_type, payload, status FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox) == ["otp.sent", "patient.registered"]
    assert all(row["status"] == "pending" for row in outbox)
    registered = next(row for row in outbox if row["event_type"] == "patient.registered")
    assert registered["payload"] == {"identity_id": identity["id"], "phone_e164": _PHONE}
    otp_sent = next(row for row in outbox if row["event_type"] == "otp.sent")
    assert otp_sent["payload"]["challenge_id"] == result.challenge_id
    assert otp_sent["payload"]["identity_id"] == identity["id"]
    assert sent not in str(otp_sent["payload"])


async def test_existing_phone_resolves_identity_and_issues_login_otp(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms)

    first = await facade.register_patient("9876543210")
    second = await facade.register_patient("9876543210")

    assert first.flow == "register"
    assert second.flow == "login"
    assert second.is_existing is True
    assert second.identity_id == first.identity_id
    assert sms.sent_count(_PHONE) == 2

    identities = await _query(database_url, "SELECT id, phone_e164 FROM iam.iam_identities")
    assert len(identities) == 1
    challenges = await _query(database_url, "SELECT id FROM iam.iam_otp_challenges")
    assert len(challenges) == 2
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    event_types = sorted(row["event_type"] for row in outbox)
    assert event_types.count("patient.registered") == 1
    assert event_types.count("otp.sent") == 2


async def test_normalized_phone_forms_converge_to_one_identity(
    database_url: str, clean_iam: Any
) -> None:
    facade = _facade(database_url, MockSmsAdapter())

    bare = await facade.register_patient("9876543210")
    prefixed = await facade.register_patient("919876543210")
    spaced = await facade.register_patient("+91 98765 43210")

    assert bare.phone_e164 == prefixed.phone_e164 == spaced.phone_e164 == _PHONE
    assert bare.identity_id == prefixed.identity_id == spaced.identity_id
    identities = await _query(database_url, "SELECT id FROM iam.iam_identities")
    assert len(identities) == 1


async def test_concurrent_registrations_converge_to_one_identity(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms)

    results = await asyncio.gather(
        facade.register_patient("9876543210"),
        facade.register_patient("9876543210"),
    )

    identity_ids = {result.identity_id for result in results}
    assert len(identity_ids) == 1
    identities = await _query(database_url, "SELECT id FROM iam.iam_identities")
    assert len(identities) == 1
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    event_types = sorted(row["event_type"] for row in outbox)
    assert event_types.count("patient.registered") == 1
    assert event_types.count("otp.sent") == 2
    assert sms.sent_count(_PHONE) == 2


async def test_sms_failure_propagates_but_state_commits_atomically(
    database_url: str, clean_iam: Any
) -> None:
    facade = _facade(database_url, FailingSmsAdapter())

    with pytest.raises(SmsDeliveryError):
        await facade.register_patient("9876543210")

    identities = await _query(database_url, "SELECT id FROM iam.iam_identities")
    assert len(identities) == 1
    challenges = await _query(database_url, "SELECT id FROM iam.iam_otp_challenges")
    assert len(challenges) == 1
    outbox = await _query(database_url, "SELECT event_type, status FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox) == ["otp.sent", "patient.registered"]
    assert all(row["status"] == "pending" for row in outbox)


async def test_invalid_phone_is_rejected_without_db_writes(
    database_url: str, clean_iam: Any
) -> None:
    facade = _facade(database_url, MockSmsAdapter())

    with pytest.raises(InvalidPhoneError):
        await facade.register_patient("14445556666")

    assert await _query(database_url, "SELECT id FROM iam.iam_identities") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_otp_challenges") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_outbox") == []
