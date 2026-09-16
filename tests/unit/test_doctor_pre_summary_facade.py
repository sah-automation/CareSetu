"""PHASE-8.1 T08: IntakeFacade get_doctor_pre_summary seam (ticket #448, FEAT-008).

Drives the get_doctor_pre_summary facade through a mocked engine at the
facade-with-fakes seam:

- Returns the FULL pre-summary content (structured summary, symptoms,
  confidence flag, review state, edits and review attribution) for the doctor
  to whom the intake is assigned (US-13).
- Unassigned doctors match no row and are refused with IntakeNotFoundError
  (data minimization, security standards §2) - never revealing the intake.
- The SQL predicates the intake's ``assigned_partner_id`` against the calling
  doctor, the same scoping seam as the review queue (#447) and media reads
  (#443).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.intake.domain.exceptions import IntakeNotFoundError
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import PreSummaryView

NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Fake-result helpers (mirrors test_doctor_review_queue_facade.py)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Mimics asyncpg ``CursorResult`` shapes used by the facade."""

    def __init__(self, row: object | None = None) -> None:
        self._row = row

    def scalar_one(self) -> object:
        return self._row  # type: ignore[return-value]

    def first(self) -> object:
        return self._row


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


def _pre_summary_row(
    *,
    ps_id: int = 101,
    intake_id: int = 42,
    structured_fields: dict | None = None,
    structuring_confidence: float | None = 0.55,
    low_confidence: bool = True,
    review_state: str = "draft",
    patient_edits: dict | None = None,
    doctor_corrections: dict | None = None,
    review_attribution: str | None = None,
    reviewed_by: int | None = None,
    reviewed_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=ps_id,
        intake_id=intake_id,
        structured_fields=structured_fields
        or {
            "chief_complaints": ["headache"],
            "symptoms": ["throbbing in the temples"],
            "duration": "3 days",
        },
        structuring_confidence=structuring_confidence,
        low_confidence=low_confidence,
        review_state=review_state,
        patient_edits=patient_edits,
        doctor_corrections=doctor_corrections,
        review_attribution=review_attribution,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        created_at=NOW,
        updated_at=NOW,
    )


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    """All SQLAlchemy statement objects executed on the connection."""
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


# ---------------------------------------------------------------------------
# get_doctor_pre_summary: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_doctor_pre_summary_returns_full_content() -> None:
    row = _pre_summary_row()
    connection = _connection([_FakeResult(row=row)])
    facade = _facade(connection)

    result = await facade.get_doctor_pre_summary(intake_id=42, doctor_id=12)

    assert isinstance(result, PreSummaryView)
    assert result.pre_summary_id == 101
    assert result.intake_id == 42
    assert result.structured_fields.chief_complaints == ["headache"]
    assert result.structured_fields.symptoms == ["throbbing in the temples"]
    assert result.structured_fields.duration == "3 days"
    assert result.structuring_confidence == 0.55
    assert result.low_confidence is True
    assert result.review_state == "draft"


@pytest.mark.asyncio
async def test_get_doctor_pre_summary_returns_review_attribution_and_edits() -> None:
    reviewed_at = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    row = _pre_summary_row(
        review_state="final",
        structuring_confidence=0.88,
        low_confidence=False,
        patient_edits={"duration": "two days"},
        doctor_corrections={"duration": "3 days"},
        review_attribution="doctor",
        reviewed_by=12,
        reviewed_at=reviewed_at,
    )
    connection = _connection([_FakeResult(row=row)])
    facade = _facade(connection)

    result = await facade.get_doctor_pre_summary(intake_id=42, doctor_id=12)

    assert result.review_state == "final"
    assert result.structuring_confidence == 0.88
    assert result.low_confidence is False
    assert result.patient_edits == {"duration": "two days"}
    assert result.doctor_corrections == {"duration": "3 days"}
    assert result.review_attribution == "doctor"
    assert result.reviewed_by == 12
    assert result.reviewed_at == reviewed_at


# ---------------------------------------------------------------------------
# get_doctor_pre_summary: assignment scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_doctor_pre_summary_refuses_when_no_assigned_row() -> None:
    connection = _connection([_FakeResult(row=None)])
    facade = _facade(connection)

    with pytest.raises(IntakeNotFoundError, match="pre-summary not found"):
        await facade.get_doctor_pre_summary(intake_id=42, doctor_id=12)


# ---------------------------------------------------------------------------
# get_doctor_pre_summary: SQL shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_doctor_pre_summary_joins_and_scopes_to_assigned_doctor() -> None:
    connection = _connection([_FakeResult(row=_pre_summary_row())])
    facade = _facade(connection)

    await facade.get_doctor_pre_summary(intake_id=42, doctor_id=99)

    stmts = _statements(connection)
    select_stmt = stmts[0]
    compiled = str(select_stmt.compile())
    params = dict(select_stmt.compile().params)

    # The predicate binds the calling doctor to the intake's ASSIGNED partner
    # (never the intake id, never an unbound filter) and the requested intake
    # id to the PRE-SUMMARY's intake column - a swapped/missing predicate would
    # leak or cross-scope an intake assigned to a different doctor (AC-2).
    assert "intake.intake_intakes.id = intake.intake_pre_summaries.intake_id" in compiled
    assert "intake.intake_intakes.assigned_partner_id = :assigned_partner_id_1" in compiled
    assert "intake.intake_pre_summaries.intake_id = :intake_id_1" in compiled
    assert int(params["assigned_partner_id_1"]) == 99
    assert int(params["intake_id_1"]) == 42
