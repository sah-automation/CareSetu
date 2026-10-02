"""

Trace: FEAT-004 (Provider Directory and Search).
#607: the shared directory-entry refresh against Postgres.

The directory entry is the read-side row search and the public profile read, and
this ticket gives it a second writer: the doctor's own address save joins the
operator approval path, so a doctor can move their listing. The property that
makes that safe is a NEGATIVE one, and a negative property is only worth
anything if it is pinned where the data actually lives - so this suite asserts
it on real rows, where the sibling unit assertion on the compiled SQL cannot
reach:

- A refresh moves the position and publishes the profile's specialty selection
  on the entry that is already there: one row per partner (ADR-0012), refreshed
  rather than duplicated.
- A refresh cannot RE-LIST a deindexed doctor and cannot touch their credential
  validity. Both are the reason the operation takes no values at all - the
  listed flag is one of the four AND-ed clauses of ``provider_visible`` and the
  ``verified`` stamp is round-scoped, so a doctor-triggered call must be unable
  to reach either. Note the same refresh DOES move the position: the
  non-interference is selective, not a no-op.
- A refresh cannot verify a credential or list a partner the operator has never
  approved - not even by materialising an entry row for them.

Every partner here is built through the real Phase-5 flow (register, submit
credentials, operator approve - the activation seam #456), so the entry row
always comes from the real writer. Only the profile's declared address fields
are seeded directly, because the address write that will own them (#609) does not
exist yet; see :func:`_declare_practice_address`.

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from conftest import seed_daltonganj_service_area
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from test_directory_search import _activate_partner, _pending_partner

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.credential_validity import refresh_directory_entry
from modules.partner.facade import DALTONGANJ_LATITUDE, DALTONGANJ_LONGITUDE, PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

#: A corrected PIN resolves somewhere else entirely (ADR-0022's replacement for
#: the sign-up fallback coordinate), far enough that a stale entry cannot pass
#: for a moved one.
_MOVED_LATITUDE = DALTONGANJ_LATITUDE + 0.4
_MOVED_LONGITUDE = DALTONGANJ_LONGITUDE + 0.4
_MOVED_LOCALITY = "Hirapur"
_MOVED_CITY = "Daltonganj"
_MOVED_PIN = "827001"
_MOVED_SPECIALTIES = ("Pediatrician", "General Physician")


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration(database_url: str) -> Iterator[None]:
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture(autouse=True)
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


def _facade(database_url: str, tmp_path: Path) -> PartnerFacade:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))
    return PartnerFacade(engine=engine, iam_facade=iam, artifact_store=store)


async def _query(database_url: str, sql: str, **params: Any) -> list[dict[str, Any]]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql), params)
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


async def _execute(database_url: str, sql: str, params: dict[str, Any]) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql), params)
    finally:
        await engine.dispose()


async def _declare_practice_address(
    database_url: str,
    partner_id: int,
    *,
    latitude: float,
    longitude: float,
    locality: str,
    city: str,
    pin: str,
    specialties: Sequence[str],
) -> None:
    """Write the profile's declared address fields, the way #609's address save will.

    The structured address parts and the derived position live on the profile
    row, and #609 is the ticket that writes them through the facade - the
    operation under test here takes no values and reads them back, so seeding
    them directly is standing in for that write, nothing more. The directory
    entry itself is never hand-built: it always comes from the real operator
    approval path, which is the only writer of the row's existence.
    """
    await _execute(
        database_url,
        "UPDATE partner.partner_profiles SET practice_latitude = :latitude, "
        "practice_longitude = :longitude, address_line = :address_line, "
        "address_locality = :locality, address_city = :city, address_pin = :pin, "
        "specialties = CAST(:specialties AS jsonb) WHERE id = :partner_id",
        {
            "partner_id": partner_id,
            "latitude": latitude,
            "longitude": longitude,
            "address_line": "12, Station Road",
            "locality": locality,
            "city": city,
            "pin": pin,
            "specialties": json.dumps(list(specialties)),
        },
    )


async def _refresh(database_url: str, partner_id: int) -> None:
    """Call the shared refresh on a real connection, as its two callers do.

    In production the address save calls this inside the transaction that wrote
    the profile; the operator approval path calls it from inside
    ``activate_partner``. Here it gets a transaction of its own, which is the
    loosest form the contract allows - the operation must not need a caller's
    transaction to be correct, only to be atomic with it.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await refresh_directory_entry(connection, partner_id)
    finally:
        await engine.dispose()


async def _entry(database_url: str, partner_id: int) -> list[dict[str, Any]]:
    return await _query(
        database_url,
        "SELECT partner_id, practice_latitude, practice_longitude, partner_type, "
        "specialty, is_active FROM partner.partner_directory_index "
        "WHERE partner_id = :partner_id",
        partner_id=partner_id,
    )


async def _credential_flags(database_url: str, partner_id: int) -> list[tuple[bool, bool]]:
    rows = await _query(
        database_url,
        "SELECT verified, revoked_at IS NOT NULL AS revoked FROM partner.partner_credentials "
        "WHERE profile_id = :partner_id ORDER BY id",
        partner_id=partner_id,
    )
    return [(bool(row["verified"]), bool(row["revoked"])) for row in rows]


