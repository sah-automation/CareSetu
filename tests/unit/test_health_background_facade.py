"""Ticket #534: the health-background snapshot save/read facade.

Pins the first-save acknowledgement gate, the auto-grant to live-relationship
doctors (ADR-0018) inside the SAME transaction as the snapshot upsert, and the
no-regrant/never-reprompt later-edit convergence - against a mocked transaction
and stub consent/care facades (coding-standards A2: DB-free unit surface,
module isolation rule; the grant cache is invalidated only after commit).

Also pins the MOD-006 seam the discovery depends on:
``CaseConsoleFacade.list_open_case_doctor_ids`` resolves a patient's open-case
doctors - claimed via ``care_cases.doctor_id`` and born-but-unclaimed via the
intake pre-summary assignment seam.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from modules.care.case_facade import CaseConsoleFacade
from modules.health.domain.exceptions import HealthBackgroundAcknowledgmentRequiredError
from modules.health.facade import HealthBackground, HealthFacade

_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)

_BACKGROUND = HealthBackground(
    blood_group="B+",
    conditions=["diabetes"],
    allergies=["penicillin"],
    medications=["metformin"],
    immunizations=["COVID-19"],
    family_history=["mother: hypertension"],
)


class _FakeResult:
    """One execute reply: first() for singleton reads, all() for row sets."""

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def first(self) -> SimpleNamespace | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[SimpleNamespace]:
        return self._rows


def _scalar_only() -> MagicMock:
    return MagicMock()


def _engine(connection: AsyncMock) -> MagicMock:
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _snapshot_row() -> SimpleNamespace:
    return SimpleNamespace(
        acknowledged_at=_NOW,
        blood_group="B+",
        conditions=["diabetes"],
        allergies=["penicillin"],
        medications=["metformin"],
        immunizations=["COVID-19"],
        family_history=["mother: hypertension"],
    )


class StubConsentFacade:
    def __init__(self, *, consents: list[SimpleNamespace] | None = None) -> None:
        self._consents = consents if consents is not None else []
        self.grants: list[tuple[object, int, str, str, str]] = []
        self.invalidations: list[tuple[int, str, str, str]] = []
        self.list_consent_calls: list[int] = []

    async def list_consents(self, patient_id: int) -> SimpleNamespace:
        self.list_consent_calls.append(patient_id)
        return SimpleNamespace(items=self._consents)

    async def grant_consent_on(
        self,
        connection: object,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
    ) -> None:
        self.grants.append(
            (connection, patient_id, counterparty_type, counterparty_id, record_scope)
        )

    async def invalidate_consent_cache(
        self,
        patient_id: int,
        counterparty_type: str,
        counterparty_id: str,
        record_scope: str,
    ) -> None:
        self.invalidations.append((patient_id, counterparty_type, counterparty_id, record_scope))


class StubCareFacade:
    def __init__(self, *, doctor_ids: set[int] | None = None) -> None:
        self._doctor_ids = doctor_ids if doctor_ids is not None else set()

    async def list_open_case_doctor_ids(self, *, patient_id: int) -> set[int]:
        assert patient_id == 7
        return self._doctor_ids


def _consent(counterparty_type: str, counterparty_id: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(
        counterparty_type=counterparty_type,
        counterparty_id=counterparty_id,
        status=status,
    )


@staticmethod
def _compiled(stmt: object) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


async def test_first_save_without_acknowledgement_raises_before_any_write() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[_FakeResult([])])
    consent = StubConsentFacade()
    care = StubCareFacade()
    facade = HealthFacade(_engine(connection), consent_facade=consent, care_facade=care)

    with pytest.raises(HealthBackgroundAcknowledgmentRequiredError):
        await facade.save_health_background(7, _BACKGROUND, acknowledge_phi=False)

    # The guard read fired, but nothing was persisted nor granted.
    assert connection.execute.await_count == 1
    assert consent.grants == []
    assert consent.invalidations == []
    assert consent.list_consent_calls == []


async def test_acknowledged_first_save_auto_grants_live_relationship_doctors() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[_FakeResult([]), _scalar_only()])
    consent = StubConsentFacade(
        consents=[
            _consent("doctor", "11", "granted"),
            _consent("doctor", "22", "granted"),
            _consent("doctor", "33", "revoked"),
            _consent("doctor", "intake-ai", "granted"),
            _consent("chemist", "44", "granted"),
        ]
    )
    care = StubCareFacade(doctor_ids={55})
    facade = HealthFacade(_engine(connection), consent_facade=consent, care_facade=care)

    view = await facade.save_health_background(7, _BACKGROUND, acknowledge_phi=True)

    assert view.set is True
    assert view.acknowledged is True
    assert view.background == _BACKGROUND
    # Live relationships = granted doctor grants {11, 22, intake-ai} UNION
    # open-case doctor {55}; the revoked doctor and the chemist are excluded.
    # Grants run IN the transaction, on the same connection, in sorted-id order
    # (each grant is independently idempotent, so the order carries no meaning
    # beyond a deterministic replay).
    _, upsert_stmt = [call.args[0] for call in connection.execute.await_args_list]
    assert consent.grants == [
        (connection, 7, "doctor", "11", "health_background"),
        (connection, 7, "doctor", "22", "health_background"),
        (connection, 7, "doctor", "55", "health_background"),
        (connection, 7, "doctor", "intake-ai", "health_background"),
    ]
    # Cache invalidation lands only after the commit.
    assert consent.invalidations == [
        (7, "doctor", "11", "health_background"),
        (7, "doctor", "22", "health_background"),
        (7, "doctor", "55", "health_background"),
        (7, "doctor", "intake-ai", "health_background"),
    ]
    # The snapshot upsert stamps acknowledged_at on the first save and never
    # overwrites it on conflict (see the later-edit test).
    sql = _compiled(upsert_stmt)
    assert "INSERT INTO health.health_background_snapshots" in sql
    assert "ON CONFLICT (identity_id) DO UPDATE" in sql
    assert "acknowledged_at" in sql


async def test_first_save_grants_non_numeric_counterparty_ids_unchanged() -> None:
    """Discovery carries each counterparty id through to the grant VERBATIM (#554).

    ``FEAT-002`` / ADR-0018. The consent lineage stores ``counterparty_id`` as a
    Text column, so a granted ``doctor`` namespace carries OPAQUE ids, not
    numbers: ``intake-ai`` (the AI egress pseudo-counterparty, whose own grant
    satisfies the intake consent gate) is a live one, and nothing about the
    column stops ``007`` either. Re-deriving an id breaks the grant two ways, and
    this fixture pins both: an id that cannot be coerced RAISES, answering the
    acknowledged first save with a 500 the client cannot re-ask on, and an id
    that coerces to a DIFFERENT string (``007`` -> ``7``) would write the grant
    onto a re-derived lineage triple that no doctor read ever matches - written,
    and inert. Both must land on the DISCOVERED triple instead.
    """
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[_FakeResult([]), _scalar_only()])
    consent = StubConsentFacade(
        consents=[
            _consent("doctor", "intake-ai", "granted"),
            _consent("doctor", "007", "granted"),
        ]
    )
    care = StubCareFacade(doctor_ids={77})
    facade = HealthFacade(_engine(connection), consent_facade=consent, care_facade=care)

    view = await facade.save_health_background(7, _BACKGROUND, acknowledge_phi=True)

    assert view.set is True and view.acknowledged is True
    # Exactly the discovered lineage triples: the opaque id verbatim, the
    # zero-padded id NOT normalised to ``7``, the open-case doctor id stringified
    # into the same ``doctor`` namespace - nothing re-derived, nothing dropped.
    assert consent.grants == [
        (connection, 7, "doctor", "007", "health_background"),
        (connection, 7, "doctor", "77", "health_background"),
        (connection, 7, "doctor", "intake-ai", "health_background"),
    ]
    assert consent.invalidations == [
        (7, "doctor", "007", "health_background"),
        (7, "doctor", "77", "health_background"),
        (7, "doctor", "intake-ai", "health_background"),
    ]


async def test_first_save_with_no_live_doctors_grants_nothing() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[_FakeResult([]), _scalar_only()])
    consent = StubConsentFacade()
    care = StubCareFacade(doctor_ids=set())
    facade = HealthFacade(_engine(connection), consent_facade=consent, care_facade=care)

    view = await facade.save_health_background(7, _BACKGROUND, acknowledge_phi=True)

    assert view.set is True and view.acknowledged is True
    assert consent.grants == []
    assert consent.invalidations == []


async def test_later_edit_never_regrants_or_reprompts() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[_FakeResult([_snapshot_row()]), _scalar_only()])
    consent = StubConsentFacade()
    care = StubCareFacade(doctor_ids={55})
    facade = HealthFacade(_engine(connection), consent_facade=consent, care_facade=care)

    view = await facade.save_health_background(7, _BACKGROUND, acknowledge_phi=False)

    assert view.set is True and view.acknowledged is True
    # A later edit is accepted without the flag, converges on the one row, and
    # skips doctor discovery, grants, and cache invalidation entirely.
    assert consent.list_consent_calls == []
    assert consent.grants == []
    assert consent.invalidations == []
    _, upsert_stmt = [call.args[0] for call in connection.execute.await_args_list]
    sql = _compiled(upsert_stmt)
    assert "ON CONFLICT (identity_id) DO UPDATE" in sql
    assert "acknowledged_at" not in sql
    assert "updated_at" in sql


async def test_save_answers_the_stored_acknowledgement_not_a_constant() -> None:
    """The answer echoes the row, never a hardcoded ``True`` (#534).

    A first acknowledged save stamps ``acknowledged_at``, so it answers True; a
    later edit answers the stamp already on the row. A row that somehow carries
    no stamp answers False instead of claiming a confirmation that was never
    persisted.
    """
    acknowledged_row = _snapshot_row()
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[_FakeResult([acknowledged_row]), _scalar_only()])
    consent = StubConsentFacade()
    facade = HealthFacade(_engine(connection), consent_facade=consent, care_facade=StubCareFacade())

    view = await facade.save_health_background(7, _BACKGROUND, acknowledge_phi=False)

    assert view.set is True
    assert view.acknowledged is True

    unstamped_row = _snapshot_row()
    unstamped_row.acknowledged_at = None
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[_FakeResult([unstamped_row]), _scalar_only()])
    facade = HealthFacade(
        _engine(connection), consent_facade=StubConsentFacade(), care_facade=StubCareFacade()
    )

    view = await facade.save_health_background(7, _BACKGROUND, acknowledge_phi=False)

    assert view.set is True
    assert view.acknowledged is False


async def test_save_without_configured_facades_raises() -> None:
    facade = HealthFacade(_engine(AsyncMock()))

    with pytest.raises(RuntimeError, match="ConsentFacade not configured"):
        await facade.save_health_background(7, _BACKGROUND, acknowledge_phi=True)


async def test_get_health_background_returns_not_set_when_absent() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(return_value=_FakeResult([]))
    facade = HealthFacade(_engine(connection))

    view = await facade.get_health_background(7)

    assert view.set is False and view.acknowledged is False and view.background is None


async def test_get_health_background_returns_the_stored_snapshot() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(return_value=_FakeResult([_snapshot_row()]))
    facade = HealthFacade(_engine(connection))

    view = await facade.get_health_background(7)

    assert view.set is True and view.acknowledged is True
    assert isinstance(view.background, HealthBackground)
    assert view.background == _BACKGROUND
    (select_stmt,) = connection.execute.await_args.args
    assert "health.health_background_snapshots" in _compiled(select_stmt)
    assert "health_background_snapshots.identity_id" in _compiled(select_stmt)


class StubIntakeFacade:
    def __init__(self, *, assigned: dict[int, int | None]) -> None:
        self._assigned = assigned

    async def assigned_partner_for_pre_summaries(
        self, pre_summary_ids: list[int]
    ) -> dict[int, int | None]:
        return self._assigned


async def test_list_open_case_doctor_ids_combines_claimed_and_unclaimed() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(
        side_effect=[
            _FakeResult([SimpleNamespace(doctor_id=7)]),
            _FakeResult(
                [
                    SimpleNamespace(id=1, pre_summary_id=10),
                    SimpleNamespace(id=2, pre_summary_id=None),
                ]
            ),
        ]
    )
    intake = StubIntakeFacade(assigned={10: 99})
    facade = CaseConsoleFacade(engine=_engine(connection), intake_facade=intake)

    doctor_ids = await facade.list_open_case_doctor_ids(patient_id=7)

    # Claimed case doctor {7} plus the unclaimed born case whose pre-summary is
    # assigned to doctor {99}; the pre_summary-less case resolves to no doctor.
    assert doctor_ids == {7, 99}


async def test_list_open_case_doctor_ids_excludes_unresolved_unclaimed_cases() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(
        side_effect=[
            _FakeResult([]),
            _FakeResult([SimpleNamespace(id=1, pre_summary_id=10)]),
        ]
    )
    intake = StubIntakeFacade(assigned={10: None})
    facade = CaseConsoleFacade(engine=_engine(connection), intake_facade=intake)

    doctor_ids = await facade.list_open_case_doctor_ids(patient_id=7)

    assert doctor_ids == set()
