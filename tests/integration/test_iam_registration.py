"""PHASE-2 T3: register_patient against a real PostgreSQL (ticket #54, #76).

Exercises the facade through its typed seam with the EXT-001 adapter stubbed
(Spec #51, Seam 1): first-time creation, existing-phone resolution, E.164
normalization convergence, concurrent duplicate resolution, the same-
transaction outbox rows, and the atomic-commit guarantee when the SMS send
fails after the transaction. Also covers the PHASE-2 REM T3 anti-spam gate
(ticket #76): an existing phone inside the resend cooldown or brute-force
lockout, or Suspended, is refused on register with no challenge, no ``otp.sent``,
and no SMS - first-time registration and out-of-cooldown login are unchanged.
Re-entering an existing phone out of cooldown is latest-wins (PHASE-2 REM FIX 1,
#101): the pending challenge is invalidated before the fresh one is issued, so
the older code can no longer verify - the same invalidate-and-issue pair
``resend_otp`` uses.
Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, and the ``iam`` schema is migrated up for the module and down
again afterwards, leaving the database as it was found.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
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
from modules.iam.domain.exceptions import InvalidPhoneError, SmsDeliveryError
from modules.iam.domain.otp import OTP_TTL_SECONDS, verify_otp
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_T0 = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_WRONG = "000000"


class MutableClock:
    """Clock stand-in that tests advance to walk cooldown and lockout windows."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def set(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


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


def _facade(database_url: str, sms: SmsAdapter, clock: MutableClock) -> IamFacade:
    engine = create_async_engine(database_url, poolclass=NullPool)
    return IamFacade(engine=engine, sms_adapter=sms, clock=clock)


async def _flush(facade: IamFacade) -> None:
    """Await the facade's background SMS deliveries (PHASE-2 REM T4, #86).

    Delivery leaves the request path, so the mock adapter's read surface is
    only populated once the background task runs; tests await the queue before
    asserting on sent codes.
    """
    await facade.delivery_queue.flush()


async def test_first_time_phone_creates_identity_issues_otp_and_writes_events(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms, MutableClock(_T0))

    result = await facade.register_patient("9876543210")
    await _flush(facade)

    assert result.phone_e164 == _PHONE
    assert result.outcome == "sent"
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
    sent_row = next(row for row in outbox if row["event_type"] == "otp.sent")
    assert sent_row["payload"]["challenge_id"] == result.challenge_id
    assert sent_row["payload"]["identity_id"] == identity["id"]
    assert sent not in str(sent_row["payload"])


async def test_existing_phone_resolves_identity_and_issues_login_otp(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    clock = MutableClock(_T0)
    facade = _facade(database_url, sms, clock)

    first = await facade.register_patient("9876543210")
    clock.set(_T0 + timedelta(seconds=61))
    second = await facade.register_patient("9876543210")
    await _flush(facade)

    assert first.flow == "register"
    assert second.flow == "login"
    assert second.outcome == "sent"
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
    sms = MockSmsAdapter()
    clock = MutableClock(_T0)
    facade = _facade(database_url, sms, clock)

    bare = await facade.register_patient("9876543210")
    clock.set(_T0 + timedelta(seconds=61))
    prefixed = await facade.register_patient("919876543210")
    clock.set(_T0 + timedelta(seconds=122))
    spaced = await facade.register_patient("+91 98765 43210")

    assert bare.phone_e164 == prefixed.phone_e164 == spaced.phone_e164 == _PHONE
    assert bare.identity_id == prefixed.identity_id == spaced.identity_id
    assert all(result.outcome == "sent" for result in (bare, prefixed, spaced))
    identities = await _query(database_url, "SELECT id FROM iam.iam_identities")
    assert len(identities) == 1


async def test_concurrent_registrations_converge_to_one_identity(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms, MutableClock(_T0))

    results = await asyncio.gather(
        facade.register_patient("9876543210"),
        facade.register_patient("9876543210"),
    )
    await _flush(facade)

    identity_ids = {result.identity_id for result in results}
    assert len(identity_ids) == 1
    outcomes = sorted(result.outcome for result in results)
    assert outcomes == ["cooldown", "sent"]
    identities = await _query(database_url, "SELECT id FROM iam.iam_identities")
    assert len(identities) == 1
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    event_types = sorted(row["event_type"] for row in outbox)
    assert event_types.count("patient.registered") == 1
    assert event_types.count("otp.sent") == 1
    assert sms.sent_count(_PHONE) == 1


async def test_sms_delivery_failure_never_blocks_register_but_state_commits_atomically(
    database_url: str, clean_iam: Any
) -> None:
    facade = _facade(database_url, FailingSmsAdapter(), MutableClock(_T0))

    result = await facade.register_patient("9876543210")
    await _flush(facade)

    assert result.outcome == "sent"
    assert result.flow == "register"
    identities = await _query(database_url, "SELECT id FROM iam.iam_identities")
    assert len(identities) == 1
    challenges = await _query(database_url, "SELECT id FROM iam.iam_otp_challenges")
    assert len(challenges) == 1
    outbox = await _query(database_url, "SELECT event_type, payload, status FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox) == [
        "otp.failed",
        "otp.sent",
        "patient.registered",
    ]
    assert all(row["status"] == "pending" for row in outbox)
    failed = next(row for row in outbox if row["event_type"] == "otp.failed")
    assert failed["payload"]["reason"] == "delivery"
    assert failed["payload"]["phone_e164"] == _PHONE
    assert failed["payload"]["lockout_until"] is None


async def test_invalid_phone_is_rejected_without_db_writes(
    database_url: str, clean_iam: Any
) -> None:
    facade = _facade(database_url, MockSmsAdapter(), MutableClock(_T0))

    with pytest.raises(InvalidPhoneError):
        await facade.register_patient("14445556666")

    assert await _query(database_url, "SELECT id FROM iam.iam_identities") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_otp_challenges") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_outbox") == []