@pytest.mark.asyncio
async def test_refresh_updates_the_existing_entry_rather_than_inserting_a_second(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """A doctor who already has a directory row gets it refreshed, not duplicated.

    The conflict target is ``partner_id``, so this is the path that gives a
    doctor indexed before this writer existed the specialties on their entry -
    the insert path can never run for them again.
    """
    partner = _facade(database_url, tmp_path)
    partner_id = await _activate_partner(database_url, partner, practice_name="Dr. Sharma")
    before = await _entry(database_url, partner_id)
    assert len(before) == 1
    # The entry mirrors the profile's declared selection, and this doctor has
    # declared none - which is the state every pre-#607 entry sat in, with its
    # specialties permanently NULL.
    assert before[0]["specialty"] == []

    await _declare_practice_address(
        database_url,
        partner_id,
        latitude=_MOVED_LATITUDE,
        longitude=_MOVED_LONGITUDE,
        locality=_MOVED_LOCALITY,
        city=_MOVED_CITY,
        pin=_MOVED_PIN,
        specialties=_MOVED_SPECIALTIES,
    )
    await _refresh(database_url, partner_id)

    after = await _entry(database_url, partner_id)
    assert len(after) == 1
    assert float(after[0]["practice_latitude"]) == pytest.approx(_MOVED_LATITUDE)
    assert float(after[0]["practice_longitude"]) == pytest.approx(_MOVED_LONGITUDE)
    assert after[0]["specialty"] == list(_MOVED_SPECIALTIES)
    assert after[0]["partner_type"] == "doctor"
    assert after[0]["is_active"] is True


@pytest.mark.asyncio
async def test_refresh_cannot_re_list_a_deindexed_doctor_or_touch_their_credentials(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """The trust property, on real rows (#607 AC 2 and AC 4).

    The doctor's credentials are invalidated through the real close-out, so the
    entry is deindexed and the round's credential is revoked. The refresh then
    runs exactly as the doctor's own address save runs it. It must move the
    position - that is the whole feature - and leave the listed flag false and
    the credential row exactly as the close-out left it. A refresh that could
    re-list a doctor, or vouch for their credentials, would let a profile edit
    stand in for an operator decision (ADR-0008).
    """
    partner = _facade(database_url, tmp_path)
    partner_id = await _activate_partner(database_url, partner, practice_name="Dr. Revoked")
    await partner.invalidate_credential(partner_id, revoked_by=uuid4())
    deindexed = await _entry(database_url, partner_id)
    assert deindexed[0]["is_active"] is False
    credentials_before = await _credential_flags(database_url, partner_id)
    assert credentials_before == [(True, True)]

    await _declare_practice_address(
        database_url,
        partner_id,
        latitude=_MOVED_LATITUDE,
        longitude=_MOVED_LONGITUDE,
        locality=_MOVED_LOCALITY,
        city=_MOVED_CITY,
        pin=_MOVED_PIN,
        specialties=_MOVED_SPECIALTIES,
    )
    await _refresh(database_url, partner_id)

    after = await _entry(database_url, partner_id)
    assert len(after) == 1
    # Moved: the refresh is not a no-op, so the assertions below mean something.
    assert float(after[0]["practice_latitude"]) == pytest.approx(_MOVED_LATITUDE)
    assert after[0]["specialty"] == list(_MOVED_SPECIALTIES)
    # Untouched: the listed flag the operation cannot write, and the credential
    # validity the operation cannot read.
    assert after[0]["is_active"] is False
    assert await _credential_flags(database_url, partner_id) == credentials_before
    view = await partner.search_directory()
    assert [entry.partner_id for entry in view.items] == []


@pytest.mark.asyncio
async def test_refresh_cannot_verify_a_credential_or_list_an_unapproved_partner(
    database_url: str, clean_partner: Any, tmp_path: Path
) -> None:
    """A profile save is not a verification round, and not an approval.

    The partner is registered and has submitted credentials, but no operator has
    decided anything: the round is unverified and the profile is not ``Active``.
    The refresh runs exactly as the doctor's own address save runs it, and it
    must not verify a credential (an operator-only act, and the ``verified``
    indicator's own half). Nor may it bring an entry row into existence at all -
    the write is scoped to a partner the recorded status says is ``[Active]``,
    which is the clause ``provider_visible`` ANDs with the listed flag, so there
    is no row for this doctor to be listed by and the partner is unsearchable
    however they have filled in their profile.
    """
    partner = _facade(database_url, tmp_path)
    partner_id = await _pending_partner(partner, practice_name="Dr. Pending")
    assert await _credential_flags(database_url, partner_id) == [(False, False)]
    assert await _entry(database_url, partner_id) == []

    await _declare_practice_address(
        database_url,
        partner_id,
        latitude=_MOVED_LATITUDE,
        longitude=_MOVED_LONGITUDE,
        locality=_MOVED_LOCALITY,
        city=_MOVED_CITY,
        pin=_MOVED_PIN,
        specialties=_MOVED_SPECIALTIES,
    )
    await _refresh(database_url, partner_id)

    # Still no approved-round credential, and still no entry row to be listed by.
    assert await _credential_flags(database_url, partner_id) == [(False, False)]
    assert await _entry(database_url, partner_id) == []
    view = await partner.search_directory()
    assert [entry.partner_id for entry in view.items] == []
