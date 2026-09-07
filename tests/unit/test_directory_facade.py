"""DirectoryFacade direct-seam suite (ADR-0006, WI-2 p2b #337).

Drives the directory sub-facade through a mocked engine, mirroring the iam MFA
facade direct-seam suite and the registration/operator-gate sub-facade suites:
no SQL plumbing, no scripting of exact SQL call order - the mocked engine pins
the seam shape and the error/behavior paths via ``connection.execute`` side
effects, while the DB-backed row behavior (distance sort, real visibility
predicates, the Redis accelerator against a live store) is the integration
suite's job.

Pins:

- ``search_directory`` projects SQL rows into a ``DirectorySearchView`` (area
  fallback, ``verified`` tick), applies the wider-area fallback with the honest
  ``fell_back`` flag, and writes the ``directory.search`` analytics envelope in
  the same transaction.
- The cached-search accelerator (PHASE-6 T02b, #314): a valid cache hit is
  served without re-scanning; a hit whose cached ids no longer pass validity is
  rejected and fresh SQL replaces the stale row (ADR-0011 lazy correctness).
- ``get_provider_profile`` projects the verified-safe payload, or raises
  ``ProviderProfileNotFoundError`` when the partner is hidden.
- ``record_partner_selected`` writes the analytics pick, nothing else.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.partner.directory_facade import DirectoryFacade
from modules.partner.domain.exceptions import ProviderProfileNotFoundError
from modules.partner.facade import DEFAULT_SERVICE_AREA_NAME


class _FakeValidity:
    """Mimics the credential-validity deep module (WI-1, #331) read seam."""

    def provider_visible(self, column: Any) -> Any:
        del column
        return True


class _FakeCache:
    """Mimics the directory-cache seam (PHASE-6 T02b, #314) as a stub module."""

    def __init__(self, hits: dict[bool, tuple[list[dict[str, Any]], bool]] | None = None) -> None:
        self._hits = hits or {}
        self.writes: list[dict[str, Any]] = []

    async def get_cached_search(
        self,
        *,
        query: str | None,
        partner_type: str | None,
        specialty: str | None,
        latitude: float,
        longitude: float,
        expanded: bool,
    ) -> tuple[list[dict[str, Any]], bool] | None:
        return self._hits.get(expanded)

    async def set_cached_search(self, **kwargs: Any) -> None:
        self.writes.append(kwargs)


class _Row:
    """Mimics a SELECT result row with attribute access."""

    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


class _FakeResult:
    """Mimics executed-statement result shapes used by the directory reads."""

    def __init__(
        self,
        rows: list[Any] | None = None,
        row: Any | None = None,
        scalar: Any = None,
    ) -> None:
        self._rows = rows if rows is not None else []
        self._row = row
        self._scalar = scalar

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any | None:
        return self._row

    def scalar_one(self) -> Any:
        return self._scalar


def _connection(results: list[Any]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=results)
    return connection


def _engine(connection: AsyncMock) -> MagicMock:
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _facade(
    connection: AsyncMock,
    *,
    ttl_seconds: int = 0,
    cache: _FakeCache | None = None,
) -> DirectoryFacade:
    return DirectoryFacade(
        engine=_engine(connection),
        credential_validity=_FakeValidity(),
        directory_cache=cache if cache is not None else _FakeCache(),
        directory_ttl_seconds=ttl_seconds,
        directory_max_results=50,
    )


def _entry_row(*, partner_id: int, area_name: Any = None) -> _Row:
    return _Row(
        partner_id=partner_id,
        practice_name=f"Practice {partner_id}",
        partner_type="doctor",
        specialty="General Physician" if partner_id % 2 else None,
        area_name=area_name,
        distance_km=3.5,
    )


def _executed(connection: AsyncMock) -> list[Any]:
    return [call.args[0] for call in connection.execute.await_args_list]


def _inserts(connection: AsyncMock) -> list[Insert]:
    return [stmt for stmt in _executed(connection) if isinstance(stmt, Insert)]


def _cached_entry(partner_id: int) -> dict[str, Any]:
    return {
        "partner_id": partner_id,
        "practice_name": f"Practice {partner_id}",
        "partner_type": "doctor",
        "specialty": None,
        "area": "DALTONGANJ",
        "distance_km": 3.5,
        "verified": True,
    }


@pytest.mark.asyncio
async def test_search_directory_projects_rows_with_the_area_fallback() -> None:
    """SQL rows project into entries; a missing recorded area falls back to the launch default."""
    connection = _connection(
        [
            _FakeResult(
                rows=[
                    _entry_row(partner_id=1),
                    _entry_row(partner_id=2, area_name="Med"),
                ]
            ),
            _FakeResult(),  # directory.search analytics outbox write
        ]
    )
    facade = _facade(connection)

    view = await facade.search_directory()

    assert view.fell_back is False
    assert [entry.partner_id for entry in view.items] == [1, 2]
    first, second = view.items
    assert first.area == DEFAULT_SERVICE_AREA_NAME
    assert first.verified is True
    assert second.area == "Med"
    assert isinstance(first.partner_id, int)
    assert isinstance(first.distance_km, float)
    # The analytics envelope is written in the same transaction as the read.
    outbox = _inserts(connection)
    assert len(outbox) == 1
    assert outbox[0].table.name == "partner_outbox"


@pytest.mark.asyncio
async def test_search_directory_flags_the_wider_area_fallback() -> None:
    """An empty peri-urban pass relaxes only the location constraint and labels fell_back."""
    connection = _connection(
        [
            _FakeResult(rows=[]),  # in-scope: nothing
            _FakeResult(rows=[_entry_row(partner_id=7)]),  # relaxed wider-area pass
            _FakeResult(),  # directory.search analytics outbox write
        ]
    )
    facade = _facade(connection)

    view = await facade.search_directory()

    assert view.fell_back is True
    assert [entry.partner_id for entry in view.items] == [7]


@pytest.mark.asyncio
async def test_search_directory_does_not_write_the_cache_when_ttl_is_zero() -> None:
    """TTL 0 is the SQL-only boot default: the accelerator is never touched."""
    cache = _FakeCache()
    connection = _connection(
        [
            _FakeResult(rows=[_entry_row(partner_id=1)]),
            _FakeResult(),  # directory.search analytics outbox write
        ]
    )
    facade = _facade(connection, cache=cache)

    await facade.search_directory()

    assert cache.writes == []


@pytest.mark.asyncio
async def test_search_directory_serves_a_valid_cache_hit_without_rescan() -> None:
    """A clean hit still re-derives validity then serves the cached items as-is."""
    raw = [_cached_entry(11), _cached_entry(22)]
    cache = _FakeCache({False: (raw, False)})
    connection = _connection(
        [
            _FakeResult(scalar=2),  # validity count: both cached ids pass
            _FakeResult(),  # directory.search analytics outbox write
        ]
    )
    facade = _facade(connection, ttl_seconds=60, cache=cache)

    view = await facade.search_directory()

    assert view.fell_back is False
    assert [entry.partner_id for entry in view.items] == [11, 22]
    # Served from the cache: only the validity re-derivation and the analytics
    # outbox write ran - the SQL distance scan never did, and nothing was
    # rewritten to the cache.
    assert len(_executed(connection)) == 2
    assert cache.writes == []


@pytest.mark.asyncio
async def test_search_directory_replaces_a_stale_cache_hit_with_fresh_sql() -> None:
    """A cached partner that no longer passes validity is rejected (ADR-0011 lazy correctness)."""
    stale = [_cached_entry(99)]
    cache = _FakeCache({False: (stale, False)})
    connection = _connection(
        [
            _FakeResult(scalar=0),  # validity count: the cached id is no longer visible
            _FakeResult(rows=[_entry_row(partner_id=5)]),  # fresh SQL read
            _FakeResult(),  # directory.search analytics outbox write
        ]
    )
    facade = _facade(connection, ttl_seconds=60, cache=cache)

    view = await facade.search_directory()

    # The stale cached partner never surfaces; fresh SQL replaces it.
    assert [entry.partner_id for entry in view.items] == [5]
    assert view.items[0].specialty == "General Physician"


@pytest.mark.asyncio
async def test_get_provider_profile_projects_the_verified_safe_payload() -> None:
    connection = _connection(
        [
            _FakeResult(
                row=_Row(
                    partner_id=3,
                    practice_name="Healing Hands",
                    partner_type="doctor",
                    specialty="Dentist",
                    area_name="DALTONGANJ",
                )
            ),
            _FakeResult(
                rows=[
                    _Row(credential_type="degree_certificate", expires_at=None),
                    _Row(credential_type="registration_certificate", expires_at=None),
                ]
            ),
        ]
    )
    facade = _facade(connection)

    profile = await facade.get_provider_profile(3)

    assert profile.partner_id == 3
    assert profile.practice_name == "Healing Hands"
    assert profile.partner_type == "doctor"
    assert profile.specialty == "Dentist"
    assert profile.verified is True
    assert [credential.credential_type for credential in profile.credentials] == [
        "degree_certificate",
        "registration_certificate",
    ]
    assert all(credential.status == "verified" for credential in profile.credentials)


@pytest.mark.asyncio
async def test_get_provider_profile_is_hidden_exactly_when_search_hides_the_card() -> None:
    connection = _connection([_FakeResult(row=None)])
    facade = _facade(connection)

    with pytest.raises(ProviderProfileNotFoundError) as excinfo:
        await facade.get_provider_profile(999)

    assert excinfo.value.partner_id == 999


@pytest.mark.asyncio
async def test_record_partner_selected_writes_only_the_pick() -> None:
    connection = _connection([_FakeResult()])
    facade = _facade(connection)

    await facade.record_partner_selected(partner_id=3, partner_type="lab", source="search")

    inserts = _inserts(connection)
    assert len(inserts) == 1
    assert inserts[0].table.name == "partner_outbox"
