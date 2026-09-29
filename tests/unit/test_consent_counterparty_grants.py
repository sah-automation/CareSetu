"""PHASE-8.2 T01: ConsentFacade list_counterparty_grants reverse lookup (#539).

Fixes the ADR-0019 read source for the doctor console: which patients
currently grant this counterparty read access. Drives the new seam through a
mocked engine at the facade-with-fakes seam:

- Returns only ``granted``-status lineages for the counterparty type+id.
- Revoked/declined/pending lineages are excluded (a standing grant only).
- Thinned to the fields the Patients list derivation consumes (consent_id,
  patient_id, record_scope, version), sorted by patient for stable fan-out.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.consent.facade import ConsentFacade, CounterpartyGrantView

# ---------------------------------------------------------------------------
# Fake-result helpers (mirrors test_doctor_review_queue_facade.py)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Mimics asyncpg ``CursorResult`` shapes used by the facade."""

    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = rows or []

    def all(self) -> list:
        return self._rows


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _facade(connection: AsyncMock) -> ConsentFacade:
    return ConsentFacade(engine=_engine(connection))


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


def _grant_row(
    *,
    consent_id: int = 1,
    patient_id: int = 10,
    record_scope: str = "full_record",
    version: int = 1,
) -> object:
    return SimpleNamespace(
        id=consent_id,
        patient_id=patient_id,
        record_scope=record_scope,
        version=version,
    )


# ---------------------------------------------------------------------------
# list_counterparty_grants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_counterparty_grants_returns_granted_grants_only() -> None:
    connection = _connection(
        [
            _FakeResult(
                rows=[
                    _grant_row(consent_id=1, patient_id=10),
                    _grant_row(consent_id=2, patient_id=11, record_scope="health_background"),
                    _grant_row(
                        consent_id=3, patient_id=12, record_scope="consultations", version=2
                    ),
                ]
            )
        ]
    )
    facade = _facade(connection)

    grants = await facade.list_counterparty_grants(counterparty_type="doctor", counterparty_id="42")

    assert len(grants) == 3
    assert all(isinstance(g, CounterpartyGrantView) for g in grants)
    first = grants[0]
    assert first.consent_id == 1
    assert first.patient_id == 10
    assert first.record_scope == "full_record"
    assert first.version == 1
    assert grants[1].record_scope == "health_background"
    assert grants[2].version == 2


@pytest.mark.asyncio
async def test_list_counterparty_grants_filters_by_counterparty_and_granted() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _facade(connection)

    await facade.list_counterparty_grants(counterparty_type="doctor", counterparty_id="42")

    stmt = _statements(connection)[0]
    compiled = str(stmt.compile())
    params = dict(stmt.compile().params)

    assert "consent_consents" in compiled
    values = set(params.values())
    assert "doctor" in values
    assert "42" in values
    assert "granted" in values


@pytest.mark.asyncio
async def test_list_counterparty_grants_empty_when_no_grants() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _facade(connection)

    grants = await facade.list_counterparty_grants(counterparty_type="lab", counterparty_id="7")

    assert grants == []
