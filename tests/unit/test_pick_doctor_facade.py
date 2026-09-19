"""PHASE-8.1 T05/T3: IntakeFacade pick_doctor seam (tickets #443, #480).

Drives the pick_doctor facade through mocked engine and consent facade,
picking at the facade-with-fakes seam:

- The pick and the consent grants are in ONE transaction (consent-at-pick,
  MOD-004): the assigned_partner_id is written and the consultations AND
  prescriptions consent lineages are minted on the same connection - either
  both grants or neither (#480), no second gate.
- After the transaction commits, the consent cache is invalidated for every
  scope just granted so a later check_consent never answers stale.
- A grant-leg failure aborts the pick: the transaction exits with the
  exception and nothing (assignment or grant) persists.
- Exactly-one-doctor: a second pick on an already-assigned intake raises
  IllegalIntakeTransitionError.
- The wrong owner is refused with IntakeNotFoundError, never revealing the
  intake exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

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
    record_scope: str = "consultations",
) -> ConsentView:
    return ConsentView(
        consent_id=consent_id,
        lineage_ref=lineage_ref,
        patient_id=7,
        counterparty_type="doctor",
        counterparty_id="909",
        record_scope=record_scope,
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
    """The pick and BOTH consent grants are recorded in one transaction."""
    consultations_grant = _consent_view(consent_id=55, record_scope="consultations")
    prescriptions_grant = _consent_view(
        consent_id=56,
        lineage_ref="consent/patient-7/doctor-909/56",
        record_scope="prescriptions",
    )
    consent_facade = AsyncMock()
    consent_facade.grant_consent_on.side_effect = [consultations_grant, prescriptions_grant]

    # 1. SELECT FOR UPDATE → intake row (unassigned)
    # 2. UPDATE → set assigned_partner_id
    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=None)),
            _FakeResult(row=None),
        ]
    )
    engine = _engine(connection)
    facade = IntakeFacade(engine=engine)
    facade._consent_facade = consent_facade

    result = await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)

    assert isinstance(result, PickDoctorResult)
    assert result.intake_id == 1
    assert result.assigned_partner_id == 909
    # The response contract is unchanged: it reports the consultations grant,
    # the scope the pick itself serves.
    assert result.consent_id == 55
    assert result.consent_lineage_ref == "consent/patient-7/doctor-909/55"
    assert result.consent_version == 1

    # Both scopes are minted on the SAME connection, in scope order, inside
    # the single transaction (consent-at-pick, #480).
    assert consent_facade.grant_consent_on.await_args_list == [
        call(connection, 7, "doctor", "909", "consultations"),
        call(connection, 7, "doctor", "909", "prescriptions"),
    ]
    # Both grants land before the transaction exits (commits) cleanly.
    assert engine.begin.return_value.__aexit__.call_args.args[0] is None

    # Both scopes are flushed from the gate cache after the commit.
    assert consent_facade.invalidate_consent_cache.await_args_list == [
        call(7, "doctor", "909", "consultations"),
        call(7, "doctor", "909", "prescriptions"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("first_leg_fails", [True, False])
async def test_pick_doctor_grant_failure_aborts_pick(first_leg_fails: bool) -> None:
    """A failing grant leg rolls the whole pick back - either both or neither.

    Exercises both legs: the consultations grant failing first and the
    prescriptions grant failing second.
    """
    consent = _consent_view()
    consent_facade = AsyncMock()
    failure = RuntimeError("grant failed")
    if first_leg_fails:
        consent_facade.grant_consent_on.side_effect = [failure, consent]
    else:
        consent_facade.grant_consent_on.side_effect = [consent, failure]

    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=None)),
            _FakeResult(row=None),
        ]
    )
    engine = _engine(connection)
    facade = IntakeFacade(engine=engine)
    facade._consent_facade = consent_facade

    with pytest.raises(RuntimeError, match="grant failed"):
        await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)

    # Every granted leg before the failure was attempted on the open
    # connection, and the failing leg is the last one attempted ...
    if first_leg_fails:
        assert consent_facade.grant_consent_on.await_count == 1
    else:
        assert consent_facade.grant_consent_on.await_count == 2
    failed_scope = "consultations" if first_leg_fails else "prescriptions"
    assert consent_facade.grant_consent_on.await_args_list[-1].args[4] == failed_scope
    # ... and the transaction exited WITH the exception - SQLAlchemy rolls
    # back, so neither the assignment nor any grant persists (no partial pick).
    assert engine.begin.return_value.__aexit__.call_args.args[0] is RuntimeError
    # No cache invalidation of a grant that never committed.
    consent_facade.invalidate_consent_cache.assert_not_awaited()


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

    # All grants are issued BEFORE any cache invalidation
    grant_idxs = [
        i for i, c in enumerate(consent_facade.method_calls) if c[0] == "grant_consent_on"
    ]
    invalidate_idxs = [
        i for i, c in enumerate(consent_facade.method_calls) if c[0] == "invalidate_consent_cache"
    ]
    assert max(grant_idxs) < min(invalidate_idxs)
    # Cache invalidated once per granted scope (consultations + prescriptions).
    assert len(grant_idxs) == 2
    assert len(invalidate_idxs) == 2


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
