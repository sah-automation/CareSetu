"""US-27 (#263): 30-day credential auto-deletion after permanent rejection.

Exercises the cleanup seam end to end against a live PostgreSQL with a
``MutableClock`` (the clock stand-in the iam tests use to walk TTL windows):

- A first-time operator rejection schedules ``cleanup_due_at`` on the held
  credential rows (now + the 30-day cleanup window), still ``[Rejected]``.
- Inside the 30-day window, ``purge_expired_credentials`` is a no-op: the
  credential row and its encrypted artifact survive (AC2).
- At/after the 30-day boundary, ``purge_expired_credentials`` deletes the
  credential row AND its artifact file, and emits ``credential.invalidated``
  (with the real ``credential_id``) in the same transaction (AC1).
- A partner who recovered to a live status (e.g. reactivated) is NOT purged:
  their documents stay until that recovery round's own terminal decision.

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
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
from conftest import seed_daltonganj_service_area
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.domain.credentials import CredentialType
from modules.partner.facade import CredentialSubmission, PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_DOC_BYTES = b"medical registration certificate image"
_OPERATOR_ID = 77
_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)


class MutableClock:
    """Clock stand-in tests advance to walk the 30-day cleanup window."""

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
def migration(database_url: str) -> Iterator[None]:
    """Migrate all schemas to head for the module, restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_partner(database_url: str, migration: None) -> AsyncIterator[None]:
    """Empty the iam + partner tables before every test for a clean slate."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE partner.partner_verifications, "
                    "partner.partner_credentials, partner.partner_profiles, "
                    "partner.partner_outbox, partner.partner_service_areas, "
                    "iam.iam_role_grants, iam.iam_sessions, "
                    "iam.iam_otp_challenges, iam.iam_outbox, "
                    "iam.iam_identities CASCADE"
                )
            )
            await seed_daltonganj_service_area(connection)
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
    database_url: str, tmp_path: Path, clock: MutableClock | None = None
) -> tuple[IamFacade, PartnerFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))
    kwargs: dict[str, Any] = {"credential_cleanup_days": 30}
    if clock is not None:
        kwargs["clock"] = clock
    partner = PartnerFacade(engine=engine, iam_facade=iam, artifact_store=store, **kwargs)
    return iam, partner


async def _register_doctor(partner: PartnerFacade, phone: str = "9876543210") -> int:
    result = await partner.register(
        phone=phone,
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=24.04,
        practice_longitude=84.07,
    )
    assert result.status == "Registered"
    return result.partner_id


def _medical_submission() -> list[CredentialSubmission]:
    return [
        CredentialSubmission(
            credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES]
        )
    ]


@pytest.mark.asyncio
async def test_rejection_schedules_30_day_cleanup_window(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """US-27: a permanent rejection schedules cleanup_due_at = now + 30 days on the
    held credential row; inside the window the purge is a no-op (AC2)."""
    clock = MutableClock(_NOW)
    _, partner = _facade(database_url, tmp_path, clock=clock)
    partner_id = await _register_doctor(partner)
    await partner.submit_credentials(partner_id, credentials=_medical_submission())

    await partner.operator_decision(
        partner_id, decision_by=_OPERATOR_ID, approve=False, reason="documents unreadable"
    )

    profile = await _query(database_url, "SELECT status FROM partner.partner_profiles")
    assert profile == [{"status": "Rejected"}]
    creds = await _query(
        database_url,
        "SELECT credential_type, cleanup_due_at FROM partner.partner_credentials",
    )
    assert len(creds) == 1
    due = creds[0]["cleanup_due_at"].replace(tzinfo=UTC)
    assert due == _NOW + timedelta(days=30)

    artifact = tmp_path / "partner" / str(partner_id) / "medical_registration_0.enc"
    assert artifact.exists()

    # Still inside the window: nothing purges.
    deleted = await partner.purge_expired_credentials()
    assert deleted == []
    assert artifact.exists()


@pytest.mark.asyncio
async def test_purge_at_30_days_deletes_row_artifact_and_emits_invalidated(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """US-27 AC1: at the 30-day boundary the credential row + artifact are removed
    and credential.invalidated emits with the real credential_id, in one txn."""
    clock = MutableClock(_NOW)
    _, partner = _facade(database_url, tmp_path, clock=clock)
    partner_id = await _register_doctor(partner)
    await partner.submit_credentials(partner_id, credentials=_medical_submission())
    await partner.operator_decision(
        partner_id, decision_by=_OPERATOR_ID, approve=False, reason="fraud signal"
    )
    artifact = tmp_path / "partner" / str(partner_id) / "medical_registration_0.enc"
    assert artifact.exists()

    # Push the clock to exactly the 30-day boundary.
    clock.set(_NOW + timedelta(days=30))
    cred_row = await _query(database_url, "SELECT id FROM partner.partner_credentials")
    partner_cred_id = cred_row[0]["id"]
    deleted = await partner.purge_expired_credentials()

    assert deleted == [partner_cred_id]
    assert not artifact.exists()
    rows = await _query(database_url, "SELECT id FROM partner.partner_credentials")
    assert rows == []
    outbox = await _query(
        database_url,
        "SELECT event_type, payload FROM partner.partner_outbox "
        "WHERE event_type = 'credential.invalidated'",
    )
    assert outbox and outbox[0]["payload"]["credential_id"] == partner_cred_id
    assert outbox[0]["payload"]["reason"] == "permanent_rejection_cleanup"


@pytest.mark.asyncio
async def test_purge_after_window_removes_and_recovered_partner_kept(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """US-27 AC1/2: past the window the purge fires on still-[Rejected] partners,
    while a partner who recovered to [Active] keeps their documents (the purge
    only deletes on a permanent-rejection status)."""
    clock = MutableClock(_NOW)
    _, partner = _facade(database_url, tmp_path, clock=clock)

    # Partner A: rejected and remains [Rejected] -> purges after 30 days.
    pa = await _register_doctor(partner, phone="9876543001")
    await partner.submit_credentials(pa, credentials=_medical_submission())
    await partner.operator_decision(pa, decision_by=_OPERATOR_ID, approve=False, reason="bad docs")

    # Partner B: rejected (cleanup scheduled) then re-submits a new round and is
    # reactivated -> now [Active], so the purge must NOT touch its credentials.
    pb = await _register_doctor(partner, phone="9876543002")
    await partner.submit_credentials(pb, credentials=_medical_submission())
    await partner.operator_decision(
        pb, decision_by=_OPERATOR_ID, approve=False, reason="review failed"
    )
    await partner.submit_credentials(pb, credentials=_medical_submission())
    await partner.operator_decision(pb, decision_by=_OPERATOR_ID, approve=True)

    clock.set(_NOW + timedelta(days=31))
    deleted = await partner.purge_expired_credentials()
    # Exactly A's credential is purged (still [Rejected]); partner B's rows are
    # retained because B recovered to [Active].
    assert len(deleted) == 1

    creds = await _query(database_url, "SELECT profile_id FROM partner.partner_credentials")
    # B holds both its round-1 (rejected) and round-2 (reactivated) credentials.
    assert [c["profile_id"] for c in creds] == [pb, pb]
