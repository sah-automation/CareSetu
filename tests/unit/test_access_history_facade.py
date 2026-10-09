"""PHASE-4 T7: the patient access-history query (ticket #241, FEAT-003).

Pins the ``query_access_history`` SELECT against a mocked connection - the
patient-record filter, the both-columns self-row exclusion predicate (#665),
newest-first ordering, and the mapping of each ledger row to an
``AccessHistoryEntry`` (denied concretized from ``outcome``, plus the
composition-root-resolved ``actor_display_name`` #668) - plus the two
facade delegation seams: ``HealthFacade.get_access_history`` through its
engine and ``AuditFacade.get_access_history`` through the MOD-003 facade
(coding-standards A2: DB-free unit surface, module isolation rule).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.audit.facade import AuditFacade
from modules.health.facade import AccessHistoryView, HealthFacade, query_access_history

_NOW = datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC)


class _FakeResult:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self):
        return self._rows


def _connection(rows: list[SimpleNamespace] | None = None) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(return_value=_FakeResult(rows if rows is not None else []))
    return connection


def _row(**fields: object) -> SimpleNamespace:
    defaults = {
        "accessor_identity_id": 7,
        "actor_type": "patient",
        "scope": "full_record",
        "accessed_at": _NOW,
        "outcome": "allowed",
        "denial_reason": None,
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


class _RecordingResolver:
    """A resolver that answers a fixed name and records what it was asked."""

    def __init__(self, name: str | None = "Sunrise Clinic") -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, actor_type: str, actor_id: str) -> str | None:
        self.calls.append((actor_type, actor_id))
        return self.name


class _FailingResolver:
    async def __call__(self, actor_type: str, actor_id: str) -> str | None:
        raise RuntimeError(f"partner seam unavailable for {actor_id}")


async def test_maps_each_ledger_row_to_an_access_history_entry() -> None:
    connection = _connection(
        [
            _row(outcome="denied", denial_reason="consent check failed"),
            _row(outcome="allowed"),
            _row(
                accessor_identity_id=3,
                actor_type="doctor",
                scope="doctor_patients_list",
            ),
        ]
    )

    view = await query_access_history(connection, patient_id=7)

    denied, allowed, doctor = view.entries
    assert allowed.actor_id == 7
    assert allowed.actor_type == "patient"
    # Unbound seam: the key is still present and null, never missing - the
    # frontend's fallback chain depends on it (#668, story 23).
    assert allowed.actor_display_name is None
    assert allowed.scope == "full_record"
    assert allowed.accessed_at == _NOW
    assert allowed.denied is False
    assert allowed.denial_reason is None
    assert denied.denied is True
    assert denied.denial_reason == "consent check failed"
    assert denied.actor_display_name is None
    assert doctor.actor_id == 3
    assert doctor.actor_type == "doctor"
    assert doctor.actor_display_name is None
    assert doctor.scope == "doctor_patients_list"
    assert doctor.denied is False


async def test_a_bound_resolver_maps_the_display_name_onto_counterparty_rows() -> None:
    resolver = _RecordingResolver()
    connection = _connection(
        [
            _row(accessor_identity_id=3, actor_type="doctor"),
            _row(accessor_identity_id=5, actor_type="lab"),
        ]
    )

    view = await query_access_history(connection, patient_id=7, display_name=resolver)

    doctor, lab = view.entries
    assert doctor.actor_display_name == "Sunrise Clinic"
    assert lab.actor_display_name == "Sunrise Clinic"
    # The id arrives at the seam as a string beside the row's actor type.
    assert resolver.calls == [("doctor", "3"), ("lab", "5")]


async def test_patient_type_rows_never_reach_the_display_name_resolver() -> None:
    """#668 (stories 21-22): a cross-patient denied row must not name a person.

    Patient-type actors are refused BEFORE the seam - another identity's
    refused attempt stays listed, but resolving its id could disclose a
    second patient's identity on the record owner's behalf.
    """
    resolver = _RecordingResolver()
    connection = _connection(
        [
            _row(
                accessor_identity_id=999,
                actor_type="patient",
                outcome="denied",
                denial_reason="only the record owner may read this record",
            )
        ]
    )

    view = await query_access_history(connection, patient_id=7, display_name=resolver)

    (entry,) = view.entries
    assert entry.denied is True
    assert entry.actor_display_name is None
    assert resolver.calls == []


async def test_an_unresolvable_counterparty_stays_null() -> None:
    resolver = _RecordingResolver(None)
    connection = _connection([_row(accessor_identity_id=3, actor_type="doctor")])

    view = await query_access_history(connection, patient_id=7, display_name=resolver)

    (entry,) = view.entries
    assert entry.actor_id == 3
    assert entry.actor_display_name is None


async def test_a_raising_resolver_degrades_to_null_with_a_type_only_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The facade seam swallows the failure: the trust view loads, nameless."""
    connection = _connection([_row(accessor_identity_id=3, actor_type="doctor")])
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    facade = HealthFacade(engine, counterparty_display_name_resolver=_FailingResolver())
    with caplog.at_level(logging.WARNING, logger="modules.health.facade"):
        view = await facade.get_access_history(7)

    (entry,) = view.entries
    assert entry.actor_id == 3
    assert entry.actor_display_name is None
    warnings = [
        record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "doctor" in warnings[0]
    # The actor id and the exception payload stay out of the log line.
    assert "3" not in warnings[0]
    assert "RuntimeError" not in warnings[0]
    assert "partner seam unavailable" not in warnings[0]


async def test_filters_to_the_patients_own_record_only() -> None:
    connection = _connection([])

    await query_access_history(connection, patient_id=7)

    (select_stmt,) = connection.execute.await_args.args
    sql = str(select_stmt)
    # The join resolves the patient's record shell; the WHERE binds the patient.
    assert "health_record_access_history JOIN health.health_patient_records" in sql
    assert "health_patient_records.identity_id" in sql


async def test_excludes_self_rows_with_the_both_columns_predicate() -> None:
    """#665: self rows are excluded on BOTH actor type and accessor identity.

    The predicate keys on both columns because doctor rows store partner ids
    in the same accessor column - a bare accessor comparison would mis-handle
    id-namespace collisions between a patient id and a partner id.
    """
    connection = _connection([])

    await query_access_history(connection, patient_id=7)

    (select_stmt,) = connection.execute.await_args.args
    sql = str(select_stmt)
    assert "NOT (" in sql
    assert "health_record_access_history.actor_type" in sql
    assert "accessor_identity_id = health.health_patient_records.identity_id" in sql


async def test_orders_entries_most_recent_first() -> None:
    connection = _connection([])

    await query_access_history(connection, patient_id=7)

    (select_stmt,) = connection.execute.await_args.args
    sql = str(select_stmt)
    assert "health_record_access_history.accessed_at DESC" in sql
    assert "health_record_access_history.id DESC" in sql


async def test_empty_history_returns_an_empty_list_not_an_error() -> None:
    connection = _connection([])

    view = await query_access_history(connection, patient_id=7)

    assert isinstance(view, AccessHistoryView)
    assert view.entries == []


async def test_health_facade_get_access_history_delegates_through_its_engine() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(return_value=_FakeResult([_row()]))
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

    facade = HealthFacade(engine)
    view = await facade.get_access_history(7)

    assert len(view.entries) == 1
    assert view.entries[0].actor_id == 7
    # Engine-only construction: the seam is unbound, the key stays null.
    assert view.entries[0].actor_display_name is None


class StubHealthFacade:
    def __init__(self) -> None:
        self.patient_ids: list[int] = []
        self.view: AccessHistoryView = AccessHistoryView(entries=[])

    async def get_access_history(self, patient_id: int) -> AccessHistoryView:
        self.patient_ids.append(patient_id)
        return self.view


async def test_audit_facade_delegates_to_the_health_facade() -> None:
    health = StubHealthFacade()
    facade = AuditFacade(engine=MagicMock(), health_facade=health)

    view = await facade.get_access_history(7)

    assert health.patient_ids == [7]
    assert view == health.view


async def test_audit_facade_requires_the_health_facade_to_be_configured() -> None:
    facade = AuditFacade(engine=MagicMock())

    try:
        await facade.get_access_history(7)
    except RuntimeError as exc:
        assert "HealthFacade" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for an unconfigured HealthFacade")
