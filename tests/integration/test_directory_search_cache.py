"""PHASE-6 T02b: the directory-search result cache against Postgres (#314).

Drives the ``MOD-002`` ``search_directory`` without a live Redis: the cache
module's global client is pointed at an in-memory fake so the facade's
cache-first / SQL-fallback / write-back / invalidation plumbing is exercised on
real data:

- A cached view is served on a repeat search WITHOUT re-running the distance
  scan (a partner added after the row was cached does not appear until the
  cache is flushed or the row expires).
- Stale rows never surface (ADR-0011 lazy correctness): when a cached partner
  no longer passes the visibility tick (deactivated since the row was written),
  the hit is rejected and fresh SQL replaces it - the cached id is NOT served.
- The namespace is flushed on ``partner.activated`` and on
  ``credential.invalidated`` (operator reject of an Active partner and the
  permanent-rejection credential purge) - the two events that can change which
  partners a cached search would return (ticket #314 ACs).

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from conftest import seed_daltonganj_service_area
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from test_directory_search import _seed_partner

import modules.partner.directory_cache as directory_cache
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.facade import DALTONGANJ_LATITUDE, DALTONGANJ_LONGITUDE, PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_OPERATOR_ID = 77
_TTL_SECONDS = 300


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
async def clean_partner(database_url: str, migration: None) -> Iterator[None]:
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
    directory_cache._REDIS_CLIENT = None


class _FakeRedis:
    """In-memory stand-in for the ``redis.asyncio.Redis`` surface the facade
    touches through :mod:`modules.partner.directory_cache`."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.last_ttl: int | None = ex

    async def scan(
        self, cursor: int, match: str | None = None, count: int | None = None
    ) -> tuple[int, list[str]]:
        keys = (
            sorted(self.store)
            if match is None
            else [k for k in self.store if k.startswith(match.rstrip("*"))]
        )
        return 0, keys

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed


def _facade(database_url: str, tmp_path: Path) -> tuple[IamFacade, PartnerFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    store = CredentialArtifactStore(root=tmp_path, key_bytes=bytes(32))
    partner = PartnerFacade(
        engine=engine,
        iam_facade=iam,
        artifact_store=store,
        directory_ttl_seconds=_TTL_SECONDS,
    )
    return iam, partner


def _cached(store: dict[str, str]) -> list[tuple[str, str]]:
    return [(k, v) for k, v in store.items() if k.startswith("directory:")]


@pytest.mark.asyncio
async def test_repeat_search_served_from_cache_without_rescan(
    database_url: str, clean_partner: Iterator[None], tmp_path: Path
) -> None:
    """A hit re-derives validity but does NOT re-scan: a partner added after the
    row was cached stays invisible until the cache is flushed or expires."""
    _, partner = _facade(database_url, tmp_path)
    cache = _FakeRedis()
    directory_cache._REDIS_CLIENT = cache

    await _seed_partner(
        database_url, practice_name="Dr. Clinch Square", specialty="General Physician"
    )
    first = await partner.search_directory()
    assert [e.practice_name for e in first.items] == ["Dr. Clinch Square"]
    assert len(_cached(cache.store)) == 1

    await _seed_partner(database_url, practice_name="Dr. Newcomer", specialty="General Physician")

    second = await partner.search_directory()
    # Served the metre-accurate distance rows from the cache - the distance scan
    # never ran, so the newcomer is not in the result.
    assert [e.practice_name for e in second.items] == ["Dr. Clinch Square"]
    assert second.fell_back is False


@pytest.mark.asyncio
async def test_stale_cached_partner_never_surfaces(
    database_url: str, clean_partner: Iterator[None], tmp_path: Path
) -> None:
    """Lazy correctness (ADR-0011): a cached partner deactivated since the row
    was written is rejected on read and fresh SQL replaces the stale row."""
    _, partner = _facade(database_url, tmp_path)
    cache = _FakeRedis()
    directory_cache._REDIS_CLIENT = cache

    await _seed_partner(
        database_url, practice_name="Dr. Clinch Square", specialty="General Physician"
    )
    first = await partner.search_directory()
    assert [e.practice_name for e in first.items] == ["Dr. Clinch Square"]
    assert len(_cached(cache.store)) == 1

    # Hide the partner from the index (deactivation) WITHOUT touching the cache:
    # a fresh distance scan now excludes it.
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE partner.partner_directory_index SET is_active = false")
            )
    finally:
        await engine.dispose()

    second = await partner.search_directory()
    # The cached row still claims the partner exists, but the re-derivation
    # rejects the hit (is_active now false) and the SQL recompute is served.
    assert second.items == []
    assert second.fell_back is True
    # The stale partner-carrying row is STILL in the cache - the point of
    # ADR-0011 lazy correctness is that it is rejected on every read, never
    # trusted. The recomputed empty result is what actually gets served.
    stale = [v for k, v in _cached(cache.store) if "Dr. Clinch Square" in v]
    assert stale
    # The fresh empty in-scope result (with its wide-area fallback) is cached.
    assert any('fell_back": true' in v and '"items": []' in v for _, v in _cached(cache.store))


