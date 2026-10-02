"""

Trace: FEAT-005 (Provider Profiles and Credential Display).
PHASE-6 T03: the public provider profile against Postgres (#309, widened #613).

Exercises the ``MOD-002`` ``get_provider_profile`` facade against a live
PostgreSQL mirroring ``test_directory_search.py`` (alembic head + raw seeding
of profiles/credentials/index rows):

- Only ``[Active]`` partners with a ``directory_index`` entry AND all valid
  (verified, unexpired, unrevoked) credentials resolve a profile.
- Not ``[Active]`` partners, partners with no index row, no credentials, or
  any expired/revoked/unverified credential raise
  ``ProviderProfileNotFoundError`` - the 404 that keeps a hidden partner's
  identity private (never a "hidden" 200).
- The payload carries two bands. The **credential** band the platform checked:
  practice name, partner type, the ``verified`` indicator and per-credential type
  + status label + expiry. The **declared** band the doctor wrote since #613:
  clinic name, the specialty SELECTION and the singular label taken from it,
  languages, consulting days, consulting hours, about text, years of experience,
  the structured address parts and the ``area`` label - all read off the profile
  row, so they reflect the doctor's last save rather than a directory-entry copy
  of it, and ``area`` is the declared locality the search card already reads
  rather than the service-area vocabulary (#612).
- The widening leaks nothing: a fully-declared partner resolves a payload with
  no photo ref, no artifact refs, no coordinates, no notification preferences
  and no registration-era display address in it, and a HIDDEN partner's declared
  text never appears in the error either.
- The ``verified`` indicator always agrees with search visibility: a partner
  whose profile resolves is exactly one whose card appears in search - and the
  declared band does not reach it.

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from itertools import count
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
from modules.partner.domain.exceptions import ProviderProfileNotFoundError
from modules.partner.facade import (
    DALTONGANJ_LATITUDE,
    DALTONGANJ_LONGITUDE,
    PartnerFacade,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_identity_ids = count(2001)


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


def _facade(database_url: str, tmp_path: Path) -> tuple[IamFacade, PartnerFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))
    partner = PartnerFacade(engine=engine, iam_facade=iam, artifact_store=store)
    return iam, partner


async def _seed_partner(
    database_url: str,
    *,
    partner_type: str = "doctor",
    status: str = "Active",
    practice_name: str,
    specialty: str | None = None,
    credential_verified: bool = True,
    credential_expires_at: datetime | None = None,
    credential_revoked_at: datetime | None = None,
    indexed: bool = True,
    is_active: bool = True,
    service_area_id: int | None = 1,
    specialties: list[str] | None = None,
    clinic_name: str | None = None,
    languages: list[str] | None = None,
    consulting_days: list[str] | None = None,
    consulting_hours: str | None = None,
    about: str | None = None,
    experience_years: int | None = None,
    address_line: str | None = None,
    address_landmark: str | None = None,
    address_locality: str | None = None,
    address_city: str | None = None,
    address_pin: str | None = None,
    photo_ref: str | None = None,
    notification_preferences: dict[str, bool] | None = None,
    availability: str | None = None,
) -> int:
    """Seed profile + credential + optional directory index row directly.

    ``service_area_id`` is kept as a knob because it is exactly the recorded
    value the public read must IGNORE: it defaults to 1 (the seeded Daltonganj
    row) so a profile carrying a declared locality still has a recorded area to
    disagree with.

    The keyword arguments after ``service_area_id`` write the columns the four
    section writes own (#608/#609/#610), so the widened payload can be asserted
    against a real row rather than a mock. ``specialty`` seeds the DIRECTORY
    ENTRY's copy and ``specialties`` the PROFILE ROW's selection - two columns,
    kept separate here on purpose, because the entry only receives a copy from
    the shared refresh (#607) and the profile row is the source of truth the
    public read uses.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            profile = await connection.execute(
                text(
                    "INSERT INTO partner.partner_profiles "
                    "(identity_id, partner_type, status, practice_name, practice_address, "
                    " practice_latitude, practice_longitude, service_area_id, "
                    " clinic_name, specialties, languages, consulting_days, "
                    " consulting_hours, about, experience_years, address_line, "
                    " address_landmark, address_locality, address_city, address_pin, "
                    " photo_ref, notification_preferences, availability) "
                    "VALUES (:identity_id, :partner_type, :status, :practice_name, "
                    " 'integration test address', :latitude, :longitude, :service_area_id, "
                    " :clinic_name, CAST(:specialties AS jsonb), CAST(:languages AS jsonb), "
                    " CAST(:consulting_days AS jsonb), :consulting_hours, :about, "
                    " :experience_years, :address_line, :address_landmark, "
                    " :address_locality, :address_city, :address_pin, :photo_ref, "
                    " CAST(:notification_preferences AS jsonb), :availability) "
                    "RETURNING id"
                ),
                {
                    "identity_id": next(_identity_ids),
                    "partner_type": partner_type,
                    "status": status,
                    "practice_name": practice_name,
                    "latitude": DALTONGANJ_LATITUDE,
                    "longitude": DALTONGANJ_LONGITUDE,
                    "service_area_id": service_area_id,
                    "clinic_name": clinic_name,
                    "specialties": json.dumps(specialties or []),
                    "languages": json.dumps(languages or []),
                    "consulting_days": json.dumps(consulting_days or []),
                    "consulting_hours": consulting_hours,
                    "about": about,
                    "experience_years": experience_years,
                    "address_line": address_line,
                    "address_landmark": address_landmark,
                    "address_locality": address_locality,
                    "address_city": address_city,
                    "address_pin": address_pin,
                    "photo_ref": photo_ref,
                    "notification_preferences": json.dumps(notification_preferences or {}),
                    "availability": availability,
                },
            )
            partner_id = int(profile.scalar_one())
            await connection.execute(
                text(
                    "INSERT INTO partner.partner_credentials "
                    "(profile_id, credential_type, verified, expires_at, revoked_at) "
                    "VALUES (:profile_id, 'medical_registration', :verified, "
                    " :expires_at, :revoked_at)"
                ),
                {
                    "profile_id": partner_id,
                    "verified": credential_verified,
                    "expires_at": credential_expires_at,
                    "revoked_at": credential_revoked_at,
                },
            )
            if indexed:
                # The specialty column is a multi-valued JSONB selection since
                # #606, so a single seeded value is written as a one-member array
                # - the pre-#606 meaning, preserved. NULL stays NULL: that is how
                # a directory entry still says "carries no specialty", which is
                # what the lab/chemist rows below rely on.
                await connection.execute(
                    text(
                        "INSERT INTO partner.partner_directory_index "
                        "(partner_id, practice_latitude, practice_longitude, partner_type, "
                        " specialty, is_active) "
                        "VALUES (:partner_id, :latitude, :longitude, :partner_type, "
                        " CAST(:specialty AS jsonb), :is_active)"
                    ),
                    {
                        "partner_id": partner_id,
                        "latitude": DALTONGANJ_LATITUDE,
                        "longitude": DALTONGANJ_LONGITUDE,
                        "partner_type": partner_type,
                        "specialty": (None if specialty is None else json.dumps([specialty])),
                        "is_active": is_active,
                    },
                )
            return partner_id
    finally:
        await engine.dispose()


async def _raises_not_found(awaitable: Any) -> bool:
    try:
        await awaitable
    except ProviderProfileNotFoundError:
        return True
    return False


@pytest.mark.asyncio
async def test_profile_resolves_active_partner_with_safe_fields(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """An [Active] indexed partner with valid credentials resolves a profile."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _seed_partner(
        database_url,
        practice_name="Dr. Sharma Clinic",
        specialties=["General Physician"],
    )

    view = await partner.get_provider_profile(partner_id)

    assert view.partner_id == partner_id
    assert view.practice_name == "Dr. Sharma Clinic"
    assert view.partner_type == "doctor"
    # The singular label is the first member of the declared selection (#613).
    assert view.specialty == "General Physician"
    assert view.verified is True
    assert len(view.credentials) == 1
    credential = view.credentials[0]
    assert credential.credential_type == "medical_registration"
    assert credential.status == "verified"


@pytest.mark.asyncio
async def test_profile_omits_a_pending_credential_row_while_staying_visible(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """#623 (B3): a pending re-verification round is neither listed nor de-listing.

    The row the read previously published for a partner mid-round was labelled
    ``verified`` unconditionally, because the mapper emitted the literal string
    rather than reading the column - and the trust cue that label carries is the
    whole reason the band exists. Meanwhile the reachability gate scopes
    ``has_invalid_credential`` to ``verified IS TRUE``, which is deliberate: a
    partner whose renewal is in flight stays [Active] instead of vanishing from
    search (ADR-0011's grace window). So a pending row can be reached, and it
    used to be published as though it were settled.

    Two halves, and the second is the one that makes the first safe. Omitting the
    pending row is only correct because the partner is still reachable at all -
    filtering it out of the LIST must not start hiding the PROFILE.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _seed_partner(
        database_url, practice_name="Dr. Renewing", specialties=["General Physician"]
    )

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO partner.partner_credentials "
                    "(profile_id, credential_type, verified, expires_at, revoked_at) "
                    "VALUES (:profile_id, 'qualification_certificate', FALSE, NULL, NULL)"
                ),
                {"profile_id": partner_id},
            )
    finally:
        await engine.dispose()

    view = await partner.get_provider_profile(partner_id)

    # Still reachable: the pending row did not de-list them.
    assert view.partner_id == partner_id
    # The approved row is published, and only it - one row, not two.
    assert [c.credential_type for c in view.credentials] == ["medical_registration"]
    assert all(c.status == "verified" for c in view.credentials)


@pytest.mark.asyncio
async def test_profile_carries_the_declared_fields_off_the_profile_row(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """#613: a completed profile surfaces every declared field, field by field.

    Seeded on the PROFILE ROW - the column each section write lands on - which is
    what the read projects. Asserted field by field rather than as a dict
    comparison so a renamed or dropped field names itself instead of hiding
    inside a mismatch.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _seed_partner(
        database_url,
        practice_name="Dr. Asha Verma",
        specialty="General Physician",
        specialties=["General Physician", "Pediatrician"],
        clinic_name="Shanti Clinic",
        languages=["Hindi", "English"],
        consulting_days=["Monday", "Tuesday", "Saturday"],
        consulting_hours="Mon-Sat, 9am-1pm",
        about="Twenty years of neighbourhood practice, children first.",
        experience_years=20,
        address_line="12, Nehru Road",
        address_landmark="Near the water tank",
        address_locality="Sadar",
        address_city="Daltonganj",
        address_pin="827101",
    )

    view = await partner.get_provider_profile(partner_id)

    assert view.clinic_name == "Shanti Clinic"
    # The declared SELECTION, multi-valued: the representative ``specialty`` the
    # narrow surfaces render stays, and this is the whole thing behind it.
    assert view.specialties == ["General Physician", "Pediatrician"]
    assert view.languages == ["Hindi", "English"]
    assert view.consulting_days == ["Monday", "Tuesday", "Saturday"]
    assert view.consulting_hours == "Mon-Sat, 9am-1pm"
    assert view.about == "Twenty years of neighbourhood practice, children first."
    assert view.experience_years == 20
    assert view.address_line == "12, Nehru Road"
    assert view.landmark == "Near the water tank"
    assert view.locality == "Sadar"
    assert view.city == "Daltonganj"
    assert view.pin_code == "827101"
    # AC 4: the widening reached the payload and NOT the indicator.
    assert view.verified is True


@pytest.mark.asyncio
async def test_profile_reads_an_undeclared_band_as_nulls_and_empty_lists(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """A doctor who has declared nothing still resolves, with empties not nulls."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _seed_partner(
        database_url,
        practice_name="Dr. Bare",
        specialty="General Physician",
    )

    view = await partner.get_provider_profile(partner_id)

    assert view.clinic_name is None
    assert view.specialties == []
    assert view.languages == []
    assert view.consulting_days == []
    assert view.consulting_hours is None
    assert view.about is None
    assert view.experience_years is None
    assert view.address_line is None
    assert view.landmark is None
    assert view.locality is None
    assert view.city is None
    assert view.pin_code is None


@pytest.mark.asyncio
async def test_profile_hides_every_non_visible_partner(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """Not-[Active], unindexed, unverified, expired and revoked partners 404."""
    _, partner = _facade(database_url, tmp_path)
    pending_id = await _seed_partner(
        database_url, practice_name="Dr. Pending", status="Under Verification"
    )
    unindexed_id = await _seed_partner(database_url, practice_name="Dr. Unindexed", indexed=False)
    unverified_id = await _seed_partner(
        database_url, practice_name="Dr. Unverified", credential_verified=False
    )
    expired_id = await _seed_partner(
        database_url,
        practice_name="Dr. Lapsed",
        credential_expires_at=datetime.now(UTC) - timedelta(days=400),
    )
    revoked_id = await _seed_partner(
        database_url,
        practice_name="Dr. Revoked",
        credential_revoked_at=datetime.now(UTC) - timedelta(days=1),
    )

    for partner_id in (pending_id, unindexed_id, unverified_id, expired_id, revoked_id):
        assert await _raises_not_found(partner.get_provider_profile(partner_id))


@pytest.mark.asyncio
async def test_profile_hides_partner_without_any_credential(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """An [Active] indexed partner with no credential rows resolves nothing."""
    _, partner = _facade(database_url, tmp_path)
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            profile = await connection.execute(
                text(
                    "INSERT INTO partner.partner_profiles "
                    "(identity_id, partner_type, status, practice_name, practice_address, "
                    " practice_latitude, practice_longitude) "
                    "VALUES (:identity_id, 'doctor', 'Active', 'Dr. No Creds', "
                    " 'integration test address', :latitude, :longitude) RETURNING id"
                ),
                {
                    "identity_id": next(_identity_ids),
                    "latitude": DALTONGANJ_LATITUDE,
                    "longitude": DALTONGANJ_LONGITUDE,
                },
            )
            partner_id = int(profile.scalar_one())
            await connection.execute(
                text(
                    "INSERT INTO partner.partner_directory_index "
                    "(partner_id, practice_latitude, practice_longitude, partner_type, "
                    " specialty, is_active) "
                    "VALUES (:partner_id, :latitude, :longitude, 'doctor', NULL, true)"
                ),
                {
                    "partner_id": partner_id,
                    "latitude": DALTONGANJ_LATITUDE,
                    "longitude": DALTONGANJ_LONGITUDE,
                },
            )
    finally:
        await engine.dispose()

    assert await _raises_not_found(partner.get_provider_profile(partner_id))


@pytest.mark.asyncio
async def test_profile_area_reads_the_declared_locality_not_the_service_area(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """#613 closes what #612 left: the profile's area is the DECLARED locality.

    #612 moved the search card onto ``address_locality`` and named this read as
    the half it did not touch, so a patient comparing the card with the profile
    behind it was reading two different places. This pins that the two now agree
    by giving the row a RECORDED service area (the seeded Daltonganj row) and a
    DIFFERENT declared locality - "declared wins over recorded" is therefore a
    real distinction and not the launch default read twice. The second profile
    pins the other half: an undeclared locality is ``None``, not a substituted
    vocabulary row name.
    """
    _, partner = _facade(database_url, tmp_path)
    declared = await _seed_partner(
        database_url,
        practice_name="Dr. Sadar Practice",
        service_area_id=1,
        address_locality="Medininagar",
    )
    undeclared = await _seed_partner(
        database_url,
        practice_name="Dr. Nowhere Practice",
        service_area_id=None,
    )

    assert (await partner.get_provider_profile(declared)).area == "Medininagar"
    assert (await partner.get_provider_profile(undeclared)).area is None
    assert (await partner.get_provider_profile(declared)).verified is True


@pytest.mark.asyncio
async def test_profile_specialty_doctors_only_lab_is_none(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """Specialty belongs to the doctor, and the lab's is absent because a lab has none.

    #623: this used to seed only the lab and assert an empty list, which passed for
    any seed - including a broken projection that dropped every specialty, or one
    that read the column off the wrong row. A claim about a DISTINCTION needs both
    sides of it, so a doctor carrying a specialty is seeded alongside and asserted
    to keep it. The lab's empty list is now meaningful: it is empty while a
    specialty exists in the same database.
    """
    _, partner = _facade(database_url, tmp_path)
    doctor_id = await _seed_partner(
        database_url,
        partner_type="doctor",
        practice_name="Dr. Specialised",
        # `specialties`, not `specialty`: the first seeds the DIRECTORY ENTRY's
        # copy, and the public profile reads the PROFILE ROW's selection (#613
        # moved the declared band onto the profile row). Seeding the entry alone
        # left the profile's own selection empty - the same empty seed this test
        # was written to stop relying on.
        specialties=["General Physician"],
    )
    lab_id = await _seed_partner(
        database_url,
        partner_type="lab",
        practice_name="MedPlus Lab",
    )

    doctor_view = await partner.get_provider_profile(doctor_id)
    assert doctor_view.partner_type == "doctor"
    assert doctor_view.specialty == "General Physician"
    assert doctor_view.specialties == ["General Physician"]

    lab_view = await partner.get_provider_profile(lab_id)
    assert lab_view.partner_type == "lab"
    assert lab_view.specialty is None
    assert lab_view.specialties == []
    assert lab_view.verified is True


@pytest.mark.asyncio
async def test_profile_verified_agrees_with_search_visibility(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """A resolvable profile is exactly a card that appears in search (ADR-0011)."""
    _, partner = _facade(database_url, tmp_path)
    visible_id = await _seed_partner(
        database_url, practice_name="Dr. Visible", specialty="General Physician"
    )
    expired_id = await _seed_partner(
        database_url,
        practice_name="Dr. Expired",
        credential_expires_at=datetime.now(UTC) - timedelta(days=10),
    )

    view = await partner.search_directory()
    visible_ids = {entry.partner_id for entry in view.items}
    assert visible_id in visible_ids
    assert expired_id not in visible_ids

    assert await _raises_not_found(partner.get_provider_profile(expired_id))
    profile = await partner.get_provider_profile(visible_id)
    assert profile.verified is True


@pytest.mark.asyncio
async def test_widened_profile_leaks_nothing_outside_its_two_bands(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """A completed profile still serializes nothing but the bands it declares.

    The row is seeded with a photo ref, a credential artifact ref, notification
    preferences, the inert pre-#610 ``availability`` blob and the
    registration-era display address - every one of them a real column - and the
    serialized response is scanned for all of them. A whole-body substring scan
    rather than a key allowlist, so a field renamed into one of these fails here
    instead of quietly widening the disclosure.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _seed_partner(
        database_url,
        practice_name="Dr. Asha Verma",
        specialty="General Physician",
        specialties=["General Physician"],
        clinic_name="Shanti Clinic",
        languages=["Hindi"],
        consulting_days=["Monday"],
        consulting_hours="Mon-Sat, 9am-1pm",
        about="Twenty years of neighbourhood practice.",
        experience_years=20,
        address_line="12, Nehru Road",
        address_locality="Sadar",
        address_city="Daltonganj",
        address_pin="827101",
        photo_ref="doctor/9f1c/portrait.jpg",
        notification_preferences={"new_consultations": True, "sms": True},
        availability="Retired hand-typed blob",
    )
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE partner.partner_credentials "
                    "SET artifact_refs = CAST(:refs AS jsonb) WHERE profile_id = :profile_id"
                ),
                {
                    "refs": json.dumps({"registration_certificate": "partner/9f1c/reg.pdf"}),
                    "profile_id": partner_id,
                },
            )
    finally:
        await engine.dispose()

    view = await partner.get_provider_profile(partner_id)
    raw = json.dumps(view.model_dump(mode="json"))

    for forbidden in (
        "artifact",
        "photo_ref",
        "9f1c",
        "identity_id",
        "email",
        "phone",
        "notification_preferences",
        "new_consultations",
        "practice_address",
        "integration test address",
        "practice_latitude",
        "practice_longitude",
        "revoked_at",
        "availability",
        "Retired hand-typed blob",
    ):
        assert forbidden.lower() not in raw.lower(), forbidden
    # The declared band IS present, so the scan above is a real pass rather than
    # a projection that quietly dropped everything it was meant to carry.
    assert view.clinic_name == "Shanti Clinic"
    assert view.pin_code == "827101"


@pytest.mark.asyncio
async def test_a_hidden_partners_declared_fields_never_reach_the_caller(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """The widening must not open a second door for a partner search already hides.

    A fully-declared doctor whose credential lapsed answers the same
    ``ProviderProfileNotFoundError`` every other hidden shape answers, and the
    error carries none of what the profile read now returns. That 404 is the
    privacy posture, not a detail of it: a hidden partner has to be
    indistinguishable from one who never existed, so no declared text may ride
    out on the error instead.
    """
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _seed_partner(
        database_url,
        practice_name="Dr. Lapsed",
        specialty="General Physician",
        specialties=["General Physician"],
        clinic_name="Confidential Clinic",
        languages=["Hindi"],
        consulting_days=["Monday"],
        consulting_hours="Confidential hours",
        about="Confidential about text.",
        experience_years=41,
        address_line="Confidential Road",
        address_locality="Confidential",
        address_city="Confidential",
        address_pin="827101",
        credential_expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    with pytest.raises(ProviderProfileNotFoundError) as excinfo:
        await partner.get_provider_profile(partner_id)

    assert excinfo.value.partner_id == partner_id
    # Distinctive TEXT markers only. The partner id is the one thing the error is
    # entitled to carry, and it is a bare counter, so pinning a numeric field
    # here would collide with it and make this a flaky assertion about the wrong
    # thing.
    error_text = f"{excinfo.value} {excinfo.value.__dict__}".lower()
    for leaked in ("confidential", "shanti", "827101", "pediatrician"):
        assert leaked.lower() not in error_text, leaked
