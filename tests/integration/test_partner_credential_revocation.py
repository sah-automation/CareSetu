"""PHASE-6 T04a (#315): credential revocation against a live PostgreSQL.

Exercises the ``invalidate_credential`` close-out seam end to end, mirroring
``test_partner_credential_cleanup.py`` (alembic head + native PostgreSQL,
skips when unreachable):

- Revoking a partner who reached ``[Active]`` through the real register →
  submit → approve flow stamps ``revoked_at`` + ``invalidation_reason =
  'revoked'`` (actor ``revoked_by``) on the live credential rows, flips the
  ``partner_directory_index`` entry to ``is_active`` false, and writes exactly
  one ``credential.invalidated`` in the same transaction (AC).
- The revoked partner drops out of directory search instantly: the lazy read-hide
  (ADR-0011 ``_has_invalid_credential``) covers even an index row that was never
  deindexed, so visibility is correct regardless of cache state.
- Recovery is re-verification, never re-registration: the profile row survives
  the revocation, a fresh round re-opens and re-approves, and the profile is
  still ``[Active]`` on the SAME row (no new profile, no lifecycle detour).

Two seams are injected as raw SQL exactly like ``test_directory_search.py``
does: the index row (the app picks it up at migration-backfill time and the
activation index writer lands with the T01/T05 wiring) and the verified flag the
review-acceptance path will set (the search gate requires verified credentials).
The revocation itself goes through the real facade.

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from modules.partner.domain.exceptions import PartnerNotFoundError
from modules.partner.facade import (
    DALTONGANJ_LATITUDE,
    DALTONGANJ_LONGITUDE,
    CredentialSubmission,
    PartnerFacade,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_OPERATOR_ID = 77
_DOC_BYTES = b"medical registration certificate image"
_NOW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)


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
                    "partner.partner_directory_index, partner.partner_outbox, "
                    "partner.partner_service_areas, iam.iam_role_grants, "
                    "iam.iam_sessions, iam.iam_otp_challenges, iam.iam_outbox, "
                    "iam.consumed_events, iam.iam_identities CASCADE"
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


def _facade(database_url: str, tmp_path: Path) -> tuple[IamFacade, PartnerFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))
    partner = PartnerFacade(engine=engine, iam_facade=iam, artifact_store=store)
    return iam, partner


async def _approve_active_partner(partner: PartnerFacade, iam: IamFacade, phone: str) -> int:
    """Run the real Phase-5 flow to a visible ``[Active]`` partner.

    Register → submit one medical-registration credential → operator approve.
    The review-acceptance index writer and verified flag live in the T01/T05
    wiring (not this ticket's scope), so the directory index row and the
    ``verified`` mark are injected as raw SQL right after, exactly mirroring
    ``test_directory_search.py``'s flat seeding.
    """
    registered = await partner.register(
        phone=phone,
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=DALTONGANJ_LATITUDE,
        practice_longitude=DALTONGANJ_LONGITUDE,
    )
    assert registered.status == "Registered"
    partner_id = registered.partner_id
    await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES]
            )
        ],
    )
    await partner.operator_decision(partner_id, decision_by=_OPERATOR_ID, approve=True)
    return partner_id


async def _make_visible(database_url: str, partner_id: int) -> None:
    """Inject the index row + verified flag the Phase-6 writer seams still own."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO partner.partner_directory_index "
                    "(partner_id, practice_latitude, practice_longitude, "
                    " partner_type, is_active) "
                    "VALUES (:partner_id, :lat, :lon, 'doctor', true)"
                ),
                {
                    "partner_id": partner_id,
                    "lat": DALTONGANJ_LATITUDE,
                    "lon": DALTONGANJ_LONGITUDE,
                },
            )
            await connection.execute(
                text(
                    "UPDATE partner.partner_credentials SET verified = true "
                    "WHERE profile_id = :partner_id"
                ),
                {"partner_id": partner_id},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalidate_credential_revokes_deindexes_and_hides_from_search(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#315 AC: real-flow Active partner is visible, revokes, then vanishes.

    Before the revoke the directory search returns the partner (index row +
    verified credential present). ``invalidate_credential`` then stamps the
    close-out on the live credential row, flips the index entry inactive, and
    emits exactly one ``credential.invalidated`` - and the next search no longer
    returns the partner even though the profile is untouched (``[Active]``).
    """
    iam, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, iam, "9876543210")
    await _make_visible(database_url, partner_id)

    before = await partner.search_directory()
    assert [entry.partner_id for entry in before.items] == [partner_id]

    credential_id = int(
        (await _query(database_url, "SELECT id FROM partner.partner_credentials"))[0]["id"]
    )
    acting_principal = uuid4()

    result = await partner.invalidate_credential(partner_id, revoked_by=acting_principal)

    assert result.status == "Active"  # no lifecycle detour
    assert result.round == 1

    creds = await _query(
        database_url,
        "SELECT revoked_at, revoked_by, invalidation_reason FROM partner.partner_credentials",
    )
    assert len(creds) == 1
    assert creds[0]["revoked_at"] is not None
    assert creds[0]["revoked_by"] == acting_principal
    assert creds[0]["invalidation_reason"] == "revoked"

    index = await _query(database_url, "SELECT is_active FROM partner.partner_directory_index")
    assert index == [{"is_active": False}]

    outbox = await _query(
        database_url,
        "SELECT event_type, payload FROM partner.partner_outbox "
        "WHERE event_type = 'credential.invalidated'",
    )
    assert len(outbox) == 1  # exactly one event, same transaction
    payload = outbox[0]["payload"]
    assert payload["credential_id"] == credential_id
    assert payload["reason"] == "revoked"

    after = await partner.search_directory()
    assert [entry.partner_id for entry in after.items] == []


@pytest.mark.asyncio
async def test_revoked_partner_recovers_by_reverification_on_the_same_profile(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#315 AC: recovery is a fresh verification round - never a new profile.

    After the revocation the SAME profile row re-opens a round-2 verification,
    is approved again, and stays ``[Active]`` - one profile row throughout (revoke
    is a defer-of-visibility, ADR-0008/ADR-0011, not a termination).
    """
    iam, partner = _facade(database_url, tmp_path)
    partner_id = await _approve_active_partner(partner, iam, "9876543001")

    await partner.invalidate_credential(partner_id, revoked_by=uuid4())

    assert await _query(database_url, "SELECT count(*) AS n FROM partner.partner_profiles") == [
        {"n": 1}
    ]

    resubmitted = await partner.submit_credentials(
        partner_id,
        credentials=[
            CredentialSubmission(
                credential_type=CredentialType.MEDICAL_REGISTRATION, artifacts=[_DOC_BYTES]
            )
        ],
    )
    assert resubmitted.partner_id == partner_id
    assert resubmitted.round == 2

    reg = await partner.operator_decision(partner_id, decision_by=_OPERATOR_ID, approve=True)
    assert reg.status == "Active"
    assert reg.round == 2

    # Still exactly one profile row - recovery never re-registered the partner.
    profiles = await _query(database_url, "SELECT id, status FROM partner.partner_profiles")
    assert profiles == [{"id": partner_id, "status": "Active"}]


@pytest.mark.asyncio
async def test_invalidate_credential_unknown_partner_raises(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """#315 AC: an unknown partner id raises and no close-out rows appear."""
    _, partner = _facade(database_url, tmp_path)

    with pytest.raises(PartnerNotFoundError, match="no partner exists with id 999999"):
        await partner.invalidate_credential(999_999)

    assert await _query(database_url, "SELECT count(*) AS n FROM partner.partner_credentials") == [
        {"n": 0}
    ]
