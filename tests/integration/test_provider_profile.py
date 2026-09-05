"""PHASE-6 T03: the public provider profile against Postgres (#309).

Exercises the ``MOD-002`` ``get_provider_profile`` facade against a live
PostgreSQL mirroring ``test_directory_search.py`` (alembic head + raw seeding
of profiles/credentials/index rows):

- Only ``[Active]`` partners with a ``directory_index`` entry AND all valid
  (verified, unexpired, unrevoked) credentials resolve a profile.
- Not-``[Active]`` partners, partners with no index row, no credentials, or
  any expired/revoked/unverified credential raise
  ``ProviderProfileNotFoundError`` - the 404 that keeps a hidden partner's
  identity private (never a "hidden" 200).
- The profile payload carries only verified-safe fields: practice name,
  partner type, specialty (doctors only), service area, the ``verified``
  indicator and per-credential type + status label + expiry. Artifact refs and
  PHI never appear.
- The ``verified`` indicator always agrees with search visibility: a partner
  whose profile resolves is exactly one whose card appears in search.

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
) -> int:
    """Seed profile + credential + optional directory index row directly.

    ``service_area_id`` defaults to 1 (the Daltonganj row) so a resolved
    profile carries a real area name; pass ``None`` to exercise the
    application-layer default.
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
                    "latitude": DALTONGANJ_LATITUDE,
                    "longitude": DALTONGANJ_LONGITUDE,
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
                        "latitude": DALTONGANJ_LATITUDE,
                        "longitude": DALTONGANJ_LONGITUDE,
                        "partner_type": partner_type,
                        "specialty": specialty,
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
        specialty="General Physician",
    )

    view = await partner.get_provider_profile(partner_id)

    assert view.partner_id == partner_id
    assert view.practice_name == "Dr. Sharma Clinic"
    assert view.partner_type == "doctor"
    assert view.specialty == "General Physician"
    assert view.area == "Daltonganj"
    assert view.verified is True
    assert len(view.credentials) == 1
    credential = view.credentials[0]
    assert credential.credential_type == "medical_registration"
    assert credential.status == "verified"


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
async def test_profile_area_falls_back_to_daltonganj_default(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """A partner declaring no service area resolves the Daltonganj default area."""
    _, partner = _facade(database_url, tmp_path)
    partner_id = await _seed_partner(
        database_url,
        practice_name="Dr. No Area",
        service_area_id=None,
    )

    view = await partner.get_provider_profile(partner_id)

    assert view.area == "Daltonganj"
    assert view.verified is True


@pytest.mark.asyncio
async def test_profile_specialty_doctors_only_lab_is_none(
    database_url: str, clean_partner: None, tmp_path: Path
) -> None:
    """A lab profile carries no specialty; only doctors do."""
    _, partner = _facade(database_url, tmp_path)
    lab_id = await _seed_partner(
        database_url,
        partner_type="lab",
        practice_name="MedPlus Lab",
    )

    view = await partner.get_provider_profile(lab_id)

    assert view.partner_type == "lab"
    assert view.specialty is None
    assert view.verified is True


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
