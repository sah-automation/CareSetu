"""PHASE-5 T05: RegistrationFacade.register facade seam (ticket #249, ADR-0010).

Drives the registration sub-facade (ADR-0006, WI-2 p1a #332) through a mocked
engine, mirroring the iam MFA facade direct-seam suite. Pins the atomicity and
duplicate-resolution contract at the facade layer (the DB-backed row behavior
is the integration suite's job):

- ``register`` holds ONE transaction and passes its own connection into the
  iam ``create_credential_account`` seam, so the iam identity insert and the
  partner profile insert commit as a single atomic unit (ADR-0010 "same
  registration transaction boundary") - no orphan identity if the profile
  insert later fails.
- A duplicate phone resolves to the existing profile with ``created=False``
  and writes no second ``partner.registered`` to the partner outbox.
- The profile insert is concurrency-safe: it uses ``INSERT ... ON CONFLICT DO
  NOTHING`` on ``uq_partner_profiles_identity`` (never a bare SELECT-then-INSERT)
  and, when a concurrent registration wins the race, re-reads and returns that
  existing profile instead of raising ``IntegrityError``.
- ``resolve_partner`` / ``get_my_status`` / ``register_partner`` / the
  non-throwing ``resolve_partner_id_by_identity`` seam resolve the same
  identity->profile projection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.iam.facade import IamFacade
from modules.iam.identity_facade import PartnerCredentialCreatedResult
from modules.partner import credential_validity as credential_validity_module
from modules.partner.domain.exceptions import (
    PartnerIamUnavailableError,
    PartnerNotFoundError,
    ServiceAreaNotFoundError,
)
from modules.partner.registration_facade import RegistrationFacade
from modules.partner.schema.models import partner_profiles


def _register_kwargs(partner_type: str) -> dict[str, object]:
    return {
        "phone": "9876543210",
        "partner_type": partner_type,
        "practice_address": "Station Road, Daltonganj",
        "practice_latitude": 24.04,
        "practice_longitude": 84.07,
    }


class _FakeResult:
    """Mimics ``Insert``/``Select`` result shapes: ``rowcount``, scalar, first row."""

    def __init__(self, rowcount: int = 0, scalar: object = None, row: object = None) -> None:
        self.rowcount = rowcount
        self._scalar = scalar
        self._row = row

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def first(self) -> object:
        return self._row


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> MagicMock:
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _iam_facade(seen_connections: list[object]) -> AsyncMock:
    iam = AsyncMock(spec=IamFacade)
    iam.create_credential_account = AsyncMock(
        side_effect=lambda phone, connection=None: (
            seen_connections.append(connection)
            or PartnerCredentialCreatedResult(identity_id=7, phone_e164="+919876543210")
        )
    )
    return iam


def _facade(connection: AsyncMock, iam: AsyncMock) -> RegistrationFacade:
    return RegistrationFacade(
        engine=_engine(connection),
        credential_validity=credential_validity_module,
        iam_facade=iam,
    )


def _inserts(connection: AsyncMock) -> list[Insert]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert)
    ]


def _profile_row(*, partner_id: int | None, status: str = "Registered") -> object | None:
    if partner_id is None:
        return None

    class _Row:
        def __init__(self) -> None:
            self.id = partner_id
            self.identity_id = 7
            self.partner_type = "doctor"
            self.status = status

    return _Row()


@pytest.mark.asyncio
async def test_register_passes_its_connection_into_the_iam_seam() -> None:
    """The identity and profile share one transaction (ADR-0010 atomicity).

    ``register`` opens a single ``begin()`` and hands that connection to
    ``create_credential_account`` instead of letting the seam open its own.
    """
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
            _FakeResult(scalar=5),  # service-area default resolution (Daltonganj)
            _FakeResult(rowcount=1, scalar=9),  # profile INSERT ... RETURNING id
            _FakeResult(rowcount=1),  # partner outbox INSERT
        ]
    )
    seen_connections: list[object] = []
    facade = _facade(connection, _iam_facade(seen_connections))

    result = await facade.register(**_register_kwargs("doctor"))

    assert seen_connections == [connection]
    assert result.created is True
    assert result.partner_id == 9
    inserts = _inserts(connection)
    assert any(stmt.table.name == partner_profiles.name for stmt in inserts)


@pytest.mark.asyncio
async def test_register_duplicate_phone_resolves_existing_profile_without_reemit() -> None:
    connection = _connection(
        [
            _FakeResult(row=_profile_row(partner_id=3)),  # profile SELECT: found + round query
            _FakeResult(scalar=0),  # max(round) for the resolved view
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    result = await facade.register(**_register_kwargs("lab"))

    assert result.created is False
    assert result.partner_id == 3
    assert result.status == "Registered"
    # No partner outbox write for a resolved duplicate.
    inserts = _inserts(connection)
    assert not [s for s in inserts if s.table.name == "partner_outbox"]


@pytest.mark.asyncio
async def test_register_concurrent_race_re_reads_winning_profile() -> None:
    """On conflict (rowcount 0) register re-reads and returns the winner."""
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
            _FakeResult(scalar=5),  # service-area default resolution (Daltonganj)
            _FakeResult(rowcount=0, scalar=None),  # profile INSERT lost the arbiter
            _FakeResult(row=_profile_row(partner_id=42)),  # re-read: winner + round query
            _FakeResult(scalar=0),  # max(round) for the resolved view
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    result = await facade.register(**_register_kwargs("chemist"))

    assert result.created is False
    assert result.partner_id == 42


@pytest.mark.asyncio
async def test_register_profile_insert_uses_on_conflict_do_nothing() -> None:
    """The profile insert carries the unique-constraint arbiter - not a bare insert."""
    connection = _connection(
        [
            _FakeResult(row=None),
            _FakeResult(scalar=5),  # service-area default resolution (Daltonganj)
            _FakeResult(rowcount=1, scalar=9),
            _FakeResult(rowcount=1),  # partner outbox INSERT
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    await facade.register(**_register_kwargs("doctor"))

    inserts = _inserts(connection)
    profile_insert = next(s for s in inserts if s.table.name == partner_profiles.name)
    # A postgresql ON CONFLICT insert carries a post-VALUES clause (DO NOTHING here).
    assert profile_insert._post_values_clause is not None


def _profile_insert_params(inserts: list[Insert]) -> dict[str, object]:
    profile_insert = next(s for s in inserts if s.table.name == partner_profiles.name)
    return dict(profile_insert.compile().params)


@pytest.mark.asyncio
async def test_register_without_area_persists_the_daltonganj_default() -> None:
    """A partner declaring no area is associated with the resolved default (REQ-008)."""
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
            _FakeResult(scalar=5),  # service-area default resolution (Daltonganj)
            _FakeResult(rowcount=1, scalar=9),  # profile INSERT ... RETURNING id
            _FakeResult(rowcount=1),  # partner outbox INSERT
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    await facade.register(**_register_kwargs("doctor"))

    assert _profile_insert_params(_inserts(connection))["service_area_id"] == 5


@pytest.mark.asyncio
async def test_register_persists_an_explicit_service_area_id() -> None:
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
            _FakeResult(scalar=3),  # service-area id lookup: exists
            _FakeResult(rowcount=1, scalar=9),  # profile INSERT ... RETURNING id
            _FakeResult(rowcount=1),  # partner outbox INSERT
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    await facade.register(
        **_register_kwargs("doctor"),
        service_area_id=3,
    )

    assert _profile_insert_params(_inserts(connection))["service_area_id"] == 3


@pytest.mark.asyncio
async def test_register_persists_a_provided_practice_name() -> None:
    """A provided practice_name is written to the profile INSERT (P6, #276)."""
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
            _FakeResult(scalar=5),  # service-area default resolution (Daltonganj)
            _FakeResult(rowcount=1, scalar=9),  # profile INSERT ... RETURNING id
            _FakeResult(rowcount=1),  # partner outbox INSERT
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    await facade.register(
        **_register_kwargs("doctor"),
        practice_name="Shanti Clinic",
    )

    assert _profile_insert_params(_inserts(connection))["practice_name"] == "Shanti Clinic"


@pytest.mark.asyncio
async def test_register_without_practice_name_inserts_null() -> None:
    """An omitted practice_name persists NULL - existing registrations keep working (P6, #276)."""
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
            _FakeResult(scalar=5),  # service-area default resolution (Daltonganj)
            _FakeResult(rowcount=1, scalar=9),  # profile INSERT ... RETURNING id
            _FakeResult(rowcount=1),  # partner outbox INSERT
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    await facade.register(**_register_kwargs("doctor"))

    assert _profile_insert_params(_inserts(connection))["practice_name"] is None


@pytest.mark.asyncio
async def test_register_rejects_an_unknown_service_area_id() -> None:
    """An unknown ``service_area_id`` is rejected - never a dangling reference."""
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
            _FakeResult(scalar=None),  # service-area id lookup: not found
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    with pytest.raises(ServiceAreaNotFoundError) as excinfo:
        await facade.register(
            **_register_kwargs("doctor"),
            service_area_id=999,
        )

    assert excinfo.value.service_area_id == 999
    # No profile insert or outbox write happened.
    assert _inserts(connection) == []


@pytest.mark.asyncio
async def test_register_partner_opens_a_registered_profile() -> None:
    """``register_partner`` opens the profile with the shared race-retry seam."""
    connection = _connection(
        [
            _FakeResult(scalar=5),  # service-area default resolution (Daltonganj)
            _FakeResult(rowcount=1, scalar=9),  # profile INSERT ... RETURNING id
            _FakeResult(rowcount=1),  # partner outbox INSERT
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    result = await facade.register_partner(
        identity_id=7,
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=24.04,
        practice_longitude=84.07,
    )

    assert result.partner_id == 9
    assert result.status == "Registered"
    assert result.round == 0


@pytest.mark.asyncio
async def test_resolve_partner_projects_the_identity_profile() -> None:
    connection = _connection(
        [
            _FakeResult(row=_profile_row(partner_id=3)),  # profile SELECT: found
            _FakeResult(scalar=0),  # max(round) for the resolved view
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    result = await facade.resolve_partner(7)

    assert result.partner_id == 3
    assert result.status == "Registered"
    assert result.round == 0


@pytest.mark.asyncio
async def test_resolve_partner_raises_when_identity_has_no_profile() -> None:
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    with pytest.raises(PartnerNotFoundError) as excinfo:
        await facade.resolve_partner(7)

    assert excinfo.value.partner_id == 7


@pytest.mark.asyncio
async def test_resolve_partner_id_by_identity_is_the_non_throwing_seam() -> None:
    """A patient-only phone resolves to None, never an exception (T05, #298)."""
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    assert await facade.resolve_partner_id_by_identity(7) is None


@pytest.mark.asyncio
async def test_resolve_partner_id_by_identity_returns_the_profile_id() -> None:
    connection = _connection(
        [
            _FakeResult(row=_profile_row(partner_id=3)),  # profile SELECT: found
            _FakeResult(scalar=0),  # max(round) for the resolved view
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    assert await facade.resolve_partner_id_by_identity(7) == 3


@pytest.mark.asyncio
async def test_register_fails_loudly_without_the_iam_seam() -> None:
    """WI-3 (#336): a facade built without iam refuses to register.

    The daily credential-expiry sweep composes a ``PartnerFacade`` without an
    iam facade. ``register`` needs the seam to create the sync credential
    account (ADR-0010) and must fail with the typed
    ``PartnerIamUnavailableError`` - never a silent no-op or a profile that can
    never authenticate.
    """
    facade = RegistrationFacade(
        engine=_engine(_connection([_FakeResult(row=None)])),
        credential_validity=credential_validity_module,
    )

    with pytest.raises(PartnerIamUnavailableError):
        await facade.register(**_register_kwargs("doctor"))


@pytest.mark.asyncio
async def test_get_my_status_projects_type_and_round() -> None:
    """The partner's own status read (US-6) resolves the identity projection."""
    connection = _connection(
        [
            _FakeResult(row=_profile_row(partner_id=3)),  # profile SELECT: found
            _FakeResult(scalar=0),  # max(round) for the resolved view
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    result = await facade.get_my_status(7)

    assert result.partner_id == 3
    assert result.status == "Registered"
    assert result.partner_type == "doctor"
    assert result.round == 0
    assert result.created_at is None


@pytest.mark.asyncio
async def test_get_my_status_raises_when_identity_has_no_profile() -> None:
    connection = _connection(
        [
            _FakeResult(row=None),  # profile SELECT: absent
        ]
    )
    facade = _facade(connection, _iam_facade([]))

    with pytest.raises(PartnerNotFoundError) as excinfo:
        await facade.get_my_status(7)

    assert excinfo.value.partner_id == 7
