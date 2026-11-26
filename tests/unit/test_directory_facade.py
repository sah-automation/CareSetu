"""

Trace: FEAT-004 (Provider Directory and Search).
DirectoryFacade direct-seam suite (ADR-0006, WI-2 p2b #337).

Drives the directory sub-facade through a mocked engine, mirroring the iam MFA
facade direct-seam suite and the registration/operator-gate sub-facade suites:
no SQL plumbing, no scripting of exact SQL call order - the mocked engine pins
the seam shape and the error/behavior paths via ``connection.execute`` side
effects, while the DB-backed row behavior (distance sort, real visibility
predicates, the Redis accelerator against a live store) is the integration
suite's job.

Pins:

- ``search_directory`` projects SQL rows into a ``DirectorySearchView``
  (``area`` from the doctor-declared locality, null when none, ``verified`` tick),
  applies the wider-area fallback with the honest ``fell_back`` flag, and writes
  the ``directory.search`` analytics envelope in the same transaction. That the
  projected area comes from ``address_locality`` and NOT from
  ``partner_service_areas`` is a DB-backed property - only a real query can show a
  doctor whose recorded service area disagrees with their declared locality - so it
  is the integration suite's pin
  (``tests/integration/test_directory_search.py``, #612), not this one's.
- The cached-search accelerator (PHASE-6 T02b, #314): a valid cache hit is
  served without re-scanning; a hit whose cached ids no longer pass validity is
  rejected and fresh SQL replaces the stale row (ADR-0011 lazy correctness).
- ``get_provider_profile`` projects the credential band the platform checked and
  the declared band the doctor wrote (#613) - the closed-vocabulary selections
  filtered on read - or raises ``ProviderProfileNotFoundError`` when the
  partner is hidden.
- ``record_partner_selected`` writes the analytics pick, nothing else.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.partner.directory_facade import DirectoryFacade
from modules.partner.directory_models import ProviderProfileView
from modules.partner.domain.exceptions import ProviderProfileNotFoundError


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


def _entry_row(*, partner_id: int, locality: Any = None) -> _Row:
    return _Row(
        partner_id=partner_id,
        practice_name=f"Practice {partner_id}",
        partner_type="doctor",
        # A JSONB array, as the widened multi-valued column decodes (#606), and
        # NULL for an even partner - the shape that still says "carries no
        # specialty", which is what a lab/chemist entry carries.
        specialty=["General Physician"] if partner_id % 2 else None,
        # The doctor-declared locality column (#612), and NULL for a doctor who
        # declared none - which projects to a null area, not a substituted
        # vocabulary row.
        declared_locality=locality,
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
async def test_search_directory_projects_rows_with_the_declared_locality() -> None:
    """SQL rows project into entries; ``area`` is the declared locality, null when none (#612)."""
    connection = _connection(
        [
            _FakeResult(
                rows=[
                    _entry_row(partner_id=1),
                    _entry_row(partner_id=2, locality="Medininagar"),
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
    # No declared locality means NO area. The pre-#612 projection substituted the
    # launch service-area name here, which rendered every doctor in the directory
    # as Daltonganj - a platform default the doctor never declared.
    assert first.area is None
    assert first.verified is True
    assert second.area == "Medininagar"
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


def _profile_row(**overrides: Any) -> _Row:
    """A profile SELECT row for a doctor who has filled the whole declared band in.

    Every column the profile SELECT reads since #613, so a test that constructs
    its row from here cannot drift out of step with the projection and fail with
    a bare ``AttributeError`` instead of an assertion about behaviour.
    """
    values: dict[str, Any] = {
        "partner_id": 3,
        "practice_name": "Dr. Asha Verma",
        "partner_type": "doctor",
        "clinic_name": "Shanti Clinic",
        "specialties": ["General Physician", "Pediatrician"],
        "languages": ["Hindi", "English"],
        "consulting_days": ["Monday", "Saturday"],
        "consulting_hours": "Mon-Sat, 9am-1pm",
        "about": "Twenty years of neighbourhood practice.",
        "experience_years": 20,
        "address_line": "12, Nehru Road",
        "address_landmark": "Near the water tank",
        "address_locality": "Sadar",
        "address_city": "Daltonganj",
        "address_pin": "827101",
    }
    values.update(overrides)
    return _Row(**values)


async def _profile_for(row: _Row) -> ProviderProfileView:
    facade = _facade(_connection([_FakeResult(row=row), _FakeResult(rows=[])]))
    return await facade.get_provider_profile(3)


@pytest.mark.asyncio
async def test_get_provider_profile_projects_the_credential_band() -> None:
    """The band the platform checked is unchanged by the #613 widening."""
    connection = _connection(
        [
            _FakeResult(
                row=_profile_row(
                    practice_name="Healing Hands",
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
    assert profile.verified is True
    assert [credential.credential_type for credential in profile.credentials] == [
        "degree_certificate",
        "registration_certificate",
    ]
    assert all(credential.status == "verified" for credential in profile.credentials)


@pytest.mark.asyncio
async def test_get_provider_profile_derives_the_specialty_label_from_the_selection() -> None:
    """The singular label is the FIRST member of the same list it publishes.

    The narrow surfaces render one label, and #613 added the whole selection
    beside it. Reading the two from different columns would let one payload report
    a label its own ``specialties`` list does not contain, so the label is derived
    from the filtered selection and cannot drift from it - including when the first
    declared member is one the vocabulary does not own and is therefore dropped.
    """
    profile = await _profile_for(
        _profile_row(specialties=["Homeopathician", "Dentist", "Pediatrician"])
    )

    assert profile.specialties == ["Dentist", "Pediatrician"]
    assert profile.specialty == profile.specialties[0]

    empty = await _profile_for(_profile_row(specialties=[]))

    assert empty.specialties == []
    assert empty.specialty is None


@pytest.mark.asyncio
async def test_get_provider_profile_area_reads_the_declared_locality() -> None:
    """#613 closes the half #612 left: ``area`` is the DECLARED locality.

    #612 moved the search card onto ``address_locality`` and named this read as
    the half it did not touch, so a card and the profile behind it could name two
    different places - or the profile could name a platform vocabulary row. The
    read no longer joins the service-area vocabulary at all, so an undeclared
    locality is ``None`` rather than a substituted default.
    """
    declared = await _profile_for(_profile_row(address_locality="Medininagar"))

    assert declared.area == "Medininagar"
    assert declared.area == declared.locality

    undeclared = await _profile_for(_profile_row(address_locality=None))

    assert undeclared.area is None


@pytest.mark.asyncio
async def test_get_provider_profile_carries_the_declared_fields() -> None:
    """#613: the widened payload projects the profile row's declared columns.

    The fields are read off the PROFILE ROW, not off the directory entry this
    read already joined - the profile row is what the four section writes land
    on, so this is the only source that cannot lag the doctor's last save.
    """
    profile = await _profile_for(_profile_row())

    assert profile.clinic_name == "Shanti Clinic"
    assert profile.specialties == ["General Physician", "Pediatrician"]
    assert profile.languages == ["Hindi", "English"]
    assert profile.consulting_days == ["Monday", "Saturday"]
    assert profile.consulting_hours == "Mon-Sat, 9am-1pm"
    assert profile.about == "Twenty years of neighbourhood practice."
    assert profile.experience_years == 20
    assert profile.address_line == "12, Nehru Road"
    assert profile.landmark == "Near the water tank"
    assert profile.locality == "Sadar"
    assert profile.city == "Daltonganj"
    assert profile.pin_code == "827101"
    # AC 4: none of that reached the indicator.
    assert profile.verified is True


@pytest.mark.asyncio
async def test_get_provider_profile_drops_a_selection_member_the_vocabulary_does_not_own() -> None:
    """A closed list is enforced at the application layer, so the PUBLIC read filters it.

    No CHECK constraint carries ``Specialty`` / ``ConsultLanguage`` /
    ``ConsultingDay``, so a hand-repaired row is the one way a value outside the
    list reaches the column. It must not reach a patient - and it must not fail
    the read either, which is why the member drops instead of raising.
    """
    profile = await _profile_for(
        _profile_row(
            specialties=["General Physician", "Homeopathician", "Dentist"],
            languages=["Hindi", "Klingon"],
            consulting_days=["Monday", "Caturday"],
        )
    )

    assert profile.specialties == ["General Physician", "Dentist"]
    assert profile.languages == ["Hindi"]
    assert profile.consulting_days == ["Monday"]


@pytest.mark.asyncio
async def test_get_provider_profile_reads_an_undeclared_band_as_nulls_and_empty_lists() -> None:
    """A doctor who has declared nothing still resolves a 200-shaped profile."""
    profile = await _profile_for(
        _profile_row(
            clinic_name=None,
            specialties=[],
            languages=[],
            consulting_days=[],
            consulting_hours=None,
            about=None,
            experience_years=None,
            address_line=None,
            address_landmark=None,
            address_locality=None,
            address_city=None,
            address_pin=None,
        )
    )

    assert profile.clinic_name is None
    assert profile.specialties == []
    assert profile.languages == []
    assert profile.consulting_days == []
    assert profile.consulting_hours is None
    assert profile.about is None
    assert profile.experience_years is None
    assert profile.address_line is None
    assert profile.landmark is None
    assert profile.locality is None
    assert profile.city is None
    assert profile.pin_code is None


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