async def _trigger_lockout(facade: IamFacade, clock: MutableClock) -> None:
    """Burn both challenges so the 10th failure triggers the 15-minute lockout.

    Challenge 1 eats the 5-attempt budget, a resend past the cooldown issues
    challenge 2 which eats 5 more - the last one is the 10th consecutive
    failure across challenges and must return the ``locked`` outcome.
    """
    for _ in range(4):
        assert (await facade.verify_otp("9876543210", _WRONG)).outcome == "wrong_code"
    assert (await facade.verify_otp("9876543210", _WRONG)).outcome == "spent"
    clock.set(_T0 + timedelta(seconds=61))
    assert (await facade.resend_otp("9876543210")).outcome == "sent"
    for _ in range(4):
        assert (await facade.verify_otp("9876543210", _WRONG)).outcome == "wrong_code"
    assert (await facade.verify_otp("9876543210", _WRONG)).outcome == "locked"


async def test_existing_phone_inside_cooldown_is_refused_without_a_challenge_or_sms(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms, clock)

    await facade.register_patient("9876543210")
    await _flush(facade)
    clock.set(_T0 + timedelta(seconds=30))
    refused = await facade.register_patient("9876543210")

    assert refused.outcome == "cooldown"
    assert refused.phone_e164 == _PHONE
    assert refused.is_existing is True
    assert refused.flow == "login"
    assert refused.challenge_id is None
    assert refused.expires_in_seconds is None
    assert refused.attempts_left is None
    assert refused.cooldown_remaining_seconds == 30
    assert refused.lockout_remaining_seconds is None
    assert sms.sent_count(_PHONE) == 1

    challenges = await _query(database_url, "SELECT id FROM iam.iam_otp_challenges")
    assert len(challenges) == 1
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox).count("otp.sent") == 1


async def test_existing_phone_is_allowed_at_the_exact_cooldown_boundary(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms, clock)

    await facade.register_patient("9876543210")
    clock.set(_T0 + timedelta(seconds=60))
    allowed = await facade.register_patient("9876543210")
    await _flush(facade)

    assert allowed.outcome == "sent"
    assert allowed.flow == "login"
    assert allowed.is_existing is True
    assert isinstance(allowed.challenge_id, int)
    assert allowed.cooldown_remaining_seconds == 60
    assert sms.sent_count(_PHONE) == 2


async def test_re_entering_existing_phone_is_latest_wins_and_shadows_the_pending_code(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms, clock)

    await facade.register_patient("9876543210")
    await _flush(facade)
    first_code = sms.last_sent_code(_PHONE)
    assert first_code is not None and len(first_code) == 6

    clock.set(_T0 + timedelta(seconds=61))
    second = await facade.register_patient("9876543210")
    await _flush(facade)
    second_code = sms.last_sent_code(_PHONE)

    assert second.outcome == "sent"
    assert second.phone_e164 == _PHONE
    assert second.flow == "login"
    assert second.is_existing is True
    assert isinstance(second.challenge_id, int)
    assert second.expires_in_seconds == OTP_TTL_SECONDS
    assert second.cooldown_remaining_seconds == 60
    assert second.attempts_left == 5
    assert second_code is not None and second_code != first_code

    challenges = await _query(
        database_url, "SELECT status, attempts FROM iam.iam_otp_challenges ORDER BY id"
    )
    assert [row["status"] for row in challenges] == ["Expired", "Pending"]
    assert all(row["attempts"] == 0 for row in challenges)

    stale = await facade.verify_otp("9876543210", first_code)
    assert stale.outcome != "verified"
    fresh = await facade.verify_otp("9876543210", second_code)
    assert fresh.outcome == "verified"

    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox).count("otp.sent") == 2


async def test_existing_phone_inside_lockout_is_refused_without_a_challenge_or_sms(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms, clock)

    await facade.register_patient("9876543210")
    await _flush(facade)
    await _trigger_lockout(facade, clock)
    await _flush(facade)

    refused = await facade.register_patient("9876543210")

    assert refused.outcome == "locked"
    assert refused.phone_e164 == _PHONE
    assert refused.is_existing is True
    assert refused.challenge_id is None
    assert refused.expires_in_seconds is None
    assert refused.attempts_left is None
    assert refused.cooldown_remaining_seconds is None
    assert refused.lockout_remaining_seconds is not None
    assert sms.sent_count(_PHONE) == 2

    challenges = await _query(database_url, "SELECT id FROM iam.iam_otp_challenges")
    assert len(challenges) == 2
    identities = await _query(
        database_url, "SELECT status, lockout_failed_attempts FROM iam.iam_identities"
    )
    assert identities == [{"status": "Unverified", "lockout_failed_attempts": 10}]
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox).count("otp.sent") == 2
    assert sorted(row["event_type"] for row in outbox).count("otp.failed") == 1


async def test_register_for_suspended_identity_is_refused_without_a_challenge_or_sms(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade = _facade(database_url, sms, clock)

    await facade.register_patient("9876543210")
    await _flush(facade)

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE iam.iam_identities SET status = 'Suspended'"))
    finally:
        await engine.dispose()

    refused = await facade.register_patient("9876543210")

    assert refused.outcome == "suspended"
    assert refused.is_existing is True
    assert refused.challenge_id is None
    assert refused.cooldown_remaining_seconds is None
    assert refused.lockout_remaining_seconds is None
    assert sms.sent_count(_PHONE) == 1

    identities = await _query(database_url, "SELECT status FROM iam.iam_identities")
    assert identities == [{"status": "Suspended"}]
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox).count("otp.sent") == 1
