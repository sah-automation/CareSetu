"""PHASE-8.1 T05/T3: IntakeFacade pick_doctor seam (FEAT-002, #443, #480, #663).

Drives the pick_doctor facade through mocked engine and consent facade,
picking at the facade-with-fakes seam:

- The pick and the consent grants are in ONE transaction (consent-at-pick,
  MOD-004): the assigned_partner_id is written and the consultations,
  prescriptions AND health_background consent lineages are minted on the
  same connection - all three grants or none (#480, widened #663), no
  second gate.
- The care-attribution event (``intake.doctor_assigned``, B4d #720) is written
  to the intake outbox on that same connection, inside that same transaction as
  the assignment, so a downstream consumer learns the intake-to-doctor pairing
  from the event rather than from a cross-schema read (ADR-0003). A pick that
  rolls back leaves no attribution edge behind, and a refused second pick
  publishes nothing at all.
- After the transaction commits, the consent cache is invalidated for every
  scope just granted so a later check_consent never answers stale.
- The pick result contract reports the consultations grant only - the
  widened grant set never changes the response shape.
- A grant-leg failure aborts the pick: the transaction exits with the
  exception and nothing (assignment, attribution event or grant) persists.
- Exactly-one-doctor: a second pick on an already-assigned intake raises
  IllegalIntakeTransitionError.
- The wrong owner is refused with IntakeNotFoundError, never revealing the
  intake exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, call
from uuid import UUID

import pytest
from sqlalchemy.sql.expression import Insert

from bus.events import EVENT_INTAKE_DOCTOR_ASSIGNED
from modules.consent.facade import ConsentView
from modules.intake.domain.events import IntakeDoctorAssignedPayload
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


def _doctor_assigned_writes(connection: AsyncMock) -> list[Insert]:
    """The ``intake_outbox`` inserts carrying the care-attribution event."""
    return [
        c.args[0]
        for c in connection.execute.await_args_list
        if isinstance(c.args[0], Insert)
        and c.args[0].table.name == "intake_outbox"
        and c.args[0].compile().params["event_type"] == EVENT_INTAKE_DOCTOR_ASSIGNED
    ]


# ---------------------------------------------------------------------------
# pick_doctor: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_doctor_writes_assignment_and_grants_consent_atomically() -> None:
    """The pick and ALL THREE consent grants are recorded in one transaction."""
    consultations_grant = _consent_view(consent_id=55, record_scope="consultations")
    prescriptions_grant = _consent_view(
        consent_id=56,
        lineage_ref="consent/patient-7/doctor-909/56",
        record_scope="prescriptions",
    )
    health_background_grant = _consent_view(
        consent_id=57,
        lineage_ref="consent/patient-7/doctor-909/57",
        record_scope="health_background",
    )
    consent_facade = AsyncMock()
    consent_facade.grant_consent_on.side_effect = [
        consultations_grant,
        prescriptions_grant,
        health_background_grant,
    ]

    # 1. SELECT FOR UPDATE → intake row (unassigned)
    # 2. UPDATE → set assigned_partner_id
    # 3. INSERT → intake_outbox (the care-attribution event)
    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=None)),
            _FakeResult(row=None),
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
    # the scope the pick itself serves - never the widened set.
    assert result.consent_id == 55
    assert result.consent_lineage_ref == "consent/patient-7/doctor-909/55"
    assert result.consent_version == 1

    # All three scopes are minted on the SAME connection, in scope order,
    # inside the single transaction (consent-at-pick, #480, widened #663).
    assert consent_facade.grant_consent_on.await_args_list == [
        call(connection, 7, "doctor", "909", "consultations"),
        call(connection, 7, "doctor", "909", "prescriptions"),
        call(connection, 7, "doctor", "909", "health_background"),
    ]
    # All three grants land before the transaction exits (commits) cleanly.
    assert engine.begin.return_value.__aexit__.call_args.args[0] is None

    # All three scopes are flushed from the gate cache after the commit.
    assert consent_facade.invalidate_consent_cache.await_args_list == [
        call(7, "doctor", "909", "consultations"),
        call(7, "doctor", "909", "prescriptions"),
        call(7, "doctor", "909", "health_background"),
    ]


@pytest.mark.asyncio
async def test_pick_doctor_publishes_the_care_attribution_event_in_the_pick_transaction() -> None:
    """The pick rides an event, not a join (B4d, #720; #717 decision 3).

    The outbox insert names the intake, the patient and the doctor on the SAME
    connection, inside the SAME transaction as the assignment and the grants, so
    attribution exists only because the event said so and never because any
    module read the care or partner schema (ADR-0003). Asserting the row rather
    than the row-``event_id`` is deliberate: replay safety downstream is the
    consumer's ledger, and the producer's guarantee here is exactly-once per
    intake (a second pick is refused, proven below).
    """
    consent_facade = AsyncMock()
    consent_facade.grant_consent_on.return_value = _consent_view()

    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=None)),
            _FakeResult(row=None),
            _FakeResult(row=None),
        ]
    )
    engine = _engine(connection)
    facade = IntakeFacade(engine=engine)
    facade._consent_facade = consent_facade

    await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)

    writes = _doctor_assigned_writes(connection)
    assert len(writes) == 1
    values = writes[0].compile().params
    # A pending outbox row like every other published event - the dispatcher
    # owns the status transition (ADR-0002 S2) - carrying the ``event_id`` a
    # consumer dedupes on, so redelivering this row changes nothing downstream.
    assert values["status"] == "pending"
    assert UUID(str(values["event_id"]))
    payload = IntakeDoctorAssignedPayload.model_validate(values["payload"])
    assert payload.intake_id == 1
    assert payload.patient_id == 7
    # The doctor reference is the same identity the assignment wrote and the
    # consent grant addressed - one pick, one doctor, one reference.
    assert payload.doctor_id == 909
    # It committed with the pick: the transaction exited cleanly.
    assert engine.begin.return_value.__aexit__.call_args.args[0] is None


@pytest.mark.asyncio
async def test_pick_doctor_attribution_event_does_not_outlive_a_failed_pick() -> None:
    """An aborted pick leaves no attribution edge behind.

    The event is written INSIDE the transaction, so a grant-leg failure rolls it
    back with the assignment. Publishing after the commit would describe a pick
    that never happened - the bug this seam exists to prevent.
    """
    consent_facade = AsyncMock()
    consent_facade.grant_consent_on.side_effect = [
        _consent_view(),
        RuntimeError("grant failed"),
    ]

    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=None)),
            _FakeResult(row=None),
            _FakeResult(row=None),
        ]
    )
    engine = _engine(connection)
    facade = IntakeFacade(engine=engine)
    facade._consent_facade = consent_facade

    with pytest.raises(RuntimeError, match="grant failed"):
        await facade.pick_doctor(intake_id=1, patient_id=7, partner_id=909)

    # The insert was attempted on the open connection, and that same connection
    # exited with the exception - so the edge cannot have committed.
    assert len(_doctor_assigned_writes(connection)) == 1
    assert engine.begin.return_value.__aexit__.call_args.args[0] is RuntimeError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failing_scope",
    ["consultations", "prescriptions", "health_background"],
)
async def test_pick_doctor_grant_failure_aborts_pick(failing_scope: str) -> None:
    """A failing grant leg rolls the whole pick back - all three or none.

    Exercises every leg: the consultations grant failing first, the
    prescriptions grant failing second, the health_background grant failing
    third.
    """
    scopes = ("consultations", "prescriptions", "health_background")
    failing_leg = scopes.index(failing_scope)
    consent = _consent_view()
    failure = RuntimeError("grant failed")
    consent_facade = AsyncMock()
    consent_facade.grant_consent_on.side_effect = [
        *(consent for _ in range(failing_leg)),
        failure,
    ]

    connection = _connection(
        [
            _FakeResult(row=_intake_row(assigned_partner_id=None)),
            _FakeResult(row=None),
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
    assert consent_facade.grant_consent_on.await_count == failing_leg + 1
    assert consent_facade.grant_consent_on.await_args_list[-1].args[4] == failing_scope
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
    # Cache invalidated once per granted scope (consultations, prescriptions,
    # health_background).
    assert len(grant_idxs) == 3
    assert len(invalidate_idxs) == 3


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
    # A refused pick publishes no attribution edge: exactly one pick exists per
    # intake, so the pairing can never be re-announced for a second doctor.
    assert _doctor_assigned_writes(connection) == []


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