@pytest.mark.asyncio
async def test_activation_flushes_namespace_and_new_partner_appears(
    database_url: str, clean_partner: Iterator[None], tmp_path: Path
) -> None:
    """``partner.activated`` invalidates the cache: the newly approved partner
    is visible on the next search even though the pre-approval row was cached."""
    _, partner = _facade(database_url, tmp_path)
    cache = _FakeRedis()
    directory_cache._REDIS_CLIENT = cache

    await _seed_partner(
        database_url, practice_name="Dr. Clinch Square", specialty="General Physician"
    )
    # A partner verified + indexed but STILL Under Verification - hidden now,
    # becomes visible only once activated.
    fresh_id = await _seed_partner(
        database_url,
        practice_name="Dr. Freshly Approved",
        status="Under Verification",
        specialty="General Physician",
    )

    before = await partner.search_directory()
    assert [e.practice_name for e in before.items] == ["Dr. Clinch Square"]
    assert len(_cached(cache.store)) == 1

    await partner.operator_decision(fresh_id, decision_by=_OPERATOR_ID, approve=True)

    # The activation flushed the whole namespace.
    assert _cached(cache.store) == []

    after = await partner.search_directory()
    names = {e.practice_name for e in after.items}
    assert names == {"Dr. Clinch Square", "Dr. Freshly Approved"}


@pytest.mark.asyncio
async def test_credential_invalidated_reject_of_active_partner_flushes_cache(
    database_url: str, clean_partner: Iterator[None], tmp_path: Path
) -> None:
    """``credential.invalidated`` (operator reject of an Active partner, the T02a
    deindex path) invalidates the cache and the deactivated partner hides."""
    _, partner = _facade(database_url, tmp_path)
    cache = _FakeRedis()
    directory_cache._REDIS_CLIENT = cache

    active_id = await _seed_partner(
        database_url, practice_name="Dr. Clinch Square", specialty="General Physician"
    )
    first = await partner.search_directory()
    assert [e.practice_name for e in first.items] == ["Dr. Clinch Square"]
    assert len(_cached(cache.store)) == 1

    await partner.operator_decision(
        active_id, decision_by=_OPERATOR_ID, approve=False, reason="reverification failed"
    )

    assert _cached(cache.store) == []

    after = await partner.search_directory()
    assert after.items == []


@pytest.mark.asyncio
async def test_credential_purge_flushes_cache(
    database_url: str, clean_partner: Iterator[None], tmp_path: Path
) -> None:
    """The permanent-rejection credential purge also flushes the namespace."""
    _, partner = _facade(database_url, tmp_path)
    cache = _FakeRedis()
    directory_cache._REDIS_CLIENT = cache

    await _seed_partner(
        database_url, practice_name="Dr. Clinch Square", specialty="General Physician"
    )
    first = await partner.search_directory()
    assert len(first.items) == 1
    assert len(_cached(cache.store)) == 1

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            # A permanently rejected partner whose credential is past its
            # cleanup window - the purge deletes it and emits invalidated.
            profile_id = int(
                (
                    await connection.execute(
                        text(
                            "INSERT INTO partner.partner_profiles "
                            "(identity_id, partner_type, status, practice_name, practice_address, "
                            " practice_latitude, practice_longitude) "
                            "VALUES (9001, 'doctor', 'Rejected', 'Dr. Purged', "
                            " 'integration test address', :latitude, :longitude) RETURNING id"
                        ),
                        {"latitude": DALTONGANJ_LATITUDE, "longitude": DALTONGANJ_LONGITUDE},
                    )
                ).scalar_one()
            )
            await connection.execute(
                text(
                    "INSERT INTO partner.partner_credentials "
                    "(profile_id, credential_type, verified, expires_at, revoked_at, "
                    " cleanup_due_at) "
                    "VALUES (:profile_id, 'medical_registration', true, NULL, NULL, "
                    " :due_at)"
                ),
                {
                    "profile_id": profile_id,
                    "due_at": datetime.now(UTC) - timedelta(days=40),
                },
            )
    finally:
        await engine.dispose()

    await partner.purge_expired_credentials()

    assert _cached(cache.store) == []

    after = await partner.search_directory()
    assert [e.practice_name for e in after.items] == ["Dr. Clinch Square"]
