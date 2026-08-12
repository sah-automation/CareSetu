"""PHASE-2 T4: verify_otp against a real PostgreSQL (ticket #55).

Exercises the facade through its typed seam with the EXT-001 adapter stubbed
(Spec #51, Seam 1): the OTP challenge machine's transitions, the single-use
consume + identity ``[Unverified] -> [Active]`` + patient-role grant, and the
same-transaction outbox rows (``patient.verified`` on success,
``patient.auth_failed`` on every rejection, never both). Requires the native
PostgreSQL; the suite skips cleanly when it is unreachable, and the ``iam``
schema is migrated up for the module and down again afterwards, leaving the
database as it was found.
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

from modules.iam.adapters.sms import MockSmsAdapter, SmsAdapter
from modules.iam.domain.exceptions import InvalidPhoneError
from modules.iam.domain.otp import OTP_TTL_SECONDS
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_T0 = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_WRONG = "000000"


class MutableClock:
    """Clock stand-in that tests advance to walk the 5-minute TTL."""

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


async def _register(
    database_url: str, sms: MockSmsAdapter, clock: MutableClock
) -> tuple[IamFacade, str]:
    facade = _facade(database_url, sms, clock)
    await facade.register_patient("9876543210")
    sent = sms.last_sent_code(_PHONE)
    assert sent is not None and len(sent) == 6
    return facade, sent


async def test_correct_code_verifies_identity_grants_role_and_writes_event(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade, sent = await _register(database_url, sms, MutableClock(_T0))

    result = await facade.verify_otp("9876543210", sent)

    assert result.outcome == "verified"
    assert result.phone_e164 == _PHONE
    assert result.attempts_left is None
    assert isinstance(result.identity_id, int)

    challenges = await _query(
        database_url,
        "SELECT status, attempts, verified_at FROM iam.iam_otp_challenges",
    )
    assert challenges == [{"status": "Verified", "attempts": 0, "verified_at": _T0}]

    identities = await _query(database_url, "SELECT status FROM iam.iam_identities")
    assert identities == [{"status": "Active"}]

    grants = await _query(database_url, "SELECT role, status FROM iam.iam_role_grants")
    assert grants == [{"role": "patient", "status": "Active"}]

    outbox = await _query(database_url, "SELECT event_type, payload, status FROM iam.iam_outbox")
    assert all(row["status"] == "pending" for row in outbox)
    assert "patient.auth_failed" not in {row["event_type"] for row in outbox}
    verified = next(row for row in outbox if row["event_type"] == "patient.verified")
    assert verified["payload"] == {
        "identity_id": result.identity_id,
        "phone_e164": _PHONE,
    }
    assert sent not in str(verified["payload"])


async def test_correct_code_cannot_be_replayed(database_url: str, clean_iam: Any) -> None:
    sms = MockSmsAdapter()
    facade, sent = await _register(database_url, sms, MutableClock(_T0))

    first = await facade.verify_otp("9876543210", sent)
    replay = await facade.verify_otp("9876543210", sent)

    assert first.outcome == "verified"
    assert replay.outcome == "expired"

    identities = await _query(database_url, "SELECT status FROM iam.iam_identities")
    assert identities == [{"status": "Active"}]
    grants = await _query(database_url, "SELECT count(*) AS n FROM iam.iam_role_grants")
    assert grants[0]["n"] == 1

    outbox = await _query(database_url, "SELECT event_type, payload FROM iam.iam_outbox")
    event_types = sorted(row["event_type"] for row in outbox)
    assert event_types.count("patient.verified") == 1
    assert event_types.count("patient.auth_failed") == 1
    failed = next(row for row in outbox if row["event_type"] == "patient.auth_failed")
    assert failed["payload"]["reason"] == "replay"


async def test_wrong_code_decrements_budget_and_keeps_the_code_alive(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade, sent = await _register(database_url, sms, MutableClock(_T0))

    wrong = await facade.verify_otp("9876543210", _WRONG)

    assert wrong.outcome == "wrong_code"
    assert wrong.attempts_left == 4
    assert isinstance(wrong.identity_id, int)

    challenges = await _query(database_url, "SELECT status, attempts FROM iam.iam_otp_challenges")
    assert challenges == [{"status": "Pending", "attempts": 1}]
    identities = await _query(database_url, "SELECT status FROM iam.iam_identities")
    assert identities == [{"status": "Unverified"}]

    outbox = await _query(database_url, "SELECT event_type, payload FROM iam.iam_outbox")
    assert "patient.verified" not in {row["event_type"] for row in outbox}
    failed = next(row for row in outbox if row["event_type"] == "patient.auth_failed")
    assert failed["payload"]["reason"] == "wrong_code"
    assert failed["payload"]["attempts_left"] == 4

    correct = await facade.verify_otp("9876543210", sent)
    assert correct.outcome == "verified"


async def test_exhausting_the_budget_spends_the_challenge(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade, sent = await _register(database_url, sms, MutableClock(_T0))

    for _ in range(4):
        assert (await facade.verify_otp("9876543210", _WRONG)).outcome == "wrong_code"
    spent = await facade.verify_otp("9876543210", _WRONG)

    assert spent.outcome == "spent"
    assert spent.attempts_left == 0

    challenges = await _query(database_url, "SELECT status, attempts FROM iam.iam_otp_challenges")
    assert challenges == [{"status": "Failed", "attempts": 5}]

    outbox = await _query(database_url, "SELECT event_type, payload FROM iam.iam_outbox")
    failures = [row for row in outbox if row["event_type"] == "patient.auth_failed"]
    assert [row["payload"]["reason"] for row in failures] == [
        "wrong_code",
        "wrong_code",
        "wrong_code",
        "wrong_code",
        "spent",
    ]
    spent_failure = failures[-1]
    assert spent_failure["payload"]["attempts_left"] == 0

    rejected = await facade.verify_otp("9876543210", sent)
    assert rejected.outcome == "expired"
    assert rejected.attempts_left is None


async def test_expired_challenge_is_rejected(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    sms = MockSmsAdapter()
    facade, _sent = await _register(database_url, sms, clock)

    clock.set(_T0 + timedelta(seconds=OTP_TTL_SECONDS + 1))
    result = await facade.verify_otp("9876543210", _sent)

    assert result.outcome == "expired"
    assert result.attempts_left is None

    challenges = await _query(database_url, "SELECT status, attempts FROM iam.iam_otp_challenges")
    assert challenges == [{"status": "Expired", "attempts": 0}]
    identities = await _query(database_url, "SELECT status FROM iam.iam_identities")
    assert identities == [{"status": "Unverified"}]
    grants = await _query(database_url, "SELECT count(*) AS n FROM iam.iam_role_grants")
    assert grants[0]["n"] == 0

    outbox = await _query(database_url, "SELECT event_type, payload FROM iam.iam_outbox")
    failed = next(row for row in outbox if row["event_type"] == "patient.auth_failed")
    assert failed["payload"]["reason"] == "expired"


async def test_verify_for_unknown_phone_is_rejected(database_url: str, clean_iam: Any) -> None:
    facade = _facade(database_url, MockSmsAdapter(), MutableClock(_T0))

    result = await facade.verify_otp("9876543210", "654321")

    assert result.outcome == "expired"
    assert result.identity_id is None
    assert result.attempts_left is None

    outbox = await _query(database_url, "SELECT event_type, payload FROM iam.iam_outbox")
    failed = next(row for row in outbox if row["event_type"] == "patient.auth_failed")
    assert failed["payload"]["identity_id"] is None
    assert failed["payload"]["reason"] == "no_challenge"


async def test_verify_for_suspended_identity_is_refused(database_url: str, clean_iam: Any) -> None:
    sms = MockSmsAdapter()
    clock = MutableClock(_T0)
    facade, sent = await _register(database_url, sms, clock)

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE iam.iam_identities SET status = 'Suspended'"))
    finally:
        await engine.dispose()

    result = await facade.verify_otp("9876543210", sent)

    assert result.outcome == "expired"
    assert result.attempts_left is None

    identities = await _query(database_url, "SELECT status FROM iam.iam_identities")
    assert identities == [{"status": "Suspended"}]
    challenges = await _query(database_url, "SELECT status, attempts FROM iam.iam_otp_challenges")
    assert challenges == [{"status": "Pending", "attempts": 0}]
    grants = await _query(database_url, "SELECT count(*) AS n FROM iam.iam_role_grants")
    assert grants[0]["n"] == 0

    outbox = await _query(database_url, "SELECT event_type, payload FROM iam.iam_outbox")
    assert "patient.verified" not in {row["event_type"] for row in outbox}
    failed = next(row for row in outbox if row["event_type"] == "patient.auth_failed")
    assert failed["payload"]["reason"] == "suspended"


async def test_login_verify_does_not_duplicate_the_role_grant(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    clock = MutableClock(_T0)
    facade, sent = await _register(database_url, sms, clock)

    await facade.verify_otp("9876543210", sent)
    second_flow = await facade.register_patient("9876543210")
    second_code = sms.last_sent_code(_PHONE)
    assert second_code is not None and second_code != sent
    assert second_flow.flow == "login"
    login = await facade.verify_otp("9876543210", second_code)

    assert login.outcome == "verified"
    grants = await _query(database_url, "SELECT role, status FROM iam.iam_role_grants")
    assert grants == [{"role": "patient", "status": "Active"}]
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    event_types = sorted(row["event_type"] for row in outbox)
    assert event_types.count("patient.verified") == 2
    assert event_types.count("patient.auth_failed") == 0


async def test_concurrent_verifications_consume_the_challenge_once(
    database_url: str, clean_iam: Any
) -> None:
    sms = MockSmsAdapter()
    facade, sent = await _register(database_url, sms, MutableClock(_T0))

    results = await asyncio.gather(
        facade.verify_otp("9876543210", sent),
        facade.verify_otp("9876543210", sent),
    )

    outcomes = sorted(result.outcome for result in results)
    assert outcomes == ["expired", "verified"]
    challenges = await _query(database_url, "SELECT status FROM iam.iam_otp_challenges")
    assert challenges == [{"status": "Verified"}]
    grants = await _query(database_url, "SELECT count(*) AS n FROM iam.iam_role_grants")
    assert grants[0]["n"] == 1
    outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert sorted(row["event_type"] for row in outbox).count("patient.verified") == 1


async def test_invalid_phone_is_rejected_without_db_writes(
    database_url: str, clean_iam: Any
) -> None:
    facade = _facade(database_url, MockSmsAdapter(), MutableClock(_T0))

    with pytest.raises(InvalidPhoneError):
        await facade.verify_otp("14445556666", "654321")

    assert await _query(database_url, "SELECT id FROM iam.iam_identities") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_otp_challenges") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_role_grants") == []
    assert await _query(database_url, "SELECT id FROM iam.iam_outbox") == []
