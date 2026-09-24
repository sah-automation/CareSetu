"""PHASE-8.2 T01: HealthFacade log_doctor_patient_view access-log seam (#539).

MOD-012 owns no ledger or outbox, so the doctor console delegates its "every
read attempt" bookkeeping to the health module's record access history. This
suite drives the seam through a mocked engine, mirroring
``test_record_access_events.py``:

- The patient's record shell is resolved (lazily ensured) and an allowed
  doctor access lands in the access-history ledger in the same transaction
  as the outbox ``record.accessed`` envelope.
- The ledger row marks the doctor as actor and the list surface as scope, so
  the patient's access view says who viewed a row and from where.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.health.facade import HealthFacade

# ---------------------------------------------------------------------------
# Fake-result helpers (mirrors test_doctor_review_queue_facade.py)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Mimics asyncpg ``CursorResult`` shapes used by the facade."""

    def __init__(self, scalar: object | None = None) -> None:
        self._scalar = scalar

    def scalar_one(self) -> object:
        return self._scalar


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _facade(connection: AsyncMock) -> HealthFacade:
    return HealthFacade(engine=_engine(connection))


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


# ---------------------------------------------------------------------------
# log_doctor_patient_view
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_doctor_patient_view_writes_ledger_and_outbox_envelope() -> None:
    # Statement order: ensure-shell insert, record-id select, history insert,
    # outbox insert.
    connection = _connection([_FakeResult(), _FakeResult(scalar=77), _FakeResult(), _FakeResult()])
    facade = _facade(connection)

    await facade.log_doctor_patient_view(patient_id=10, doctor_id=42)

    connection.execute.assert_awaited()
    stmts = _statements(connection)
    assert len(stmts) == 4

    shell_insert = str(stmts[0].compile())
    record_select = stmts[1].compile()
    history_insert = stmts[2].compile()
    outbox_insert = stmts[3].compile()

    assert "health_patient_records" in shell_insert
    assert 10 in dict(record_select.params).values()

    history_params = dict(history_insert.params)
    assert "health_record_access_history" in str(history_insert)
    assert history_params["record_id"] == 77
    assert history_params["accessor_identity_id"] == 42
    assert history_params["outcome"] == "allowed"
    assert history_params["actor_type"] == "doctor"
    assert history_params["scope"] == "doctor_patients_list"

    outbox_params = dict(outbox_insert.params)
    assert "health_outbox" in str(outbox_insert)
    assert outbox_params["event_type"] == "record.accessed"
    assert outbox_params["status"] == "pending"


@pytest.mark.asyncio
async def test_log_doctor_patient_view_returns_none() -> None:
    connection = _connection([_FakeResult(), _FakeResult(scalar=77), _FakeResult(), _FakeResult()])
    facade = _facade(connection)

    result = await facade.log_doctor_patient_view(patient_id=10, doctor_id=42)

    assert result is None
