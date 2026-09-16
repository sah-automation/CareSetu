"""PHASE-8.1 T05: IntakeFacade pick_doctor seam (ticket #443).

Drives the pick_doctor facade through mocked engine and consent facade,
picking at the facade-with-fakes seam:

- The pick and the consent grant are in ONE transaction (consent-at-pick,
  MOD-004): the assigned_partner_id is written and the consent lineage is
  minted on the same connection, no second gate.
- After the transaction commits, the consent cache is invalidated so a later
  check_consent never answers stale.
- Exactly-one-doctor: a second pick on an already-assigned intake raises
  IllegalIntakeTransitionError.
- The wrong owner is refused with IntakeNotFoundError, never revealing the
  intake exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.consent.facade import ConsentView
from modules.intake.domain.exceptions import (
    IllegalIntakeTransitionError,
    IntakeNotFoundError,
    IntakeValidationError,
)
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import PickDoctorResult

NOW = datetime.now(UTC)


class _FakeResult:
    """Mimics asyncpg ``CursorResult`` shapes used by the facade."""

    def __init__(
        self,
        scalar: object | None = None,
        row: object | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._scalar = scalar
        self._row = row
        self._rows = rows or []

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def first(self) -> object:
        return self._row

    def all(self) -> list:
        return self._rows


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    from sqlalchemy.ext.asyncio import AsyncEngine

    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _consent_view(
    *,
    consent_id: int = 55,
    lineage_ref: str = "consent/patient-7/doctor-909/55",
    version: int = 1,
) -> ConsentView:
    return ConsentView(
        consent_id=consent_id,
        lineage_ref=lineage_ref,
        patient_id=7,
        counterparty_type="doctor",
        counterparty_id="909",
        record_scope="consultations",
        status="granted",
        version=version,
        created_at=NOW,
        updated_at=NOW,
        events=[],
    )


def _intake_row(
    *,
    intake_id: int = 1,
    patient_id: int = 7,
    assigned_partner_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=intake_id,
        patient_id=patient_id,
        assigned_partner_id=assigned_partner_id,
    )


def _facade(connection: AsyncMock, consent_facade: AsyncMock | None = None) -> IntakeFacade:
    facade = IntakeFacade(engine=_engine(connection))
    facade._consent_facade = consent_facade
    return facade


# ---------------------------------------------------------------------------
# pick_doctor: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_doctor_writes_assignment_and_grants_consent_atomically() -> None:
    """The pick and the consent grant are recorded in one transaction."""
    consent = _consent_view()
    consent_facade = AsyncMock()
    consent_facade.grant_consent_on.return_value = consent

    # 1. SELECT FOR UPDATE → intake row (unassigned)
    # 2. UPDATE → set assigned_partner_id
    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=None)),
            _FakeResult(row=None),
        ]
    )
    facade = _facade(connection, consent_facade=consent_facade)

    result = await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)

    assert isinstance(result, PickDoctorResult)
    assert result.intake_id == 1
    assert result.assigned_partner_id == 909
    assert result.consent_id == 55
    assert result.consent_lineage_ref == "consent/patient-7/doctor-909/55"
    assert result.consent_version == 1

    consent_facade.grant_consent_on.assert_awaited_once_with(
        connection, 7, "doctor", "909", "consultations"
    )
    consent_facade.invalidate_consent_cache.assert_awaited_once_with(
        7, "doctor", "909", "consultations"
    )


@pytest.mark.asyncio
async def test_pick_doctor_invalidates_cache_after_commit() -> None:
    """Cache invalidation happens after the transaction, not inside it."""
    consent = _consent_view()
    consent_facade = AsyncMock()
    consent_facade.grant_consent_on.return_value = consent

    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=None)),
            _FakeResult(row=None),
        ]
    )
    facade = _facade(connection, consent_facade=consent_facade)

    await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)

    # grant_consent_on is called BEFORE invalidate_consent_cache
    grant_idx = 0
    invalidate_idx = 0
    for i, c in enumerate(consent_facade.method_calls):
        if c[0] == "grant_consent_on":
            grant_idx = i
        elif c[0] == "invalidate_consent_cache":
            invalidate_idx = i
    assert grant_idx < invalidate_idx


# ---------------------------------------------------------------------------
# pick_doctor: wrong owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_doctor_wrong_owner_raises_not_found() -> None:
    """The patient must own the intake - wrong owner never revealed."""
    consent_facade = AsyncMock()
    connection = _connection(
        [
            _FakeResult(row=_intake_row(patient_id=99, assigned_partner_id=None)),
        ]
    )
    facade = _facade(connection, consent_facade=consent_facade)

    with pytest.raises(IntakeNotFoundError, match="not found for patient 7"):
        await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)

    consent_facade.grant_consent_on.assert_not_awaited()


@pytest.mark.asyncio
async def test_pick_doctor_missing_intake_raises_not_found() -> None:
    """A non-existent intake id is refused with the same 404."""
    consent_facade = AsyncMock()
    connection = _connection([_FakeResult(row=None)])
    facade = _facade(connection, consent_facade=consent_facade)

    with pytest.raises(IntakeNotFoundError, match="not found for patient 7"):
        await facade.pick_doctor(intake_id=999, patient_id=7, partner_id=909)

    consent_facade.grant_consent_on.assert_not_awaited()


# ---------------------------------------------------------------------------
# pick_doctor: already-assigned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_doctor_second_pick_raises_illegal_transition() -> None:
    """An already-assigned intake cannot be re-picked."""
    consent_facade = AsyncMock()
    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=909)),
        ]
    )
    facade = _facade(connection, consent_facade=consent_facade)

    with pytest.raises(IllegalIntakeTransitionError, match="already assigned"):
        await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)

    consent_facade.grant_consent_on.assert_not_awaited()


# ---------------------------------------------------------------------------
# pick_doctor: validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_doctor_missing_partner_id_raises_validation_error() -> None:
    facade = _facade(_connection([]))

    with pytest.raises(IntakeValidationError, match="a doctor must be chosen"):
        await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=0)


@pytest.mark.asyncio
async def test_pick_doctor_no_consent_facade_raises_validation_error() -> None:
    facade = _facade(_connection([]))
    facade._consent_facade = None

    with pytest.raises(IntakeValidationError, match="consent facade is not configured"):
        await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)
