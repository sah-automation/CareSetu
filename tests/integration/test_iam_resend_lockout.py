"""PHASE-2 T5: resend_otp + brute-force lockout against a real PostgreSQL (#56).

Exercises the facade through its typed seam with the EXT-001 adapter stubbed
(Spec #51, Seam 1): latest-wins resend (invalidate pending, issue fresh), the
>= 60 s per-phone cooldown boundary, the 10-consecutive-failure lockout across
challenges with expiry, enforcement on both verify and resend, the lockout as
a counter never identity state (``Suspended`` stays operator-only), and the
same-transaction outbox rows (``otp.sent`` on resend, ``otp.failed`` on the
lockout trigger). Requires the native PostgreSQL; the suite skips cleanly when
it is unreachable, and the ``iam`` schema is migrated up for the module and
down again afterwards, leaving the database as it was found.
"""

from __future__ import annotations

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

from modules.iam.adapters.sms import MockSmsAdapter, SmsAdapter
from modules.iam.domain.exceptions import InvalidPhoneError
from modules.iam.domain.lockout import LOCKOUT_SECONDS
from modules.iam.domain.otp import OTP_TTL_SECONDS
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_T0 = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_WRONG = "000000"


class MutableClock:
    """Clock stand-in that tests advance to walk cooldown, TTL, and lockout."""

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


async def _register(
    database_url: str, sms: MockSmsAdapter, clock: MutableClock
) -> tuple[IamFacade, str]:
    facade = _facade(database_url, sms, clock)
    await facade.register_patient("9876543210")
    await _flush(facade)
    sent = sms.last_sent_code(_PHONE)
    assert sent is not None and len(sent) == 6
    return facade, sent


async def _spend_budget(facade: IamFacade) -> None:
    for _ in range(4):
        assert (await facade.verify_otp("9876543210", _WRONG)).outcome == "wrong_code"
    assert (await facade.verify_otp("9876543210", _WRONG)).outcome == "spent"


async def _exhaust_and_relock(facade: IamFacade, clock: MutableClock, sms: MockSmsAdapter) -> None:
    """Burn both challenges so the 10th failure triggers the lockout.

    Challenge 1 eats 5 failures, then a resend (clock past the cooldown) issues
    challenge 2, which eats 5 more - the last one is the 10th consecutive
    failure across challenges and must return the ``locked`` outcome.
    """
    await _spend_budget(facade)
    clock.set(_T0 + timedelta(seconds=61))
    resend = await facade.resend_otp("9876543210")
    assert resend.outcome == "sent"
    await _flush(facade)
    code = sms.last_sent_code(_PHONE)
    assert code is not None
    for _ in range(4):
        assert (await facade.verify_otp("9876543210", _WRONG)).outcome == "wrong_code"
    triggered = await facade.verify_otp("9876543210", _WRONG)
    assert triggered.outcome == "locked"
    assert triggered.lockout_remaining_seconds is not None


