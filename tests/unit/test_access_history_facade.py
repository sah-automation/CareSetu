"""PHASE-4 T7: the patient access-history query (ticket #241, FEAT-003).

Pins the ``query_access_history`` SELECT against a mocked connection - the
patient-record filter, newest-first ordering, and the mapping of each ledger
row to an ``AccessHistoryEntry`` (denied concretized from ``outcome``) - plus
the two facade delegation seams: ``HealthFacade.get_access_history`` through
its engine and ``AuditFacade.get_access_history`` through the MOD-003 facade
(coding-standards A2: DB-free unit surface, module isolation rule).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


async def test_maps_each_ledger_row_to_an_access_history_entry() -> None:
    connection = _connection(
        [
            _row(outcome="denied", denial_reason="consent check failed"),
            _row(outcome="allowed"),
        ]
    )

    view = await query_access_history(connection, patient_id=7)

    denied, allowed = view.entries
    assert allowed.actor_id == 7
    assert allowed.actor_type == "patient"
    assert allowed.scope == "full_record"
    assert allowed.accessed_at == _NOW
    assert allowed.denied is False
    assert allowed.denial_reason is None
    assert denied.denied is True
    assert denied.denial_reason == "consent check failed"


async def test_filters_to_the_patients_own_record_only() -> None:
    connection = _connection([])

    await query_access_history(connection, patient_id=7)

    (select_stmt,) = connection.execute.await_args.args
    sql = str(select_stmt)
    # The join resolves the patient's record shell; the WHERE binds the patient.
    assert "health_record_access_history JOIN health.health_patient_records" in sql
    assert "health_patient_records.identity_id" in sql


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
