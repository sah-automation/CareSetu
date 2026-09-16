"""PHASE-8.1 T07: IntakeFacade list_review_queue seam (ticket #447).

Drives the list_review_queue facade through a mocked engine at the
facade-with-fakes seam:

- Returns only draft-state pre-summaries assigned to the calling doctor
  (data minimization, security standards §2).
- Low-confidence pre-summaries surface first (US-12), newest-created first
  within each confidence class.
- Each item carries the low_confidence honesty flag (AMB-006).
- Empty result returns an empty list, never an error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import ReviewQueueItem

NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Fake-result helpers (mirrors test_pick_doctor_facade.py)
# ---------------------------------------------------------------------------


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
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _facade(connection: AsyncMock) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection))


def _queue_row(
    *,
    ps_id: int = 1,
    intake_id: int = 10,
    structuring_confidence: float | None = 0.80,
    low_confidence: bool = False,
    review_state: str = "draft",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=ps_id,
        intake_id=intake_id,
        structuring_confidence=structuring_confidence,
        low_confidence=low_confidence,
        review_state=review_state,
        created_at=created_at or NOW,
        updated_at=updated_at or NOW,
    )


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    """All SQLAlchemy statement objects executed on the connection."""
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


# ---------------------------------------------------------------------------
# list_review_queue: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_review_queue_returns_review_queue_items() -> None:
    rows = [
        _queue_row(ps_id=2, intake_id=20, low_confidence=True, structuring_confidence=0.55),
        _queue_row(ps_id=1, intake_id=10, low_confidence=False, structuring_confidence=0.82),
    ]
    connection = _connection([_FakeResult(rows=rows)])
    facade = _facade(connection)

    results = await facade.list_review_queue(doctor_id=42)

    assert len(results) == 2
    assert all(isinstance(r, ReviewQueueItem) for r in results)
    assert results[0].pre_summary_id == 2
    assert results[0].intake_id == 20
    assert results[0].low_confidence is True
    assert results[0].structuring_confidence == 0.55
    assert results[1].pre_summary_id == 1
    assert results[1].low_confidence is False
    assert results[1].structuring_confidence == 0.82


@pytest.mark.asyncio
async def test_list_review_queue_empty_when_no_rows() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _facade(connection)

    results = await facade.list_review_queue(doctor_id=42)

    assert results == []


# ---------------------------------------------------------------------------
# list_review_queue: SQL shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_review_queue_uses_doctor_filter_and_low_confidence_first() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _facade(connection)

    await facade.list_review_queue(doctor_id=42)

    stmts = _statements(connection)
    select_stmt = stmts[0]
    compiled_sql = str(select_stmt.compile()).upper()
    compiled_params = dict(select_stmt.compile().params)

    assert 42 in compiled_params.values()
    assert "draft" in compiled_params.values()
    assert "ORDER BY" in compiled_sql
    assert "CASE" in compiled_sql
    assert "INTAKE_INTAKES" in compiled_sql


@pytest.mark.asyncio
async def test_list_review_queue_joins_assigned_partner_and_filters_draft() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _facade(connection)

    await facade.list_review_queue(doctor_id=99)

    stmts = _statements(connection)
    select_stmt = stmts[0]
    compiled = str(select_stmt.compile())
    params = dict(select_stmt.compile().params)

    assert "intake_intakes" in compiled
    assert "intake_pre_summaries" in compiled
    assert 99 in params.values()
    assert "draft" in params.values()