async def test_resend_after_cooldown_issues_fresh_challenge_and_invalidates_pending(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, first_code = await _register(database_url, sms, clock)

    clock.set(_T0 + timedelta(seconds=61))
    resend = await facade.resend_otp("9876543210")

    assert resend.outcome == "sent"
    assert resend.phone_e164 == _PHONE
    assert isinstance(resend.challenge_id, int)
    assert resend.expires_in_seconds == OTP_TTL_SECONDS
    assert resend.cooldown_remaining_seconds == 60
    assert resend.attempts_left == 5
    await _flush(facade)
    second_code = sms.last_sent_code(_PHONE)
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


async def test_resend_inside_cooldown_is_refused_and_allowed_at_the_boundary(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, _first_code = await _register(database_url, sms, clock)

    clock.set(_T0 + timedelta(seconds=59))
    blocked = await facade.resend_otp("9876543210")

    assert blocked.outcome == "cooldown"
    assert blocked.cooldown_remaining_seconds == 1
    assert sms.sent_count(_PHONE) == 1

    clock.set(_T0 + timedelta(seconds=60))
    allowed = await facade.resend_otp("9876543210")

    assert allowed.outcome == "sent"
    await _flush(facade)
    assert sms.sent_count(_PHONE) == 2


async def test_ten_consecutive_failures_trigger_lockout_as_counter_not_status(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, _ = await _register(database_url, sms, clock)

    await _exhaust_and_relock(facade, clock, sms)

    identities = await _query(
        database_url,
        "SELECT status, lockout_failed_attempts, lockout_until FROM iam.iam_identities",
    )
    assert identities == [
        {
            "status": "Unverified",
            "lockout_failed_attempts": 10,
            "lockout_until": _T0 + timedelta(seconds=61 + LOCKOUT_SECONDS),
        }
    ]

    outbox = await _query(database_url, "SELECT event_type, payload FROM iam.iam_outbox")
    event_types = sorted(row["event_type"] for row in outbox)
    assert event_types.count("patient.auth_failed") == 10
    assert event_types.count("otp.failed") == 1
    failed = next(row for row in outbox if row["event_type"] == "otp.failed")
    assert failed["payload"]["reason"] == "lockout"
    assert failed["payload"]["phone_e164"] == _PHONE
    assert failed["payload"]["lockout_until"] == "2026-08-13T12:16:01Z"


async def test_verify_and_resend_are_refused_while_locked(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, code = await _register(database_url, sms, clock)
    await _exhaust_and_relock(facade, clock, sms)

    verify = await facade.verify_otp("9876543210", code)

    assert verify.outcome == "locked"
    assert verify.lockout_remaining_seconds is not None

    resend = await facade.resend_otp("9876543210")

    assert resend.outcome == "locked"
    assert resend.lockout_remaining_seconds is not None
    assert sms.sent_count(_PHONE) == 2

    identities = await _query(
        database_url,
        "SELECT lockout_failed_attempts, lockout_until FROM iam.iam_identities",
    )
    assert identities[0]["lockout_failed_attempts"] == 10
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox).count("otp.failed") == 1


async def test_lockout_expires_and_success_resets_the_counter(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, _ = await _register(database_url, sms, clock)
    await _exhaust_and_relock(facade, clock, sms)

    clock.set(_T0 + timedelta(seconds=61 + LOCKOUT_SECONDS + 1))
    resend = await facade.resend_otp("9876543210")

    assert resend.outcome == "sent"
    await _flush(facade)
    fresh_code = sms.last_sent_code(_PHONE)
    assert fresh_code is not None
    verified = await facade.verify_otp("9876543210", fresh_code)

    assert verified.outcome == "verified"

    identities = await _query(
        database_url,
        "SELECT status, lockout_failed_attempts, lockout_until FROM iam.iam_identities",
    )
    assert identities == [
        {
            "status": "Active",
            "lockout_failed_attempts": 0,
            "lockout_until": None,
        }
    ]


async def test_lockout_expires_and_failure_starts_a_fresh_streak(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, _ = await _register(database_url, sms, clock)
    await _exhaust_and_relock(facade, clock, sms)

    clock.set(_T0 + timedelta(seconds=61 + LOCKOUT_SECONDS + 1))
    resend = await facade.resend_otp("9876543210")

    assert resend.outcome == "sent"
    await _flush(facade)
    fresh_code = sms.last_sent_code(_PHONE)
    assert fresh_code is not None

    wrong = await facade.verify_otp("9876543210", _WRONG)

    assert wrong.outcome == "wrong_code"

    identities = await _query(
        database_url,
        "SELECT status, lockout_failed_attempts, lockout_until FROM iam.iam_identities",
    )
    assert identities == [
        {
            "status": "Unverified",
            "lockout_failed_attempts": 1,
            "lockout_until": None,
        }
    ]
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox).count("otp.failed") == 1


async def test_resend_for_suspended_identity_is_refused(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, _ = await _register(database_url, sms, clock)

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE iam.iam_identities SET status = 'Suspended'"))
    finally:
        await engine.dispose()

    result = await facade.resend_otp("9876543210")

    assert result.outcome == "suspended"
    assert result.challenge_id is None
    assert sms.sent_count(_PHONE) == 1

    identities = await _query(database_url, "SELECT status FROM iam.iam_identities")
    assert identities == [{"status": "Suspended"}]
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox).count("otp.sent") == 1


async def test_resend_for_unknown_phone_is_refused(database_url: str, clean_iam: Any) -> None:
    facade = _facade(database_url, MockSmsAdapter(), MutableClock(_T0))

    result = await facade.resend_otp("9876543210")

    assert result.outcome == "no_identity"
    assert result.challenge_id is None
    assert await _query(database_url, "SELECT id FROM iam.iam_identities") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_otp_challenges") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_outbox") == []


async def test_invalid_phone_is_rejected_without_db_writes(
    database_url: str, clean_iam: Any
) -> None:
    facade = _facade(database_url, MockSmsAdapter(), MutableClock(_T0))

    with pytest.raises(InvalidPhoneError):
        await facade.resend_otp("14445556666")

    assert await _query(database_url, "SELECT id FROM iam.iam_identities") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_otp_challenges") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_outbox") == []
