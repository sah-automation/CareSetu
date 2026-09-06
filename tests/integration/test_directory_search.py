"""PHASE-6 T02a: the public provider directory search against Postgres (#313).

Exercises the ``MOD-002`` ``search_directory`` facade against a live PostgreSQL
mirroring ``test_partner_verification_queue.py`` (alembic head + raw seeding of
profiles/credentials/index rows so each partner state is a single flat insert):

- Only ``[Active]`` partners whose credentials are all verified, unexpired and
  unrevoked appear (the provider visibility rule - REQ-028 + ADR-0011, derived
  on read, never cached). Under Verification partners and partners whose
  credentials expired/revoked stay hidden even when their directory_index row
  still claims ``is_active``.
- The wider-area fallback relaxes ONLY the location constraint - type,
  specialty and free-text filters hold while ``fell_back`` labels the results
  "outside your area"; a match inside the peri-urban scope never falls back.
- Distance sort is nearest-first from the caller's geo point (the facade
  defaults to the Daltonganj centre, REQ-008).
- One ``directory.search`` analytics event per search lands in the partner
  outbox inside the same transaction, carrying filters, result count and the
  fallback flag (no Redis caching - T02b is a separate ticket).

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

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
from modules.partner.facade import (
    DALTONGANJ_LATITUDE,
    DALTONGANJ_LONGITUDE,
    DEFAULT_SERVICE_AREA_NAME,
    PartnerFacade,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

# An active partner a little outside the peri-urban scope (~95 km north on the
# Daltonganj meridian - distance from the centre exceeds PERI_URBAN_RADIUS_KM).
_FAR_LATITUDE = 24.90
_FAR_LONGITUDE = DALTONGANJ_LONGITUDE

_identity_ids = count(1001)


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


async def _seed_partner(
    database_url: str,
    *,
    partner_type: str = "doctor",
    status: str = "Active",
    practice_name: str,
    latitude: float = DALTONGANJ_LATITUDE,
    longitude: float = DALTONGANJ_LONGITUDE,
    specialty: str | None = None,
    credential_verified: bool = True,
    credential_expires_at: datetime | None = None,
    credential_revoked_at: datetime | None = None,
    indexed: bool = True,
    is_active: bool = True,
    service_area_id: int | None = None,
) -> int:
    """Seed profile + current-round credential + directory index row directly.

    A single flat insert per partner table gives the search's read-time rules
    exact states to chew on (ADR-0011 lazy read-hide: the index row may claim
    ``is_active`` while the credential is already revoked/expired - the facade
    must still hide it). ``service_area_id`` is passed through to the profile so
    tests can pin a partner's recorded service area (and its fallback when
    omitted).
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            profile = await connection.execute(
                text(
                    "INSERT INTO partner.partner_profiles "
                    "(identity_id, partner_type, status, practice_name, practice_address, "
                    " practice_latitude, practice_longitude, service_area_id) "
                    "VALUES (:identity_id, :partner_type, :status, :practice_name, "
                    " 'integration test address', :latitude, :longitude, :service_area_id) "
                    "RETURNING id"
                ),
                {
                    "identity_id": next(_identity_ids),
                    "partner_type": partner_type,
                    "status": status,
                    "practice_name": practice_name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "service_area_id": service_area_id,
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
                await connection.execute(
                    text(
                        "INSERT INTO partner.partner_directory_index "
                        "(partner_id, practice_latitude, practice_longitude, partner_type, "
                        " specialty, is_active) "
                        "VALUES (:partner_id, :latitude, :longitude, :partner_type, "
                        " :specialty, :is_active)"
                    ),
                    {
                        "partner_id": partner_id,
                        "latitude": latitude,
                        "longitude": longitude,
                        "partner_type": partner_type,
                        "specialty": specialty,
                        "is_active": is_active,
                    },
                )
            return partner_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_returns_only_active_with_valid_credentials(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """Visibility rule (REQ-028 + ADR-0011): status-free, credential-free rows stay out."""
    _, partner = _facade(database_url, tmp_path)
    await _seed_partner(
        database_url,
        practice_name="Dr. Sharma Clinic",
        specialty="General Physician",
    )
    await _seed_partner(
        database_url,
        practice_name="Dr. Pending",
        status="Under Verification",
    )
    await _seed_partner(
        database_url,
        practice_name="Dr. Lapsed",
        credential_expires_at=datetime.now(UTC) - timedelta(days=400),
    )
    await _seed_partner(
        database_url,
        practice_name="Dr. Revoked",
        credential_revoked_at=datetime.now(UTC) - timedelta(days=1),
    )
    await _seed_partner(
        database_url,
        practice_name="Dr. Unverified",
        credential_verified=False,
    )

    view = await partner.search_directory()

    names = [entry.practice_name for entry in view.items]
    assert view.fell_back is False
    assert names == ["Dr. Sharma Clinic"]
    for entry in view.items:
        assert entry.verified is True


@pytest.mark.asyncio
async def test_wider_area_fallback_relaxes_only_location(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """Fallback is location-only: filters hold, and the label tells the truth."""
    _, partner = _facade(database_url, tmp_path)
    far_id = await _seed_partner(
        database_url,
        practice_name="Dr. Far",
        latitude=_FAR_LATITUDE,
        longitude=_FAR_LONGITUDE,
        specialty="General Physician",
    )

    by_specialty = await partner.search_directory(specialty="General Physician")
    assert by_specialty.fell_back is True
    assert [e.partner_id for e in by_specialty.items] == [far_id]

    by_type = await partner.search_directory(partner_type="lab")
    assert by_type.fell_back is True
    assert by_type.items == []

    by_name = await partner.search_directory(query="No Such Practice")
    assert by_name.fell_back is True
    assert by_name.items == []

    # A nearby match kills the fallback: an in-scope result means the far row
    # is NOT served (the wider-area relaxation only fires when nothing matches
    # in scope - "outside your area" is never mixed with local listings).
    near_id = await _seed_partner(
        database_url,
        practice_name="Dr. Nearby",
        specialty="General Physician",
    )
    combined = await partner.search_directory(specialty="General Physician")
    assert combined.fell_back is False
    assert [e.partner_id for e in combined.items] == [near_id]


@pytest.mark.asyncio
async def test_search_orders_nearest_first(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """Distance sort is ascending from the caller's geo point."""
    _, partner = _facade(database_url, tmp_path)
    # Longitude offsets grow the great-circle distance from the Daltonganj centre.
    await _seed_partner(
        database_url,
        practice_name="Dr. Farther",
        longitude=DALTONGANJ_LONGITUDE + 0.070,
    )
    await _seed_partner(
        database_url,
        practice_name="Dr. Mid",
        longitude=DALTONGANJ_LONGITUDE + 0.030,
    )
    await _seed_partner(
        database_url,
        practice_name="Dr. Closest",
        longitude=DALTONGANJ_LONGITUDE + 0.008,
    )

    view = await partner.search_directory()

    assert [e.practice_name for e in view.items] == [
        "Dr. Closest",
        "Dr. Mid",
        "Dr. Farther",
    ]
    distances = [e.distance_km for e in view.items]
    assert distances == sorted(distances)


@pytest.mark.asyncio
async def test_search_composes_partner_type_specialty_and_free_text(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """Filters compose: closed type enum, doctors-only specialty, ILIKE name."""
    _, partner = _facade(database_url, tmp_path)
    await _seed_partner(
        database_url,
        practice_name="Sharma Clinic and Sons",
        specialty="General Physician",
    )
    await _seed_partner(
        database_url,
        practice_name="Mehta Children's Clinic",
        specialty="Pediatrician",
    )
    await _seed_partner(database_url, practice_name="MedPlus Lab", partner_type="lab")

    doctors = await partner.search_directory(partner_type="doctor")
    assert {e.practice_name for e in doctors.items} == {
        "Sharma Clinic and Sons",
        "Mehta Children's Clinic",
    }

    pediatricians = await partner.search_directory(specialty="Pediatrician")
    assert [e.practice_name for e in pediatricians.items] == ["Mehta Children's Clinic"]

    # Specialty pins the type: a lab row never carries one, so a lab + specialty
    # request matches nothing rather than silently dropping the specialty.
    lab_specialty = await partner.search_directory(partner_type="lab", specialty="Pediatrician")
    assert lab_specialty.items == []

    by_name = await partner.search_directory(query="medplus")
    assert [e.practice_name for e in by_name.items] == ["MedPlus Lab"]

    composed = await partner.search_directory(query="mehta", partner_type="doctor")
    assert [e.practice_name for e in composed.items] == ["Mehta Children's Clinic"]


@pytest.mark.asyncio
async def test_search_emits_directory_search_event_once_per_search(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """One ``directory.search`` analytics row per search, in the same transaction."""
    _, partner = _facade(database_url, tmp_path)
    await _seed_partner(database_url, practice_name="Dr. Sharma Clinic")

    await partner.search_directory(query="sharma")
    rows = await _query(
        database_url,
        "SELECT event_type, payload FROM partner.partner_outbox "
        "WHERE event_type = 'directory.search'",
    )
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["query"] == "sharma"
    assert payload["result_count"] == 1
    assert payload["fell_back"] is False

    await partner.search_directory(query="no such clinic")
    # Outbox ids are random UUIDs (gen_random_uuid), never an insert-order
    # sequence: group by the event payload instead of row position.
    rows = await _query(
        database_url,
        "SELECT event_type, payload FROM partner.partner_outbox "
        "WHERE event_type = 'directory.search'",
    )
    by_flag = {row["payload"]["fell_back"]: row["payload"] for row in rows}
    assert len(by_flag) == 2
    assert by_flag[False]["query"] == "sharma"
    assert by_flag[False]["result_count"] == 1
    assert by_flag[True]["query"] == "no such clinic"
    assert by_flag[True]["result_count"] == 0


@pytest.mark.asyncio
async def test_select_emits_partner_selected_once_per_pick(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """One ``partner.selected`` analytics row per pick - anonymous, pick-only facts.

    The public ingest path (PHASE-6 T4 #326) writes into the same partner
    outbox the search event uses: each facade call produces exactly one row
    carrying only the pick facts. No patient id or actor ever lands - the
    route is unauthenticated, so the payload stays anonymous by construction.
    """
    _, partner = _facade(database_url, tmp_path)

    await partner.record_partner_selected(
        partner_id=42, partner_type="doctor", source="search-card"
    )

    rows = await _query(
        database_url,
        "SELECT event_type, payload FROM partner.partner_outbox "
        "WHERE event_type = 'partner.selected'",
    )
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["partner_id"] == 42
    assert payload["partner_type"] == "doctor"
    assert payload["source"] == "search-card"
    assert "patient_id" not in payload
    assert "actor" not in payload

    await partner.record_partner_selected(partner_id=43, partner_type="lab", source=None)

    rows = await _query(
        database_url,
        "SELECT event_type, payload FROM partner.partner_outbox "
        "WHERE event_type = 'partner.selected'",
    )
    assert len(rows) == 2
    by_partner = {row["payload"]["partner_id"]: row["payload"] for row in rows}
    assert by_partner[42]["source"] == "search-card"
    assert by_partner[43]["source"] is None


@pytest.mark.asyncio
async def test_search_caps_in_scope_results_at_directory_max_results(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """#324: a >50-match in-scope search returns at most top-50, still nearest-first."""
    _, partner = _facade(database_url, tmp_path)
    # 12 distinct longitude offsets * 6 partners each = 72 partners, all within
    # the peri-urban scope (longitude offset <= ~18 km < PERI_URBAN_RADIUS_KM).
    offsets = [0.001 + 0.015 * i for i in range(12)]
    expected_count = 50
    for index, offset in enumerate(offsets):
        for _ in range(6):
            await _seed_partner(
                database_url,
                practice_name=f"Dr. Offset {offset:.3f} #{index}",
                longitude=DALTONGANJ_LONGITUDE + offset,
            )

    view = await partner.search_directory()

    assert view.fell_back is False
    assert len(view.items) == expected_count
    distances = [entry.distance_km for entry in view.items]
    assert distances == sorted(distances)
    # The nearest 50 of 72 are returned; the furthest are excluded.
    assert all(entry.distance_km <= distances[expected_count - 1] for entry in view.items)


@pytest.mark.asyncio
async def test_search_caps_fallback_results_at_directory_max_results(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """#324: the wider-area fallback path is also bounded at the top-N."""
    _, partner = _facade(database_url, tmp_path)
    # All partners sit beyond the peri-urban scope (~50 km east) so every search
    # falls back; the relaxed run must still cap at the top-50 nearest.
    for index in range(72):
        await _seed_partner(
            database_url,
            practice_name=f"Dr. Far #{index}",
            longitude=DALTONGANJ_LONGITUDE + 0.50 + 0.005 * index,
        )

    view = await partner.search_directory()

    assert view.fell_back is True
    assert len(view.items) == 50
    distances = [entry.distance_km for entry in view.items]
    assert distances == sorted(distances)


@pytest.mark.asyncio
async def test_search_maps_area_from_recorded_service_area_with_fallback(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """The area on each entry comes from the recorded service area, exactly like
    ``get_provider_profile``: a partner with no ``service_area_id`` falls back to
    Daltonganj, never invented. Distance ordering is unaffected by the join."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO partner.partner_service_areas (id, name) "
                    "VALUES (2, 'Hutar') ON CONFLICT (name) DO NOTHING"
                )
            )
    finally:
        await engine.dispose()

    _, partner = _facade(database_url, tmp_path)
    await _seed_partner(
        database_url,
        practice_name="Dr. Hutar Clinic",
        longitude=DALTONGANJ_LONGITUDE + 0.008,
        service_area_id=2,
    )
    await _seed_partner(
        database_url,
        practice_name="Dr. No Area",
        longitude=DALTONGANJ_LONGITUDE + 0.030,
    )

    view = await partner.search_directory()

    name_to_area = {entry.practice_name: entry.area for entry in view.items}
    assert name_to_area["Dr. Hutar Clinic"] == "Hutar"
    assert name_to_area["Dr. No Area"] == DEFAULT_SERVICE_AREA_NAME
    distances = [entry.distance_km for entry in view.items]
    assert distances == sorted(distances)
